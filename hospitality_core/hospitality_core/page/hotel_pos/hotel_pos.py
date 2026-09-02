import frappe
from frappe import _
from frappe.utils import getdate, flt
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
        if not room.is_enabled or room.status == "Out of Order":
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
    if data.get("is_new_guest"):
        gd = data.get("guest_details", {})
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
