// Copyright (c) 2026, FRC Consulting and contributors
// For license information, please see license.txt

/* Form actions for Hotel Booking.
 *
 * The booking lifecycle used to be reachable only from the Hotel CRM console, so a
 * manager who opened a booking in the desk had no way to confirm it, take an advance or
 * cancel it. These buttons expose the same whitelisted methods the console calls.
 */

frappe.ui.form.on("Hotel Booking", {
	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("add_actions");
		frm.trigger("show_summary");
		frm.trigger("render_room_details");

		// Stays always run from the standard check-in to the standard check-out time
		// (Hospitality Accounting Settings) and rooms are allocated by night, so the
		// times are shown, not typed.
		['arrival_time', 'departure_time'].forEach((f) => {
			frm.set_df_property(f, 'read_only', 1);
			frm.set_df_property(f, 'description', __('From Hospitality Accounting Settings'));
		});
	},

	arrival_date: (frm) => frm.trigger("render_room_details"),
	departure_date: (frm) => frm.trigger("render_room_details"),
	discount_type: (frm) => frm.trigger("render_room_details"),
	discount_value: (frm) => frm.trigger("render_room_details"),
	remarks: (frm) => frm.trigger("render_room_details"),

	/* What the guest is buying: each category's capacity, amenities and tariff, plus a
	 * night-by-night quote so a weekend premium is visible before the booking is taken
	 * rather than discovered on the folio. */
	render_room_details(frm) {
		const field = frm.get_field("room_details_preview");
		if (!field || !field.$wrapper) return;

		const lines = (frm.doc.rooms || []).filter((l) => l.room_type);
		if (!lines.length || !frm.doc.arrival_date || !frm.doc.departure_date) {
			field.$wrapper.empty();
			return;
		}

		frappe.call({
			method: "hospitality_core.hospitality_core.api.tariff.quote_rooms",
			args: {
				lines: lines.map((l) => ({
					room_type: l.room_type,
					qty: l.qty || 1,
					adults: l.adults || 0,
					children: l.children || 0,
					extra_beds_adult: l.extra_beds_adult || 0,
					extra_beds_child: l.extra_beds_child || 0,
					rate_override: l.rate || 0,
					is_rate_overridden: l.is_rate_overridden || 0,
					idx: l.idx,
				})),
				arrival_date: frm.doc.arrival_date,
				departure_date: frm.doc.departure_date,
				// The discount is agreed once for the booking, so it is applied to the
				// quote as a whole rather than line by line.
				discount_type: frm.doc.discount_type || null,
				discount_value: frm.doc.discount_value || 0,
			},
		}).then((r) => {
			const res = r.message;
			if (!res) {
				field.$wrapper.empty();
				return;
			}

			frappe.hospitality.room_details.catalog().then((types) => {
				const money = (v) => format_currency(v, res.currency);
				const blocks = res.lines.map((q) => {
					const t = types.find((x) => x.name === q.room_type) || {};
					const rows = q.nights
						.map(
							(n) =>
								`<tr class="${n.weekend ? "wknd" : ""}">
									<td>${frappe.datetime.str_to_user(n.date)}</td>
									<td>${__(n.rate_class || (n.weekend ? "Weekend" : "Weekday"))}</td>
									<td class="num">${money(n.rate)}</td>
									<td class="num">${n.extra_bed ? money(n.extra_bed) : ""}</td>
									<td class="num">${money(n.amount)}</td>
								</tr>`
						)
						.join("");

					// The line's commercial story: what the beds added, what the
					// discount took off, and what was agreed rather than tariffed.
					const extras = [
						q.beds_auto_added || q.extra_bed_total
							? `<tr><td colspan="4">🛏 ${__("Extra beds")} (${
									q.extra_beds_adult
							  } ${__("adult")}, ${q.extra_beds_child} ${__(
									"child"
							  )})</td><td class="num">${money(q.extra_bed_total)}</td></tr>`
							: "",
					]
						.filter(Boolean)
						.join("");

					const agreed = q.rate_override
						? `<div class="hc-quote-note">${__(
								"Agreed rate of {0} per night — the tariff does not apply to this line.",
								[money(q.rate_override)]
						  )}</div>`
						: "";

					return `
						${frappe.hospitality.room_details.card(t)}
						${agreed}
						<div class="hc-quote">
							<table>
								<tbody>${rows}${extras}</tbody>
								<tfoot><tr>
									<td colspan="4">${__("Total")} &times; ${q.qty} ${__("room(s)")}</td>
									<td class="num">${money(q.total)}</td>
								</tr></tfoot>
							</table>
						</div>`;
				});

				const warn = (res.warnings || [])
					.map((w) => `<div class="hc-warn">⚠ ${frappe.utils.escape_html(w)}</div>`)
					.join("");

				// The booking's own commercials, below the per-room breakdown: one
				// discount off the whole quote, and the note that reaches the bill.
				const money2 = (v) => format_currency(v, res.currency);
				const summary = `
					<div class="hc-quote">
						<table>
							<tfoot>
								<tr><td>${__("Subtotal")}</td><td class="num">${money2(
									res.gross_total
								)}</td></tr>
								${
									res.discount_amount
										? `<tr><td>${__("Discount")}${
												frm.doc.discount_type === "Percentage"
													? ` (${frm.doc.discount_value}%)`
													: ""
										  }</td><td class="num">-${money2(res.discount_amount)}</td></tr>`
										: ""
								}
								<tr><td><b>${__("Total")}</b></td><td class="num"><b>${money2(
									res.total
								)}</b></td></tr>
							</tfoot>
						</table>
					</div>
					${
						frm.doc.remarks
							? `<div class="hc-room-desc">📝 ${frappe.utils.escape_html(
									frm.doc.remarks
							  )}</div>`
							: ""
					}`;

				// Say plainly why some nights cost more, so a holiday premium does not
				// look like a pricing bug to whoever takes the booking.
				const holidays = res.lines.reduce((n, q) => n + (q.holiday_nights || 0), 0);
				const note = holidays
					? `<div class="hc-quote-note">${__(
							"{0} night(s) are public holidays and are charged at the weekend rate.",
							[holidays]
					  )}</div>`
					: "";

				field.$wrapper.html(blocks.join("") + summary + note + warn);
			});
		});
	},

	set_indicator(frm) {
		const colors = {
			Draft: "gray",
			Tentative: "orange",
			Confirmed: "blue",
			"Checked In": "green",
			Completed: "darkgrey",
			Cancelled: "red",
			"No Show": "red",
		};
		if (frm.doc.status) {
			frm.page.set_indicator(__(frm.doc.status), colors[frm.doc.status] || "gray");
		}
	},

	add_actions(frm) {
		if (frm.is_new()) return;
		const status = frm.doc.status;

		const today = frappe.datetime.get_today();
		const arrived = frm.doc.arrival_date && frm.doc.arrival_date <= today;

		// On arrival day the next thing the desk does is check in, so that is the
		// primary action; before then it is confirming the booking.
		// A No Show whose guest turns up late is checked in the same way.
		if (["Draft", "Tentative", "Confirmed", "No Show"].includes(status) && arrived) {
			frm.add_custom_button(__("Check In"), () => frm.trigger("check_in"))
				.addClass("btn-primary");
		}

		if (["Draft", "Tentative"].includes(status)) {
			const btn = frm.add_custom_button(__("Confirm Booking"), () => frm.trigger("confirm_booking"));
			if (!arrived) btn.addClass("btn-primary");
		}

		if (["Draft", "Tentative", "Confirmed"].includes(status)) {
			frm.add_custom_button(__("Change Dates"), () => {
				frappe.hospitality.stay.change_booking_dates(frm.doc.name, {
					on_done: () => frm.reload_doc(),
				});
			});
		}

		if (["Tentative", "Confirmed", "Checked In"].includes(status)) {
			frm.add_custom_button(__("Booking Confirmation"), () => {
				window.open(
					`/printview?doctype=Hotel%20Booking&name=${encodeURIComponent(frm.doc.name)}` +
						`&format=${encodeURIComponent("Booking Confirmation")}`
				);
			}, __("View"));
		}

		if (status === "Draft") {
			frm.add_custom_button(__("Place Hold"), () => frm.trigger("place_hold"));
		}

		if (["Draft", "Tentative", "Confirmed", "Checked In"].includes(status)) {
			frm.add_custom_button(__("Take Advance"), () => frm.trigger("take_advance"), __("Money"));
		}

		if (frm.doc.booking_folio) {
			frm.add_custom_button(__("Booking Folio"), () => {
				frappe.set_route("Form", "Guest Folio", frm.doc.booking_folio);
			}, __("Money"));
		}

		if (!["Cancelled", "Completed"].includes(status)) {
			frm.add_custom_button(__("Cancel Booking"), () => frm.trigger("cancel_booking"));
		}

		const reservations = (frm.doc.rooms || []).filter((r) => r.reservation);

		// In house on a one-room booking: check out and extend from here too, rather
		// than making the desk go and find the reservation.
		if (status === "Checked In" && reservations.length === 1) {
			const res = reservations[0].reservation;
			frm.add_custom_button(__("Check Out"), () =>
				frappe.hospitality.stay.check_out(res, { on_done: () => frm.reload_doc() })
			).addClass("btn-primary");
			frm.add_custom_button(__("Extend Stay"), () =>
				frappe.hospitality.stay.extend(res, { on_done: () => frm.reload_doc() })
			);
		}

		if (reservations.length) {
			frm.add_custom_button(__("Reservations"), () => {
				frappe.set_route("List", "Hotel Reservation", { hotel_booking: frm.doc.name });
			}, __("View"));
		}
		if (frm.doc.enquiry) {
			frm.add_custom_button(__("Enquiry"), () => {
				frappe.set_route("Form", "Hotel Enquiry", frm.doc.enquiry);
			}, __("View"));
		}
	},

	/** Where the booking is in its journey, and where the money stands. */
	show_summary(frm) {
		if (frm.is_new()) {
			frm.dashboard.clear_headline();
			return;
		}
		const fmt = (v) => format_currency(v || 0, frappe.defaults.get_default("currency"));
		const due = flt(frm.doc.balance_due);

		const steps = ["Enquiry", "Hold", "Confirmed", "Checked In", "Completed"];
		const reached = {
			Draft: 0, Tentative: 1, Confirmed: 2, "Checked In": 3, Completed: 4,
		}[frm.doc.status];
		const track = ["Cancelled", "No Show"].includes(frm.doc.status)
			? `<span class="indicator-pill red">${__(frm.doc.status)}</span>`
			: steps
					.map((label, i) => {
						const done = reached !== undefined && i <= reached;
						return `<span style="padding:2px 10px;border-radius:999px;font-size:var(--text-xs);
							font-weight:${i === reached ? 700 : 500};
							background:${done ? "var(--bg-green)" : "var(--subtle-fg)"};
							color:${done ? "var(--text-on-green)" : "var(--text-muted)"}">${__(label)}</span>`;
					})
					.join(' <span class="text-muted">›</span> ');

		const money = frm.doc.total_amount
			? `<div style="margin-top:6px">${__("Total")}: <b>${fmt(frm.doc.total_amount)}</b>
			 &nbsp;&middot;&nbsp; ${__("Advance")}: <b>${fmt(frm.doc.advance_received)}</b>
			 &nbsp;&middot;&nbsp; ${__("Balance due")}:
			 <b style="color:${due > 0 ? "var(--red-600)" : "var(--green-600)"}">${fmt(due)}</b>
			 &nbsp;&middot;&nbsp; ${frm.doc.nights || 0} ${__("night(s)")}</div>`
			: "";
		frm.dashboard.set_headline(`<div>${track}</div>${money}`);
	},

	/* Arrival: a single-room booking opens the full check-in dialog (ID, bill, payment);
	 * a multi-room one checks every room in at once and applies the advance. */
	check_in(frm) {
		const reservations = (frm.doc.rooms || []).filter((r) => r.reservation);
		if (frm.doc.status === "Confirmed" && reservations.length === 1) {
			frappe.hospitality.stay.check_in(reservations[0].reservation, {
				on_done: () => frm.reload_doc(),
			});
			return;
		}
		const n = (frm.doc.rooms || []).length;
		frappe.confirm(
			__("Check in all {0} room(s) on this booking now? Rooms not yet assigned get a free room of their type, and the advance is applied.", [n]),
			() => {
				frm.call({
					method: "hospitality_core.hospitality_core.page.hotel_pos.hotel_pos.checkin_arrival",
					args: { booking: frm.doc.name },
					freeze: true,
					freeze_message: __("Checking in…"),
					callback: (r) => {
						if (!r.message) return;
						let msg = __("Checked in {0} room(s)", [(r.message.checked_in || []).length]);
						if (flt(r.message.advance_applied)) {
							msg += " · " + __("advance {0} applied", [format_currency(r.message.advance_applied)]);
						}
						frappe.show_alert({ message: msg, indicator: "green" }, 6);
						frm.reload_doc();
					},
				});
			}
		);
	},

	confirm_booking(frm) {
		const unassigned = (frm.doc.rooms || []).filter((r) => !r.room).length;
		const message = unassigned
			? __("{0} room line(s) have no room yet. Free rooms will be assigned automatically. Continue?", [unassigned])
			: __("Confirm this booking and create the reservations?");

		frappe.confirm(message, () => {
			frm.call({
				method: "hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking.confirm_booking",
				args: { booking: frm.doc.name },
				freeze: true,
				freeze_message: __("Confirming…"),
				callback: () => {
					frappe.show_alert({ message: __("Booking confirmed"), indicator: "green" });
					frm.reload_doc();
				},
			});
		});
	},

	place_hold(frm) {
		const dlg = new frappe.ui.Dialog({
			title: __("Place Hold"),
			fields: [
				{
					fieldname: "hold_hours",
					label: __("Hold For (hours)"),
					fieldtype: "Int",
					default: 24,
					reqd: 1,
					description: __("Rooms of this type are held until the hold expires, then released automatically."),
				},
			],
			primary_action_label: __("Hold"),
			primary_action: (values) => {
				dlg.hide();
				frm.call({
					method: "hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking.hold_booking",
					args: { booking: frm.doc.name, hold_hours: values.hold_hours },
					freeze: true,
					callback: () => frm.reload_doc(),
				});
			},
		});
		dlg.show();
	},

	take_advance(frm) {
		const dlg = new frappe.ui.Dialog({
			title: __("Take Advance"),
			fields: [
				{
					fieldname: "amount",
					label: __("Amount"),
					fieldtype: "Currency",
					reqd: 1,
					default: frm.doc.balance_due,
				},
				{
					fieldname: "mode_of_payment",
					label: __("Mode of Payment"),
					fieldtype: "Link",
					options: "Mode of Payment",
					reqd: 1,
					default: "Cash",
				},
				{ fieldname: "reference_no", label: __("Reference / UTR"), fieldtype: "Data" },
				{
					fieldname: "info",
					fieldtype: "HTML",
					options: `<p class="text-muted small">${__(
						"Creates a Payment Entry and holds the money against the advance liability account until the guest checks in."
					)}</p>`,
				},
			],
			primary_action_label: __("Record Advance"),
			primary_action: (values) => {
				dlg.hide();
				frm.call({
					method: "hospitality_core.hospitality_core.api.advance.record_advance",
					args: {
						booking: frm.doc.name,
						amount: values.amount,
						mode_of_payment: values.mode_of_payment,
						reference_no: values.reference_no,
					},
					freeze: true,
					freeze_message: __("Recording advance…"),
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({
								message: __("Advance recorded: {0}", [r.message.payment_entry]),
								indicator: "green",
							});
						}
						frm.reload_doc();
					},
				});
			},
		});
		dlg.show();
	},

	cancel_booking(frm) {
		const dlg = new frappe.ui.Dialog({
			title: __("Cancel Booking"),
			fields: [
				{ fieldname: "reason", label: __("Reason"), fieldtype: "Small Text", reqd: 1 },
				{
					fieldname: "cancellation_charge",
					label: __("Cancellation Charge"),
					fieldtype: "Currency",
					description: __("Retained from any advance. Leave blank for a full refund."),
				},
				{
					fieldname: "warn",
					fieldtype: "HTML",
					options: flt(frm.doc.advance_received)
						? `<p class="text-danger small">${__(
								"This booking holds an advance. Cancelling releases the rooms but does not refund the money — issue the refund from the booking folio."
						  )}</p>`
						: "",
				},
			],
			primary_action_label: __("Cancel Booking"),
			primary_action: (values) => {
				dlg.hide();
				frm.call({
					method: "hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking.cancel_booking",
					args: {
						booking: frm.doc.name,
						reason: values.reason,
						cancellation_charge: values.cancellation_charge || 0,
					},
					freeze: true,
					callback: () => {
						frappe.show_alert({ message: __("Booking cancelled"), indicator: "orange" });
						frm.reload_doc();
					},
				});
			},
		});
		dlg.show();
	},
});

