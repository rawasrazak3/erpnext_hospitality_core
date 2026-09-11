import frappe
from frappe import _
from frappe.model.document import Document

from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import BLOCKED_STATUSES

class HotelMaintenanceRequest(Document):
	def recalculate_total_expenses(self):
		total = frappe.db.sql("""
			SELECT SUM(grand_total) 
			FROM `tabHospitality Expense` 
			WHERE maintenance_request = %s AND docstatus = 1
		""", (self.name))[0][0] or 0.0
		self.db_set("total_expenses", total)

	def validate(self):
		if self.status == "Completed" and not self.resolution_notes:
			frappe.throw(_("Please enter Resolution Notes before marking as Completed."))

	def on_update(self):
		self.update_room_status()

	def update_room_status(self):
		"""Keep the room's status in step with the request.

		An open request puts the room into 'Maintenance', which blocks allocation.
		'Out of Order' is left alone: that is the manual, longer-term block a manager
		sets by hand, and a routine work order finishing should not quietly lift it.
		"""
		if not frappe.db.get_value("Hotel Room", self.room, "is_enabled"):
			return

		current_room_status = frappe.db.get_value("Hotel Room", self.room, "status")

		if self.status in ("Reported", "In Progress"):
			# Already blocked (either way) — nothing to do.
			if current_room_status in BLOCKED_STATUSES:
				return

			occupant = frappe.db.exists(
				"Hotel Reservation", {"room": self.room, "status": "Checked In"}
			)
			if occupant:
				# The guest is physically in the room, so blocking it would make the
				# tape chart lie. Flag it instead and let the front desk move them.
				frappe.msgprint(_(
					"Room {0} has a guest checked in, so it has not been blocked. "
					"Move or check out the guest, then set the room to Maintenance."
				).format(self.room), indicator="orange", alert=True)
				return

			frappe.db.set_value("Hotel Room", self.room, "status", "Maintenance")
			frappe.msgprint(
				_("Room {0} marked as 'Maintenance' and will not be offered for allocation.")
				.format(self.room)
			)

		elif self.status in ("Completed", "Cancelled"):
			# Only release what this workflow blocked.
			if current_room_status == "Maintenance":
				if self.has_other_open_requests():
					return
				frappe.db.set_value("Hotel Room", self.room, "status", "Dirty")
				frappe.msgprint(
					_("Room {0} released from Maintenance and marked 'Dirty' for cleaning.")
					.format(self.room)
				)

	def has_other_open_requests(self):
		"""Another open work order on the same room keeps it blocked."""
		return bool(frappe.db.exists("Hotel Maintenance Request", {
			"room": self.room,
			"status": ["in", ("Reported", "In Progress")],
			"name": ["!=", self.name],
		}))