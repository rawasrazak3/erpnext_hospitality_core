"""The whole guest journey, CRM to invoice, with the money checked at every step.

    enquiry -> booking (hold) -> POS shows the room Reserved -> confirm -> advance
    -> change dates (repriced) -> check-in (advance applied) -> extend stay (repriced)
    -> check-out with payment -> Sales Invoice (GST, advance allocated, Paid)
    -> ledger balanced: receivable 0, advance liability released, suspense untouched
    plus: walk-in from the POS with check-in now, early departure, cancellation with a
    retained charge.

Picks free rooms on the live inventory, so it runs on any property. Rolled back; safe
against a live site.

    bench --site <site> execute hospitality_core.tests.verify_guest_journey.run
"""

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


def _free_room(arrival, departure, exclude=()):
	from hospitality_core.hospitality_core.api.availability import get_availability

	data = get_availability(arrival, departure, include_soft_holds=False)
	for r in data["rooms"]:
		if r["available"] and r["name"] not in exclude:
			return r["name"], r["room_type"]
	raise AssertionError(f"No free room for {arrival} to {departure}")


def _gl_balance(account, party=None, voucher_like=None):
	conditions = ["account=%s", "is_cancelled=0"]
	params = [account]
	if party:
		conditions.append("party=%s")
		params.append(party)
	return flt(frappe.db.sql(
		f"SELECT SUM(debit-credit) FROM `tabGL Entry` WHERE {' AND '.join(conditions)}", params
	)[0][0])


def _pos_room(data, room):
	return next(r for r in data["rooms"] if r["name"] == room)


