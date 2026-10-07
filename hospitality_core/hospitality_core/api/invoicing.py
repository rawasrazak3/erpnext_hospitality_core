"""Sales Invoices for hotel stays.

The Sales Invoice is where a stay's revenue and GST are booked. A folio is the running
bill while the guest is in house; at check-out its charges become one submitted Sales
Invoice, and the payments the guest made for this stay (the booking advance and anything
paid at the desk) are allocated against it, so the invoice closes as Paid and the
guest's receivable nets to zero.

What goes on the invoice:
  * every charge on the folio that is not a money movement — room rent, extra beds,
    anything posted manually;
  * DISCOUNT / COMPLIMENTARY lines come off as the invoice's discount, not as negative
    items;
  * NOT payments, refunds, transfers or advance moves (they are money, not sales);
  * NOT charges that came from a POS Invoice, which already booked its own revenue.

Folio amounts are tax-inclusive (see utils.get_tax_breakdown), so GST rows are added
with "included in print rate" and the invoice total equals the folio total the guest
was shown.

Advances taken before arrival were parked on the Advance Liability account (see
accounting.park_advance_as_liability). Once such an advance is allocated to the invoice
the stay has been delivered, so `settle_parked_advances` moves it back out of that
liability — otherwise the receivable would stay debited by the parked amount forever.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, nowdate

from hospitality_core.hospitality_core.api.utils import (
	NON_REVENUE_ITEM_CODES,
	get_hotel_company,
	get_receivable_account,
	get_tax_config,
)

DISCOUNT_ITEMS = ("DISCOUNT", "COMPLIMENTARY")
PARK_REMARK = "Advance held for Booking Folio"
SETTLE_REMARK = "Advance settled by invoice"
UNREALIZE_REMARK = "Advance realization moved to invoice"


def _customer_for(folio):
	if folio.company:
		return folio.company
	from hospitality_core.hospitality_core.api.advance import resolve_customer

	if not folio.guest:
		frappe.throw(_("Folio {0} has no guest to invoice.").format(folio.name))
	return resolve_customer(folio.guest)


def _billable(folio):
	"""(charges, discounts) on the folio that have not been invoiced yet."""
	charges, discounts = [], []
	for t in folio.transactions:
		if cint(t.is_void) or cint(t.is_invoiced):
			continue
		if t.item in DISCOUNT_ITEMS and flt(t.amount) < 0:
			discounts.append(t)
		elif (
			flt(t.amount) > 0
			and t.item not in NON_REVENUE_ITEM_CODES
			and t.reference_doctype != "POS Invoice"
		):
			charges.append(t)
	return charges, discounts


def _add_taxes(si, settings, cost_center):
	"""Tax-inclusive GST rows matching what the folio amounts already contain."""
	config = get_tax_config()
	if flt(config["gst_rate"]) <= 0:
		return

	if cint(config["enable_igst"]) and config.get("igst_account"):
		rows = [("IGST", config["igst_account"], config["gst_rate"])]
	else:
		rows = [
			("CGST", config.get("cgst_account"), config["cgst_rate"]),
			("SGST", config.get("sgst_account"), config["sgst_rate"]),
		]

	for label, account, rate in rows:
		if not account:
			frappe.throw(_(
				"Set the {0} account in Hospitality Accounting Settings before invoicing."
			).format(label))
		si.append("taxes", {
			"charge_type": "On Net Total",
			"account_head": account,
			"rate": flt(rate),
			"included_in_print_rate": 1,
			"description": f"{label} @ {flt(rate)}%",
			"cost_center": cost_center,
		})


def _stay_payment_entries(folio, customer):
	"""Submitted receipts that belong to this stay: paid onto its folio, or taken as an
	advance on its booking. Restricting to these stops an invoice from swallowing an
	advance the same guest paid for a different, future booking."""
	folios = [folio.name]
	booking = folio.get("hotel_booking")
	if folio.reservation:
		booking = booking or frappe.db.get_value("Hotel Reservation", folio.reservation, "hotel_booking")
	if booking:
		booking_folio = frappe.db.get_value("Hotel Booking", booking, "booking_folio")
		if booking_folio:
			folios.append(booking_folio)

	conditions = {"docstatus": 1, "payment_type": "Receive", "party": customer}
	names = set(frappe.get_all(
		"Payment Entry", filters={**conditions, "guest_folio": ["in", folios]}, pluck="name"
	))
	if booking:
		names.update(frappe.get_all(
			"Payment Entry", filters={**conditions, "hotel_booking": booking}, pluck="name"
		))
	return names


def _allocate_stay_advances(si, folio):
	"""Allocate this stay's unallocated receipts against the invoice, oldest first."""
	allowed = _stay_payment_entries(folio, si.customer)
	if not allowed:
		return

	si.set("advances", [])
	remaining = flt(si.get("rounded_total") or si.grand_total)
	for d in si.get_advance_entries():
		if remaining <= 0.009:
			break
		if d.reference_type != "Payment Entry" or d.reference_name not in allowed:
			continue
		allocated = min(remaining, flt(d.amount))
		if allocated <= 0:
			continue
		remaining -= allocated
		row = {
			"reference_type": d.reference_type,
			"reference_name": d.reference_name,
			"reference_row": d.reference_row,
			"remarks": d.remarks,
			"advance_amount": flt(d.amount),
			"allocated_amount": allocated,
			"ref_exchange_rate": flt(d.exchange_rate) or 1,
			"difference_posting_date": si.posting_date,
		}
		if d.get("paid_from"):
			row["account"] = d.paid_from
		si.append("advances", row)


