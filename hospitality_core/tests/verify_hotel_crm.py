"""End-to-end check of the Hotel CRM: enquiry, quote maths, and call linkage.

Everything is rolled back, so this is safe against a live site.

Run with:
    bench --site <site> execute hospitality_core.tests.verify_hotel_crm.run
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
    from hospitality_core.hospitality_core.api import telephony

    print("\n1. Pipeline masters seeded")
    check("statuses seeded", frappe.db.count("Hotel Enquiry Status") >= 8)
    check("sources seeded", frappe.db.count("Hotel Enquiry Source") >= 9)
    check("lost reasons seeded", frappe.db.count("Hotel Lost Reason") >= 6)
    check("Hotel Sales Agent role", frappe.db.exists("Role", "Hotel Sales Agent"))

    print("\n2. Phone normalisation (last 10 digits)")
    check("+91 prefix", telephony.match_key("+919072140018") == "9072140018")
    check("leading zero", telephony.match_key("09072140018") == "9072140018")
    check("spaces and dashes", telephony.match_key("90721-400 18") == "9072140018")
    check("too short is rejected", telephony.match_key("123") == "")
    check("empty is rejected", telephony.match_key(None) == "")

    print("\n3. Create an enquiry")
    room_type = _ensure("Hotel Room Type", {
        "room_type_name": "TEST-SUITE", "default_rate": 8000, "max_adults": 3, "max_children": 2,
    })

    enquiry = frappe.get_doc({
        "doctype": "Hotel Enquiry",
        "guest_name": "Ramesh Kumar",
        "mobile_no": "+91 90721 40018",
        "check_in_date": add_days(nowdate(), 10),
        "check_out_date": add_days(nowdate(), 13),
        "adults": 4,
        "room_lines": [
            {"room_type": room_type.name, "qty": 2, "adults": 2, "rate_quoted": 8000},
        ],
    }).insert(ignore_permissions=True)

    check("default status applied", enquiry.status == "New", enquiry.status)
    check("status type fetched", enquiry.status_type == "Open", enquiry.status_type)
    check("owner defaulted to session user", enquiry.enquiry_owner == frappe.session.user)
    check("nights computed", enquiry.nights == 3, enquiry.nights)
    # 2 rooms x 3 nights x 8000
    check("quote totalled", flt(enquiry.quoted_total) == 48000.0, enquiry.quoted_total)
    check("room line amount", flt(enquiry.room_lines[0].amount) == 48000.0, enquiry.room_lines[0].amount)

    print("\n4. Guard rails")
    bad = frappe.get_doc({
        "doctype": "Hotel Enquiry", "guest_name": "Bad Dates", "mobile_no": "9000000009",
        "check_in_date": add_days(nowdate(), 5), "check_out_date": add_days(nowdate(), 5),
    })
    check("check-out must be after check-in", _throws(bad.insert))

    enquiry.status = "Lost"
    check("Lost without a reason is refused", _throws(enquiry.save))
    enquiry.reload()

    print("\n5. Call log links to the enquiry automatically")
    call = frappe.get_doc({
        "doctype": "CRM Call Log",
        "id": "test-call-hotel-crm-1",
        "from": "919072140018",       # same number, different formatting
        "to": "918000000000",
        "type": "Incoming",
        "status": "Completed",
        "duration": 95,
        "start_time": frappe.utils.now_datetime(),
    }).insert(ignore_permissions=True)
    call.reload()
    check("call matched to the enquiry", call.custom_hotel_enquiry == enquiry.name,
          call.custom_hotel_enquiry)

    enquiry.reload()
    check("enquiry last_contacted stamped", enquiry.last_contacted, enquiry.last_contacted)
    check("first_call_log stamped", enquiry.first_call_log == call.name, enquiry.first_call_log)

    history = telephony.get_calls_for_enquiry(enquiry.name)
    check("call appears in enquiry history", any(c.name == call.name for c in history), len(history))

    print("\n6. An unknown number stays unlinked, then becomes an enquiry")
    orphan = frappe.get_doc({
        "doctype": "CRM Call Log",
        "id": "test-call-hotel-crm-2",
        "from": "917777700001",
        "to": "918000000000",
        "type": "Incoming",
        "status": "Completed",
        "duration": 40,
        "start_time": frappe.utils.now_datetime(),
    }).insert(ignore_permissions=True)
    orphan.reload()
    check("unknown number is not linked", not orphan.custom_hotel_enquiry)

    unlinked = telephony.get_unlinked_calls(limit=100)
    check("orphan shows in the unattended queue",
          any(c.name == orphan.name for c in unlinked), len(unlinked))

    new_enquiry = telephony.create_enquiry_from_call(orphan.name)
    orphan.reload()
    check("enquiry created from the call", frappe.db.exists("Hotel Enquiry", new_enquiry), new_enquiry)
    check("call now linked back", orphan.custom_hotel_enquiry == new_enquiry)

    created = frappe.get_doc("Hotel Enquiry", new_enquiry)
    check("number carried over", telephony.match_key(created.mobile_no) == "7777700001",
          created.mobile_no)
    check("source defaulted to Phone Call", created.source == "Phone Call", created.source)

    check("calling it twice is idempotent",
          telephony.create_enquiry_from_call(orphan.name) == new_enquiry)

    print("\n7. Follow-up logging")
    from hospitality_core.hospitality_core.doctype.hotel_enquiry.hotel_enquiry import log_follow_up

    result = log_follow_up(
        enquiry.name, outcome="Connected", remarks="Wants sea view, will confirm tomorrow",
        next_follow_up=add_days(nowdate(), 1),
    )
    enquiry.reload()
    check("follow-up appended", len(enquiry.follow_ups) == 1, len(enquiry.follow_ups))
    check("follow-up attributed", enquiry.follow_ups[0].user == frappe.session.user)
    check("next follow-up set", result.get("next_follow_up"), result.get("next_follow_up"))
    check("last_contacted advanced by a Connected outcome", enquiry.last_contacted)


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
