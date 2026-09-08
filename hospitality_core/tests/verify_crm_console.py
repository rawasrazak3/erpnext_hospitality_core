"""Check the Hotel CRM sales console API (/app/hotel-crm backend).

Rolled back, safe against a live site.

Run with:
    bench --site <site> execute hospitality_core.tests.verify_crm_console.run
"""

import json

import frappe

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
    from hospitality_core.hospitality_core.page.hotel_crm import hotel_crm

    print("\n1. Console boot payload")
    data = hotel_crm.get_console_data()
    check("statuses returned in pipeline order",
          [s.name for s in data["statuses"]][:3] == ["New", "Contacted", "Quoted"],
          [s.name for s in data["statuses"]][:3])
    check("sources returned", len(data["sources"]) >= 9, len(data["sources"]))
    check("lost reasons returned", len(data["lost_reasons"]) >= 6, len(data["lost_reasons"]))
    check("queue counts present", set(data["counts"]) == {"due", "mine", "all", "calls"},
          data["counts"])
    check("session user echoed", data["user"] == frappe.session.user)

    print("\n2. Save an enquiry through the console")
    room_type = _ensure("Hotel Room Type", {
        "room_type_name": "TEST-COTTAGE", "default_rate": 6000, "max_adults": 2, "max_children": 1,
    })

    saved = hotel_crm.save_enquiry(json.dumps({
        "guest_name": "Console Test",
        "mobile_no": "+91 98470 11111",
        "check_in_date": "2026-10-01",
        "check_out_date": "2026-10-04",
        "adults": 3,
        "status": "New",
        "source": "Phone Call",
        "room_lines": [{"room_type": room_type.name, "qty": 2, "rate_quoted": 6000}],
    }))
    check("enquiry created", saved.get("name"), saved.get("name"))
    check("nights computed server-side", saved.get("nights") == 3, saved.get("nights"))
    # 2 rooms x 3 nights x 6000
    check("quote computed server-side", saved.get("quoted_total") == 36000, saved.get("quoted_total"))
    check("calls attached to the payload", "calls" in saved)

    print("\n3. Update the same enquiry (no duplicate)")
    before = frappe.db.count("Hotel Enquiry")
    updated = hotel_crm.save_enquiry(json.dumps({
        "name": saved["name"],
        "guest_name": "Console Test Renamed",
        "mobile_no": "+91 98470 11111",
        "check_in_date": "2026-10-01",
        "check_out_date": "2026-10-06",
        "status": "Quoted",
        "room_lines": [{"room_type": room_type.name, "qty": 1, "rate_quoted": 7000}],
    }))
    check("no new record created", frappe.db.count("Hotel Enquiry") == before, before)
    check("name preserved", updated["name"] == saved["name"])
    check("nights recomputed", updated["nights"] == 5, updated["nights"])
    check("quote recomputed", updated["quoted_total"] == 35000, updated["quoted_total"])
    check("status updated", updated["status"] == "Quoted", updated["status"])

    print("\n4. Queues")
    all_open = hotel_crm.get_enquiries(queue="all")
    check("returns enquiries", all_open["type"] == "enquiries")
    check("our record is in the open queue",
          any(r["name"] == saved["name"] for r in all_open["rows"]), len(all_open["rows"]))
    check("rows carry a status colour for the pill",
          all("status_color" in r for r in all_open["rows"]))

    by_phone = hotel_crm.get_enquiries(queue="all", search="9847011111")
    check("search by phone finds it",
          any(r["name"] == saved["name"] for r in by_phone["rows"]), len(by_phone["rows"]))

    by_name = hotel_crm.get_enquiries(queue="all", search="Console Test")
    check("search by name finds it",
          any(r["name"] == saved["name"] for r in by_name["rows"]), len(by_name["rows"]))

    calls = hotel_crm.get_enquiries(queue="calls")
    check("calls queue returns call rows", calls["type"] == "calls", len(calls["rows"]))

    print("\n5. Board")
    board = hotel_crm.get_board()
    check("board has a column per status",
          len(board["statuses"]) == frappe.db.count("Hotel Enquiry Status"),
          len(board["statuses"]))
    check("every status has a bucket",
          all(s.name in board["grouped"] for s in board["statuses"]))
    check("our record sits in its status column",
          any(r["name"] == saved["name"] for r in board["grouped"].get("Quoted", [])))

    print("\n6. Status moves")
    moved = hotel_crm.set_status(saved["name"], "Contacted")
    check("status moved", moved["status"] == "Contacted", moved)
    check("status_type followed", moved["status_type"] == "Ongoing", moved["status_type"])

    check("moving to Lost without a reason is refused",
          _throws(lambda: hotel_crm.set_status(saved["name"], "Lost")))

    lost = hotel_crm.set_status(saved["name"], "Lost", lost_reason="Rate too high")
    check("moving to Lost with a reason works", lost["status"] == "Lost", lost)

    open_after = hotel_crm.get_enquiries(queue="all")
    check("a Lost enquiry drops out of the open queue",
          not any(r["name"] == saved["name"] for r in open_after["rows"]))


def _throws(fn):
    try:
        fn()
    except Exception:
        return True
    return False


def _ensure(doctype, values):
    key = list(values.keys())[0]
    existing = frappe.db.get_value(doctype, {key: values[key]}, "name")
    if existing:
        return frappe.get_doc(doctype, existing)
    doc = frappe.get_doc(dict(doctype=doctype, **values))
    doc.insert(ignore_permissions=True)
    return doc
