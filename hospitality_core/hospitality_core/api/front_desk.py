"""Front desk operations on a stay: check-in, extension, check-out.

Each of these used to be several separate trips — check in on the reservation, open the
booking to find the advance, open the folio to take the payment, come back to check out,
open the folio again to invoice. These endpoints do one desk action each, end to end,
and return a summary the dialogs render, so the desk sees the money before it commits.

The state machines themselves stay on Hotel Reservation (process_check_in /
process_check_out); this module orchestrates around them.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from hospitality_core.hospitality_core.api import advance as advance_api
from hospitality_core.hospitality_core.api.folio import sync_folio_balance
from hospitality_core.hospitality_core.api.night_audit import get_extra_bed_charge, get_rate
from hospitality_core.hospitality_core.api.tariff import rate_class
from hospitality_core.hospitality_core.api.stay_policy import stay_time_values
from hospitality_core.hospitality_core.api.utils import NON_REVENUE_ITEM_CODES

ID_FIELDS = {
	"Aadhaar Card": "aadhaar_number",
	"PAN Card": "pan_number",
}


# ------------------------------------------------------------------ pricing
def price_nights(res, from_date, to_date):
	"""Price each night in [from_date, to_date) exactly as the night audit will post it.

	Same rate precedence (agreed rate > rate plan > weekday/weekend tariff), same extra
	beds, same discount rule — so a preview never disagrees with the folio.
	"""
	nights = []
	current = getdate(from_date)
	end = getdate(to_date)
	while current < end:
		rate = flt(get_rate(res.rate_plan, res.room_type, current, reservation=res))
		beds = flt(get_extra_bed_charge(res, current))
		gross = rate + beds
		# Same basis as night_audit.post_room_charge: the discount is taken off the
		# night's full charge, extra beds included.
		if cint(res.is_complimentary):
			discount = gross
		elif str(res.discount_type or "").strip() == "Percentage":
			discount = gross * flt(res.discount_value) / 100.0
		elif str(res.discount_type or "").strip() == "Amount":
			discount = flt(res.discount_value)
		else:
			discount = 0.0
		discount = min(max(discount, 0.0), gross)
		nights.append({
			"date": str(current),
			"rate_class": rate_class(current),
			"rate": flt(rate, 2),
			"extra_bed": flt(beds, 2),
			"discount": flt(discount, 2),
			"amount": flt(gross - discount, 2),
		})
		current = add_days(current, 1)
	return nights


# ------------------------------------------------------------------ summaries
def _folio_lines(folio):
	rows = frappe.db.sql(
		"""SELECT posting_date, item, description, amount, is_invoiced, reference_doctype,
		          reference_name
		FROM `tabFolio Transaction`
		WHERE parent=%s AND is_void=0
		ORDER BY posting_date, idx""",
		(folio,),
		as_dict=True,
	)
	for r in rows:
		if r.item in ("DISCOUNT", "COMPLIMENTARY"):
			r.kind = "discount"
		elif flt(r.amount) < 0 or r.item in NON_REVENUE_ITEM_CODES:
			r.kind = "payment"
		else:
			r.kind = "charge"
	return rows


@frappe.whitelist()
def get_stay_summary(reservation):
	"""Everything the check-in / check-out dialogs show about one stay."""
	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("read")

	guest = frappe.db.get_value(
		"Guest", res.guest,
		["full_name", "mobile_no", "email_id", "identification_type", "identification_no",
		 "aadhaar_number", "pan_number", "guest_type", "vip_notes"],
		as_dict=True,
	) or {}

	folio = {}
	lines = []
	if res.folio:
		sync_folio_balance(frappe.get_doc("Guest Folio", res.folio))
		folio = frappe.db.get_value(
			"Guest Folio", res.folio,
			["name", "status", "total_charges", "total_payments", "total_discounts",
			 "outstanding_balance"],
			as_dict=True,
		) or {}
		lines = _folio_lines(res.folio)

	booking = {}
	unapplied = 0.0
	if res.hotel_booking:
		booking = frappe.db.get_value(
			"Hotel Booking", res.hotel_booking,
			["name", "status", "total_amount", "advance_received", "balance_due", "booking_folio"],
			as_dict=True,
		) or {}
		unapplied = advance_api.get_advance_balance(res.hotel_booking)

	today = getdate(nowdate())
	nights = date_diff(res.departure_date, res.arrival_date)

	# What the whole stay will cost, night by night, for the check-in dialog.
	estimate = price_nights(res, res.arrival_date, res.departure_date)

	# Nights still to be posted if the guest stays until the booked departure.
	posted_dates = {str(l.posting_date) for l in lines if l.kind == "charge" and l.item == "ROOM-RENT"}
	pending = [n for n in estimate if n["date"] not in posted_dates and getdate(n["date"]) >= today]

	balance = flt(folio.get("outstanding_balance"))
	invoices = frappe.get_all(
		"Sales Invoice",
		filters={"guest_folio": res.folio, "docstatus": ["<", 2]} if res.folio else {"name": ""},
		fields=["name", "grand_total", "outstanding_amount", "status", "docstatus"],
	)

	early = res.status == "Checked In" and getdate(res.departure_date) > today
	checkout_pending = res.status == "Checked In" and getdate(res.departure_date) < today
	from hospitality_core.hospitality_core.api.stay_policy import get_stay_times
	check_in_time, check_out_time = get_stay_times()

	return {
		"reservation": res.name,
		"status": res.status,
		"room": res.room,
		"room_type": res.room_type,
		"arrival_date": res.arrival_date,
		"departure_date": res.departure_date,
		"nights": nights,
		"adults": res.adults,
		"children": res.children,
		"is_company_guest": cint(res.is_company_guest),
		"company": res.company,
		"guest": res.guest,
		"guest_detail": guest,
		"folio": folio,
		"lines": lines,
		"booking": booking,
		"unapplied_advance": unapplied,
		"stay_estimate": estimate,
		"stay_estimate_total": flt(sum(n["amount"] for n in estimate), 2),
		"pending_nights": pending,
		"pending_total": flt(sum(n["amount"] for n in pending), 2),
		# At check-out any unapplied booking advance is applied first, so the amount the
		# desk must collect is the folio balance less that advance.
		"balance": balance,
		"to_collect": flt(max(balance - unapplied, 0), 2),
		"refund_due": flt(max(unapplied - balance, 0), 2),
		"early_departure": early,
		"checkout_pending": checkout_pending,
		"check_in_time": check_in_time,
		"check_out_time": check_out_time,
		"can_check_in": res.status == "Reserved" and getdate(res.arrival_date) <= today,
		"invoices": invoices,
	}


# ------------------------------------------------------------------ check-in
def _update_guest_identity(guest, id_type=None, id_number=None, mobile_no=None):
	if not guest:
		return
	updates = {}
	if id_type:
		updates["identification_type"] = id_type
	if id_number:
		updates["identification_no"] = id_number
		field = ID_FIELDS.get(id_type)
		if field:
			updates[field] = id_number
	if mobile_no:
		updates["mobile_no"] = mobile_no
	if updates:
		frappe.db.set_value("Guest", guest, updates)


def _take_payment(folio, amount, mode_of_payment, reference_no=None):
	from hospitality_core.hospitality_core.api.payment_bridge import create_folio_payment

	amount = flt(amount)
	if amount <= 0:
		return None
	if not mode_of_payment:
		frappe.throw(_("Choose how the guest paid."))
	reception = frappe.db.get_value("Guest Folio", folio, "hotel_reception") or frappe.db.get_value(
		"Hotel Reception", {}, "name"
	)
	pe = create_folio_payment(folio, amount, mode_of_payment, reception)
	if reference_no:
		frappe.db.set_value("Payment Entry", pe, "reference_no", reference_no)
	return pe


@frappe.whitelist()
def check_in(reservation, id_type=None, id_number=None, mobile_no=None,
             payment_amount=0, mode_of_payment=None, reference_no=None):
	"""Check one room in: record the guest's ID, charge the first night, apply the
	booking advance, and optionally take a payment — in one step."""
	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("write")

	_update_guest_identity(res.guest, id_type, id_number, mobile_no)

	# A room held on a Tentative booking has no Reserved status to check in from yet;
	# confirming the booking creates it.
	if res.status == "No Show":
		res.db_set("status", "Reserved")
		res.reload()

	res.process_check_in()
	res.reload()

	applied = 0.0
	if res.hotel_booking:
		booking_status = frappe.db.get_value("Hotel Booking", res.hotel_booking, "status")
		if booking_status in ("Confirmed", "Tentative"):
			frappe.db.set_value("Hotel Booking", res.hotel_booking, "status", "Checked In")
		applied = flt(advance_api.apply_advance(res.hotel_booking, res.name).get("applied"))

	payment = _take_payment(res.folio, payment_amount, mode_of_payment, reference_no)

	summary = get_stay_summary(res.name)
	summary.update({"advance_applied": applied, "payment_entry": payment})
	return summary


# ------------------------------------------------------------------ extension
@frappe.whitelist()
def preview_extension(reservation, new_departure_date):
	"""Price the extra nights and check the room is free for them."""
	from hospitality_core.hospitality_core.api.availability import is_room_free

	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("read")

	new_departure = getdate(new_departure_date)
	if new_departure <= getdate(res.departure_date):
		frappe.throw(_("The new departure must be after {0}.").format(
			frappe.format(res.departure_date, "Date")
		))

	nights = price_nights(res, res.departure_date, new_departure)
	free = is_room_free(
		res.room, res.departure_date, new_departure,
		arrival_time=res.departure_time, ignore_reservation=res.name,
		ignore_booking=res.hotel_booking,
	)

	booking = {}
	if res.hotel_booking:
		booking = frappe.db.get_value(
			"Hotel Booking", res.hotel_booking,
			["total_amount", "advance_received", "balance_due"], as_dict=True,
		) or {}

	extra = flt(sum(n["amount"] for n in nights), 2)
	return {
		"nights": nights,
		"extra_nights": len(nights),
		"extra_total": extra,
		"free": free["free"],
		"reason": free.get("reason"),
		"current_departure": res.departure_date,
		"new_departure": new_departure,
		"booking_total": flt(booking.get("total_amount")),
		"new_booking_total": flt(booking.get("total_amount")) + extra if booking else None,
	}


# ------------------------------------------------------------------ check-out
@frappe.whitelist()
def check_out(reservation, payment_amount=0, mode_of_payment=None, reference_no=None,
              make_invoice=1):
	"""Settle and check out one room, then raise its Sales Invoice.

	Order matters: the booking advance is applied first, then the desk's payment, then
	the folio is closed (which refuses a private guest with a balance), then the
	invoice. All of it is one transaction, so a refused check-out leaves no stray
	payment behind.
	"""
	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("write")
	if res.status != "Checked In":
		frappe.throw(_("Only a guest who is checked in can check out."))

	applied = 0.0
	if res.hotel_booking:
		applied = flt(advance_api.apply_advance(res.hotel_booking, res.name).get("applied"))

	payment = _take_payment(res.folio, payment_amount, mode_of_payment, reference_no)

	res.reload()
	res.process_check_out()

	invoice, invoice_error = None, None
	if cint(make_invoice) and res.folio:
		from hospitality_core.hospitality_core.api.invoicing import create_invoice_from_folio

		# The guest has left; an invoicing problem (a missing account, say) must not
		# undo that. Invoice under a savepoint and report the failure instead.
		frappe.db.savepoint("hotel_checkout_invoice")
		try:
			invoice = create_invoice_from_folio(res.folio, submit=1)
		except Exception as e:
			frappe.db.rollback(save_point="hotel_checkout_invoice")
			frappe.clear_messages()
			invoice_error = str(e) or e.__class__.__name__
			frappe.log_error(
				f"Check-out invoice failed for {res.name}: {invoice_error}",
				"Hotel check-out invoice",
			)

	folio = frappe.db.get_value(
		"Guest Folio", res.folio, ["name", "outstanding_balance", "status"], as_dict=True
	) if res.folio else {}

	return {
		"reservation": res.name,
		"status": frappe.db.get_value("Hotel Reservation", res.name, "status"),
		"advance_applied": applied,
		"payment_entry": payment,
		"folio": folio,
		"invoice": invoice,
		"invoice_error": invoice_error,
		"hotel_booking": res.hotel_booking,
	}


# ------------------------------------------------------------------ the Guests board
# One list of every stay the desk might act on, and one small endpoint per action, so
# the Hotel POS "Guests" tab can run the whole stay without opening a form.

STAGE_ORDER = {
	"Check-out pending": 0, "Due out": 0, "Late arrival": 1, "Arriving": 2, "In house": 3,
	"No show": 4, "Hold": 5, "Upcoming": 6,
}


def _stage(status, arrival, departure, today):
	arrival, departure = getdate(arrival), getdate(departure)
	if status == "Checked In":
		if departure < today:
			# Their nights are over and the room is already free; they only need
			# checking out (and settling) — nothing more is being charged.
			return "Check-out pending"
		return "Due out" if departure == today else "In house"
	if status == "Reserved":
		if arrival < today:
			return "Late arrival"
		return "Arriving" if arrival == today else "Upcoming"
	if status == "No Show":
		return "No show"
	return status


VIEWS = {
	"live": ("Due out", "Check-out pending", "Late arrival", "Arriving", "In house"),
	"arriving": ("Late arrival", "Arriving"),
	"inhouse": ("In house", "Due out"),
	"dueout": ("Due out", "Check-out pending"),
	"upcoming": ("Upcoming",),
	"holds": ("Hold",),
	"noshow": ("No show",),
}


@frappe.whitelist()
def get_stays(view="live", search=None):
	"""Every stay the desk can act on, with where it is and what is owed.

	Reservations cover everything from confirmed onwards; bookings still on hold (no
	reservation yet) are listed as their own rows so a hold can be confirmed here too.
	"""
	today = getdate(nowdate())
	params = {"today": today, "horizon": add_days(today, 60), "recent": add_days(today, -3)}

	rows = frappe.db.sql(
		"""
		SELECT r.name, r.status, r.room, r.room_type, r.arrival_date, r.departure_date,
		       r.hotel_booking, r.folio, r.is_company_guest, r.company,
		       g.full_name AS guest_name, g.mobile_no,
		       f.outstanding_balance
		FROM `tabHotel Reservation` r
		LEFT JOIN `tabGuest` g ON g.name = r.guest
		LEFT JOIN `tabGuest Folio` f ON f.name = r.folio
		WHERE r.status = 'Checked In'
		   OR (r.status = 'Reserved' AND r.arrival_date <= %(horizon)s)
		   OR (r.status = 'No Show' AND r.arrival_date >= %(recent)s)
		""",
		params,
		as_dict=True,
	)

	holds = frappe.db.sql(
		"""
		SELECT b.name, b.status, b.arrival_date, b.departure_date, b.guest_name, b.mobile_no,
		       b.total_amount, b.advance_received, b.balance_due,
		       (SELECT GROUP_CONCAT(IFNULL(NULLIF(l.room, ''), l.room_type) SEPARATOR ', ')
		          FROM `tabHotel Booking Room` l WHERE l.parent = b.name) AS rooms
		FROM `tabHotel Booking` b
		WHERE b.status IN ('Draft', 'Tentative') AND b.departure_date >= %(today)s
		""",
		params,
		as_dict=True,
	)

	advances = {}
	for b in {r.hotel_booking for r in rows if r.hotel_booking}:
		advances[b] = advance_api.get_advance_balance(b)
	booking_due = {}
	if rows:
		for b in frappe.get_all(
			"Hotel Booking",
			filters={"name": ["in", list(advances) or [""]]},
			fields=["name", "balance_due"],
		):
			booking_due[b.name] = flt(b.balance_due)

	out = []
	for r in rows:
		stage = _stage(r.status, r.arrival_date, r.departure_date, today)
		unapplied = advances.get(r.hotel_booking, 0.0)
		if r.status == "Checked In":
			due = flt(r.outstanding_balance) - unapplied
		else:
			due = booking_due.get(r.hotel_booking, 0.0)
		out.append({
			"kind": "reservation", "name": r.name, "booking": r.hotel_booking,
			"status": r.status, "stage": stage,
			"guest_name": r.guest_name, "mobile_no": r.mobile_no,
			"room": r.room, "room_type": r.room_type,
			"arrival_date": str(r.arrival_date), "departure_date": str(r.departure_date),
			"nights": date_diff(r.departure_date, r.arrival_date),
			"due": flt(due, 2), "company": r.company if cint(r.is_company_guest) else None,
		})
	for b in holds:
		out.append({
			"kind": "booking", "name": b.name, "booking": b.name,
			"status": b.status, "stage": "Hold",
			"guest_name": b.guest_name, "mobile_no": b.mobile_no,
			"room": b.rooms, "room_type": None,
			"arrival_date": str(b.arrival_date), "departure_date": str(b.departure_date),
			"nights": date_diff(b.departure_date, b.arrival_date),
			"due": flt(b.balance_due, 2), "company": None,
		})

	counts = {key: sum(1 for o in out if o["stage"] in stages) for key, stages in VIEWS.items()}
	counts["all"] = len(out)

	wanted = VIEWS.get(view)
	if wanted:
		out = [o for o in out if o["stage"] in wanted]

	if search:
		needle = str(search).strip().lower()
		digits = "".join(ch for ch in needle if ch.isdigit())
		def hit(o):
			hay = " ".join(str(o.get(k) or "") for k in ("guest_name", "room", "name", "booking")).lower()
			if needle in hay:
				return True
			phone = "".join(ch for ch in str(o.get("mobile_no") or "") if ch.isdigit())
			return bool(digits) and len(digits) >= 4 and digits in phone
		out = [o for o in out if hit(o)]

	out.sort(key=lambda o: (STAGE_ORDER.get(o["stage"], 9), o["arrival_date"], o["guest_name"] or ""))
	return {"rows": out[:300], "counts": counts, "today": str(today)}


# ------------------------------------------------------------------ payments
@frappe.whitelist()
def take_payment(amount, mode_of_payment, reservation=None, booking=None, reference_no=None):
	"""Take money for a stay, wherever it is in its life.

	Before arrival it is an advance on the booking; once the guest is in (or has left
	with a balance) it goes on the room's folio.
	"""
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Enter the amount received."))

	if reservation:
		res = frappe.get_doc("Hotel Reservation", reservation)
		res.check_permission("write")
		if res.status in ("Checked In", "Checked Out") and res.folio:
			pe = _take_payment(res.folio, amount, mode_of_payment, reference_no)
			return {"payment_entry": pe, "where": "folio"}
		booking = res.hotel_booking
		if not booking:
			frappe.throw(_("This reservation has no booking to hold an advance. Check the guest in first, then take the payment."))

	if not booking:
		frappe.throw(_("Choose a stay to take the payment for."))
	result = advance_api.record_advance(booking, amount, mode_of_payment, reference_no=reference_no)
	return {"payment_entry": result.get("payment_entry"), "where": "advance"}


@frappe.whitelist()
def refund(reservation, amount):
	"""Pay back a guest's credit from the room folio."""
	from hospitality_core.hospitality_core.api.payment_bridge import issue_folio_refund

	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("write")
	if not res.folio:
		frappe.throw(_("This stay has no folio."))
	reception = frappe.db.get_value("Guest Folio", res.folio, "hotel_reception") or frappe.db.get_value(
		"Hotel Reception", {}, "name"
	)
	return issue_folio_refund(res.folio, flt(amount), reception)


