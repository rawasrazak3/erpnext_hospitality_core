frappe.pages['tape-chart'].on_page_load = function(wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Tape Chart (Reservation Calendar)',
        single_column: true
    });

    // Filters
    page.add_field({
        fieldname: 'start_date',
        label: 'Start Date',
        fieldtype: 'Date',
        default: frappe.datetime.now_date(),
        change: function() {
            render_tape_chart(wrapper, page);
        }
    });

    $(wrapper).find('.layout-main-section').append('<div id="tape-chart-container" style="overflow-x: auto; margin-top: 20px;"></div>');
    
    render_tape_chart(wrapper, page);
}

function render_tape_chart(wrapper, page) {
    let start_date = page.fields_dict.start_date.get_value();
    let end_date = frappe.datetime.add_days(start_date, 14); // 2 week view

    frappe.call({
        method: "hospitality_core.hospitality_core.page.tape_chart.tape_chart.get_chart_data",
        args: {
            start_date: start_date,
            end_date: end_date
        },
        callback: function(r) {
            if(r.message) {
                draw_grid(r.message, start_date, end_date);
            }
        }
    });
}

function draw_grid(data, start, end) {
    let rooms = data.rooms;
    let bookings = data.bookings;
    let container = $('#tape-chart-container');
    container.empty();

    // Simple Table Construction
    let html = `<table class="table table-bordered table-sm" style="font-size: 11px;">
        <thead><tr><th style="width: 80px;">Room</th>`;
    
    // Header Dates
    let dates = [];
    let curr = start;
    while(curr <= end) {
        dates.push(curr);
        html += `<th style="min-width: 40px; text-align: center;">${curr.split('-')[2]}</th>`;
        curr = frappe.datetime.add_days(curr, 1);
    }
    html += `</tr></thead><tbody>`;

    // Room Rows
    rooms.forEach(room => {
        // Capacity and amenities in the row header, so the chart answers "which unit
        // sleeps six and has a pool" at a glance.
        const amen = (room.amenities || []).map(a => a.icon).join(' ');
        const meta = [
            room.bedroom_configuration || '',
            room.max_occupancy ? __('Max {0}', [room.max_occupancy]) : ''
        ].filter(Boolean).join(' · ');
        const blocked = ['Maintenance', 'Out of Order'].includes(room.status);

        html += `<tr><td${blocked ? ' style="background:#f8fafc"' : ''}>
            <b>${frappe.utils.escape_html(room.room_number)}</b>
            ${blocked ? `<br><small style="color:#b45309">${room.status}</small>` : ''}
            <br><small>${frappe.utils.escape_html(room.room_type || '')}</small>
            ${meta ? `<br><small style="color:#94a3b8">${meta}</small>` : ''}
            ${amen ? `<br><small title="${__('Amenities')}">${amen}</small>` : ''}
        </td>`;
        
        dates.forEach(date => {
            // Find booking for this room on this date
            let booking = bookings.find(b => 
                b.room === room.name && 
                date >= b.arrival_date && 
                date < b.departure_date // Standard Hotel Logic: Departure day is free
            );

            if (booking) {
                let color = booking.status === 'Checked In' ? '#d4edda' : '#fff3cd'; // Green vs Yellow
                html += `<td style="background-color: ${color}; text-align: center; vertical-align: middle; cursor: pointer;" 
                            title="${booking.guest} (${booking.status})"
                            onclick="frappe.set_route('Form', 'Hotel Reservation', '${booking.name}')">
                            ${booking.name.split('-').pop()}
                         </td>`;
            } else {
                html += `<td></td>`;
            }
        });
        html += `</tr>`;
    });

    html += `</tbody></table>`;
    container.html(html);
}