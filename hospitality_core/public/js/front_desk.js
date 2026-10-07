/**
 * Front desk dialogs: Check In, Check Out, Extend Stay, Change Booking Dates.
 *
 * One implementation, used by the reservation form, the booking form, the Hotel POS
 * and the Front Desk Console, so the desk sees the same bill and the same questions
 * wherever it starts from. Each dialog shows the money first (what the stay costs, what
 * has been paid, what the advance covers, what is left) and then performs the whole
 * desk action in one server call — see api/front_desk.py.
 *
 *   frappe.hospitality.stay.check_in(reservation, {on_done})
 *   frappe.hospitality.stay.check_out(reservation, {on_done})
 *   frappe.hospitality.stay.extend(reservation, {on_done})
 *   frappe.hospitality.stay.change_booking_dates(booking, {on_done})
 *   frappe.hospitality.stay.print_bill(folio)
 */
frappe.provide('frappe.hospitality');

(function () {
	const API = 'hospitality_core.hospitality_core.api.front_desk.';
	const BOOKING_API = 'hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking.';

	const esc = (v) => frappe.utils.escape_html(v == null ? '' : String(v));
	const money = (v) => format_currency(flt(v), frappe.defaults.get_default('currency'));
	const day = (v) => (v ? frappe.datetime.str_to_user(v) : '');

	function row(label, value, cls) {
		return `<div class="hfd-row ${cls || ''}"><span>${label}</span><span>${value}</span></div>`;
	}

	function head(s) {
		const g = s.guest_detail || {};
		const vip = ['VIP', 'Blacklisted'].includes(g.guest_type)
			? `<span class="hfd-pill ${g.guest_type === 'VIP' ? 'hfd-pill-vip' : 'hfd-pill-bad'}">${esc(
					g.guest_type
			  )}</span>`
			: '';
		return `<div class="hfd-head">
			<div>
				<div class="hfd-guest">${esc(g.full_name || s.guest)} ${vip}</div>
				<div class="hfd-sub">${esc(g.mobile_no || '')}${
			s.company ? ' · ' + __('Billed to {0}', [esc(s.company)]) : ''
		}</div>
			</div>
			<div class="hfd-room">
				<div class="hfd-room-no">${esc(s.room)}</div>
				<div class="hfd-sub">${esc(s.room_type)}</div>
			</div>
		</div>
		<div class="hfd-stay">
			<span>${day(s.arrival_date)} ${fmt_time(s.check_in_time)} → ${day(s.departure_date)} ${fmt_time(s.check_out_time)}</span>
			<span>${s.nights} ${__('night(s)')}</span>
			<span>${cint(s.adults)} ${__('adult(s)')}${cint(s.children) ? ', ' + cint(s.children) + ' ' + __('child(ren)') : ''}</span>
		</div>
		${g.vip_notes ? `<div class="hfd-note">${esc(g.vip_notes)}</div>` : ''}`;
	}

	function nights_table(nights) {
		if (!nights || !nights.length) return '';
		const rows = nights
			.map(
				(n) => `<tr>
				<td>${day(n.date)} <span class="hfd-tag hfd-${(n.rate_class || '').toLowerCase()}">${esc(
					n.rate_class || ''
				)}</span></td>
				<td class="text-right">${money(n.rate)}</td>
				<td class="text-right">${n.extra_bed ? money(n.extra_bed) : '—'}</td>
				<td class="text-right">${n.discount ? '−' + money(n.discount) : '—'}</td>
				<td class="text-right"><b>${money(n.amount)}</b></td>
			</tr>`
			)
			.join('');
		return `<table class="hfd-table">
			<thead><tr><th>${__('Night')}</th><th class="text-right">${__('Rate')}</th>
			<th class="text-right">${__('Extra bed')}</th><th class="text-right">${__('Discount')}</th>
			<th class="text-right">${__('Amount')}</th></tr></thead>
			<tbody>${rows}</tbody></table>`;
	}

	function bill_table(lines) {
		if (!lines || !lines.length) {
			return `<div class="hfd-empty">${__('Nothing posted to the folio yet.')}</div>`;
		}
		const rows = lines
			.map((l) => {
				const credit = l.kind !== 'charge';
				return `<tr class="hfd-${l.kind}">
					<td>${day(l.posting_date)}</td>
					<td>${esc(l.description || l.item)}</td>
					<td class="text-right">${credit ? '−' + money(Math.abs(l.amount)) : money(l.amount)}</td>
				</tr>`;
			})
			.join('');
		return `<table class="hfd-table"><tbody>${rows}</tbody></table>`;
	}

	function load(reservation) {
		return frappe
			.call({ method: API + 'get_stay_summary', args: { reservation }, freeze: true })
			.then((r) => r.message);
	}

	/** "16:00:00" -> "4:00 PM". Stay times come from Hospitality Accounting Settings. */
	const fmt_time = (v) => {
		if (!v) return '';
		const [h, m] = String(v).split(':').map((x) => parseInt(x, 10) || 0);
		const ap = h >= 12 ? 'PM' : 'AM';
		return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${ap}`;
	};

	const stay = (frappe.hospitality.stay = {
		fmt_time,

		// ---------------------------------------------------------------- check-in
		check_in(reservation, opts = {}) {
			load(reservation).then((s) => {
				if (s.status !== 'Reserved') {
					frappe.msgprint(__('This stay is {0}; only a Reserved stay can be checked in.', [s.status]));
					return;
				}
				if (!s.can_check_in) {
					frappe.msgprint(
						__('Arrival is {0}. A guest can be checked in from the arrival date.', [day(s.arrival_date)])
					);
					return;
				}
				const g = s.guest_detail || {};
				const est = s.stay_estimate_total;
				const after_advance = Math.max(est - flt(s.unapplied_advance), 0);

				const summary = `${head(s)}
					<div class="hfd-section">${__('Stay charges (posted night by night)')}</div>
					${nights_table(s.stay_estimate)}
					<div class="hfd-totals">
						${row(__('Estimated stay total'), money(est))}
						${s.unapplied_advance ? row(__('Advance paid — applied now'), '−' + money(s.unapplied_advance), 'hfd-good') : ''}
						${row(__('Estimated balance at check-out'), money(after_advance), 'hfd-big')}
					</div>`;

				const d = new frappe.ui.Dialog({
					title: __('Check In · {0}', [s.room]),
					size: 'large',
					fields: [
						{ fieldtype: 'HTML', fieldname: 'summary', options: summary },
						{ fieldtype: 'Section Break', label: __('Guest identity') },
						{
							fieldtype: 'Select',
							fieldname: 'id_type',
							label: __('ID Type'),
							options: ['', 'Aadhaar Card', 'PAN Card', 'Voter ID', 'Driving License', 'Passport', 'Other'].join('\n'),
							default: g.identification_type || 'Aadhaar Card',
						},
						{
							fieldtype: 'Data',
							fieldname: 'id_number',
							label: __('ID Number'),
							default: g.identification_no || g.aadhaar_number || '',
						},
						{ fieldtype: 'Column Break' },
						{ fieldtype: 'Data', fieldname: 'mobile_no', label: __('Mobile'), default: g.mobile_no || '' },
						{ fieldtype: 'Section Break', label: __('Collect a payment now (optional)') },
						{ fieldtype: 'Currency', fieldname: 'payment_amount', label: __('Amount'), default: 0 },
						{ fieldtype: 'Column Break' },
						{
							fieldtype: 'Link',
							fieldname: 'mode_of_payment',
							label: __('Mode of Payment'),
							options: 'Mode of Payment',
							default: 'Cash',
						},
						{ fieldtype: 'Data', fieldname: 'reference_no', label: __('Reference / UTR') },
					],
					primary_action_label: __('Check In'),
					primary_action(values) {
						frappe.call({
							method: API + 'check_in',
							args: Object.assign({ reservation }, values),
							freeze: true,
							freeze_message: __('Checking in…'),
						}).then((r) => {
							if (!r.message) return;
							d.hide();
							let msg = __('{0} checked in to {1}', [g.full_name || s.guest, s.room]);
							if (flt(r.message.advance_applied)) {
								msg += ' · ' + __('advance {0} applied', [money(r.message.advance_applied)]);
							}
							frappe.show_alert({ message: msg, indicator: 'green' }, 6);
							opts.on_done && opts.on_done(r.message);
						});
					},
				});
				d.show();
			});
		},

		// ---------------------------------------------------------------- check-out
		check_out(reservation, opts = {}) {
			load(reservation).then((s) => {
				if (s.status !== 'Checked In') {
					frappe.msgprint(__('This stay is {0}; only a checked-in guest can check out.', [s.status]));
					return;
				}
				const f = s.folio || {};
				const company = !!s.is_company_guest;
				const early = s.early_departure
					? `<div class="hfd-warn">${__(
							'Early departure: booked until {0}. The stay is shortened to today and the remaining nights are not charged.',
							[day(s.departure_date)]
					  )}</div>`
					: s.checkout_pending
					? `<div class="hfd-note">${__(
							'Stay ended {0} at {1}. No extra nights are charged for checking out late, and the room is already free for the next guest.',
							[day(s.departure_date), fmt_time(s.check_out_time)]
					  )}</div>`
					: '';
				const refund = s.refund_due
					? `<div class="hfd-note">${__(
							'The guest has {0} in credit after this bill. Refund it from the folio (Issue Refund) after check-out, or it stays on the guest\'s balance for a future stay.',
							[money(s.refund_due)]
					  )}</div>`
					: '';
				const summary = `${head(s)}${early}
					<div class="hfd-section">${__('Bill')}</div>
					${bill_table(s.lines)}
					<div class="hfd-totals">
						${row(__('Charges'), money(f.total_charges))}
						${flt(f.total_discounts) ? row(__('Discounts'), '−' + money(f.total_discounts)) : ''}
						${row(__('Paid / advance applied'), '−' + money(f.total_payments), 'hfd-good')}
						${s.unapplied_advance ? row(__('Advance still on the booking — applied now'), '−' + money(s.unapplied_advance), 'hfd-good') : ''}
						${row(company ? __('Balance (billed to company)') : __('To collect'), money(s.to_collect), 'hfd-big')}
					</div>${refund}`;

				const d = new frappe.ui.Dialog({
					title: __('Check Out · {0}', [s.room]),
					size: 'large',
					fields: [
						{ fieldtype: 'HTML', fieldname: 'summary', options: summary },
						{ fieldtype: 'Section Break', label: __('Settle') },
						{
							fieldtype: 'Currency',
							fieldname: 'payment_amount',
							label: __('Amount received now'),
							default: company ? 0 : s.to_collect,
						},
						{ fieldtype: 'Column Break' },
						{
							fieldtype: 'Link',
							fieldname: 'mode_of_payment',
							label: __('Mode of Payment'),
							options: 'Mode of Payment',
							default: 'Cash',
						},
						{ fieldtype: 'Data', fieldname: 'reference_no', label: __('Reference / UTR') },
						{ fieldtype: 'Section Break' },
						{
							fieldtype: 'Check',
							fieldname: 'make_invoice',
							label: __('Create the GST Sales Invoice'),
							default: 1,
							description: __('Books the stay\'s revenue and GST and allocates the payments against it.'),
						},
					],
					primary_action_label: __('Settle & Check Out'),
					primary_action(values) {
						if (!company && flt(values.payment_amount) + 0.01 < flt(s.to_collect)) {
							frappe.msgprint(
								__('{0} is still due. Collect it before checking out.', [money(s.to_collect - flt(values.payment_amount))])
							);
							return;
						}
						frappe.call({
							method: API + 'check_out',
							args: Object.assign({ reservation }, values),
							freeze: true,
							freeze_message: __('Checking out…'),
						}).then((r) => {
							if (!r.message) return;
							d.hide();
							stay._after_checkout(r.message, s);
							opts.on_done && opts.on_done(r.message);
						});
					},
				});
				d.show();
			});
		},

		_after_checkout(res, s) {
			const inv = res.invoice
				? `<p>${__('Sales Invoice')} <a href="/app/sales-invoice/${encodeURIComponent(res.invoice)}">${esc(
						res.invoice
				  )}</a> ${__('created and paid.')}</p>`
				: res.invoice_error
				? `<div class="hfd-warn">${__('The guest is checked out, but the invoice could not be created: {0}', [
						esc(res.invoice_error),
				  ])}<br>${__('Fix the setting and use Create Invoice on the folio.')}</div>`
				: '';
			const d = new frappe.ui.Dialog({
				title: __('Checked out'),
				fields: [
					{
						fieldtype: 'HTML',
						options: `<p><b>${esc((s.guest_detail || {}).full_name || s.guest)}</b> ${__(
							'has checked out of'
						)} <b>${esc(s.room)}</b>. ${__('The room is free again.')}</p>${inv}`,
					},
				],
				primary_action_label: __('Print Bill'),
				primary_action() {
					stay.print_bill(res.folio && res.folio.name);
				},
				secondary_action_label: res.invoice ? __('Print Invoice') : null,
				secondary_action: res.invoice
					? () => window.open(`/printview?doctype=Sales%20Invoice&name=${encodeURIComponent(res.invoice)}&trigger_print=1`)
					: null,
			});
			d.show();
		},

		print_bill(folio) {
			if (!folio) return;
			window.open(
				`/printview?doctype=Guest%20Folio&name=${encodeURIComponent(folio)}` +
					`&format=${encodeURIComponent('Guest Folio Classic')}&trigger_print=1`
			);
		},

		// ---------------------------------------------------------------- extend
		/** Kept for existing buttons: the Change Dates dialog with one night added. */
		extend(reservation, opts = {}) {
			stay.change_dates(reservation, Object.assign({ extend: true }, opts));
		},

		// ---------------------------------------------------------------- payment
		/** Money for a stay: an advance before arrival, a folio payment after. */
		take_payment(target, opts = {}) {
			const args = typeof target === 'string' ? { reservation: target } : target;
			const d = new frappe.ui.Dialog({
				title: __('Take Payment'),
				fields: [
					{
						fieldtype: 'HTML',
						options: `<p class="text-muted small">${
							opts.due != null ? __('Balance due: {0}', [money(opts.due)]) + ' · ' : ''
						}${__('Before check-in this is held as an advance; after check-in it goes on the guest\'s bill.')}</p>`,
					},
					{ fieldtype: 'Currency', fieldname: 'amount', label: __('Amount'), reqd: 1,
					  default: opts.due > 0 ? opts.due : null },
					{ fieldtype: 'Link', fieldname: 'mode_of_payment', label: __('Mode of Payment'),
					  options: 'Mode of Payment', reqd: 1, default: 'Cash' },
					{ fieldtype: 'Data', fieldname: 'reference_no', label: __('Reference / UTR') },
				],
				primary_action_label: __('Record Payment'),
				primary_action(values) {
					frappe.call({
						method: API + 'take_payment',
						args: Object.assign({}, args, values),
						freeze: true,
					}).then((r) => {
						if (!r.message) return;
						d.hide();
						frappe.show_alert({ message: __('Payment of {0} recorded', [money(values.amount)]), indicator: 'green' });
						opts.on_done && opts.on_done(r.message);
					});
				},
			});
			d.show();
		},

		refund(reservation, opts = {}) {
			const d = new frappe.ui.Dialog({
				title: __('Refund'),
				fields: [
					{ fieldtype: 'HTML', options: `<p class="text-muted small">${__('Pays back the guest\'s credit from the room bill.')}</p>` },
					{ fieldtype: 'Currency', fieldname: 'amount', label: __('Amount'), reqd: 1, default: opts.credit || null },
				],
				primary_action_label: __('Refund'),
				primary_action(values) {
					frappe.call({ method: API + 'refund', args: { reservation, amount: values.amount }, freeze: true })
						.then((r) => {
							d.hide();
							frappe.show_alert({ message: __('Refund recorded'), indicator: 'green' });
							opts.on_done && opts.on_done(r.message);
						});
				},
			});
			d.show();
		},

		// ---------------------------------------------------------------- charges
		add_charge(reservation, opts = {}) {
			const d = new frappe.ui.Dialog({
				title: __('Add Charge'),
				fields: [
					{ fieldtype: 'Data', fieldname: 'description', label: __('What for'), reqd: 1,
					  description: __('Shown on the bill, e.g. "Dinner 27 Sep", "Laundry", "Airport pickup".') },
					{ fieldtype: 'Currency', fieldname: 'amount', label: __('Amount (incl. GST)'), reqd: 1 },
					{ fieldtype: 'Column Break' },
					{ fieldtype: 'Float', fieldname: 'qty', label: __('Quantity'), default: 1 },
					{ fieldtype: 'Link', fieldname: 'item', label: __('Item (optional)'), options: 'Item',
					  description: __('Leave blank for "Extra Service".') },
				],
				primary_action_label: __('Add to Bill'),
				primary_action(values) {
					frappe.call({ method: API + 'add_charge', args: Object.assign({ reservation }, values), freeze: true })
						.then((r) => {
							if (!r.message) return;
							d.hide();
							frappe.show_alert({ message: __('Added to the bill'), indicator: 'green' });
							opts.on_done && opts.on_done(r.message);
						});
				},
			});
			d.show();
		},

		// ---------------------------------------------------------------- dates
		/** Extend, shorten or move a stay. In house: departure only. */
		change_dates(reservation, opts = {}) {
			frappe.db.get_value('Hotel Reservation', reservation, ['arrival_date', 'departure_date', 'status', 'room'])
				.then((r) => {
					const res = r.message || {};
					const in_house = res.status === 'Checked In';
					const d = new frappe.ui.Dialog({
						title: __('Change Dates · {0}', [res.room]),
						fields: [
							{ fieldtype: 'Date', fieldname: 'arrival_date', label: __('Arrival'), reqd: 1,
							  default: res.arrival_date, read_only: in_house ? 1 : 0, onchange: () => preview() },
							{ fieldtype: 'Column Break' },
							{ fieldtype: 'Date', fieldname: 'departure_date', label: __('Departure'), reqd: 1,
							  default: opts.extend ? frappe.datetime.add_days(res.departure_date, 1) : res.departure_date,
							  onchange: () => preview() },
							{ fieldtype: 'Section Break' },
							{ fieldtype: 'HTML', fieldname: 'quick' },
							{ fieldtype: 'HTML', fieldname: 'preview' },
						],
						primary_action_label: __('Save Dates'),
						primary_action(values) {
							frappe.call({ method: API + 'change_stay_dates', args: Object.assign({ reservation }, values), freeze: true })
								.then((r2) => {
									if (!r2.message) return;
									d.hide();
									frappe.show_alert({
										message: __('Dates saved: {0} → {1}', [day(values.arrival_date), day(values.departure_date)]),
										indicator: 'green',
									});
									opts.on_done && opts.on_done(r2.message);
								});
						},
					});
					// One-tap extensions, the most common request at the desk.
					d.fields_dict.quick.$wrapper.html(
						`<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">${[1, 2, 3]
							.map((n) => `<button class="btn btn-xs btn-default" data-n="${n}">+${n} ${__('night')}${n > 1 ? 's' : ''}</button>`)
							.join('')}</div>`
					);
					d.fields_dict.quick.$wrapper.on('click', 'button', (e) => {
						d.set_value('departure_date', frappe.datetime.add_days(res.departure_date, cint($(e.currentTarget).data('n'))));
					});
					const preview = () => {
						const a = d.get_value('arrival_date');
						const dep = d.get_value('departure_date');
						const $p = d.fields_dict.preview.$wrapper;
						if (!a || !dep) return $p.html('');
						frappe.call({ method: API + 'preview_date_change', args: { reservation, arrival_date: a, departure_date: dep } })
							.then((p) => {
								const x = p.message;
								if (!x) return;
								d.get_primary_btn().prop('disabled', !x.free);
								const diff = flt(x.difference);
								$p.html(
									(x.free ? '' : `<div class="hfd-warn">${esc(x.reason)}</div>`) +
									(x.new_room ? `<div class="hfd-note">${__('{0} is taken on those dates; the guest will be moved to {1}.', [esc(x.room), esc(x.new_room)])}</div>` : '') +
									nights_table(x.nights_changed) +
									`<div class="hfd-totals">
										${row(__('Now'), `${day(x.current.arrival)} → ${day(x.current.departure)} · ${x.current.nights} ${__('night(s)')} · ${money(x.current.total)}`)}
										${row(__('New'), `${day(x.new.arrival)} → ${day(x.new.departure)} · ${x.new.nights} ${__('night(s)')} · ${money(x.new.total)}`)}
										${row(__('Difference'), (diff >= 0 ? '+' : '−') + money(Math.abs(diff)), 'hfd-big ' + (diff > 0 ? 'hfd-bad' : 'hfd-good'))}
									</div>`
								);
							})
							.catch(() => d.get_primary_btn().prop('disabled', true));
					};
					d.show();
					preview();
				});
		},

		// ---------------------------------------------------------------- rooms
		move_room(reservation, opts = {}) {
			frappe.call({ method: API + 'get_move_options', args: { reservation } }).then((r) => {
				const rooms = r.message || [];
				if (!rooms.length) {
					frappe.msgprint(__('No other room is free for the rest of this stay.'));
					return;
				}
				const d = new frappe.ui.Dialog({
					title: __('Move Room'),
					fields: [
						{
							fieldtype: 'Select', fieldname: 'new_room', label: __('Move to'), reqd: 1,
							options: rooms.map((o) => ({
								value: o.room,
								label: `${o.room} · ${o.room_type}${o.same_type ? '' : ' (' + __('different type') + ')'} · ${money(o.rate)}/${__('night')}`,
							})),
						},
						{ fieldtype: 'HTML', options: `<p class="text-muted small">${__('Nights already charged stay as they are. Later nights are charged at the new room\'s rate.')}</p>` },
					],
					primary_action_label: __('Move'),
					primary_action(values) {
						frappe.call({ method: API + 'move_room', args: { reservation, new_room: values.new_room }, freeze: true })
							.then((r2) => {
								if (!r2.message) return;
								d.hide();
								frappe.show_alert({ message: __('Moved to {0}', [r2.message.room]), indicator: 'green' });
								opts.on_done && opts.on_done(r2.message);
							});
					},
				});
				d.show();
			});
		},

		// ---------------------------------------------------------------- cancel
		cancel(reservation, opts = {}) {
			const d = new frappe.ui.Dialog({
				title: __('Cancel Stay'),
				fields: [
					{ fieldtype: 'Small Text', fieldname: 'reason', label: __('Reason'), reqd: 1 },
					{ fieldtype: 'Currency', fieldname: 'cancellation_charge', label: __('Cancellation charge kept from the advance'),
					  description: __('Leave 0 to keep nothing. The rest of the advance can then be refunded from the booking folio.') },
				],
				primary_action_label: __('Cancel Stay'),
				primary_action(values) {
					frappe.call({ method: API + 'cancel_stay', args: Object.assign({ reservation }, values), freeze: true })
						.then((r) => {
							if (!r.message) return;
							d.hide();
							frappe.show_alert({ message: __('Cancelled; the room is free again'), indicator: 'orange' });
							opts.on_done && opts.on_done(r.message);
						});
				},
			});
			d.get_primary_btn().removeClass('btn-primary').addClass('btn-danger');
			d.show();
		},

		// ---------------------------------------------------------------- booking dates
		change_booking_dates(booking, opts = {}) {
			frappe.db.get_value('Hotel Booking', booking, ['arrival_date', 'departure_date', 'total_amount']).then((r) => {
				const b = r.message || {};
				const d = new frappe.ui.Dialog({
					title: __('Change Dates · {0}', [booking]),
					fields: [
						{
							fieldtype: 'Date', fieldname: 'arrival_date', label: __('Arrival'), reqd: 1,
							default: b.arrival_date, onchange: () => preview(),
						},
						{ fieldtype: 'Column Break' },
						{
							fieldtype: 'Date', fieldname: 'departure_date', label: __('Departure'), reqd: 1,
							default: b.departure_date, onchange: () => preview(),
						},
						{ fieldtype: 'Section Break' },
						{ fieldtype: 'HTML', fieldname: 'preview' },
					],
					primary_action_label: __('Change Dates'),
					primary_action(values) {
						frappe.call({
							method: BOOKING_API + 'change_booking_dates',
							args: Object.assign({ booking }, values),
							freeze: true,
						}).then((r2) => {
							if (!r2.message) return;
							d.hide();
							let msg = __('Dates changed. New total {0}', [money(r2.message.total_amount)]);
							if ((r2.message.moved || []).length) {
								msg += ' · ' + __('rooms reassigned: {0}', [r2.message.moved.join(', ')]);
							}
							frappe.show_alert({ message: msg, indicator: 'green' }, 8);
							opts.on_done && opts.on_done(r2.message);
						});
					},
				});
				const preview = () => {
					const a = d.get_value('arrival_date');
					const dep = d.get_value('departure_date');
					const $p = d.fields_dict.preview.$wrapper;
					if (!a || !dep || dep <= a) return $p.html('');
					frappe
						.call({ method: BOOKING_API + 'preview_booking_dates', args: { booking, arrival_date: a, departure_date: dep } })
						.then((p) => {
							const x = p.message;
							if (!x) return;
							const diff = flt(x.difference);
							$p.html(`<div class="hfd-totals">
								${row(__('Nights'), x.nights)}
								${row(__('Current total'), money(x.previous_total))}
								${row(__('New total'), money(x.new_total), 'hfd-big')}
								${row(__('Difference'), (diff >= 0 ? '+' : '−') + money(Math.abs(diff)), diff > 0 ? 'hfd-bad' : 'hfd-good')}
								${row(__('Advance received'), money(x.advance_received))}
								${row(__('New balance due'), money(x.new_balance))}
							</div>`);
						})
						.catch(() => $p.html(''));
				};
				d.show();
				preview();
			});
		},
	});
})();
