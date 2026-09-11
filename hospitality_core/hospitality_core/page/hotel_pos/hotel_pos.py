import frappe
from frappe import _
from frappe.utils import getdate, flt

from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import BLOCKED_STATUSES
import json

@frappe.whitelist()
def get_pos_data(arrival, departure, arrival_time=None, departure_time=None):
    """
    Returns live room inventory for the specified date+time range.
    Rooms are marked Available, Occupied, or Maintenance.
    Also returns room type metadata for grouping.
    """
    if getdate(departure) < getdate(arrival):
        return {"rooms": [], "room_types": []}

    # Default times if not provided
    arr_time = arrival_time or "14:00:00"
    dep_time = departure_time or "12:00:00"

    rooms = frappe.get_all("Hotel Room",
        fields=["name", "room_type", "status", "is_enabled"],
        order_by="room_type asc, name asc"
    )

    # Fetch room types with rates and descriptions
    room_types = frappe.get_all("Hotel Room Type",
        fields=["name", "default_rate", "max_adults", "max_children", "description"],
        order_by="name asc"
    )
    rate_map = {rt.name: flt(rt.default_rate) for rt in room_types}

    # Fetch overlapping reservations using full datetime comparison
    # CONCAT(date, time) builds a full datetime for accurate overlap detection
    conflicts = frappe.db.sql("""
        SELECT DISTINCT room
        FROM `tabHotel Reservation`
        WHERE status IN ('Reserved', 'Checked In')
        AND CAST(CONCAT(arrival_date, ' ', IFNULL(NULLIF(arrival_time, ''), '14:00:00')) AS DATETIME) < %s
        AND CAST(CONCAT(departure_date, ' ', IFNULL(NULLIF(departure_time, ''), '12:00:00')) AS DATETIME) > %s
    """, (f"{departure} {dep_time}", f"{arrival} {arr_time}"), as_dict=True)
    conflict_rooms = [c.room for c in conflicts]

    pos_rooms = []
    for room in rooms:
        status = "Available"
        # Both blocking statuses collapse into one unsellable bucket here; the POS
        # only needs to know the room cannot be sold, not why.
        if not room.is_enabled or room.status in BLOCKED_STATUSES:
            status = "Maintenance"
        elif room.name in conflict_rooms:
            status = "Occupied"

        pos_rooms.append({
            "name": room.name,
            "room_type": room.room_type,
            "rate": rate_map.get(room.room_type, 0.0),
            "status": status
        })

    return {
        "rooms": pos_rooms,
        "room_types": [{"name": rt.name, "rate": flt(rt.default_rate),
                        "max_adults": rt.max_adults, "description": rt.description}
                       for rt in room_types]
    }

@frappe.whitelist()
def search_guests(query):
    """Quick guest search by name or phone."""
    if not query or len(query) < 2:
        return []
    return frappe.get_all("Guest",
        filters=[
            ["Guest", "full_name", "like", f"%{query}%"]
        ],
        or_filters=[
            ["Guest", "mobile_no", "like", f"%{query}%"]
        ],
        fields=["name", "full_name", "mobile_no", "email_id"],
        limit=10
    )