# ------------------------------------------------------------------ charges
EXTRA_ITEM = "EXTRA-SERVICE"


@frappe.whitelist()
def add_charge(reservation, description, amount, item=None, qty=1):
	"""Put a charge on an in-house guest's bill: food, laundry, a transfer, damages.

	It is invoiced with the room at check-out.
	"""
	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("write")
	if res.status != "Checked In" or not res.folio:
		frappe.throw(_("Charges can be added while the guest is checked in."))
	amount, qty = flt(amount), flt(qty) or 1
	if amount <= 0:
		frappe.throw(_("Enter the amount to charge."))
	if not (description or "").strip():
		frappe.throw(_("Describe the charge so it reads clearly on the bill."))

	item = item or advance_api.ensure_item(EXTRA_ITEM, "Extra Service")
	frappe.get_doc({
		"doctype": "Folio Transaction",
		"parent": res.folio,
		"parenttype": "Guest Folio",
		"parentfield": "transactions",
		"posting_date": nowdate(),
		"item": item,
		"description": description.strip(),
		"qty": qty,
		"amount": flt(amount * qty, 2),
		"bill_to": "Company" if cint(res.is_company_guest) else "Guest",
		"posted_by": frappe.session.user,
	}).insert(ignore_permissions=True)
	sync_folio_balance(frappe.get_doc("Guest Folio", res.folio))
	return get_stay_summary(res.name)


