frappe.listview_settings['Guest Feedback'] = {
    add_fields: ['status', 'needs_follow_up', 'overall_rating'],
    get_indicator: function (doc) {
        if (doc.status === 'Closed') {
            return [__('Closed'), 'gray', 'status,=,Closed'];
        }
        if (doc.needs_follow_up) {
            return [__('Needs Follow-up'), 'red', 'needs_follow_up,=,1'];
        }
        if (doc.status === 'Actioned') {
            return [__('Actioned'), 'green', 'status,=,Actioned'];
        }
        if (doc.status === 'Under Review') {
            return [__('Under Review'), 'blue', 'status,=,Under Review'];
        }
        return [__('New'), 'orange', 'status,=,New'];
    }
};
