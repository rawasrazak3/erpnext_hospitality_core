// Copyright (c) 2026, FRC Consulting and contributors
// For license information, please see license.txt

frappe.query_reports["Enquiry Conversion"] = {
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
			fieldname: "group_by",
			label: __("Group By"),
			fieldtype: "Select",
			options: ["Source", "Owner", "Status"],
			default: "Source",
			reqd: 1,
		},
		{
			fieldname: "source",
			label: __("Source"),
			fieldtype: "Link",
			options: "Hotel Enquiry Source",
		},
		{
			fieldname: "enquiry_owner",
			label: __("Agent"),
			fieldtype: "Link",
			options: "User",
		},
	],
};