@frappe.whitelist()
def create_invoice_from_folio(folio_name, submit=1):
	"""Sales Invoice for everything on the folio not yet invoiced. Returns its name."""
	folio = frappe.get_doc("Guest Folio", folio_name)
	folio.check_permission("read")

	if cint(folio.get("is_booking_master")):
		frappe.throw(_(
			"This is a booking advance folio. Advances are invoiced on the room folio at "
			"check-out; a retained cancellation charge is invoiced from Cancel Booking."
		))
	if cint(folio.is_company_master):
		frappe.throw(_(
			"This is a company (city ledger) master folio. Invoice each guest's own folio; "
			"its company charges are billed to the company there."
		))

	charges, discounts = _billable(folio)
	if not charges:
		frappe.throw(_("No uninvoiced charges on folio {0}.").format(folio.name))

	settings = frappe.get_single("Hospitality Accounting Settings")
	company = settings.get("company") or get_hotel_company()
	cost_center = settings.get("cost_center") or frappe.get_cached_value("Company", company, "cost_center")
	customer = _customer_for(folio)

	guest_name = frappe.db.get_value("Guest", folio.guest, "full_name") if folio.guest else None
	stay = ""
	if folio.reservation:
		arrival, departure = frappe.db.get_value(
			"Hotel Reservation", folio.reservation, ["arrival_date", "departure_date"]
		)
		stay = _("{0} to {1}").format(
			frappe.format(arrival, "Date"), frappe.format(departure, "Date")
		)

	si = frappe.new_doc("Sales Invoice")
	si.customer = customer
	si.company = company
	si.guest_folio = folio.name
	si.posting_date = nowdate()
	si.due_date = nowdate()
	si.debit_to = settings.get("receivable_account") or get_receivable_account(company)
	si.cost_center = cost_center
	si.disable_rounded_total = 1
	si.allocate_advances_automatically = 0
	si.remarks = _("Guest: {0} | Room: {1} | Stay: {2} | Folio: {3}").format(
		guest_name or folio.guest or "", folio.room or "", stay, folio.name
	)

	for t in charges:
		qty = flt(t.qty) or 1
		description = t.description or t.item
		if t.posting_date:
			description = f"{description} ({frappe.format(t.posting_date, 'Date')})"
		si.append("items", {
			"item_code": t.item,
			"description": description,
			"qty": qty,
			"rate": flt(t.amount) / qty,
			"uom": frappe.db.get_value("Item", t.item, "stock_uom") or "Nos",
			"conversion_factor": 1,
			"income_account": get_income_account(t.item, company),
			"cost_center": cost_center,
		})

	discount_total = sum(abs(flt(t.amount)) for t in discounts)
	if discount_total > 0:
		si.apply_discount_on = "Grand Total"
		si.discount_amount = min(discount_total, sum(flt(t.amount) for t in charges))

	_add_taxes(si, settings, cost_center)

	si.set_missing_values()
	si.calculate_taxes_and_totals()
	_allocate_stay_advances(si, folio)
	si.insert(ignore_permissions=True)
	if cint(submit):
		si.submit()

	for t in charges + discounts:
		frappe.db.set_value("Folio Transaction", t.name, {
			"is_invoiced": 1,
			"reference_doctype": "Sales Invoice",
			"reference_name": si.name,
		})

	return si.name