# ------------------------------------------------------------------ dates
def _window_total(res, arrival, departure):
	return flt(sum(n["amount"] for n in price_nights(res, arrival, departure)), 2)


def _alternative_room(res, arrival, departure):
	from hospitality_core.hospitality_core.api.availability import get_free_rooms

	free = get_free_rooms(
		arrival, departure, room_type=res.room_type,
		ignore_reservation=res.name, ignore_booking=res.hotel_booking,
	)
	return free[0] if free else None


@frappe.whitelist()
def preview_date_change(reservation, arrival_date, departure_date):
	"""What moving a stay to new dates costs, and whether the room is free for them.

	A guest who has not arrived can move both dates. A guest in house keeps their
	arrival and can move the departure later (extend) or earlier, down to today.
	"""
	from hospitality_core.hospitality_core.api.availability import is_room_free

	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("read")
	arrival, departure = getdate(arrival_date), getdate(departure_date)
	today = getdate(nowdate())

	if res.status not in ("Reserved", "Checked In", "No Show"):
		frappe.throw(_("A {0} stay cannot change dates.").format(res.status))
	if departure <= arrival:
		frappe.throw(_("Departure must be after arrival."))
	if res.status == "Checked In":
		if arrival != getdate(res.arrival_date):
			frappe.throw(_("The guest is already in house; only the departure can change."))
		if departure < today:
			frappe.throw(_("The departure cannot be before today. To leave now, use Check Out."))
	elif arrival < today:
		frappe.throw(_("The arrival cannot be in the past."))

	old_total = _window_total(res, res.arrival_date, res.departure_date)
	new_total = _window_total(res, arrival, departure)

	# Only the nights the guest does not already hold need checking.
	if res.status == "Checked In" and departure > getdate(res.departure_date):
		check_from = res.departure_date
	else:
		check_from = arrival
	free = {"free": True, "reason": None}
	if departure > getdate(check_from):
		free = is_room_free(
			res.room, check_from, departure, ignore_reservation=res.name,
			ignore_booking=res.hotel_booking,
		)
	new_room = None
	if not free["free"] and res.status != "Checked In":
		new_room = _alternative_room(res, arrival, departure)

	if departure > getdate(res.departure_date):
		changed = price_nights(res, max(getdate(res.departure_date), arrival), departure)
	elif departure < getdate(res.departure_date):
		changed = [dict(n, amount=-n["amount"]) for n in price_nights(res, departure, res.departure_date)]
	else:
		changed = []

	return {
		"status": res.status,
		"room": res.room,
		"current": {"arrival": str(res.arrival_date), "departure": str(res.departure_date),
		            "nights": date_diff(res.departure_date, res.arrival_date), "total": old_total},
		"new": {"arrival": str(arrival), "departure": str(departure),
		        "nights": date_diff(departure, arrival), "total": new_total},
		"difference": flt(new_total - old_total, 2),
		"nights_changed": changed,
		"free": free["free"] or bool(new_room),
		"reason": free.get("reason"),
		"new_room": new_room,
		"arrival_locked": res.status == "Checked In",
	}


