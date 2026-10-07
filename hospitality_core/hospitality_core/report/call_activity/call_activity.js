// Copyright (c) 2026, FRC Consulting and contributors
// For license information, please see license.txt

frappe.query_reports["Call Activity"] = {
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
			fieldname: "agent",
			label: __("Agent"),
			fieldtype: "Link",
			options: "User",
		},
		{
			// Which of our lines the calls went through. Sourced from the call log
			// rather than from CRM Device so a retired handset's number still lists —
			// its old calls are still inside the reporting window.
			fieldname: "handset",
			label: __("Line / Handset Number"),
			fieldtype: "MultiSelectList",
			get_data(txt) {
				return frappe.call({
					method: "hospitality_core.hospitality_core.api.telephony.get_handset_numbers",
					args: { txt: txt },
				}).then((r) => r.message || []);
			},
		},
	],

	// A line that drops a third of what rings it is the thing worth spotting on this
	// report, so it is coloured rather than left to be read out of two Int columns.
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "missed_pct" && data) {
			const pct = Number(data.missed_pct) || 0;
			if (pct >= 50) value = `<span style="color:var(--red-500,#e24c4c);font-weight:600">${value}</span>`;
			else if (pct >= 25) value = `<span style="color:var(--orange-500,#f59e0b);font-weight:600">${value}</span>`;
		}
		return value;
	},
};
