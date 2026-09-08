"""Create the custom fields this app has always assumed existed.

`hospitality_core.setup.after_install` only runs on a fresh install, so sites that
installed the app before these fields were declared have no
`Payment Entry.guest_folio` / `.hotel_reception` / `.room_number` / `.cashier` and no
`Sales Invoice.guest_folio`.

The consequence is silent and total: `payment_bridge.process_payment_entry` opens with

    if not doc.get("guest_folio") or not frappe.db.exists("Guest Folio", doc.guest_folio):
        return

so every Payment Entry returns early and no payment ever reaches a folio, while
`create_folio_payment`'s `frappe.get_all("Sales Invoice", filters={"guest_folio": ...})`
raises on an unknown column.
"""

import frappe

from hospitality_core.setup import setup_custom_fields


def execute():
    setup_custom_fields()
    frappe.db.commit()