@frappe.whitelist()
def change_stay_dates(reservation, arrival_date, departure_date):
	"""Move one stay to new dates (see preview_date_change for the rules)."""
	from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import extend_stay

	p = preview_date_change(reservation, arrival_date, departure_date)
	if not p["free"]:
		frappe.throw(p["reason"] or _("The room is not free for those dates."))

	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("write")
	arrival, departure = getdate(arrival_date), getdate(departure_date)

	if res.status == "Checked In":
		if departure > getdate(res.departure_date):
			extend_stay(res.name, departure)
		elif departure < getdate(res.departure_date):
			posted = frappe.db.get_value(
				"Folio Transaction",
				{"parent": res.folio, "item": "ROOM-RENT", "is_void": 0,
				 "posting_date": [">=", departure]},
				"posting_date",
			)
			if posted:
				frappe.throw(_("The night of {0} is already on the bill. Check the guest out instead, "
				               "or void that night on the folio first.").format(frappe.format(posted, "Date")))
			res.db_set({"departure_date": departure, **stay_time_values()})
			res.add_comment("Info", _("Stay shortened to depart {0}.").format(frappe.format(departure, "Date")))
			res.sync_parent_booking()
		return p

	# Not arrived yet. A one-room booking moves as a whole, so its own dates follow.
	lines = frappe.get_all("Hotel Booking Room", filters={"parent": res.hotel_booking}, pluck="name") \
		if res.hotel_booking else []
	if res.hotel_booking and len(lines) == 1:
		booking = frappe.get_doc("Hotel Booking", res.hotel_booking)
		if booking.status in ("Draft", "Tentative", "Confirmed"):
			booking.change_dates(arrival, departure)
			return p

	room = p["new_room"] or res.room
	previous = (res.arrival_date, res.departure_date, res.room)
	if res.status == "No Show":
		res.db_set("status", "Reserved")
		if res.hotel_booking and frappe.db.get_value("Hotel Booking", res.hotel_booking, "status") == "No Show":
			frappe.db.set_value("Hotel Booking", res.hotel_booking, "status", "Confirmed")
	res.db_set({"arrival_date": arrival, "departure_date": departure, "room": room, **stay_time_values()})
	if room != previous[2]:
		if res.folio:
			frappe.db.set_value("Guest Folio", res.folio, "room", room)
		if res.hotel_booking:
			frappe.db.set_value("Hotel Booking Room", {"parent": res.hotel_booking, "reservation": res.name}, "room", room)
	res.add_comment("Info", _("Dates changed from {0} – {1} to {2} – {3}{4}.").format(
		frappe.format(previous[0], "Date"), frappe.format(previous[1], "Date"),
		frappe.format(arrival, "Date"), frappe.format(departure, "Date"),
		_(", room {0} → {1}").format(previous[2], room) if room != previous[2] else "",
	))
	res.sync_parent_booking()
	return p