@frappe.whitelist()
def submit_pos_booking(payload):
    """
    Creates Guest (if new) and Hotel Reservation records.
    Returns reservation names for navigation.
    """
    data = json.loads(payload)

    # 1. Resolve Guest
    guest = data.get("guest")
    gd = None
    if data.get("is_new_guest"):
        gd = data.get("guest_details", {})

        # Reuse an existing Guest with this phone number instead of blindly inserting.
        # Without this, a guest who booked by phone gets a SECOND Guest record at the
        # desk, and their advance ends up stranded on the first one's folio.
        existing = find_guest_by_phone(gd.get("phone"))
        if existing:
            return_guest = frappe.get_doc("Guest", existing)
            # Fill in anything the desk collected that we did not already hold.
            updates = {}
            for field, value in (
                ("email_id", gd.get("email")),
                ("address", gd.get("address")),
                ("aadhaar_number", gd.get("aadhaar")),
                ("pan_number", gd.get("pan")),
            ):
                if value and not return_guest.get(field):
                    updates[field] = value
            if updates:
                frappe.db.set_value("Guest", existing, updates)
            guest = existing
            gd = None

    if gd is not None:
        new_guest = frappe.get_doc({
            "doctype": "Guest",
            "full_name": gd.get("full_name"),
            "guest_type": gd.get("guest_type") or "Regular",
            "gender": gd.get("gender") or None,
            "mobile_no": gd.get("phone"),
            "email_id": gd.get("email"),
            "address": gd.get("address") or None,
            "nationality": gd.get("nationality") or "Indian",
            "aadhaar_number": gd.get("aadhaar") or None,
            "pan_number": gd.get("pan") or None,
            "special_requests": gd.get("special_requests") or None
        })
        new_guest.insert(ignore_permissions=True)
        guest = new_guest.name

    if not guest:
        frappe.throw(_("Guest is required to create a booking."))

    company = frappe.db.get_single_value("Hospitality Accounting Settings", "company") \
              or frappe.defaults.get_user_default("Company")
              
    reception = frappe.db.get_value("Hotel Reception", filters={})

    # Calculate date and time based on Policy
    billing_policy = frappe.db.get_single_value("Hospitality Accounting Settings", "billing_policy") or "Fixed Time"
    
    arrival_date_str = data.get("arrival")
    departure_date_str = data.get("departure")
    
    now_dt = frappe.utils.now_datetime()
    today_date_str = frappe.utils.nowdate()
    
    # Check if arrival is today. If so, they are checking in right now.
    is_today = (arrival_date_str == today_date_str)

    # Get time values from payload, or compute defaults
    arrival_time_str = data.get("arrival_time")
    departure_time_str = data.get("departure_time")
    
    if billing_policy == "24-Hour":
        if is_today:
            # Arriving right now — use current time
            if not arrival_time_str:
                arrival_time_str = now_dt.strftime("%H:%M:%S")
        else:
            # Future booking, assume 14:00 checkin as standard fallback
            if not arrival_time_str:
                arrival_time_str = "14:00:00"
            
        # Departure time = same time as arrival (24-hour policy)
        if not departure_time_str:
            departure_time_str = arrival_time_str
        
    else:
        # Fixed Time Policy
        std_in = frappe.db.get_single_value("Hospitality Accounting Settings", "standard_check_in_time") or "14:00:00"
        std_out = frappe.db.get_single_value("Hospitality Accounting Settings", "standard_check_out_time") or "12:00:00"
        
        if is_today:
            if not arrival_time_str:
                arrival_time_str = now_dt.strftime("%H:%M:%S")  # Walk-ins always check-in right now
        else:
            if not arrival_time_str:
                arrival_time_str = std_in
            
        if not departure_time_str:
            departure_time_str = std_out

    # 2. Create Reservations (one per room)
    reservations = []
    for room in data.get("rooms", []):
        res = frappe.get_doc({
            "doctype": "Hotel Reservation",
            "guest": guest,
            "room": room,
            "arrival_date": arrival_date_str,
            "arrival_time": arrival_time_str,
            "departure_date": departure_date_str,
            "departure_time": departure_time_str,
            "adults": int(data.get("adults") or 1),
            "status": "Reserved",
            "hotel_reception": reception,
            "room_type": frappe.db.get_value("Hotel Room", room, "room_type")
        })
        res.insert(ignore_permissions=True)
        reservations.append(res.name)

    return {
        "success": True,
        "reservations": reservations,
        "guest": guest
    }


# ---------------------------------------------------------------------------
# Arrivals: pulling a booking made earlier by the sales team.
#
# Until now this page could only ever create a NEW reservation. A guest who booked by
# phone and paid an advance could not be processed at all: their room showed as Occupied
# and was un-clickable, the guest lookup created a duplicate Guest record, and confirming
# threw "Room is already booked". These endpoints are the other half of the flow.
# ---------------------------------------------------------------------------

