import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields as _create_custom_fields

# Every custom field this app owns. Tagged with module "Hospitality Core" so the
# `fixtures` hook in hooks.py exports them and a fresh site rebuilds them exactly.
#
# These are NOT optional. `payment_bridge.process_payment_entry` returns early unless
# `Payment Entry.guest_folio` is set, and `create_folio_payment` queries
# `Sales Invoice.guest_folio` — without these fields every payment silently fails to
# reach a folio and the invoice lookup raises on an unknown column.
CUSTOM_FIELDS = {
    "Payment Entry": [
        {
            "fieldname": "hospitality_section",
            "label": "Hospitality",
            "fieldtype": "Section Break",
            "insert_after": "party_name",
            "collapsible": 1,
        },
        {
            "fieldname": "guest_folio",
            "label": "Guest Folio",
            "fieldtype": "Link",
            "options": "Guest Folio",
            "insert_after": "hospitality_section",
            "read_only": 1,
            "allow_on_submit": 1,
            "print_hide": 1,
            "description": "Payment for this Guest Folio",
        },
        {
            "fieldname": "hotel_reception",
            "label": "Hotel Reception",
            "fieldtype": "Link",
            "options": "Hotel Reception",
            "insert_after": "guest_folio",
            "allow_on_submit": 1,
            "print_hide": 1,
        },
        {
            "fieldname": "hospitality_col_break",
            "fieldtype": "Column Break",
            "insert_after": "hotel_reception",
        },
        {
            "fieldname": "room_number",
            "label": "Room",
            "fieldtype": "Link",
            "options": "Hotel Room",
            "insert_after": "hospitality_col_break",
            "read_only": 1,
            "allow_on_submit": 1,
            "print_hide": 1,
        },
        {
            "fieldname": "cashier",
            "label": "Cashier",
            "fieldtype": "Link",
            "options": "User",
            "insert_after": "room_number",
            "read_only": 1,
            "allow_on_submit": 1,
            "print_hide": 1,
        },
        {
            "fieldname": "hotel_booking",
            "label": "Hotel Booking",
            "fieldtype": "Link",
            "options": "Hotel Booking",
            "insert_after": "cashier",
            "read_only": 1,
            "allow_on_submit": 1,
            "print_hide": 1,
            "description": "Set when this payment is an advance for a future stay.",
        },
    ],
    "Sales Invoice": [
        {
            "fieldname": "guest_folio",
            "label": "Guest Folio",
            "fieldtype": "Link",
            "options": "Guest Folio",
            "insert_after": "customer",
            "read_only": 1,
            "allow_on_submit": 1,
            "print_hide": 1,
            "description": "Generated from this Guest Folio",
        }
    ],
    # Fed by the Android sync app via crm_mobile_sync. We only add our own link;
    # the sync app and the handset are untouched.
    "CRM Call Log": [
        {
            "fieldname": "custom_hotel_enquiry",
            "label": "Hotel Enquiry",
            "fieldtype": "Link",
            "options": "Hotel Enquiry",
            "insert_after": "custom_contact_name",
            "read_only": 1,
        },
        {
            # Digits-only form of the guest's number on this call, indexed.
            # At 200+ calls/day this table grows by ~70k rows a year; matching it
            # against enquiries with REGEXP_REPLACE would scan every row.
            "fieldname": "custom_number_key",
            "label": "Number Key",
            "fieldtype": "Data",
            "insert_after": "custom_hotel_enquiry",
            "read_only": 1,
            "hidden": 1,
            "search_index": 1,
        },
    ],
    "POS Invoice": [
        {
            "fieldname": "hotel_room",
            "label": "Hotel Room Number",
            "fieldtype": "Link",
            "options": "Hotel Room",
            "insert_after": "customer",
        }
    ],
}


def after_install():
    create_roles()
    setup_custom_fields()
    create_default_data()
    create_crm_default_data()

def create_roles():
    roles = [
        "Hospitality User",
        "Hospitality Manager",
        "Housekeeping Staff",
        # The phone sales team. Distinct from front desk: they work enquiries and
        # bookings, and never touch housekeeping or folio settlement.
        "Hotel Sales Agent",
    ]
    for role in roles:
        if not frappe.db.exists("Role", role):
            frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert()

