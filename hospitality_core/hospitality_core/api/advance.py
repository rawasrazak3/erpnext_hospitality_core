"""Advance payments for Hotel Bookings.

An advance is real money: it creates a submitted ERPNext Payment Entry, so the day's cash
reconciles. But it is NOT revenue on the day it is collected — the guest has not stayed
yet. So it lands on the booking folio (a Guest Folio flagged `is_booking_master`) and is
held against the configured advance liability account. Revenue is recognised only when
the advance is applied to a room folio at check-in.

The reuse here is deliberate: the Payment Entry is built the same way
`payment_bridge.create_folio_payment` builds one, and the existing
`payment_bridge.process_payment_entry` hook posts the folio credit. This module adds the
booking-level plumbing, not a second payment system.
"""

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from hospitality_core.hospitality_core.api.folio import sync_folio_balance
from hospitality_core.hospitality_core.api.utils import (
	get_hotel_company,
	get_mop_account,
	get_receivable_account,
)

# Charge codes. ADVANCE-TRANSFER is kept distinct from the pre-existing
# BALANCE-TRANSFER precisely so revenue reports can exclude it by item code — see the
# note in api/folio.py about transfers being counted as revenue.
ITEM_ADVANCE_TRANSFER = "ADVANCE-TRANSFER"


def ensure_item(item_code, item_name):
	if frappe.db.exists("Item", item_code):
		return item_code
	group = "Services" if frappe.db.exists("Item Group", "Services") else "All Item Groups"
	frappe.get_doc({
		"doctype": "Item",
		"item_code": item_code,
		"item_name": item_name,
		"item_group": group,
		"is_stock_item": 0,
	}).insert(ignore_permissions=True)
	return item_code


def resolve_customer(guest):
	"""Guest.validate auto-creates a Customer, but older rows may predate that."""
	customer, full_name = frappe.db.get_value("Guest", guest, ["customer", "full_name"])
	if customer:
		return customer

	doc = frappe.get_doc({
		"doctype": "Customer",
		"customer_name": full_name or guest,
		"customer_type": "Individual",
	})
	doc.insert(ignore_permissions=True)
	frappe.db.set_value("Guest", guest, "customer", doc.name)
	return doc.name


@frappe.whitelist()
def record_advance(booking, amount, mode_of_payment, reference_no=None, posting_date=None):
	"""Take an advance against a booking.

	Creates a submitted Payment Entry against the booking folio. The
	`Payment Entry.on_submit` hook posts the matching credit onto that folio, so the
	folio balance and the accounting stay in step without a second code path.
	"""
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Advance amount must be greater than zero."))

	doc = frappe.get_doc("Hotel Booking", booking)
	doc.check_permission("write")

	if doc.status in ("Cancelled", "Completed"):
		frappe.throw(_("Cannot take an advance on a {0} booking.").format(doc.status))
	if not doc.guest:
		frappe.throw(_("Set a guest on the booking before taking an advance."))

	folio_name = doc.ensure_booking_folio()
	customer = resolve_customer(doc.guest)
	company = get_hotel_company()

	payment = frappe.get_doc({
		"doctype": "Payment Entry",
		"company": company,
		"payment_type": "Receive",
		"posting_date": posting_date or nowdate(),
		"party_type": "Customer",
		"party": customer,
		"paid_from": get_receivable_account(company),
		"paid_to": get_mop_account(mode_of_payment, company),
		"paid_amount": amount,
		"received_amount": amount,
		"source_exchange_rate": 1,
		"target_exchange_rate": 1,
		"mode_of_payment": mode_of_payment,
		"reference_no": reference_no or doc.name,
		"reference_date": posting_date or nowdate(),
		"guest_folio": folio_name,
		"hotel_booking": doc.name,
		"hotel_reception": doc.hotel_reception,
		"cashier": frappe.session.user,
		"remarks": _("Advance for booking {0} — guest {1}, arriving {2}").format(
			doc.name, doc.guest_name or doc.guest, doc.arrival_date
		),
	})
	payment.insert(ignore_permissions=True)
	payment.submit()

	doc.append("payments", {
		"posting_date": payment.posting_date,
		"payment_type": "Advance",
		"amount": amount,
		"mode_of_payment": mode_of_payment,
		"reference_no": reference_no,
		"payment_entry": payment.name,
		"received_by": frappe.session.user,
	})
	doc.save(ignore_permissions=True)

	return {
		"payment_entry": payment.name,
		"booking_folio": folio_name,
		"advance_received": doc.advance_received,
		"balance_due": doc.balance_due,
	}


