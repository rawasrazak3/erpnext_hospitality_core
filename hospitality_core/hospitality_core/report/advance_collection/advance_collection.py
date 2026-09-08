# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""Advances received in a period.

Cash the resort actually holds for stays that have not happened yet. Deliberately keyed
off the Payment Entry posting date (when the money arrived), not the arrival date, so it
reconciles against the day's banking.
"""

import frappe
from frappe import _


def execute(filters=None):
    filters = filters or {}
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 100},
        {"label": _("Booking"), "fieldname": "booking", "fieldtype": "Link",
         "options": "Hotel Booking", "width": 130},
        {"label": _("Guest"), "fieldname": "guest_name", "fieldtype": "Data", "width": 160},
        {"label": _("Mobile"), "fieldname": "mobile_no", "fieldtype": "Data", "width": 120},
        {"label": _("Arrival"), "fieldname": "arrival_date", "fieldtype": "Date", "width": 100},
        {"label": _("Source"), "fieldname": "booking_source", "fieldtype": "Data", "width": 110},
        {"label": _("Mode"), "fieldname": "mode_of_payment", "fieldtype": "Link",
         "options": "Mode of Payment", "width": 110},
        {"label": _("Reference"), "fieldname": "reference_no", "fieldtype": "Data", "width": 120},
        {"label": _("Received By"), "fieldname": "cashier", "fieldtype": "Link",
         "options": "User", "width": 140},
        {"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 120},
        {"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
        {"label": _("Payment Entry"), "fieldname": "payment_entry", "fieldtype": "Link",
         "options": "Payment Entry", "width": 140},
    ]


def get_data(filters):
    conditions = ["pe.docstatus = 1", "pe.posting_date BETWEEN %(from_date)s AND %(to_date)s"]
    params = {"from_date": filters.get("from_date"), "to_date": filters.get("to_date")}

    if filters.get("hotel_reception"):
        conditions.append("pe.hotel_reception = %(reception)s")
        params["reception"] = filters.get("hotel_reception")
    if filters.get("mode_of_payment"):
        conditions.append("pe.mode_of_payment = %(mop)s")
        params["mop"] = filters.get("mode_of_payment")
    if filters.get("cashier"):
        conditions.append("pe.cashier = %(cashier)s")
        params["cashier"] = filters.get("cashier")

    return frappe.db.sql(
        """
        SELECT pe.posting_date,
               b.name AS booking,
               b.guest_name,
               b.mobile_no,
               b.arrival_date,
               b.booking_source,
               pe.mode_of_payment,
               pe.reference_no,
               pe.cashier,
               CASE WHEN pe.payment_type = 'Pay' THEN -pe.paid_amount ELSE pe.paid_amount END AS amount,
               b.status,
               pe.name AS payment_entry
        FROM `tabPayment Entry` pe
        JOIN `tabHotel Booking` b ON b.name = pe.hotel_booking
        WHERE {conditions}
        ORDER BY pe.posting_date DESC, pe.name DESC
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )
