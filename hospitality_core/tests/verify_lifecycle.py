"""Booking lifecycle: does a booking finish, and does a dead booking free its enquiry?

Gaps this covers, all found by auditing rather than by the earlier suites:
  * nothing ever moved a booking to Completed, so finished stays sat in "Checked In"
    forever and lingered in the Advance Liability Register;
  * cancelling or expiring a booking left the enquiry pointing at it, marked Won, so the
    guest could never be re-booked from that enquiry.

Rolled back; safe against a live site.

    bench --site <site> execute hospitality_core.tests.verify_lifecycle.run
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


def make_enquiry(name, mobile, room_type, qty, rate, arrival, nights=2):
    return frappe.get_doc({
        "doctype": "Hotel Enquiry",
        "guest_name": name,
        "mobile_no": mobile,
        "check_in_date": arrival,
        "check_out_date": add_days(arrival, nights),
        "room_lines": [{"room_type": room_type, "qty": qty, "rate_quoted": rate}],
    }).insert(ignore_permissions=True)


def settle(reservation):
    """Pay off whatever the folio owes, so check-out is not blocked on money."""
    from hospitality_core.hospitality_core.api.payment_bridge import create_folio_payment

    balance = flt(frappe.db.get_value("Guest Folio", reservation.folio, "outstanding_balance"))
    if balance > 0.01:
        create_folio_payment(
            folio_name=reservation.folio,
            amount=balance,
            mode_of_payment="Cash",
            hotel_reception=reservation.hotel_reception,
        )


def _run():
    from hospitality_core.hospitality_core.api import advance
    from hospitality_core.hospitality_core.doctype.hotel_booking import hotel_booking as hb
    from hospitality_core.hospitality_core.page.hotel_crm import hotel_crm

    today = nowdate()

    print("\n1. A completed stay closes its booking")
    enq = make_enquiry("Lifecycle One", "9000030001", "Deluxe Room", 2, 4500, today)
    result = hotel_crm.create_booking_from_enquiry(enq.name, action="confirm")
    booking = frappe.get_doc("Hotel Booking", result["booking"])

    check("two reservations created", len(booking.rooms) == 2, len(booking.rooms))
    enq.reload()
    check("enquiry marked converted", enq.converted == 1)
    check("enquiry status is Won",
          frappe.db.get_value("Hotel Enquiry Status", enq.status, "type") == "Won", enq.status)

    reservations = [frappe.get_doc("Hotel Reservation", r.reservation) for r in booking.rooms]
    for res in reservations:
        res.process_check_in()
    booking.reload()
    check("booking is Checked In once rooms are in", booking.status == "Checked In", booking.status)

    # Check out the first room only. Its departure is two days out, so this also
    # exercises early departure — standard in a hotel, and previously refused outright.
    first = frappe.get_doc("Hotel Reservation", reservations[0].name)
    first.reload()
    original_departure = first.departure_date
    settle(first)
    first.process_check_out()
    first.reload()
    check("early departure shortened the stay to today",
          str(first.departure_date) == today, (original_departure, first.departure_date))
    booking.reload()
    check("still Checked In while a room remains in house",
          booking.status == "Checked In", booking.status)

    second = frappe.get_doc("Hotel Reservation", reservations[1].name)
    second.reload()
    settle(second)
    second.process_check_out()
    booking.reload()
    check("booking is Completed after the last room leaves",
          booking.status == "Completed", booking.status)

    print("\n2. Cancelling a booking frees its enquiry")
    enq2 = make_enquiry("Lifecycle Two", "9000030002", "Premium Cottage", 1, 7500, add_days(today, 20))
    r2 = hotel_crm.create_booking_from_enquiry(enq2.name, action="confirm")
    b2 = frappe.get_doc("Hotel Booking", r2["booking"])
    enq2.reload()
    check("enquiry linked to the booking", enq2.hotel_booking == b2.name)

    b2.cancel_booking(reason="Guest changed plans")
    b2.reload()
    enq2.reload()

    check("booking is Cancelled", b2.status == "Cancelled", b2.status)
    check("its reservations were cancelled",
          all(frappe.db.get_value("Hotel Reservation", r.reservation, "status") == "Cancelled"
              for r in b2.rooms))
    check("enquiry link cleared", not enq2.hotel_booking, enq2.hotel_booking)
    check("enquiry no longer marked converted", enq2.converted == 0)
    check("enquiry moved out of a Won stage",
          frappe.db.get_value("Hotel Enquiry Status", enq2.status, "type") != "Won", enq2.status)

    # The whole point: the agent can book this guest again.
    again = hotel_crm.create_booking_from_enquiry(enq2.name, action="confirm")
    check("a replacement booking can be created", again["created"] is True, again)
    check("and it is a different booking", again["booking"] != b2.name, again["booking"])

    print("\n3. Rooms are genuinely released by a cancellation")
    avail = hotel_crm.get_stay_availability(add_days(today, 20), add_days(today, 22))
    cottage = next(t for t in avail["room_types"] if t["room_type"] == "Premium Cottage")
    # One cottage is taken by the replacement booking, so exactly one should remain.
    check("cancelled rooms went back on sale", cottage["free"] == 1, cottage)

    print("\n4. An expired hold releases its enquiry too")
    enq3 = make_enquiry("Lifecycle Three", "9000030003", "Pool Villa", 1, 12000, add_days(today, 40))
    r3 = hotel_crm.create_booking_from_enquiry(enq3.name, action="hold", hold_hours=1)
    b3 = frappe.get_doc("Hotel Booking", r3["booking"])
    check("hold created", b3.status == "Tentative", b3.status)

    # Push the expiry into the past and run the scheduled release.
    frappe.db.set_value("Hotel Booking", b3.name, "hold_expiry", add_days(today, -1))
    hb.release_expired_holds()

    b3.reload()
    enq3.reload()
    check("expired hold cancelled", b3.status == "Cancelled", b3.status)
    check("expired hold released its enquiry", not enq3.hotel_booking, enq3.hotel_booking)

    print("\n5. A paid hold is NOT auto-released")
    enq4 = make_enquiry("Lifecycle Four", "9000030004", "Pool Villa", 1, 12000, add_days(today, 50))
    r4 = hotel_crm.create_booking_from_enquiry(enq4.name, action="confirm")
    b4 = frappe.get_doc("Hotel Booking", r4["booking"])
    advance.record_advance(b4.name, 3000, "Cash")
    frappe.db.set_value("Hotel Booking", b4.name, {
        "status": "Tentative", "hold_expiry": add_days(today, -1)})

    hb.release_expired_holds()
    b4.reload()
    check("a hold holding money survives expiry", b4.status == "Tentative", b4.status)
    check("its advance is intact", flt(advance.get_advance_balance(b4.name)) == 3000)

    print("\n6. A cancelled booking cannot be cancelled twice")
    check("second cancel is refused", _throws(lambda: b2.cancel_booking(reason="again")))


def _throws(fn):
    try:
        fn()
    except Exception:
        return True
    return False
