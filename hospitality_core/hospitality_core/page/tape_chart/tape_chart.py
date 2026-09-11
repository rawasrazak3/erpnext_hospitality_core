import frappe
from frappe.utils import getdate

from hospitality_core.hospitality_core.api import tariff

@frappe.whitelist()
def get_chart_data(start_date, end_date):
    # 1. Get all Enabled Rooms
    rooms = frappe.get_all("Hotel Room", 
        filters={"is_enabled": 1}, 
        fields=["name", "room_number", "room_type", "status", "floor"],
        order_by="room_number asc"
    )

    # Each row shows what the unit actually is — bed layout, capacity, amenities —
    # rather than just its name, so the chart is readable without a second lookup.
    catalog = {t["name"]: t for t in tariff.get_room_type_catalog(only_active=False)}
    for room in rooms:
        details = catalog.get(room.room_type) or {}
        room["max_occupancy"] = details.get("max_occupancy")
        room["bedroom_configuration"] = details.get("bedroom_configuration")
        room["amenities"] = details.get("amenities", [])
        room["default_rate"] = details.get("default_rate")
        room["weekend_rate"] = details.get("weekend_rate")

    # 2. Get Reservations in range using full datetime comparison
    # Logic: Arrival < End AND Departure > Start
    bookings = frappe.db.sql("""
        SELECT name, guest, room, arrival_date, arrival_time, departure_date, departure_time, status
        FROM `tabHotel Reservation`
        WHERE status IN ('Reserved', 'Checked In')
        AND CAST(CONCAT(arrival_date, ' ', IFNULL(NULLIF(arrival_time, ''), '14:00:00')) AS DATETIME) < %(end)s
        AND CAST(CONCAT(departure_date, ' ', IFNULL(NULLIF(departure_time, ''), '12:00:00')) AS DATETIME) > %(start)s
    """, {"start": f"{start_date} 14:00:00", "end": f"{end_date} 12:00:00"}, as_dict=True)

    return {
        "rooms": rooms,
        "bookings": bookings
    }