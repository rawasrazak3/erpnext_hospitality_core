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
                       arrival_time=None, departure_time=None):
    """
    Checks if a room is available for the given date+time range.
    Returns True if available, raises ValidationError if not.
    """
    if not room or not arrival_date or not departure_date:
        return

    # 1. Check if Room is Enabled (Maintenance check)
    room_status = frappe.db.get_value("Hotel Room", room, ["status", "is_enabled"], as_dict=True)
    if not room_status.is_enabled:
        frappe.throw(_("Room {0} is currently disabled/under maintenance.").format(room))
    
    if room_status.status in BLOCKED_STATUSES:
        frappe.throw(blocked_reason(room, room_status.status))

    # Build full datetime for the new booking
    new_arrival_dt = _make_datetime(arrival_date, arrival_time, "14:00:00")
    new_departure_dt = _make_datetime(departure_date, departure_time, "12:00:00")

    # 2. Check Overlapping Reservations
    # Logic: New Arrival < Existing Departure AND New Departure > Existing Arrival
    filters = {
        "room": room,
        "status": ["in", ["Reserved", "Checked In"]],
        "name": ["!=", ignore_reservation] if ignore_reservation else ["is", "set"]
    }
    
    existing_bookings = frappe.get_all("Hotel Reservation", 
        filters=filters,
        fields=["name", "arrival_date", "arrival_time", "departure_date", "departure_time", "guest"]
    )

    for booking in existing_bookings:
        # Build full datetime for the existing booking
        existing_arrival_dt = _make_datetime(booking.arrival_date, booking.arrival_time, "14:00:00")
        existing_departure_dt = _make_datetime(booking.departure_date, booking.departure_time, "12:00:00")

        # Check for strict overlap using full Datetime comparison
        if (new_arrival_dt < existing_departure_dt) and \
           (new_departure_dt > existing_arrival_dt):
            # It's an overlap
            frappe.throw(_("Room {0} is already booked for Guest {1} from {2} to {3}. (Reservation: {4})").format(
                    room, booking.guest, booking.arrival_date, booking.departure_date, booking.name
                )
             )
    
    return True

def check_bulk_availability(rooms, arrival_date, departure_date, ignore_reservation=None,
                            arrival_time=None, departure_time=None):
    """
    Checks if a list of rooms is available for the given date+time range.
    Collects ALL conflicts and raises a single ValidationError.
    """
    if not rooms or not arrival_date or not departure_date:
        return

    conflicts = []

    # Build full datetime for the new booking
    new_arrival_dt = _make_datetime(arrival_date, arrival_time, "14:00:00")
    new_departure_dt = _make_datetime(departure_date, departure_time, "12:00:00")

    # 1. Check Room Maintenance Status for all rooms in batch
    room_data = frappe.get_all("Hotel Room", 
        filters={"room_number": ["in", rooms]},
        fields=["room_number", "status", "is_enabled"]
    )
    
    room_map = {r.room_number: r for r in room_data}

    for room_num in rooms:
        r = room_map.get(room_num)
        if not r:
            conflicts.append(_("Room {0} does not exist.").format(room_num))
            continue
            
        if not r.is_enabled:
            conflicts.append(_("Room {0} is currently disabled/under maintenance.").format(room_num))
        elif r.status in BLOCKED_STATUSES:
            conflicts.append(blocked_reason(room_num, r.status))

    # 2. Check Overlapping Reservations for all rooms in batch
    # Logic: New Arrival < Existing Departure AND New Departure > Existing Arrival
    existing_bookings = frappe.get_all("Hotel Reservation", 
        filters={
            "room": ["in", rooms],
            "status": ["in", ["Reserved", "Checked In"]],
            "name": ["!=", ignore_reservation] if ignore_reservation else ["is", "set"]
        },
        fields=["name", "arrival_date", "arrival_time", "departure_date", "departure_time", "guest", "room"]
    )

    for booking in existing_bookings:
        # Build full datetime for the existing booking
        existing_arrival_dt = _make_datetime(booking.arrival_date, booking.arrival_time, "14:00:00")
        existing_departure_dt = _make_datetime(booking.departure_date, booking.departure_time, "12:00:00")

        # Check for strict overlap using full Datetime comparison
        if (new_arrival_dt < existing_departure_dt) and \
           (new_departure_dt > existing_arrival_dt):
            # Overlap found
            conflicts.append(
                _("Room {0} is already booked for Guest {1} from {2} to {3}. (Reservation: {4})").format(
                    booking.room, booking.guest, booking.arrival_date, booking.departure_date, booking.name
                )
            )

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
    Search picker for rooms that are available for the selected dates.
    Filters: arrival_date, departure_date, room_type, ignore_reservation
    """
    filters = frappe.parse_json(filters)
    arrival = filters.get("arrival_date")
    departure = filters.get("departure_date")
    room_type = filters.get("room_type")
    ignore = filters.get("ignore_reservation")

    if not arrival or not departure:
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

    # Complex Query: Find rooms that are NOT in the overlapping reservations set
    # Uses CONCAT(date, time) to build full datetime for accurate time-based overlap comparison
    return frappe.db.sql("""
        SELECT name, room_type, status
        FROM `tabHotel Room`
        WHERE is_enabled = 1
        AND status NOT IN ({blocked})
        AND (%s IS NULL OR room_type = %s)
        AND name LIKE %s
        AND name NOT IN (
            SELECT room FROM `tabHotel Reservation`
            WHERE status IN ('Reserved', 'Checked In')
            AND name != %s
            AND CAST(CONCAT(arrival_date, ' ', IFNULL(NULLIF(arrival_time, ''), '14:00:00')) AS DATETIME) < %s
            AND CAST(CONCAT(departure_date, ' ', IFNULL(NULLIF(departure_time, ''), '12:00:00')) AS DATETIME) > %s
        )
        ORDER BY name ASC
        LIMIT %s, %s
    """.format(blocked=", ".join(["%s"] * len(BLOCKED_STATUSES))),
        (*BLOCKED_STATUSES, room_type, room_type, f"%{txt}%", ignore or "",
         f"{departure} {filters.get('departure_time') or '12:00:00'}",
         f"{arrival} {filters.get('arrival_time') or '14:00:00'}",
         start, page_len))

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
                  extra_beds_adult=0, extra_beds_child=0):
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
    base_rate = flt(get_rate(rate_plan, room_type, date))

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