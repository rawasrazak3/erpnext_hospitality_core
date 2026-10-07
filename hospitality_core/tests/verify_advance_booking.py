"""End-to-end check of Phase 2: availability, Hotel Booking, advances, no-show handling.

This is the test the plan called "the one that matters": money taken days before a stay
must reconcile as cash on the day it is collected, must NOT be revenue until the guest
stays, and must survive a no-show.

Everything is rolled back, so this is safe against a live site.

    bench --site <site> execute hospitality_core.tests.verify_advance_booking.run
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

    arrival = add_days(nowdate(), 20)
    departure = add_days(arrival, 3)

    print("\n1. Availability baseline")
    base = availability.get_availability(arrival, departure)
    by_type = {t["room_type"]: t for t in base["room_types"]}
    check("nights computed", base["nights"] == 3, base["nights"])
    check("all 5 demo rooms are free", base["total_free"] == 5, base["total_free"])
    check("Deluxe has 2 free", by_type["Deluxe Room"]["free"] == 2, by_type["Deluxe Room"])
    check("Pool Villa has 1 free", by_type["Pool Villa"]["free"] == 1, by_type["Pool Villa"])

    free_rooms = availability.get_free_rooms(arrival, departure, room_type="Deluxe Room")
    check("get_free_rooms lists both deluxe rooms", sorted(free_rooms) == ["101", "102"], free_rooms)

    print("\n2. Create a booking with a room-type hold (no room chosen yet)")
    guest = frappe.get_doc({
        "doctype": "Guest",
        "full_name": "Advance Test Guest",
        "mobile_no": "9000012345",
        "guest_type": "Regular",
    }).insert(ignore_permissions=True)

    booking = frappe.get_doc({
        "doctype": "Hotel Booking",
        "guest": guest.name,
        "arrival_date": arrival,
        "departure_date": departure,
        "adults": 4,
        "status": "Draft",
        "rooms": [{"room_type": "Deluxe Room", "qty": 2, "adults": 2, "rate": 4500}],
    }).insert(ignore_permissions=True)

    check("nights on booking", booking.nights == 3, booking.nights)
    # 2 rooms x 3 nights x 4500
    check("total computed", flt(booking.total_amount) == 27000, booking.total_amount)
    check("no rooms assigned yet", not any(r.room for r in booking.rooms))

    print("\n3. A tentative hold consumes capacity but blocks no specific room")
    booking.set_tentative(hold_hours=24)
    booking.reload()
    check("status is Tentative", booking.status == "Tentative", booking.status)
    check("hold expiry set", booking.hold_expiry, booking.hold_expiry)

    held = availability.get_availability(arrival, departure)
    held_by_type = {t["room_type"]: t for t in held["room_types"]}
    check("2 deluxe rooms now held", held_by_type["Deluxe Room"]["held"] == 2,
          held_by_type["Deluxe Room"])
    check("deluxe free drops to 0", held_by_type["Deluxe Room"]["free"] == 0,
          held_by_type["Deluxe Room"])
    check("but no individual room is marked unavailable",
          all(r["available"] for r in held["rooms"] if r["room_type"] == "Deluxe Room"))
    check("other room types unaffected", held_by_type["Pool Villa"]["free"] == 1)

    print("\n4. Confirm — holds become real rooms and reservations")
    booking.confirm()
    booking.reload()

    check("status is Confirmed", booking.status == "Confirmed", booking.status)
    check("hold expiry cleared", not booking.hold_expiry)
    check("expanded to one line per room", len(booking.rooms) == 2, len(booking.rooms))
    check("every line has a room", all(r.room for r in booking.rooms),
          [r.room for r in booking.rooms])
    check("every line has a reservation", all(r.reservation for r in booking.rooms),
          [r.reservation for r in booking.rooms])
    check("each line is qty 1", all(r.qty == 1 for r in booking.rooms))

    reservations = [frappe.get_doc("Hotel Reservation", r.reservation) for r in booking.rooms]
    check("reservations are Reserved", all(r.status == "Reserved" for r in reservations))
    check("reservations link back to the booking",
          all(r.hotel_booking == booking.name for r in reservations))
    check("each reservation got a folio", all(r.folio for r in reservations))

    after = availability.get_availability(arrival, departure)
    after_by_type = {t["room_type"]: t for t in after["room_types"]}
    check("deluxe now shows 2 occupied", after_by_type["Deluxe Room"]["occupied"] == 2,
          after_by_type["Deluxe Room"])
    check("soft holds released (not double counted)", after_by_type["Deluxe Room"]["held"] == 0,
          after_by_type["Deluxe Room"])
    check("total free is now 3", after["total_free"] == 3, after["total_free"])

    print("\n5. Take a ₹10,000 advance")
    result = advance.record_advance(booking.name, 10000, "Cash", reference_no="TEST-UTR-1")
    booking.reload()

    payment = frappe.get_doc("Payment Entry", result["payment_entry"])
    check("payment entry submitted", payment.docstatus == 1, payment.name)
    check("payment tagged with the booking", payment.hotel_booking == booking.name)
    check("advance_received tracked", flt(booking.advance_received) == 10000,
          booking.advance_received)
    check("balance due is total minus advance", flt(booking.balance_due) == 17000,
          booking.balance_due)
    check("payment row logged", len(booking.payments) == 1, len(booking.payments))

    folio = frappe.get_doc("Guest Folio", booking.booking_folio)
    check("booking folio flagged as master", folio.is_booking_master == 1)
    check("folio holds a credit of 10000", flt(folio.outstanding_balance) == -10000,
          folio.outstanding_balance)
    check("unapplied advance readable", advance.get_advance_balance(booking.name) == 10000)

    print("\n6. The advance is a liability, NOT revenue")
    settings = frappe.get_single("Hospitality Accounting Settings")
    gl = frappe.get_all(
        "GL Entry",
        filters={"voucher_type": "Payment Entry", "voucher_no": payment.name},
        fields=["account", "debit", "credit"],
    )
    accounts = {g.account: g for g in gl}
    check("posted to the advance liability account",
          settings.advance_liability_account in accounts, list(accounts))
    check("liability is credited 10000",
          flt(accounts.get(settings.advance_liability_account, {}).get("credit")) == 10000,
          accounts.get(settings.advance_liability_account))
    check("NO income recognised yet", settings.income_account not in accounts, list(accounts))

    print("\n7. No-show does not strand the money")
    from hospitality_core.hospitality_core.api.night_audit import cancel_no_shows

    # Backdate the arrival so the night audit sees it as a no-show.
    past = add_days(nowdate(), -1)
    for r in reservations:
        frappe.db.set_value("Hotel Reservation", r.name, "arrival_date", past)

    cancel_no_shows(nowdate())

    statuses = [frappe.db.get_value("Hotel Reservation", r.name, "status") for r in reservations]
    check("prepaid reservations marked No Show, not Cancelled",
          all(s == "No Show" for s in statuses), statuses)
    check("advance still on the folio after the audit",
          advance.get_advance_balance(booking.name) == 10000)

    # Restore for the check-in leg.
    for r in reservations:
        frappe.db.set_value("Hotel Reservation", r.name, {"arrival_date": nowdate(), "status": "Reserved"})

    print("\n8. Check in — the advance lands on the room folio")
    reservation = frappe.get_doc("Hotel Reservation", reservations[0].name)
    reservation.reload()
    reservation.process_check_in()

    applied = advance.apply_advance(booking.name, reservation.name)
    check("advance applied", flt(applied["applied"]) == 10000, applied)
    check("nothing left unapplied", advance.get_advance_balance(booking.name) == 0,
          advance.get_advance_balance(booking.name))

    room_folio = frappe.get_doc("Guest Folio", reservation.folio)
    credits = [t for t in room_folio.transactions if t.item == "ADVANCE-TRANSFER"]
    check("ADVANCE-TRANSFER credit on the room folio", len(credits) == 1, len(credits))
    check("credit is negative", flt(credits[0].amount) == -10000, credits[0].amount)

    booking_folio = frappe.get_doc("Guest Folio", booking.booking_folio)
    check("booking folio nets to zero", abs(flt(booking_folio.outstanding_balance)) < 0.01,
          booking_folio.outstanding_balance)

    check("move logged for audit",
          frappe.db.exists("Folio Transaction Move Log",
                           {"source_folio": booking.booking_folio, "target_folio": room_folio.name}))

    print("\n9. Applying the advance posts no revenue; the check-out invoice does that")
    released = frappe.get_all(
        "GL Entry",
        filters={"voucher_type": "Hotel Booking", "voucher_no": booking.name},
        fields=["account", "debit", "credit"],
    )
    # Revenue is recognised once, by the Sales Invoice raised at check-out, which also
    # releases the parked advance (see verify_guest_journey). Moving it into income
    # suspense here as well is what used to leave suspense uncleared.
    check("no GL posted on application", not released, released)

    print("\n10. Overbooking is refused")
    clash = frappe.get_doc({
        "doctype": "Hotel Booking",
        "guest": guest.name,
        "arrival_date": arrival,
        "departure_date": departure,
        "adults": 2,
        "status": "Draft",
        "rooms": [{"room_type": "Deluxe Room", "qty": 2, "adults": 2, "rate": 4500}],
    }).insert(ignore_permissions=True)
    check("confirming beyond capacity throws", _throws(clash.confirm))

    villa = frappe.get_doc({
        "doctype": "Hotel Booking",
        "guest": guest.name,
        "arrival_date": arrival,
        "departure_date": departure,
        "adults": 2,
        "status": "Draft",
        "rooms": [{"room_type": "Pool Villa", "qty": 1, "adults": 2, "rate": 12000}],
    }).insert(ignore_permissions=True)
    villa.confirm()
    villa.reload()
    check("a type with capacity still confirms", villa.status == "Confirmed", villa.status)
    check("villa room assigned", villa.rooms[0].room == "301", villa.rooms[0].room)


def _throws(fn):
    try:
        fn()
    except Exception:
        return True
    return False
