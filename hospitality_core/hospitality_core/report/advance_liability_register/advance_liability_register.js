// Copyright (c) 2026, FRC Consulting and contributors
// For license information, please see license.txt

frappe.query_reports["Advance Liability Register"] = {
	filters: [
		{
			fieldname: "hotel_reception",
			label: __("Property"),
			fieldtype: "Link",
			options: "Hotel Reception",
		},
	],
};
