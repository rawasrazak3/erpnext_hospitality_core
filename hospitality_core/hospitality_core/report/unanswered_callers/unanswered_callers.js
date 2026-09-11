// Copyright (c) 2026, FRC Consulting and contributors
// For license information, please see license.txt

frappe.query_reports["Unanswered Callers"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			// The point of the report: "nobody has called them back in N days".
			fieldname: "min_days_waiting",
			label: __("Waiting At Least (days)"),
			fieldtype: "Int",
			default: 1,
		},
		{
			fieldname: "min_attempts",
			label: __("Min Attempts"),
			fieldtype: "Int",
			default: 1,
		},
		{
			fieldname: "agent",
			label: __("Agent"),
			fieldtype: "Link",
			options: "User",
		},
		{
			fieldname: "hide_with_enquiry",
			label: __("Hide callers who already have an enquiry"),
			fieldtype: "Check",
			default: 0,
		},
	],

	// The longer someone has waited the louder the row, so a manager scanning the report
	// sees the worst cases without reading the numbers.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "days_waiting" && data) {
			const d = Number(data.days_waiting) || 0;
			if (d >= 7) value = `<span style="color:var(--red-500,#e24c4c);font-weight:600">${value}</span>`;
			else if (d >= 3) value = `<span style="color:var(--orange-500,#f59e0b);font-weight:600">${value}</span>`;
		}
		if (column.fieldname === "attempts" && data && Number(data.attempts) >= 3) {
			value = `<span style="font-weight:600">${value}</span>`;
		}
		return value;
	},
};
