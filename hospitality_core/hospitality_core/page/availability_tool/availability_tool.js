frappe.pages['availability-tool'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Room Availability Query',
        single_column: true
    });

    page.add_field({
        fieldname: 'date_range',
        label: 'Date Range',
        fieldtype: 'DateRange',
        default: [frappe.datetime.now_date(), frappe.datetime.add_days(frappe.datetime.now_date(), 1)],
        reqd: 1
    });

    page.set_primary_action('Check', function () {
        let dates = page.fields_dict.date_range.get_value();
        if (!dates) return;

        // DateRange field returns string "YYYY-MM-DD to YYYY-MM-DD" or array depending on version.
        // We assume Array for modern Frappe.
        let start = dates[0];
        let end = dates[1];

        frappe.call({
            method: "hospitality_core.hospitality_core.page.availability_tool.availability_tool.check_availability_counts",
            args: { start_date: start, end_date: end },
            freeze: true,
            callback: function (r) {
                render_results(wrapper, r.message);
            }
        });
    });

    $(wrapper).find('.layout-main-section').append('<div id="avail-results" style="margin-top:20px;"></div>');
}

function render_results(wrapper, data) {
    let summary_html = `<h4>Room Type Summary</h4>
        <table class="table table-bordered">
        <thead><tr style="background-color:#f0f4f7;"><th>Room Type</th><th>Total Rooms</th><th>Unavailable</th><th>Available</th></tr></thead>
        <tbody>`;

    data.summary.forEach(row => {
        let color = row.available > 0 ? 'green' : 'red';
        summary_html += `
            <tr>
                <td><b>${row.room_type}</b></td>
                <td>${row.total}</td>
                <td>${row.occupied}</td>
                <td style="color:${color}; font-weight:bold; font-size:1.2em;">${row.available}</td>
            </tr>
        `;
    });
    summary_html += `</tbody></table>`;

    let details_html = `<h4 style="margin-top:30px;">Detailed Room Status</h4>
        <table class="table table-bordered">
        <thead><tr style="background-color:#f0f4f7;"><th>Room</th><th>Type</th><th>Status</th><th>Reason/Reservation</th></tr></thead>
        <tbody>`;

    data.room_details.forEach(row => {
        let status_color = 'green';
        if (row.status === 'Occupied') status_color = '#d35400';
        if (row.status === 'Reserved') status_color = '#2980b9';
        if (row.status === 'Out of Order') status_color = '#c0392b';
        else if (row.status === 'Maintenance') status_color = '#d35400';

        details_html += `
            <tr>
                <td>${row.room}</td>
                <td>${row.room_type}</td>
                <td><span class="label" style="background-color:${status_color}; color:white; padding: 2px 8px; border-radius: 4px;">${row.status}</span></td>
                <td><small>${row.details || '-'}</small></td>
            </tr>
        `;
    });
    details_html += `</tbody></table>`;

    $('#avail-results').html(summary_html + details_html);
}