# ------------------------------------------------------------------ rooms
@frappe.whitelist()
def get_move_options(reservation):
	"""Rooms free for the rest of this stay, with what each costs a night."""
	from hospitality_core.hospitality_core.api.availability import get_availability

	res = frappe.get_doc("Hotel Reservation", reservation)
	start = max(getdate(res.arrival_date), getdate(nowdate()))
	end = getdate(res.departure_date)
	if end <= start:
		end = add_days(start, 1)
	data = get_availability(start, end, include_soft_holds=False,
	                        ignore_reservation=res.name, ignore_booking=res.hotel_booking)
	rates = {t["room_type"]: t for t in data["room_types"]}
	return [
		{
			"room": r["name"], "room_type": r["room_type"],
			"rate": flt(rates.get(r["room_type"], {}).get("default_rate")),
			"same_type": r["room_type"] == res.room_type,
		}
		for r in data["rooms"]
		if r["available"] and r["name"] != res.room
	]


@frappe.whitelist()
def move_room(reservation, new_room):
	"""Put the guest in another room, before or during the stay.

	Nights already charged stay as they are; later nights are charged at the new
	room's tariff, and the booking is repriced to match.
	"""
	from hospitality_core.hospitality_core.api.availability import is_room_free

	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("write")
	if res.status not in ("Reserved", "Checked In"):
		frappe.throw(_("Only a reserved or in-house stay can change rooms."))
	if new_room == res.room:
		frappe.throw(_("The guest is already in {0}.").format(new_room))
	# Moving someone already in a room was a supervisor action before; keep it one.
	if res.status == "Checked In" and not (
		set(frappe.get_roles()) & {"Frontdesk Supervisor", "Hospitality Manager", "System Manager"}
		or frappe.session.user == "Administrator"
	):
		frappe.throw(_("Only a front desk supervisor or manager can move a guest who is in house."))

	start = max(getdate(res.arrival_date), getdate(nowdate()))
	end = getdate(res.departure_date)
	if end <= start:
		end = add_days(start, 1)
	free = is_room_free(new_room, start, end, ignore_reservation=res.name, ignore_booking=res.hotel_booking)
	if not free["free"]:
		frappe.throw(free["reason"])

	old_room = res.room
	new_type = frappe.db.get_value("Hotel Room", new_room, "room_type")
	res.db_set({"room": new_room, "room_type": new_type})
	if res.folio:
		frappe.db.set_value("Guest Folio", res.folio, "room", new_room)
	if res.status == "Checked In":
		from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import refresh_room_status
		refresh_room_status(old_room)
		refresh_room_status(new_room)
	if res.hotel_booking:
		frappe.db.set_value(
			"Hotel Booking Room", {"parent": res.hotel_booking, "reservation": res.name},
			{"room": new_room, "room_type": new_type},
		)
	res.add_comment("Info", _("Moved from {0} to {1}.").format(old_room, new_room))
	res.sync_parent_booking()
	return {"room": new_room, "room_type": new_type, "previous": old_room}


