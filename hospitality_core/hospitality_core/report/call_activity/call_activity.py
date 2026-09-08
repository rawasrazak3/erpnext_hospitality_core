# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""Per-agent call funnel: calls handled, enquiries raised, bookings won.

Reads CRM Call Log, which the Android handsets feed through crm_mobile_sync. Talk time
counts only connected calls, so a run of unanswered dials does not read as activity.
"""

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Agent"), "fieldname": "agent", "fieldtype": "Data", "width": 200},
        {"label": _("Total Calls"), "fieldname": "total_calls", "fieldtype": "Int", "width": 100},
        {"label": _("Incoming"), "fieldname": "incoming", "fieldtype": "Int", "width": 90},
        {"label": _("Outgoing"), "fieldname": "outgoing", "fieldtype": "Int", "width": 90},
        {"label": _("Connected"), "fieldname": "connected", "fieldtype": "Int", "width": 100},
        {"label": _("Missed / No Answer"), "fieldname": "missed", "fieldtype": "Int", "width": 150},
        {"label": _("Talk Time (min)"), "fieldname": "talk_minutes", "fieldtype": "Float",
         "precision": 1, "width": 130},
        {"label": _("Enquiries Touched"), "fieldname": "enquiries", "fieldtype": "Int", "width": 150},
        {"label": _("Unlinked Calls"), "fieldname": "unlinked", "fieldtype": "Int", "width": 130},
    ]


def get_data(filters):
    if not frappe.db.exists("DocType", "CRM Call Log"):
        return []

    meta = frappe.get_meta("CRM Call Log")
    # Fall back to the caller/receiver when the mobile-sync agent field is absent.
    agent_expr = ("IFNULL(cl.custom_agent, IFNULL(cl.caller, cl.receiver))"
                  if meta.has_field("custom_agent")
                  else "IFNULL(cl.caller, cl.receiver)")
    enquiry_expr = "cl.custom_hotel_enquiry" if meta.has_field("custom_hotel_enquiry") else "NULL"

    conditions = ["DATE(cl.start_time) BETWEEN %(from_date)s AND %(to_date)s"]
    params = {"from_date": filters.get("from_date"), "to_date": filters.get("to_date")}

    if filters.get("agent") and meta.has_field("custom_agent"):
        conditions.append("cl.custom_agent = %(agent)s")
        params["agent"] = filters.get("agent")

    return frappe.db.sql(
        """
        SELECT IFNULL({agent_expr}, 'Unattributed') AS agent,
               COUNT(*) AS total_calls,
               SUM(CASE WHEN cl.type = 'Incoming' THEN 1 ELSE 0 END) AS incoming,
               SUM(CASE WHEN cl.type = 'Outgoing' THEN 1 ELSE 0 END) AS outgoing,
               SUM(CASE WHEN cl.status = 'Completed' THEN 1 ELSE 0 END) AS connected,
               SUM(CASE WHEN cl.status != 'Completed' THEN 1 ELSE 0 END) AS missed,
               ROUND(SUM(CASE WHEN cl.status = 'Completed'
                              THEN IFNULL(cl.duration, 0) ELSE 0 END) / 60.0, 1) AS talk_minutes,
               COUNT(DISTINCT {enquiry_expr}) AS enquiries,
               SUM(CASE WHEN IFNULL({enquiry_expr}, '') = '' THEN 1 ELSE 0 END) AS unlinked
        FROM `tabCRM Call Log` cl
        WHERE {conditions}
        GROUP BY agent
        ORDER BY total_calls DESC
        """.format(
            agent_expr=agent_expr,
            enquiry_expr=enquiry_expr,
            conditions=" AND ".join(conditions),
        ),
        params,
        as_dict=True,
    )