@frappe.whitelist()
def create_cancellation_invoice(booking, amount):
	"""Invoice the part of a booking advance kept as a cancellation charge.

	The retained amount becomes revenue on a Sales Invoice paid from the advance; it is
	posted onto the booking folio as a charge so that folio's remaining credit is exactly
	what is still refundable.
	"""
	from hospitality_core.hospitality_core.api.advance import ensure_item, get_advance_balance

	doc = frappe.get_doc("Hotel Booking", booking)
	amount = min(flt(amount), get_advance_balance(booking))
	if amount <= 0 or not doc.booking_folio:
		return None

	ensure_item("CANCELLATION-FEE", "Cancellation Charge")
	folio = frappe.get_doc("Guest Folio", doc.booking_folio)
	frappe.get_doc({
		"doctype": "Folio Transaction",
		"parent": folio.name,
		"parenttype": "Guest Folio",
		"parentfield": "transactions",
		"posting_date": nowdate(),
		"item": "CANCELLATION-FEE",
		"description": _("Cancellation charge — booking {0}").format(doc.name),
		"qty": 1,
		"amount": amount,
		"bill_to": "Guest",
	}).insert(ignore_permissions=True)

	folio.reload()
	charges, _discounts = _billable(folio)
	settings = frappe.get_single("Hospitality Accounting Settings")
	company = settings.get("company") or get_hotel_company()
	cost_center = settings.get("cost_center") or frappe.get_cached_value("Company", company, "cost_center")

	si = frappe.new_doc("Sales Invoice")
	si.customer = _customer_for(folio)
	si.company = company
	si.guest_folio = folio.name
	si.posting_date = nowdate()
	si.due_date = nowdate()
	si.debit_to = settings.get("receivable_account") or get_receivable_account(company)
	si.cost_center = cost_center
	si.disable_rounded_total = 1
	si.allocate_advances_automatically = 0
	si.remarks = _("Cancellation charge for booking {0}").format(doc.name)
	for t in charges:
		si.append("items", {
			"item_code": t.item,
			"description": t.description,
			"qty": 1,
			"rate": flt(t.amount),
			"uom": "Nos",
			"conversion_factor": 1,
			"income_account": get_income_account(t.item, company),
			"cost_center": cost_center,
		})
	_add_taxes(si, settings, cost_center)
	si.set_missing_values()
	si.calculate_taxes_and_totals()
	_allocate_stay_advances(si, folio)
	si.insert(ignore_permissions=True)
	si.submit()

	for t in charges:
		frappe.db.set_value("Folio Transaction", t.name, {
			"is_invoiced": 1,
			"reference_doctype": "Sales Invoice",
			"reference_name": si.name,
		})

	from hospitality_core.hospitality_core.api.folio import sync_folio_balance
	sync_folio_balance(frappe.get_doc("Guest Folio", folio.name))
	return si.name


def get_income_account(item_code, company):
	"""
	Resolves the Income Account for an Item in the given Company.
	Order: Item Default > Item Group Default > Hospitality settings > Company Default
	"""
	account = frappe.db.get_value(
		"Item Default", {"parent": item_code, "company": company}, "income_account"
	)

	if not account:
		item_group = frappe.db.get_value("Item", item_code, "item_group")
		if item_group:
			account = frappe.db.get_value(
				"Item Group Default", {"parent": item_group, "company": company}, "income_account"
			)

	if not account:
		account = frappe.db.get_single_value("Hospitality Accounting Settings", "income_account")

	if not account:
		account = frappe.get_cached_value("Company", company, "default_income_account")

	if not account:
		frappe.throw(_(
			"Could not determine an Income Account for {0}. Set one on the Item, its Item "
			"Group, or in Hospitality Accounting Settings."
		).format(item_code))
	return account


