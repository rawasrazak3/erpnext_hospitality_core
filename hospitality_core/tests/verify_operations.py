"""Standard front-office operations: extend stay, early departure, availability
consistency, and the guest-facing booking confirmation.

Rolled back; safe against a live site.

    bench --site <site> execute hospitality_core.tests.verify_operations.run
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
    from hospitality_core.hospitality_core.api import advance, availability
    from hospitality_core.hospitality_core.doctype.hotel_reservation import hotel_reservation as hr
    from hospitality_core.hospitality_core.page.hotel_crm import hotel_crm
    from hospitality_core.hospitality_core.report.room_availability_report import (
        room_availability_report,
    )

    today = nowdate()

    guest = frappe.get_doc({
        "doctype": "Guest", "full_name": "Ops Test Guest",
        "mobile_no": "9000040001", "guest_type": "Regular",
    }).insert(ignore_permissions=True)

    print("\n1. Extend a stay")
    booking = frappe.get_doc({
        "doctype": "Hotel Booking", "guest": guest.name,
        "arrival_date": today, "departure_date": add_days(today, 2),
        "adults": 2, "status": "Draft",
        "special_requests": "Quiet room away from the pool",
        "rooms": [{"room_type": "Pool Villa", "qty": 1, "rate": 12000}],
    }).insert(ignore_permissions=True)
    booking.confirm()
    booking.reload()

    res_name = booking.rooms[0].reservation
    result = hr.extend_stay(res_name, add_days(today, 4))
    check("stay extended", result["departure_date"] == str(add_days(today, 4)), result)

    reservation = frappe.get_doc("Hotel Reservation", res_name)
    check("reservation departure moved", str(reservation.departure_date) == str(add_days(today, 4)))
    booking.reload()
    check("booking window widened to match",
          str(booking.departure_date) == str(add_days(today, 4)), booking.departure_date)

    check("extending backwards is refused",
          _throws(lambda: hr.extend_stay(res_name, add_days(today, 1))))

    print("\n2. Extending into an occupied night is refused")
    blocker_guest = frappe.get_doc({
        "doctype": "Guest", "full_name": "Ops Blocker", "mobile_no": "9000040002",
    }).insert(ignore_permissions=True)
    blocker = frappe.get_doc({
        "doctype": "Hotel Reservation",
        "guest": blocker_guest.name,
        "room": reservation.room,
        "room_type": reservation.room_type,
        "hotel_reception": reservation.hotel_reception,
        "arrival_date": add_days(today, 6),
        "departure_date": add_days(today, 8),
        "status": "Reserved",
    }).insert(ignore_permissions=True)
    check("blocking reservation created", blocker.name)
    check("cannot extend over another booking",
          _throws(lambda: hr.extend_stay(res_name, add_days(today, 7))))

    print("\n3. Early departure at check-out")
    reservation.reload()
    reservation.process_check_in()
    reservation.reload()

    from hospitality_core.hospitality_core.api.payment_bridge import create_folio_payment
    balance = flt(frappe.db.get_value("Guest Folio", reservation.folio, "outstanding_balance"))
    if balance > 0:
        create_folio_payment(reservation.folio, balance, "Cash", reservation.hotel_reception)

    reservation.reload()
    reservation.process_check_out()
    reservation.reload()
    check("early departure shortened the stay to today",
          str(reservation.departure_date) == today, reservation.departure_date)
    check("departure time is a clean clock time",
          "." not in str(reservation.departure_time or ""), reservation.departure_time)
    check("room released", frappe.db.get_value("Hotel Room", reservation.room, "status") == "Available")

    print("\n4. Availability report agrees with the booking engine")
    hold_guest = frappe.get_doc({
        "doctype": "Guest", "full_name": "Ops Holder", "mobile_no": "9000040003",
    }).insert(ignore_permissions=True)
    hold = frappe.get_doc({
        "doctype": "Hotel Booking", "guest": hold_guest.name,
        "arrival_date": add_days(today, 30), "departure_date": add_days(today, 32),
        "status": "Draft",
        "rooms": [{"room_type": "Deluxe Room", "qty": 2, "rate": 4500}],
    }).insert(ignore_permissions=True)
    hold.set_tentative(hold_hours=48)

    night = add_days(today, 30)
    engine = availability.get_availability(night, add_days(night, 1))
    engine_deluxe = next(t for t in engine["room_types"] if t["room_type"] == "Deluxe Room")

    rows = room_availability_report.get_data({"from_date": night, "to_date": night})
    report_deluxe = next(r for r in rows if r["room_type"] == "Deluxe Room")

    check("engine sees the hold", engine_deluxe["held"] == 2, engine_deluxe)
    check("report sees the same hold", report_deluxe["held"] == 2, report_deluxe)
    check("report free count matches the engine",
          report_deluxe["available"] == engine_deluxe["free"],
          (report_deluxe["available"], engine_deluxe["free"]))
    check("report shows nothing free once both are held",
          report_deluxe["available"] == 0, report_deluxe)

    print("\n5. Booking confirmation renders")
    hold.reload()
    # Render the template directly rather than via frappe.get_print: printing writes an
    # Access Log, and Frappe force-commits that — which would end this transaction and
    # leak every record above onto the live site.
    html = render_confirmation(hold)
    check("print format produced output", html and len(html) > 500, len(html or ""))
    check("shows the booking number", hold.name in html)
    check("shows the guest name", "Ops Holder" in html)
    check("shows the tentative status", "Tentative" in html)
    check("warns that the hold expires", "released automatically" in html)
    check("unassigned rooms are labelled", "To be assigned" in html)

    booking.reload()
    confirmed_html = render_confirmation(booking)
    check("renders for a confirmed booking too", confirmed_html and len(confirmed_html) > 500)
    check("special requests carried through",
          "Quiet room away from the pool" in confirmed_html)


def render_confirmation(doc):
    """Run the Booking Confirmation template against a document, no side effects.

    A standard print format keeps its markup in the app's .html file rather than the
    DocType's html field, so read it through printview's own loader.
    """
    from frappe.www.printview import get_print_format

    fmt = frappe.get_doc("Print Format", "Booking Confirmation")
    template = get_print_format(doc.doctype, fmt)
    return frappe.render_template(template, {"doc": doc})


def _throws(fn):
    try:
        fn()
    except Exception:
        return True
    return False
