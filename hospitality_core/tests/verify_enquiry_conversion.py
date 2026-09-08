"""Check the enquiry -> booking -> advance path the sales console drives.

Rolled back; safe against a live site.

    bench --site <site> execute hospitality_core.tests.verify_enquiry_conversion.run
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
    from hospitality_core.hospitality_core.page.hotel_crm import hotel_crm

    arrival = add_days(nowdate(), 45)
    departure = add_days(arrival, 2)

    print("\n1. Live availability for the console")
    avail = hotel_crm.get_stay_availability(arrival, departure)
    check("availability returned", avail and "room_types" in avail)
    check("all rooms free for a far-future window", avail["total_free"] == 5, avail["total_free"])
    check("bad dates return an error rather than raising",
          (hotel_crm.get_stay_availability(departure, arrival) or {}).get("error"))
    check("missing dates return None", hotel_crm.get_stay_availability(None, None) is None)

    print("\n2. Enquiry -> booking")
    enquiry = frappe.get_doc({
        "doctype": "Hotel Enquiry",
        "guest_name": "Conversion Test",
        "mobile_no": "+91 98888 12345",
        "check_in_date": arrival,
        "check_out_date": departure,
        "adults": 3,
        "source": "Phone Call",
        "room_lines": [{"room_type": "Premium Cottage", "qty": 2, "rate_quoted": 7500}],
    }).insert(ignore_permissions=True)
    check("enquiry quoted", flt(enquiry.quoted_total) == 30000, enquiry.quoted_total)

    result = hotel_crm.create_booking_from_enquiry(enquiry.name, action="hold", hold_hours=12)
    booking = frappe.get_doc("Hotel Booking", result["booking"])
    enquiry.reload()

    check("booking created", result["created"])
    check("booking is a tentative hold", booking.status == "Tentative", booking.status)
    check("hold expiry set", booking.hold_expiry)
    check("enquiry links to the booking", enquiry.hotel_booking == booking.name)
    check("guest created from the enquiry", enquiry.guest, enquiry.guest)
    check("guest carries the phone number",
          frappe.db.get_value("Guest", enquiry.guest, "mobile_no") == "+91 98888 12345")
    check("booking total matches the quote", flt(booking.total_amount) == 30000, booking.total_amount)
    check("rooms held without assignment", not any(r.room for r in booking.rooms))

    print("\n3. The hold shows up in availability")
    held = hotel_crm.get_stay_availability(arrival, departure)
    cottage = next(t for t in held["room_types"] if t["room_type"] == "Premium Cottage")
    check("2 cottages held", cottage["held"] == 2, cottage)
    check("cottage free count is 0", cottage["free"] == 0, cottage)

    print("\n4. Conversion is idempotent")
    again = hotel_crm.create_booking_from_enquiry(enquiry.name)
    check("second call returns the same booking", again["booking"] == booking.name)
    check("and reports it did not create one", again["created"] is False)

    print("\n5. Guest is reused, not duplicated")
    second = frappe.get_doc({
        "doctype": "Hotel Enquiry",
        "guest_name": "Conversion Test Again",
        "mobile_no": "9888812345",          # same number, different formatting
        "check_in_date": add_days(nowdate(), 60),
        "check_out_date": add_days(nowdate(), 62),
        "room_lines": [{"room_type": "Deluxe Room", "qty": 1, "rate_quoted": 4500}],
    }).insert(ignore_permissions=True)
    before = frappe.db.count("Guest")
    r2 = hotel_crm.create_booking_from_enquiry(second.name, action="confirm")
    check("no duplicate Guest created", frappe.db.count("Guest") == before, before)
    check("reused the same guest", r2["guest"] == enquiry.guest, r2["guest"])

    print("\n6. Confirm + advance through the console path")
    confirmed = frappe.get_doc("Hotel Booking", r2["booking"])
    check("confirmed booking", confirmed.status == "Confirmed", confirmed.status)
    check("room assigned", confirmed.rooms[0].room, confirmed.rooms[0].room)
    check("reservation created", confirmed.rooms[0].reservation, confirmed.rooms[0].reservation)

    advance.record_advance(confirmed.name, 3000, "Cash", reference_no="UPI-9911")
    summary = hotel_crm.get_booking(confirmed.name)
    check("advance recorded", flt(summary["advance_received"]) == 3000, summary["advance_received"])
    check("unapplied advance surfaced for the UI",
          flt(summary["unapplied_advance"]) == 3000, summary["unapplied_advance"])
    check("balance due correct", flt(summary["balance_due"]) == 6000, summary["balance_due"])

    print("\n7. Winning an enquiry moves it to a Won status")
    second.reload()
    won_type = frappe.db.get_value("Hotel Enquiry Status", second.status, "type")
    check("enquiry status is now Won", won_type == "Won", f"{second.status} ({won_type})")
    check("enquiry flagged converted", second.converted == 1)
