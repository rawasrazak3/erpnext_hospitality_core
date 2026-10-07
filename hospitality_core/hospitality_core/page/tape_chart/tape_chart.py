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

    # 2. Stays with at least one night shown on the chart. The chart's columns are the
    # nights start_date..end_date inclusive; a stay holds arrival_date <= night <
    # departure_date (times play no part — see api.availability).
    from frappe.utils import add_days

    from hospitality_core.hospitality_core.api.availability import (
        BLOCKING_RESERVATION_STATUSES, _room_holds,
    )

    start = getdate(start_date)
    end = getdate(add_days(end_date, 1))
    if end <= start:
        end = getdate(add_days(start, 1))

    bookings = frappe.db.sql("""
        SELECT name, guest, room, arrival_date, arrival_time, departure_date, departure_time, status
        FROM `tabHotel Reservation`
        WHERE status IN %(statuses)s
        AND arrival_date < %(end)s
        AND departure_date > %(start)s
    """, {"start": start, "end": end, "statuses": BLOCKING_RESERVATION_STATUSES}, as_dict=True)

    # Rooms held on a Tentative/Confirmed booking before a reservation exists block the
    # room just as a reservation does (see api.availability), so the chart shows them.
    for hold in _room_holds(start, end):
        bookings.append({
            "name": hold.booking,
            "doctype": "Hotel Booking",
            "guest": hold.guest_name or hold.guest,
            "room": hold.room,
            "arrival_date": hold.arrival_date,
            "departure_date": hold.departure_date,
            "status": hold.status,
        })

    return {
        "rooms": rooms,
        "bookings": bookings
    }