# ------------------------------------------------------------------ cancel
@frappe.whitelist()
def cancel_stay(reservation, reason, cancellation_charge=0):
	"""Cancel a stay that has not checked in.

	A one-room booking is cancelled as a booking, so a kept cancellation charge is
	invoiced from its advance. On a bigger booking only this room is released.
	"""
	res = frappe.get_doc("Hotel Reservation", reservation)
	res.check_permission("write")
	if res.status not in ("Reserved", "No Show"):
		frappe.throw(_("Only a stay that has not checked in can be cancelled. Check the guest out instead."))
	if not (reason or "").strip():
		frappe.throw(_("Give a reason for the cancellation."))

	lines = frappe.get_all("Hotel Booking Room", filters={"parent": res.hotel_booking}, pluck="name") \
		if res.hotel_booking else []
	if res.hotel_booking and len(lines) == 1:
		booking = frappe.get_doc("Hotel Booking", res.hotel_booking)
		booking.cancel_booking(reason, flt(cancellation_charge))
		return {"cancelled": "booking", "booking": booking.name}

	if res.status == "No Show":
		res.db_set("status", "Reserved")
		res.reload()
	res.process_cancel()
	res.add_comment("Info", _("Cancelled: {0}").format(reason))
	return {"cancelled": "reservation", "reservation": res.name}


