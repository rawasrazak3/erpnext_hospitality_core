import frappe

from hospitality_core.hospitality_core.api import tariff


@frappe.whitelist()
def get_room_statuses():
    rooms = frappe.get_all("Hotel Room",
        fields=["name", "room_number", "status", "room_type", "floor"],
        filters={"is_enabled": 1},
        order_by="room_number asc"
    )

    # Housekeeping needs to know what is in a room to service it — a suite with a
    # fridge and a private pool is not the same turnaround as a tent house.
    catalog = {t["name"]: t for t in tariff.get_room_type_catalog(only_active=False)}
    for room in rooms:
        details = catalog.get(room.room_type) or {}
        room["max_occupancy"] = details.get("max_occupancy")
        room["bedroom_configuration"] = details.get("bedroom_configuration")
        room["amenities"] = details.get("amenities", [])

    return rooms

@frappe.whitelist()
def set_room_status(room, status):
    # Security check: Ensure user is Housekeeping or Manager
    if not frappe.has_permission("Hotel Room", "write"):
        frappe.throw("Not authorized to change room status")
    
    # If marking as "Available" (Clean), checking if there is still an active guest
    if status == "Available":
        active_res = frappe.db.exists("Hotel Reservation", {
            "room": room,
            "status": "Checked In"
        })
        if active_res:
            # Guest is still here, so status should be Occupied, not Available
            status = "Occupied"

    frappe.db.set_value("Hotel Room", room, "status", status)
    return True