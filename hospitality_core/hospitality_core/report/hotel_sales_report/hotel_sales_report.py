"""Hotel Sales Report: revenue, occupancy, collections by mode and advances, per day,
week or month. Uses the same figures as the Sales Dashboard
(api/sales_dashboard.get_period_rows), so the two always agree."""

import frappe
from frappe import _
from frappe.utils import add_days, getdate, nowdate

from hospitality_core.hospitality_core.api.sales_dashboard import get_period_rows


def execute(filters=None):
	filters = frappe._dict(filters or {})
	from_date = filters.get("from_date") or add_days(nowdate(), -6)
	to_date = filters.get("to_date") or nowdate()
	group_by = filters.get("group_by") or "Day"

	rows, modes = get_period_rows(from_date, to_date, group_by)

	period_label = {"Day": _("Date"), "Week": _("Week starting"), "Month": _("Month")}[group_by]
	columns = [
		{"fieldname": "period", "label": period_label, "fieldtype": "Data", "width": 150},
		{"fieldname": "nights_sold", "label": _("Room Nights"), "fieldtype": "Int", "width": 105},
		{"fieldname": "occupancy_pct", "label": _("Occupancy %"), "fieldtype": "Percent", "width": 105},
		{"fieldname": "adr", "label": _("Avg Room Rate"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "room", "label": _("Room Revenue"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "extras", "label": _("Services & Extras"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "cancellation", "label": _("Cancellation Charges"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "discounts", "label": _("Discounts"), "fieldtype": "Currency", "width": 115},
		{"fieldname": "net_revenue", "label": _("Revenue (incl. GST)"), "fieldtype": "Currency", "width": 145},
		{"fieldname": "gst", "label": _("GST included"), "fieldtype": "Currency", "width": 115},
		{"fieldname": "advances", "label": _("Advances Received"), "fieldtype": "Currency", "width": 140},
		{"fieldname": "settlements", "label": _("Bills Settled"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "refunds", "label": _("Refunds"), "fieldtype": "Currency", "width": 105},
		{"fieldname": "collections", "label": _("Net Collected"), "fieldtype": "Currency", "width": 125},
	]
	for i, mode in enumerate(modes):
		columns.append({
			"fieldname": f"mode_{i}", "label": _("{0} (net)").format(mode),
			"fieldtype": "Currency", "width": 120,
		})
	columns += [
		{"fieldname": "applied", "label": _("Advances Applied"), "fieldtype": "Currency", "width": 135},
		{"fieldname": "bookings", "label": _("Bookings Made"), "fieldtype": "Int", "width": 115},
		{"fieldname": "booking_value", "label": _("Booking Value"), "fieldtype": "Currency", "width": 125},
	]

	def label(key):
		if group_by == "Week":
			return _("Week of {0}").format(frappe.format(key, "Date"))
		if group_by == "Month":
			return getdate(key).strftime("%b %Y")
		return frappe.format(key, "Date")

	data = []
	for r in rows:
		row = {k: v for k, v in r.items() if k != "modes"}
		row["period"] = label(r["period"])
		for i, mode in enumerate(modes):
			row[f"mode_{i}"] = r["modes"].get(mode, 0.0)
		data.append(row)

	# Occupancy and average rate do not add up across rows; recompute them for the
	# total row from the summed parts instead of summing percentages.
	if data:
		nights = sum(r["nights_sold"] for r in rows)
		capacity = sum(r["capacity"] for r in rows)
		charged = sum(r["nights_charged"] for r in rows)
		room = sum(r["room"] for r in rows)
		total = {"period": _("Total"), "bold": 1}
		for key in ("nights_sold", "room", "extras", "cancellation", "discounts", "net_revenue", "gst",
		            "advances", "settlements", "refunds", "collections", "applied", "bookings", "booking_value"):
			total[key] = sum(r[key] for r in data)
		for i in range(len(modes)):
			total[f"mode_{i}"] = sum(r[f"mode_{i}"] for r in data)
		total["occupancy_pct"] = round(nights / capacity * 100, 1) if capacity else 0
		total["adr"] = round(room / charged, 2) if charged else 0
		data.append(total)

		summary = [
			{"label": _("Revenue (incl. GST)"), "value": sum(r["net_revenue"] for r in rows),
			 "datatype": "Currency", "indicator": "Blue"},
			{"label": _("Net Collected"), "value": sum(r["collections"] for r in rows),
			 "datatype": "Currency", "indicator": "Orange"},
			{"label": _("Advances Received"), "value": sum(r["advances"] for r in rows),
			 "datatype": "Currency", "indicator": "Gray"},
			{"label": _("Occupancy"), "value": round(nights / capacity * 100, 1) if capacity else 0,
			 "datatype": "Percent", "indicator": "Green"},
			{"label": _("Average Room Rate"), "value": round(room / charged, 2) if charged else 0,
			 "datatype": "Currency", "indicator": "Gray"},
		]
	else:
		total = {"period": _("Total"), "bold": 1}
		for key in ("nights_sold", "room", "extras", "cancellation", "discounts", "net_revenue", "gst",
		            "advances", "settlements", "refunds", "collections", "applied", "bookings", "booking_value"):
			total[key] = sum(r[key] for r in data)
		for i in range(len(modes)):
			total[f"mode_{i}"] = sum(r[f"mode_{i}"] for r in data)
		total["occupancy_pct"] = round(nights / capacity * 100, 1) if capacity else 0
		total["adr"] = round(room / charged, 2) if charged else 0
		data.append(total)

		summary = []

	return columns, data, None, None, summary
