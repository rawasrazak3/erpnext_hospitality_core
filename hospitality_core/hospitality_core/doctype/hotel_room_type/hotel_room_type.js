frappe.ui.form.on('Hotel Room Type', {
	refresh(frm) {
		frm.trigger('show_unit_count');
		frm.trigger('warn_on_occupancy_split');
	},

	max_occupancy(frm) {
		// The adult/child figures are advisory, but letting either exceed the ceiling
		// puts two different capacity answers on the same screen.
		['max_adults', 'max_children'].forEach((field) => {
			if (frm.doc[field] > frm.doc.max_occupancy) {
				frm.set_value(field, frm.doc.max_occupancy);
			}
		});
		frm.trigger('warn_on_occupancy_split');
	},

	warn_on_occupancy_split(frm) {
		frm.get_field('max_occupancy').set_description(
			__('Maximum total guests (adults + children) allowed in the room.')
		);
	},

	show_unit_count(frm) {
		if (frm.is_new()) return;

		frappe.db.get_list('Hotel Room', {
			filters: { room_type: frm.doc.name },
			fields: ['name', 'status'],
			limit: 100,
		}).then((rooms) => {
			if (!rooms.length) {
				frm.dashboard.add_comment(
					__('No units are assigned to this category yet.'), 'orange', true
				);
				return;
			}

			const blocked = rooms.filter(
				(r) => ['Maintenance', 'Out of Order'].includes(r.status)
			);
			const names = rooms.map((r) => r.name).join(', ');

			frm.dashboard.add_comment(
				__('{0} unit(s): {1}', [rooms.length, names]), 'blue', true
			);

			if (blocked.length) {
				frm.dashboard.add_comment(
					__('{0} unit(s) blocked and not allocatable: {1}', [
						blocked.length,
						blocked.map((r) => `${r.name} (${r.status})`).join(', '),
					]),
					'orange',
					true
				);
			}
		});
	},
});