@frappe.whitelist()
def get_advance_balance(booking):
	"""What is still sitting on the booking folio, unapplied."""
	folio = frappe.db.get_value("Hotel Booking", booking, "booking_folio")
	if not folio:
		return 0.0
	# outstanding_balance is charges - payments, so a credit balance is negative.
	return abs(min(flt(frappe.db.get_value("Guest Folio", folio, "outstanding_balance")), 0.0))


@frappe.whitelist()
def apply_advance(booking, reservation, amount=None):
	"""Move advance money from the booking folio onto a room folio at check-in.

	Posts a matched pair — a debit on the booking folio and a credit on the room folio —
	rather than reparenting the original transaction, so the booking folio keeps its
	history and the movement is auditable from both sides.
	"""
	doc = frappe.get_doc("Hotel Booking", booking)
	doc.check_permission("write")

	if not doc.booking_folio:
		return {"applied": 0.0, "reason": _("This booking has no advance folio.")}

	available = get_advance_balance(booking)
	if available <= 0.01:
		return {"applied": 0.0, "reason": _("No unapplied advance remains.")}

	target_folio = frappe.db.get_value("Hotel Reservation", reservation, "folio")
	if not target_folio:
		frappe.throw(_("Reservation {0} has no folio.").format(reservation))

	amount = flt(amount) if amount else available
	amount = min(amount, available)
	if amount <= 0.01:
		return {"applied": 0.0, "reason": _("Nothing to apply.")}

	ensure_item(ITEM_ADVANCE_TRANSFER, "Advance Transfer")
	today = nowdate()
	room = frappe.db.get_value("Hotel Reservation", reservation, "room")

	# Debit the booking folio: the money leaves it.
	_post(
		doc.booking_folio, amount,
		_("Advance applied to {0} (room {1})").format(reservation, room),
		today, reference=target_folio,
	)
	# Credit the room folio: the guest's bill is reduced.
	_post(
		target_folio, -amount,
		_("Advance from booking {0}").format(doc.name),
		today, reference=doc.booking_folio,
	)

	# Folio Transaction is a child doctype, so its `after_save` doc_event does not fire
	# on a direct insert — the balances have to be recomputed explicitly. This is the
	# same thing payment_bridge.process_payment_entry does after posting its own rows.
	for folio in (doc.booking_folio, target_folio):
		sync_folio_balance(frappe.get_doc("Guest Folio", folio))

	frappe.get_doc({
		"doctype": "Folio Transaction Move Log",
		"transaction_name": f"{ITEM_ADVANCE_TRANSFER}:{doc.name}",
		"source_folio": doc.booking_folio,
		"target_folio": target_folio,
		"item": ITEM_ADVANCE_TRANSFER,
		"amount": amount,
		"user": frappe.session.user,
		"move_datetime": frappe.utils.now_datetime(),
	}).insert(ignore_permissions=True)

	realize_advance_income(doc, amount)

	return {
		"applied": amount,
		"remaining": get_advance_balance(booking),
		"target_folio": target_folio,
	}


def _post(folio, amount, description, posting_date, reference=None):
	"""One folio transaction. Positive is a charge, negative a credit."""
	frappe.get_doc({
		"doctype": "Folio Transaction",
		"parent": folio,
		"parenttype": "Guest Folio",
		"parentfield": "transactions",
		"posting_date": posting_date,
		"item": ITEM_ADVANCE_TRANSFER,
		"description": description,
		"qty": 1,
		"amount": amount,
		"bill_to": "Guest",
		"reference_doctype": "Guest Folio",
		"reference_name": reference,
		"is_invoiced": 0,
	}).insert(ignore_permissions=True)


def realize_advance_income(booking, amount):
	"""Release an applied advance from the liability account into income suspense.

	While the money sat on the booking folio it was a liability — the resort owed a stay.
	Applying it to a room folio is the point that obligation starts being delivered.
	"""
	settings = frappe.get_single("Hospitality Accounting Settings")
	liability = settings.get("advance_liability_account")
	suspense = settings.get("income_suspense_account")
	if not (liability and suspense):
		return

	company = get_hotel_company()
	cost_center = settings.get("cost_center")
	today = nowdate()

	for account, debit, credit in (
		(liability, flt(amount), 0.0),
		(suspense, 0.0, flt(amount)),
	):
		frappe.get_doc({
			"doctype": "GL Entry",
			"posting_date": today,
			"account": account,
			"debit": debit,
			"credit": credit,
			"debit_in_account_currency": debit,
			"credit_in_account_currency": credit,
			"company": company,
			"cost_center": cost_center,
			"voucher_type": "Hotel Booking",
			"voucher_no": booking.name,
			"remarks": _("Advance applied from booking {0}").format(booking.name),
		}).insert(ignore_permissions=True)
