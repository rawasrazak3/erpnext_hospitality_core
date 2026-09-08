// Copyright (c) 2026, FRC Consulting and contributors
// For license information, please see license.txt

frappe.query_reports["Advance Collection"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "hotel_reception",
			label: __("Property"),
			fieldtype: "Link",
			options: "Hotel Reception",
		},
		{
			fieldname: "mode_of_payment",
			label: __("Mode of Payment"),
			fieldtype: "Link",
			options: "Mode of Payment",
		},
		{
			fieldname: "cashier",
			label: __("Received By"),
			fieldtype: "Link",
			options: "User",
		},
	],
};
