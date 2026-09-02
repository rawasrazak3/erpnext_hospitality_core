frappe.pages['front-desk-console'].on_page_load = function (wrapper) {
    var page = frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Front Desk Console',
        single_column: true
    });

    // 1. Add Date Filter
    page.add_field({
        fieldname: 'console_date',
        label: 'Date',
        fieldtype: 'Date',
        default: frappe.datetime.now_date(),
        change: function () {
            render_console(wrapper, page);
        }
    });

    // Refresh Button
    page.set_primary_action('Refresh Data', function () {
        render_console(wrapper, page);
    });

    // Inject CSS Inline to prevent asset build issues
    if(!document.getElementById('fd-styles')){
        var s = document.createElement('style');
        s.id = 'fd-styles';
        s.textContent = "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');" +
":root{--fd-primary:#6366f1;--fd-primary-dark:#4f46e5;--fd-success:#10b981;--fd-danger:#ef4444;--fd-warning:#f59e0b;--fd-bg:#f8fafc;--fd-card:#ffffff;--fd-text:#0f172a;--fd-muted:#64748b;--fd-border:#e2e8f0;--fd-radius:12px;}" +
".fd-wrapper{font-family:'Inter',sans-serif;background:var(--fd-bg);min-height:calc(100vh - 120px);padding:20px 24px;color:var(--fd-text);}" +
".fd-wrapper *{box-sizing:border-box;}" +
".fd-toolbar{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin-bottom:30px;}" +
".fd-toolbar-card{background:var(--fd-card);border:1px solid var(--fd-border);border-radius:var(--fd-radius);padding:20px 10px;text-align:center;cursor:pointer;transition:all 0.25s cubic-bezier(0.4,0,0.2,1);box-shadow:0 1px 3px rgba(0,0,0,0.04);text-decoration:none !important;display:block;}" +
".fd-toolbar-card:hover{transform:translateY(-4px);box-shadow:0 10px 25px rgba(99,102,241,0.15);border-color:var(--fd-primary);text-decoration:none;}" +
".fd-toolbar-icon{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 12px auto;font-size:20px;color:var(--fd-primary);background:#eef2ff;transition:all 0.25s;}" +
".fd-toolbar-card:hover .fd-toolbar-icon{background:var(--fd-primary);color:#ffffff;}" +
".fd-toolbar-label{font-size:13px;font-weight:600;color:var(--fd-text);}" +
".fd-stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:20px;margin-bottom:30px;}" +
".fd-stat-card{background:var(--fd-card);border:1px solid var(--fd-border);border-radius:var(--fd-radius);padding:24px;display:flex;flex-direction:column;justify-content:center;position:relative;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.04);transition:all 0.2s;}" +
".fd-stat-card:hover{box-shadow:0 8px 20px rgba(0,0,0,0.06);}" +
".fd-stat-card::before{content:'';position:absolute;top:0;left:0;width:4px;height:100%;}" +
".fd-stat-card.stat-pending::before{background:var(--fd-warning);}" +
".fd-stat-card.stat-depart::before{background:var(--fd-danger);}" +
".fd-stat-card.stat-inhouse::before{background:var(--fd-primary);}" +
".fd-stat-card.stat-avail::before{background:var(--fd-success);}" +
".fd-stat-label{font-size:12px;font-weight:700;color:var(--fd-muted);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;}" +
".fd-stat-number{font-size:36px;font-weight:800;color:var(--fd-text);line-height:1;margin-bottom:8px;}" +
".fd-stat-card.stat-pending .fd-stat-number{color:var(--fd-warning);}" +
".fd-stat-card.stat-depart .fd-stat-number{color:var(--fd-danger);}" +
".fd-stat-card.stat-inhouse .fd-stat-number{color:var(--fd-primary);}" +
".fd-stat-card.stat-avail .fd-stat-number{color:var(--fd-success);}" +
".fd-stat-sub{font-size:12px;color:var(--fd-muted);}" +
".fd-lists-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;}" +
"@media (max-width:991px){.fd-lists-grid{grid-template-columns:1fr;}}" +
".fd-list-card{background:var(--fd-card);border:1px solid var(--fd-border);border-radius:var(--fd-radius);box-shadow:0 2px 8px rgba(0,0,0,0.02);display:flex;flex-direction:column;max-height:500px;}" +
".fd-list-header{padding:16px 20px;border-bottom:1px solid var(--fd-border);font-size:15px;font-weight:700;color:var(--fd-text);display:flex;align-items:center;gap:8px;background:#fcfdfd;border-radius:var(--fd-radius) var(--fd-radius) 0 0;}" +
".fd-list-header i{font-size:16px;}" +
".hdr-arr i{color:var(--fd-primary);}" +
".hdr-dep i{color:var(--fd-danger);}" +
".fd-list-body{flex:1;overflow-y:auto;padding:0;}" +
".fd-list-item{padding:16px 20px;border-bottom:1px solid var(--fd-border);display:flex;align-items:center;justify-content:space-between;transition:background 0.15s;}" +
".fd-list-item:hover{background:#f8fafc;}" +
".fd-list-item:last-child{border-bottom:none;}" +
".fd-li-main{display:flex;flex-direction:column;gap:4px;}" +
".fd-li-name{font-size:14px;font-weight:600;color:var(--fd-text);text-decoration:none !important;}" +
".fd-li-name:hover{color:var(--fd-primary);}" +
".fd-li-meta{font-size:12px;color:var(--fd-muted);display:flex;align-items:center;gap:6px;}" +
".fd-li-meta i{font-size:11px;opacity:0.7;}" +
".fd-li-actions{display:flex;flex-direction:column;align-items:flex-end;gap:8px;}" +
".fd-badge{padding:4px 10px;border-radius:20px;font-size:11px;font-weight:600;display:inline-flex;align-items:center;gap:4px;}" +
".badge-pending{background:#fffbeb;color:#b45309;border:1px solid #fde68a;}" +
".badge-done{background:#ecfdf5;color:#047857;border:1px solid #a7f3d0;}" +
".badge-missed{background:#fef2f2;color:#b91c1c;border:1px solid #fecaca;}" +
".fd-btn{padding:6px 14px;border:none;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;transition:all 0.2s;font-family:inherit;}" +
".fd-btn-primary{background:var(--fd-primary);color:#fff;}" +
".fd-btn-primary:hover{background:var(--fd-primary-dark);box-shadow:0 2px 6px rgba(99,102,241,0.3);}" +
".fd-btn-danger{background:var(--fd-danger);color:#fff;}" +
".fd-btn-danger:hover{background:#dc2626;box-shadow:0 2px 6px rgba(239,68,68,0.3);}" +
".fd-empty-state{padding:40px 20px;text-align:center;color:var(--fd-muted);font-size:14px;}" +
".fd-empty-state i{font-size:32px;margin-bottom:12px;opacity:0.4;display:block;}";
        document.head.appendChild(s);
    }

    // Main Layout Skeleton
    $(wrapper).find('.layout-main-section').html(`
        <div class="fd-wrapper">
            <!-- Quick Actions Toolbar -->
            <div class="fd-toolbar">
                <a class="fd-toolbar-card" onclick="frappe.set_route('hotel-pos')">
                    <div class="fd-toolbar-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path></svg></div>
                    <div class="fd-toolbar-label">Hotel POS</div>
                </a>
                <a class="fd-toolbar-card" onclick="frappe.set_route('tape-chart')">
                    <div class="fd-toolbar-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg></div>
                    <div class="fd-toolbar-label">Tape Chart</div>
                </a>
                <a class="fd-toolbar-card" onclick="frappe.set_route('availability-tool')">
                    <div class="fd-toolbar-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4v16M2 8h18a2 2 0 0 1 2 2v10M2 17h20M6 8v9"></path></svg></div>
                    <div class="fd-toolbar-label">Availability</div>
                </a>
                <a class="fd-toolbar-card" onclick="frappe.set_route('List', 'Hotel Reservation')">
                    <div class="fd-toolbar-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg></div>
                    <div class="fd-toolbar-label">Reservations</div>
                </a>
                <a class="fd-toolbar-card" onclick="frappe.set_route('housekeeping-view')">
                    <div class="fd-toolbar-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path></svg></div>
                    <div class="fd-toolbar-label">Housekeeping</div>
                </a>
                <a class="fd-toolbar-card" onclick="frappe.set_route('List', 'Hotel Maintenance Request')">
                    <div class="fd-toolbar-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path></svg></div>
                    <div class="fd-toolbar-label">Maintenance</div>
                </a>
            </div>

            <!-- Stats Row -->
            <div class="fd-stats-grid">
                <div class="fd-stat-card stat-pending">
                    <div class="fd-stat-label">Arrivals Pending</div>
                    <div class="fd-stat-number" id="stat-arr-pending">0</div>
                    <div class="fd-stat-sub">For selected date</div>
                </div>
                <div class="fd-stat-card stat-depart">
                    <div class="fd-stat-label">Departures Pending</div>
                    <div class="fd-stat-number" id="stat-dep-pending">0</div>
                    <div class="fd-stat-sub">For selected date</div>
                </div>
                <div class="fd-stat-card stat-inhouse">
                    <div class="fd-stat-label">Rooms In-House</div>
                    <div class="fd-stat-number" id="stat-occupancy">0</div>
                    <div class="fd-stat-sub" id="stat-occ-pct">0% Occupancy</div>
                </div>
                <div class="fd-stat-card stat-avail">
                    <div class="fd-stat-label">Available Rooms</div>
                    <div class="fd-stat-number" id="stat-available">0</div>
                    <div class="fd-stat-sub">Net Availability</div>
                </div>
            </div>

            <!-- Lists Row -->
            <div class="fd-lists-grid">
                <!-- Arrivals Column -->
                <div class="fd-list-card">
                    <div class="fd-list-header hdr-arr">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> Arrivals
                    </div>
                    <div id="list-arrivals" class="fd-list-body">
                        <div class="fd-empty-state">Loading...</div>
                    </div>
                </div>

                <!-- Departures Column -->
                <div class="fd-list-card">
                    <div class="fd-list-header hdr-dep">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg> Departures
                    </div>
                    <div id="list-departures" class="fd-list-body">
                        <div class="fd-empty-state">Loading...</div>
                    </div>
                </div>
            </div>
        </div>
    `);

    // Hide standard page padding to let our wrapper fill the space
    $(wrapper).find('.layout-main-section').css({'padding':'0', 'background': 'var(--fd-bg)'});
    
    render_console(wrapper, page);
}

