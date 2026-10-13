/**
 * Sales Dashboard — the owner's view of the business for any period.
 *
 * Earned (revenue by night), collected (money in, by mode of payment), advances
 * (received, applied, held now) and what is owed right now, each compared with the
 * previous period of the same length. All figures come from
 * api/sales_dashboard.get_dashboard, which the Hotel Sales Report also uses, so the
 * two always agree.
 */
frappe.pages['sales-dashboard'].on_page_load = function (wrapper) {
	frappe.ui.make_app_page({ parent: wrapper, title: __('Sales Dashboard'), single_column: true });
	$(wrapper).find('.page-head').hide();
	const board = new SalesDashboard(wrapper);
	wrapper.sales_dashboard = board;
};

frappe.pages['sales-dashboard'].on_page_show = function (wrapper) {
	if (wrapper.sales_dashboard) wrapper.sales_dashboard.apply_route();
};

class SalesDashboard {
	constructor(wrapper) {
		this.wrapper = wrapper;
		this.$root = $('<div class="sdb"><div class="sdb-wrap"></div></div>').appendTo(
			$(wrapper).find('.layout-main-section')
		);
		this.$w = this.$root.find('.sdb-wrap');
		this.preset = 'last7';
		this.range = this.preset_range('last7');
		this.data = null;
		this.build();
		this.apply_route();
		$(window).on(
			'resize.sdb',
			frappe.utils.debounce(() => this.data && this.render_trend(), 150)
		);
		// The chart reads colours from CSS; redraw when the desk theme flips.
		new MutationObserver(() => this.data && this.render_trend()).observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['data-theme'],
		});
	}

	// ------------------------------------------------------------ periods
	presets() {
		return [
			['today', __('Today')],
			['yesterday', __('Yesterday')],
			['week', __('This week')],
			['last7', __('Last 7 days')],
			['month', __('This month')],
			['lastmonth', __('Last month')],
			['last30', __('Last 30 days')],
			['custom', __('Custom')],
		];
	}

	preset_range(key) {
		const d = frappe.datetime;
		const today = d.get_today();
		const dt = new Date(today + 'T00:00:00');
		const iso = (x) => x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0') + '-' + String(x.getDate()).padStart(2, '0');
		switch (key) {
			case 'today':
				return [today, today];
			case 'yesterday':
				return [d.add_days(today, -1), d.add_days(today, -1)];
			case 'week': {
				const back = (dt.getDay() + 6) % 7; // Monday start
				return [d.add_days(today, -back), today];
			}
			case 'month':
				return [iso(new Date(dt.getFullYear(), dt.getMonth(), 1)), today];
			case 'lastmonth':
				return [
					iso(new Date(dt.getFullYear(), dt.getMonth() - 1, 1)),
					iso(new Date(dt.getFullYear(), dt.getMonth(), 0)),
				];
			case 'last30':
				return [d.add_days(today, -29), today];
			case 'last7':
			default:
				return [d.add_days(today, -6), today];
		}
	}

	apply_route() {
		const o = frappe.route_options || {};
		frappe.route_options = null;
		if (o.from_date && o.to_date) {
			this.preset = 'custom';
			this.range = [o.from_date, o.to_date];
			this.render_filters();
		}
		this.load();
	}

	// ------------------------------------------------------------ layout
	build() {
		this.$w.html(`
			<div class="sdb-head">
				<div>
					<h1 class="sdb-title">${__('Sales')}</h1>
					<div class="sdb-sub" id="sdb-period"></div>
				</div>
				<div class="sdb-filters" id="sdb-filters"></div>
			</div>
			<div class="sdb-hero" id="sdb-hero"></div>
			<div class="sdb-kpis" id="sdb-kpis"></div>
			<div class="sdb-g2">
				<div class="sdb-card">
					<div class="sdb-card-h">
						<span class="sdb-card-t">${__('Revenue and collections by day')}</span>
						<span class="sdb-legend">
							<span><i style="background:var(--sdb-s1)"></i>${__('Revenue earned')}</span>
							<span><i style="background:var(--sdb-s2)"></i>${__('Money collected')}</span>
						</span>
					</div>
					<div class="sdb-chart" id="sdb-trend"></div>
				</div>
				<div class="sdb-card" id="sdb-position"></div>
			</div>
			<div class="sdb-card" id="sdb-modes"></div>
			<div class="sdb-g3">
				<div class="sdb-card" id="sdb-types"></div>
				<div class="sdb-card" id="sdb-sources"></div>
				<div class="sdb-card" id="sdb-breakdown"></div>
			</div>
			<div class="sdb-g2e">
				<div class="sdb-card" id="sdb-held"></div>
				<div class="sdb-card" id="sdb-bookings"></div>
			</div>
			<div class="sdb-card" id="sdb-register"></div>
		`);
		this.render_filters();
	}

	render_filters() {
		const segs = this.presets()
			.map(([k, l]) => `<button type="button" data-p="${k}" class="${k === this.preset ? 'active' : ''}">${l}</button>`)
			.join('');
		$('#sdb-filters').html(`
			<div class="sdb-seg" role="group" aria-label="${__('Period')}">${segs}</div>
			<span class="sdb-custom" ${this.preset === 'custom' ? '' : 'hidden'}>
				<input type="date" id="sdb-from" value="${this.range[0]}" aria-label="${__('From')}">
				<span class="sdb-card-n">→</span>
				<input type="date" id="sdb-to" value="${this.range[1]}" aria-label="${__('To')}">
			</span>
			<button type="button" class="sdb-btn" id="sdb-report">${__('Detailed report')}</button>
		`);
		const $f = $('#sdb-filters');
		$f.find('.sdb-seg button').on('click', (e) => {
			const p = $(e.currentTarget).data('p');
			this.preset = p;
			if (p !== 'custom') this.range = this.preset_range(p);
			this.render_filters();
			if (p !== 'custom') this.load();
		});
		$f.find('#sdb-from, #sdb-to').on('change', () => {
			const a = $('#sdb-from').val();
			const b = $('#sdb-to').val();
			if (a && b) {
				this.range = a <= b ? [a, b] : [b, a];
				this.load();
			}
		});
		$f.find('#sdb-report').on('click', () => {
			frappe.route_options = {
				from_date: this.range[0],
				to_date: this.range[1],
				group_by: frappe.datetime.get_diff(this.range[1], this.range[0]) > 62 ? 'Week' : 'Day',
			};
			frappe.set_route('query-report', 'Hotel Sales Report');
		});
	}

	load() {
		this.$w.addClass('sdb-loading');
		frappe
			.call({
				method: 'hospitality_core.hospitality_core.api.sales_dashboard.get_dashboard',
				args: { from_date: this.range[0], to_date: this.range[1] },
			})
			.then((r) => {
				this.$w.removeClass('sdb-loading');
				if (!r.message) return;
				this.data = r.message;
				this.render();
			})
			.catch(() => this.$w.removeClass('sdb-loading'));
	}

	// ------------------------------------------------------------ formatting
	money(v) {
		return format_currency(flt(v), this.data.currency, 0);
	}

	/* Indian short form for axis ticks: 12.5K, 3.4L, 1.2Cr. */
	short(v) {
		const a = Math.abs(v);
		const sym = (frappe.boot.sysdefaults && frappe.boot.sysdefaults.currency === 'INR') || this.data.currency === 'INR' ? '₹' : '';
		const trim = (n) => String(parseFloat(n.toFixed(2)));
		if (a >= 1e7) return sym + trim(v / 1e7) + 'Cr';
		if (a >= 1e5) return sym + trim(v / 1e5) + 'L';
		if (a >= 1e3) return sym + trim(v / 1e3) + 'K';
		return sym + Math.round(v);
	}

	day(d, long) {
		const x = new Date(d + 'T00:00:00');
		return x.toLocaleDateString(undefined, long ? { day: 'numeric', month: 'short', year: 'numeric' } : { day: 'numeric', month: 'short' });
	}

	/* Change against the previous period: arrow + percent, coloured good/bad with the
	 * arrow and the words carrying the meaning, never colour alone. */
	delta(cur, prev, higher_is_good = true) {
		cur = flt(cur);
		prev = flt(prev);
		if (!prev && !cur) return `<span class="sdb-delta">— <span class="sdb-vs">${__('no change')}</span></span>`;
		if (!prev) return `<span class="sdb-delta up">▲ ${__('new')} <span class="sdb-vs">${__('vs previous')}</span></span>`;
		const pct = ((cur - prev) / Math.abs(prev)) * 100;
		const up = pct >= 0;
		const good = up === higher_is_good;
		const cls = Math.abs(pct) < 0.05 ? '' : good ? 'up' : 'down';
		return `<span class="sdb-delta ${cls}" title="${__('Previous period')}: ${frappe.utils.escape_html(String(prev))}">${
			up ? '▲' : '▼'
		} ${Math.abs(pct).toFixed(Math.abs(pct) < 10 ? 1 : 0)}% <span class="sdb-vs">${__('vs previous')}</span></span>`;
	}

	// ------------------------------------------------------------ render
	render() {
		const d = this.data;
		const p = d.previous;
		const esc = frappe.utils.escape_html;
		const same = d.from_date === d.to_date;
		$('#sdb-period').text(
			(same ? this.day(d.from_date, true) : `${this.day(d.from_date)} – ${this.day(d.to_date, true)}`) +
				' · ' +
				__('compared with') +
				' ' +
				(p.from_date === p.to_date ? this.day(p.from_date) : `${this.day(p.from_date)} – ${this.day(p.to_date)}`)
		);

		// Hero: revenue earned, and money collected beside it.
		$('#sdb-hero').html(`
			<div class="sdb-card sdb-hero-main">
				<span class="sdb-label">${__('Revenue earned')}</span>
				<div class="sdb-hero-v">${this.money(d.revenue.net)}</div>
				<div class="sdb-hero-row">
					${this.delta(d.revenue.net, p.revenue.net)}
					<span>${__('Before GST')} <b>${this.money(d.revenue.ex_gst)}</b></span>
					<span>${__('GST {0}%', [d.revenue.gst_rate])} <b>${this.money(d.revenue.gst)}</b></span>
					<span>${__('Discounts')} <b>${this.money(d.revenue.discounts)}</b></span>
				</div>
			</div>
			<div class="sdb-card sdb-hero-main">
				<span class="sdb-label">${__('Money collected')}</span>
				<div class="sdb-hero-v" style="font-size:40px">${this.money(d.collections.net)}</div>
				<div class="sdb-hero-row">${this.delta(d.collections.net, p.collections.net)}</div>
				<div class="sdb-split">
					<div><span class="v">${this.money(d.collections.advances)}</span><span class="l">${__('Advances')}</span></div>
					<div><span class="v">${this.money(d.collections.settlements)}</span><span class="l">${__('Bills settled')}</span></div>
					<div><span class="v">${this.money(d.collections.refunds)}</span><span class="l">${__('Refunded')}</span></div>
				</div>
			</div>
		`);

		const o = d.occupancy;
		const po = p.occupancy;
		const b = d.bookings;
		const tiles = [
			[__('Occupancy'), `${o.occupancy_pct}%`, `${o.nights_sold} ${__('of')} ${o.rooms * o.days} ${__('room nights')}`, this.delta(o.occupancy_pct, po.occupancy_pct)],
			[__('Average room rate'), this.money(o.adr), __('per night charged (ADR)'), this.delta(o.adr, po.adr)],
			[__('Revenue per room'), this.money(o.revpar), __('per available room night'), this.delta(o.revpar, po.revpar)],
			[__('Room nights sold'), o.nights_sold, `${o.rooms} ${__('rooms')} · ${o.days} ${__('day(s)')}`, this.delta(o.nights_sold, po.nights_sold)],
			[__('New bookings'), b.count, `${this.money(b.value)} · ${b.rooms} ${__('rooms')}`, this.delta(b.count, p.bookings.count)],
			[__('Enquiry conversion'), `${b.conversion_pct}%`, `${b.converted} ${__('of')} ${b.enquiries} ${__('enquiries')}`, this.delta(b.conversion_pct, p.bookings.conversion_pct)],
		];
		$('#sdb-kpis').html(
			tiles
				.map(
					([l, v, s, dl]) => `<div class="sdb-card sdb-kpi">
						<span class="sdb-label">${l}</span>
						<span class="v">${v}</span>
						<span class="s">${s}</span>
						<span>${dl}</span>
					</div>`
				)
				.join('')
		);

		this.render_trend();
		this.render_position();
		this.render_modes();
		this.render_bars('#sdb-types', __('Revenue by room type'), d.room_types.map((r) => [r.room_type, r.revenue, '']));
		this.render_bars(
			'#sdb-sources',
			__('New bookings by source'),
			d.sources.map((s) => [s.source, s.value, `${s.count} ${__('bkg')}`])
		);
		this.render_breakdown();
		this.render_held();
		this.render_bookings();
		this.render_register();
	}

	render_trend() {
		const d = this.data;
		const $c = $('#sdb-trend');
		const pts = d.daily || [];
		const W = Math.max($c.width() || 600, 280);
		const H = 260;
		const m = { l: 56, r: 14, t: 14, b: 28 };
		const iw = W - m.l - m.r;
		const ih = H - m.t - m.b;
		const max = Math.max(1000, ...pts.map((x) => Math.max(x.revenue, x.collections)));
		const min = Math.min(0, ...pts.map((x) => Math.min(x.revenue, x.collections)));
		// Gridlines on round values: a 1 / 2 / 2.5 / 5 x 10^n step, about four of them.
		const raw = (max - min) / 4;
		const mag = Math.pow(10, Math.floor(Math.log10(raw)));
		const step = [1, 2, 2.5, 5, 10].map((f) => f * mag).find((v) => v >= raw);
		const top = Math.ceil(max / step) * step;
		const bottom = min < 0 ? -Math.ceil(-min / step) * step : 0;
		const x = (i) => m.l + (pts.length <= 1 ? iw / 2 : (i * iw) / (pts.length - 1));
		const y = (v) => m.t + ih - ((v - bottom) / (top - bottom)) * ih;

		const ticks = Math.round((top - bottom) / step);
		let grid = '';
		for (let k = 0; k <= ticks; k++) {
			const v = bottom + step * k;
			const yy = y(v);
			grid += `<line x1="${m.l}" x2="${W - m.r}" y1="${yy}" y2="${yy}" stroke="var(--sdb-grid)" stroke-width="1"/>`;
			grid += `<text x="${m.l - 8}" y="${yy + 4}" text-anchor="end">${this.short(v)}</text>`;
		}
		// Date labels: as many as fit (about one per 64px), always including the last.
		const fit = Math.max(2, Math.floor(iw / 64));
		const every = Math.max(1, Math.ceil(pts.length / fit));
		let xl = '';
		pts.forEach((p, i) => {
			if (i % every === 0 || i === pts.length - 1) {
				if (i !== pts.length - 1 && pts.length - 1 - i < every * 0.6) return;
				xl += `<text x="${x(i)}" y="${H - 8}" text-anchor="middle">${this.day(p.date)}</text>`;
			}
		});
		const path = (key) => pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p[key]).toFixed(1)}`).join(' ');
		const single = pts.length === 1;
		const marks = single
			? `<circle cx="${x(0)}" cy="${y(pts[0].revenue)}" r="5" fill="var(--sdb-s1)" stroke="var(--sdb-surface)" stroke-width="2"/>
			   <circle cx="${x(0)}" cy="${y(pts[0].collections)}" r="5" fill="var(--sdb-s2)" stroke="var(--sdb-surface)" stroke-width="2"/>`
			: `<path d="${path('revenue')}" fill="none" stroke="var(--sdb-s1)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
			   <path d="${path('collections')}" fill="none" stroke="var(--sdb-s2)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;

		$c.html(`
			<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${__('Revenue earned and money collected per day')}">
				${grid}
				<line x1="${m.l}" x2="${W - m.r}" y1="${y(0)}" y2="${y(0)}" stroke="var(--sdb-axis)" stroke-width="1"/>
				${xl}
				${marks}
				<g id="sdb-hover" style="display:none">
					<line id="sdb-hx" y1="${m.t}" y2="${m.t + ih}" stroke="var(--sdb-axis)" stroke-width="1"/>
					<circle id="sdb-h1" r="5" fill="var(--sdb-s1)" stroke="var(--sdb-surface)" stroke-width="2"/>
					<circle id="sdb-h2" r="5" fill="var(--sdb-s2)" stroke="var(--sdb-surface)" stroke-width="2"/>
				</g>
				<rect x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent" id="sdb-hit"/>
			</svg>
			<div class="sdb-tip" id="sdb-tip"></div>
		`);
		if (!pts.length) return;

		const $tip = $c.find('#sdb-tip');
		const $hover = $c.find('#sdb-hover');
		const svg = $c.find('svg')[0];
		$c.find('#sdb-hit')
			.on('mousemove', (e) => {
				const rect = svg.getBoundingClientRect();
				const px = ((e.clientX - rect.left) / rect.width) * W;
				const i = pts.length <= 1 ? 0 : Math.max(0, Math.min(pts.length - 1, Math.round(((px - m.l) / iw) * (pts.length - 1))));
				const p = pts[i];
				$hover.show();
				$c.find('#sdb-hx').attr({ x1: x(i), x2: x(i) });
				$c.find('#sdb-h1').attr({ cx: x(i), cy: y(p.revenue) });
				$c.find('#sdb-h2').attr({ cx: x(i), cy: y(p.collections) });
				$tip.html(`
					<div class="d">${this.day(p.date, true)}</div>
					<div class="r"><span><span class="sw" style="background:var(--sdb-s1)"></span>${__('Revenue')}</span><b>${this.money(p.revenue)}</b></div>
					<div class="r"><span><span class="sw" style="background:var(--sdb-s2)"></span>${__('Collected')}</span><b>${this.money(p.collections)}</b></div>
					<div class="r"><span>${__('Occupancy')}</span><b>${p.occupancy_pct}% · ${p.nights_sold} ${__('rm')}</b></div>
				`);
				const left = (x(i) / W) * rect.width;
				const tw = $tip.outerWidth() || 180;
				$tip.css({ display: 'block', top: 6, left: Math.min(Math.max(left + 12, 0), rect.width - tw - 4) + 'px' });
				if (left + 12 + tw > rect.width) $tip.css('left', Math.max(left - tw - 12, 0) + 'px');
			})
			.on('mouseleave', () => {
				$hover.hide();
				$tip.hide();
			});
	}

	render_position() {
		const r = this.data.receivables;
		const h = this.data.advance_held;
		const a = this.data.advances;
		$('#sdb-position').html(`
			<div class="sdb-card-h"><span class="sdb-card-t">${__('Money position')}</span><span class="sdb-card-n">${__('right now')}</span></div>
			<div class="sdb-pos">
				<div class="sdb-pos-row"><span class="l">${__('To collect from guests in house')}<small>${r.in_house_count} ${__('stay(s)')}</small></span><span class="v">${this.money(r.in_house)}</span></div>
				<div class="sdb-pos-row ${r.checkout_pending ? 'alert' : ''}"><span class="l">${__('Check-outs not settled')}<small>${r.checkout_pending_count} ${__('guest(s) left without settling')}</small></span><span class="v">${this.money(r.checkout_pending)}</span></div>
				<div class="sdb-pos-row"><span class="l">${__('Balance due from arrivals')}<small>${__('next 7 days')}</small></span><span class="v">${this.money(r.arriving_7_days)}</span></div>
				<div class="sdb-pos-row"><span class="l">${__('Advances held for future stays')}<small>${h.count} ${__('booking(s)')}${h.refundable ? ' · ' + this.money(h.refundable) + ' ' + __('on cancelled / no-show') : ''}</small></span><span class="v">${this.money(h.total)}</span></div>
				<div class="sdb-pos-row"><span class="l">${__('Advances in this period')}<small>${__('applied to rooms at check-in')}: ${this.money(a.applied)}</small></span><span class="v">${this.money(a.received)}</span></div>
			</div>
		`);
	}

	render_modes() {
		const rows = this.data.modes || [];
		const esc = frappe.utils.escape_html;
		const total = rows.reduce((s, r) => s + r.net, 0);
		const max = Math.max(1, ...rows.map((r) => Math.abs(r.net)));
		const sum = (k) => rows.reduce((s, r) => s + flt(r[k]), 0);
		const body = rows.length
			? rows
					.map(
						(r) => `<tr>
							<td><b>${esc(r.mode)}</b><span class="sub">${r.count} ${__('payment(s)')}</span></td>
							<td style="width:28%"><div class="sdb-bar-row" style="grid-template-columns:1fr auto"><div class="t"><i style="width:${(Math.abs(r.net) / max) * 100}%"></i></div><span class="a">${total ? Math.round((r.net / total) * 100) : 0}%</span></div></td>
							<td class="num">${this.money(r.advance)}</td>
							<td class="num">${this.money(r.settlement)}</td>
							<td class="num">${r.refund ? '−' + this.money(r.refund) : '—'}</td>
							<td class="num"><b>${this.money(r.net)}</b></td>
						</tr>`
					)
					.join('') +
			  `<tr class="tot"><td>${__('Total')}</td><td></td>
					<td class="num">${this.money(sum('advance'))}</td>
					<td class="num">${this.money(sum('settlement'))}</td>
					<td class="num">${sum('refund') ? '−' + this.money(sum('refund')) : '—'}</td>
					<td class="num">${this.money(total)}</td></tr>`
			: `<tr><td colspan="6" class="sdb-empty">${__('No payments in this period.')}</td></tr>`;
		$('#sdb-modes').html(`
			<div class="sdb-card-h"><span class="sdb-card-t">${__('Collections by mode of payment')}</span><span class="sdb-card-n">${__('advances are taken before arrival; bills settled are paid during the stay or at check-out')}</span></div>
			<div class="sdb-table-wrap"><table>
				<thead><tr><th>${__('Mode')}</th><th>${__('Share')}</th><th class="num">${__('Advances')}</th><th class="num">${__('Bills settled')}</th><th class="num">${__('Refunds')}</th><th class="num">${__('Net received')}</th></tr></thead>
				<tbody>${body}</tbody>
			</table></div>
		`);
	}

	render_bars(sel, title, rows) {
		const esc = frappe.utils.escape_html;
		const max = Math.max(1, ...rows.map((r) => Math.abs(r[1])));
		const total = rows.reduce((s, r) => s + flt(r[1]), 0);
		$(sel).html(`
			<div class="sdb-card-h"><span class="sdb-card-t">${title}</span><span class="sdb-card-n">${this.money(total)}</span></div>
			${
				rows.length
					? `<div class="sdb-bars">${rows
							.slice(0, 8)
							.map(
								(r) => `<div class="sdb-bar-row" title="${esc(r[0])}: ${esc(this.money(r[1]))}${r[2] ? ' · ' + esc(r[2]) : ''}">
									<span class="n">${esc(r[0])}</span>
									<span class="t"><i style="width:${(Math.abs(r[1]) / max) * 100}%"></i></span>
									<span class="a">${this.short(r[1])}${r[2] ? `<span>${esc(r[2])}</span>` : ''}</span>
								</div>`
							)
							.join('')}</div>`
					: `<div class="sdb-empty">${__('Nothing in this period.')}</div>`
			}
		`);
	}

	render_breakdown() {
		const r = this.data.revenue;
		const rows = [
			[__('Room rent & extra beds'), r.room],
			[__('Services & extras'), r.extras],
			[__('Cancellation charges'), r.cancellation],
			[__('Discounts given'), -r.discounts],
		];
		$('#sdb-breakdown').html(`
			<div class="sdb-card-h"><span class="sdb-card-t">${__('Where revenue came from')}</span></div>
			<div class="sdb-pos">
				${rows
					.map(
						([l, v]) => `<div class="sdb-pos-row"><span class="l">${l}</span><span class="v" style="font-size:14px">${
							v < 0 ? '−' + this.money(-v) : this.money(v)
						}</span></div>`
					)
					.join('')}
				<div class="sdb-pos-row"><span class="l"><b>${__('Revenue earned')}</b><small>${__('incl. GST {0}', [this.money(r.gst)])}</small></span><span class="v">${this.money(r.net)}</span></div>
			</div>
		`);
	}

	render_held() {
		const h = this.data.advance_held;
		const esc = frappe.utils.escape_html;
		const rows = (h.bookings || [])
			.map(
				(b) => `<tr>
					<td><a href="/app/hotel-booking/${encodeURIComponent(b.booking)}">${esc(b.guest_name || b.booking)}</a><span class="sub">${esc(b.booking)} · ${esc(b.status)}</span></td>
					<td>${b.arrival_date ? this.day(b.arrival_date) : ''}</td>
					<td class="num">${this.money(b.total_amount)}</td>
					<td class="num"><b>${this.money(b.held)}</b></td>
				</tr>`
			)
			.join('');
		$('#sdb-held').html(`
			<div class="sdb-card-h"><span class="sdb-card-t">${__('Advances held')}</span><span class="sdb-card-n">${this.money(h.total)} · ${h.count} ${__('booking(s)')}</span></div>
			${
				rows
					? `<div class="sdb-table-wrap"><table><thead><tr><th>${__('Guest')}</th><th>${__('Arrives')}</th><th class="num">${__('Booking')}</th><th class="num">${__('Held')}</th></tr></thead><tbody>${rows}</tbody></table></div>`
					: `<div class="sdb-empty">${__('No advance money is held right now.')}</div>`
			}
		`);
	}

	render_bookings() {
		const b = this.data.bookings;
		const p = this.data.previous.bookings;
		$('#sdb-bookings').html(`
			<div class="sdb-card-h"><span class="sdb-card-t">${__('Bookings and enquiries')}</span><span class="sdb-card-n">${__('made in this period')}</span></div>
			<div class="sdb-pos">
				<div class="sdb-pos-row"><span class="l">${__('Enquiries received')}</span><span class="v">${b.enquiries} ${this.delta(b.enquiries, p.enquiries)}</span></div>
				<div class="sdb-pos-row"><span class="l">${__('Converted to bookings')}<small>${b.conversion_pct}% ${__('conversion')}</small></span><span class="v">${b.converted}</span></div>
				<div class="sdb-pos-row"><span class="l">${__('Bookings made')}<small>${b.rooms} ${__('rooms')}</small></span><span class="v">${b.count}</span></div>
				<div class="sdb-pos-row"><span class="l">${__('Value of bookings made')}<small>${__('excluding cancelled')}</small></span><span class="v">${this.money(b.value)}</span></div>
				<div class="sdb-pos-row ${b.cancelled + b.no_show ? 'alert' : ''}"><span class="l">${__('Cancelled / no-show')}</span><span class="v">${b.cancelled} / ${b.no_show}</span></div>
			</div>
		`);
	}

	render_register() {
		const rows = this.data.payments || [];
		const esc = frappe.utils.escape_html;
		const pill = { Advance: 'adv', Settlement: 'set', Refund: 'ref' };
		const label = { Advance: __('Advance'), Settlement: __('Bill settled'), Refund: __('Refund') };
		const body = rows.length
			? rows
					.map(
						(p) => `<tr>
							<td>${this.day(p.date)}</td>
							<td>${esc(p.guest || '')}<span class="sub">${esc(p.room || p.booking || '')}</span></td>
							<td><span class="sdb-pill ${pill[p.kind]}">${label[p.kind]}</span></td>
							<td>${esc(p.mode)}${p.reference ? `<span class="sub">${esc(p.reference)}</span>` : ''}</td>
							<td><a href="/app/payment-entry/${encodeURIComponent(p.name)}">${esc(p.name)}</a></td>
							<td class="num"><b>${p.kind === 'Refund' ? '−' : ''}${this.money(p.amount)}</b></td>
						</tr>`
					)
					.join('')
			: `<tr><td colspan="6" class="sdb-empty">${__('No payments in this period.')}</td></tr>`;
		$('#sdb-register').html(`
			<div class="sdb-card-h"><span class="sdb-card-t">${__('Payments received')}</span><span class="sdb-card-n">${__('latest {0}', [rows.length])}</span></div>
			<div class="sdb-table-wrap"><table>
				<thead><tr><th>${__('Date')}</th><th>${__('Guest')}</th><th>${__('Type')}</th><th>${__('Mode')}</th><th>${__('Receipt')}</th><th class="num">${__('Amount')}</th></tr></thead>
				<tbody>${body}</tbody>
			</table></div>
		`);
	}
}
