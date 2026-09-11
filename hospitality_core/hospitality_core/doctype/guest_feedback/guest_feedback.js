frappe.ui.form.on('Guest Feedback', {
    refresh: function (frm) {
        if (frm.doc.needs_follow_up && frm.doc.status !== 'Closed') {
            frm.dashboard.set_headline_alert(
                __('This guest reported a problem. Review and action it before closing.'),
                'orange'
            );
        }

        if (frm.doc.reservation) {
            frm.add_custom_button(__('Reservation'), function () {
                frappe.set_route('Form', 'Hotel Reservation', frm.doc.reservation);
            }, __('View'));
        }

        // Turn a complaint into a work order without retyping it.
        if (!frm.is_new() && frm.doc.room && frm.doc.needs_follow_up) {
            frm.add_custom_button(__('Maintenance Request'), function () {
                frappe.new_doc('Hotel Maintenance Request', {
                    room: frm.doc.room,
                    description: build_issue_summary(frm.doc)
                });
            }, __('Create'));
        }
    }
});

function build_issue_summary(doc) {
    const lines = (doc.issues || []).map(
        (row) => `${row.area}: ${row.details || __('No detail given')}`
    );
    if (doc.improvements) {
        lines.push(__('Guest comment') + ': ' + doc.improvements);
    }
    lines.push(__('Reported via Guest Feedback {0}', [doc.name]));
    return lines.join('\n');
}
