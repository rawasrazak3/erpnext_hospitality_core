"""Consistency rules between bookings, reservations, rooms, bills and enquiries.

Every screen reads a different part of the data — the POS and Tape Chart read
reservations, the CRM reads enquiries, the dashboard reads bills — so when two parts
disagree, one screen shows something false. These rules say what must always agree.
`find_problems` checks them (for everything, or for the given bookings/reservations);
the Booking Health Check report and the daily job show what breaks them, and the
test suite asserts none are broken after every desk action.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

LIVE_RES = ("Tentative", "Reserved", "Checked In")


def _p(rule, doc, message, severity="High"):
	return {"rule": rule, "document": doc, "message": message, "severity": severity}


def find_problems(bookings=None, reservations=None):
	"""Every broken rule, as [{rule, document, message, severity}]. Read-only."""
	today = getdate(nowdate())
	out = []

	b_filter = {"name": ["in", list(bookings)]} if bookings else {}
	booking_rows = frappe.get_all(
		"Hotel Booking",
		filters=b_filter,
		fields=["name", "status", "arrival_date", "departure_date", "enquiry", "advance_received",
		        "booking_folio", "guest", "mobile_no", "total_amount"],
	)
	if reservations:
		extra = frappe.get_all("Hotel Reservation", filters={"name": ["in", list(reservations)]},
		                       pluck="hotel_booking")
		have = {b.name for b in booking_rows}
		extra = [b for b in extra if b and b not in have]
		if extra:
			booking_rows += frappe.get_all("Hotel Booking", filters={"name": ["in", extra]},
			                               fields=["name", "status", "arrival_date", "departure_date", "enquiry",
			                                       "advance_received", "booking_folio", "guest", "mobile_no",
			                                       "total_amount"])

	for b in booking_rows:
		lines = frappe.get_all("Hotel Booking Room", filters={"parent": b.name},
		                       fields=["idx", "room", "room_type", "reservation"])
		res = {}
		for l in lines:
			if l.reservation:
				r = frappe.db.get_value("Hotel Reservation", l.reservation,
				                        ["name", "status", "room", "room_type", "arrival_date", "departure_date"],
				                        as_dict=True)
				if not r:
					out.append(_p("line points at a missing reservation", b.name,
					              _("Row {0} links {1}, which does not exist.").format(l.idx, l.reservation)))
					continue
				res[l.reservation] = r
				live = r.status in LIVE_RES or r.status == "No Show"
				if live and (l.room or None) != (r.room or None):
					out.append(_p("booking room differs from reservation", b.name,
					              _("Row {0}: booking says {1}, reservation {2} says {3}.").format(
						              l.idx, l.room, r.name, r.room)))
				if live and l.room_type != r.room_type:
					out.append(_p("booking room type differs from reservation", b.name,
					              _("Row {0}: {1} vs {2} on {3}.").format(l.idx, l.room_type, r.room_type, r.name)))

		if b.status in ("Confirmed", "Checked In") and any(not l.reservation for l in lines):
			out.append(_p("confirmed booking without a reservation", b.name,
			              _("{0} has a room line with no reservation: it is on no screen and holds no room.").format(b.status)))

		live = [r for r in res.values() if r.status in ("Reserved", "Checked In", "No Show")]
		if b.status == "Cancelled" and any(r.status in ("Reserved", "Checked In") for r in res.values()):
			out.append(_p("cancelled booking still holds a room", b.name,
			              _("Its reservation(s) are still live, so the room stays blocked.")))
		if b.status == "Completed" and any(r.status in ("Reserved", "Checked In") for r in res.values()):
			out.append(_p("completed booking with a live room", b.name, _("A room on it is still reserved or in house.")))
		if b.status in ("Confirmed", "Checked In", "No Show") and live:
			lo = min(getdate(r.arrival_date) for r in live)
			hi = max(getdate(r.departure_date) for r in live)
			if lo != getdate(b.arrival_date) or (hi != getdate(b.departure_date) and hi > lo):
				out.append(_p("booking dates differ from its rooms", b.name,
				              _("Booking {0} – {1}, rooms {2} – {3}.").format(b.arrival_date, b.departure_date, lo, hi)))
		if b.status == "Checked In" and not any(r.status == "Checked In" for r in res.values()) and res:
			out.append(_p("booking status behind its rooms", b.name, _("Booking says Checked In but no room is."),
			              "Medium"))

		if b.enquiry and b.status in ("Draft", "Tentative", "Confirmed", "No Show"):
			e = frappe.db.get_value("Hotel Enquiry", b.enquiry, ["check_in_date", "check_out_date", "hotel_booking"],
			                        as_dict=True)
			if e and e.hotel_booking == b.name and (
				str(e.check_in_date) != str(b.arrival_date) or str(e.check_out_date) != str(b.departure_date)
			):
				out.append(_p("enquiry dates differ from its booking", b.name,
				              _("Enquiry {0} says {1} – {2}; booking {3} – {4}.").format(
					              b.enquiry, e.check_in_date, e.check_out_date, b.arrival_date, b.departure_date),
				              "Medium"))

		paid = flt(frappe.db.sql(
			"""SELECT SUM(CASE WHEN p.payment_type='Advance' THEN p.amount ELSE -p.amount END)
			FROM `tabHotel Booking Payment` p JOIN `tabPayment Entry` pe ON pe.name = p.payment_entry
			WHERE p.parent=%s AND pe.docstatus=1""", b.name)[0][0])
		if abs(paid - flt(b.advance_received)) > 0.01:
			out.append(_p("advance differs from its payments", b.name,
			              _("Booking shows {0} advance; its submitted payments add to {1}.").format(
				              flt(b.advance_received), paid)))

	# ---------------------------------------------------------- reservations
	r_filter = {"status": ["in", ["Reserved", "Checked In", "Tentative", "Checked Out", "Cancelled", "No Show"]]}
	if reservations or bookings:
		names = set(reservations or [])
		for b in booking_rows:
			names.update(frappe.get_all("Hotel Booking Room", filters={"parent": b.name, "reservation": ["is", "set"]},
			                            pluck="reservation"))
		r_filter = {"name": ["in", list(names) or [""]]}
	else:
		r_filter["departure_date"] = [">=", add_days(today, -30)]

	rows = frappe.get_all("Hotel Reservation", filters=r_filter,
	                      fields=["name", "status", "room", "room_type", "arrival_date", "departure_date",
	                              "folio", "hotel_booking", "is_company_guest"])
	for r in rows:
		if r.room and r.room_type != frappe.db.get_value("Hotel Room", r.room, "room_type"):
			out.append(_p("room type differs from the room", r.name, _("{0} is not a {1}.").format(r.room, r.room_type)))
		if r.status in ("Reserved", "Checked In") and not r.folio:
			out.append(_p("live stay without a bill", r.name, _("No folio to charge.")))
		if r.folio:
			f = frappe.db.get_value("Guest Folio", r.folio, ["status", "room", "outstanding_balance"], as_dict=True) or {}
			expect = {"Reserved": ("Provisional", "Open"), "Checked In": ("Open",), "Checked Out": ("Closed",),
			          "Cancelled": ("Cancelled", "Closed")}.get(r.status)
			if expect and f.get("status") not in expect:
				out.append(_p("bill status out of step", r.name,
				              _("Stay is {0} but its folio {1} is {2}.").format(r.status, r.folio, f.get("status")),
				              "Medium"))
			if r.status in ("Reserved", "Checked In") and f.get("room") != r.room:
				out.append(_p("bill shows another room", r.name,
				              _("Folio {0} says {1}, stay is in {2}.").format(r.folio, f.get("room"), r.room), "Medium"))
			if r.status == "Checked Out" and not r.is_company_guest and flt(f.get("outstanding_balance")) > 0.01:
				out.append(_p("checked out owing money", r.name,
				              _("Folio {0} still shows {1} due.").format(r.folio, flt(f.get("outstanding_balance")))))
			late, inside = frappe.db.sql(
				"""SELECT SUM(posting_date >= %(dep)s), SUM(posting_date < %(dep)s)
				FROM `tabFolio Transaction` WHERE parent=%(f)s AND item='ROOM-RENT' AND is_void=0""",
				{"f": r.folio, "dep": r.departure_date})[0]
			late = int(late or 0)
			# A stay billed only on its departure day (checked in late, or in and out the
			# same day) used the room once; that one night is the stay, not an extra.
			if late and not int(inside or 0):
				late -= 1
			if late and r.status in ("Checked In", "Checked Out", "Reserved"):
				out.append(_p("night charged after departure", r.name,
				              _("{0} room night(s) on or after the departure date {1}.").format(late, r.departure_date)))
		if r.status in ("Reserved", "Checked In", "Tentative") and r.room:
			clash = frappe.db.sql(
				"""SELECT name FROM `tabHotel Reservation`
				WHERE room=%s AND name!=%s AND status IN ('Tentative','Reserved','Checked In')
				  AND arrival_date < %s AND departure_date > %s LIMIT 1""",
				(r.room, r.name, r.departure_date, r.arrival_date))
			if clash:
				out.append(_p("double-booked room", r.name,
				              _("{0} overlaps {1} in {2}.").format(r.name, clash[0][0], r.room)))
		if r.hotel_booking and not frappe.db.exists("Hotel Booking Room", {"parent": r.hotel_booking, "reservation": r.name}):
			out.append(_p("reservation missing from its booking", r.name,
			              _("Booking {0} has no line for it.").format(r.hotel_booking), "Medium"))

	# ---------------------------------------------------------- rooms (whole hotel only)
	if not (bookings or reservations):
		from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import BLOCKED_STATUSES, current_occupant
		for room in frappe.get_all("Hotel Room", filters={"is_enabled": 1}, fields=["name", "status"]):
			if room.status in BLOCKED_STATUSES:
				continue
			occupied = bool(current_occupant(room.name))
			if occupied and room.status != "Occupied":
				out.append(_p("room status out of step", room.name,
				              _("A guest is checked in but the room says {0}.").format(room.status), "Low"))
			if not occupied and room.status == "Occupied":
				out.append(_p("room status out of step", room.name, _("Says Occupied but nobody is in it."), "Low"))

		dup = frappe.db.sql(
			"""SELECT RIGHT(REGEXP_REPLACE(IFNULL(mobile_no,''),'[^0-9]',''),10) AS phone,
			          GROUP_CONCAT(name ORDER BY creation) AS names, COUNT(*) AS n
			FROM `tabHotel Booking`
			WHERE status IN ('Draft','Tentative','Confirmed','No Show') AND departure_date >= %s
			  AND IFNULL(mobile_no,'') != ''
			GROUP BY phone HAVING n > 1""", (today,), as_dict=True)
		for d in dup:
			out.append(_p("guest booked more than once", d.names.split(",")[0],
			              _("Phone {0} has live bookings {1}: check it is not a date change booked twice.").format(
				              d.phone, d.names), "Medium"))
	return out


def daily_check():
	"""Scheduled: record any broken rule so it is fixed before a guest notices."""
	problems = find_problems()
	high = [p for p in problems if p["severity"] == "High"]
	if high:
		frappe.log_error(
			"\n".join(f"{p['document']}: {p['rule']} — {p['message']}" for p in high),
			f"Hotel booking health: {len(high)} problem(s)",
		)
	return len(problems)