# ------------------------------------------------------------------ parked advances
def _gl(account, debit, credit, si, settings, remarks, party=None):
	frappe.get_doc({
		"doctype": "GL Entry",
		"posting_date": si.posting_date,
		"account": account,
		"party_type": "Customer" if party else None,
		"party": party,
		"debit": flt(debit, 2),
		"credit": flt(credit, 2),
		"debit_in_account_currency": flt(debit, 2),
		"credit_in_account_currency": flt(credit, 2),
		"company": si.company,
		"cost_center": settings.get("cost_center"),
		"voucher_type": "Sales Invoice",
		"voucher_no": si.name,
		"remarks": remarks,
	}).insert(ignore_permissions=True)


def _sum(sql, params):
	return flt(frappe.db.sql(sql, params)[0][0])


def settle_parked_advances(doc, method=None):
	"""Hook: Sales Invoice on_submit.

	An advance allocated to this invoice has been earned, so undo its parking:
	dr Advance Liability / cr Receivable (party). If check-in had already moved it from
	the liability into income suspense (older bookings), that move is undone too, so the
	invoice is the single place the stay's revenue is recognised. Entries are posted
	under this invoice, so cancelling the invoice reverses them with it.
	"""
	if not doc.get("guest_folio"):
		return

	settings = frappe.get_single("Hospitality Accounting Settings")
	liability = settings.get("advance_liability_account")
	suspense = settings.get("income_suspense_account")
	receivable = doc.debit_to
	if not liability:
		return

	for adv in doc.get("advances") or []:
		if adv.reference_type != "Payment Entry" or flt(adv.allocated_amount) <= 0:
			continue
		pe = adv.reference_name

		parked = _sum(
			"""SELECT SUM(credit - debit) FROM `tabGL Entry`
			WHERE voucher_type='Payment Entry' AND voucher_no=%s AND account=%s
			AND is_cancelled=0 AND remarks LIKE %s""",
			(pe, liability, f"{PARK_REMARK}%"),
		)
		settled = _sum(
			"""SELECT SUM(debit - credit) FROM `tabGL Entry`
			WHERE account=%s AND is_cancelled=0 AND remarks LIKE %s""",
			(liability, f"{SETTLE_REMARK}%PE:{pe}|%"),
		)
		amount = min(flt(adv.allocated_amount), parked - settled)
		if amount <= 0.009:
			continue

		remark = f"{SETTLE_REMARK} | SI:{doc.name} | PE:{pe}|"
		_gl(liability, amount, 0, doc, settings, remark)
		_gl(receivable, 0, amount, doc, settings, remark, party=doc.customer)

		# Older check-ins moved applied advances liability -> suspense. Put that back.
		booking = frappe.db.get_value("Payment Entry", pe, "hotel_booking")
		if not (booking and suspense):
			continue
		realized = _sum(
			"""SELECT SUM(debit - credit) FROM `tabGL Entry`
			WHERE voucher_type='Hotel Booking' AND voucher_no=%s AND account=%s
			AND is_cancelled=0""",
			(booking, liability),
		)
		undone = _sum(
			"""SELECT SUM(credit - debit) FROM `tabGL Entry`
			WHERE account=%s AND is_cancelled=0 AND remarks LIKE %s""",
			(liability, f"{UNREALIZE_REMARK}%HB:{booking}|%"),
		)
		back = min(amount, realized - undone)
		if back > 0.009:
			remark = f"{UNREALIZE_REMARK} | SI:{doc.name} | HB:{booking}|"
			_gl(suspense, back, 0, doc, settings, remark)
			_gl(liability, 0, back, doc, settings, remark)


def cancel_sales_invoice(doc, method=None):
	"""
	Hook: Sales Invoice (on_cancel)
	Logic: Unlinks all Folio Transactions from the Sales Invoice so they can be re-invoiced.
	"""
	if not doc.get("guest_folio"):
		return

	transactions = frappe.get_all("Folio Transaction", filters={
		"reference_doctype": "Sales Invoice",
		"reference_name": doc.name
	})

	if transactions:
		for t in transactions:
			frappe.db.set_value("Folio Transaction", t.name, {
				"is_invoiced": 0,
				"reference_doctype": None,
				"reference_name": None
			})

		frappe.msgprint(_("Folio Transactions unlinked from cancelled Sales Invoice {0}.").format(doc.name))
