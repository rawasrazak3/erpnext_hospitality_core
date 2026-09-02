import frappe
from frappe.utils import getdate

@frappe.whitelist()
def get_chart_data(start_date, end_date):
    # 1. Get all Enabled Rooms
    rooms = frappe.get_all("Hotel Room", 
        filters={"is_enabled": 1}, 
        fields=["name", "room_number", "room_type"],
        order_by="room_number asc"
    )

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