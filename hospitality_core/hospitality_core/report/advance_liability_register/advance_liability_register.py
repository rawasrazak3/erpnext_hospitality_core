# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""Advances still held for stays that have not happened.

This is the balancing report for the Advance Liability account: the sum of the Held
column should equal that account's balance. A row here is money the resort owes a guest
in the form of a stay.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate


def execute(filters=None):
    filters = filters or {}
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Booking"), "fieldname": "booking", "fieldtype": "Link",
         "options": "Hotel Booking", "width": 130},
        {"label": _("Guest"), "fieldname": "guest_name", "fieldtype": "Data", "width": 160},
        {"label": _("Mobile"), "fieldname": "mobile_no", "fieldtype": "Data", "width": 120},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": _("Arrival"), "fieldname": "arrival_date", "fieldtype": "Date", "width": 100},
        {"label": _("Days To Arrival"), "fieldname": "days_to_arrival", "fieldtype": "Int", "width": 120},
        {"label": _("Booking Value"), "fieldname": "total_amount", "fieldtype": "Currency", "width": 120},
        {"label": _("Advance Received"), "fieldname": "advance_received", "fieldtype": "Currency", "width": 140},
        {"label": _("Still Held"), "fieldname": "held", "fieldtype": "Currency", "width": 120},
        {"label": _("Balance Due"), "fieldname": "balance_due", "fieldtype": "Currency", "width": 120},
        {"label": _("Folio"), "fieldname": "booking_folio", "fieldtype": "Link",
         "options": "Guest Folio", "width": 130},
    ]


def get_data(filters):
    conditions = [
        "IFNULL(b.booking_folio, '') != ''",
        "b.status NOT IN ('Completed', 'Cancelled')",
    ]
    params = {}

    if filters.get("as_on"):
        conditions.append("b.arrival_date >= %(as_on)s OR b.status = 'Confirmed'")
        params["as_on"] = filters.get("as_on")
    if filters.get("hotel_reception"):
        conditions.append("b.hotel_reception = %(reception)s")
        params["reception"] = filters.get("hotel_reception")

    rows = frappe.db.sql(
        """
        SELECT b.name AS booking, b.guest_name, b.mobile_no, b.status,
               b.arrival_date, b.total_amount, b.advance_received, b.balance_due,
               b.booking_folio,
               -- a credit balance on the booking folio is money not yet applied
               GREATEST(-IFNULL(gf.outstanding_balance, 0), 0) AS held
        FROM `tabHotel Booking` b
        JOIN `tabGuest Folio` gf ON gf.name = b.booking_folio
        WHERE {conditions}
        ORDER BY b.arrival_date ASC
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )

    today = getdate(nowdate())
    out = []
    for row in rows:
        if flt(row.held) <= 0.01:
            continue
        row["days_to_arrival"] = (getdate(row.arrival_date) - today).days
        out.append(row)
    return out
