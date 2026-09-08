"""Seed the enquiry pipeline masters on an already-installed site.

`after_install` only runs on a fresh install, so an existing site needs this to get the
default statuses / sources / lost reasons that the Hotel CRM pipeline is driven by.
"""

import frappe

from hospitality_core.setup import create_crm_default_data


def execute():
    create_crm_default_data()
    frappe.db.commit()
