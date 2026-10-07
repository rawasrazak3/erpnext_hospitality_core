import frappe
from frappe import _
from frappe.utils import getdate, date_diff, nowdate, get_time
from datetime import datetime, time as dt_time

from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import (
    BLOCKED_STATUSES,
    blocked_reason,
)


def _make_datetime(date_val, time_val, default_time="14:00:00"):
    """
    Combine a Date and a Time field into a full datetime for accurate overlap comparison.
    Falls back to `default_time` (e.g. '14:00:00' for check-in, '12:00:00' for check-out)
    when time_val is None or empty.

    Parsing goes through frappe.utils.get_time, which accepts every shape a Time field
    can actually hold: a string, a datetime.time, or a timedelta. Splitting on ":" and
    calling int() on the parts does not — Frappe stamps a new document's Time fields with
    the current time at microsecond precision ("01:02:22.569617"), so int("22.569617")
    raised ValueError on every reservation created without an explicit arrival time.
    """
    d = getdate(date_val)
    t = _coerce_time(time_val) or _coerce_time(default_time) or dt_time(14, 0, 0)
    return datetime.combine(d, t)


def _coerce_time(value):
    """Return a datetime.time for anything a Time field may hold, else None."""
    if value in (None, ""):
        return None
    try:
        parsed = get_time(value)
    except Exception:
        return None
    # Times are compared to the minute in booking logic; drop microseconds so two
    # equivalent moments never sort differently.
    return parsed.replace(microsecond=0) if parsed else None


@frappe.whitelist()
def check_availability(room, arrival_date, departure_date, ignore_reservation=None,
                       arrival_time=None, departure_time=None, ignore_booking=None):
    """
    Checks if a room is available for the given date+time range.
    Returns True if available, raises ValidationError if not.

    Delegates to api.availability so a reservation respects the same blockers as the
    POS and the CRM: Tentative reservations and rooms held on a booking, not only
    Reserved/Checked In stays. This used to be its own loop, which let a room held on
    a Tentative booking be reserved for somebody else.
    """
    if not room or not arrival_date or not departure_date:
        return

    from hospitality_core.hospitality_core.api.availability import is_room_free

    result = is_room_free(
        room, arrival_date, departure_date,
        arrival_time=arrival_time, departure_time=departure_time,
        ignore_reservation=ignore_reservation, ignore_booking=ignore_booking,
    )
    if not result["free"]:
        frappe.throw(result["reason"])

    return True

def check_bulk_availability(rooms, arrival_date, departure_date, ignore_reservation=None,
                            arrival_time=None, departure_time=None):
    """
    Checks a list of rooms for the given nights and raises one ValidationError listing
    every conflict. Uses the shared rule in api.availability (by night; times are the
    standard ones and play no part).
    """
    if not rooms or not arrival_date or not departure_date:
        return

    from hospitality_core.hospitality_core.api.availability import is_room_free

    conflicts = []
    for room_num in rooms:
        if not frappe.db.exists("Hotel Room", room_num):
            conflicts.append(_("Room {0} does not exist.").format(room_num))
            continue
        result = is_room_free(room_num, arrival_date, departure_date,
                              ignore_reservation=ignore_reservation)
        if not result["free"]:
            conflicts.append(result["reason"])

    if conflicts:
        message = _("The following availability issues were found:") + "<br><br>"
        message += "<div class='alert alert-danger'>"
        message += "<ul>"
        for conflict in conflicts:
            message += f"<li>{conflict}</li>"
        message += "</ul>"
        message += "</div>"
        frappe.throw(message, title=_("Room Availability Conflict"))

    return True

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_available_rooms_for_picker(doctype, txt, searchfield, start, page_len, filters):
    """
    Search picker for rooms that are free for the selected nights.
    Filters: arrival_date, departure_date, room_type, ignore_reservation
    """
    filters = frappe.parse_json(filters)
    arrival = filters.get("arrival_date")
    departure = filters.get("departure_date")
    room_type = filters.get("room_type")
    ignore = filters.get("ignore_reservation")
    txt = (txt or "").lower()
    start, page_len = int(start or 0), int(page_len or 20)

    if not arrival or not departure or getdate(departure) <= getdate(arrival):
        # If dates aren't set, return all rooms of that type (or all if no type)
        return frappe.db.sql("""
            SELECT name, room_type, status
            FROM `tabHotel Room`
            WHERE is_enabled = 1
            AND (%s IS NULL OR room_type = %s)
            AND name LIKE %s
            ORDER BY name ASC
            LIMIT %s, %s
        """, (room_type, room_type, f"%{txt}%", start, page_len))

    from hospitality_core.hospitality_core.api.availability import get_availability

    booking = frappe.db.get_value("Hotel Reservation", ignore, "hotel_booking") if ignore else None
    data = get_availability(arrival, departure, room_type=room_type or None,
                            include_soft_holds=False, ignore_reservation=ignore,
                            ignore_booking=booking)
    rows = [
        (r["name"], r["room_type"], r["status"])
        for r in data["rooms"]
        if r["available"] and txt in r["name"].lower()
    ]
    return rows[start:start + page_len]