function render_console(wrapper, page) {
    let selected_date = page.fields_dict.console_date.get_value();

    frappe.call({
        method: "hospitality_core.hospitality_core.page.front_desk_console.front_desk_console.get_console_data",
        args: { target_date: selected_date },
        callback: function (r) {
            if (r.message) {
                update_stats(r.message.stats);
                render_arrivals(r.message.arrivals);
                render_departures(r.message.departures);
            }
        }
    });
}

function update_stats(stats) {
    $('#stat-arr-pending').text(stats.arrivals_pending);
    $('#stat-dep-pending').text(stats.departures_pending);
    $('#stat-occupancy').text(stats.in_house);
    $('#stat-occ-pct').text(stats.occupancy_pct + '% Occupancy');
    $('#stat-available').text(stats.available);
}

function render_arrivals(data) {
    let html = '';
    if (data.length === 0) {
        html = '<div class="fd-empty-state">No arrivals found for this date.</div>';
    } else {
        data.forEach(d => {
            let is_pending = d.status === 'Reserved';
            let is_arrived = d.status === 'Checked In' || d.status === 'Checked Out';
            let badge = '';

            if (is_arrived) {
                badge = '<span class="fd-badge badge-done"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> Arrived</span>';
            } else if (is_pending) {
                let is_past = frappe.datetime.get_diff(frappe.datetime.now_date(), d.arrival_date) > 0;
                if (is_past) badge = '<span class="fd-badge badge-missed">No Show</span>';
                else badge = '<span class="fd-badge badge-pending">Pending</span>';
            }

            html += `
            <div class="fd-list-item">
                <div class="fd-li-main">
                    <a class="fd-li-name" href="#" onclick="frappe.set_route('Form', 'Hotel Reservation', '${d.name}')">${d.guest_name}</a>
                    <div class="fd-li-meta">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 4v16M2 8h18a2 2 0 0 1 2 2v10M2 17h20M6 8v9"></path></svg> ${d.room || 'Unassigned'} &middot; ${d.room_type}${d.arrival_time ? ' &middot; ' + d.arrival_time.substring(0,5) : ''}
                    </div>
                </div>
                <div class="fd-li-actions">
                    ${badge}
                    ${d.status === 'Reserved' ? `<button class="fd-btn fd-btn-primary" onclick="frappe.set_route('Form', 'Hotel Reservation', '${d.name}')">Check-in</button>` : ''}
                </div>
            </div>`;
        });
    }
    $('#list-arrivals').html(html);
}