def setup_custom_fields():
    # Add 'Room Charge' to Mode of Payment if not exists
    if not frappe.db.exists("Mode of Payment", "Room Charge"):
        mode = frappe.new_doc("Mode of Payment")
        mode.mode_of_payment = "Room Charge"
        mode.type = "General"
        mode.insert()

    _create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)

    # Tag them so the `fixtures` hook (filters on module) actually exports them.
    for dt, fields in CUSTOM_FIELDS.items():
        for field in fields:
            name = f"{dt}-{field['fieldname']}"
            if frappe.db.exists("Custom Field", name):
                frappe.db.set_value("Custom Field", name, "module", "Hospitality Core")

def create_default_data():
    # Create default Allowance Reason Codes
    reasons = [
        {"code": "POST-ERR", "desc": "Posting Error", "mgr": 0},
        {"code": "GUEST-SAT", "desc": "Guest Satisfaction / Complaint", "mgr": 1},
        {"code": "MGMT-COMP", "desc": "Management Complementary", "mgr": 1}
    ]
    
    for r in reasons:
        if not frappe.db.exists("Allowance Reason Code", r["code"]):
            frappe.get_doc({
                "doctype": "Allowance Reason Code",
                "reason_code": r["code"],
                "description": r["desc"],
                "requires_manager_approval": r["mgr"]
            }).insert()

    # Create Service Items
    items = [
        {"code": "ROOM-RENT", "name": "Room Rent"},
        {"code": "POS-CHARGE", "name": "POS Charge"},
        {"code": "PAYMENT", "name": "Payment Credit"}
    ]
    # Determine default Item Group
    target_item_group = "Services"
    if not frappe.db.exists("Item Group", "Services"):
        # Find the root item group
        root_item_group = frappe.db.get_value("Item Group", 
            {"parent_item_group": ["in", ["", None]], "is_group": 1}, "name")
        
        if not root_item_group:
             # Fallback: get any group
             root_item_group = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
        
        if root_item_group:
            try:
                frappe.get_doc({
                    "doctype": "Item Group",
                    "item_group_name": "Services",
                    "parent_item_group": root_item_group,
                    "is_group": 0
                }).insert(ignore_permissions=True)
            except Exception:
                # If creation fails, fallback to using the root directly
                target_item_group = root_item_group
        else:
            # Last resort: grab any item group
            target_item_group = frappe.db.get_value("Item Group", {}, "name")
            
    for i in items:
        if not frappe.db.exists("Item", i["code"]):
            item = frappe.new_doc("Item")
            item.item_code = i["code"]
            item.item_name = i["name"]
            item.item_group = target_item_group
            item.is_stock_item = 0
            item.insert(ignore_permissions=True)

# --- Hotel CRM seed data -----------------------------------------------------
# The enquiry pipeline is driven by these masters rather than a hardcoded Select,
# so the resort can rename or reorder stages without a code change.

ENQUIRY_STATUSES = [
    {"status_name": "New", "color": "Gray", "position": 1, "type": "Open"},
    {"status_name": "Contacted", "color": "Blue", "position": 2, "type": "Ongoing"},
    {"status_name": "Quoted", "color": "Purple", "position": 3, "type": "Ongoing"},
    {"status_name": "Negotiation", "color": "Orange", "position": 4, "type": "Ongoing"},
    {"status_name": "Tentative Hold", "color": "Yellow", "position": 5, "type": "Ongoing"},
    {"status_name": "Confirmed", "color": "Green", "position": 6, "type": "Won"},
    {"status_name": "Lost", "color": "Red", "position": 7, "type": "Lost"},
    {"status_name": "Junk", "color": "Gray", "position": 8, "type": "Lost"},
]

ENQUIRY_SOURCES = [
    "Phone Call", "WhatsApp", "Walk-in", "Website", "Referral",
    "Travel Agent", "OTA", "Repeat Guest", "Social Media",
]

LOST_REASONS = [
    "Rate too high", "No availability for the dates", "Chose another property",
    "Trip cancelled", "No response from guest", "Wrong number / not an enquiry",
]


def create_crm_default_data():
    for status in ENQUIRY_STATUSES:
        if not frappe.db.exists("Hotel Enquiry Status", status["status_name"]):
            frappe.get_doc(dict(doctype="Hotel Enquiry Status", **status)).insert(
                ignore_permissions=True
            )

    for source in ENQUIRY_SOURCES:
        if not frappe.db.exists("Hotel Enquiry Source", source):
            frappe.get_doc({
                "doctype": "Hotel Enquiry Source",
                "source_name": source,
                "is_active": 1,
            }).insert(ignore_permissions=True)

    for reason in LOST_REASONS:
        if not frappe.db.exists("Hotel Lost Reason", reason):
            frappe.get_doc({
                "doctype": "Hotel Lost Reason",
                "reason": reason,
            }).insert(ignore_permissions=True)
