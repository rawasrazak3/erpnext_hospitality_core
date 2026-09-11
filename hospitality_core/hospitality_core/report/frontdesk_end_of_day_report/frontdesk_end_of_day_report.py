# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt

from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import BLOCKED_STATUSES

def execute(filters=None):
	columns = get_columns()
	data = get_data(filters)
	return columns, data

def get_columns():
	return [
		{
			"fieldname": "metric",
			"label": _("Metric"),
			"fieldtype": "Data",
			"width": 200
		},
		{
			"fieldname": "value",
			"label": _("Value"),
			"fieldtype": "Data",
			"width": 150
		},
		{
			"fieldname": "description",
			"label": _("Description"),
			"fieldtype": "Data",
			"width": 300
		}
	]

def get_data(filters):
	if not filters or not filters.get("date"):
		return []

	report_date = filters.get("date")
	reception = filters.get("hotel_reception")  # Can be None for all receptions

	data = []

	# 1. New Check-ins
	check_in_filters = {
		"arrival_date": report_date,
		"status": ["in", ["Checked In", "Checked Out"]]
	}
	if reception:
		check_in_filters["hotel_reception"] = reception
	check_ins = frappe.db.count("Hotel Reservation", check_in_filters)
	
	# Refine Check-in query: Actually status could be 'Checked In' or 'Checked Out' if they left same day, 
	# but primarily we want to know how many ARRIVED this day.
	# Let's trust 'arrival_date' and status != Cancelled/Reserved?
	# "Reserved" implies they haven't arrived yet (no show or future).
	# So status in Checked In, Checked Out.
	
	data.append({
		"metric": "New Check-ins",
		"value": check_ins,
		"description": "Number of guests who arrived and checked in on this date."
	})

	# 2. Retained (Stay-overs)
	# Guests who arrived BEFORE today and depart AFTER today.
	if reception:
		retained = frappe.db.sql("""
			SELECT count(name) FROM `tabHotel Reservation`
			WHERE
				CAST(CONCAT(arrival_date, ' ', IFNULL(NULLIF(arrival_time, ''), '14:00:00')) AS DATETIME) < %s
				AND CAST(CONCAT(departure_date, ' ', IFNULL(NULLIF(departure_time, ''), '12:00:00')) AS DATETIME) > %s
				AND hotel_reception = %s
				AND status IN ('Checked In', 'Checked Out')
		""", (f"{report_date} 14:00:00", f"{report_date} 14:00:00", reception))[0][0]
	else:
		retained = frappe.db.sql("""
			SELECT count(name) FROM `tabHotel Reservation`
			WHERE
				CAST(CONCAT(arrival_date, ' ', IFNULL(NULLIF(arrival_time, ''), '14:00:00')) AS DATETIME) < %s
				AND CAST(CONCAT(departure_date, ' ', IFNULL(NULLIF(departure_time, ''), '12:00:00')) AS DATETIME) > %s
				AND status IN ('Checked In', 'Checked Out')
		""", (f"{report_date} 14:00:00", f"{report_date} 14:00:00"))[0][0]

	data.append({
		"metric": "Retained Guests",
		"value": retained,
		"description": "Guests currently in-house (arrived before today, leaving after today)."
	})

	# 3. Departures (Check-outs)
	departure_filters = {
		"departure_date": report_date,
		"status": "Checked Out"
	}
	if reception:
		departure_filters["hotel_reception"] = reception
	top_departures = frappe.db.count("Hotel Reservation", departure_filters)

	data.append({
		"metric": "Departures",
		"value": top_departures,
		"description": "Number of guests who checked out on this date."
	})

	# 4. Sales Consumption
	# Sum of Folio Transactions posted on this date, linked to guests in this reception.
	if reception:
		sales_consumption = frappe.db.sql("""
			SELECT SUM(ft.amount)
			FROM `tabFolio Transaction` ft
			JOIN `tabGuest Folio` gf ON ft.parent = gf.name
			WHERE
				ft.posting_date = %s
				AND gf.hotel_reception = %s
				AND ft.is_void = 0
				AND gf.docstatus < 2
				AND (ft.reference_doctype != 'Payment Entry' OR ft.reference_doctype IS NULL)
				AND IFNULL(ft.item, '') NOT IN ('PAYMENT','REFUND','TRANSFER','TRANSFER-GROUP','REFUND-TRANSFER','BALANCE-TRANSFER','ADVANCE-TRANSFER')
		""", (report_date, reception))[0][0] or 0.0
	else:
		sales_consumption = frappe.db.sql("""
			SELECT SUM(ft.amount)
			FROM `tabFolio Transaction` ft
			JOIN `tabGuest Folio` gf ON ft.parent = gf.name
			WHERE
				ft.posting_date = %s
				AND ft.is_void = 0
				AND gf.docstatus < 2
				AND (ft.reference_doctype != 'Payment Entry' OR ft.reference_doctype IS NULL)
				AND IFNULL(ft.item, '') NOT IN ('PAYMENT','REFUND','TRANSFER','TRANSFER-GROUP','REFUND-TRANSFER','BALANCE-TRANSFER','ADVANCE-TRANSFER')
		""", (report_date,))[0][0] or 0.0

	data.append({
		"metric": "Sales Consumption (Gross)",
		"value": frappe.format_value(sales_consumption, currency=frappe.get_cached_value('Company',  frappe.defaults.get_user_default("Company"),  "default_currency")),
		"description": "Total value of services/goods consumed (Inclusive of Taxes)."
	})

	# Breakdown for Sales Consumption
	from hospitality_core.hospitality_core.api.accounting import get_tax_breakdown
	sales_taxes = get_tax_breakdown(sales_consumption)
	company_currency = frappe.get_cached_value('Company', frappe.defaults.get_user_default("Company"), "default_currency")

	data.append({
		"metric": "  - Net Sales",
		"value": frappe.format_value(sales_taxes["net_amount"], currency=company_currency),
		"description": "Base revenue before taxes."
	})
	half_rate = flt(sales_taxes["gst_rate"]) / 2
	data.append({
		"metric": f"  - CGST ({half_rate:g}%)",
		"value": frappe.format_value(sales_taxes["cgst_amount"], currency=company_currency),
		"description": "Central GST component of the gross amount."
	})
	data.append({
		"metric": f"  - SGST ({half_rate:g}%)",
		"value": frappe.format_value(sales_taxes["sgst_amount"], currency=company_currency),
		"description": "State GST component of the gross amount."
	})
	data.append({
		"metric": "  - Total Tax",
		"value": frappe.format_value(sales_taxes["total_tax"], currency=company_currency),
		"description": "CGST + SGST."
	})

	# 5. Payment
	# Front-desk collections for this reception on this date.
	#
	# This MUST stay scoped to payments that actually hit a Guest Folio. Without the
	# `guest_folio IS NOT NULL` filter this summed every Payment Entry in the system —
	# supplier payments, POS consolidation entries and all — and reported them as
	# front-desk cash. Refunds ("Pay") are netted off rather than added.
	payment_conditions = ["pe.posting_date = %(report_date)s", "pe.docstatus = 1", "pe.guest_folio IS NOT NULL"]
	params = {"report_date": report_date}
	if reception:
		payment_conditions.append("pe.hotel_reception = %(reception)s")
		params["reception"] = reception

	# Split in-house settlement from advances taken for a FUTURE stay. Both are cash in
	# the drawer today, but only the first relates to revenue earned today — reporting
	# them as one number is what made an advance look like same-day trading.
	rows = frappe.db.sql("""
		SELECT IFNULL(gf.is_booking_master, 0) AS is_advance,
		       SUM(CASE WHEN pe.payment_type = 'Pay' THEN -pe.paid_amount ELSE pe.paid_amount END) AS amt
		FROM `tabPayment Entry` pe
		JOIN `tabGuest Folio` gf ON gf.name = pe.guest_folio
		WHERE {conditions}
		GROUP BY IFNULL(gf.is_booking_master, 0)
	""".format(conditions=" AND ".join(payment_conditions)), params, as_dict=True)

	in_house = sum(flt(r.amt) for r in rows if not r.is_advance)
	advances = sum(flt(r.amt) for r in rows if r.is_advance)
	payments = in_house + advances

	company_ccy = frappe.get_cached_value('Company', frappe.defaults.get_user_default("Company"), "default_currency")

	data.append({
		"metric": "Total Collections",
		"value": frappe.format_value(payments, currency=company_ccy),
		"description": "All cash collected at this reception today (in-house + advances)."
	})
	data.append({
		"metric": "  - In-House Settlement",
		"value": frappe.format_value(in_house, currency=company_ccy),
		"description": "Paid against a stay in progress. Relates to revenue earned."
	})
	data.append({
		"metric": "  - Advances (Future Stays)",
		"value": frappe.format_value(advances, currency=company_ccy),
		"description": "Collected today for a stay that has not happened yet. Held as a liability, NOT revenue."
	})

	# 6. Analytics
	# Occupancy = (Retained + New Check-ins) / Total Rooms in Reception
	room_filters = {
		"is_enabled": 1,
		"status": ["not in", BLOCKED_STATUSES]
	}
	if reception:
		room_filters["hotel_reception"] = reception
	total_rooms = frappe.db.count("Hotel Room", room_filters)

	occupancy_pct = 0.0
	if total_rooms > 0:
		# Occupied = Retained + Check-ins (Assuming check-ins stayed the night, which is typical for EOD report)
		occupied_rooms = retained + check_ins
		occupancy_pct = (occupied_rooms / total_rooms) * 100.0

	data.append({
		"metric": "Occupancy",
		"value": f"{occupancy_pct:.2f}%",
		"description": f"Occupancy Percentage ({retained + check_ins} occupied / {total_rooms} available rooms)."
	})

	# 7. Expenses
	if reception:
		expenses_by_cat = frappe.db.sql("""
			SELECT expense_category, SUM(grand_total) as amount
			FROM `tabHospitality Expense`
			WHERE
				expense_date = %s
				AND hotel_reception = %s
				AND docstatus = 1
			GROUP BY expense_category
		""", (report_date, reception), as_dict=1)
	else:
		expenses_by_cat = frappe.db.sql("""
			SELECT expense_category, SUM(grand_total) as amount
			FROM `tabHospitality Expense`
			WHERE
				expense_date = %s
				AND docstatus = 1
			GROUP BY expense_category
		""", (report_date,), as_dict=1)

	total_expenses = sum(e.amount for e in expenses_by_cat)
	company_currency = frappe.get_cached_value('Company', frappe.defaults.get_user_default("Company"), "default_currency")

	data.append({
		"metric": "Total Expenses",
		"value": frappe.format_value(total_expenses, currency=company_currency),
		"description": "Total expenses logged for this date (including taxes)."
	})

	for exp in expenses_by_cat:
		data.append({
			"metric": f"  - {exp.expense_category}",
			"value": frappe.format_value(exp.amount, currency=company_currency),
			"description": f"Expenses for category {exp.expense_category}"
		})

	# 8. Net Profit/Loss
	net_pl = sales_taxes["net_amount"] - total_expenses
	data.append({
		"metric": "Net Profit/Loss",
		"value": frappe.format_value(net_pl, currency=company_currency),
		"description": "Total Net Sales minus Total Expenses."
	})
	
	return data
