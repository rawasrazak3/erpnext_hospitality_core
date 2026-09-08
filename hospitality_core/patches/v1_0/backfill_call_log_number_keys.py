"""Backfill custom_number_key on existing CRM Call Logs and link them to enquiries.

The telephony hook only fires on insert, so call logs written before the Hotel CRM
existed carry no number key and no enquiry link.

Custom fields are synced by the `after_migrate` hook, which runs AFTER post_model_sync
patches — so this ensures the field exists before relying on it rather than silently
doing nothing.
"""

import frappe

from hospitality_core.hospitality_core.api.telephony import backfill_call_keys
from hospitality_core.setup import setup_custom_fields


def execute():
    if not frappe.db.exists("DocType", "CRM Call Log"):
        return
    setup_custom_fields()
    backfill_call_keys()
