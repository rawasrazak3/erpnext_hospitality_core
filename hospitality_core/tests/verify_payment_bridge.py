"""End-to-end check that money actually reaches a Guest Folio.

This is the Phase 0 acceptance test. Before the missing custom fields were created,
`payment_bridge.process_payment_entry` returned early on every Payment Entry because
`doc.get("guest_folio")` was always falsy, so payments silently never reached a folio.

Everything is created inside a transaction and rolled back at the end, so this can be
run against a live site without leaving any data behind.

Run with:
    bench --site <site> execute hospitality_core.tests.verify_payment_bridge.run
"""

import frappe
from frappe.utils import add_days, flt, nowdate

CHECKS = []


def check(label, condition, detail=""):
    CHECKS.append((label, bool(condition), detail))
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}{(' — ' + str(detail)) if detail else ''}")


def run():
    try:
        _run()
    except Exception:
        import traceback

        print("\n!!! Aborted with an exception:\n")
        traceback.print_exc()
        CHECKS.append(("no exception during run", False, "see traceback above"))
    finally:
        frappe.db.rollback()
        print("\nRolled back — no test data persisted.")

    failed = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed.")
    if failed:
        print("FAILED:")
        for label, _ok, detail in failed:
            print(f"  - {label} {detail}")
        raise SystemExit(1)


def _run():
    settings = frappe.get_single("Hospitality Accounting Settings")

    print("\n1. Configuration")
    check("company set", settings.company, settings.company)
    check("receivable account set", settings.receivable_account, settings.receivable_account)
    check("income suspense account set", settings.income_suspense_account, settings.income_suspense_account)
    check("advance liability account set", settings.advance_liability_account, settings.advance_liability_account)
    check(
        "check-in time is a clock time",
        # Whatever the property chose (it has been 14:00 and 16:00); it must parse.
        bool(settings.standard_check_in_time) and bool(frappe.utils.get_time(settings.standard_check_in_time)),
        settings.standard_check_in_time,
    )

    print("\n2. Custom fields exist as real columns")
    for dt, fieldname in [
        ("Payment Entry", "guest_folio"),
        ("Payment Entry", "hotel_reception"),
        ("Payment Entry", "room_number"),
        ("Payment Entry", "cashier"),
        ("Sales Invoice", "guest_folio"),
    ]:
        check(f"{dt}.{fieldname}", frappe.get_meta(dt).has_field(fieldname))

    print("\n3. Build a minimal property")
    reception = _ensure("Hotel Reception", {"reception_name": "TEST-RECEPTION"})
    room_type = _ensure(
        "Hotel Room Type",
        {"room_type_name": "TEST-DELUXE", "default_rate": 5000, "max_adults": 2, "max_children": 1},
    )
    room = _ensure(
        "Hotel Room",
        {
            "room_number": "TEST-101",
            "room_type": room_type.name,
            "hotel_reception": reception.name,
            "status": "Available",
            "is_enabled": 1,
        },
    )
    check("room created", room.name, room.name)

    guest = frappe.get_doc({
        "doctype": "Guest",
        "full_name": "Payment Bridge Test Guest",
        "mobile_no": "9000000001",
        "guest_type": "Regular",
    }).insert(ignore_permissions=True)
    check("guest auto-created an ERPNext Customer", guest.customer, guest.customer)

    print("\n4. Reservation creates a folio")
    reservation = frappe.get_doc({
        "doctype": "Hotel Reservation",
        "guest": guest.name,
        "room": room.name,
        "room_type": room_type.name,
        "hotel_reception": reception.name,
        "arrival_date": nowdate(),
        "departure_date": add_days(nowdate(), 2),
    }).insert(ignore_permissions=True)
    reservation.reload()
    check("folio back-link set on reservation", reservation.folio, reservation.folio)

    folio = frappe.get_doc("Guest Folio", reservation.folio)
    check("folio starts Provisional", folio.status == "Provisional", folio.status)

    print("\n5. Check in, then take a payment")
    reservation.process_check_in()
    folio.reload()
    check("folio is Open after check-in", folio.status == "Open", folio.status)
    check("first night charged", flt(folio.total_charges) > 0, folio.total_charges)

    charged = flt(folio.total_charges)

    from hospitality_core.hospitality_core.api.payment_bridge import create_folio_payment

    payment_name = create_folio_payment(
        folio_name=folio.name,
        amount=charged,
        mode_of_payment="Cash",
        hotel_reception=reception.name,
    )
    payment = frappe.get_doc("Payment Entry", payment_name)

    check("payment entry submitted", payment.docstatus == 1, payment.name)
    check("guest_folio stored on the payment", payment.guest_folio == folio.name, payment.guest_folio)
    check("cashier stored on the payment", payment.cashier, payment.cashier)

    print("\n6. The payment reached the folio (this is what was broken)")
    credit = frappe.get_all(
        "Folio Transaction",
        filters={"parent": folio.name, "reference_doctype": "Payment Entry", "reference_name": payment.name},
        fields=["item", "amount"],
    )
    check("a folio transaction was posted for the payment", len(credit) == 1, credit)
    if credit:
        check("posted as a credit (negative amount)", flt(credit[0].amount) < 0, credit[0].amount)

    folio.reload()
    check(
        "folio balance settled to zero",
        abs(flt(folio.outstanding_balance)) < 0.01,
        folio.outstanding_balance,
    )


def _ensure(doctype, values):
    """Create the doc if an equivalent one is not already there."""
    key = list(values.keys())[0]
    existing = frappe.db.get_value(doctype, {key: values[key]}, "name")
    if existing:
        return frappe.get_doc(doctype, existing)
    doc = frappe.get_doc(dict(doctype=doctype, **values))
    doc.insert(ignore_permissions=True)
    return doc
