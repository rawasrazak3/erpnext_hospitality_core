frappe.pages['hotel-pos'].on_page_load = function(wrapper) {
    frappe.ui.make_app_page({ parent: wrapper, title: 'Hotel POS', single_column: true });

    // Inline CSS
    if(!document.getElementById('hpos-styles')){
        var s = document.createElement('style');
        s.id = 'hpos-styles';
        s.textContent = "@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');" +
":root{--pos-primary:#6366f1;--pos-primary-dark:#4f46e5;--pos-success:#10b981;--pos-danger:#ef4444;--pos-warning:#f59e0b;--pos-bg:#f1f5f9;--pos-card:#fff;--pos-text:#0f172a;--pos-muted:#64748b;--pos-border:#e2e8f0;--pos-radius:12px}" +
".hpos{font-family:'Inter',sans-serif;display:flex;height:calc(100vh - 80px);background:var(--pos-bg);gap:0;overflow:hidden}" +
".hpos *{box-sizing:border-box}" +
".hpos-left{flex:1;display:flex;flex-direction:column;overflow:hidden}" +
".hpos-right{width:400px;background:var(--pos-card);border-left:1px solid var(--pos-border);display:flex;flex-direction:column;min-height:0;overflow:hidden}" +
/* Both panes are header / scrolling body / pinned footer, so both have to be flex
   columns themselves. min-height:0 is the part that actually matters: a flex item
   defaults to min-height:auto, which makes it grow to fit its content and silently
   disables the overflow-y:auto on .cart-body inside it. */
"#pos-cart-pane,#pos-arr-detail{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}" +
"#pos-cart-pane.pane-hidden,#pos-arr-detail.pane-hidden{display:none}" +
".hpos-topbar{display:flex;align-items:center;gap:12px;padding:16px 24px;background:var(--pos-card);border-bottom:1px solid var(--pos-border)}" +
".hpos-topbar .logo-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;overflow:hidden;background:#fff;flex:0 0 auto}" +
".hpos-topbar .logo-icon img{width:100%;height:100%;object-fit:contain;display:block}" +
".hpos-topbar h2{margin:0;font-size:20px;font-weight:700;color:var(--pos-text)}" +
".hpos-topbar .subtitle{font-size:12px;color:var(--pos-muted);margin:0}" +
".hpos-filters{display:flex;gap:12px;padding:16px 24px;background:var(--pos-card);border-bottom:1px solid var(--pos-border);align-items:flex-end;flex-wrap:wrap}" +
".hpos-fg{display:flex;flex-direction:column;gap:4px}" +
".hpos-fg label{font-size:11px;font-weight:600;color:var(--pos-muted);text-transform:uppercase;letter-spacing:.5px}" +
".hpos-fg input{padding:8px 12px;border:1px solid var(--pos-border);border-radius:8px;font-size:13px;font-family:inherit;background:#fff;transition:all .2s}" +
".hpos-fg input:focus{outline:none;border-color:var(--pos-primary);box-shadow:0 0 0 3px rgba(99,102,241,.12)}" +
".hpos-btn{padding:8px 16px;border:none;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;font-family:inherit;transition:all .15s}" +
".hpos-btn-primary{background:var(--pos-primary);color:#fff}" +
".hpos-btn-primary:hover{background:var(--pos-primary-dark);transform:translateY(-1px)}" +
".hpos-stats{display:flex;gap:12px;padding:12px 24px;background:var(--pos-card);border-bottom:1px solid var(--pos-border)}" +
".hpos-stat{flex:1;text-align:center;padding:10px;border-radius:8px;background:var(--pos-bg)}" +
".hpos-stat .num{font-size:22px;font-weight:800;color:var(--pos-text)}" +
".hpos-stat .lbl{font-size:10px;color:var(--pos-muted);text-transform:uppercase;letter-spacing:.5px;margin-top:2px}" +
".stat-green .num{color:var(--pos-success)}" +
".stat-red .num{color:var(--pos-danger)}" +
".stat-blue .num{color:var(--pos-primary)}" +
".hpos-type-tabs{display:flex;gap:8px;padding:12px 24px;overflow-x:auto;background:var(--pos-card);border-bottom:1px solid var(--pos-border)}" +
".hpos-tab{padding:6px 16px;border-radius:20px;font-size:12px;font-weight:600;cursor:pointer;border:1px solid var(--pos-border);background:transparent;color:var(--pos-muted);white-space:nowrap;transition:all .2s;font-family:inherit}" +
".hpos-tab.active,.hpos-tab:hover{background:var(--pos-primary);color:#fff;border-color:var(--pos-primary)}" +
".hpos-grid{flex:1;padding:20px 24px;overflow-y:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;align-content:start}" +
".hpos-room{background:var(--pos-card);border:2px solid var(--pos-border);border-radius:var(--pos-radius);padding:16px;cursor:pointer;transition:all .25s cubic-bezier(.4,0,.2,1);position:relative}" +
".hpos-room:hover:not(.off):not(.occ){transform:translateY(-3px);box-shadow:0 8px 25px rgba(0,0,0,.08)}" +
".hpos-room.sel{border-color:var(--pos-primary);background:linear-gradient(135deg,#eef2ff,#e0e7ff)}" +
".hpos-room.sel::after{content:'\\2713';position:absolute;top:8px;right:8px;width:22px;height:22px;background:var(--pos-primary);color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700}" +
".hpos-room.occ{opacity:.5;cursor:not-allowed;background:#fef2f2;border-color:#fecaca}" +
".hpos-room.off{opacity:.4;cursor:not-allowed;background:#f8fafc;border-style:dashed}" +
".hpos-room .rm-num{font-size:20px;font-weight:800;color:var(--pos-text);margin-bottom:2px}" +
".hpos-room .rm-type{font-size:11px;color:var(--pos-muted);margin-bottom:8px}" +
".hpos-room .rm-rate{font-size:14px;font-weight:700;color:var(--pos-success)}" +
".hpos-room .rm-rate span{font-size:10px;font-weight:400;color:var(--pos-muted)}" +
".hpos-room .rm-dot{position:absolute;bottom:12px;right:12px;width:8px;height:8px;border-radius:50%}" +
".hpos-room .rm-meta{display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:6px}" +
".rm-cap{display:inline-flex;align-items:center;gap:3px;font-size:10px;font-weight:700;color:var(--pos-primary-dark);background:#eef2ff;border-radius:20px;padding:2px 7px;white-space:nowrap}" +
".rm-bed{display:inline-flex;align-items:center;font-size:10px;font-weight:600;color:var(--pos-muted);background:var(--pos-bg);border-radius:20px;padding:2px 7px;white-space:nowrap}" +
".rm-amen{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px;min-height:16px}" +
".rm-amen i{font-style:normal;font-size:12px;line-height:1;opacity:.85;cursor:help}" +
".rm-wknd{display:block;font-size:9px;color:var(--pos-warning);font-weight:700;margin-top:2px}" +
".rm-stay{display:block;font-size:10px;color:var(--pos-muted);font-weight:500;margin-top:1px}" +
".ci-warn{font-size:11px;color:var(--pos-danger);margin-top:4px;font-weight:600}" +
".ci-amen{font-size:11px;color:var(--pos-muted);margin-top:2px}" +
".cart-note{font-size:11px;color:var(--pos-muted);padding:8px 0 0;border-top:1px dashed var(--pos-border);margin-top:8px}" +
".dot-avail{background:var(--pos-success);box-shadow:0 0 6px var(--pos-success)}" +
".dot-occ{background:var(--pos-danger)}" +
".dot-maint{background:var(--pos-warning)}" +
".cart-hdr{flex:0 0 auto;padding:20px;border-bottom:1px solid var(--pos-border)}" +
".cart-hdr h3{margin:0;font-size:16px;font-weight:700;color:var(--pos-text)}" +
".cart-hdr .nights{font-size:12px;color:var(--pos-muted);margin-top:2px}" +
".cart-body{flex:1 1 auto;min-height:0;overflow-y:auto;padding:16px 20px}" +
".cart-sec{font-size:10px;font-weight:700;color:var(--pos-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:10px;margin-top:16px}" +
".cart-sec:first-child{margin-top:0}" +
".cart-item{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--pos-border)}" +
".cart-item:last-child{border-bottom:none}" +
".ci-name{font-size:14px;font-weight:600;color:var(--pos-text)}" +
".ci-sub{font-size:11px;color:var(--pos-muted)}" +
".ci-price{font-size:14px;font-weight:700;color:var(--pos-text)}" +
".ci-rm{color:var(--pos-danger);cursor:pointer;margin-left:8px;font-size:11px;padding:2px 6px;border-radius:4px;border:1px solid var(--pos-danger);background:transparent;font-family:inherit}" +
".ci-rm:hover{background:#fef2f2}" +
".cart-empty{text-align:center;padding:40px 20px;color:var(--pos-muted);font-size:13px}" +
".cart-empty .icon{font-size:36px;margin-bottom:8px;opacity:.4}" +
".guest-toggle{width:100%;padding:8px;border:1px dashed var(--pos-border);border-radius:8px;background:transparent;color:var(--pos-primary);font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;transition:all .2s;margin-bottom:12px}" +
".guest-toggle:hover{background:#eef2ff;border-color:var(--pos-primary)}" +
".guest-form{background:var(--pos-bg);padding:14px;border-radius:8px;display:none}" +
".gf-row{margin-bottom:10px}" +
".gf-row label{font-size:10px;font-weight:600;color:var(--pos-muted);text-transform:uppercase;display:block;margin-bottom:3px}" +
".gf-row input, .gf-row select{width:100%;padding:7px 10px;border:1px solid var(--pos-border);border-radius:6px;font-size:12px;font-family:inherit;background:#fff}" +
".gf-row input:focus, .gf-row select:focus{outline:none;border-color:var(--pos-primary)}" +
".cart-footer{flex:0 0 auto;padding:16px 20px;background:var(--pos-card);border-top:1px solid var(--pos-border)}" +
".cart-total{display:flex;justify-content:space-between;font-size:18px;font-weight:800;color:var(--pos-text);margin-bottom:12px}" +
".btn-book{width:100%;padding:14px;background:linear-gradient(135deg,#6366f1,#8b5cf6);color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;transition:all .2s;font-family:inherit;box-shadow:0 4px 14px rgba(99,102,241,.35)}" +
".btn-book:hover:not(:disabled){transform:translateY(-2px);box-shadow:0 6px 20px rgba(99,102,241,.45)}" +
".btn-book:disabled{opacity:.4;cursor:not-allowed;transform:none;box-shadow:none}" +
"#guest-link-wrapper .frappe-control{margin:0}";
        document.head.appendChild(s);
    }

    var $main = $(wrapper).find('.layout-main-section');
    $main.html(build_layout());
    $(wrapper).find('.page-head').hide();

    // Setup guest link field
    var guest_field = frappe.ui.form.make_control({
        parent: $('#guest-link-wrapper'),
        df: { fieldtype:'Link', options:'Guest', fieldname:'sel_guest', label:'Search Guest (Name / Phone)',
              onchange: function(){ POS.state.selected_guest = this.get_value(); POS.refresh_btn(); }},
        render_input: true
    });
    guest_field.make_input();

    // POS App
    var POS = {
        state: { rooms:[], room_types:[], cart:[], selected_guest:null, is_new_guest:false,
                 arrival: frappe.datetime.now_date(),
                 departure: frappe.datetime.add_days(frappe.datetime.now_date(),1),
                 arrival_time: '',
                 departure_time: '12:00',
                 nights:1, filter_type:'All', mode:'new', arrival_doc:null,
                 adults:1, children:0 },

        init: function(){
            this.bind();
            this.load();
        },

        bind: function(){
            var self = this;
            $('#pos-search-btn').on('click', function(){ self.on_search(); });
            // Party size drives the capacity warning in the cart, so keep state in
            // step as it is typed rather than only reading it at checkout.
            $('#pos-adults, #pos-children').on('input change', function(){
                self.state.adults = cint($('#pos-adults').val());
                self.state.children = cint($('#pos-children').val());
                self.render_cart();
            });
            $('#btn-new-guest').on('click', function(){
                self.state.is_new_guest = !self.state.is_new_guest;
                if(self.state.is_new_guest){
                    $('#new-guest-form').slideDown(200);
                    $('#guest-link-wrapper').hide();
                    $(this).text('Cancel');
                    guest_field.set_value('');
                } else {
                    $('#new-guest-form').slideUp(200);
                    $('#guest-link-wrapper').show();
                    $(this).text('+ New Guest');
                }
                self.refresh_btn();
            });
            $('#btn-confirm').on('click', function(){ self.book(); });
            $('#new-guest-form').on('input','input', function(){ self.refresh_btn(); });

            $('.hpos-mode').on('click', function(){ self.set_mode($(this).data('mode')); });
            $('#pos-arr-refresh').on('click', function(){ self.load_arrivals(); });
            $('#pos-arr-q').on('keydown', function(e){ if(e.key === 'Enter'){ self.load_arrivals(); } });
        },

        // --- Arrivals -------------------------------------------------------
        // The walk-in flow above is untouched. This mode exists because a guest who
        // booked by phone could not be processed here at all: their room reads as
        // Occupied and is un-clickable, and confirming would throw "already booked".
        set_mode: function(mode){
            this.state.mode = mode;
            $('.hpos-mode').removeClass('active');
            $('.hpos-mode[data-mode="'+mode+'"]').addClass('active');

            var arrivals = mode === 'arrivals';
            $('#pos-arrivals').toggle(arrivals);
            $('#pos-arr-detail').toggleClass('pane-hidden', !arrivals);
            $('#pos-grid, #pos-type-tabs, .hpos-filters, .hpos-stats').toggle(!arrivals);
            $('#pos-cart-pane').toggleClass('pane-hidden', arrivals);

            if(arrivals){ this.load_arrivals(); }
        },

        load_arrivals: function(){
            var self = this;
            $('#pos-arr-list').html('<div class="cart-empty"><div class="icon">⏳</div>Loading arrivals...</div>');
            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.get_arrivals',
                args:{ date: $('#pos-arr-date').val(), search: $('#pos-arr-q').val() },
                callback: function(r){
                    if(r.message){ self.render_arrivals(r.message); }
                }
            });
        },

        render_arrivals: function(data){
            var self = this;
            var rows = [];

            (data.bookings || []).forEach(function(b){
                var advance = b.advance_received ? '<span class="arr-adv">Advance '+format_currency(b.advance_received)+'</span>' : '';
                var due = b.balance_due > 0 ? '<span class="arr-due">Due '+format_currency(b.balance_due)+'</span>' : '';
                rows.push('<div class="arr-row" data-booking="'+b.name+'">'+
                    '<div class="arr-main">'+
                      '<div class="arr-name">'+frappe.utils.escape_html(b.guest_name || b.guest || '')+'</div>'+
                      '<div class="arr-meta">'+frappe.utils.escape_html(b.mobile_no || '')+' · '+b.name+'</div>'+
                      '<div class="arr-meta">'+frappe.datetime.str_to_user(b.arrival_date)+' → '+
                        frappe.datetime.str_to_user(b.departure_date)+' · '+(b.room_count||0)+' room(s)</div>'+
                    '</div>'+
                    '<div class="arr-side"><span class="arr-status arr-'+(b.status||'').toLowerCase().replace(/\s/g,'')+'">'+
                      b.status+'</span>'+advance+due+'</div>'+
                  '</div>');
            });

            (data.reservations || []).forEach(function(r){
                rows.push('<div class="arr-row" data-reservation="'+r.name+'">'+
                    '<div class="arr-main">'+
                      '<div class="arr-name">'+frappe.utils.escape_html(r.guest_name || r.guest || '')+'</div>'+
                      '<div class="arr-meta">'+frappe.utils.escape_html(r.mobile_no || '')+' · '+r.name+'</div>'+
                      '<div class="arr-meta">Room '+(r.room||'-')+' · '+
                        frappe.datetime.str_to_user(r.arrival_date)+'</div>'+
                    '</div>'+
                    '<div class="arr-side"><span class="arr-status arr-walkin">Walk-in</span></div>'+
                  '</div>');
            });

            $('#pos-arr-count').text(rows.length ? '('+rows.length+')' : '');

            if(!rows.length){
                $('#pos-arr-list').html('<div class="cart-empty"><div class="icon">📋</div>No arrivals for this date</div>');
                $('#pos-arr-detail').html('');
                return;
            }
            $('#pos-arr-list').html(rows.join(''));
            $('#pos-arr-list .arr-row').on('click', function(){
                $('#pos-arr-list .arr-row').removeClass('active');
                $(this).addClass('active');
                self.open_arrival($(this).data('booking'), $(this).data('reservation'));
            });
        },

        open_arrival: function(booking, reservation){
            var self = this;
            $('#pos-arr-detail').html('<div class="cart-empty"><div class="icon">⏳</div>Loading...</div>');
            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.get_arrival_detail',
                args:{ booking: booking || null, reservation: reservation || null },
                callback: function(r){
                    if(r.message){ self.state.arrival_doc = r.message; self.render_arrival_detail(r.message); }
                }
            });
        },

        render_arrival_detail: function(d){
            var self = this;
            var rooms = (d.rooms || []).map(function(line){
                var opts = (d.room_options && d.room_options[line.room_type]) || [];
                var cell;
                if(line.room){
                    cell = '<span class="arr-room-fixed">'+frappe.utils.escape_html(line.room)+'</span>';
                } else if(opts.length){
                    cell = '<select class="arr-room-pick" data-idx="'+line.idx+'">'+
                        opts.map(function(o){ return '<option value="'+frappe.utils.escape_html(o)+'">'+
                            frappe.utils.escape_html(o)+'</option>'; }).join('')+'</select>';
                } else {
                    cell = '<span class="arr-room-none">No room free</span>';
                }
                return '<div class="arr-line">'+
                    '<div>'+frappe.utils.escape_html(line.room_type || '')+
                      (line.reservation_status ? ' <span class="arr-tag">'+line.reservation_status+'</span>' : '')+'</div>'+
                    '<div>'+cell+'</div>'+
                  '</div>';
            }).join('');

            var advance = d.unapplied_advance > 0
                ? '<div class="arr-money arr-money-adv"><span>Advance to apply</span><span>'+
                  format_currency(d.unapplied_advance)+'</span></div>' : '';

            $('#pos-arr-detail').html(
                '<div class="cart-hdr"><h3>'+frappe.utils.escape_html(d.guest_name || '')+'</h3>'+
                  '<div class="nights">'+frappe.utils.escape_html(d.mobile_no || '')+'</div></div>'+
                '<div class="cart-body">'+
                  '<div class="cart-sec">'+d.name+' · '+(d.nights || '')+' night(s)</div>'+
                  '<div class="arr-lines">'+rooms+'</div>'+
                  (d.special_requests ? '<div class="arr-note">'+frappe.utils.escape_html(d.special_requests)+'</div>' : '')+
                  '<div class="cart-sec">Money</div>'+
                  '<div class="arr-money"><span>Total</span><span>'+format_currency(d.total_amount||0)+'</span></div>'+
                  '<div class="arr-money"><span>Advance received</span><span>'+format_currency(d.advance_received||0)+'</span></div>'+
                  advance+
                  '<div class="arr-money arr-money-due"><span>Balance due</span><span>'+format_currency(d.balance_due||0)+'</span></div>'+
                '</div>'+
                '<div class="cart-footer">'+
                  '<button class="btn-book" id="btn-checkin">Check In</button>'+
                '</div>'
            );

            $('#btn-checkin').on('click', function(){ self.checkin_arrival(); });
        },

        checkin_arrival: function(){
            var self = this;
            var d = this.state.arrival_doc;
            if(!d){ return; }

            var assignments = {};
            $('#pos-arr-detail .arr-room-pick').each(function(){
                assignments[$(this).data('idx')] = $(this).val();
            });

            var unassigned = (d.rooms || []).filter(function(l){
                return !l.room && !assignments[l.idx];
            });
            if(unassigned.length){
                frappe.msgprint('Every room must be assigned before check-in.');
                return;
            }

            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.checkin_arrival',
                args:{
                    booking: d.type === 'booking' ? d.name : null,
                    reservation: d.type === 'reservation' ? d.name : null,
                    room_assignments: JSON.stringify(assignments)
                },
                freeze: true,
                freeze_message: 'Checking in...',
                callback: function(r){
                    if(!r.message){ return; }
                    var msg = 'Checked in '+(r.message.checked_in || []).length+' room(s)';
                    if(r.message.advance_applied){
                        msg += ' · advance '+format_currency(r.message.advance_applied)+' applied';
                    }
                    frappe.show_alert({message: msg, indicator: 'green'});
                    self.load_arrivals();
                    $('#pos-arr-detail').html('');
                }
            });
        },

        on_search: function(){
            this.state.arrival = $('#pos-arr').val();
            this.state.departure = $('#pos-dep').val();
            this.state.arrival_time = $('#pos-arr-time').val();
            this.state.departure_time = $('#pos-dep-time').val();
            this.state.adults = cint($('#pos-adults').val());
            this.state.children = cint($('#pos-children').val());
            this.state.nights = frappe.datetime.get_diff(this.state.departure, this.state.arrival);
            if(this.state.nights <= 0){ frappe.msgprint('Departure must be after Arrival.'); return; }
            this.state.cart = [];
            this.load();
        },

        load: function(){
            var self = this;
            $('#pos-grid').html('<div class="cart-empty"><div class="icon">⏳</div>Loading inventory...</div>');
            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.get_pos_data',
                args:{
                    arrival: self.state.arrival,
                    departure: self.state.departure,
                    arrival_time: self.state.arrival_time || '',
                    departure_time: self.state.departure_time || '12:00'
                },
                callback: function(r){
                    if(r.message){
                        self.state.rooms = r.message.rooms || [];
                        self.state.room_types = r.message.room_types || [];
                        self.render_tabs();
                        self.render_grid();
                        self.render_stats();
                        self.render_cart();
                    }
                }
            });
        },

        render_stats: function(){
            var avail = this.state.rooms.filter(function(r){return r.status==='Available'}).length;
            var occ = this.state.rooms.filter(function(r){return r.status==='Occupied'}).length;
            var total = this.state.rooms.length;
            var pct = total ? Math.round(occ/total*100) : 0;
            $('#stat-avail').text(avail);
            $('#stat-occ').text(occ);
            $('#stat-pct').text(pct + '%');
            $('#stat-sel').text(this.state.cart.length);
            $('#cart-nights').text(this.state.nights);
        },

        render_tabs: function(){
            var self = this;
            var $tabs = $('#pos-type-tabs');
            $tabs.empty();
            $tabs.append('<button class="hpos-tab'+(self.state.filter_type==='All'?' active':'')+'" data-type="All">All Rooms</button>');
            self.state.room_types.forEach(function(rt){
                $tabs.append('<button class="hpos-tab'+(self.state.filter_type===rt.name?' active':'')+'" data-type="'+rt.name+'">'+rt.name+'</button>');
            });
            $tabs.off('click','.hpos-tab').on('click','.hpos-tab', function(){
                self.state.filter_type = $(this).data('type');
                $tabs.find('.hpos-tab').removeClass('active');
                $(this).addClass('active');
                self.render_grid();
            });
        },

        render_grid: function(){
            var self = this;
            var $grid = $('#pos-grid');
            $grid.empty();
            var filtered = self.state.rooms;
            if(self.state.filter_type !== 'All'){
                filtered = filtered.filter(function(r){ return r.room_type === self.state.filter_type; });
            }
            if(!filtered.length){
                $grid.html('<div class="cart-empty" style="grid-column:1/-1"><div class="icon">🏨</div>No rooms found</div>');
                return;
            }
            filtered.forEach(function(room){
                var is_sel = self.state.cart.some(function(c){return c.name===room.name});
                var cls = 'hpos-room';
                var dot = 'dot-avail';
                if(room.status==='Occupied'){ cls+=' occ'; dot='dot-occ'; }
                else if(room.status==='Maintenance'){ cls+=' off'; dot='dot-maint'; }
                if(is_sel) cls+=' sel';
                var currency = frappe.boot.sysdefaults.currency || 'INR';

                // Capacity and bed layout: what the guest is actually buying.
                var meta = '';
                if(room.max_occupancy){
                    meta += '<span class="rm-cap" title="'+__('Maximum guests allowed')+'">'+
                            '\uD83D\uDC64 '+__('Max {0}', [room.max_occupancy])+'</span>';
                }
                if(room.bedroom_configuration){
                    meta += '<span class="rm-bed">'+frappe.utils.escape_html(room.bedroom_configuration)+'</span>';
                }

                var amen = (room.amenities || []).map(function(a){
                    return '<i title="'+frappe.utils.escape_html(a.label)+'">'+a.icon+'</i>';
                }).join('');

                // Weekend nights cost more, so the flat nightly figure alone would
                // understate the stay. Show both when they disagree.
                var stay = '';
                if(room.stay_total && self.state.nights){
                    var flat = room.rate * self.state.nights;
                    if(Math.abs(room.stay_total - flat) > 0.5){
                        stay = '<span class="rm-stay">'+__('Stay')+': '+
                               format_currency(room.stay_total,currency)+'</span>';
                    }
                }
                var wknd = room.has_weekend_premium
                    ? '<span class="rm-wknd" title="'+__('Charged on Saturday, Sunday and holiday nights')+'">'+
                      __('Weekend/Holiday')+' '+format_currency(room.weekend_rate,currency)+'</span>'
                    : '';

                var $card = $('<div class="'+cls+'">'+
                    '<div class="rm-num">'+frappe.utils.escape_html(room.name)+'</div>'+
                    '<div class="rm-type">'+frappe.utils.escape_html(room.room_type)+'</div>'+
                    (meta ? '<div class="rm-meta">'+meta+'</div>' : '')+
                    '<div class="rm-rate">'+format_currency(room.rate,currency)+' <span>/night</span>'+wknd+stay+'</div>'+
                    (amen ? '<div class="rm-amen">'+amen+'</div>' : '')+
                    '<div class="rm-dot '+dot+'"></div>'+
                '</div>');
                if(room.status==='Available'){
                    $card.on('click', function(){ self.toggle(room); });
                }
                $grid.append($card);
            });
        },

        toggle: function(room){
            var idx = -1;
            for(var i=0;i<this.state.cart.length;i++){
                if(this.state.cart[i].name===room.name){idx=i;break;}
            }
            if(idx>-1) this.state.cart.splice(idx,1);
            else this.state.cart.push(room);
            this.render_grid();
            this.render_cart();
            this.render_stats();
        },

        render_cart: function(){
            var self = this;
            var $list = $('#cart-list');
            $list.empty();
            var total = 0;
            var currency = frappe.boot.sysdefaults.currency || 'INR';
            if(!self.state.cart.length){
                $list.html('<div class="cart-empty"><div class="icon">🛒</div>Select rooms from the left panel</div>');
            } else {
                var has_weekend = false;
                var capacity = 0;
                self.state.cart.forEach(function(room){
                    // stay_total is priced night by night on the server, so a stay
                    // spanning a weekend is charged correctly instead of rate x nights.
                    var rt = room.stay_total || (room.rate * self.state.nights);
                    total += rt;
                    capacity += (room.max_occupancy || 0);

                    var sub = frappe.utils.escape_html(room.room_type);
                    if(room.stay_total && Math.abs(room.stay_total - room.rate*self.state.nights) > 0.5){
                        has_weekend = true;
                        sub += ' &middot; '+format_currency(room.average_nightly,currency)+
                               ' '+__('avg')+' &times; '+self.state.nights+' '+__('nights');
                    } else {
                        sub += ' &middot; '+format_currency(room.rate,currency)+
                               ' &times; '+self.state.nights+' '+__('nights');
                    }

                    var amen = (room.amenities || []).map(function(a){ return a.icon; }).join(' ');
                    var cap = room.max_occupancy
                        ? '<div class="ci-amen">\uD83D\uDC64 '+__('Max {0}', [room.max_occupancy])+
                          (amen ? ' &nbsp; '+amen : '')+'</div>'
                        : (amen ? '<div class="ci-amen">'+amen+'</div>' : '');

                    $list.append(
                        '<div class="cart-item">'+
                          '<div><div class="ci-name">'+frappe.utils.escape_html(room.name)+'</div>'+
                          '<div class="ci-sub">'+sub+'</div>'+cap+'</div>'+
                          '<div style="display:flex;align-items:center">'+
                            '<div class="ci-price">'+format_currency(rt,currency)+'</div>'+
                            '<button class="ci-rm" data-room="'+frappe.utils.escape_html(room.name)+'">&times;</button>'+
                          '</div>'+
                        '</div>'
                    );
                });

                // Warn the moment the party no longer fits what is in the cart.
                var guests = cint(self.state.adults) + cint(self.state.children);
                if(guests && capacity && guests > capacity){
                    $list.append('<div class="ci-warn">\u26A0 '+
                        __('{0} guests exceed the {1} these rooms allow. Add a room or an extra bed.',
                           [guests, capacity])+'</div>');
                }
                if(has_weekend){
                    $list.append('<div class="cart-note">'+
                        __('Totals include the weekend tariff for Saturday, Sunday and holiday nights.')+
                        '</div>');
                }
                $list.off('click','.ci-rm').on('click','.ci-rm',function(){
                    var rn = $(this).data('room');
                    var rm = self.state.rooms.find(function(r){return r.name===rn});
                    if(rm) self.toggle(rm);
                });
            }
            $('#cart-total-val').text(format_currency(total, currency));
            self.refresh_btn();
        },

        refresh_btn: function(){
            var ok = this.state.cart.length > 0;
            if(this.state.is_new_guest){
                if(!$('#gf-name').val() || !$('#gf-name').val().trim()) ok = false;
            } else {
                if(!this.state.selected_guest) ok = false;
            }
            $('#btn-confirm').prop('disabled',!ok);
        },

        book: function(){
            var self = this;
            
            if(self.state.is_new_guest){
                var aadhaar = $('#gf-aadhaar').val().replace(/\s/g, '');
                if (aadhaar && aadhaar.length !== 12) {
                    frappe.msgprint("Aadhaar Number must be exactly 12 digits.");
                    return;
                }
                var pan = $('#gf-pan').val().replace(/\s/g, '');
                if (pan && pan.length !== 10) {
                    frappe.msgprint("PAN Number must be exactly 10 characters.");
                    return;
                }
            }
            
            $('#btn-confirm').prop('disabled',true).text('Processing...');
            var payload = {
                arrival: self.state.arrival,
                departure: self.state.departure,
                arrival_time: self.state.arrival_time || '',
                departure_time: self.state.departure_time || '',
                adults: $('#pos-adults').val() || 1,
                children: $('#pos-children').val() || 0,
                rooms: self.state.cart.map(function(c){return c.name}),
                is_new_guest: self.state.is_new_guest
            };
            if(self.state.is_new_guest){
                payload.guest_details = {
                    full_name: $('#gf-name').val(),
                    phone: $('#gf-phone').val(),
                    email: $('#gf-email').val(),
                    nationality: $('#gf-nationality').val(),
                    aadhaar: aadhaar,
                    pan: pan,
                    guest_type: $('#gf-type').val(),
                    gender: $('#gf-gender').val(),
                    address: $('#gf-address').val(),
                    special_requests: $('#gf-requests').val()
                };
            } else {
                payload.guest = self.state.selected_guest;
            }
            frappe.call({
                method:'hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.submit_pos_booking',
                args:{ payload: JSON.stringify(payload) },
                callback: function(r){
                    $('#btn-confirm').text('Confirm Booking');
                    if(!r.exc && r.message && r.message.success){
                        frappe.show_alert({message:'Booking confirmed!',indicator:'green'}, 5);
                        if(r.message.reservations.length===1)
                            frappe.set_route('Form','Hotel Reservation',r.message.reservations[0]);
                        else
                            frappe.set_route('List','Hotel Reservation');
                    } else {
                        self.refresh_btn();
                    }
                }
            });
        }
    };

    window.pos_app = POS;
    POS.init();
};

