import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

def add_custom_fields():
    custom_fields = {
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
                "description": "Generated from Guest Folio"
            }
        ],
        "Payment Entry": [
            {
                "fieldname": "guest_folio",
                "label": "Guest Folio",
                "fieldtype": "Link",
                "options": "Guest Folio",
                "insert_after": "party_name",
                "read_only": 1,
                "allow_on_submit": 1,
                "print_hide": 1,
                "description": "Payment for Guest Folio"
            }
        ]
    }
    
    frappe.flags.ignore_permissions = True
    create_custom_fields(custom_fields, ignore_validate=True)
    frappe.db.commit()
    print("Custom fields 'guest_folio' successfully added to Sales Invoice and Payment Entry.")

if __name__ == "__main__":
    add_custom_fields()
