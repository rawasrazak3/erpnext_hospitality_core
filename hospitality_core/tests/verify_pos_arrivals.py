"""Check the POS can pull a booking made by the sales team and check it in.

This is the handoff the plan was built around: sales takes an advance days earlier, the
front desk opens that same booking and the advance is already applied.

Rolled back; safe against a live site.

    bench --site <site> execute hospitality_core.tests.verify_pos_arrivals.run
"""

import frappe
from frappe.utils import add_days, flt, nowdate

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append((label, bool(condition), detail))
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{(' — ' + str(detail)) if detail else ''}")


def run():
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
    from hospitality_core.hospitality_core.api import advance
    from hospitality_core.hospitality_core.page.hotel_pos import hotel_pos

    today = nowdate()
    departure = add_days(today, 2)

    print("\n1. Sales creates a booking arriving today, takes an advance")
    guest = frappe.get_doc({
        "doctype": "Guest", "full_name": "Arrival Test Guest",
        "mobile_no": "+91 90000 55555", "guest_type": "Regular",
    }).insert(ignore_permissions=True)

    booking = frappe.get_doc({
        "doctype": "Hotel Booking",
        "guest": guest.name,
        "arrival_date": today,
        "departure_date": departure,
        "adults": 4,
        "status": "Draft",
        "special_requests": "Late arrival, ground floor please",
        "rooms": [{"room_type": "Deluxe Room", "qty": 2, "adults": 2, "rate": 4500}],
    }).insert(ignore_permissions=True)
    booking.confirm()
    booking.reload()

    advance.record_advance(booking.name, 8000, "Cash", reference_no="ADV-POS-1")
    booking.reload()
    check("booking confirmed with 2 rooms", len(booking.rooms) == 2, len(booking.rooms))
    check("advance held", flt(booking.advance_received) == 8000, booking.advance_received)
    # 2 rooms x 2 nights x 4500 = 18000, less 8000
    check("balance due", flt(booking.balance_due) == 10000, booking.balance_due)

    print("\n2. Front desk finds it in Arrivals")
    arrivals = hotel_pos.get_arrivals(today)
    names = [b["name"] for b in arrivals["bookings"]]
    check("booking appears in today's arrivals", booking.name in names, names)

    row = next(b for b in arrivals["bookings"] if b["name"] == booking.name)
    check("advance shown on the row", flt(row["advance_received"]) == 8000, row["advance_received"])
    check("balance shown on the row", flt(row["balance_due"]) == 10000, row["balance_due"])
    check("room count shown", row["room_count"] == 2, row["room_count"])

    print("\n3. Search by phone finds it")
    by_phone = hotel_pos.get_arrivals(today, search="9000055555")
    check("found by phone digits",
          any(b["name"] == booking.name for b in by_phone["bookings"]), by_phone["bookings"])
    by_name = hotel_pos.get_arrivals(today, search="Arrival Test")
    check("found by name",
          any(b["name"] == booking.name for b in by_name["bookings"]))

    print("\n4. Detail carries what the desk needs")
    detail = hotel_pos.get_arrival_detail(booking=booking.name)
    check("detail is a booking", detail["type"] == "booking")
    check("unapplied advance surfaced", flt(detail["unapplied_advance"]) == 8000,
          detail["unapplied_advance"])
    check("rooms listed with assignments", all(r["room"] for r in detail["rooms"]),
          [r["room"] for r in detail["rooms"]])
    check("special requests passed through", "ground floor" in (detail["special_requests"] or ""))

    print("\n5. Check in — advance lands on the room folios")
    result = hotel_pos.checkin_arrival(booking=booking.name)
    booking.reload()

    check("both rooms checked in", len(result["checked_in"]) == 2, result["checked_in"])
    check("full advance applied", flt(result["advance_applied"]) == 8000, result["advance_applied"])
    check("booking marked Checked In", booking.status == "Checked In", booking.status)
    check("nothing left on the booking folio",
          advance.get_advance_balance(booking.name) == 0)

    reservations = [frappe.get_doc("Hotel Reservation", r.reservation) for r in booking.rooms]
    check("reservations are Checked In",
          all(r.status == "Checked In" for r in reservations),
          [r.status for r in reservations])
    check("rooms marked Occupied",
          all(frappe.db.get_value("Hotel Room", r.room, "status") == "Occupied" for r in reservations))

    # The advance was spread across the room folios as each checked in.
    credits = frappe.db.sql("""
        SELECT SUM(ABS(amount)) FROM `tabFolio Transaction`
        WHERE item = 'ADVANCE-TRANSFER' AND amount < 0 AND parent IN %s
    """, ([r.folio for r in reservations],))[0][0]
    check("advance credited across room folios", flt(credits) == 8000, credits)

    print("\n6. Walk-in guest is not duplicated")
    import json
    before = frappe.db.count("Guest")
    payload = {
        "is_new_guest": True,
        "guest_details": {"full_name": "Arrival Test Guest", "phone": "9000055555",
                          "email": "late@example.com"},
        "arrival": today,
        "departure": add_days(today, 1),
        "rooms": ["301"],
        "adults": 2,
        # This guest is already booked for tonight, which the POS now refuses as a
        # duplicate (verify_flows covers that). Marked additional so this section keeps
        # testing what it is about: the Guest record is reused, not duplicated.
        "additional_stay": 1,
    }
    out = hotel_pos.submit_pos_booking(json.dumps(payload))
    check("reused the existing guest", out["guest"] == guest.name, out["guest"])
    check("no duplicate Guest created", frappe.db.count("Guest") == before, before)
    check("email backfilled onto the existing guest",
          frappe.db.get_value("Guest", guest.name, "email_id") == "late@example.com")

    print("\n7. A late guest already marked No Show can still be checked in")
    late_booking = frappe.get_doc({
        "doctype": "Hotel Booking",
        "guest": guest.name,
        "arrival_date": today,
        "departure_date": add_days(today, 1),
        "status": "Draft",
        "rooms": [{"room_type": "Premium Cottage", "qty": 1, "rate": 7500}],
    }).insert(ignore_permissions=True)
    late_booking.confirm()
    late_booking.reload()

    res_name = late_booking.rooms[0].reservation
    frappe.db.set_value("Hotel Reservation", res_name, "status", "No Show")

    late_result = hotel_pos.checkin_arrival(booking=late_booking.name)
    check("no-show reservation recovered and checked in",
          res_name in late_result["checked_in"], late_result)
    check("status is now Checked In",
          frappe.db.get_value("Hotel Reservation", res_name, "status") == "Checked In")