function build_layout(){
    var today = frappe.datetime.now_date();
    var tomorrow = frappe.datetime.add_days(today, 1);
    return '<div class="hpos">'+
      '<div class="hpos-left">'+
        '<div class="hpos-topbar">'+
          '<div class="logo-icon"><img src="/files/logo.jpeg" alt=""></div>'+
          '<div><h2>Hotel POS</h2><p class="subtitle">Quick Reservation &amp; Guest Registration</p></div>'+
          '<div class="hpos-modes">'+
            '<button class="hpos-mode active" data-mode="new">New Booking</button>'+
            '<button class="hpos-mode" data-mode="arrivals">Arrivals <span id="pos-arr-count"></span></button>'+
          '</div>'+
        '</div>'+
        '<div class="hpos-filters">'+
          '<div class="hpos-fg"><label>Check-in</label><input type="date" id="pos-arr" value="'+today+'"></div>'+
          '<div class="hpos-fg"><label>Check-in Time</label><input type="time" id="pos-arr-time" value="" style="width:110px" placeholder="Auto"></div>'+
          '<div class="hpos-fg"><label>Check-out</label><input type="date" id="pos-dep" value="'+tomorrow+'"></div>'+
          '<div class="hpos-fg"><label>Check-out Time</label><input type="time" id="pos-dep-time" value="12:00" style="width:110px"></div>'+
          '<div class="hpos-fg"><label>Adults</label><input type="number" id="pos-adults" value="1" min="1" max="30" style="width:70px"></div>'+
          '<div class="hpos-fg"><label>Children</label><input type="number" id="pos-children" value="0" min="0" max="30" style="width:70px"></div>'+
          '<button class="hpos-btn hpos-btn-primary" id="pos-search-btn">Check Availability</button>'+
        '</div>'+
        '<div class="hpos-stats">'+
          '<div class="hpos-stat stat-green"><div class="num" id="stat-avail">-</div><div class="lbl">Available</div></div>'+
          '<div class="hpos-stat stat-red"><div class="num" id="stat-occ">-</div><div class="lbl">Occupied</div></div>'+
          '<div class="hpos-stat stat-blue"><div class="num" id="stat-pct">-</div><div class="lbl">Occupancy</div></div>'+
          '<div class="hpos-stat"><div class="num" id="stat-sel">0</div><div class="lbl">Selected</div></div>'+
        '</div>'+
        '<div class="hpos-type-tabs" id="pos-type-tabs"></div>'+
        '<div class="hpos-grid" id="pos-grid"></div>'+
        '<div class="hpos-arrivals" id="pos-arrivals" style="display:none">'+
          '<div class="hpos-arr-search">'+
            '<input type="date" id="pos-arr-date" value="'+today+'">'+
            '<input type="search" id="pos-arr-q" placeholder="Search name, phone or booking no">'+
            '<button class="hpos-btn hpos-btn-primary" id="pos-arr-refresh">Find</button>'+
          '</div>'+
          '<div id="pos-arr-list"></div>'+
        '</div>'+
      '</div>'+
      '<div class="hpos-right">'+
        '<div id="pos-arr-detail" class="pane-hidden"></div>'+
        '<div id="pos-cart-pane">'+
        '<div class="cart-hdr"><h3>Booking Summary</h3><div class="nights"><span id="cart-nights">1</span> Night(s) Stay</div></div>'+
        '<div class="cart-body">'+
          '<div class="cart-sec">Selected Rooms</div>'+
          '<div id="cart-list"><div class="cart-empty"><div class="icon">🛒</div>Select rooms from the left panel</div></div>'+
          '<div class="cart-sec">Guest Details</div>'+
          '<div id="guest-link-wrapper"></div>'+
          '<button class="guest-toggle" id="btn-new-guest">+ New Guest</button>'+
          '<div class="guest-form" id="new-guest-form">'+
            '<div class="gf-row"><label>Full Name *</label><input id="gf-name" placeholder="Enter full name"></div>'+
            '<div class="gf-row"><label>Guest Type</label><select id="gf-type"><option value="Regular">Regular</option><option value="VIP">VIP</option><option value="Corporate">Corporate</option><option value="Staff">Staff</option><option value="Blacklisted">Blacklisted</option></select></div>'+
            '<div class="gf-row"><label>Gender</label><select id="gf-gender"><option value=""></option><option value="Male">Male</option><option value="Female">Female</option><option value="Other">Other</option></select></div>'+
            '<div class="gf-row"><label>Phone</label><input id="gf-phone" placeholder="+91 98765 43210"></div>'+
            '<div class="gf-row"><label>Email</label><input id="gf-email" type="email" placeholder="guest@email.com"></div>'+
            '<div class="gf-row"><label>Address</label><input id="gf-address" placeholder="Address"></div>'+
            '<div class="gf-row"><label>Nationality</label><input id="gf-nationality" value="Indian"></div>'+
            '<div class="gf-row"><label>Aadhaar (Optional)</label><input id="gf-aadhaar" placeholder="1234 5678 9012"></div>'+
            '<div class="gf-row"><label>PAN (Optional)</label><input id="gf-pan" placeholder="ABCDE1234F"></div>'+
            '<div class="gf-row"><label>Special Requests</label><input id="gf-requests" placeholder="Any special requests..."></div>'+
          '</div>'+
        '</div>'+
        '<div class="cart-footer">'+
          '<div class="cart-total"><span>Total</span><span id="cart-total-val">₹0</span></div>'+
          '<button class="btn-book" id="btn-confirm" disabled>Confirm Booking</button>'+
        '</div>'+
        '</div>'+
      '</div>'+
    '</div>';
}