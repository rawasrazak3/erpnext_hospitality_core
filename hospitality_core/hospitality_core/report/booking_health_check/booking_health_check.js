// Booking Health Check — empty means every screen tells the same story.
frappe.query_reports["Booking Health Check"] = {
	filters: [],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "severity" && data) {
			const color = { High: "red", Medium: "orange", Low: "gray" }[data.severity] || "gray";
			return `<span class="indicator-pill ${color}">${value}</span>`;
		}
		return value;
	},
};