def _run():
	from hospitality_core.hospitality_core.api import advance, front_desk
	from hospitality_core.hospitality_core.doctype.hotel_booking import hotel_booking as hb
	from hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation import extend_stay
	from hospitality_core.hospitality_core.page.hotel_crm import hotel_crm
	from hospitality_core.hospitality_core.page.hotel_pos import hotel_pos

	settings = frappe.get_single("Hospitality Accounting Settings")
	today = nowdate()

	# ---------------------------------------------------------------- 1. CRM
	print("\n1. Enquiry comes in and is put on hold with a specific room")
	arrive, leave = add_days(today, 40), add_days(today, 42)
	room, room_type = _free_room(arrive, leave)
	enquiry = frappe.get_doc({
		"doctype": "Hotel Enquiry",
		"guest_name": "Journey Test Guest",
		"mobile_no": "+91 90000 71717",
		"source": "Phone Call",
		"check_in_date": arrive,
		"check_out_date": leave,
		"adults": 2,
		"room_lines": [{"room_type": room_type, "qty": 1, "adults": 2}],
	}).insert(ignore_permissions=True)
	out = hotel_crm.create_booking_from_enquiry(enquiry.name, action="hold")
	booking = frappe.get_doc("Hotel Booking", out["booking"])
	check("hold created as Tentative", booking.status == "Tentative", booking.status)

	# The desk pins the room on the hold.
	booking.rooms[0].room = room
	booking.save(ignore_permissions=True)

	print("\n2. POS sees the held room as Reserved (it used to show it free)")
	data = hotel_pos.get_pos_data(arrive, leave)
	card = _pos_room(data, room)
	check("held room shows Reserved on the POS", card["status"] == "Reserved", card["status"])
	check("POS names the guest", "Journey Test" in (card["occupant"] or {}).get("guest_name", ""),
	      card["occupant"])
	from hospitality_core.hospitality_core.api.availability import is_room_free
	check("held room cannot be sold to someone else",
	      not is_room_free(room, arrive, leave)["free"])
	from hospitality_core.hospitality_core.page.tape_chart.tape_chart import get_chart_data
	chart = get_chart_data(arrive, leave)
	check("tape chart shows the hold",
	      any(b.get("room") == room and b.get("name") == booking.name for b in chart["bookings"]))
	try:
		frappe.get_doc({
			"doctype": "Hotel Reservation", "guest": booking.guest, "room": room,
			"arrival_date": arrive, "departure_date": leave, "status": "Reserved",
		}).insert(ignore_permissions=True)
		check("a reservation for someone else is refused on a held room", False)
	except frappe.ValidationError:
		check("a reservation for someone else is refused on a held room", True)

	print("\n3. Confirm and take an advance")
	booking.reload()
	booking.confirm()
	booking.reload()
	res_name = booking.rooms[0].reservation
	check("confirm created the reservation", bool(res_name))
	check("enquiry marked converted",
	      frappe.db.get_value("Hotel Enquiry", enquiry.name, "converted") == 1)
	card = _pos_room(hotel_pos.get_pos_data(arrive, leave), room)
	check("POS still shows it Reserved after confirm", card["status"] == "Reserved", card["status"])
	check("POS links the reservation", card["occupant"]["reservation"] == res_name)

	advance.record_advance(booking.name, 3000, "Cash", reference_no="JOURNEY-ADV")
	booking.reload()
	check("advance recorded", flt(booking.advance_received) == 3000, booking.advance_received)
	pe_adv = booking.payments[0].payment_entry
	parked = flt(frappe.db.sql(
		"SELECT SUM(credit-debit) FROM `tabGL Entry` WHERE voucher_no=%s AND account=%s AND is_cancelled=0",
		(pe_adv, settings.advance_liability_account),
	)[0][0])
	check("advance parked as a liability, not revenue", parked == 3000, parked)

	print("\n4. Guest postpones by a week — dates move and the price follows")
	old_total = flt(booking.total_amount)
	new_arrive, new_leave = add_days(today, 47), add_days(today, 50)
	preview = hb.preview_booking_dates(booking.name, new_arrive, new_leave)
	check("preview prices 3 nights", preview["nights"] == 3, preview)
	hb.change_booking_dates(booking.name, new_arrive, new_leave)
	booking.reload()
	res = frappe.get_doc("Hotel Reservation", res_name)
	check("reservation moved", str(res.arrival_date) == str(getdate(new_arrive)), res.arrival_date)
	check("booking repriced to the preview", abs(flt(booking.total_amount) - preview["new_total"]) < 1,
	      (booking.total_amount, preview["new_total"]))
	check("3 nights cost more than 2", flt(booking.total_amount) > old_total,
	      (old_total, booking.total_amount))
	check("balance due = total - advance",
	      abs(flt(booking.balance_due) - (flt(booking.total_amount) - 3000)) < 0.01)

	# ---------------------------------------------------------------- 5. arrival
	print("\n5. Arrival day: check-in applies the advance and charges the first night")
	# Bring the stay to today so it can be checked in.
	arrive2, leave2 = today, add_days(today, 2)
	room2, _t = _free_room(arrive2, leave2)
	frappe.db.set_value("Hotel Reservation", res_name, {
		"arrival_date": arrive2, "departure_date": leave2, "room": room2,
	})
	frappe.db.set_value("Hotel Booking Room", booking.rooms[0].name, "room", room2)
	frappe.db.set_value("Hotel Booking", booking.name, {"arrival_date": arrive2, "departure_date": leave2})

	summary = front_desk.get_stay_summary(res_name)
	check("summary allows check-in today", summary["can_check_in"], summary["status"])
	check("summary shows the unapplied advance", flt(summary["unapplied_advance"]) == 3000,
	      summary["unapplied_advance"])
	estimate = summary["stay_estimate_total"]

	after = front_desk.check_in(res_name, id_type="Aadhaar Card", id_number="123412341234")
	check("checked in", after["status"] == "Checked In", after["status"])
	check("advance applied at check-in", flt(after["advance_applied"]) == 3000, after["advance_applied"])
	check("first night on the folio", flt(after["folio"]["total_charges"]) > 0, after["folio"])
	check("guest ID saved",
	      frappe.db.get_value("Guest", res.guest, "aadhaar_number") == "123412341234")
	card = _pos_room(hotel_pos.get_pos_data(today, add_days(today, 1)), room2)
	check("POS shows the room Occupied once checked in", card["status"] == "Occupied", card["status"])
	check("booking moved to Checked In",
	      frappe.db.get_value("Hotel Booking", booking.name, "status") == "Checked In")

	print("\n6. Guest extends by a night — preview, then the booking reprices")
	prev = front_desk.preview_extension(res_name, add_days(leave2, 1))
	check("extension priced", prev["extra_nights"] == 1 and prev["extra_total"] > 0, prev)
	check("room free for the extra night", prev["free"], prev.get("reason"))
	before = flt(frappe.db.get_value("Hotel Booking", booking.name, "total_amount"))
	extend_stay(res_name, add_days(leave2, 1))
	after_total = flt(frappe.db.get_value("Hotel Booking", booking.name, "total_amount"))
	check("booking total grew by the previewed amount",
	      abs((after_total - before) - prev["extra_total"]) < 1, (before, after_total, prev["extra_total"]))
	check("booking departure follows the stay",
	      str(frappe.db.get_value("Hotel Booking", booking.name, "departure_date")) == str(getdate(add_days(leave2, 1))))

	print("\n7. Check-out today (early): settle the balance, invoice, close")
	summary = front_desk.get_stay_summary(res_name)
	check("early departure flagged", summary["early_departure"])
	to_collect = summary["to_collect"]
	result = front_desk.check_out(res_name, payment_amount=to_collect, mode_of_payment="Cash")
	check("checked out", result["status"] == "Checked Out", result["status"])
	check("no invoice error", not result["invoice_error"], result["invoice_error"])
	si = frappe.get_doc("Sales Invoice", result["invoice"]) if result["invoice"] else None
	check("Sales Invoice submitted", si and si.docstatus == 1)
	if si:
		charges = flt(frappe.db.sql(
			"""SELECT SUM(amount) FROM `tabFolio Transaction` WHERE parent=%s AND is_void=0
			AND item NOT IN ('PAYMENT','ADVANCE-TRANSFER','DISCOUNT','COMPLIMENTARY')""",
			(res.folio,))[0][0])
		discounts = abs(flt(frappe.db.sql(
			"""SELECT SUM(amount) FROM `tabFolio Transaction` WHERE parent=%s AND is_void=0
			AND item IN ('DISCOUNT','COMPLIMENTARY')""", (res.folio,))[0][0]))
		check("invoice total = folio charges - discounts",
		      abs(flt(si.grand_total) - (charges - discounts)) < 0.05, (si.grand_total, charges, discounts))
		check("invoice carries GST", len(si.taxes) >= 1 and flt(si.total_taxes_and_charges) > 0,
		      si.total_taxes_and_charges)
		check("invoice is Paid (advance + desk payment allocated)", si.status == "Paid" and
		      flt(si.outstanding_amount) < 0.05, (si.status, si.outstanding_amount))
		check("room rent lines only — no payment lines on the invoice",
		      all(i.item_code not in ("PAYMENT", "ADVANCE-TRANSFER") for i in si.items))
		check("guest's receivable nets to zero",
		      abs(_gl_balance(si.debit_to, si.customer)) < 0.05, _gl_balance(si.debit_to, si.customer))
		parked_left = flt(frappe.db.sql(
			"""SELECT SUM(credit-debit) FROM `tabGL Entry` WHERE account=%s AND is_cancelled=0
			AND (voucher_no=%s OR voucher_no=%s)""",
			(settings.advance_liability_account, pe_adv, si.name))[0][0])
		check("advance released from the liability", abs(parked_left) < 0.05, parked_left)
		sales = flt(frappe.db.sql(
			"SELECT SUM(credit-debit) FROM `tabGL Entry` WHERE voucher_no=%s AND account=%s AND is_cancelled=0",
			(si.name, settings.income_account))[0][0])
		check("revenue booked once, net of GST",
		      abs(sales - flt(si.net_total)) < 0.05, (sales, si.net_total))
	folio = frappe.db.get_value("Guest Folio", res.folio, ["status", "outstanding_balance"], as_dict=True)
	check("folio closed at zero", folio.status == "Closed" and abs(flt(folio.outstanding_balance)) < 0.05, folio)
	check("booking completed",
	      frappe.db.get_value("Hotel Booking", booking.name, "status") == "Completed")
	card = _pos_room(hotel_pos.get_pos_data(add_days(today, 1), add_days(today, 2)), room2)
	check("room free again for tomorrow", card["status"] == "Available", card["status"])

	# ---------------------------------------------------------------- walk-in
	print("\n8. Walk-in at the POS: book, take a payment and check in, in one go")
	room3, _t = _free_room(today, add_days(today, 1), exclude=(room2,))
	pos = hotel_pos.submit_pos_booking(frappe.as_json({
		"arrival": today, "departure": add_days(today, 1),
		"adults": 2, "children": 0, "rooms": [room3],
		"is_new_guest": 1,
		"guest_details": {"full_name": "Walkin Journey", "phone": "+91 90000 72727"},
		"discount_type": "Amount", "discount_value": 500,
		"advance_amount": 1000, "mode_of_payment": "Cash",
		"check_in_now": 1,
	}))
	check("POS created a Hotel Booking", bool(pos["booking"]), pos)
	check("walk-in checked in", len(pos["checked_in"]) == 1, pos["checked_in"])
	wb = frappe.get_doc("Hotel Booking", pos["booking"])
	check("discount taken off the total once (not per night)",
	      abs(flt(wb.discount_amount) - 500) < 0.01, wb.discount_amount)
	wres = pos["reservations"][0]
	card = _pos_room(hotel_pos.get_pos_data(today, add_days(today, 1)), room3)
	check("walk-in room Occupied on the POS", card["status"] == "Occupied", card["status"])
	s = front_desk.get_stay_summary(wres)
	check("walk-in advance applied at check-in", flt(s["unapplied_advance"]) < 0.01, s["unapplied_advance"])
	out = front_desk.check_out(wres, payment_amount=s["to_collect"], mode_of_payment="Cash")
	check("walk-in same-day check-out works", out["status"] == "Checked Out", out)
	check("walk-in invoiced", bool(out["invoice"]) and not out["invoice_error"], out["invoice_error"])

	# ---------------------------------------------------------------- cancellation
	print("\n9. Cancellation keeps part of the advance as a charge")
	arrive4, leave4 = add_days(today, 60), add_days(today, 61)
	room4, room_type4 = _free_room(arrive4, leave4)
	guest = frappe.get_doc({"doctype": "Guest", "full_name": "Cancel Journey",
	                        "mobile_no": "+91 90000 73737"}).insert(ignore_permissions=True)
	cb = frappe.get_doc({
		"doctype": "Hotel Booking", "guest": guest.name, "arrival_date": arrive4,
		"departure_date": leave4, "adults": 2, "status": "Draft",
		"rooms": [{"room_type": room_type4, "room": room4, "qty": 1, "adults": 2}],
	}).insert(ignore_permissions=True)
	cb.confirm()
	advance.record_advance(cb.name, 2000, "Cash")
	cb.reload()
	cb.cancel_booking(reason="Plans changed", cancellation_charge=500)
	inv = frappe.get_all("Sales Invoice", filters={"guest_folio": cb.booking_folio, "docstatus": 1},
	                     fields=["name", "grand_total", "status"])
	check("cancellation charge invoiced", len(inv) == 1 and abs(flt(inv[0].grand_total) - 500) < 0.01, inv)
	check("cancellation invoice paid from the advance", inv and inv[0].status == "Paid", inv)
	refundable = advance.get_advance_balance(cb.name)
	check("remaining advance is refundable", abs(refundable - 1500) < 0.01, refundable)
	check("room released", is_room_free(room4, arrive4, leave4)["free"])

	# ---------------------------------------------------------------- nightly billing
	print("\n10. Extra beds and a per-night discount are billed on every night, and an")
	print("    extension is priced, posted and totalled the same way")
	from hospitality_core.hospitality_core.api import night_audit

	room5, type5 = _free_room(today, add_days(today, 3), exclude=(room2, room3))
	cap = frappe.db.get_value("Hotel Room Type", type5, "max_occupancy") or 2
	bed_rate = flt(frappe.db.get_value("Hotel Room Type", type5, "extra_bed_adult_rate"))
	pos = hotel_pos.submit_pos_booking(frappe.as_json({
		"arrival": today, "departure": add_days(today, 2),
		"adults": int(cap) + 2, "children": 0, "rooms": [room5],
		"is_new_guest": 1, "guest_details": {"full_name": "Beds Journey", "phone": "+91 90000 74747"},
		"discount_type": "Amount", "discount_value": 600,
		"check_in_now": 1,
	}))
	r5 = pos["reservations"][0]
	res5 = frappe.get_doc("Hotel Reservation", r5)
	check("two extra beds on the stay", res5.extra_beds_adult == 2, res5.extra_beds_adult)
	check("booking discount stored per night (600 over 2 nights)", abs(flt(res5.discount_value) - 300) < 0.01,
	      res5.discount_value)

	tomorrow = add_days(today, 1)
	expected = front_desk.price_nights(res5, tomorrow, add_days(tomorrow, 1))[0]
	row = frappe.get_all("Hotel Reservation", filters={"name": r5}, fields=night_audit.AUDIT_FIELDS)[0]
	night_audit.process_single_reservation(row, tomorrow)
	posted = frappe.db.sql(
		"""SELECT SUM(amount) FROM `tabFolio Transaction` WHERE parent=%s AND posting_date=%s
		AND is_void=0 AND item IN ('ROOM-RENT','DISCOUNT')""", (res5.folio, tomorrow))[0][0]
	rent = frappe.db.get_value("Folio Transaction",
		{"parent": res5.folio, "posting_date": tomorrow, "item": "ROOM-RENT"}, "amount")
	check("night audit bills the extra beds", bed_rate <= 0 or flt(rent) >= expected["rate"] + 2 * bed_rate - 0.01,
	      (rent, expected))
	check("audit night = previewed night (rate + beds - discount)", abs(flt(posted) - expected["amount"]) < 0.01,
	      (posted, expected["amount"]))

	prev = front_desk.preview_extension(r5, add_days(today, 3))
	extend_stay(r5, add_days(today, 3))
	b5 = frappe.get_doc("Hotel Booking", pos["booking"])
	folio_total_if_stayed = sum(n["amount"] for n in front_desk.price_nights(
		frappe.get_doc("Hotel Reservation", r5), today, add_days(today, 3)))
	check("booking total = what the folio will bill for the 3 nights",
	      abs(flt(b5.total_amount) - folio_total_if_stayed) < 1, (b5.total_amount, folio_total_if_stayed))
	check("extension adds exactly the previewed amount",
	      abs(flt(b5.total_amount) - (flt(pos["total_amount"]) + prev["extra_total"])) < 1,
	      (pos["total_amount"], prev["extra_total"], b5.total_amount))

	# ---------------------------------------------------------------- the Guests board
	print("\n11. Guests board: every action on one stay from one place")
	fd = front_desk
	arr, dep = add_days(today, 20), add_days(today, 22)
	# Free for the whole span the test later moves the stay through.
	room6, type6 = _free_room(arr, add_days(today, 28), exclude=(room2, room3, room5))
	pos = hotel_pos.submit_pos_booking(frappe.as_json({
		"arrival": arr, "departure": dep, "adults": 2, "rooms": [room6],
		"is_new_guest": 1, "guest_details": {"full_name": "Board Journey", "phone": "+91 90000 75757"},
	}))
	r6 = pos["reservations"][0]
	board = fd.get_stays(view="upcoming", search="Board Journey")
	check("upcoming stay listed on the board", any(o["name"] == r6 for o in board["rows"]), board["rows"])
	check("counts per view returned", "live" in board["counts"] and "upcoming" in board["counts"])

	pay = fd.take_payment(1500, "Cash", reservation=r6)
	check("payment before arrival held as advance", pay["where"] == "advance", pay)
	check("advance on the booking",
	      flt(frappe.db.get_value("Hotel Booking", pos["booking"], "advance_received")) == 1500)

	p = fd.preview_date_change(r6, add_days(today, 25), add_days(today, 28))
	check("date change preview: 3 nights", p["new"]["nights"] == 3, p["new"])
	fd.change_stay_dates(r6, add_days(today, 25), add_days(today, 28))
	moved = frappe.get_doc("Hotel Reservation", r6)
	b6 = frappe.get_doc("Hotel Booking", pos["booking"])
	check("reservation moved to the new dates", str(moved.arrival_date) == str(getdate(add_days(today, 25))))
	check("booking total equals the preview", abs(flt(b6.total_amount) - p["new"]["total"]) < 1,
	      (b6.total_amount, p["new"]["total"]))

	opts = fd.get_move_options(r6)
	if opts:
		target = opts[0]["room"]
		fd.move_room(r6, target)
		check("room changed before arrival", frappe.db.get_value("Hotel Reservation", r6, "room") == target)
		check("booking line follows the room",
		      frappe.db.get_value("Hotel Booking Room", {"parent": pos["booking"]}, "room") == target)

	fd.cancel_stay(r6, "Changed plans", cancellation_charge=400)
	check("cancel from the board cancels the booking",
	      frappe.db.get_value("Hotel Booking", pos["booking"], "status") == "Cancelled")
	check("cancellation charge invoiced from the advance",
	      frappe.db.exists("Sales Invoice", {"guest_folio": b6.booking_folio, "docstatus": 1, "grand_total": 400}))

	print("\n12. In house: charge, shorten, move, pay, check out")
	room7, _t7 = _free_room(today, add_days(today, 3), exclude=(room2, room3, room5))
	pos = hotel_pos.submit_pos_booking(frappe.as_json({
		"arrival": today, "departure": add_days(today, 3), "adults": 2, "rooms": [room7],
		"is_new_guest": 1, "guest_details": {"full_name": "House Journey", "phone": "+91 90000 76767"},
		"check_in_now": 1,
	}))
	r7 = pos["reservations"][0]
	live = fd.get_stays(view="inhouse", search="House Journey")
	check("in-house guest listed with a balance", any(o["name"] == r7 and o["due"] > 0 for o in live["rows"]),
	      live["rows"])

	s = fd.add_charge(r7, "Dinner for two", 1200)
	check("charge on the bill", any(l["description"] == "Dinner for two" for l in s["lines"]))

	fd.change_stay_dates(r7, today, add_days(today, 2))
	check("stay shortened by a night", str(frappe.db.get_value("Hotel Reservation", r7, "departure_date"))
	      == str(getdate(add_days(today, 2))))
	try:
		fd.change_stay_dates(r7, add_days(today, 1), add_days(today, 2))
		check("in-house arrival cannot move", False)
	except frappe.ValidationError:
		check("in-house arrival cannot move", True)

	opts = fd.get_move_options(r7)
	if opts:
		old_room = room7
		fd.move_room(r7, opts[0]["room"])
		check("in-house move frees the old room",
		      frappe.db.get_value("Hotel Room", old_room, "status") == "Available")

	pay = fd.take_payment(500, "Cash", reservation=r7)
	check("payment in house goes on the folio", pay["where"] == "folio", pay)
	s = fd.get_stay_summary(r7)
	out = fd.check_out(r7, payment_amount=s["to_collect"], mode_of_payment="Cash")
	inv = frappe.get_doc("Sales Invoice", out["invoice"]) if out["invoice"] else None
	check("check-out invoice includes the added charge",
	      inv and any("Dinner for two" in (i.description or "") for i in inv.items))
	check("invoice paid in full", inv and inv.status == "Paid", inv and inv.status)

	# ---------------------------------------------------------------- 4 PM to 4 PM nights
	print("\n13. Rooms are let by night: a guest nobody checked out never blocks the next one")
	from hospitality_core.hospitality_core.api import night_audit as na
	from hospitality_core.hospitality_core.api.stay_policy import get_stay_times

	check_in_t, check_out_t = get_stay_times()
	yday, d2 = add_days(today, -1), add_days(today, -2)

	def past_stay(room, name, arrival, departure, nights_charged):
		"""A checked-in stay moved into the past, as if checked in on `arrival`."""
		p = hotel_pos.submit_pos_booking(frappe.as_json({
			"arrival": today, "departure": add_days(today, 1), "adults": 1, "rooms": [room],
			"is_new_guest": 1, "guest_details": {"full_name": name, "phone": "+91 90000 7%04d" % (hash(name) % 10000)},
			"check_in_now": 1,
		}))
		r = frappe.get_doc("Hotel Reservation", p["reservations"][0])
		frappe.db.set_value("Hotel Reservation", r.name, {"arrival_date": arrival, "departure_date": departure})
		rent = frappe.get_all("Folio Transaction", filters={"parent": r.folio, "item": ["in", ["ROOM-RENT", "DISCOUNT"]]}, pluck="name")
		for t in rent:
			frappe.db.set_value("Folio Transaction", t, "posting_date", arrival)
		for extra in nights_charged[1:]:
			na.post_room_charge(frappe.get_doc("Hotel Reservation", r.name), 1000, extra)
		from hospitality_core.hospitality_core.api.folio import sync_folio_balance
		sync_folio_balance(frappe.get_doc("Guest Folio", r.folio))
		return frappe.get_doc("Hotel Reservation", r.name)

	room8, _t8 = _free_room(today, add_days(today, 2), exclude=(room2, room3, room5, room7))
	forgot = past_stay(room8, "Forgot Journey", d2, yday, [d2])
	check("forgotten guest is still Checked In", forgot.status == "Checked In")
	check("their room is free tonight", is_room_free(room8, today, add_days(today, 1))["free"])
	stage = next((o["stage"] for o in fd.get_stays(view="dueout", search="Forgot Journey")["rows"]), None)
	check("listed as Check-out pending", stage == "Check-out pending", stage)

	lines_before = frappe.db.count("Folio Transaction", {"parent": forgot.folio, "is_void": 0})
	row = frappe.get_all("Hotel Reservation", filters={"name": forgot.name}, fields=na.AUDIT_FIELDS)[0]
	na.process_single_reservation(row, today)
	check("audit adds no night past departure",
	      frappe.db.count("Folio Transaction", {"parent": forgot.folio, "is_void": 0}) == lines_before)
	check("audit does not extend the stay",
	      str(frappe.db.get_value("Hotel Reservation", forgot.name, "departure_date")) == str(getdate(yday)))

	nxt = hotel_pos.submit_pos_booking(frappe.as_json({
		"arrival": today, "departure": add_days(today, 1), "adults": 1, "rooms": [room8],
		"is_new_guest": 1, "guest_details": {"full_name": "Next Journey", "phone": "+91 90000 78787"},
		"check_in_now": 1,
	}))
	check("next guest booked and checked in on the same room", len(nxt["checked_in"]) == 1, nxt)
	nres = frappe.get_doc("Hotel Reservation", nxt["reservations"][0])
	check("standard check-in time stamped", str(nres.arrival_time).zfill(8) == check_in_t, nres.arrival_time)
	check("standard check-out time stamped", str(nres.departure_time).zfill(8) == check_out_t, nres.departure_time)
	card = _pos_room(hotel_pos.get_pos_data(today, add_days(today, 1)), room8)
	check("POS shows the new guest, not the forgotten one",
	      card["status"] == "Occupied" and card["occupant"]["reservation"] == nres.name, card["occupant"])

	s = fd.get_stay_summary(forgot.name)
	check("check-out pending flagged on the bill", s["checkout_pending"])
	out = fd.check_out(forgot.name, payment_amount=s["to_collect"], mode_of_payment="Cash")
	check("forgotten guest checks out without extending", out["status"] == "Checked Out"
	      and str(frappe.db.get_value("Hotel Reservation", forgot.name, "departure_date")) == str(getdate(yday)))
	inv = frappe.get_doc("Sales Invoice", out["invoice"]) if out["invoice"] else None
	check("their invoice has only the booked night", inv and len(inv.items) == 1, inv and len(inv.items))
	check("new guest's room stays Occupied after the late check-out",
	      frappe.db.get_value("Hotel Room", room8, "status") == "Occupied")

	print("\n14. Auto check-out after check-out time: settled bills only")
	room9, _t9 = _free_room(today, add_days(today, 1), exclude=(room2, room3, room5, room7, room8))
	paid = past_stay(room9, "Paid Journey", d2, yday, [d2])
	fd.take_payment(fd.get_stay_summary(paid.name)["to_collect"], "Cash", reservation=paid.name)
	room10, _t10 = _free_room(today, add_days(today, 1), exclude=(room2, room3, room5, room7, room8, room9))
	owing = past_stay(room10, "Owing Journey", d2, yday, [d2])
	done = fd.auto_check_out()
	check("settled stay checked out automatically", paid.name in done, done)
	check("auto check-out raised the invoice",
	      frappe.db.exists("Sales Invoice", {"guest_folio": paid.folio, "docstatus": 1}))
	check("stay with money due left for the desk",
	      owing.name not in done and frappe.db.get_value("Hotel Reservation", owing.name, "status") == "Checked In")

	print("\n15. Extending a forgotten guest who really stayed bills the missed nights")
	before = frappe.db.count("Folio Transaction", {"parent": owing.folio, "item": "ROOM-RENT", "is_void": 0})
	extend_stay(owing.name, add_days(today, 1))
	after = frappe.db.count("Folio Transaction", {"parent": owing.folio, "item": "ROOM-RENT", "is_void": 0})
	check("yesterday and tonight billed on extension", after - before == 2, (before, after))
	check("running the catch-up again charges nothing twice",
	      na.post_due_nights(frappe.get_doc("Hotel Reservation", owing.name), today) == 0)
	waived = frappe.db.get_value("Folio Transaction",
		{"parent": owing.folio, "item": "ROOM-RENT", "posting_date": today, "is_void": 0}, "name")
	frappe.db.set_value("Folio Transaction", waived, {"is_void": 1, "void_reason": "Waived"})
	check("a night the desk voided is not re-billed",
	      na.post_due_nights(frappe.get_doc("Hotel Reservation", owing.name), today) == 0)

	print("\n16. Standard times everywhere")
	enq = frappe.get_doc({
		"doctype": "Hotel Enquiry", "guest_name": "Times Journey", "mobile_no": "+91 90000 79797",
		"source": "Phone Call", "check_in_date": add_days(today, 70), "check_out_date": add_days(today, 71),
		"adults": 1, "room_lines": [{"room_type": type6, "qty": 1, "adults": 1}],
	}).insert(ignore_permissions=True)
	bk = frappe.get_doc("Hotel Booking", hotel_crm.create_booking_from_enquiry(enq.name, action="confirm")["booking"])
	rr = frappe.get_doc("Hotel Reservation", bk.rooms[0].reservation)
	check("CRM booking carries the standard times",
	      str(bk.arrival_time).zfill(8) == check_in_t and str(bk.departure_time).zfill(8) == check_out_t,
	      (bk.arrival_time, bk.departure_time))
	check("its reservation too",
	      str(rr.arrival_time).zfill(8) == check_in_t and str(rr.departure_time).zfill(8) == check_out_t)
	pos_times = hotel_pos.get_pos_data(today, add_days(today, 1))
	check("POS reports the standard times",
	      pos_times["check_in_time"] == check_in_t and pos_times["check_out_time"] == check_out_t)

	# ---------------------------------------------------------------- CRM by room
	print("\n17. CRM offers rooms, not just room types")
	import json as _json
	arr, dep = add_days(today, 80), add_days(today, 82)
	free = [r for r in frappe.get_all("Hotel Room", filters={"is_enabled": 1}, fields=["name", "room_type"])
	        if is_room_free(r.name, arr, dep)["free"]]
	ra, rb = free[0], free[1]
	console = hotel_crm.get_console_data()
	check("console lists rooms with their type",
	      any(r.name == ra.name and r.room_type == ra.room_type for r in console["rooms"]))

	saved = hotel_crm.save_enquiry(_json.dumps({
		"guest_name": "Room Pick Journey", "mobile_no": "+91 90000 81818", "source": "Phone Call",
		"check_in_date": arr, "check_out_date": dep, "adults": 4,
		"room_lines": [{"room": ra.name, "adults": 2}, {"room": rb.name, "adults": 2, "qty": 3}],
	}))
	lines = saved["room_lines"]
	check("room type filled from the room", lines[0]["room_type"] == ra.room_type, lines[0]["room_type"])
	check("a room line is always one room", all(l["qty"] == 1 for l in lines), [l["qty"] for l in lines])
	check("quote priced per room", flt(saved["quoted_total"]) > 0, saved["quoted_total"])

	try:
		hotel_crm.save_enquiry(_json.dumps({"name": saved["name"],
			"room_lines": [{"room": ra.name}, {"room": ra.name}]}))
		check("the same room twice is refused", False)
	except frappe.ValidationError:
		check("the same room twice is refused", True)

	rival = hotel_crm.save_enquiry(_json.dumps({
		"guest_name": "Rival Journey", "mobile_no": "+91 90000 82828", "source": "Phone Call",
		"check_in_date": arr, "check_out_date": dep, "room_lines": [{"room": ra.name}],
	}))
	av = hotel_crm.get_stay_availability(arr, dep, exclude_enquiry=saved["name"])
	check("availability says which other enquiry wants the room",
	      "Rival Journey" in (av["contention"]["by_room"].get(ra.name) or []), av["contention"].get("by_room"))

	b = hotel_crm.get_board(date_field="staying", from_date=arr, to_date=arr, room=ra.name)
	names = [r["name"] for rows in b["grouped"].values() for r in rows]
	check("pipeline filters by room", saved["name"] in names and rival["name"] in names, names)
	b2 = hotel_crm.get_board(date_field="staying", from_date=arr, to_date=arr, room=rb.name)
	names2 = [r["name"] for rows in b2["grouped"].values() for r in rows]
	check("room filter excludes enquiries for other rooms", rival["name"] not in names2, names2)
	check("pipeline counts requests per room",
	      any(x["room"] == ra.name and x["enquiries"] == 2 for x in b["room_requests"]), b["room_requests"])
	card = next(r for rows in b["grouped"].values() for r in rows if r["name"] == saved["name"])
	check("card carries the rooms", {x.get("room") for x in card["rooms"]} == {ra.name, rb.name}, card["rooms"])
	b3 = hotel_crm.get_board(date_field="staying", from_date=arr, to_date=arr, room_type=ra.room_type)
	check("room type filter still works",
	      saved["name"] in [r["name"] for rows in b3["grouped"].values() for r in rows])

	out = hotel_crm.create_booking_from_enquiry(saved["name"], action="hold")
	hb = frappe.get_doc("Hotel Booking", out["booking"])
	check("booking holds exactly the chosen rooms", {l.room for l in hb.rooms} == {ra.name, rb.name},
	      [l.room for l in hb.rooms])
	check("the chosen room is now blocked for others", not is_room_free(ra.name, arr, dep)["free"])

	legacy = hotel_crm.save_enquiry(_json.dumps({
		"guest_name": "Type Only Journey", "mobile_no": "+91 90000 83838", "source": "Phone Call",
		"check_in_date": arr, "check_out_date": dep,
		"room_lines": [{"room_type": ra.room_type, "qty": 2}],
	}))
	check("a request by type only still works", legacy["room_lines"][0]["qty"] == 2
	      and not legacy["room_lines"][0].get("room"))

	# ---------------------------------------------------------------- sales dashboard
	print("\n18. Sales dashboard and report agree with what happened")
	from hospitality_core.hospitality_core.api import sales_dashboard as sd
	from hospitality_core.hospitality_core.report.hotel_sales_report.hotel_sales_report import execute as sales_report

	before = sd.get_dashboard(today, today)
	room11, _t11 = _free_room(today, add_days(today, 1), exclude=(room2, room3, room5, room7, room8, room9, room10))
	pos = hotel_pos.submit_pos_booking(frappe.as_json({
		"arrival": today, "departure": add_days(today, 1), "adults": 1, "rooms": [room11],
		"is_new_guest": 1, "guest_details": {"full_name": "Dash Journey", "phone": "+91 90000 84848"},
		"advance_amount": 777, "mode_of_payment": "Cash", "check_in_now": 1,
	}))
	charge = flt(frappe.db.sql("""SELECT SUM(amount) FROM `tabFolio Transaction` ft JOIN `tabGuest Folio` f ON f.name=ft.parent
		WHERE f.reservation=%s AND ft.item IN ('ROOM-RENT','DISCOUNT') AND ft.is_void=0""", pos["reservations"][0])[0][0])
	after = sd.get_dashboard(today, today)
	check("revenue includes the night just charged",
	      abs((after["revenue"]["net"] - before["revenue"]["net"]) - charge) < 0.01,
	      (before["revenue"]["net"], after["revenue"]["net"], charge))
	check("advance counted as collected and as an advance",
	      abs(after["collections"]["advances"] - before["collections"]["advances"] - 777) < 0.01)
	cash_b = next((m["net"] for m in before["modes"] if m["mode"] == "Cash"), 0)
	cash_a = next((m["net"] for m in after["modes"] if m["mode"] == "Cash"), 0)
	check("shown under its mode of payment", abs(cash_a - cash_b - 777) < 0.01, (cash_b, cash_a))
	check("advance applied at check-in counted", after["advances"]["applied"] >= 777)
	check("payment listed in the register",
	      any(p["amount"] == 777 and p["kind"] == "Advance" for p in after["payments"]))
	check("room night counted in occupancy",
	      after["occupancy"]["nights_sold"] >= before["occupancy"]["nights_sold"] + 1)

	cols, data, _m, _c, summary = sales_report({"from_date": today, "to_date": today, "group_by": "Day"})
	total = data[-1]
	check("report revenue = dashboard revenue", abs(total["net_revenue"] - after["revenue"]["net"]) < 0.01,
	      (total["net_revenue"], after["revenue"]["net"]))
	check("report collections = dashboard collections",
	      abs(total["collections"] - after["collections"]["net"]) < 0.01)
	check("report has a column per payment mode", any(c["label"].startswith("Cash") for c in cols))
	week = sd.get_dashboard(add_days(today, -6), today)
	check("weekly view compares with the week before",
	      week["previous"]["to_date"] == str(getdate(add_days(today, -7))) and week["days"] == 7)

	# ---------------------------------------------------------------- form edits stay in step
	print("\n19. Editing a booking or reservation on its form keeps every screen in step")
	from hospitality_core.hospitality_core.page.front_desk_console.front_desk_console import get_console_data

	def booked_on(room, day):
		return not is_room_free(room, day, add_days(day, 1))["free"]

	def two_free_of_a_type(arr, dep):
		by_type = {}
		for r in frappe.get_all("Hotel Room", filters={"is_enabled": 1}, fields=["name", "room_type"]):
			if is_room_free(r.name, arr, dep)["free"]:
				by_type.setdefault(r.room_type, []).append(r.name)
		return next((t, rooms) for t, rooms in by_type.items() if len(rooms) >= 2)

	g = frappe.get_doc({"doctype": "Guest", "full_name": "Edit Journey",
	                    "mobile_no": "+91 90000 85858"}).insert(ignore_permissions=True)

	# a. Confirmed by editing the status (how HB-2026-00087 lost its reservation).
	arr = today
	rt_a, rooms_a = two_free_of_a_type(arr, add_days(arr, 1))
	hold = frappe.get_doc({"doctype": "Hotel Booking", "guest": g.name, "arrival_date": arr,
	                       "departure_date": add_days(arr, 1), "adults": 2, "status": "Tentative",
	                       "rooms": [{"room_type": rt_a, "qty": 1, "adults": 2}]}).insert(ignore_permissions=True)
	console = get_console_data(today)
	check("a hold arriving today is on the Front Desk",
	      any(a.get("kind") == "booking" and a["name"] == hold.name for a in console["arrivals"]))
	hold.reload(); hold.status = "Confirmed"; hold.save(ignore_permissions=True); hold.reload()
	check("confirming by editing the status still creates the reservation",
	      all(l.reservation and l.room for l in hold.rooms), [(l.room, l.reservation) for l in hold.rooms])
	console = get_console_data(today)
	check("it is on the Front Desk as an arrival",
	      any(a["name"] == hold.rooms[0].reservation for a in console["arrivals"]))
	check("its room is blocked", booked_on(hold.rooms[0].room, arr))

	# b. Dates edited on the booking form.
	a1, a2 = add_days(today, 90), add_days(today, 92)
	rt_b, rooms_b = two_free_of_a_type(a1, a2)
	bk = frappe.get_doc({"doctype": "Hotel Booking", "guest": g.name, "arrival_date": a1,
	                     "departure_date": a2, "adults": 2, "status": "Draft",
	                     "rooms": [{"room_type": rt_b, "room": rooms_b[0], "qty": 1, "adults": 2}]}).insert(ignore_permissions=True)
	bk.confirm(); bk.reload()
	res_b = bk.rooms[0].reservation
	n1, n2 = add_days(today, 100), add_days(today, 103)
	bk.arrival_date, bk.departure_date = n1, n2
	bk.save(ignore_permissions=True); bk.reload()
	r = frappe.get_doc("Hotel Reservation", res_b)
	check("reservation moved with the booking's new dates",
	      str(r.arrival_date) == str(getdate(n1)) and str(r.departure_date) == str(getdate(n2)),
	      (r.arrival_date, r.departure_date))
	check("old dates free again on the POS", not booked_on(r.room, a1))
	card = _pos_room(hotel_pos.get_pos_data(n1, n2), r.room)
	check("new dates show Reserved on the POS", card["status"] == "Reserved", card["status"])
	check("booking repriced for 3 nights", bk.nights == 3 and flt(bk.total_amount) > 0, (bk.nights, bk.total_amount))

	# c. New dates clash with someone else in that room: another room of the type is used.
	other = frappe.get_doc({"doctype": "Hotel Booking", "guest": g.name, "arrival_date": add_days(today, 110),
	                        "departure_date": add_days(today, 111), "adults": 1, "status": "Draft",
	                        "rooms": [{"room_type": rt_b, "room": r.room, "qty": 1, "adults": 1}]}).insert(ignore_permissions=True)
	other.confirm()
	bk.arrival_date, bk.departure_date = add_days(today, 110), add_days(today, 111)
	bk.save(ignore_permissions=True); bk.reload()
	moved = frappe.get_doc("Hotel Reservation", res_b)
	check("clash on the new date moves the guest to another room of the type",
	      moved.room != r.room and moved.room_type == rt_b and bk.rooms[0].room == moved.room, moved.room)
	taken_room = other.rooms[0].room
	bk.reload(); bk.rooms[0].room = taken_room
	try:
		bk.save(ignore_permissions=True)
		check("picking a room that is taken is refused", False)
	except frappe.ValidationError:
		check("picking a room that is taken is refused", True)

	# d. Room changed on the form.
	bk.reload()
	free_rooms = [x for x in frappe.get_all("Hotel Room", filters={"room_type": rt_b, "is_enabled": 1}, pluck="name")
	              if x != bk.rooms[0].room and is_room_free(x, bk.arrival_date, bk.departure_date)["free"]]
	if free_rooms:
		old_room = bk.rooms[0].room
		bk.rooms[0].room = free_rooms[0]
		bk.save(ignore_permissions=True)
		check("room changed on the form moves the reservation",
		      frappe.db.get_value("Hotel Reservation", res_b, "room") == free_rooms[0])
		check("the previous room is free again", not booked_on(old_room, bk.arrival_date))

	# e. A room line removed from a two-room booking.
	two = frappe.get_doc({"doctype": "Hotel Booking", "guest": g.name, "arrival_date": add_days(today, 120),
	                      "departure_date": add_days(today, 121), "adults": 2, "status": "Draft",
	                      "rooms": [{"room_type": rt_b, "qty": 2, "adults": 2}]}).insert(ignore_permissions=True)
	two.confirm(); two.reload()
	dropped = two.rooms[1].reservation
	two.remove(two.rooms[1]); two.save(ignore_permissions=True)
	check("a removed room line releases its reservation",
	      frappe.db.get_value("Hotel Reservation", dropped, "status") == "Cancelled")

	# f. A checked-in booking cannot be re-dated from the booking form.
	hold.reload()
	from hospitality_core.hospitality_core.api import front_desk as fdk
	fdk.check_in(hold.rooms[0].reservation)
	hold.reload(); hold.departure_date = add_days(today, 3)
	try:
		hold.save(ignore_permissions=True)
		check("checked-in booking dates are changed on the guest, not the form", False)
	except frappe.ValidationError:
		check("checked-in booking dates are changed on the guest, not the form", True)

	# g. Reservation edited on its own form: the booking follows.
	r = frappe.get_doc("Hotel Reservation", res_b)
	r.departure_date = add_days(r.departure_date, 2)
	r.save(ignore_permissions=True)
	b_dep = frappe.db.get_value("Hotel Booking", bk.name, ["departure_date", "nights"], as_dict=True)
	check("booking follows a reservation edited on its form",
	      str(b_dep.departure_date) == str(getdate(r.departure_date)) and b_dep.nights == 3, b_dep)

	# h. A no-show moved to new dates is live again.
	frappe.db.set_value("Hotel Reservation", res_b, "status", "No Show")
	frappe.db.set_value("Hotel Booking", bk.name, "status", "No Show")
	bk.reload(); bk.arrival_date, bk.departure_date = add_days(today, 130), add_days(today, 131)
	bk.save(ignore_permissions=True)
	check("a no-show moved to new dates is reserved again",
	      frappe.db.get_value("Hotel Reservation", res_b, "status") == "Reserved"
	      and frappe.db.get_value("Hotel Booking", bk.name, "status") == "Confirmed")

	# ---------------------------------------------------------------- CRM date changes
	print("\n20. Changing dates from the CRM moves the booking; no accidental second booking")
	from hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking import change_booking_dates
	d1, d2 = add_days(today, 140), add_days(today, 141)
	r20, t20 = _free_room(d1, d2)
	enq = hotel_crm.save_enquiry(_json.dumps({
		"guest_name": "Move Journey", "mobile_no": "+91 90000 87878", "source": "Phone Call",
		"check_in_date": d1, "check_out_date": d2, "room_lines": [{"room": r20, "adults": 2}],
	}))
	b20 = hotel_crm.create_booking_from_enquiry(enq["name"], action="confirm")["booking"]
	res20 = frappe.db.get_value("Hotel Booking Room", {"parent": b20}, "reservation")

	n1, n2 = add_days(today, 150), add_days(today, 152)
	hotel_crm.save_enquiry(_json.dumps({"name": enq["name"], "check_in_date": n1, "check_out_date": n2}))
	rr = frappe.db.get_value("Hotel Reservation", res20, ["arrival_date", "departure_date", "status"], as_dict=True)
	check("new dates on the enquiry move the booking's reservation",
	      str(rr.arrival_date) == str(getdate(n1)) and str(rr.departure_date) == str(getdate(n2)), rr)
	check("booking follows the enquiry",
	      str(frappe.db.get_value("Hotel Booking", b20, "arrival_date")) == str(getdate(n1)))
	check("old dates are free again", is_room_free(r20, d1, d2)["free"])

	change_booking_dates(b20, add_days(today, 155), add_days(today, 156))
	e = frappe.db.get_value("Hotel Enquiry", enq["name"], ["check_in_date", "check_out_date"], as_dict=True)
	check("changing the booking's dates updates the enquiry",
	      str(e.check_in_date) == str(getdate(add_days(today, 155))), e)

	again = hotel_crm.save_enquiry(_json.dumps({
		"guest_name": "Move Journey", "mobile_no": "+91 90000 87878", "source": "Phone Call",
		"check_in_date": add_days(today, 170), "check_out_date": add_days(today, 171),
		"room_lines": [{"room_type": t20, "qty": 1}],
	}))
	check("the CRM sees the guest's existing booking",
	      any(x.name == b20 for x in hotel_crm.get_live_bookings_for_enquiry(again["name"])))
	try:
		hotel_crm.create_booking_from_enquiry(again["name"], action="hold")
		check("a second booking for the same guest needs confirming", False)
	except frappe.ValidationError:
		check("a second booking for the same guest needs confirming", True)
	extra = hotel_crm.create_booking_from_enquiry(again["name"], action="hold", additional_stay=1)
	check("an additional stay can still be booked on purpose", bool(extra.get("booking")))

	frappe.db.set_value("Hotel Reservation", res20, "status", "No Show")
	frappe.db.set_value("Hotel Booking", b20, "status", "No Show")
	change_booking_dates(b20, add_days(today, 160), add_days(today, 161))
	check("a no-show re-dated is live again",
	      frappe.db.get_value("Hotel Booking", b20, "status") == "Confirmed"
	      and frappe.db.get_value("Hotel Reservation", res20, "status") == "Reserved")

	# an in-house stay is not re-dated from the CRM (the guest checked in in section 19)
	wb = frappe.get_doc("Hotel Booking", hold.name)
	e2 = frappe.get_doc({"doctype": "Hotel Enquiry", "guest_name": "Edit Journey", "mobile_no": "+91 90000 85858",
	                     "source": "Walk-in", "check_in_date": wb.arrival_date, "check_out_date": wb.departure_date,
	                     "room_lines": [{"room": wb.rooms[0].room}]}).insert(ignore_permissions=True)
	frappe.db.set_value("Hotel Enquiry", e2.name, "hotel_booking", wb.name)
	frappe.db.set_value("Hotel Booking", wb.name, "enquiry", e2.name)
	check("that booking is in house", wb.status == "Checked In", wb.status)
	try:
		hotel_crm.save_enquiry(_json.dumps({"name": e2.name, "check_in_date": add_days(today, 5), "check_out_date": add_days(today, 6)}))
		check("an in-house stay is not re-dated from the CRM", False)
	except frappe.ValidationError:
		check("an in-house stay is not re-dated from the CRM", True)
