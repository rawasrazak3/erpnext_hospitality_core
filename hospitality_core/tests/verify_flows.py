"""Every way a booking or stay changes, with the consistency rules checked after each.

For each desk action — book, hold, confirm, pay, change dates or rooms (from the CRM,
the booking form, the reservation form, the dialogs), check in, extend, shorten, move,
check out, forget to check out, cancel (a room, a booking, an in-house guest), no-show,
hold expiry, duplicates — this runs the action and then asserts that
api.integrity.find_problems reports nothing for the records involved: bookings,
reservations, rooms, bills and enquiries all still agree, so every screen tells the
same story.

Rolled back; safe against a live site.

    bench --site <site> execute hospitality_core.tests.verify_flows.run
"""

import json

import frappe
from frappe.utils import add_days, flt, getdate, nowdate

CHECKS = []


def check(label, condition, detail=""):
	CHECKS.append((label, bool(condition), detail))
	print(f"  [{'PASS' if condition else 'FAIL'}] {label}{(' — ' + str(detail)) if detail else ''}")


def run():
	CHECKS.clear()
	try:
		_run()
	except Exception:
		import traceback

		print("\n!!! Aborted:\n")
		traceback.print_exc()
		CHECKS.append(("no exception during run", False, "see traceback"))
	finally:
		frappe.db.rollback()
		print("\nRolled back — no test data persisted.")
	failed = [c for c in CHECKS if not c[1]]
	print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed.")
	if failed:
		for label, _ok, detail in failed:
			print(f"  FAILED: {label} {detail}")
		raise SystemExit(1)


