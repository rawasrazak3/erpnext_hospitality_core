"""Quick health read of the hospitality module. Read-only."""

import frappe


def run():
    print("\n--- Desk pages (script + style load from disk) ---")
    for name in ("hotel-crm", "hotel-pos"):
        page = frappe.get_doc("Page", name)
        page.load_assets()
        print(f"  {name:12} js={len(page.get('script') or '')}b  css={len(page.get('style') or '')}b")

    print("\n--- Form scripts the client will load ---")
    # frappe.get_meta does not carry __js; the desk builds it through form.meta.
    from frappe.desk.form.meta import get_meta as get_form_meta

    for dt in ("Hotel Booking", "Hotel Enquiry", "Hotel Reservation", "Guest Folio"):
        js = get_form_meta(dt).get("__js") or ""
        print(f"  {dt:20} {len(js)}b {'OK' if js else 'MISSING'}")

    print("\n--- Whitelisted API surface ---")
    modules = [
        "hospitality_core.hospitality_core.api.availability",
        "hospitality_core.hospitality_core.api.advance",
        "hospitality_core.hospitality_core.api.telephony",
        "hospitality_core.hospitality_core.page.hotel_crm.hotel_crm",
        "hospitality_core.hospitality_core.page.hotel_pos.hotel_pos",
        "hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking",
        "hospitality_core.hospitality_core.doctype.hotel_enquiry.hotel_enquiry",
        "hospitality_core.hospitality_core.doctype.hotel_reservation.hotel_reservation",
    ]
    total = 0
    for path in modules:
        mod = frappe.get_module(path)
        names = [
            n for n in dir(mod)
            if getattr(getattr(mod, n, None), "__dict__", {}).get("whitelisted")
            or n in getattr(frappe, "whitelisted", set())
        ]
        fns = [n for n in dir(mod) if callable(getattr(mod, n, None))
               and getattr(getattr(mod, n), "__module__", "") == mod.__name__]
        total += len(fns)
        print(f"  {path.split('.')[-1]:22} {len(fns)} callable(s)")
    print(f"  total {total}")

    print("\n--- Reports ---")
    reports = frappe.get_all("Report", filters={"module": "Hospitality Core"},
                             fields=["name", "disabled"], order_by="name")
    broken = []
    for r in reports:
        try:
            frappe.get_module(
                "hospitality_core.hospitality_core.report."
                f"{frappe.scrub(r.name)}.{frappe.scrub(r.name)}"
            )
        except Exception as e:
            broken.append((r.name, str(e)[:60]))
    print(f"  {len(reports)} reports; {len(broken)} failed to import")
    for name, err in broken:
        print(f"    BROKEN {name}: {err}")

    print("\n--- Scheduled jobs ---")
    for job in frappe.get_all("Scheduled Job Type",
                              filters={"method": ["like", "%hospitality%"]},
                              fields=["method", "cron_format", "stopped", "last_execution"]):
        state = "STOPPED" if job.stopped else "active"
        print(f"  {job.cron_format:12} {state:8} last={job.last_execution} {job.method.split('.')[-1]}")

    print("\n--- Print formats ---")
    for pf in frappe.get_all("Print Format", filters={"module": "Hospitality Core"},
                             fields=["name", "doc_type"], order_by="doc_type"):
        print(f"  {pf.doc_type:20} {pf.name}")
