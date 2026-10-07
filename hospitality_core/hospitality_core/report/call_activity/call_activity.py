# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""Per-agent, per-line call funnel: calls handled, enquiries raised, bookings won.

Reads CRM Call Log, which the Android handsets feed through crm_mobile_sync. Talk time
counts only connected calls, so a run of unanswered dials does not read as activity.

A row is one agent on one line, not one agent, because an agent working two SIMs is two
different stories: the reception number ringing out while the sales number connects is
invisible once the two are added together. An agent on a single handset still produces
a single row.
"""

import frappe
from frappe import _

from hospitality_core.hospitality_core.api.telephony import handset_sql


def execute(filters=None):
    filters = filters or {}
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Agent"), "fieldname": "agent", "fieldtype": "Data", "width": 180},
        {"label": _("Line (Handset)"), "fieldname": "handset", "fieldtype": "Data", "width": 150},
        {"label": _("Handset"), "fieldname": "device_label", "fieldtype": "Data", "width": 150},
        {"label": _("Total Calls"), "fieldname": "total_calls", "fieldtype": "Int", "width": 100},
        {"label": _("Incoming"), "fieldname": "incoming", "fieldtype": "Int", "width": 90},
        {"label": _("Outgoing"), "fieldname": "outgoing", "fieldtype": "Int", "width": 90},
        {"label": _("Connected"), "fieldname": "connected", "fieldtype": "Int", "width": 100},
        {"label": _("Missed / No Answer"), "fieldname": "missed", "fieldtype": "Int", "width": 150},
        {"label": _("Missed %"), "fieldname": "missed_pct", "fieldtype": "Percent", "width": 100},
        {"label": _("Talk Time (min)"), "fieldname": "talk_minutes", "fieldtype": "Float",
         "precision": 1, "width": 130},
        {"label": _("Enquiries Touched"), "fieldname": "enquiries", "fieldtype": "Int", "width": 150},
        {"label": _("Unlinked Calls"), "fieldname": "unlinked", "fieldtype": "Int", "width": 130},
    ]


def _as_list(value):
    """MultiSelectList hands back a list; a Data filter or a URL hands back a string."""
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",")]
    return [part for part in (value or []) if part]


def get_data(filters):
    if not frappe.db.exists("DocType", "CRM Call Log"):
        return []

    meta = frappe.get_meta("CRM Call Log")
    # Fall back to the caller/receiver when the mobile-sync agent field is absent.
    agent_expr = ("IFNULL(cl.custom_agent, IFNULL(cl.caller, cl.receiver))"
                  if meta.has_field("custom_agent")
                  else "IFNULL(cl.caller, cl.receiver)")
    enquiry_expr = "cl.custom_hotel_enquiry" if meta.has_field("custom_hotel_enquiry") else "NULL"
    device_join, handset_expr, label_expr = handset_sql()

    conditions = ["DATE(cl.start_time) BETWEEN %(from_date)s AND %(to_date)s"]
    params = {"from_date": filters.get("from_date"), "to_date": filters.get("to_date")}

    if filters.get("agent") and meta.has_field("custom_agent"):
        conditions.append("cl.custom_agent = %(agent)s")
        params["agent"] = filters.get("agent")

    handsets = _as_list(filters.get("handset"))
    if handsets:
        conditions.append(f"{handset_expr} IN %(handsets)s")
        params["handsets"] = handsets

    rows = frappe.db.sql(
        """
        SELECT IFNULL({agent_expr}, 'Unattributed') AS agent,
               {handset_expr} AS handset,
               MAX({label_expr}) AS device_label,
               COUNT(*) AS total_calls,
               SUM(CASE WHEN cl.type = 'Incoming' THEN 1 ELSE 0 END) AS incoming,
               SUM(CASE WHEN cl.type = 'Outgoing' THEN 1 ELSE 0 END) AS outgoing,
               SUM(CASE WHEN cl.status = 'Completed' THEN 1 ELSE 0 END) AS connected,
               SUM(CASE WHEN cl.status != 'Completed' THEN 1 ELSE 0 END) AS missed,
               ROUND(100.0 * SUM(CASE WHEN cl.status != 'Completed' THEN 1 ELSE 0 END)
                     / COUNT(*), 1) AS missed_pct,
               ROUND(SUM(CASE WHEN cl.status = 'Completed'
                              THEN IFNULL(cl.duration, 0) ELSE 0 END) / 60.0, 1) AS talk_minutes,
               COUNT(DISTINCT {enquiry_expr}) AS enquiries,
               SUM(CASE WHEN IFNULL({enquiry_expr}, '') = '' THEN 1 ELSE 0 END) AS unlinked
        FROM `tabCRM Call Log` cl
        {device_join}
        WHERE {conditions}
        GROUP BY agent, handset
        ORDER BY total_calls DESC
        """.format(
            agent_expr=agent_expr,
            handset_expr=handset_expr,
            label_expr=label_expr,
            enquiry_expr=enquiry_expr,
            device_join=device_join,
            conditions=" AND ".join(conditions),
        ),
        params,
        as_dict=True,
    )

    # MySQL SUM() hands back Decimal, which renders as "12.0" in an Int column.
    for row in rows:
        for field in ("total_calls", "incoming", "outgoing", "connected", "missed",
                      "enquiries", "unlinked"):
            row[field] = int(row.get(field) or 0)

    return rows
