"""A physical, sellable unit. The property names its units rather than numbering them
("Pinnacle Suite", "Red Hut", "Germany"), so `room_number` holds that name.

`BLOCKED_STATUSES` is the single definition of "this room cannot be given to a guest".
Availability, the reservation guards, the POS, the tape chart and the end-of-day report
all read it, so adding a new blocking status here is enough to have every one of them
honour it.
"""

import frappe
from frappe import _
from frappe.model.document import Document

# Statuses that take a room out of allocation. Occupied and Dirty are deliberately not
# here: Occupied is derived from reservations (blocking one would double-count), and a
# Dirty room is still sellable once housekeeping turns it around.
BLOCKED_STATUSES = ("Maintenance", "Out of Order")

# What a blocked room is blocked by, for messages shown to the front desk.
BLOCKED_STATUS_REASON = {
	"Maintenance": _("Room {0} is under Maintenance."),
	"Out of Order": _("Room {0} is marked Out of Order."),
}


def is_blocked(status):
	return status in BLOCKED_STATUSES


def blocked_reason(room, status):
	"""Human-readable reason, or None if the status does not block."""
	if not is_blocked(status):
		return None
	return BLOCKED_STATUS_REASON.get(status, _("Room {0} is unavailable.")).format(room)


class HotelRoom(Document):
	def validate(self):
		self.guard_blocking_status()

	def guard_blocking_status(self):
		"""Refuse to block a room that someone is currently standing in. The front desk
		has to move or check the guest out first, otherwise the room would be both
		occupied and unallocatable and the tape chart would disagree with reality."""
		if self.status not in BLOCKED_STATUSES:
			return

		previous = self.get_doc_before_save()
		if previous and previous.status == self.status:
			return

		occupant = frappe.db.get_value(
			"Hotel Reservation",
			{"room": self.name, "status": "Checked In"},
			["name", "guest"],
			as_dict=True,
		)
		if occupant:
			frappe.throw(
				_("Room {0} cannot be set to {1}: {2} is checked in on {3}. "
				  "Move or check out the guest first.").format(
					self.name, _(self.status), occupant.guest, occupant.name
				)
			)
