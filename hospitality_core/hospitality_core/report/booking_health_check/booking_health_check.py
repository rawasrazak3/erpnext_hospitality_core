"""Booking Health Check: anything where bookings, stays, rooms, bills and enquiries
disagree (see api/integrity.py). Empty is healthy."""

import frappe
from frappe import _

from hospitality_core.hospitality_core.api.integrity import find_problems

ORDER = {"High": 0, "Medium": 1, "Low": 2}


def execute(filters=None):
	columns = [
		{"fieldname": "severity", "label": _("Severity"), "fieldtype": "Data", "width": 90},
		{"fieldname": "rule", "label": _("Problem"), "fieldtype": "Data", "width": 260},
		{"fieldname": "document", "label": _("Record"), "fieldtype": "Dynamic Link", "options": "doctype", "width": 150},
		{"fieldname": "doctype", "label": _("Type"), "fieldtype": "Data", "width": 130, "hidden": 1},
		{"fieldname": "message", "label": _("Details"), "fieldtype": "Data", "width": 560},
	]
	rows = []
	for p in sorted(find_problems(), key=lambda p: (ORDER.get(p["severity"], 9), p["rule"])):
		doc = p["document"]
		doctype = ("Hotel Booking" if doc.startswith("HB-") else "Hotel Reservation" if doc.startswith("HR-")
		           else "Hotel Room")
		rows.append(dict(p, doctype=doctype))
	message = None if rows else _("No problems found: bookings, stays, rooms, bills and enquiries all agree.")
	return columns, rows, message