frappe.ui.form.on("Hotel Booking Room", {
	room_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.room_type) return;

		// Price the line for the actual stay window rather than pulling a flat rate:
		// weekend nights cost more, so rate x nights would understate the booking.
		frappe.hospitality.room_details
			.quote(row.room_type, frm.doc.arrival_date, frm.doc.departure_date, {
				qty: row.qty || 1,
				adults: row.adults || 0,
				children: row.children || 0,
				extra_beds_adult: row.extra_beds_adult || 0,
				extra_beds_child: row.extra_beds_child || 0,
			})
			.then((q) => {
				if (q && !row.rate) {
					frappe.model.set_value(cdt, cdn, "rate", q.average_room_nightly);
				}
				frm.trigger("render_room_details");
			});
	},

	/* A rate typed into the grid is an agreement with the guest. The flag is what stops
	 * calculate_totals repricing it on every save, and it travels to the reservation. */
	rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.rate)) {
			frappe.model.set_value(cdt, cdn, "is_rate_overridden", 1);
		}
		frm.trigger("render_room_details");
	},

	qty: (frm) => frm.trigger("render_room_details"),
	adults: (frm) => frm.trigger("render_room_details"),
	children: (frm) => frm.trigger("render_room_details"),
	extra_beds_adult: (frm) => frm.trigger("render_room_details"),
	extra_beds_child: (frm) => frm.trigger("render_room_details"),
	rooms_remove: (frm) => frm.trigger("render_room_details"),
});
