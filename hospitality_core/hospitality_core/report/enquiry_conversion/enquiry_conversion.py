# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""Enquiries in, bookings out — by source and by agent.

Answers the question a 200-calls-a-day operation actually has: which sources and which
agents turn calls into stays, and what that is worth.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    return get_columns(filters), get_data(filters)


def get_columns(filters):
    dimension = filters.get("group_by") or "Source"
    first = {
        "Source": {"label": _("Source"), "fieldname": "dimension", "fieldtype": "Data", "width": 160},
        "Owner": {"label": _("Agent"), "fieldname": "dimension", "fieldtype": "Data", "width": 200},
        "Status": {"label": _("Status"), "fieldname": "dimension", "fieldtype": "Data", "width": 160},
    }[dimension]

    return [
        first,
        {"label": _("Enquiries"), "fieldname": "enquiries", "fieldtype": "Int", "width": 100},
        {"label": _("Quoted Value"), "fieldname": "quoted_total", "fieldtype": "Currency", "width": 130},
        {"label": _("Converted"), "fieldname": "converted", "fieldtype": "Int", "width": 100},
        {"label": _("Conversion %"), "fieldname": "conversion_pct", "fieldtype": "Percent", "width": 120},
        {"label": _("Booked Value"), "fieldname": "booked_value", "fieldtype": "Currency", "width": 130},
        {"label": _("Advance Collected"), "fieldname": "advance", "fieldtype": "Currency", "width": 150},
        {"label": _("Lost"), "fieldname": "lost", "fieldtype": "Int", "width": 80},
    ]


DIMENSION_SQL = {
    "Source": "IFNULL(e.source, 'Unspecified')",
    "Owner": "IFNULL(e.enquiry_owner, 'Unassigned')",
    "Status": "IFNULL(e.status, 'Unknown')",
}


def get_data(filters):
    dimension = DIMENSION_SQL[filters.get("group_by") or "Source"]

    conditions = ["DATE(e.creation) BETWEEN %(from_date)s AND %(to_date)s"]
    params = {"from_date": filters.get("from_date"), "to_date": filters.get("to_date")}

    if filters.get("source"):
        conditions.append("e.source = %(source)s")
        params["source"] = filters.get("source")
    if filters.get("enquiry_owner"):
        conditions.append("e.enquiry_owner = %(owner)s")
        params["owner"] = filters.get("enquiry_owner")

    rows = frappe.db.sql(
        """
        SELECT {dimension} AS dimension,
               COUNT(*) AS enquiries,
               SUM(IFNULL(e.quoted_total, 0)) AS quoted_total,
               SUM(CASE WHEN e.converted = 1 THEN 1 ELSE 0 END) AS converted,
               SUM(CASE WHEN st.type = 'Lost' THEN 1 ELSE 0 END) AS lost,
               SUM(IFNULL(b.total_amount, 0)) AS booked_value,
               SUM(IFNULL(b.advance_received, 0)) AS advance
        FROM `tabHotel Enquiry` e
        LEFT JOIN `tabHotel Enquiry Status` st ON st.name = e.status
        LEFT JOIN `tabHotel Booking` b ON b.name = e.hotel_booking
        WHERE {conditions}
        GROUP BY dimension
        ORDER BY enquiries DESC
        """.format(dimension=dimension, conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )

    for row in rows:
        row["conversion_pct"] = (
            flt(row.converted) / flt(row.enquiries) * 100.0 if row.enquiries else 0.0
        )
    return rows
