/* Hotel CRM — sales console for phone enquiries.
 *
 * Same stack as hotel_pos (Frappe Desk Page + vanilla JS, no build step), but every
 * input is a real frappe.ui.form.make_control rather than a bare <input>. That is what
 * gives native theming, dark mode, the user's date format, and Link autocomplete —
 * hand-rolled inputs look like unstyled HTML no matter how much CSS is thrown at them.
 *
 * The detail form is built ONCE and reused: opening a record sets values on the existing
 * controls instead of re-rendering the DOM, so focus and scroll survive and there is no
 * flicker between records — which matters when an agent is moving through a call queue.
 *
 * Styles live in hotel_crm.css, which Frappe bundles automatically.
 */

frappe.pages['hotel-crm'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Hotel CRM'),
		single_column: true,
	});

	// Brand mark in the page head rather than inside the three-pane layout: the console
	// is dense and every pixel of it is working space. onerror drops the node so a
	// missing file leaves the title where it was, not a broken-image glyph beside it.
	page.$title_area.prepend(
		'<img class="hcrm-brand" src="/files/logo.jpeg" alt="" onerror="this.remove()">'
	);

	// Frappe ships two icon sprites (timeless "#icon-x" and espresso "#es-line-x") and
	// which ids resolve depends on the active theme, so a hardcoded <use href> renders
	// blank half the time. These inline paths render on every theme.
	const svg = (body, cls) =>
		`<svg class="hcrm-icon ${cls || ''}" viewBox="0 0 24 24" fill="none"
			stroke="currentColor" stroke-width="1.7" stroke-linecap="round"
			stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

	const ICONS = {
		search: svg('<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>', 'hcrm-icon-sm'),
		call: svg(
			'<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2 4.2 2 2 0 0 1 4 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.1a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2z"/>',
			'hcrm-icon-lg'
		),
		users: svg(
			'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9"/><path d="M16 3.1a4 4 0 0 1 0 7.8"/>',
			'hcrm-icon-lg'
		),
	};

	const PERSON_FIELDS = [
		{ fieldname: 'guest_name', label: __('Guest Name'), fieldtype: 'Data', reqd: 1, span: 2 },
		{ fieldname: 'mobile_no', label: __('Mobile'), fieldtype: 'Data', options: 'Phone', reqd: 1 },
		{ fieldname: 'alt_mobile', label: __('Alternate'), fieldtype: 'Data', options: 'Phone' },
		{ fieldname: 'email', label: __('Email'), fieldtype: 'Data', options: 'Email', span: 2 },
		{ fieldname: 'city', label: __('City'), fieldtype: 'Data' },
		{ fieldname: 'source', label: __('Source'), fieldtype: 'Link', options: 'Hotel Enquiry Source', reqd: 1 },
	];

	const PIPELINE_FIELDS = [
		{ fieldname: 'status', label: __('Status'), fieldtype: 'Link', options: 'Hotel Enquiry Status' },
		{ fieldname: 'enquiry_owner', label: __('Owner'), fieldtype: 'Link', options: 'User' },
		{ fieldname: 'next_follow_up', label: __('Next Follow-up'), fieldtype: 'Datetime', span: 2 },
	];

	const STAY_FIELDS = [
		{ fieldname: 'check_in_date', label: __('Check In'), fieldtype: 'Date' },
		{ fieldname: 'check_out_date', label: __('Check Out'), fieldtype: 'Date' },
		{ fieldname: 'adults', label: __('Adults'), fieldtype: 'Int' },
		{ fieldname: 'children', label: __('Children'), fieldtype: 'Int' },
	];

	const CLOSING_FIELDS = [
		{ fieldname: 'budget', label: __('Guest Budget'), fieldtype: 'Currency', span: 2 },
		{ fieldname: 'lost_reason', label: __('Lost Reason'), fieldtype: 'Link', options: 'Hotel Lost Reason', span: 2 },
		{ fieldname: 'notes', label: __('Remarks'), fieldtype: 'Small Text', span: 4 },
	];

	const ALL_FIELDS = [].concat(PERSON_FIELDS, PIPELINE_FIELDS, STAY_FIELDS, CLOSING_FIELDS);

	const CRM = {
		state: {
			view: 'console',
			queue: 'due',
			search: '',
			selected: null,
			doc: null,
			dirty: false,
			masters: null,
			built: false,
		},
		controls: {},

		// ------------------------------------------------------------------ boot
		init() {
			this.$body = $(wrapper).find('.layout-main-section');

			page.set_primary_action(__('New Enquiry'), () => this.new_enquiry(), 'add');
			this.$board_btn = page.add_button(__('Pipeline Board'), () => this.toggle_view());
			page.add_menu_item(__('Refresh'), () => this.reload());

			frappe.call({
				method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_console_data',
				callback: (r) => {
					if (!r.message) return;
					this.state.masters = r.message;
					this.render_shell();
					this.load_queue();
				},
			});

			// Ctrl/Cmd+S saves, like every other Frappe form.
			$(document).on('keydown.hotelcrm', (e) => {
				if ((e.ctrlKey || e.metaKey) && e.key === 's' && this.state.view === 'console') {
					e.preventDefault();
					this.save();
				}
			});
			$(wrapper).on('remove', () => $(document).off('keydown.hotelcrm'));
		},

		toggle_view() {
			this.state.view = this.state.view === 'board' ? 'console' : 'board';
			this.state.built = false;
			this.$board_btn.text(this.state.view === 'board' ? __('Console') : __('Pipeline Board'));
			if (this.state.view === 'board') {
				this.$body.html(
					'<div class="hcrm-board-wrap">' +
						'<div class="hcrm-board-filters" id="hcrm-board-filters"></div>' +
						'<div class="hcrm-board" id="hcrm-board"></div>' +
					'</div>'
				);
				this.render_board_filters();
				this.load_board();
			} else {
				this.render_shell();
				this.load_queue();
				if (this.state.selected) this.open(this.state.selected);
			}
		},

		reload() {
			if (this.state.view === 'board') return this.load_board();
			this.load_queue();
			this.refresh_counts();
			if (this.state.selected) this.open(this.state.selected);
		},

		// ------------------------------------------------------------------ shell
		render_shell() {
			this.$body.html(`
				<div class="hcrm">
					<aside class="hcrm-pane hcrm-queue">
						<div class="hcrm-queue-head">
							<div class="hcrm-segmented" id="hcrm-tabs"></div>
							<div class="hcrm-search">
								${ICONS.search}
								<input type="search" id="hcrm-search"
									placeholder="${__('Search name or phone')}" autocomplete="off">
							</div>
						</div>
						<div class="hcrm-scroll" id="hcrm-list"></div>
					</aside>

					<section class="hcrm-pane hcrm-detail">
						<div class="hcrm-scroll" id="hcrm-detail"></div>
					</section>

					<aside class="hcrm-pane hcrm-context">
						<div class="hcrm-pane-head">
							<span>${__('Call History')}</span>
							<span class="hcrm-chip" id="hcrm-call-count"></span>
						</div>
						<div class="hcrm-scroll" id="hcrm-context"></div>
					</aside>
				</div>
			`);
			this.state.built = false;
			this.render_tabs();

			const debounced = frappe.utils.debounce(() => {
				this.state.search = $('#hcrm-search').val().trim();
				this.load_queue();
			}, 300);
			$('#hcrm-search').on('input', debounced);

			this.render_empty_detail();
		},

		render_tabs() {
			const c = (this.state.masters && this.state.masters.counts) || {};
			const tabs = [
				{ key: 'due', label: __('Due'), count: c.due },
				{ key: 'mine', label: __('Mine'), count: c.mine },
				{ key: 'all', label: __('Open'), count: c.all },
				{ key: 'calls', label: __('Calls'), count: c.calls },
			];
			$('#hcrm-tabs').html(
				tabs
					.map(
						(t) => `<button class="hcrm-seg ${t.key === this.state.queue ? 'active' : ''}"
							data-queue="${t.key}">${t.label}${
							t.count ? `<span class="hcrm-seg-count">${t.count}</span>` : ''
						}</button>`
					)
					.join('')
			);
			$('#hcrm-tabs')
				.off('click')
				.on('click', '.hcrm-seg', (e) => {
					this.state.queue = $(e.currentTarget).data('queue');
					this.render_tabs();
					this.load_queue();
				});
		},

		// ------------------------------------------------------------------ queue
		load_queue() {
			$('#hcrm-list').html(this.skeleton(6));
			frappe.call({
				method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_enquiries',
				args: { queue: this.state.queue, search: this.state.search },
				callback: (r) => {
					if (!r.message) return;
					if (r.message.type === 'calls') this.render_calls_queue(r.message.rows);
					else this.render_queue(r.message.rows);
				},
			});
		},

		skeleton(n) {
			return new Array(n).fill('<div class="hcrm-skel"></div>').join('');
		},

		empty(icon, title, hint) {
			return `<div class="hcrm-empty">
				${ICONS[icon] || ''}
				<div class="hcrm-empty-title">${title}</div>
				${hint ? `<div class="hcrm-empty-hint">${hint}</div>` : ''}
			</div>`;
		},

		initials(name) {
			return (name || '?')
				.trim()
				.split(/\s+/)
				.slice(0, 2)
				.map((w) => w[0])
				.join('')
				.toUpperCase();
		},

		render_queue(rows) {
			if (!rows.length) {
				$('#hcrm-list').html(
					this.empty(
						'search',
						__('Nothing here'),
						this.state.search ? __('Try a different name or number.') : __('This queue is clear.')
					)
				);
				return;
			}
			const now = frappe.datetime.now_datetime();
			$('#hcrm-list').html(
				rows
					.map((row) => {
						const overdue = row.next_follow_up && row.next_follow_up <= now;
						const stay = row.check_in_date
							? `${frappe.datetime.str_to_user(row.check_in_date)} · ${row.nights || 0}N`
							: __('No dates');
						return `
						<div class="hcrm-row ${row.name === this.state.selected ? 'active' : ''}" data-name="${row.name}">
							<div class="hcrm-avatar hcrm-c-${(row.status_color || 'gray').toLowerCase()}">${this.initials(
							row.guest_name
						)}</div>
							<div class="hcrm-row-main">
								<div class="hcrm-row-top">
									<span class="hcrm-row-name">${frappe.utils.escape_html(row.guest_name || '')}</span>
									${overdue ? `<span class="hcrm-due-dot" title="${__('Follow-up due')}"></span>` : ''}
								</div>
								<div class="hcrm-row-meta">${frappe.utils.escape_html(row.mobile_no || '')}</div>
								<div class="hcrm-row-foot">
									<span class="hcrm-pill hcrm-c-${(row.status_color || 'gray').toLowerCase()}">${frappe.utils.escape_html(
							row.status || ''
						)}</span>
									<span class="hcrm-row-stay">${stay}</span>
									${row.quoted_total ? `<span class="hcrm-row-amt">${format_currency(row.quoted_total)}</span>` : ''}
								</div>
							</div>
						</div>`;
					})
					.join('')
			);
			$('#hcrm-list')
				.off('click')
				.on('click', '.hcrm-row', (e) => this.open($(e.currentTarget).data('name')));
		},

		render_calls_queue(rows) {
			if (!rows.length) {
				$('#hcrm-list').html(this.empty('call', __('No unattended calls'), __('Every call is linked to an enquiry.')));
				return;
			}
			$('#hcrm-list').html(
				rows
					.map((c) => {
						const number = c.type === 'Outgoing' ? c.to : c.from;
						const missed = c.status !== 'Completed';
						const cls = missed ? 'missed' : c.type === 'Incoming' ? 'in' : 'out';
						return `
						<div class="hcrm-row" data-call="${c.name}">
							<div class="hcrm-avatar hcrm-call-${cls}">${c.type === 'Incoming' ? '↓' : '↑'}</div>
							<div class="hcrm-row-main">
								<div class="hcrm-row-name">${frappe.utils.escape_html(c.custom_contact_name || number || '')}</div>
								<div class="hcrm-row-meta">${frappe.utils.escape_html(number || '')}</div>
								<div class="hcrm-row-foot">
									<span class="hcrm-tag hcrm-call-${cls}">${frappe.utils.escape_html(c.status || '')}</span>
									<span class="hcrm-row-stay">${c.start_time ? frappe.datetime.str_to_user(c.start_time) : ''}</span>
								</div>
							</div>
							<button class="btn btn-xs btn-default hcrm-row-action">${__('Add')}</button>
						</div>`;
					})
					.join('')
			);
			$('#hcrm-list')
				.off('click')
				.on('click', '.hcrm-row', (e) => this.enquiry_from_call($(e.currentTarget).data('call')));
		},

		// ------------------------------------------------------------------ detail
		render_empty_detail() {
			$('#hcrm-detail').html(
				this.empty(
					'users',
					__('No enquiry selected'),
					__('Pick one from the queue, or press New Enquiry while you are on a call.')
				)
			);
			$('#hcrm-context').html(this.empty('call', __('No calls'), ''));
			$('#hcrm-call-count').text('');
		},

		/** Build the form skeleton and mount every control. Runs at most once per shell. */
		build_form() {
			if (this.state.built) return;

			$('#hcrm-detail').html(`
				<div class="hcrm-doc">
					<header class="hcrm-doc-head">
						<div class="hcrm-avatar hcrm-avatar-lg" id="hcrm-head-avatar">?</div>
						<div class="hcrm-head-main">
							<div class="hcrm-head-title" id="hcrm-head-name">${__('New Enquiry')}</div>
							<div class="hcrm-head-sub" id="hcrm-head-sub"></div>
						</div>
						<div class="hcrm-head-side">
							<div class="hcrm-head-amt" id="hcrm-head-amt"></div>
							<div class="hcrm-head-actions" id="hcrm-head-actions"></div>
						</div>
					</header>

					<div class="hcrm-body">
						<div class="hcrm-card">
							<div class="hcrm-card-title">${__('Guest')}</div>
							<div class="hcrm-grid" id="grp-person"></div>
						</div>

						<div class="hcrm-card">
							<div class="hcrm-card-title">${__('Pipeline')}</div>
							<div class="hcrm-grid" id="grp-pipeline"></div>
						</div>

						<div class="hcrm-card">
							<div class="hcrm-card-title">
								<span>${__('Stay')}</span>
								<span class="hcrm-chip" id="hcrm-nights"></span>
							</div>
							<div class="hcrm-grid" id="grp-stay"></div>
							<div id="hcrm-avail"></div>
						</div>

						<div class="hcrm-card">
							<div class="hcrm-card-title">
								<span>${__('Rooms')}</span>
								<span class="hcrm-rooms-tools">
									<select class="form-control input-xs" id="hcrm-room-filter"
										title="${__('Show only rooms of this type in the room picker')}"></select>
									<button class="btn btn-xs btn-default" id="hcrm-add-line">
										${__('Add Room')}
									</button>
								</span>
							</div>
							<div id="hcrm-lines-wrap"></div>
						</div>

						<div class="hcrm-card">
							<div class="hcrm-card-title">${__('Notes')}</div>
							<div class="hcrm-grid" id="grp-closing"></div>
						</div>
					</div>

					<footer class="hcrm-actionbar">
						<span class="hcrm-dirty" id="hcrm-dirty"></span>
						<span class="hcrm-booking-state" id="hcrm-booking-state"></span>
						<button class="btn btn-default btn-sm" id="hcrm-followup">${__('Log Follow-up')}</button>
						<button class="btn btn-default btn-sm" id="hcrm-book">${__('Create Booking')}</button>
						<button class="btn btn-primary btn-sm" id="hcrm-save">${__('Save')}</button>
					</footer>
				</div>
			`);

			this.controls = {};
			this.mount(PERSON_FIELDS, '#grp-person');
			this.mount(PIPELINE_FIELDS, '#grp-pipeline');
			this.mount(STAY_FIELDS, '#grp-stay');
			this.mount(CLOSING_FIELDS, '#grp-closing');

			$('#hcrm-save').on('click', () => this.save());
			$('#hcrm-followup').on('click', () => this.follow_up_dialog());
			$('#hcrm-add-line').on('click', () => this.add_line());
			// Narrows the room picker to one category; the room chosen still decides
			// the type of each line.
			$('#hcrm-room-filter')
				.html(
					`<option value="">${__('All room types')}</option>` +
						(this.state.masters.room_types || [])
							.map((t) => `<option value="${frappe.utils.escape_html(t.name)}">${frappe.utils.escape_html(t.name)}</option>`)
							.join('')
				)
				.val(this.state.room_filter || '')
				.on('change', (e) => {
					this.state.room_filter = $(e.currentTarget).val() || '';
					this.render_lines();
				});
			$('#hcrm-book').on('click', () => this.booking_dialog());

			this.state.built = true;
		},

		mount(fields, selector) {
			const $wrap = $(selector);
			fields.forEach((f) => {
				const $cell = $(`<div class="hcrm-cell span${f.span || 1}"></div>`).appendTo($wrap);
				const df = Object.assign({}, f);
				delete df.span;

				// Statuses are ordered by pipeline position, not alphabetically, so the
				// dropdown reads like the board does.
				if (df.fieldname === 'status') {
					df.get_query = () => ({ query: null });
				}

				df.change = () => this.on_field_change(f.fieldname);

				const control = frappe.ui.form.make_control({
					parent: $cell,
					df: df,
					render_input: true,
					only_input: false,
				});
				control.refresh();
				this.controls[f.fieldname] = control;
			});
		},

		on_field_change(fieldname) {
			if (!this.state.doc) return;
			// Ignore the change events a control fires while we are pushing saved values
			// into it — that is us writing, not the user editing.
			if (this._loading) return;

			const control = this.controls[fieldname];
			if (!control) return;

			const value = control.get_value();
			if (this.same(this.state.doc[fieldname], value)) return;

			this.state.doc[fieldname] = value;
			this.mark_dirty();

			if (fieldname === 'check_in_date' || fieldname === 'check_out_date') {
				this.render_lines();
				// The tariff is weekday/weekend/holiday split, so moving the dates can
				// change every line's rate. Ask the server rather than guessing.
				this.refresh_all_rates();
				this.update_header();
				this.load_availability();
			}
			if (fieldname === 'status') this.on_status_change();
			if (fieldname === 'guest_name' || fieldname === 'mobile_no') this.update_header();
		},

		on_status_change() {
			const type = this.status_type(this.state.doc.status);
			// Lost Reason is only meaningful on a Lost status, and is mandatory there.
			this.toggle_field('lost_reason', type === 'Lost');
			this.update_header();
		},

		toggle_field(fieldname, show) {
			const c = this.controls[fieldname];
			if (!c) return;
			$(c.wrapper).closest('.hcrm-cell').toggle(!!show);
		},

		/** Would the server consider these two values the same?
		 *
		 * A strict === here reported a freshly saved record as dirty: the server sends
		 * null for an empty field while a Frappe control reads back "", and Currency and
		 * Int fields come back as numbers but read as strings. Every one of those false
		 * positives blocked Create Booking behind a Save that had already happened.
		 */
		same(a, b) {
			const aEmpty = a == null || a === '';
			const bEmpty = b == null || b === '';
			if (aEmpty || bEmpty) return aEmpty && bEmpty;
			if (typeof a === 'number' || typeof b === 'number') {
				return Number(a) === Number(b);
			}
			return String(a) === String(b);
		},

		mark_dirty() {
			this.state.dirty = true;
			$('#hcrm-dirty').text(__('Unsaved changes'));
		},

		clear_dirty() {
			this.state.dirty = false;
			$('#hcrm-dirty').text('');
		},

		open(name) {
			if (this.state.dirty && !confirm(__('Discard unsaved changes?'))) return;
			frappe.call({
				method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_enquiry',
				args: { name },
				callback: (r) => {
					if (!r.message) return;
					this.state.selected = name;
					this.state.doc = r.message;
					this.build_form();
					this.load_into_form();
					this.clear_dirty();
					$('#hcrm-list .hcrm-row').removeClass('active');
					$(`#hcrm-list .hcrm-row[data-name="${name}"]`).addClass('active');
					this.render_context();
				},
			});
		},

		new_enquiry() {
			if (this.state.view === 'board') this.toggle_view();
			if (this.state.dirty && !confirm(__('Discard unsaved changes?'))) return;

			this.state.selected = null;
			this.state.doc = {
				guest_name: '',
				mobile_no: '',
				adults: 2,
				children: 0,
				status: this.default_status(),
				enquiry_owner: this.state.masters.user,
				room_lines: [],
				calls: [],
				discount_type: '',
				discount_value: 0,
				remarks: '',
			};
			this.build_form();
			this.load_into_form();
			this.mark_dirty();
			$('#hcrm-list .hcrm-row').removeClass('active');
			this.render_context();
			setTimeout(() => this.controls.guest_name && this.controls.guest_name.set_focus(), 60);
		},

		default_status() {
			const open = (this.state.masters.statuses || []).filter((s) => s.type === 'Open');
			return (open[0] || this.state.masters.statuses[0] || {}).name;
		},

		status_type(status) {
			const s = (this.state.masters.statuses || []).find((x) => x.name === status);
			return s ? s.type : 'Open';
		},

		status_color(status) {
			const s = (this.state.masters.statuses || []).find((x) => x.name === status);
			return (s && s.color ? s.color : 'gray').toLowerCase();
		},

		load_into_form() {
			const d = this.state.doc;
			this._loading = true;
			ALL_FIELDS.forEach((f) => {
				const c = this.controls[f.fieldname];
				if (!c) return;
				let v = d[f.fieldname];
				if (f.fieldtype === 'Small Text') v = this.strip_html(v);
				v = v == null ? '' : v;
				// Keep the record in step with what the control actually holds, so the
				// next comparison is against the same shape of value.
				d[f.fieldname] = v;
				c.set_value(v);
			});
			this._loading = false;
			this.on_status_change();
			this.render_lines();
			this.update_header();
			this.load_availability();
			this.render_booking_state();
		},

		read_form() {
			const out = Object.assign({}, this.state.doc);
			ALL_FIELDS.forEach((f) => {
				const c = this.controls[f.fieldname];
				if (c) out[f.fieldname] = c.get_value();
			});
			return out;
		},

		update_header() {
			const d = this.state.doc || {};
			const color = this.status_color(d.status);
			$('#hcrm-head-avatar')
				.attr('class', `hcrm-avatar hcrm-avatar-lg hcrm-c-${color}`)
				.text(this.initials(d.guest_name) || '?');
			$('#hcrm-head-name').text(d.guest_name || __('New Enquiry'));

			const nights = this.nights();
			$('#hcrm-nights').text(nights ? __('{0} nights', [nights]) : '');

			const bits = [];
			if (this.state.selected) bits.push(this.state.selected);
			if (d.mobile_no) bits.push(frappe.utils.escape_html(d.mobile_no));
			if (d.status)
				bits.push(
					`<span class="hcrm-pill hcrm-c-${color}">${frappe.utils.escape_html(d.status)}</span>`
				);
			$('#hcrm-head-sub').html(bits.join('<span class="hcrm-sep">·</span>'));

			const total = this.quote_total();
			$('#hcrm-head-amt').text(total ? format_currency(total) : '');

			// Click-to-call / WhatsApp straight from the header — the two things an agent
			// does most between saves.
			const num = (d.mobile_no || '').replace(/[^\d+]/g, '');
			$('#hcrm-head-actions').html(
				num
					? `<a class="btn btn-xs btn-default" href="tel:${num}">${__('Call')}</a>
					   <a class="btn btn-xs btn-default" target="_blank" rel="noopener"
					      href="https://wa.me/${num.replace(/\D/g, '')}">${__('WhatsApp')}</a>`
					: ''
			);
		},

		// ------------------------------------------------------------------ room lines
		nights() {
			const d = this.state.doc || {};
			const ci = this.controls.check_in_date ? this.controls.check_in_date.get_value() : d.check_in_date;
			const co = this.controls.check_out_date ? this.controls.check_out_date.get_value() : d.check_out_date;
			if (!ci || !co) return 0;
			return Math.max(frappe.datetime.get_diff(co, ci), 0);
		},

		/* Room charge before extra beds and before discount. */
		line_room_total(line) {
			const nights = Math.max(this.nights(), 1);
			return (Number(line.rate_quoted) || 0) * Math.max(Number(line.qty) || 1, 1) * nights;
		},

		/* Extra beds for a party over capacity, priced from the category.
		 * Mirrors tariff.auto_extra_beds: capacity is filled with adults first, so the
		 * overflow is billed at the rate matching who is actually in the bed. */
		line_extra_beds(line) {
			const t = (this.state.masters.room_types || []).find((x) => x.name === line.room_type);
			if (!t || !cint(t.max_occupancy)) return { adults: 0, children: 0, amount: 0 };

			const qty = Math.max(cint(line.qty) || 1, 1);
			const capacity = cint(t.max_occupancy) * qty;
			const adults = cint(line.adults);
			const children = cint(line.children);

			let bed_adults = cint(line.extra_beds_adult);
			let bed_children = cint(line.extra_beds_child);
			if (!bed_adults && !bed_children) {
				bed_adults = Math.max(adults - capacity, 0);
				bed_children = Math.max(children - Math.max(capacity - adults, 0), 0);
			}

			const nights = Math.max(this.nights(), 1);
			const amount =
				(bed_adults * flt(t.extra_bed_adult_rate) +
					bed_children * flt(t.extra_bed_child_rate)) *
				qty *
				nights;
			return { adults: bed_adults, children: bed_children, amount };
		},

		line_gross(line) {
			return this.line_room_total(line) + this.line_extra_beds(line).amount;
		},

		/* What the Amount cell reads while a row has no rate yet. A pending row used to
		 * show ₹0.00 and then jump, which looked like the figure arriving and leaving. */
		line_amount_text(line) {
			return !flt(line.rate_quoted) && this.can_quote()
				? '—'
				: format_currency(this.line_amount(line));
		},

		line_amount(line) {
			// Mirrors HotelEnquiry.calculate_quote: a line is room + extra beds. The
			// discount is agreed once for the whole quote, so it is not applied here.
			return this.line_gross(line);
		},

		/* Pull one line's rate from the pricing engine, so the figure an agent quotes is
		 * the figure the folio will bill: weekend and holiday nights included.
		 *
		 * The catalog's `default_rate` is only the weekday tariff, so it is right for a
		 * Tuesday and wrong for a Saturday. A line whose rate the agent agreed by hand is
		 * left alone.
		 */
		/* True once the dates on screen describe a real stay, so the engine can price it. */
		can_quote() {
			const ci = this.controls.check_in_date && this.controls.check_in_date.get_value();
			const co = this.controls.check_out_date && this.controls.check_out_date.get_value();
			return !!(ci && co && frappe.datetime.get_diff(co, ci) > 0);
		},

		/* Show that a row's rate is being priced rather than showing a guess at it. */
		mark_rate_pending(i, pending) {
			$(`#hcrm-lines-wrap tbody tr[data-i="${i}"] .l-rate_quoted`)
				.toggleClass('hcrm-pricing', !!pending);
		},

		refresh_line_rate(i) {
			const d = this.state.doc;
			const line = d && d.room_lines && d.room_lines[i];
			if (!line || !line.room_type || cint(line.is_rate_overridden)) return;

			const ci = this.controls.check_in_date && this.controls.check_in_date.get_value();
			const co = this.controls.check_out_date && this.controls.check_out_date.get_value();
			if (!ci || !co || frappe.datetime.get_diff(co, ci) <= 0) return;

			this.mark_rate_pending(i, true);

			// Remember what we asked about: an agent clicking through the dropdown can
			// land a stale response on a row that has since become something else.
			const asked_for = line.room_type;

			frappe
				.call({
					method: 'hospitality_core.hospitality_core.api.tariff.quote_stay',
					args: {
						room_type: asked_for,
						arrival_date: ci,
						departure_date: co,
						qty: line.qty || 1,
						adults: line.adults || 0,
						children: line.children || 0,
					},
				})
				.then((r) => {
					this.mark_rate_pending(i, false);
					const q = r && r.message;
					if (!q) return;
					const current = this.state.doc && this.state.doc.room_lines && this.state.doc.room_lines[i];
					if (!current || current.room_type !== asked_for || cint(current.is_rate_overridden)) {
						return;
					}
					// The agent is in the rate box right now, so whatever they are part
					// way through typing wins over a quote that happens to land on this
					// keystroke.
					const $rate = $(`#hcrm-lines-wrap tbody tr[data-i="${i}"] .l-rate_quoted`);
					if ($rate.is(':focus')) return;

					// `average_room_nightly`, not `average_nightly`: this field is the
					// room's own rate and the extra beds are shown and added separately
					// below it. The all-in figure billed the beds twice.
					//
					// Derived from the breakdown when the key is absent, so a server
					// still running a build without it prices the row instead of
					// silently leaving the box empty.
					const room_nights = (q.nights || []).length * Math.max(cint(q.qty) || 1, 1);
					const quoted =
						flt(q.average_room_nightly) ||
						(room_nights ? flt(q.room_total) / room_nights : 0);
					if (!quoted) return;
					if (flt(current.rate_quoted) === flt(quoted)) return;

					current.rate_quoted = flt(quoted, 2);

					// Patched in place rather than redrawn. This callback lands whenever
					// the server answers, which is routinely while the agent is still
					// typing in the same row; render_lines() here replaced the inputs
					// mid-keystroke, so a rate would appear and then vanish on its own.
					$rate.val(current.rate_quoted).removeClass('hcrm-agreed');
					this.refresh_row(i);
					this.refresh_money();
					this.mark_dirty();
					this.update_header();
				})
				.catch(() => {
					this.mark_rate_pending(i, false);
					// Nothing was quoted, so show the category's weekday tariff rather
					// than leaving the box empty. The server reprices on save anyway.
					const current = this.state.doc && this.state.doc.room_lines && this.state.doc.room_lines[i];
					if (!current || current.room_type !== asked_for) return;
					if (cint(current.is_rate_overridden) || flt(current.rate_quoted)) return;
					const t = (this.state.masters.room_types || []).find((x) => x.name === asked_for);
					if (!t) return;
					current.rate_quoted = flt(t.default_rate);
					$(`#hcrm-lines-wrap tbody tr[data-i="${i}"] .l-rate_quoted`).val(current.rate_quoted);
					this.refresh_row(i);
					this.refresh_money();
				});
		},

		/* Repaint the parts of one row that depend on its numbers, without rebuilding it.
		 *
		 * Changing Rooms, Adults or Children changes the amount, whether extra beds are
		 * needed, and whether the party is over capacity. A full redraw would show all
		 * three correctly but would take focus out of the field being typed in, so each
		 * piece is patched in place instead.
		 */
		refresh_row(i) {
			const d = this.state.doc;
			const line = d && d.room_lines && d.room_lines[i];
			const $tr = $(`#hcrm-lines-wrap tbody tr[data-i="${i}"]`);
			if (!line || !$tr.length) return;

			$tr.find('.hcrm-line-amt').text(this.line_amount_text(line));

			const t = (this.state.masters.room_types || []).find((x) => x.name === line.room_type) || {};
			const beds = this.line_extra_beds(line);
			const $type_cell = $tr.find('td').first();

			$type_cell.find('.hcrm-line-beds').remove();
			if (beds.adults || beds.children) {
				$type_cell.append(
					`<div class="hcrm-line-beds" title="${__(
						"Extra beds are charged at this category's rates"
					)}">🛏 ${__('{0} extra bed(s)', [
						beds.adults + beds.children,
					])} &middot; ${format_currency(beds.amount)}</div>`
				);
			}

			const cap = cint(t.max_occupancy) * Math.max(cint(line.qty) || 1, 1);
			const heads = cint(line.adults) + cint(line.children);
			const $adults = $tr.find('.l-adults');
			if (cap && heads > cap) {
				$adults.attr(
					'title',
					__('Over the {0} this category sleeps — extra beds added', [cap])
				);
			} else {
				$adults.removeAttr('title');
			}
		},

		refresh_all_rates() {
			((this.state.doc && this.state.doc.room_lines) || []).forEach((l, i) =>
				this.refresh_line_rate(i)
			);
		},

		quote_subtotal() {
			return ((this.state.doc && this.state.doc.room_lines) || []).reduce(
				(sum, l) => sum + this.line_amount(l),
				0
			);
		},

		/* The discount the agent agreed for the whole quote, and the note that travels
		 * with it to the booking, the reservation and the guest's bill. Mirrors
		 * tariff.apply_discount: never below zero, never negative. */
		quote_discount() {
			const d = this.state.doc || {};
			const subtotal = this.quote_subtotal();
            const value = flt(d.discount_value);
			if (!d.discount_type || value <= 0) return 0;
			const raw =
				d.discount_type === 'Percentage' ? subtotal * (Math.min(value, 100) / 100) : value;
			return Math.max(Math.min(raw, subtotal), 0);
		},

		/* Rendered directly under the room table, which is where an agent settles the
		 * commercials once the rooms are chosen. */
		discount_panel() {
			const d = this.state.doc || {};
			const discount = this.quote_discount();

			return `
				<div class="hcrm-discount">
					<div class="hcrm-discount-row">
						<label>${__('Discount')}</label>
						<select class="form-control input-sm d-discount_type">
							<option value="">${__('None')}</option>
							<option value="Amount"${
								d.discount_type === 'Amount' ? ' selected' : ''
							}>${__('Amount')}</option>
							<option value="Percentage"${
								d.discount_type === 'Percentage' ? ' selected' : ''
							}>${__('Percentage')}</option>
						</select>
						<input type="number" min="0" step="any" class="form-control input-sm d-discount_value"
							value="${d.discount_value || 0}" ${d.discount_type ? '' : 'disabled'}
							placeholder="${d.discount_type === 'Percentage' ? '%' : format_currency(0)}">
						<span class="hcrm-discount-amt">${discount ? `- ${format_currency(discount)}` : ''}</span>
					</div>
					<div class="hcrm-discount-row">
						<label>${__('Remarks')}</label>
						<textarea rows="2" class="form-control input-sm d-remarks" placeholder="${__(
							'Carried to the booking, the reservation and the guest\'s bill'
						)}">${frappe.utils.escape_html(d.remarks || '')}</textarea>
					</div>
					<div class="hcrm-discount-total">
						<span>${__('Quoted Total')}</span>
						<b class="hcrm-total">${format_currency(this.quote_total())}</b>
					</div>
				</div>`;
		},

		quote_total() {
			return this.quote_subtotal() - this.quote_discount();
		},

		/* Update the three money figures in place. A full redraw would take the caret
		 * out of whichever field the agent is typing in. */
		refresh_money() {
			const discount = this.quote_discount();
			$('#hcrm-lines-wrap .hcrm-subtotal').text(format_currency(this.quote_subtotal()));
			$('#hcrm-lines-wrap .hcrm-discount-amt').text(
				discount ? `- ${format_currency(discount)}` : ''
			);
			$('#hcrm-lines-wrap .hcrm-total').text(format_currency(this.quote_total()));
		},

		/* Whether a room is free for the dates on screen, from the availability payload,
		 * and which other open enquiries are offering it. Null when no dates yet. */
		room_state(room) {
			const data = this._availData;
			if (!room || !data || data.error || !data.rooms) return null;
			const r = data.rooms.find((x) => x.name === room);
			const rivals = ((data.contention || {}).by_room || {})[room] || [];
			if (!r) return { free: false, reason: __('Not available'), rivals };
			return { free: !!r.available, reason: r.blocked_by || '', rivals };
		},

		/* Rooms the picker offers: the type filter applied, but a row's own room is
		 * always kept so changing the filter never silently drops a choice. */
		room_choices(current) {
			const filter = this.state.room_filter || '';
			return (this.state.masters.rooms || []).filter(
				(r) => !filter || r.room_type === filter || r.name === current
			);
		},

		add_line() {
			const rooms = this.room_choices();
			if (!rooms.length) {
				frappe.msgprint(__('No rooms are set up for this room type.'));
				return;
			}
			const taken = new Set(((this.state.doc && this.state.doc.room_lines) || []).map((l) => l.room));
			// The first room not already on this enquiry that is free for the dates;
			// failing that, the first one not on it.
			const pick =
				rooms.find((r) => !taken.has(r.name) && (this.room_state(r.name) || { free: true }).free) ||
				rooms.find((r) => !taken.has(r.name)) ||
				rooms[0];
			const type = (this.state.masters.room_types || []).find((x) => x.name === pick.room_type) || {};

			this.state.doc.room_lines = this.state.doc.room_lines || [];
			this.state.doc.room_lines.push({
				room: pick.name,
				room_type: pick.room_type,
				qty: 1,
				adults: 2,
				children: 0,
				// Seeded from the tariff only when the engine cannot be asked. With real
				// dates on screen the weekday tariff would flash into the box and then be
				// replaced by the weekend one, which reads as the rate moving by itself.
				rate_quoted: this.can_quote() ? 0 : type.default_rate || 0,
				is_rate_overridden: 0,
				extra_beds_adult: 0,
				extra_beds_child: 0,
			});
			this.mark_dirty();
			this.render_lines();
			// The seeded rate is the weekday tariff; price it for the actual dates.
			this.refresh_line_rate(this.state.doc.room_lines.length - 1);
			this.update_header();
			this.refresh_availability_need();
		},

		render_lines() {
			const lines = (this.state.doc && this.state.doc.room_lines) || [];
			const types = this.state.masters.room_types || [];

			if (!lines.length) {
				$('#hcrm-lines-wrap').html(
					`<div class="hcrm-empty hcrm-empty-sm">
						<div class="hcrm-empty-hint">${__('No rooms added yet.')}</div>
					</div>`
				);
				return;
			}

			const esc = frappe.utils.escape_html;
			const others = (i) => new Set(lines.filter((_, j) => j !== i).map((x) => x.room).filter(Boolean));

			const rows = lines
				.map((l, i) => {
					// Rooms grouped by type, each marked for the dates on screen.
					const used = others(i);
					const groups = {};
					this.room_choices(l.room).forEach((r) => {
						(groups[r.room_type] = groups[r.room_type] || []).push(r);
					});
					const legacy = !l.room
						? `<option value="" selected>${esc(__('Any {0}', [l.room_type || '']))}${
								cint(l.qty) > 1 ? ' ×' + cint(l.qty) : ''
						  } — ${esc(__('choose a room'))}</option>`
						: '';
					const opts =
						legacy +
						Object.keys(groups)
							.map((type) => {
								const options = groups[type]
									.map((r) => {
										const st = this.room_state(r.name);
										let tag = '';
										if (used.has(r.name)) tag = ' — ' + __('on this enquiry');
										else if (st && !st.free) tag = ' — ' + __('booked');
										else if (st && st.rivals.length) tag = ' — ' + __('also offered ×{0}', [st.rivals.length]);
										else if (st) tag = ' — ' + __('free');
										return `<option value="${esc(r.name)}" ${r.name === l.room ? 'selected' : ''}${
											used.has(r.name) ? ' disabled' : ''
										}>${esc(r.name)}${esc(tag)}</option>`;
									})
									.join('');
								return `<optgroup label="${esc(type)}">${options}</optgroup>`;
							})
							.join('');

					const t = types.find((x) => x.name === l.room_type) || {};
					// What the picked room is, and whether it can be had for these dates.
					const st = this.room_state(l.room);
					let room_warn = '';
					if (l.room && st && !st.free) {
						room_warn = `<div class="hcrm-line-warn">${esc(__('Not free for these dates'))}${
							st.reason ? ' · ' + esc(st.reason) : ''
						}</div>`;
					} else if (l.room && st && st.rivals.length) {
						room_warn = `<div class="hcrm-line-rival">${esc(
							__('Also offered to: {0}', [st.rivals.slice(0, 3).join(', ')])
						)}</div>`;
					}
					const type_line = l.room_type
						? `<div class="hcrm-line-type">${esc(l.room_type)}</div>`
						: '';
					const cap = cint(t.max_occupancy) * Math.max(cint(l.qty) || 1, 1);
					const heads = (cint(l.adults) || 0) + (cint(l.children) || 0);
					const over = cap && heads > cap;
					const amen = (t.amenities || []).map((a) => a.icon).join(' ');
					const meta = [
						t.bedroom_configuration || '',
						t.max_occupancy ? __('Max {0}', [t.max_occupancy]) : '',
						amen,
					].filter(Boolean).join(' &middot; ');
					const wknd = t.has_weekend_premium
						? `<div class="hcrm-line-meta">${__('Weekend')} ${format_currency(t.weekend_rate)}</div>`
						: '';

					// Over capacity is sold with extra beds, so say what it adds rather
					// than flagging it as a mistake.
					const beds = this.line_extra_beds(l);
					const bed_note =
						beds.adults || beds.children
							? `<div class="hcrm-line-beds" title="${__(
									'Extra beds are charged at this category\'s rates'
							  )}">🛏 ${__('{0} extra bed(s)', [
									beds.adults + beds.children,
							  ])} &middot; ${format_currency(beds.amount)}</div>`
							: '';

					return `<tr data-i="${i}">
						<td><select class="form-control input-sm l-room">${opts}</select>
							${type_line}
							${meta ? `<div class="hcrm-line-meta">${meta}</div>` : ''}${wknd}${bed_note}${room_warn}</td>
						<td><input type="number" min="0" class="form-control input-sm l-adults" value="${
							l.adults || 2
						}"${over ? ` title="${__('Over the {0} this category sleeps — extra beds added', [cap])}"` : ''}></td>
						<td><input type="number" min="0" class="form-control input-sm l-children" value="${
							l.children || 0
						}"></td>
						<td><input type="number" min="0" step="any" class="form-control input-sm l-rate_quoted${
							cint(l.is_rate_overridden) ? ' hcrm-agreed' : ''
						}" value="${flt(l.rate_quoted) ? l.rate_quoted : ''}" placeholder="${
							this.can_quote() ? __('Pricing…') : __('Rate')
						}" title="${__(
						'Typing a rate here fixes it for the whole booking cycle. Clear the box to go back to the tariff.'
					)}"></td>
						<td class="num hcrm-line-amt">${this.line_amount_text(l)}</td>
						<td class="hcrm-line-del"><button class="btn btn-xs l-del" title="${__('Remove')}">&times;</button></td>
					</tr>`;
				})
				.join('');

			$('#hcrm-lines-wrap').html(`
				<table class="hcrm-lines">
					<thead><tr>
						<th style="width:40%">${__('Room')}</th>
						<th style="width:12%">${__('Adults')}</th>
						<th style="width:12%">${__('Children')}</th>
						<th style="width:16%">${__('Rate / Night')}</th>
						<th style="width:16%" class="num">${__('Amount')}</th>
						<th style="width:4%"></th>
					</tr></thead>
					<tbody>${rows}</tbody>
					<tfoot><tr>
						<td colspan="4" class="num hcrm-total-label">${__('Subtotal')}</td>
						<td class="num hcrm-subtotal">${format_currency(this.quote_subtotal())}</td>
						<td></td>
					</tr></tfoot>
				</table>
				${this.discount_panel()}
			`);
			this.bind_lines();
		},

		bind_lines() {
			const d = this.state.doc;
			$('#hcrm-lines-wrap')
				.off('input change click wheel')
				// A wheel over a focused number box silently changes it. On Rate/Night
				// that read as a rate the agent had agreed, which locked the line off
				// the tariff — a rate that moved on its own just from scrolling the
				// panel. Drop focus instead, so the wheel scrolls the page.
				.on('wheel', 'input[type=number]', (e) => {
					if ($(e.currentTarget).is(':focus')) e.currentTarget.blur();
				})
				// Document-level commercials, edited below the table.
				.on('input change', '.d-discount_type, .d-discount_value, .d-remarks', (e) => {
					const $el = $(e.currentTarget);
					const key = ($el.attr('class') || '')
						.split(/\s+/)
						.find((c) => c.startsWith('d-'))
						.slice(2);

					d[key] = key === 'discount_value' ? Number($el.val()) : $el.val();

					if (key === 'discount_type') {
						// Changes whether the value input is live, so redraw the panel.
						this.render_lines();
					} else {
						this.refresh_money();
					}
					this.mark_dirty();
					this.update_header();
				})
				.on('input change', 'select, input, textarea', (e) => {
					const $el = $(e.currentTarget);
					const i = $el.closest('tr').data('i');
					const field = ($el.attr('class') || '').split(/\s+/).find((c) => c.startsWith('l-'));
					if (!field || i == null) return;
					const key = field.slice(2);
					const line = d.room_lines[i];

					if (key === 'room') {
						// The room decides the type. A room line is always one room.
						const room = (this.state.masters.rooms || []).find((x) => x.name === $el.val());
						if (!room) return;
						const changed_type = room.room_type !== line.room_type;
						line.room = room.name;
						line.qty = 1;
						if (changed_type) {
							line.room_type = room.room_type;
							const t = (this.state.masters.room_types || []).find((x) => x.name === room.room_type);
							// A rate agreed by hand survives; a tariff rate is re-quoted
							// for the new category.
							if (t && !cint(line.is_rate_overridden)) {
								line.rate_quoted = this.can_quote() ? 0 : flt(t.default_rate);
							}
						}
						this.render_lines();
						if (changed_type) this.refresh_line_rate(i);
						this.mark_dirty();
						this.update_header();
						this.refresh_availability_need();
						return;
					}

					line[key] = key === 'room_type' ? $el.val() : Number($el.val());

					// A rate typed by hand is an agreement with the guest. Flagging it is
					// what stops the server recomputing it back to the tariff on every
					// later save, and it is the flag that travels to the reservation.
					//
					// It is only set on `change`, never on `input`. Flagging every
					// keystroke meant that clearing the box to retype it read as an
					// agreed rate of zero and froze the line there: no later date, room
					// type or headcount change could reprice it, because the tariff stops
					// applying the moment this flag is on.
					if (key === 'rate_quoted') {
						const typed = String($el.val()).trim();
						if (!typed) {
							// An empty box means "go back to the tariff", not "charge zero".
							line.is_rate_overridden = 0;
							line.rate_quoted = 0;
							$el.removeClass('hcrm-agreed');
							if (e.type === 'change') this.refresh_line_rate(i);
						} else if (e.type === 'change') {
							line.is_rate_overridden = 1;
							// Marked in place rather than by redrawing: a re-render
							// mid-keystroke would take the caret out of the field.
							$el.addClass('hcrm-agreed');
						}
					}

					// Switching the room type changes everything the row describes —
					// bed layout, capacity, amenities and tariff — so the row is always
					// redrawn. Previously this only happened when the rate was blank,
					// and since a new row is seeded with one it never happened at all:
					// every row kept showing the first category's "Max" and amenities.
					if (key === 'room_type') {
						const t = (this.state.masters.room_types || []).find(
							(x) => x.name === $el.val()
						);
						// A rate the agent agreed by hand is the one thing that survives
						// the switch; a seeded tariff rate is only a suggestion.
						//
						// `default_rate` is only the weekday tariff, so writing it here
						// flashed a weekday figure into the box on a weekend stay a moment
						// before the real quote replaced it — the rate appearing and then
						// changing on its own. When the engine can be asked, leave the box
						// pending and let the answer fill it; guess only when it cannot.
						if (t && !cint(line.is_rate_overridden)) {
							line.rate_quoted = this.can_quote() ? 0 : flt(t.default_rate);
						}
						this.render_lines();
						this.refresh_line_rate(i);
					} else {
						// Patched in place rather than redrawn, so the caret stays in the
						// field being typed in.
						this.refresh_row(i);
						this.refresh_money();

						// Headcount and quantity both change what the engine charges —
						// per-head pricing and extra beds — so re-ask once the value is
						// committed rather than on every keystroke.
						if (
							e.type === 'change' &&
							(key === 'qty' || key === 'adults' || key === 'children')
						) {
							this.refresh_line_rate(i);
						}
					}
					this.mark_dirty();
					this.update_header();
					if (key === 'room_type' || key === 'qty') this.refresh_availability_need();
				})
				.on('click', '.l-del', (e) => {
					const i = $(e.currentTarget).closest('tr').data('i');
					d.room_lines.splice(i, 1);
					this.mark_dirty();
					this.render_lines();
					this.update_header();
					this.refresh_availability_need();
				});
		},

		// ------------------------------------------------------------------ actions
		save(onDone) {
			if (!this.state.doc) return;
			const payload = this.read_form();

			if (!payload.guest_name || !payload.mobile_no || !payload.source) {
				frappe.msgprint({
					title: __('Missing details'),
					message: __('Guest name, mobile number and source are required.'),
					indicator: 'orange',
				});
				return;
			}

			payload.name = this.state.selected || null;
			delete payload.calls;

			frappe.call({
				method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.save_enquiry',
				args: { payload: JSON.stringify(payload) },
				freeze: true,
				freeze_message: __('Saving…'),
				callback: (r) => {
					if (!r.message) return;
					this.state.doc = r.message;
					this.state.selected = r.message.name;
					this.load_into_form();
					this.clear_dirty();
					frappe.show_alert({ message: __('Saved'), indicator: 'green' });
					this.render_context();
					this.load_queue();
					this.refresh_counts();
					if (typeof onDone === 'function') onDone();
				},
			});
		},

		follow_up_dialog() {
			if (!this.state.selected) {
				frappe.msgprint(__('Save the enquiry before logging a follow-up.'));
				return;
			}
			const dlg = new frappe.ui.Dialog({
				title: __('Log Follow-up'),
				fields: [
					{
						fieldname: 'outcome',
						label: __('Outcome'),
						fieldtype: 'Select',
						reqd: 1,
						options: ['Connected', 'No Answer', 'Callback Requested', 'Quoted', 'Not Interested'],
						default: 'Connected',
					},
					{ fieldname: 'remarks', label: __('Remarks'), fieldtype: 'Small Text' },
					{ fieldname: 'next_follow_up', label: __('Next Follow-up'), fieldtype: 'Datetime' },
				],
				primary_action_label: __('Log'),
				primary_action: (values) => {
					frappe.call({
						method:
							'hospitality_core.hospitality_core.doctype.hotel_enquiry.hotel_enquiry.log_follow_up',
						args: Object.assign({ enquiry: this.state.selected }, values),
						callback: () => {
							dlg.hide();
							frappe.show_alert({ message: __('Follow-up logged'), indicator: 'green' });
							this.open(this.state.selected);
							this.load_queue();
							this.refresh_counts();
						},
					});
				},
			});
			dlg.show();
		},

		enquiry_from_call(call_log) {
			frappe.call({
				method: 'hospitality_core.hospitality_core.api.telephony.create_enquiry_from_call',
				args: { call_log },
				freeze: true,
				callback: (r) => {
					if (!r.message) return;
					this.state.queue = 'mine';
					this.render_tabs();
					this.load_queue();
					this.open(r.message);
					this.refresh_counts();
				},
			});
		},

		refresh_counts() {
			frappe.call({
				method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_queue_counts',
				callback: (r) => {
					if (!r.message) return;
					this.state.masters.counts = r.message;
					this.render_tabs();
				},
			});
		},


		// ------------------------------------------------------------------ availability
		load_availability() {
			const ci = this.controls.check_in_date && this.controls.check_in_date.get_value();
			const co = this.controls.check_out_date && this.controls.check_out_date.get_value();

			if (!ci || !co || frappe.datetime.get_diff(co, ci) <= 0) {
				this._availData = null;
				this._availKey = null;
				$('#hcrm-avail').empty();
				if (!$('#hcrm-lines-wrap').find(':focus').length) this.render_lines();
				return;
			}
			// Cheap guard against re-querying the same window on every keystroke.
			const key = ci + '|' + co + '|' + ((this.state.doc && this.state.doc.name) || '');
			if (this._availKey === key) return;
			this._availKey = key;
			this._availData = null; // stale until the new window comes back

			$('#hcrm-avail').html(
				`<div class="hcrm-avail-loading">${__('Checking availability…')}</div>`
			);
			frappe.call({
				method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_stay_availability',
				args: {
					arrival_date: ci,
					departure_date: co,
					// Without this the enquiry on screen shows up as its own competitor.
					exclude_enquiry: (this.state.doc && this.state.doc.name) || null,
				},
				callback: (r) => {
					if (this._availKey !== key) return; // a newer request won
					this._availData = r.message;
					this.render_availability(r.message);
					// The room picker marks each room free / booked for these dates.
					// Redraw it now — unless the agent is typing in a row, in which case
					// the next redraw picks the marks up.
					if (!$('#hcrm-lines-wrap').find(':focus').length) this.render_lines();
				},
			});
		},

		/* The `need` badges read the room lines, so editing a line makes the strip stale.
		 * The inventory numbers only depend on the dates, so re-render from the payload we
		 * already have rather than asking the server the same question again. */
		refresh_availability_need() {
			if (this._availData) this.render_availability(this._availData);
		},

		render_availability(data) {
			if (!data) return $('#hcrm-avail').empty();
			if (data.error) {
				return $('#hcrm-avail').html(
					`<div class="hcrm-avail-loading">${frappe.utils.escape_html(data.error)}</div>`
				);
			}

			const wanted = {};
			((this.state.doc && this.state.doc.room_lines) || []).forEach((l) => {
				if (l.room_type) wanted[l.room_type] = (wanted[l.room_type] || 0) + (Number(l.qty) || 1);
			});

			const contention = data.contention || { by_type: {}, total: 0, enquiries: [] };

			const cells = data.room_types
				.map((t) => {
					const need = wanted[t.room_type] || 0;
					const rival = contention.by_type[t.room_type];
					let cls = 'ok';
					if (t.free === 0) cls = 'none';
					else if (need && t.free < need) cls = 'short';
					else if (t.free <= 1) cls = 'low';

					const tip = [
						`${t.total} ${__('total')}`,
						`${t.occupied} ${__('booked')}`,
						`${t.held} ${__('held')}`,
						rival ? `${rival.qty} ${__('wanted by other open enquiries')}` : '',
					].filter(Boolean).join(' · ');

					return `<div class="hcrm-avail-cell hcrm-avail-${cls}" title="${tip}">
						<div class="hcrm-avail-n">${t.free}</div>
						<div class="hcrm-avail-t">${frappe.utils.escape_html(t.room_type)}</div>
						${need ? `<div class="hcrm-avail-need">${__('need')} ${need}</div>` : ''}
						${
							rival
								? `<div class="hcrm-avail-rival">${__('{0} also wanted', [rival.qty])}</div>`
								: ''
						}
					</div>`;
				})
				.join('');

			/* Free rooms are a fact; competing enquiries are a warning. They are kept
			 * visually separate because an enquiry does not reduce inventory — quoting
			 * over one is allowed, doing it unknowingly is not. */
			let warning = '';
			if (contention.total) {
				const lines = contention.enquiries
					.map((e) => {
						const who = e.mine ? __('you') : (e.owner || __('unassigned'));
						return `<li>${frappe.utils.escape_html(e.guest_name || e.name)}
							<span class="hcrm-rival-meta">${frappe.utils.escape_html(e.status || '')} ·
							${frappe.utils.escape_html(who)}</span></li>`;
					})
					.join('');
				warning = `
					<div class="hcrm-contention">
						<div class="hcrm-contention-head">
							${__('{0} other open enquiries want these dates', [contention.total])}
						</div>
						<ul class="hcrm-contention-list">${lines}</ul>
					</div>`;
			}

			$('#hcrm-avail').html(`
				<div class="hcrm-avail">
					<div class="hcrm-avail-head">
						${__('Rooms free')} · ${data.nights} ${__('nights')}
					</div>
					<div class="hcrm-avail-row">${cells}</div>
					${warning}
				</div>
			`);
		},

		// ------------------------------------------------------------------ booking
		render_booking_state() {
			const b = this.state.doc && this.state.doc.hotel_booking;
			$('#hcrm-booking-state').html(
				b
					? `<a href="/app/hotel-booking/${encodeURIComponent(b)}" target="_blank"
						 rel="noopener">${__('Booking')} ${frappe.utils.escape_html(b)}</a>`
					: ''
			);
			$('#hcrm-book').text(b ? __('Open Booking') : __('Create Booking'));
		},

		booking_dialog() {
			if (!this.state.doc) return;

			const existing = this.state.doc.hotel_booking;
			if (existing) {
				frappe.set_route('Form', 'Hotel Booking', existing);
				return;
			}
			if (!(this.state.doc.room_lines || []).length) {
				frappe.msgprint(__('Add at least one room before creating a booking.'));
				return;
			}

			// The agent asked to create a booking, not to be told to press Save first.
			// Save any pending edits, then carry straight on into the dialog.
			if (this.state.dirty || !this.state.selected) {
				this.save(() => this.open_booking_dialog());
				return;
			}
			this.open_booking_dialog();
		},

		/* Before booking, look for bookings this guest already has. A caller with a
		 * booking usually wants to change it; booking again left the old room blocked
		 * and the advance recorded twice. */
		open_booking_dialog() {
			if (!this.state.selected) return;
			frappe
				.call({
					method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_live_bookings_for_enquiry',
					args: { enquiry: this.state.selected },
				})
				.then((r) => this._booking_dialog(r.message || []));
		},

		_booking_dialog(existing) {
			const esc = frappe.utils.escape_html;
			const warn = existing.length
				? [
						{
							fieldtype: 'HTML',
							fieldname: 'existing',
							options: `<div class="hcrm-dup-warn">
								<b>${__('This guest already has {0} booking(s)', [existing.length])}</b>
								<ul>${existing
									.map(
										(b) => `<li><a href="/app/hotel-booking/${encodeURIComponent(b.name)}" target="_blank">${esc(b.name)}</a>
											· ${esc(b.rooms || '')} · ${frappe.datetime.str_to_user(b.arrival_date)} → ${frappe.datetime.str_to_user(b.departure_date)}
											· ${esc(b.status)}${flt(b.advance_received) ? ' · ' + __('advance {0}', [format_currency(b.advance_received)]) : ''}${
											b.enquiry ? ` · <a href="#" class="hcrm-dup-open" data-enquiry="${esc(b.enquiry)}">${__('open its enquiry')}</a>` : ''
										}</li>`
									)
									.join('')}</ul>
								${__('To change those dates, open that enquiry and change the dates there (the booking moves with them), or use Change Dates on the booking. Do not take the advance again.')}
							</div>`,
						},
						{
							fieldtype: 'Check',
							fieldname: 'additional_stay',
							label: __('This is a separate, additional stay (not a date change)'),
						},
						{ fieldtype: 'Section Break' },
				  ]
				: [];

			const dlg = new frappe.ui.Dialog({
				title: __('Create Booking'),
				fields: warn.concat([
					{
						fieldname: 'action',
						label: __('Action'),
						fieldtype: 'Select',
						reqd: 1,
						default: 'hold',
						options: [
							{ label: __('Tentative hold (blocks rooms, no payment yet)'), value: 'hold' },
							{ label: __('Confirm now (assigns rooms)'), value: 'confirm' },
						],
					},
					{
						fieldname: 'hold_hours',
						label: __('Hold For (hours)'),
						fieldtype: 'Int',
						default: 24,
						depends_on: "eval:doc.action=='hold'",
					},
					{ fieldname: 'sec', fieldtype: 'Section Break', label: __('Advance (optional)') },
					{ fieldname: 'advance_amount', label: __('Amount'), fieldtype: 'Currency' },
					{
						fieldname: 'mode_of_payment',
						label: __('Mode'),
						fieldtype: 'Link',
						options: 'Mode of Payment',
						depends_on: 'advance_amount',
					},
					{
						fieldname: 'reference_no',
						label: __('Reference / UTR'),
						fieldtype: 'Data',
						depends_on: 'advance_amount',
					},
				]),
				primary_action_label: __('Create'),
				primary_action: (values) => {
					if (existing.length && !values.additional_stay) {
						frappe.msgprint(__('Tick “separate, additional stay” to book again, or change the existing booking instead.'));
						return;
					}
					dlg.hide();
					this.create_booking(values);
				},
			});
			dlg.$wrapper.on('click', '.hcrm-dup-open', (e) => {
				e.preventDefault();
				dlg.hide();
				this.open($(e.currentTarget).data('enquiry'));
			});
			dlg.show();
		},

		create_booking(values) {
			frappe.call({
				method:
					'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.create_booking_from_enquiry',
				args: {
					enquiry: this.state.selected,
					action: values.action,
					hold_hours: values.hold_hours || 24,
					additional_stay: values.additional_stay ? 1 : 0,
				},
				freeze: true,
				freeze_message: __('Creating booking…'),
				callback: (r) => {
					if (!r.message) return;
					const booking = r.message.booking;

					const done = () => {
						frappe.show_alert({
							message: __('Booking {0} created', [booking]),
							indicator: 'green',
						});
						this.open(this.state.selected);
						this.load_queue();
						this.refresh_counts();
					};

					if (values.advance_amount > 0) {
						frappe.call({
							method: 'hospitality_core.hospitality_core.api.advance.record_advance',
							args: {
								booking: booking,
								amount: values.advance_amount,
								mode_of_payment: values.mode_of_payment || 'Cash',
								reference_no: values.reference_no,
							},
							freeze: true,
							freeze_message: __('Recording advance…'),
							callback: done,
						});
					} else {
						done();
					}
				},
			});
		},

		// ------------------------------------------------------------------ context
		render_context() {
			const calls = (this.state.doc && this.state.doc.calls) || [];
			$('#hcrm-call-count').text(calls.length || '');

			if (!calls.length) {
				$('#hcrm-context').html(
					this.empty('call', __('No calls yet'), __('Calls synced from the sales handsets appear here.'))
				);
				return;
			}
			$('#hcrm-context').html(
				`<div class="hcrm-timeline">${calls
					.map((c) => {
						const missed = c.status !== 'Completed';
						const cls = missed ? 'missed' : c.type === 'Incoming' ? 'in' : 'out';
						return `<div class="hcrm-tl-item">
							<div class="hcrm-tl-dot hcrm-call-${cls}"></div>
							<div class="hcrm-tl-body">
								<div class="hcrm-tl-top">
									<span class="hcrm-call-${cls}">${c.type === 'Incoming' ? __('Incoming') : __('Outgoing')}</span>
									<span class="hcrm-tl-dur">${c.duration ? this.duration(c.duration) : ''}</span>
								</div>
								<div class="hcrm-tl-meta">${frappe.utils.escape_html(c.status || '')}${
							c.start_time ? ' · ' + frappe.datetime.str_to_user(c.start_time) : ''
						}</div>
								${
									c.custom_agent
										? `<div class="hcrm-tl-meta">${frappe.utils.escape_html(c.custom_agent)}</div>`
										: ''
								}
							</div>
						</div>`;
					})
					.join('')}</div>`
			);
		},

		duration(seconds) {
			const s = Number(seconds) || 0;
			const m = Math.floor(s / 60);
			return m ? `${m}m ${s % 60}s` : `${s}s`;
		},

		// ------------------------------------------------------------------ board
		/* Presets rather than two date pickers for the common questions. A sales lead
		 * asking "who came in this week" should not have to compute Monday's date. */
		board_presets() {
			const d = frappe.datetime;
			return [
				{ key: 'all', label: __('All') },
				{ key: 'today', label: __('Today'), from: d.now_date(), to: d.now_date() },
				{ key: '7', label: __('Last 7 days'), from: d.add_days(d.now_date(), -6), to: d.now_date() },
				{ key: '30', label: __('Last 30 days'), from: d.add_days(d.now_date(), -29), to: d.now_date() },
				{ key: 'custom', label: __('Custom') },
			];
		},

		render_board_filters() {
			const f = this.state.board_filter || (this.state.board_filter = {
				preset: 'all', date_field: 'enquired', from: null, to: null, room_type: null, room: null,
			});
			const presets = this.board_presets()
				.map(
					(p) => `<button class="hcrm-seg ${p.key === f.preset ? 'active' : ''}"
						data-preset="${p.key}">${frappe.utils.escape_html(p.label)}</button>`
				)
				.join('');

			$('#hcrm-board-filters').html(`
				<div class="hcrm-bf">
					<label class="hcrm-bf-label">${__('Show enquiries by')}</label>
					<select class="hcrm-bf-select" id="hcrm-bf-field">
						<option value="enquired" ${f.date_field === 'enquired' ? 'selected' : ''}>${__('Date enquired')}</option>
						<option value="staying" ${f.date_field === 'staying' ? 'selected' : ''}>${__('Date staying')}</option>
					</select>
					<div class="hcrm-segmented hcrm-bf-presets">${presets}</div>
					<div class="hcrm-bf-custom" ${f.preset === 'custom' ? '' : 'hidden'}>
						<input type="date" class="hcrm-bf-date" id="hcrm-bf-from" value="${f.from || ''}">
						<span class="hcrm-bf-dash">→</span>
						<input type="date" class="hcrm-bf-date" id="hcrm-bf-to" value="${f.to || ''}">
					</div>
					<span class="hcrm-bf-count" id="hcrm-bf-count"></span>
				</div>
				<div class="hcrm-bf-rooms" id="hcrm-bf-rooms"></div>
			`);
			this.render_room_chips();
			this.bind_board_filters();
		},

		bind_board_filters() {
			const $f = $('#hcrm-board-filters').off();
			$f.on('change', '#hcrm-bf-field', (e) => {
				this.state.board_filter.date_field = $(e.currentTarget).val();
				this.load_board();
			});
			$f.on('click', '.hcrm-seg', (e) => {
				const key = $(e.currentTarget).data('preset');
				const preset = this.board_presets().find((p) => p.key === key);
				const f = this.state.board_filter;
				f.preset = key;
				if (key === 'all') { f.from = null; f.to = null; }
				else if (key !== 'custom') { f.from = preset.from; f.to = preset.to; }
				this.render_board_filters();
				// "Custom" only opens the inputs; nothing is filtered until dates are picked.
				if (key !== 'custom' || (f.from && f.to)) this.load_board();
			});
			$f.on('click', '.hcrm-roomchip', (e) => {
				const room = $(e.currentTarget).data('room') || null;
				const f = this.state.board_filter;
				f.room_type = f.room_type === room ? null : room; // clicking the active chip clears it
				this.render_room_chips();
				this.load_board();
			});
			$f.on('change', '#hcrm-bf-room', (e) => {
				this.state.board_filter.room = $(e.currentTarget).val() || null;
				this.load_board();
			});
			$f.on('change', '#hcrm-bf-from, #hcrm-bf-to', () => {
				const f = this.state.board_filter;
				f.from = $('#hcrm-bf-from').val() || null;
				f.to = $('#hcrm-bf-to').val() || null;
				if (f.from || f.to) this.load_board();
			});
		},

		/* Demand chips, not a dropdown: the counts are the answer to "how much is this
		 * room being asked for in these dates", so they have to be readable without
		 * opening anything. Rendered from the last load, which measures demand before
		 * the room filter is applied — otherwise selecting a type would erase the
		 * comparison that makes the row worth looking at. */
		render_room_chips() {
			const f = this.state.board_filter;
			const demand = this.state.room_demand || [];
			if (!demand.length && !(this.state.masters.rooms || []).length) return $('#hcrm-bf-rooms').empty();

			const chips = demand
				.map((d) => {
					const active = f.room_type === d.room_type;
					return `<button class="hcrm-roomchip ${active ? 'active' : ''}"
						data-room="${frappe.utils.escape_html(d.room_type)}"
						title="${__('{0} enquiries want {1} room(s) of this type', [d.enquiries, d.qty])}">
						<span class="hcrm-roomchip-t">${frappe.utils.escape_html(d.room_type)}</span>
						<span class="hcrm-roomchip-n">${d.enquiries}</span>
						<span class="hcrm-roomchip-q">${__('{0} rm', [d.qty])}</span>
					</button>`;
				})
				.join('');

			// A specific room, for "who wants France these dates". Rooms are listed
			// with how many enquiries in view offer each; the type chips narrow it.
			const esc = frappe.utils.escape_html;
			const asked = {};
			(this.state.room_requests || []).forEach((r) => (asked[r.room] = r.enquiries));
			const room_opts = (this.state.masters.rooms || [])
				.filter((r) => !f.room_type || r.room_type === f.room_type || r.name === f.room)
				.map((r) => `<option value="${esc(r.name)}" ${f.room === r.name ? 'selected' : ''}>${esc(r.name)} · ${esc(
					r.room_type
				)}${asked[r.name] ? ` (${asked[r.name]})` : ''}</option>`)
				.join('');

			$('#hcrm-bf-rooms').html(`
				<span class="hcrm-bf-label">${__('Room type')}</span>
				<button class="hcrm-roomchip ${f.room_type ? '' : 'active'}" data-room="">${__('Any')}</button>
				${chips}
				<span class="hcrm-bf-label hcrm-bf-label-room">${__('Room')}</span>
				<select class="hcrm-bf-select" id="hcrm-bf-room">
					<option value="">${__('Any room')}</option>${room_opts}
				</select>
			`);
		},

		load_board() {
			const f = this.state.board_filter || {};
			frappe.call({
				method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_board',
				args: {
					date_field: f.date_field || 'enquired',
					from_date: f.preset === 'all' ? null : f.from,
					to_date: f.preset === 'all' ? null : f.to,
					room_type: f.room_type || null,
					room: f.room || null,
				},
				callback: (r) => r.message && this.render_board(r.message),
			});
		},

		render_board(data) {
			$('#hcrm-board').html(
				data.statuses
					.map((s) => {
						const rows = data.grouped[s.name] || [];
						const color = (s.color || 'gray').toLowerCase();
						return `<div class="hcrm-col" data-status="${frappe.utils.escape_html(s.name)}">
							<div class="hcrm-col-head">
								<span class="hcrm-pill hcrm-c-${color}">${frappe.utils.escape_html(s.name)}</span>
								<span class="hcrm-chip">${rows.length}</span>
							</div>
							<div class="hcrm-col-body">
								${rows.map((row) => this.board_card(row)).join('')}
							</div>
						</div>`;
					})
					.join('')
			);
			this.state.room_demand = data.room_demand || [];
			this.state.room_requests = data.room_requests || [];
			this.render_room_chips();
			$('#hcrm-bf-count').text(
				data.total === undefined
					? ''
					: data.room || data.room_type
					? __('{0} enquiries for {1}', [data.total, data.room || data.room_type])
					: __('{0} enquiries', [data.total])
			);
			this.bind_board();
		},

		/* What an agent triages on: who, what they want, and what it is worth. Budget is
		 * the guest's own number and quote is ours; when both exist they are shown
		 * together, because a quote far above a stated budget is the signal to
		 * renegotiate rather than chase. */
		board_card(row) {
			const esc = frappe.utils.escape_html;
			// The room offered, with its type; a request made by type alone reads "2× Type".
			const rooms = (row.rooms || [])
				.map((r) =>
					r.room
						? `<b>${esc(r.room)}</b> <span class="hcrm-row-type">${esc(r.room_type)}</span>`
						: `${r.qty}× ${esc(r.room_type)}`
				)
				.join(', ');

			const pax = [
				row.adults ? `${row.adults} ${__('ad')}` : '',
				row.children ? `${row.children} ${__('ch')}` : '',
			].filter(Boolean).join(' ');

			const money = [];
			if (row.budget) {
				money.push(
					`<span class="hcrm-row-budget" title="${__('Guest budget')}">${format_currency(row.budget)}</span>`
				);
			}
			if (row.quoted_total) {
				money.push(
					`<span class="hcrm-row-amt" title="${__('Quoted')}">${format_currency(row.quoted_total)}</span>`
				);
			}

			return `<div class="hcrm-card-mini" draggable="true" data-name="${row.name}">
				<div class="hcrm-row-name">${esc(row.guest_name || '')}</div>
				<div class="hcrm-row-meta">${esc(row.mobile_no || '')}</div>
				${
					rooms
						? `<div class="hcrm-row-rooms" title="${__('Rooms requested')}">${rooms}${
								pax ? ` <span class="hcrm-row-pax">· ${pax}</span>` : ''
						  }</div>`
						: ''
				}
				<div class="hcrm-row-foot">
					<span class="hcrm-row-stay">${
						row.check_in_date
							? frappe.datetime.str_to_user(row.check_in_date) +
							  ' · ' + (row.nights || 0) + 'N'
							: __('No dates')
					}</span>
					<span class="hcrm-row-money">${money.join('')}</span>
				</div>
			</div>`;
		},

		bind_board() {
			let dragged = null;
			$('#hcrm-board')
				.off()
				.on('dragstart', '.hcrm-card-mini', (e) => {
					dragged = $(e.currentTarget).data('name');
					$(e.currentTarget).addClass('dragging');
					e.originalEvent.dataTransfer.effectAllowed = 'move';
				})
				.on('dragend', '.hcrm-card-mini', (e) => {
					$(e.currentTarget).removeClass('dragging');
					$('.hcrm-col').removeClass('drop-target');
				})
				.on('dragover', '.hcrm-col', (e) => {
					e.preventDefault();
					$(e.currentTarget).addClass('drop-target');
				})
				.on('dragleave', '.hcrm-col', (e) => $(e.currentTarget).removeClass('drop-target'))
				.on('drop', '.hcrm-col', (e) => {
					e.preventDefault();
					const status = $(e.currentTarget).data('status');
					$('.hcrm-col').removeClass('drop-target');
					if (dragged && status) this.move_card(dragged, status);
					dragged = null;
				})
				.on('dblclick', '.hcrm-card-mini', (e) => {
					const name = $(e.currentTarget).data('name');
					this.toggle_view();
					this.open(name);
				});
		},

		move_card(enquiry, status) {
			const commit = (extra) =>
				frappe.call({
					method: 'hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.set_status',
					args: Object.assign({ enquiry, status }, extra || {}),
					callback: () => {
						frappe.show_alert({ message: __('Moved to {0}', [status]), indicator: 'green' });
						this.load_board();
					},
				});

			// A Lost status needs a reason, so ask rather than letting the save throw.
			if (this.status_type(status) === 'Lost') {
				const dlg = new frappe.ui.Dialog({
					title: __('Why was this lost?'),
					fields: [
						{
							fieldname: 'lost_reason',
							label: __('Lost Reason'),
							fieldtype: 'Select',
							reqd: 1,
							options: this.state.masters.lost_reasons,
						},
						{ fieldname: 'lost_notes', label: __('Notes'), fieldtype: 'Small Text' },
					],
					primary_action_label: __('Save'),
					primary_action: (values) => {
						dlg.hide();
						commit(values);
					},
				});
				dlg.show();
				return;
			}
			commit();
		},

		strip_html(value) {
			return value ? String(value).replace(/<[^>]*>/g, '') : '';
		},
	};

	CRM.init();
	window.hotel_crm = CRM;
};