def _run():
	from hospitality_core.hospitality_core.api import advance, front_desk as fd, night_audit as na
	from hospitality_core.hospitality_core.api.availability import is_room_free
	from hospitality_core.hospitality_core.api.integrity import find_problems
	from hospitality_core.hospitality_core.api.room_move import process_room_move
	from hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking import (
		change_booking_dates, release_expired_holds,
	)
	from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import extend_stay
	from hospitality_core.hospitality_core.page.hotel_crm import hotel_crm
	from hospitality_core.hospitality_core.page.hotel_pos import hotel_pos

	today = nowdate()

	def consistent(label, bookings=(), reservations=()):
		problems = find_problems(bookings=list(bookings) or None, reservations=list(reservations) or None)
		check(f"consistent after: {label}", not problems,
		      [f"{p['document']}: {p['rule']} — {p['message']}" for p in problems])

	def rooms_of(rt):
		return frappe.get_all("Hotel Room", filters={"room_type": rt, "is_enabled": 1}, pluck="name", order_by="name")

	def free(arr, dep, rt=None, exclude=()):
		filters = {"is_enabled": 1}
		if rt:
			filters["room_type"] = rt
		for r in frappe.get_all("Hotel Room", filters=filters, fields=["name", "room_type"], order_by="name"):
			if r.name not in exclude and is_room_free(r.name, arr, dep)["free"]:
				return r.name, r.room_type
		raise AssertionError(f"no free room {arr}–{dep} {rt or ''}")

	def booking(guest, arr, dep, lines, status="Draft"):
		return frappe.get_doc({"doctype": "Hotel Booking", "guest": guest, "arrival_date": arr,
		                       "departure_date": dep, "adults": 2, "status": status,
		                       "rooms": lines}).insert(ignore_permissions=True)

	def guest(name, phone):
		return frappe.get_doc({"doctype": "Guest", "full_name": name, "mobile_no": phone}).insert(
			ignore_permissions=True).name

	# Tent House has three identical rooms, which room-change paths need.
	tents = rooms_of("Tent House")
	far = lambda n: add_days(today, n)  # noqa: E731

	# ------------------------------------------------------------ 1. sales path
	print("\n1. Enquiry → hold → confirm → advance")
	enq = hotel_crm.save_enquiry(json.dumps({
		"guest_name": "Flow One", "mobile_no": "+91 90000 91001", "source": "Phone Call",
		"check_in_date": far(200), "check_out_date": far(202),
		"room_lines": [{"room": tents[0], "adults": 2}],
	}))
	b1 = hotel_crm.create_booking_from_enquiry(enq["name"], action="hold")["booking"]
	consistent("hold from the CRM", [b1])
	frappe.get_doc("Hotel Booking", b1).confirm()
	consistent("confirm", [b1])
	advance.record_advance(b1, 2500, "Cash")
	consistent("advance", [b1])

	print("\n2. Dates and rooms changed every way")
	hotel_crm.save_enquiry(json.dumps({"name": enq["name"], "check_in_date": far(205), "check_out_date": far(207)}))
	consistent("dates changed on the enquiry", [b1])
	doc = frappe.get_doc("Hotel Booking", b1)
	doc.arrival_date, doc.departure_date = far(210), far(213)
	doc.save(ignore_permissions=True)
	consistent("dates changed on the booking form", [b1])
	doc.reload(); doc.rooms[0].room = tents[1]; doc.save(ignore_permissions=True)
	consistent("room changed on the booking form", [b1])
	doc.reload(); doc.rooms[0].room_type = "Single Glass House"; doc.save(ignore_permissions=True)
	consistent("room type changed on the booking form", [b1])
	change_booking_dates(b1, far(220), far(221))
	consistent("Change Dates dialog on the booking", [b1])
	res1 = frappe.db.get_value("Hotel Booking Room", {"parent": b1}, "reservation")
	fd.change_stay_dates(res1, far(222), far(224))
	consistent("Change Dates on the stay", [b1])
	r = frappe.get_doc("Hotel Reservation", res1)
	r.departure_date = far(225); r.save(ignore_permissions=True)
	consistent("date changed on the reservation form", [b1])
	r.reload(); other, _t = free(r.arrival_date, r.departure_date, r.room_type, exclude=(r.room,))
	r.room = other; r.save(ignore_permissions=True)
	consistent("room changed on the reservation form", [b1])
	opts = fd.get_move_options(res1)
	fd.move_room(res1, opts[0]["room"])
	consistent("Move Room before arrival", [b1])
	doc.reload()
	doc.append("rooms", {"room_type": "Tent House", "qty": 1, "adults": 2})
	doc.save(ignore_permissions=True)
	consistent("room line added to a confirmed booking", [b1])
	doc.reload()
	check("the added room got a reservation", all(l.reservation for l in doc.rooms))
	two = len(doc.rooms)
	doc.remove(doc.rooms[-1]); doc.save(ignore_permissions=True)
	consistent("room line removed", [b1])
	check("removed line released", len(frappe.get_doc("Hotel Booking", b1).rooms) == two - 1)

	print("\n3. Cancelling one room of two, then the booking")
	g3 = guest("Flow Three", "+91 90000 91003")
	b3 = booking(g3, far(240), far(241), [{"room_type": "Tent House", "qty": 2, "adults": 2}])
	b3.confirm(); b3.reload()
	full = flt(b3.total_amount)
	fd.cancel_stay(b3.rooms[0].reservation, "One room no longer needed")
	b3.reload()
	consistent("one room cancelled", [b3.name])
	check("booking total drops by the cancelled room", flt(b3.total_amount) < full, (full, b3.total_amount))
	b3.cancel_booking(reason="Plans changed")
	consistent("booking cancelled", [b3.name])

	print("\n4. Arrival, stay and departure")
	room4, rt4 = free(today, far(3))
	g4 = guest("Flow Four", "+91 90000 91004")
	b4 = booking(g4, today, far(3), [{"room_type": rt4, "room": room4, "qty": 1, "adults": 2}])
	b4.confirm(); b4.reload(); res4 = b4.rooms[0].reservation
	advance.record_advance(b4.name, 1000, "Cash")
	fd.check_in(res4, id_type="Aadhaar Card", id_number="111122223333")
	consistent("check-in", [b4.name])
	check("room Occupied", frappe.db.get_value("Hotel Room", room4, "status") == "Occupied")
	try:
		frappe.get_doc("Hotel Booking", b4.name).cancel_booking(reason="test")
		check("cancelling a booking with a guest in house is refused", False)
	except frappe.ValidationError:
		check("cancelling a booking with a guest in house is refused", True)
	extend_stay(res4, far(4))
	consistent("extend", [b4.name])
	fd.change_stay_dates(res4, today, far(2))
	consistent("shorten", [b4.name])
	fd.add_charge(res4, "Dinner", 900)
	consistent("charge added", [b4.name])
	opts = fd.get_move_options(res4)
	if opts:
		fd.move_room(res4, opts[0]["room"])
		consistent("Move Room in house", [b4.name])
		check("old room freed", frappe.db.get_value("Hotel Room", room4, "status") == "Available")
	s = fd.get_stay_summary(res4)
	fd.check_out(res4, payment_amount=s["to_collect"], mode_of_payment="Cash")
	consistent("early check-out with invoice", [b4.name])

	print("\n5. Late check-in on the departure day still bills the night")
	room5, rt5 = free(far(-1), today, exclude=(room4,))
	g5 = guest("Flow Five", "+91 90000 91005")
	b5 = booking(g5, far(-1), today, [{"room_type": rt5, "room": room5, "qty": 1, "adults": 2}])
	b5.confirm(); b5.reload(); res5 = b5.rooms[0].reservation
	fd.check_in(res5)
	nights = frappe.db.count("Folio Transaction", {"parent": frappe.db.get_value("Hotel Reservation", res5, "folio"),
	                                               "item": "ROOM-RENT", "is_void": 0})
	check("late check-in billed one night", nights == 1, nights)
	consistent("late check-in", [b5.name])

	print("\n6. Guest nobody checked out")
	s = fd.get_stay_summary(res5)
	frappe.db.set_value("Hotel Reservation", res5, "departure_date", far(-1) if False else today)
	row = frappe.get_all("Hotel Reservation", filters={"name": res5}, fields=na.AUDIT_FIELDS)[0]
	na.process_single_reservation(row, today)
	consistent("audit on the departure day", [b5.name])
	room6, rt6 = room5, rt5
	g6 = guest("Flow Six", "+91 90000 91006")
	b6 = booking(g6, today, far(1), [{"room_type": rt6, "room": room6, "qty": 1, "adults": 1}])
	b6.confirm(); b6.reload()
	fd.check_in(b6.rooms[0].reservation)
	consistent("next guest checked in while the previous is still marked in", [b6.name])
	fd.check_out(res5, payment_amount=fd.get_stay_summary(res5)["to_collect"], mode_of_payment="Cash")
	consistent("forgotten guest checked out late", [b5.name, b6.name])
	check("new guest's room still Occupied", frappe.db.get_value("Hotel Room", room6, "status") == "Occupied")

	print("\n7. Supervisor cancels an in-house stay")
	res6 = b6.rooms[0].reservation
	frappe.get_doc("Hotel Reservation", res6).process_cancel()
	consistent("in-house stay cancelled", [b6.name])
	check("room empty again", frappe.db.get_value("Hotel Room", room6, "status") == "Available")

	print("\n8. No-shows: unpaid cancelled, paid kept, revived by new dates")
	g8 = guest("Flow Eight", "+91 90000 91008")
	e8 = hotel_crm.save_enquiry(json.dumps({
		"guest_name": "Flow Eight", "mobile_no": "+91 90000 91008", "source": "Phone Call",
		"check_in_date": far(-2), "check_out_date": far(-1), "room_lines": [{"room_type": "Tent House", "qty": 1}],
	}))
	frappe.db.set_value("Hotel Enquiry", e8["name"], "mobile_no", "+91 90000 91008")
	room8, _t8 = free(far(-2), far(-1), "Tent House")
	b8 = booking(g8, far(-2), far(-1), [{"room_type": "Tent House", "room": room8, "qty": 1, "adults": 1}])
	frappe.db.set_value("Hotel Booking", b8.name, "enquiry", e8["name"])
	frappe.db.set_value("Hotel Enquiry", e8["name"], "hotel_booking", b8.name)
	b8.reload(); b8.confirm()
	na.cancel_no_shows(today)
	consistent("unpaid no-show cancelled by the audit", [b8.name])
	check("its enquiry is back in the pipeline", not frappe.db.get_value("Hotel Enquiry", e8["name"], "hotel_booking"))

	room9, _t9 = free(far(-2), far(-1), "Tent House", exclude=(room8,))
	b9 = booking(g8, far(-2), far(-1), [{"room_type": "Tent House", "room": room9, "qty": 1, "adults": 1}])
	b9.confirm(); advance.record_advance(b9.name, 1500, "Cash")
	na.cancel_no_shows(today)
	b9.reload()
	check("paid no-show kept as No Show", b9.status == "No Show", b9.status)
	consistent("paid no-show", [b9.name])
	change_booking_dates(b9.name, far(260), far(261))
	consistent("no-show re-dated", [b9.name])

	print("\n9. Holds")
	g10 = guest("Flow Ten", "+91 90000 91010")
	b10 = booking(g10, far(270), far(271), [{"room_type": "Tent House", "room": tents[2], "qty": 1, "adults": 1}])
	b10.set_tentative(1)
	frappe.db.set_value("Hotel Booking", b10.name, "hold_expiry", add_days(today, -1))
	release_expired_holds()
	consistent("expired hold released", [b10.name])
	check("held room free again", is_room_free(tents[2], far(270), far(271))["free"])

	print("\n10. Guards")
	g11 = guest("Flow Eleven", "+91 90000 91011")
	room11, _t11 = free(today, far(1))
	hotel_pos.submit_pos_booking(json.dumps({"arrival": today, "departure": far(1), "rooms": [room11],
	                                         "guest": g11, "adults": 1}))
	try:
		room12, _t12 = free(today, far(1), exclude=(room11,))
		hotel_pos.submit_pos_booking(json.dumps({"arrival": today, "departure": far(1), "rooms": [room12],
		                                         "guest": g11, "adults": 1}))
		check("POS refuses booking the same guest twice for the same nights", False)
	except frappe.ValidationError:
		check("POS refuses booking the same guest twice for the same nights", True)
	r11 = frappe.db.get_value("Hotel Reservation", {"guest": g11, "status": "Reserved"}, "name")
	try:
		frappe.delete_doc("Hotel Reservation", r11, ignore_permissions=True)
		check("a booked stay cannot be deleted", False)
	except frappe.ValidationError:
		check("a booked stay cannot be deleted", True)
	try:
		hotel_crm.set_status(enq["name"], "Lost", lost_reason="Rate too high")
		check("an enquiry with a live booking cannot be marked Lost", False)
	except frappe.ValidationError:
		check("an enquiry with a live booking cannot be marked Lost", True)
	try:
		d = frappe.get_doc("Hotel Booking", b1); d.status = "Cancelled"; d.save(ignore_permissions=True)
		consistent("status edited to Cancelled from the backend", [b1])
	except frappe.ValidationError:
		pass