# ------------------------------------------------------------------ forgotten check-outs
def auto_check_out():
	"""Scheduled hourly: check out stays whose check-out time has passed and that owe nothing.

	Staff forget to press Check Out. The room is free for the next guest regardless
	(rooms are allocated by night), and no extra night is ever charged; this just
	closes the paperwork for guests who have settled. A stay with money still to
	collect is left on the Guests board as "Check-out pending" for the desk to settle.
	Company and group guests are left for the desk too, since their bill is settled
	elsewhere.
	"""
	from frappe.utils import get_datetime, now_datetime

	from hospitality_core.hospitality_core.api.stay_policy import get_stay_times

	_check_in, check_out_time = get_stay_times()
	now = now_datetime()

	due = frappe.get_all(
		"Hotel Reservation",
		filters={"status": "Checked In", "departure_date": ["<=", getdate(now)]},
		fields=["name", "departure_date", "is_company_guest", "is_group_guest"],
	)
	done = []
	for row in due:
		if cint(row.is_company_guest) or cint(row.is_group_guest):
			continue
		if get_datetime(f"{row.departure_date} {check_out_time}") > now:
			continue
		frappe.db.savepoint("hotel_auto_checkout")
		try:
			summary = get_stay_summary(row.name)
			if flt(summary.get("to_collect")) > 0.01:
				continue
			result = check_out(row.name, payment_amount=0, make_invoice=1)
			frappe.get_doc("Hotel Reservation", row.name).add_comment("Info", _(
				"Checked out automatically after the {0} check-out time: the bill was settled{1}."
			).format(
				check_out_time[:5],
				_(" and invoice {0} was raised").format(result["invoice"]) if result.get("invoice") else "",
			))
			done.append(row.name)
		except Exception:
			frappe.db.rollback(save_point="hotel_auto_checkout")
			frappe.log_error(f"Auto check-out failed for {row.name}", "Hotel auto check-out")
	return done
