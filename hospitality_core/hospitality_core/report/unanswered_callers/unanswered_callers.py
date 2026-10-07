# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""Callers nobody got back to.

One row per phone number rather than per call, because the question a manager is asking
is "who tried to reach us and never heard back", not "list every missed call". A guest
who rang four times is one problem to solve, not four rows to read past.

A number is dropped from the report as soon as any call to or from it connects, or an
enquiry exists for it — either means somebody dealt with the person, whatever the
individual call records look like.

The Line and Handset columns say which of our numbers the caller reached, so a manager
can see that the reception SIM is swallowing calls while the sales SIM is not.
"""

import frappe
from frappe import _
from frappe.utils import cint

from hospitality_core.hospitality_core.api.telephony import UNANSWERED_STATUSES, handset_sql

# Shared with the Call History console, so the two never disagree on what went unanswered.
UNANSWERED = UNANSWERED_STATUSES


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Number"), "fieldname": "number", "fieldtype": "Data", "width": 150},
		{"label": _("Caller"), "fieldname": "caller_name", "fieldtype": "Data", "width": 170},
		{"label": _("Attempts"), "fieldname": "attempts", "fieldtype": "Int", "width": 90},
		{"label": _("First Tried"), "fieldname": "first_try", "fieldtype": "Datetime", "width": 155},
		{"label": _("Last Tried"), "fieldname": "last_try", "fieldtype": "Datetime", "width": 155},
		{"label": _("Days Waiting"), "fieldname": "days_waiting", "fieldtype": "Int", "width": 115},
		{"label": _("Incoming"), "fieldname": "incoming", "fieldtype": "Int", "width": 95},
		{"label": _("Outgoing"), "fieldname": "outgoing", "fieldtype": "Int", "width": 95},
		# Which of our numbers they last reached, and how many of our numbers they had
		# to try — a caller who worked through three lines and got none of them is a
		# different problem from one who rang the same dead line three times.
		{"label": _("Line (Handset)"), "fieldname": "handset", "fieldtype": "Data", "width": 150},
		{"label": _("Handset"), "fieldname": "device_label", "fieldtype": "Data", "width": 150},
		{"label": _("Lines Tried"), "fieldname": "lines_tried", "fieldtype": "Int", "width": 105},
		{"label": _("Last Agent"), "fieldname": "agent", "fieldtype": "Data", "width": 180},
		{"label": _("Enquiry"), "fieldname": "enquiry", "fieldtype": "Link",
		 "options": "Hotel Enquiry", "width": 140},
		{"label": _("Last Call"), "fieldname": "call_log", "fieldtype": "Link",
		 "options": "CRM Call Log", "width": 130},
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
	has_key = meta.has_field("custom_number_key")
	has_agent = meta.has_field("custom_agent")
	has_enquiry = meta.has_field("custom_hotel_enquiry")
	has_contact = meta.has_field("custom_contact_name")

	# The indexed digits-only column when the telephony bridge has populated it; the raw
	# number otherwise, so the report still works on a site that predates the backfill.
	number_expr = "cl.custom_number_key" if has_key else "IFNULL(cl.`from`, cl.`to`)"
	agent_expr = "cl.custom_agent" if has_agent else "NULL"
	enquiry_expr = "cl.custom_hotel_enquiry" if has_enquiry else "NULL"
	contact_expr = "cl.custom_contact_name" if has_contact else "NULL"
	device_join, handset_expr, label_expr = handset_sql()

	conditions = [f"IFNULL({number_expr}, '') != ''"]
	values = {"unanswered": UNANSWERED}

	if filters.get("from_date"):
		conditions.append("cl.start_time >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conditions.append("cl.start_time <= %(to_date)s")
		values["to_date"] = f"{filters.to_date} 23:59:59"

	# The agent and handset filters deliberately do NOT narrow the WHERE clause. This
	# report only shows a caller when *nothing* connected, and a call answered by
	# another agent, or on another line, still means the person was dealt with. Scoping
	# the scan would hide that connect and report the caller as ignored. So the whole
	# number's history is still read, and the filter is applied as "at least one missed
	# attempt was on this agent / this line".
	extra_selects = []
	having = ["had_miss = 1", "connected = 0"]

	if filters.get("agent") and has_agent:
		extra_selects.append(
			"SUM(CASE WHEN cl.status IN %(unanswered)s "
			"AND cl.custom_agent = %(agent)s THEN 1 ELSE 0 END) AS on_agent"
		)
		having.append("on_agent > 0")
		values["agent"] = filters.agent

	handsets = _as_list(filters.get("handset"))
	if handsets:
		extra_selects.append(
			f"SUM(CASE WHEN cl.status IN %(unanswered)s "
			f"AND {handset_expr} IN %(handsets)s THEN 1 ELSE 0 END) AS on_handset"
		)
		having.append("on_handset > 0")
		values["handsets"] = handsets

	extra_select_sql = ("," + ",\n            ".join(extra_selects)) if extra_selects else ""

	rows = frappe.db.sql(
		f"""
        SELECT
            {number_expr} AS number,
            MAX(CASE WHEN cl.status IN %(unanswered)s THEN 1 ELSE 0 END) AS had_miss,
            SUM(CASE WHEN cl.status IN %(unanswered)s THEN 1 ELSE 0 END) AS attempts,
            SUM(CASE WHEN cl.status NOT IN %(unanswered)s THEN 1 ELSE 0 END) AS connected,
            SUM(CASE WHEN cl.status IN %(unanswered)s AND cl.type = 'Incoming' THEN 1 ELSE 0 END) AS incoming,
            SUM(CASE WHEN cl.status IN %(unanswered)s AND cl.type = 'Outgoing' THEN 1 ELSE 0 END) AS outgoing,
            MIN(cl.start_time) AS first_try,
            MAX(cl.start_time) AS last_try,
            DATEDIFF(NOW(), MAX(cl.start_time)) AS days_waiting,
            MAX({contact_expr}) AS caller_name,
            MAX({agent_expr}) AS agent,
            MAX({enquiry_expr}) AS enquiry,
            COUNT(DISTINCT {handset_expr}) AS lines_tried,
            SUBSTRING_INDEX(GROUP_CONCAT({handset_expr} ORDER BY cl.start_time DESC), ',', 1) AS handset,
            SUBSTRING_INDEX(GROUP_CONCAT({label_expr} ORDER BY cl.start_time DESC), ',', 1) AS device_label,
            SUBSTRING_INDEX(GROUP_CONCAT(cl.name ORDER BY cl.start_time DESC), ',', 1) AS call_log
            {extra_select_sql}
        FROM `tabCRM Call Log` cl
        {device_join}
        WHERE {" AND ".join(conditions)}
        GROUP BY {number_expr}
        HAVING {" AND ".join(having)}
        ORDER BY days_waiting DESC, attempts DESC
        """,
		values,
		as_dict=True,
	)

	min_days = cint(filters.get("min_days_waiting"))
	min_attempts = cint(filters.get("min_attempts"))
	hide_with_enquiry = cint(filters.get("hide_with_enquiry"))

	out = []
	for row in rows:
		if min_days and cint(row.days_waiting) < min_days:
			continue
		if min_attempts and cint(row.attempts) < min_attempts:
			continue
		# An enquiry means the person is already in the pipeline: the call was not
		# returned, but they are not forgotten. Off by default, since a stale enquiry
		# with no callback is still worth chasing.
		if hide_with_enquiry and row.enquiry:
			continue
		# MySQL SUM()/DATEDIFF hand back Decimal, which renders as "2.0" in an Int
		# column. Cast so the counts read as counts.
		for field in ("attempts", "connected", "incoming", "outgoing", "days_waiting",
		              "lines_tried"):
			row[field] = cint(row.get(field))
		out.append(row)

	return out
