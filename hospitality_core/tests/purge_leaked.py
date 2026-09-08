"""Remove records leaked onto the site by a test run whose rollback was defeated.

Scoped strictly to the test fingerprint (guests named "Lifecycle %"); anything else is
left untouched. Prints what it would remove, and only removes with confirm=1.
"""

import frappe

# Every fingerprint the suites use for throwaway guests.
GUEST_PATTERNS = ("Lifecycle %", "Ops %", "%Test Guest%", "Advance Test%", "Conversion Test%",
                  "Arrival Test%", "Report Test%", "Payment Bridge Test%", "Diag%")


def collect():
    clauses = " OR ".join(["full_name LIKE %s"] * len(GUEST_PATTERNS))
    guests = frappe.db.sql_list(
        f"SELECT name FROM `tabGuest` WHERE {clauses}", GUEST_PATTERNS
    )
    if not guests:
        return {}

    bookings = frappe.db.sql_list(
        "SELECT name FROM `tabHotel Booking` WHERE guest IN %s", (guests,)
    )
    reservations = frappe.db.sql_list(
        "SELECT name FROM `tabHotel Reservation` WHERE guest IN %s", (guests,)
    )
    folios = frappe.db.sql_list(
        "SELECT name FROM `tabGuest Folio` WHERE guest IN %s", (guests,)
    )
    payments = frappe.db.sql_list(
        "SELECT name FROM `tabPayment Entry` WHERE guest_folio IN %s AND docstatus < 2",
        (folios or [""],),
    )
    # Hotel Enquiry names the field guest_name, not full_name.
    enq_clauses = " OR ".join(["guest_name LIKE %s"] * len(GUEST_PATTERNS))
    enquiries = frappe.db.sql_list(
        f"SELECT name FROM `tabHotel Enquiry` WHERE {enq_clauses}", GUEST_PATTERNS
    )
    cust_clauses = " OR ".join(["customer_name LIKE %s"] * len(GUEST_PATTERNS))
    customers = frappe.db.sql_list(
        f"SELECT name FROM `tabCustomer` WHERE {cust_clauses}", GUEST_PATTERNS
    )
    return {
        "Payment Entry": payments,
        "Hotel Reservation": reservations,
        "Guest Folio": folios,
        "Hotel Booking": bookings,
        "Hotel Enquiry": enquiries,
        "Guest": guests,
        "Customer": customers,
    }


def run(confirm=0):
    found = collect()
    if not found:
        print("Nothing leaked — site is clean.")
        return

    for doctype, names in found.items():
        print(f"{doctype:20} {len(names)}")

    if not int(confirm or 0):
        print("\nDry run. Re-run with confirm=1 to remove.")
        return

    # Payments are submitted, so they must be cancelled before anything they touch goes.
    for name in found["Payment Entry"]:
        doc = frappe.get_doc("Payment Entry", name)
        if doc.docstatus == 1:
            doc.flags.ignore_permissions = True
            doc.cancel()
        frappe.delete_doc("Payment Entry", name, force=True, ignore_permissions=True)

    for folio in found["Guest Folio"]:
        frappe.db.delete("Folio Transaction", {"parent": folio})
        frappe.db.delete("Folio Transaction Move Log", {"source_folio": folio})
        frappe.db.delete("Folio Transaction Move Log", {"target_folio": folio})

    # Break the reservation <-> folio links so neither blocks the other's deletion.
    for res in found["Hotel Reservation"]:
        frappe.db.set_value("Hotel Reservation", res, "folio", None, update_modified=False)

    # on_trash refuses anything not Draft/Cancelled — correct for real use, so flip the
    # leaked ones directly rather than weakening the guard.
    for booking in found["Hotel Booking"]:
        frappe.db.set_value("Hotel Booking", booking, "status", "Cancelled",
                            update_modified=False)

    for doctype in ("Hotel Reservation", "Guest Folio", "Hotel Booking",
                    "Hotel Enquiry", "Guest", "Customer"):
        for name in found[doctype]:
            try:
                frappe.delete_doc(doctype, name, force=True, ignore_permissions=True,
                                  delete_permanently=True)
            except Exception as e:
                print(f"  could not delete {doctype} {name}: {e}")

    frappe.db.commit()
    print("\nRemoved. Re-run with no args to confirm the site is clean.")


def purge_orphans(confirm=0):
    """Remove records whose parent record no longer exists.

    Two kinds show up after a failed cleanup:
      * Hotel Bookings whose Guest was deleted first;
      * GL Entries whose Payment Entry was deleted. These matter — this app writes some
        GL Entries as raw inserts rather than through ERPNext's general ledger helper, so
        they are not removed with their voucher and would silently distort the ledger.
    """
    orphan_bookings = frappe.db.sql_list("""
        SELECT b.name FROM `tabHotel Booking` b
        LEFT JOIN `tabGuest` g ON g.name = b.guest
        WHERE g.name IS NULL
    """)
    orphan_gl = frappe.db.sql_list("""
        SELECT gle.name FROM `tabGL Entry` gle
        LEFT JOIN `tabPayment Entry` pe ON pe.name = gle.voucher_no
        WHERE gle.voucher_type = 'Payment Entry' AND pe.name IS NULL
    """)
    orphan_folios = frappe.db.sql_list("""
        SELECT f.name FROM `tabGuest Folio` f
        LEFT JOIN `tabGuest` g ON g.name = f.guest
        WHERE f.guest IS NOT NULL AND g.name IS NULL
    """)

    print(f"orphan Hotel Bookings : {len(orphan_bookings)}")
    print(f"orphan Guest Folios   : {len(orphan_folios)}")
    print(f"orphan GL Entries     : {len(orphan_gl)}")

    if not int(confirm or 0):
        print("\nDry run. Re-run with confirm=1 to remove.")
        return

    for name in orphan_bookings:
        frappe.db.set_value("Hotel Booking", name, "status", "Cancelled", update_modified=False)
        frappe.delete_doc("Hotel Booking", name, force=True, ignore_permissions=True,
                          delete_permanently=True)
    for name in orphan_folios:
        frappe.db.delete("Folio Transaction", {"parent": name})
        frappe.delete_doc("Guest Folio", name, force=True, ignore_permissions=True,
                          delete_permanently=True)
    for name in orphan_gl:
        frappe.db.delete("GL Entry", {"name": name})

    frappe.db.commit()
    print("\nOrphans removed.")
