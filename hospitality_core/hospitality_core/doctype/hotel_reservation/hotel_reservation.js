frappe.ui.form.on('Hotel Reservation', {
    onload: function (frm) {
        if (frm.is_new()) {
            frm.set_value('status', 'Reserved');
            frm.set_value('is_company_guest', 0);
            frm.set_value('company', ''); // Ensure company is empty
        }
    },
    validate: function (frm) {
        if (!frm.doc.is_company_guest) {
            frm.set_value('company', null);
        }
    },
    is_company_guest: function (frm) {
        if (!frm.doc.is_company_guest) {
            frm.set_value('company', null);
        }
    },
    refresh: function (frm) {
        // Keep room type aligned with the selected room on load and refresh.
        sync_room_type_from_room(frm);
        render_room_details(frm);

        // Filter Rooms based on Room Type AND Availability
        frm.set_query('room', function () {
            return {
                query: 'hospitality_core.hospitality_core.api.reservation.get_available_rooms_for_picker',
                filters: {
                    'arrival_date': frm.doc.arrival_date,
                    'departure_date': frm.doc.departure_date,
                    'room_type': frm.doc.room_type,
                    'ignore_reservation': frm.doc.name
                }
            };
        });

        // Add Workflow Buttons
        if (!frm.is_new()) {

            // CHECK IN — one dialog: ID, the stay's price night by night, the advance
            // that will be applied, and an optional payment.
            if (frm.doc.status === 'Reserved') {
                frm.add_custom_button(__('Check In'), function () {
                    frappe.hospitality.stay.check_in(frm.doc.name, {
                        on_done: () => frm.reload_doc(),
                    });
                }).addClass("btn-primary");
            }

            // CHECK OUT — shows the bill, applies any advance still on the booking,
            // takes the balance, closes the folio and raises the Sales Invoice.
            // An early departure is allowed: the server shortens the stay to today.
            if (frm.doc.status === 'Checked In') {
                frm.page.set_primary_action(__('Check Out'), function () {
                    frappe.hospitality.stay.check_out(frm.doc.name, {
                        on_done: () => {
                            frm.reload_doc();
                            // Check-out is the moment the guest will answer, so ask now.
                            prompt_feedback_whatsapp(frm);
                        },
                    });
                });
            }

            // CANCEL RESERVATION BUTTON
            // Visible for Reserved AND Checked In, Restricted to Supervisors
            let is_supervisor = frappe.user_roles.includes('Frontdesk Supervisor') ||
                frappe.user_roles.includes('System Manager') ||
                frappe.session.user === 'Administrator';

            // A stay not yet checked in is cancelled with Stay › Cancel Stay (which also
            // handles a kept cancellation charge); this is the supervisor's override for
            // a guest already in house.
            if (frm.doc.status === 'Checked In' && is_supervisor) {
                frm.add_custom_button(__('Cancel Reservation'), function () {
                    frappe.confirm(
                        'Are you sure you want to Cancel this Reservation?',
                        function () {
                            frm.call({
                                method: 'cancel_reservation',
                                args: {
                                    name: frm.doc.name
                                },
                                freeze: true,
                                callback: function (r) {
                                    if (!r.exc) {
                                        frappe.msgprint('Reservation Cancelled.');
                                        frm.reload_doc();
                                    }
                                }
                            });
                        }
                    );
                }, null).addClass('btn-danger'); // Add class for styling if possible, or just standard custom button
            }

            // FEEDBACK LINK — available from check-in onward so it can be resent if missed.
            if (['Checked In', 'Checked Out'].includes(frm.doc.status)) {
                frm.add_custom_button(__('Send Feedback Link (WhatsApp)'), function () {
                    prompt_feedback_whatsapp(frm);
                }, __('Guest'));
            }

            // Quick Access to Folio
            if (frm.doc.folio) {
                frm.add_custom_button(__('Open Folio'), function () {
                    frappe.set_route('Form', 'Guest Folio', frm.doc.folio);
                }, 'View');
            }

        }

        set_reservation_read_only_state(frm);

        // Stays always run from the standard check-in to the standard check-out time
        // (Hospitality Accounting Settings) and rooms are allocated by night, so the
        // times are shown, not typed.
        ['arrival_time', 'departure_time'].forEach((f) => {
            frm.set_df_property(f, 'read_only', 1);
            frm.set_df_property(f, 'description', __('From Hospitality Accounting Settings'));
        });

        // ROOM MOVE BUTTON
        // Extend Stay — the planned counterpart to the night audit's overstay handler,
        // which only fires at 2 PM and cannot be used to agree an extra night at the desk.
        if (!frm.is_new() && ['Reserved', 'Checked In', 'No Show'].includes(frm.doc.status)) {
            const stay = frappe.hospitality.stay;
            const done = { on_done: () => frm.reload_doc() };
            const in_house = frm.doc.status === 'Checked In';
            frm.add_custom_button(in_house ? __('Extend / Change Dates') : __('Change Dates'),
                () => stay.change_dates(frm.doc.name, Object.assign({ extend: in_house }, done)), __('Stay'));
            frm.add_custom_button(__('Take Payment'), () => stay.take_payment(frm.doc.name, done), __('Stay'));
            if (in_house) {
                frm.add_custom_button(__('Add Charge'), () => stay.add_charge(frm.doc.name, done), __('Stay'));
            }
            if (frm.doc.status !== 'No Show') {
                frm.add_custom_button(__('Move Room'), () => stay.move_room(frm.doc.name, done), __('Stay'));
            }
            if (!in_house) {
                frm.add_custom_button(__('Cancel Stay'), () => stay.cancel(frm.doc.name, done), __('Stay'));
            }
        }

        if (!frm.is_new()) {
            frm.add_custom_button(__('Open in Front Desk'), function () {
                frappe.route_options = { reservation: frm.doc.name };
                frappe.set_route('hotel-pos');
            }, 'View');
        }

        if (frm.doc.folio && !frm.is_new()) {
            frm.add_custom_button(__('Print Bill'), function () {
                frappe.hospitality.stay.print_bill(frm.doc.folio);
            }, 'View');
        }

        if (frm.doc.hotel_booking) {
            frm.add_custom_button(__('Booking'), function () {
                frappe.set_route('Form', 'Hotel Booking', frm.doc.hotel_booking);
            });
        }

    },

    room_type: function (frm) {
        if (frm.__syncing_room_type) {
            return;
        }

        // Clear room if type changes
        frm.set_value('room', '');
    },

    arrival_date: function (frm) {
        calculate_nights(frm);
        validate_room_availability(frm);
        render_room_rate_preview(frm);
    },

    departure_date: function (frm) {
        calculate_nights(frm);
        validate_room_availability(frm);
    },
    
    room: function (frm) {
        sync_room_type_from_room(frm);
        render_room_rate_preview(frm);
        render_room_details(frm);
    },

    room_type: function (frm) {
        render_room_details(frm);
    },

    adults: function (frm) {
        render_room_details(frm);
    },

    children: function (frm) {
        render_room_details(frm);
    },

    agreed_rate: function (frm) {
        // Typing a rate here is an agreement with the guest: flag it so the night audit
        // bills this figure instead of the room type's tariff.
        frm.set_value('is_rate_overridden', flt(frm.doc.agreed_rate) ? 1 : 0);
        render_room_rate_preview(frm);
    },

    extra_beds_adult: function (frm) {
        render_room_rate_preview(frm);
        render_room_details(frm);
    },

    extra_beds_child: function (frm) {
        render_room_rate_preview(frm);
        render_room_details(frm);
    },
    
    rate_plan: function (frm) {
        render_room_rate_preview(frm);
    },
    
    discount_type: function (frm) {
        render_room_rate_preview(frm);
    },
    
    discount_value: function (frm) {
        render_room_rate_preview(frm);
    },
    
    is_complimentary: function (frm) {
        render_room_rate_preview(frm);
    }
});

