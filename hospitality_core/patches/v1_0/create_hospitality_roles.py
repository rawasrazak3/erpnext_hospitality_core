"""Create this app's roles before any doctype that references them is synced."""

import frappe

from hospitality_core.setup import create_roles


def execute():
    create_roles()
    frappe.db.commit()
