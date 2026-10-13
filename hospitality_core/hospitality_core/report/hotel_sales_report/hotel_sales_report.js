// Hotel Sales Report — the table behind the Sales Dashboard, per day, week or month.
frappe.query_reports["Hotel Sales Report"] = {
	filters: [
		{
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
			default: frappe.datetime.add_days(frappe.datetime.get_today(), -6),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("To"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "group_by",
			label: __("Show by"),
			fieldtype: "Select",
			options: "Day\nWeek\nMonth",
			default: "Day",
		},
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		return data && data.bold ? `<b>${value}</b>` : value;
	},
	onload(report) {
		report.page.add_inner_button(__("Sales Dashboard"), () => {
			frappe.route_options = {
				from_date: report.get_filter_value("from_date"),
				to_date: report.get_filter_value("to_date"),
			};
			frappe.set_route("sales-dashboard");
		});
	},
};