/* The room's capacity, amenities and tariff, shown beside the room field so the desk can
 * answer "how many fit" and "does it have a TV" without opening the Room Type. */
function render_room_details(frm) {
    const room_type = frm.doc.room_type;
    if (!room_type) {
        const field = frm.get_field('room_details_preview');
        if (field && field.$wrapper) field.$wrapper.empty();
        return;
    }

    frappe.hospitality.room_details.get(room_type).then((t) => {
        const field = frm.get_field('room_details_preview');
        if (!field || !field.$wrapper) return;

        let html = frappe.hospitality.room_details.card(t);

        // Over capacity is sold with extra beds, so show what is needed and what it
        // costs rather than treating it as an error.
        const guests = cint(frm.doc.adults) + cint(frm.doc.children);
        const beds = cint(frm.doc.extra_beds_adult) + cint(frm.doc.extra_beds_child);
        const cap = cint(t && t.max_occupancy);

        if (cap && guests > cap + beds) {
            const short = guests - cap - beds;
            const cost =
                short * flt(t.extra_bed_adult_rate) * Math.max(frm.doc.nights || 1, 1);
            html += `<div class="hc-quote-note">🛏 ${__(
                '{0} guest(s) over the {1} this room sleeps. Add {0} extra bed(s) — about {2} for the stay.',
                [short, cap, format_currency(cost)]
            )}</div>`;
        } else if (beds) {
            html += `<div class="hc-quote-note">🛏 ${__(
                '{0} extra bed(s) on this reservation, charged every night.',
                [beds]
            )}</div>`;
        }

        if (cint(frm.doc.is_rate_overridden) && flt(frm.doc.agreed_rate)) {
            html += `<div class="hc-quote-note">${__(
                'Agreed rate of {0} per night — the tariff does not apply to this stay.',
                [format_currency(frm.doc.agreed_rate)]
            )}</div>`;
        }

        field.$wrapper.html(html);
    });
}

