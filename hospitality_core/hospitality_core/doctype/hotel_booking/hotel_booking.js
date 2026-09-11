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
	},

	arrival_date: (frm) => frm.trigger("render_room_details"),
	departure_date: (frm) => frm.trigger("render_room_details"),

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
				})),
				arrival_date: frm.doc.arrival_date,
				departure_date: frm.doc.departure_date,
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

					return `
						${frappe.hospitality.room_details.card(t)}
						<div class="hc-quote">
							<table>
								<tbody>${rows}</tbody>
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

				// Say plainly why some nights cost more, so a holiday premium does not
				// look like a pricing bug to whoever takes the booking.
				const holidays = res.lines.reduce((n, q) => n + (q.holiday_nights || 0), 0);
				const note = holidays
					? `<div class="hc-quote-note">${__(
							"{0} night(s) are public holidays and are charged at the weekend rate.",
							[holidays]
					  )}</div>`
					: "";

				field.$wrapper.html(blocks.join("") + note + warn);
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

		if (["Draft", "Tentative"].includes(status)) {
			frm.add_custom_button(__("Confirm Booking"), () => frm.trigger("confirm_booking"))
				.addClass("btn-primary");
		}

		if (status === "Draft") {
			frm.add_custom_button(__("Place Hold"), () => frm.trigger("place_hold"));
		}

		if (["Tentative", "Confirmed", "Checked In"].includes(status)) {
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

	/** A short read of where the money stands, above the form. */
	show_summary(frm) {
		if (frm.is_new() || !frm.doc.total_amount) {
			frm.dashboard.clear_headline();
			return;
		}
		const fmt = (v) => format_currency(v || 0, frappe.defaults.get_default("currency"));
		const due = flt(frm.doc.balance_due);
		frm.dashboard.set_headline(
			`<div>${__("Total")}: <b>${fmt(frm.doc.total_amount)}</b>
			 &nbsp;&middot;&nbsp; ${__("Advance")}: <b>${fmt(frm.doc.advance_received)}</b>
			 &nbsp;&middot;&nbsp; ${__("Balance due")}:
			 <b style="color:${due > 0 ? "var(--red-600)" : "var(--green-600)"}">${fmt(due)}</b></div>`
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
					frappe.model.set_value(cdt, cdn, "rate", q.average_nightly);
				}
				frm.trigger("render_room_details");
			});
	},

	qty: (frm) => frm.trigger("render_room_details"),
	adults: (frm) => frm.trigger("render_room_details"),
	children: (frm) => frm.trigger("render_room_details"),
	extra_beds_adult: (frm) => frm.trigger("render_room_details"),
	extra_beds_child: (frm) => frm.trigger("render_room_details"),
	rooms_remove: (frm) => frm.trigger("render_room_details"),
});
