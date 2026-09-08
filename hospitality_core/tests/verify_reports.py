"""Check that advances reconcile as cash without being counted as revenue.

The plan's hardest requirement: an advance must appear as a collection on the day it is
taken, must NOT be revenue that day, and must not be counted a second time on the stay
date. Also checks the four new reports run and the three previously-crashing ones render.

Rolled back; safe against a live site.

    bench --site <site> execute hospitality_core.tests.verify_reports.run
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


def metric(rows, name):
    for r in rows:
        if r.get("metric") == name:
            return r.get("value")
    return None


def money(text):
    """Strip currency formatting back to a number."""
    if text is None:
        return 0.0
    return flt("".join(c for c in str(text) if c.isdigit() or c in ".-"))


def _run():
    from hospitality_core.hospitality_core.api import advance
    from hospitality_core.hospitality_core.report.advance_collection import advance_collection
    from hospitality_core.hospitality_core.report.advance_liability_register import (
        advance_liability_register,
    )
    from hospitality_core.hospitality_core.report.call_activity import call_activity
    from hospitality_core.hospitality_core.report.enquiry_conversion import enquiry_conversion
    from hospitality_core.hospitality_core.report.frontdesk_end_of_day_report import (
        frontdesk_end_of_day_report,
    )

    today = nowdate()

    print("\n1. Previously-crashing reports now render")
    # These raised KeyError on ct_amount / vat_amount / sc_amount for any date with data.
    for label, module_path in (
        ("Frontdesk End of Day", "frontdesk_end_of_day_report"),
        ("Gross Revenue", "gross_revenue_report"),
        ("Daily Sales Consumption", "daily_sales_consumption"),
    ):
        mod = frappe.get_module(
            f"hospitality_core.hospitality_core.report.{module_path}.{module_path}"
        )
        try:
            mod.execute({
                "date": today, "from_date": today, "to_date": today,
                "company": frappe.db.get_single_value("Hospitality Accounting Settings", "company"),
                "group_by": "Room",
            })
            check(f"{label} runs", True)
        except Exception as e:
            check(f"{label} runs", False, repr(e))

    print("\n2. Take an advance today for a stay next month")
    guest = frappe.get_doc({
        "doctype": "Guest", "full_name": "Report Test Guest",
        "mobile_no": "9000077777", "guest_type": "Regular",
    }).insert(ignore_permissions=True)

    future = add_days(today, 30)
    booking = frappe.get_doc({
        "doctype": "Hotel Booking",
        "guest": guest.name,
        "arrival_date": future,
        "departure_date": add_days(future, 2),
        "status": "Draft",
        "rooms": [{"room_type": "Pool Villa", "qty": 1, "rate": 12000}],
    }).insert(ignore_permissions=True)
    booking.confirm()
    advance.record_advance(booking.name, 9000, "Cash", reference_no="RPT-1")
    booking.reload()

    print("\n3. EOD: the advance is cash today, but NOT revenue today")
    _cols, rows = frontdesk_end_of_day_report.execute({"date": today})

    total_collections = money(metric(rows, "Total Collections"))
    in_house = money(metric(rows, "  - In-House Settlement"))
    advances = money(metric(rows, "  - Advances (Future Stays)"))
    revenue = money(metric(rows, "Sales Consumption (Gross)"))

    check("collections include the advance", total_collections >= 9000, total_collections)
    check("advance is broken out separately", advances == 9000, advances)
    check("advance is NOT in in-house settlement", in_house == 0, in_house)
    check("split adds up to the total", abs((in_house + advances) - total_collections) < 0.01,
          (in_house, advances, total_collections))
    check("no revenue recognised today", revenue == 0, revenue)

    print("\n4. Transfers are excluded from revenue")
    # Check in the stay so the advance moves to the room folio via ADVANCE-TRANSFER.
    frappe.db.set_value("Hotel Booking", booking.name, {
        "arrival_date": today, "departure_date": add_days(today, 2)})
    for line in booking.rooms:
        frappe.db.set_value("Hotel Reservation", line.reservation,
                            {"arrival_date": today, "departure_date": add_days(today, 2)})

    res = frappe.get_doc("Hotel Reservation", booking.rooms[0].reservation)
    res.reload()
    res.process_check_in()
    applied = advance.apply_advance(booking.name, res.name)
    check("advance moved to the room folio", flt(applied["applied"]) == 9000, applied)

    _cols, rows2 = frontdesk_end_of_day_report.execute({"date": today})
    revenue2 = money(metric(rows2, "Sales Consumption (Gross)"))

    # Only the first night's room rent should count. The ADVANCE-TRANSFER pair must not.
    room_rent = frappe.db.sql("""
        SELECT SUM(amount) FROM `tabFolio Transaction`
        WHERE parent = %s AND item = 'ROOM-RENT' AND is_void = 0 AND posting_date = %s
    """, (res.folio, today))[0][0] or 0
    check("revenue equals room rent only, transfers excluded",
          abs(revenue2 - flt(room_rent)) < 0.01, (revenue2, flt(room_rent)))
    # If the ADVANCE-TRANSFER credit had leaked into the revenue query it would have
    # subtracted 9000 and left 3000; if the debit leg had, it would have added 9000.
    check("the transfer credit did not reduce revenue",
          abs(revenue2 - (flt(room_rent) - 9000)) > 0.01, revenue2)
    check("the transfer debit did not increase revenue",
          abs(revenue2 - (flt(room_rent) + 9000)) > 0.01, revenue2)

    print("\n5. Room Only Sales and EOD now agree")
    from hospitality_core.hospitality_core.report.room_only_sales import room_only_sales
    ros = room_only_sales.get_data({"from_date": today, "to_date": today})
    # The report appends its own bolded Total row; counting it would double everything.
    ros_total = sum(
        flt(r.get("amount") or 0) for r in ros
        if "Total" not in str(r.get("guest_name") or "")
    )
    check("room-only sales matches EOD revenue",
          abs(ros_total - revenue2) < 0.01, (ros_total, revenue2))

    print("\n6. New reports return sane data")
    adv_rows = advance_collection.execute({"from_date": today, "to_date": today})[1]
    check("advance collection lists the payment",
          any(r["booking"] == booking.name for r in adv_rows), len(adv_rows))
    check("advance amount correct",
          flt(next(r for r in adv_rows if r["booking"] == booking.name)["amount"]) == 9000)

    liab = advance_liability_register.execute({})[1]
    check("liability register is empty once the advance is applied",
          not any(r["booking"] == booking.name for r in liab), liab)

    conv = enquiry_conversion.execute({
        "from_date": add_days(today, -90), "to_date": today, "group_by": "Source"})[1]
    check("enquiry conversion runs and groups", isinstance(conv, list), len(conv))
    if conv:
        check("conversion % computed", all("conversion_pct" in r for r in conv))

    calls = call_activity.execute({"from_date": add_days(today, -30), "to_date": today})[1]
    check("call activity runs", isinstance(calls, list), len(calls))
    if calls:
        check("agent funnel columns present",
              all({"total_calls", "connected", "talk_minutes"} <= set(r) for r in calls))

    print("\n7. An unapplied advance DOES show as a liability")
    b2 = frappe.get_doc({
        "doctype": "Hotel Booking", "guest": guest.name,
        "arrival_date": add_days(today, 40), "departure_date": add_days(today, 42),
        "status": "Draft",
        "rooms": [{"room_type": "Deluxe Room", "qty": 1, "rate": 4500}],
    }).insert(ignore_permissions=True)
    b2.confirm()
    advance.record_advance(b2.name, 2500, "Cash")

    liab2 = advance_liability_register.execute({})[1]
    row = next((r for r in liab2 if r["booking"] == b2.name), None)
    check("unapplied advance appears", row is not None, [r["booking"] for r in liab2])
    if row:
        check("held amount correct", flt(row["held"]) == 2500, row["held"])
        check("days to arrival computed", row["days_to_arrival"] == 40, row["days_to_arrival"])