function render_departures(data) {
    let html = '';
    if (data.length === 0) {
        html = '<div class="fd-empty-state">No departures found for this date.</div>';
    } else {
        data.forEach(d => {
            let is_left = d.status === 'Checked Out';
            let is_pending = d.status === 'Checked In';
            let badge = '';

            if (is_left) {
                badge = '<span class="fd-badge badge-done"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> Checked Out</span>';
            } else if (is_pending) {
                let is_past = frappe.datetime.get_diff(frappe.datetime.now_date(), d.departure_date) > 0;
                if (is_past) badge = '<span class="fd-badge badge-missed">Overstay</span>';
                else badge = '<span class="fd-badge badge-pending">Expected</span>';
            }

            html += `
            <div class="fd-list-item">
                <div class="fd-li-main">
                    <a class="fd-li-name" href="#" onclick="frappe.set_route('Form', 'Hotel Reservation', '${d.name}')">${d.guest_name}</a>
                    <div class="fd-li-meta">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg> ${d.room} &middot; ${d.room_type}${d.departure_time ? ' &middot; ' + d.departure_time.substring(0,5) : ''}
                    </div>
                </div>
                <div class="fd-li-actions">
                    ${badge}
                    ${d.status === 'Checked In' ? `<button class="fd-btn fd-btn-danger" onclick="frappe.set_route('Form', 'Hotel Reservation', '${d.name}')">Checkout</button>` : ''}
                </div>
            </div>`;
        });
    }
    $('#list-departures').html(html);
}