function sync_room_type_from_room(frm) {
    if (!frm.doc.room) {
        return;
    }

    frappe.db.get_value('Hotel Room', frm.doc.room, 'room_type').then(r => {
        let room_type = r.message ? r.message.room_type : null;
        if (!room_type || frm.doc.room_type === room_type) {
            return;
        }

        frm.__syncing_room_type = true;
        return frm.set_value('room_type', room_type).then(() => {
            frm.__syncing_room_type = false;
            render_room_rate_preview(frm);
        });
    });
}

function set_reservation_read_only_state(frm) {
    if (!frm.fields_dict) return;

    let exceptions = [];
    if (frm.doc.status === 'Checked In') {
        exceptions = [
            'departure_date',
            'departure_time',
            'discount_value',
            'is_company_guest',
            'company',
            'allow_pos_posting'
        ];
    }

    let should_lock = ['Checked In', 'Checked Out', 'Cancelled'].includes(frm.doc.status);

    Object.keys(frm.fields_dict).forEach(fieldname => {
        let field = frm.fields_dict[fieldname];
        if (!field || !field.df) return;

        let is_readonly = fieldname === 'status' || (should_lock && !exceptions.includes(fieldname));
        frm.set_df_property(fieldname, 'read_only', is_readonly ? 1 : 0);
    });
}

function render_room_rate_preview(frm) {
    if (!frm.fields_dict.room_rate_preview) return;
    
    let wrapper = frm.fields_dict.room_rate_preview.$wrapper;
    
    if (!frm.doc.room) {
        wrapper.html("<div class='text-muted small'>Select a room to see rate.</div>");
        return;
    }
    
    // Show loading state
    wrapper.html("<div class='text-muted small'>Calculating rate...</div>");
    
    frappe.call({
        method: "hospitality_core.hospitality_core.api.reservation.get_room_rate",
        args: {
            room: frm.doc.room,
            rate_plan: frm.doc.rate_plan,
            room_type: frm.doc.room_type,
            arrival_date: frm.doc.arrival_date,
            discount_type: frm.doc.discount_type,
            discount_value: frm.doc.discount_value,
            is_complimentary: frm.doc.is_complimentary,
            // Extra beds and an agreed rate both change what the night audit will post,
            // so the preview has to account for them or it contradicts the folio.
            extra_beds_adult: frm.doc.extra_beds_adult || 0,
            extra_beds_child: frm.doc.extra_beds_child || 0,
            agreed_rate: frm.doc.agreed_rate || 0,
            is_rate_overridden: frm.doc.is_rate_overridden || 0
        },
        callback: function(r) {
            if (r.message) {
                let d = r.message;
                let currency = frappe.boot.sysdefaults.currency;
                
                let html = `<div style="padding: 15px; border: 1px solid #d1d8dd; border-radius: 4px; background-color: #f7fafc;">
                    <div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                        <span class="text-muted">Base Rate:</span>
                        <span style="font-weight: 500;">${format_currency(d.base_rate, currency)}</span>
                    </div>`;
                    
                if (d.extra_bed_amount > 0) {
                    html += `<div style="display: flex; justify-content: space-between; margin-bottom: 5px;">
                        <span class="text-muted">Extra Beds (incl. above):</span>
                        <span>${format_currency(d.extra_bed_amount, currency)}</span>
                    </div>`;
                }

                if (d.discount_amount > 0) {
                    html += `<div style="display: flex; justify-content: space-between; margin-bottom: 5px; color: #e74c3c;">
                        <span>Discount:</span>
                        <span>- ${format_currency(d.discount_amount, currency)}</span>
                    </div>`;
                }
                
                html += `<div style="display: flex; justify-content: space-between; margin-top: 10px; padding-top: 10px; border-top: 1px solid #d1d8dd;">
                        <span style="font-weight: 600; font-size: 1.1em;">Final Rate / Night:</span>
                        <span style="font-weight: 700; font-size: 1.1em; color: #2ecc71;">${format_currency(d.final_rate, currency)}</span>
                    </div>
                </div>`;
                
                wrapper.html(html);
            }
        }
    });
}

