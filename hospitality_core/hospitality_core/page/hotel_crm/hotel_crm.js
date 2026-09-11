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
		{ fieldname: 'source', label: __('Source'), fieldtype: 'Link', options: 'Hotel Enquiry Source' },
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
								<span>${__('Rooms Requested')}</span>
								<button class="btn btn-xs btn-default" id="hcrm-add-line">
									${__('Add Room')}
								</button>
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

		line_amount(line) {
			// Mirrors HotelEnquiry.calculate_quote so the number quoted on the call is the
			// number the server stores.
			const nights = Math.max(this.nights(), 1);
			return (Number(line.rate_quoted) || 0) * Math.max(Number(line.qty) || 1, 1) * nights;
		},

		quote_total() {
			return ((this.state.doc && this.state.doc.room_lines) || []).reduce(
				(sum, l) => sum + this.line_amount(l),
				0
			);
		},

		add_line() {
			const types = this.state.masters.room_types || [];
			if (!types.length) {
				frappe.msgprint(__('No Hotel Room Types are set up yet.'));
				return;
			}
			const first = types[0];
			this.state.doc.room_lines = this.state.doc.room_lines || [];
			this.state.doc.room_lines.push({
				room_type: first.name,
				qty: 1,
				adults: 2,
				children: 0,
				rate_quoted: first.default_rate || 0,
			});
			this.mark_dirty();
			this.render_lines();
			this.update_header();
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

			const rows = lines
				.map((l, i) => {
					const opts = types
						.map(
							(t) =>
								`<option value="${frappe.utils.escape_html(t.name)}" ${
									t.name === l.room_type ? 'selected' : ''
								}>${frappe.utils.escape_html(t.name)}</option>`
						)
						.join('');
					return `<tr data-i="${i}">
						<td><select class="form-control input-sm l-room_type">${opts}</select></td>
						<td><input type="number" min="1" class="form-control input-sm l-qty" value="${l.qty || 1}"></td>
						<td><input type="number" min="1" class="form-control input-sm l-adults" value="${l.adults || 2}"></td>
						<td><input type="number" min="0" step="any" class="form-control input-sm l-rate_quoted" value="${
							l.rate_quoted || 0
						}"></td>
						<td class="num hcrm-line-amt">${format_currency(this.line_amount(l))}</td>
						<td class="hcrm-line-del"><button class="btn btn-xs l-del" title="${__('Remove')}">&times;</button></td>
					</tr>`;
				})
				.join('');

			$('#hcrm-lines-wrap').html(`
				<table class="hcrm-lines">
					<thead><tr>
						<th style="width:32%">${__('Room Type')}</th>
						<th style="width:12%">${__('Rooms')}</th>
						<th style="width:12%">${__('Adults')}</th>
						<th style="width:20%">${__('Rate / Night')}</th>
						<th style="width:20%" class="num">${__('Amount')}</th>
						<th style="width:4%"></th>
					</tr></thead>
					<tbody>${rows}</tbody>
					<tfoot><tr>
						<td colspan="4" class="num hcrm-total-label">${__('Quoted Total')}</td>
						<td class="num hcrm-total">${format_currency(this.quote_total())}</td>
						<td></td>
					</tr></tfoot>
				</table>
			`);
			this.bind_lines();
		},

		bind_lines() {
			const d = this.state.doc;
			$('#hcrm-lines-wrap')
				.off('input change click')
				.on('input change', 'select, input', (e) => {
					const $el = $(e.currentTarget);
					const i = $el.closest('tr').data('i');
					const field = ($el.attr('class') || '').split(/\s+/).find((c) => c.startsWith('l-'));
					if (!field || i == null) return;
					const key = field.slice(2);
					d.room_lines[i][key] = key === 'room_type' ? $el.val() : Number($el.val());

					// Choosing a room type pulls its default rate when none was entered.
					if (key === 'room_type' && !d.room_lines[i].rate_quoted) {
						const t = (this.state.masters.room_types || []).find((x) => x.name === $el.val());
						if (t) d.room_lines[i].rate_quoted = t.default_rate;
						this.render_lines();
					} else {
						// Update just the amounts so the input keeps focus while typing.
						$('#hcrm-lines-wrap tbody tr').each((idx, tr) => {
							$(tr).find('.hcrm-line-amt').text(format_currency(this.line_amount(d.room_lines[idx])));
						});
						$('#hcrm-lines-wrap .hcrm-total').text(format_currency(this.quote_total()));
					}
					this.mark_dirty();
					this.update_header();
				})
				.on('click', '.l-del', (e) => {
					const i = $(e.currentTarget).closest('tr').data('i');
					d.room_lines.splice(i, 1);
					this.mark_dirty();
					this.render_lines();
					this.update_header();
				});
		},

		// ------------------------------------------------------------------ actions
		save(onDone) {
			if (!this.state.doc) return;
			const payload = this.read_form();

			if (!payload.guest_name || !payload.mobile_no) {
				frappe.msgprint({
					title: __('Missing details'),
					message: __('Guest name and mobile number are required.'),
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
				$('#hcrm-avail').empty();
				return;
			}
			// Cheap guard against re-querying the same window on every keystroke.
			const key = ci + '|' + co + '|' + ((this.state.doc && this.state.doc.name) || '');
			if (this._availKey === key) return;
			this._availKey = key;

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
					this.render_availability(r.message);
				},
			});
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

		open_booking_dialog() {
			if (!this.state.selected) return;

			const dlg = new frappe.ui.Dialog({
				title: __('Create Booking'),
				fields: [
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
				],
				primary_action_label: __('Create'),
				primary_action: (values) => {
					dlg.hide();
					this.create_booking(values);
				},
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
				preset: 'all', date_field: 'enquired', from: null, to: null, room_type: null,
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
			if (!demand.length) return $('#hcrm-bf-rooms').empty();

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

			$('#hcrm-bf-rooms').html(`
				<span class="hcrm-bf-label">${__('Room requested')}</span>
				<button class="hcrm-roomchip ${f.room_type ? '' : 'active'}" data-room="">${__('Any')}</button>
				${chips}
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
			this.render_room_chips();
			$('#hcrm-bf-count').text(
				data.total === undefined
					? ''
					: data.room_type
					? __('{0} enquiries for {1}', [data.total, data.room_type])
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
			const rooms = (row.rooms || [])
				.map((r) => `${r.qty}× ${esc(r.room_type)}`)
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
