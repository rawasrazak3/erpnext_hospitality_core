// Copyright (c) 2026, FRC Consulting and contributors
// For license information, please see license.txt

frappe.query_reports["Advance Collection Summary"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			// Month to date: the period a desk is usually asked about. Advance
			// Collection defaults to the last month because it is a listing you scroll;
			// this one answers "how are we doing this month".
			default: frappe.datetime.month_start(),
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
			options: ["Mode of Payment", "Received By", "Date", "Booking Source", "Property"],
			default: "Mode of Payment",
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

	onload(report) {
		// The grouped total is the starting point, not the destination: an odd-looking
		// figure is usually a question about one receipt, and this hands the same
		// filters to the line-by-line report rather than making someone retype them.
		report.page.add_inner_button(__("Receipt Detail"), () => {
			const f = report.get_values();
			frappe.set_route("query-report", "Advance Collection", {
				from_date: f.from_date,
				to_date: f.to_date,
				hotel_reception: f.hotel_reception,
				mode_of_payment: f.mode_of_payment,
				cashier: f.cashier,
			});
		});
	},
};
