import frappe
from frappe import _
from hospitality_core.hospitality_core.api.reservation import check_availability

@frappe.whitelist()
def process_room_move(reservation_name, new_room):
    """
    Moves a checked-in guest to a new room.
    1. Validate permissions.
    2. Validate New Room availability.
    3. Mark Old Room 'Available'.
    4. Mark New Room 'Occupied'.
    5. Update Reservation and Folio.
    """
    
    if not ("Frontdesk Supervisor" in frappe.get_roles() or frappe.session.user == "Administrator"):
        frappe.throw(_("Access Denied. Only Frontdesk Supervisors can move rooms."))

    res = frappe.get_doc("Hotel Reservation", reservation_name)
    
    if res.status != "Checked In":
        frappe.throw(_("Room moves are only allowed for Checked In guests."))
        
    if res.room == new_room:
        frappe.throw(_("New Room cannot be the same as Current Room."))

    old_room = res.room
    new_room_type = frappe.db.get_value("Hotel Room", new_room, "room_type")

    # 1. The new room must be free for the remaining nights (at least tonight, even for
    # a guest past their departure).
    today = frappe.utils.getdate(frappe.utils.nowdate())
    end = max(frappe.utils.getdate(res.departure_date), frappe.utils.getdate(frappe.utils.add_days(today, 1)))
    check_availability(new_room, today, end, ignore_reservation=res.name,
                       ignore_booking=res.get("hotel_booking"))

    # 2. Update Documents (Bypass set_only_once restriction)
    res.db_set("room", new_room)

    if new_room_type and res.room_type != new_room_type:
        res.db_set("room_type", new_room_type)
    
    # Update Folio
    if res.folio:
        frappe.db.set_value("Guest Folio", res.folio, "room", new_room)

    # 3. Room statuses from who is actually in each room now.
    from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import refresh_room_status
    refresh_room_status(old_room)
    refresh_room_status(new_room)

    # 4. Log the Move (Optional: Add a comment)
    res.add_comment("Info", _("Moved from Room {0} to Room {1} on {2}").format(
        old_room, new_room, frappe.utils.now_datetime()
    ))
    
    frappe.msgprint(_("Successfully moved guest to Room {0}").format(new_room))
    
    return True