from hospitality_core.hospitality_core.api import advance as advance_api
from hospitality_core.hospitality_core.api import availability as availability_api
from hospitality_core.hospitality_core.api.telephony import match_key


@frappe.whitelist()
def get_arrivals(date=None, search=None, include_inhouse=0):
    """Bookings and reservations due to arrive.

    Anything still expected on or before `date` is included, so a guest who was due
    yesterday and turns up today is not invisible to the front desk.
    """
    date = date or frappe.utils.nowdate()
    params = {"date": date}
    conditions = ["b.status IN ('Confirmed', 'Tentative')", "b.arrival_date <= %(date)s"]

    if search:
        key = match_key(search)
        if key:
            conditions.append("REPLACE(REPLACE(IFNULL(b.mobile_no,''),' ',''),'-','') LIKE %(like)s")
            params["like"] = f"%{key}%"
        else:
            conditions.append("(b.guest_name LIKE %(txt)s OR b.name LIKE %(txt)s)")
            params["txt"] = f"%{search}%"

    bookings = frappe.db.sql(
        """
        SELECT b.name, b.guest, b.guest_name, b.mobile_no, b.status,
               b.arrival_date, b.departure_date, b.nights,
               b.total_amount, b.advance_received, b.balance_due,
               b.booking_folio,
               (SELECT COUNT(*) FROM `tabHotel Booking Room` r WHERE r.parent = b.name) AS room_count
        FROM `tabHotel Booking` b
        WHERE {conditions}
        ORDER BY b.arrival_date ASC, b.name ASC
        LIMIT 100
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )

    # Walk-in reservations created directly on this page have no Hotel Booking parent,
    # so surface those too or the front desk would not find them here.
    res_conditions = ["r.status = 'Reserved'", "r.arrival_date <= %(date)s",
                      "IFNULL(r.hotel_booking, '') = ''"]
    res_params = {"date": date}
    if search:
        res_conditions.append("(g.full_name LIKE %(txt)s OR g.mobile_no LIKE %(txt)s OR r.name LIKE %(txt)s)")
        res_params["txt"] = f"%{search}%"

    loose = frappe.db.sql(
        """
        SELECT r.name, r.guest, g.full_name AS guest_name, g.mobile_no,
               r.status, r.arrival_date, r.departure_date, r.room, r.room_type, r.folio
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabGuest` g ON g.name = r.guest
        WHERE {conditions}
        ORDER BY r.arrival_date ASC
        LIMIT 100
        """.format(conditions=" AND ".join(res_conditions)),
        res_params,
        as_dict=True,
    )

    return {"bookings": bookings, "reservations": loose, "date": date}


@frappe.whitelist()
def get_arrival_detail(booking=None, reservation=None):
    """Everything the POS needs to check one arrival in."""
    if booking:
        doc = frappe.get_doc("Hotel Booking", booking)
        rooms = []
        for line in doc.rooms:
            rooms.append({
                "idx": line.idx,
                "room_type": line.room_type,
                "room": line.room,
                "reservation": line.reservation,
                "rate": line.rate,
                "amount": line.amount,
                "reservation_status": frappe.db.get_value(
                    "Hotel Reservation", line.reservation, "status"
                ) if line.reservation else None,
            })

        # Free rooms per type, so unassigned lines can be given a room at the desk.
        options = {}
        for line in doc.rooms:
            if line.room or line.room_type in options:
                continue
            options[line.room_type] = availability_api.get_free_rooms(
                doc.arrival_date, doc.departure_date, room_type=line.room_type,
                ignore_booking=doc.name,
            )

        return {
            "type": "booking",
            "name": doc.name,
            "guest": doc.guest,
            "guest_name": doc.guest_name,
            "mobile_no": doc.mobile_no,
            "status": doc.status,
            "arrival_date": doc.arrival_date,
            "departure_date": doc.departure_date,
            "nights": doc.nights,
            "adults": doc.adults,
            "children": doc.children,
            "total_amount": doc.total_amount,
            "advance_received": doc.advance_received,
            "balance_due": doc.balance_due,
            "unapplied_advance": advance_api.get_advance_balance(doc.name),
            "special_requests": doc.special_requests,
            "rooms": rooms,
            "room_options": options,
        }

    if reservation:
        res = frappe.get_doc("Hotel Reservation", reservation)
        guest = frappe.db.get_value(
            "Guest", res.guest, ["full_name", "mobile_no"], as_dict=True
        ) or {}
        return {
            "type": "reservation",
            "name": res.name,
            "guest": res.guest,
            "guest_name": guest.get("full_name"),
            "mobile_no": guest.get("mobile_no"),
            "status": res.status,
            "arrival_date": res.arrival_date,
            "departure_date": res.departure_date,
            "unapplied_advance": 0,
            "rooms": [{
                "idx": 1, "room_type": res.room_type, "room": res.room,
                "reservation": res.name, "reservation_status": res.status,
            }],
            "room_options": {},
        }

    frappe.throw(_("Pass either a booking or a reservation."))


@frappe.whitelist()
def checkin_arrival(booking=None, reservation=None, room_assignments=None):
    """Check a pre-made arrival in, assigning rooms and applying any advance.

    `room_assignments` is {booking_room_idx: room_name} for lines that had no room.
    """
    if reservation and not booking:
        res = frappe.get_doc("Hotel Reservation", reservation)
        res.process_check_in()
        return {"checked_in": [res.name], "advance_applied": 0.0}

    doc = frappe.get_doc("Hotel Booking", booking)
    doc.check_permission("write")

    if doc.status in ("Cancelled", "Completed"):
        frappe.throw(_("Booking {0} is {1}.").format(doc.name, doc.status))

    assignments = room_assignments
    if isinstance(assignments, str):
        assignments = json.loads(assignments or "{}")
    assignments = assignments or {}

    for line in doc.rooms:
        chosen = assignments.get(str(line.idx)) or assignments.get(line.idx)
        if chosen and not line.room:
            line.room = chosen
    doc.save(ignore_permissions=True)
    doc.reload()

    # Tentative bookings arriving as walk-ins still need reservations created.
    if doc.status in ("Draft", "Tentative"):
        doc.confirm()
        doc.reload()
    else:
        doc.create_reservations()
        doc.reload()

    checked_in = []
    applied_total = 0.0

    for line in doc.rooms:
        if not line.reservation:
            continue
        res = frappe.get_doc("Hotel Reservation", line.reservation)
        if res.status == "Reserved":
            res.process_check_in()
            checked_in.append(res.name)
        elif res.status == "No Show":
            # The guest turned up late. Put them back in play rather than making the
            # desk rebuild the booking from scratch.
            res.db_set("status", "Reserved")
            res.reload()
            res.process_check_in()
            checked_in.append(res.name)

        # Spread the advance across the rooms as they check in.
        result = advance_api.apply_advance(doc.name, res.name)
        applied_total += flt(result.get("applied"))

    doc.db_set("status", "Checked In")

    return {
        "booking": doc.name,
        "checked_in": checked_in,
        "advance_applied": applied_total,
        "balance_due": doc.balance_due,
    }


def find_guest_by_phone(mobile_no):
    """Existing Guest with this number, matched on the last 10 digits."""
    key = match_key(mobile_no)
    if not key:
        return None
    rows = frappe.db.sql(
        """
        SELECT name FROM `tabGuest`
        WHERE RIGHT(REGEXP_REPLACE(IFNULL(mobile_no, ''), '[^0-9]', ''), 10) = %s
        ORDER BY modified DESC LIMIT 1
        """,
        (key,),
    )
    return rows[0][0] if rows else None