function calculate_nights(frm) {
    if (frm.doc.arrival_date && frm.doc.departure_date) {
        var diff = frappe.datetime.get_diff(frm.doc.departure_date, frm.doc.arrival_date);
        if (diff < 1) {
            frappe.msgprint("Departure must be after Arrival");
        }
    }
}

function validate_room_availability(frm) {
    if (frm.doc.room && frm.doc.arrival_date && frm.doc.departure_date) {
        frappe.call({
            method: "hospitality_core.hospitality_core.api.reservation.check_availability",
            args: {
                room: frm.doc.room,
                arrival_date: frm.doc.arrival_date,
                departure_date: frm.doc.departure_date,
                ignore_reservation: frm.doc.name
            },
            callback: function (r) {
                if (r.exc) {
                    frm.set_value('room', '');
                }
            }
        });
    }
}
// --- GUEST FEEDBACK HAND-OFF ----------------------------------------------------------
// Opens a wa.me redirect carrying a pre-written message and the guest's feedback link.
// Nothing is sent from the server: the staff member sends it from their own WhatsApp,
// so this works without any WhatsApp Business API account.
function prompt_feedback_whatsapp(frm) {
    frappe.call({
        method: 'hospitality_core.hospitality_core.api.feedback.get_whatsapp_feedback_link',
        args: { reservation: frm.doc.name },
        freeze: true,
        freeze_message: __('Preparing feedback link...'),
        callback: function (r) {
            if (r.exc || !r.message) {
                return;
            }
            show_feedback_whatsapp_dialog(r.message);
        }
    });
}

function show_feedback_whatsapp_dialog(data) {
    const dialog = new frappe.ui.Dialog({
        title: __('Send Feedback Link'),
        fields: [
            {
                fieldname: 'mobile_no',
                fieldtype: 'Data',
                label: __('Guest WhatsApp Number'),
                default: data.mobile_no || '',
                reqd: 1,
                description: __('Include the country code, e.g. 919876543210.')
            },
            {
                fieldname: 'no_mobile_warning',
                fieldtype: 'HTML',
                options: data.has_mobile
                    ? ''
                    : `<p class="text-muted small">${__(
                        'No mobile number is saved for this guest. Enter one to continue.'
                    )}</p>`
            },
            { fieldname: 'sb', fieldtype: 'Section Break' },
            {
                fieldname: 'message',
                fieldtype: 'Small Text',
                label: __('Message'),
                default: data.message,
                description: __('Edit if you like — this is what WhatsApp will open with.')
            },
            {
                fieldname: 'link_html',
                fieldtype: 'HTML',
                options: `<p class="text-muted small">${__('Feedback link')}:
                    <a href="${frappe.utils.escape_html(data.feedback_url)}" target="_blank"
                       rel="noopener">${frappe.utils.escape_html(data.feedback_url)}</a></p>`
            }
        ],
        primary_action_label: __('Open WhatsApp'),
        primary_action: function (values) {
            const digits = (values.mobile_no || '').replace(/\D/g, '');
            if (!digits) {
                frappe.msgprint(__('Enter the guest\'s WhatsApp number, including the country code.'));
                return;
            }
            dialog.hide();
            // Opened from this click so the browser does not treat it as a pop-up.
            window.open(
                `https://wa.me/${digits}?text=${encodeURIComponent(values.message || data.message)}`,
                '_blank',
                'noopener'
            );
        },
        secondary_action_label: __('Copy Link'),
        secondary_action: function () {
            frappe.utils.copy_to_clipboard(data.feedback_url);
        }
    });

    dialog.show();
}
