/**
 * Shared room-type presentation for Hospitality Core.
 *
 * Capacity, bed layout, tariff and amenities have to read the same on the booking form,
 * the enquiry, the reservation and the tape chart. Before this, each surface fetched
 * `default_rate` on its own and showed nothing else, so "does it have a pool" and "how
 * many people fit" were only answerable by opening the Room Type record.
 *
 * `frappe.hospitality.room_details` caches the catalog for the session — it is small
 * (a handful of categories) and changes about as often as the property is rebuilt.
 */
frappe.provide('frappe.hospitality');

frappe.hospitality.room_details = {
	_cache: null,
	_pending: null,

	/** The whole catalog, cached. Resolves to an array of room types. */
	catalog() {
		if (this._cache) return Promise.resolve(this._cache);
		if (this._pending) return this._pending;

		this._pending = frappe
			.call({
				method: 'hospitality_core.hospitality_core.api.tariff.get_room_type_catalog',
				args: { only_active: 0 },
			})
			.then((r) => {
				this._cache = r.message || [];
				this._pending = null;
				return this._cache;
			})
			.catch(() => {
				this._pending = null;
				return [];
			});

		return this._pending;
	},

	/** One room type by name, or null. */
	get(room_type) {
		if (!room_type) return Promise.resolve(null);
		return this.catalog().then(
			(types) => types.find((t) => t.name === room_type) || null
		);
	},

	/** Drop the cache after a Room Type is edited, so forms pick the change up. */
	clear() {
		this._cache = null;
	},

	/** "3BH · Max 10 · 📺 📶 🧊 🏊" — the one-line summary used under a field. */
	summary(t) {
		if (!t) return '';
		const amen = (t.amenities || []).map((a) => a.icon).join(' ');
		return [
			t.bedroom_configuration,
			t.max_occupancy ? __('Max {0} guests', [t.max_occupancy]) : '',
			amen,
		]
			.filter(Boolean)
			.join(' &middot; ');
	},

	/** Amenity chips as HTML, each with its label on hover. */
	chips(t) {
		if (!t || !(t.amenities || []).length) return '';
		return (
			'<span class="hc-amenities">' +
			t.amenities
				.map(
					(a) =>
						`<span class="hc-amenity" title="${frappe.utils.escape_html(
							a.label
						)}">${a.icon} ${frappe.utils.escape_html(a.label)}</span>`
				)
				.join('') +
			'</span>'
		);
	},

	/** The full detail card shown on reservation and booking forms. */
	card(t) {
		if (!t) return '';
		const money = (v) => format_currency(v, frappe.boot.sysdefaults.currency || 'INR');

		const rates = [
			`<div class="hc-rate"><span>${__('Weekday')}</span><b>${money(
				t.default_rate
			)}</b></div>`,
			t.has_weekend_premium
				? `<div class="hc-rate hc-rate-wknd" title="${__(
						'Charged on Saturday, Sunday and holiday nights'
				  )}"><span>${__('Weekend/Holiday')}</span><b>${money(
						t.weekend_rate
				  )}</b></div>`
				: '',
			t.per_head_rate_weekday
				? `<div class="hc-rate"><span>${__('Per head/day')}</span><b>${money(
						t.per_head_rate_weekday
				  )}</b></div>`
				: '',
			t.extra_bed_adult_rate
				? `<div class="hc-rate"><span>${__('Extra bed (adult)')}</span><b>${money(
						t.extra_bed_adult_rate
				  )}</b></div>`
				: '',
			t.extra_bed_child_rate
				? `<div class="hc-rate"><span>${__('Extra bed (child)')}</span><b>${money(
						t.extra_bed_child_rate
				  )}</b></div>`
				: '',
		]
			.filter(Boolean)
			.join('');

		return `
			<div class="hc-room-card">
				<div class="hc-room-head">
					<span class="hc-room-name">${frappe.utils.escape_html(t.name)}</span>
					${
						t.bedroom_configuration
							? `<span class="hc-room-bed">${frappe.utils.escape_html(
									t.bedroom_configuration
							  )}</span>`
							: ''
					}
					${
						t.max_occupancy
							? `<span class="hc-room-cap">👤 ${__('Max {0}', [
									t.max_occupancy,
							  ])}</span>`
							: ''
					}
				</div>
				${this.chips(t)}
				<div class="hc-rates">${rates}</div>
				${
					t.description
						? `<div class="hc-room-desc">${frappe.utils.escape_html(
								t.description
						  )}</div>`
						: ''
				}
			</div>`;
	},

	/**
	 * Price a stay through the server so the figure matches what is billed.
	 * Returns the quote, or null if the dates are not usable yet.
	 */
	quote(room_type, arrival, departure, opts) {
		if (!room_type || !arrival || !departure) return Promise.resolve(null);
		if (frappe.datetime.get_diff(departure, arrival) <= 0) return Promise.resolve(null);

		return frappe
			.call({
				method: 'hospitality_core.hospitality_core.api.tariff.quote_stay',
				args: Object.assign(
					{ room_type, arrival_date: arrival, departure_date: departure },
					opts || {}
				),
			})
			.then((r) => r.message || null)
			.catch(() => null);
	},

	/** Render the detail card into a form's HTML field. */
	render_into(frm, fieldname, room_type) {
		const field = frm.get_field(fieldname);
		if (!field || !field.$wrapper) return;
		if (!room_type) {
			field.$wrapper.empty();
			return;
		}
		this.get(room_type).then((t) => {
			field.$wrapper.html(this.card(t));
		});
	},
};

// A Room Type edit invalidates every cached card.
frappe.ui.form.on('Hotel Room Type', {
	after_save() {
		frappe.hospitality.room_details.clear();
	},
});
