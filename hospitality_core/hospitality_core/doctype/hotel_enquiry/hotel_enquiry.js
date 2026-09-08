// Copyright (c) 2026, FRC Consulting and contributors
// For license information, please see license.txt

/* Form actions for Hotel Enquiry.
 *
 * Most agents work in the Hotel CRM console, but the desk form is what a manager opens
 * from a report or a list view, so the same conversion and follow-up actions live here.
 */

frappe.ui.form.on("Hotel Enquiry", {
	refresh(frm) {
		frm.trigger("set_indicator");
		frm.trigger("add_actions");
		frm.trigger("show_availability");
	},

	set_indicator(frm) {
		if (!frm.doc.status) return;
		frappe.db.get_value("Hotel Enquiry Status", frm.doc.status, ["color", "type"]).then((r) => {
			const meta = (r && r.message) || {};
			const map = {
				Won: "green",
				Lost: "red",
				Ongoing: "orange",
				Open: "blue",
			};
			frm.page.set_indicator(__(frm.doc.status), map[meta.type] || "gray");
		});
	},

	add_actions(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Open in CRM Console"), () => {
			frappe.set_route("hotel-crm");
		});

		if (frm.doc.hotel_booking) {
			frm.add_custom_button(__("View Booking"), () => {
				frappe.set_route("Form", "Hotel Booking", frm.doc.hotel_booking);
			}).addClass("btn-primary");
		} else {
			frm.add_custom_button(__("Create Booking"), () => frm.trigger("create_booking"))
				.addClass("btn-primary");
		}

		frm.add_custom_button(__("Log Follow-up"), () => frm.trigger("log_follow_up"));
	},

	/** Show what is actually free for the dates the guest asked about. */
	show_availability(frm) {
		if (frm.is_new() || !frm.doc.check_in_date || !frm.doc.check_out_date) {
			frm.dashboard.clear_headline();
			return;
		}
		frappe.call({
			method: "hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.get_stay_availability",
			args: { arrival_date: frm.doc.check_in_date, departure_date: frm.doc.check_out_date },
			callback: (r) => {
				const data = r.message;
				if (!data || data.error || !data.room_types) return;

				const wanted = {};
				(frm.doc.room_lines || []).forEach((l) => {
					if (l.room_type) wanted[l.room_type] = (wanted[l.room_type] || 0) + (l.qty || 1);
				});

				const parts = data.room_types.map((t) => {
					const need = wanted[t.room_type] || 0;
					const short = need && t.free < need;
					const color = t.free === 0 || short ? "var(--red-600)" : "var(--green-600)";
					return `<span style="margin-right:14px">${frappe.utils.escape_html(t.room_type)}:
						<b style="color:${color}">${t.free}</b>${need ? ` / ${__("need")} ${need}` : ""}</span>`;
				});
				frm.dashboard.set_headline(
					`<div>${__("Free for these dates")} &mdash; ${parts.join("")}</div>`
				);
			},
		});
	},

	check_in_date(frm) { frm.trigger("show_availability"); },
	check_out_date(frm) { frm.trigger("show_availability"); },

	create_booking(frm) {
		if (!(frm.doc.room_lines || []).length) {
			frappe.msgprint(__("Add at least one room before creating a booking."));
			return;
		}
		if (!frm.doc.check_in_date || !frm.doc.check_out_date) {
			frappe.msgprint(__("Set check-in and check-out dates first."));
			return;
		}

		const dlg = new frappe.ui.Dialog({
			title: __("Create Booking"),
			fields: [
				{
					fieldname: "action",
					label: __("Action"),
					fieldtype: "Select",
					reqd: 1,
					default: "hold",
					options: [
						{ label: __("Tentative hold (blocks rooms, no payment yet)"), value: "hold" },
						{ label: __("Confirm now (assigns rooms)"), value: "confirm" },
					],
				},
				{
					fieldname: "hold_hours",
					label: __("Hold For (hours)"),
					fieldtype: "Int",
					default: 24,
					depends_on: "eval:doc.action=='hold'",
				},
			],
			primary_action_label: __("Create"),
			primary_action: (values) => {
				dlg.hide();
				frm.call({
					method: "hospitality_core.hospitality_core.page.hotel_crm.hotel_crm.create_booking_from_enquiry",
					args: {
						enquiry: frm.doc.name,
						action: values.action,
						hold_hours: values.hold_hours || 24,
					},
					freeze: true,
					freeze_message: __("Creating booking…"),
					callback: (r) => {
						if (!r.message) return;
						frappe.show_alert({
							message: __("Booking {0} created", [r.message.booking]),
							indicator: "green",
						});
						frappe.set_route("Form", "Hotel Booking", r.message.booking);
					},
				});
			},
		});
		dlg.show();
	},

	log_follow_up(frm) {
		const dlg = new frappe.ui.Dialog({
			title: __("Log Follow-up"),
			fields: [
				{
					fieldname: "outcome",
					label: __("Outcome"),
					fieldtype: "Select",
					reqd: 1,
					default: "Connected",
					options: ["Connected", "No Answer", "Callback Requested", "Quoted", "Not Interested"],
				},
				{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" },
				{ fieldname: "next_follow_up", label: __("Next Follow-up"), fieldtype: "Datetime" },
			],
			primary_action_label: __("Log"),
			primary_action: (values) => {
				dlg.hide();
				frm.call({
					method: "hospitality_core.hospitality_core.doctype.hotel_enquiry.hotel_enquiry.log_follow_up",
					args: Object.assign({ enquiry: frm.doc.name }, values),
					callback: () => {
						frappe.show_alert({ message: __("Follow-up logged"), indicator: "green" });
						frm.reload_doc();
					},
				});
			},
		});
		dlg.show();
	},
});

frappe.ui.form.on("Enquiry Room Line", {
	room_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.room_type || row.rate_quoted) return;
		frappe.db.get_value("Hotel Room Type", row.room_type, "default_rate").then((r) => {
			if (r && r.message) {
				frappe.model.set_value(cdt, cdn, "rate_quoted", r.message.default_rate);
			}
		});
	},
});