def create_folio(reservation_doc):
    """
    Creates a 'Provisional' Guest Folio linked to this reservation.
    """
    if frappe.db.exists("Guest Folio", {"reservation": reservation_doc.name, "status": ["!=", "Cancelled"]}):
        return

    folio = frappe.new_doc("Guest Folio")
    folio.guest = reservation_doc.guest
    folio.reservation = reservation_doc.name
    folio.room = reservation_doc.room
    folio.status = "Provisional"
    folio.company = reservation_doc.company # If corporate booking
    folio.hotel_reception = reservation_doc.hotel_reception
    folio.reserved_by = reservation_doc.reserved_by
    folio.open_date = nowdate()
    
    # Save the Folio
    folio.insert(ignore_permissions=True)
    
    # Link Folio back to Reservation
    reservation_doc.db_set("folio", folio.name)
    frappe.msgprint(_("Guest Folio {0} created successfully.").format(folio.name))

    # Transfer existing balances from the Guest Balance Ledger
    from hospitality_core.hospitality_core.api.folio import transfer_existing_balances
    transfer_existing_balances(folio)

@frappe.whitelist()
def get_room_rate(room=None, rate_plan=None, room_type=None, arrival_date=None,
                  discount_type=None, discount_value=None, is_complimentary=None,
                  extra_beds_adult=0, extra_beds_child=0,
                  agreed_rate=None, is_rate_overridden=0):
    """
    Returns the base rate and discounted rate for the reservation form preview.
    Called by hotel_reservation.js when room, rate_plan, or discount fields change.

    `base_rate` is the tariff for the arrival night — weekday or weekend, whichever the
    date falls on — plus any extra beds, so the preview matches what the night audit
    will post for that night.
    """
    from hospitality_core.hospitality_core.api.night_audit import get_rate
    from frappe.utils import flt, nowdate

    # Resolve room_type from room if not provided
    if room and not room_type:
        room_type = frappe.db.get_value("Hotel Room", room, "room_type")

    if not room_type:
        return {"base_rate": 0, "discount_amount": 0, "final_rate": 0}

    date = arrival_date or nowdate()
    base_rate = flt(get_rate(
        rate_plan, room_type, date,
        reservation={"is_rate_overridden": is_rate_overridden, "agreed_rate": agreed_rate},
    ))

    # Extra beds are a per-night charge on top of the room, so they belong in the
    # figure the desk is quoting from.
    beds = frappe.db.get_value(
        "Hotel Room Type", room_type,
        ["extra_bed_adult_rate", "extra_bed_child_rate"], as_dict=True,
    ) or {}
    extra_bed_amount = (
        frappe.utils.cint(extra_beds_adult) * flt(beds.get("extra_bed_adult_rate"))
        + frappe.utils.cint(extra_beds_child) * flt(beds.get("extra_bed_child_rate"))
    )
    base_rate += extra_bed_amount

    # Calculate discount
    discount_amount = 0.0
    if frappe.utils.cint(is_complimentary):
        discount_amount = base_rate
    elif discount_type == "Percentage":
        discount_amount = base_rate * (flt(discount_value) / 100.0)
    elif discount_type == "Amount":
        discount_amount = flt(discount_value)

    final_rate = base_rate - discount_amount

    return {
        "base_rate": base_rate,
        "extra_bed_amount": extra_bed_amount,
        "discount_amount": discount_amount,
        "final_rate": final_rate
    }