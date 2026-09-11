# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""Hotel Booking — the advance-booking container.

One Hotel Reservation is one room and one folio, so a three-room phone booking is three
reservations and three folios while the advance is a single payment. Hotel Booking is the
object that owns the guest, the stay window, the rooms and the money, and fans out into
reservations when it is confirmed.

Deliberate design choice: confirming a booking creates REAL Hotel Reservation rows in
status `Reserved`. Everything downstream — availability, folio creation, the night audit,
check-in, POS room charging — already understands those, so none of it had to change.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime, nowdate

from hospitality_core.hospitality_core.api import availability, tariff

# Statuses from which a booking may still be confirmed.
CONFIRMABLE = ("Draft", "Tentative")
# Statuses where reservations should exist.
LIVE = ("Confirmed", "Checked In")


class HotelBooking(Document):
	def validate(self):
		self.validate_dates()
		self.calculate_totals()
		self.validate_capacity()
		self.validate_rooms()

	def before_insert(self):
		if not self.hotel_reception:
			self.hotel_reception = frappe.db.get_value("Hotel Reception", {}, "name")
		if not self.booking_source and self.enquiry:
			self.booking_source = frappe.db.get_value("Hotel Enquiry", self.enquiry, "source")

	def on_trash(self):
		if self.status not in ("Draft", "Cancelled"):
			frappe.throw(_("Only a Draft or Cancelled booking can be deleted."))
		if self.booking_folio and frappe.db.exists(
			"Folio Transaction", {"parent": self.booking_folio}
		):
			frappe.throw(_("This booking has money on its folio and cannot be deleted."))

	# ------------------------------------------------------------------ validation
	def validate_dates(self):
		if not (self.arrival_date and self.departure_date):
			return
		if getdate(self.departure_date) <= getdate(self.arrival_date):
			frappe.throw(_("Departure must be after arrival."))
		self.nights = (getdate(self.departure_date) - getdate(self.arrival_date)).days

	def calculate_totals(self):
		"""Price every line for the actual stay window, not rate x nights.

		The property charges more Friday through Sunday, so a flat multiplication
		understates any stay touching a weekend. `quote_stay` walks the nights and the
		line's `rate` is set to the resulting average, which keeps the stored
		`rate x qty x nights` arithmetic true for anything reading the row later.
		"""
		total = 0.0
		for line in self.rooms:
			line.nights = cint(self.nights)

			quote = self._quote_line(line)
			if quote:
				line.rate = quote["average_nightly"]
				line.amount = quote["total"]
			else:
				line.amount = flt(line.rate) * max(cint(line.qty), 1) * max(cint(line.nights), 1)

			total += flt(line.amount)

		self.total_amount = total
		self.advance_received = sum(
			flt(p.amount) if p.payment_type == "Advance" else -flt(p.amount)
			for p in self.payments
		)
		self.balance_due = flt(self.total_amount) - flt(self.advance_received)

	def _quote_line(self, line):
		"""Server-priced quote for one room line, or None if it cannot be priced yet."""
		if not (line.room_type and self.arrival_date and self.departure_date):
			return None
		if getdate(self.departure_date) <= getdate(self.arrival_date):
			return None
		try:
			return tariff.quote_stay(
				line.room_type, self.arrival_date, self.departure_date,
				qty=line.qty, adults=line.adults, children=line.children,
				extra_beds_adult=line.get("extra_beds_adult"),
				extra_beds_child=line.get("extra_beds_child"),
			)
		except Exception:
			# A category with a broken tariff should not block saving the booking;
			# the line falls back to whatever rate the agent typed.
			frappe.log_error(
				f"Could not price {line.room_type} on {self.name}", "Hotel Booking pricing"
			)
			return None

	def validate_capacity(self):
		"""Refuse to sell a room to more people than it holds.

		Caught here rather than at check-in, which is where the guest finds out.
		"""
		for line in self.rooms:
			if not line.room_type:
				continue
			max_occupancy = cint(
				frappe.db.get_value("Hotel Room Type", line.room_type, "max_occupancy")
			)
			if not max_occupancy:
				continue

			capacity = max_occupancy * max(cint(line.qty), 1)
			beds = cint(line.get("extra_beds_adult")) + cint(line.get("extra_beds_child"))
			guests = cint(line.adults) + cint(line.children)

			if guests > capacity + beds:
				frappe.throw(
					_("Row {0}: {1} guests exceed the {2} that {3} x {4} allows. "
					  "Add another room, or {5} extra bed(s).").format(
						line.idx, guests, capacity, max(cint(line.qty), 1),
						line.room_type, guests - capacity - beds,
					)
				)

	def validate_rooms(self):
		"""A line with a room assigned must actually be free, and no room twice."""
		seen = set()
		for line in self.rooms:
			if not line.room:
				continue
			if line.room in seen:
				frappe.throw(_("Room {0} appears twice on this booking.").format(line.room))
			seen.add(line.room)

			if cint(line.qty) > 1:
				frappe.throw(
					_("Row {0}: a line with a specific room must have Rooms = 1. "
					  "Use one line per assigned room.").format(line.idx)
				)

			# A line already turned into a reservation is blocked by that reservation,
			# so exclude it or it would clash with itself.
			result = availability.is_room_free(
				line.room, self.arrival_date, self.departure_date,
				self.arrival_time, self.departure_time,
				ignore_reservation=line.reservation,
			)
			if not result["free"]:
				frappe.throw(_("Row {0}: {1}").format(line.idx, result["reason"]))

	# ------------------------------------------------------------------ folio
	def ensure_booking_folio(self):
		"""The folio advances land on before any room folio exists.

		Flagged `is_booking_master` so revenue recognition skips it — money here is a
		liability until the guest arrives, not income.
		"""
		if self.booking_folio and frappe.db.exists("Guest Folio", self.booking_folio):
			return self.booking_folio

		folio = frappe.get_doc({
			"doctype": "Guest Folio",
			"guest": self.guest,
			"hotel_booking": self.name,
			"is_booking_master": 1,
			"hotel_reception": self.hotel_reception,
			"status": "Open",
			"open_date": nowdate(),
		})
		folio.insert(ignore_permissions=True)
		self.db_set("booking_folio", folio.name)
		return folio.name

	# ------------------------------------------------------------------ transitions
	def set_tentative(self, hold_hours=24):
		if self.status not in ("Draft", "Tentative"):
			frappe.throw(_("Only a Draft booking can be put on hold."))
		self.db_set("status", "Tentative")
		self.db_set("hold_expiry", frappe.utils.add_to_date(now_datetime(), hours=cint(hold_hours)))
		return self.status

	def confirm(self):
		"""Assign rooms, create reservations, open the booking folio."""
		if self.status not in CONFIRMABLE:
			frappe.throw(_("Only a Draft or Tentative booking can be confirmed."))
		if not self.rooms:
			frappe.throw(_("Add at least one room before confirming."))

		self.assign_pending_rooms()
		self.reload()
		self.create_reservations()
		self.ensure_booking_folio()
		self.db_set("status", "Confirmed")
		self.db_set("hold_expiry", None)

		if self.enquiry:
			self.mark_enquiry_converted()

		return self.name

	def assign_pending_rooms(self):
		"""Turn room-type holds into concrete rooms.

		A line with qty > 1 is expanded into one line per room, because a reservation is
		always exactly one room.
		"""
		taken = {line.room for line in self.rooms if line.room}
		expanded = []

		for line in self.rooms:
			if line.room:
				expanded.append(line.as_dict())
				continue

			rooms = availability.assign_rooms(
				line.room_type, line.qty, self.arrival_date, self.departure_date,
				self.arrival_time, self.departure_time,
				ignore_booking=self.name, exclude=taken,
			)
			for room in rooms:
				taken.add(room)
				row = line.as_dict()
				row.update({"name": None, "room": room, "qty": 1})
				expanded.append(row)

		self.set("rooms", [])
		for row in expanded:
			row.pop("idx", None)
			self.append("rooms", row)
		self.save(ignore_permissions=True)

	def create_reservations(self):
		"""One Hotel Reservation per assigned room. Idempotent."""
		for line in self.rooms:
			if line.reservation and frappe.db.exists("Hotel Reservation", line.reservation):
				continue
			if not line.room:
				frappe.throw(_("Row {0} has no room assigned.").format(line.idx))

			reservation = frappe.get_doc({
				"doctype": "Hotel Reservation",
				"guest": self.guest,
				"room": line.room,
				"room_type": line.room_type,
				"hotel_reception": self.hotel_reception,
				"arrival_date": self.arrival_date,
				"arrival_time": self.arrival_time,
				"departure_date": self.departure_date,
				"departure_time": self.departure_time,
				"adults": line.adults or self.adults,
				"children": line.children or self.children,
				"status": "Reserved",
				"hotel_booking": self.name,
				"hotel_enquiry": self.enquiry,
				"booking_source": self.booking_source,
			})
			reservation.insert(ignore_permissions=True)
			line.db_set("reservation", reservation.name)

	def mark_enquiry_converted(self):
		frappe.db.set_value("Hotel Enquiry", self.enquiry, {
			"converted": 1,
			"hotel_booking": self.name,
			"guest": self.guest,
		})
		won = frappe.db.get_value(
			"Hotel Enquiry Status", {"type": "Won"}, "name", order_by="position asc"
		)
		if won:
			enquiry = frappe.get_doc("Hotel Enquiry", self.enquiry)
			enquiry.status = won
			enquiry.save(ignore_permissions=True)

	def cancel_booking(self, reason=None, cancellation_charge=0):
		if self.status in ("Cancelled", "Completed"):
			frappe.throw(_("This booking is already {0}.").format(self.status))

		for line in self.rooms:
			if not line.reservation:
				continue
			reservation = frappe.get_doc("Hotel Reservation", line.reservation)
			if reservation.status in ("Reserved", "Checked In"):
				reservation.process_cancel()

		self.db_set("status", "Cancelled")
		if cancellation_charge:
			self.db_set("cancellation_charge", flt(cancellation_charge))
		if reason:
			self.add_comment("Info", _("Cancelled: {0}").format(reason))

		self.release_enquiry(_("Booking {0} was cancelled.").format(self.name))
		return self.status

	def release_enquiry(self, note):
		"""Detach the enquiry so the agent can book it again.

		A cancelled or expired booking used to stay linked to its enquiry, which left the
		enquiry marked Won while pointing at a dead booking — and the console's Create
		Booking button would just reopen the cancelled one, so the guest could never be
		re-booked without editing the record by hand.
		"""
		if not self.enquiry or not frappe.db.exists("Hotel Enquiry", self.enquiry):
			return

		frappe.db.set_value("Hotel Enquiry", self.enquiry, {
			"hotel_booking": None,
			"converted": 0,
		})

		# Put it back into the pipeline rather than leaving it sitting in a Won stage.
		current = frappe.db.get_value("Hotel Enquiry", self.enquiry, "status")
		if frappe.db.get_value("Hotel Enquiry Status", current, "type") == "Won":
			reopen = frappe.db.get_value(
				"Hotel Enquiry Status", {"type": "Ongoing"}, "name", order_by="position desc"
			) or frappe.db.get_value(
				"Hotel Enquiry Status", {"type": "Open"}, "name", order_by="position asc"
			)
			if reopen:
				frappe.db.set_value("Hotel Enquiry", self.enquiry, "status", reopen)
				frappe.db.set_value("Hotel Enquiry", self.enquiry, "status_type",
				                    frappe.db.get_value("Hotel Enquiry Status", reopen, "type"))

		frappe.get_doc("Hotel Enquiry", self.enquiry).add_comment("Info", note)

	def sync_status_from_reservations(self):
		"""Advance the booking as its rooms move through their stay.

		Nothing used to close a booking: once checked in it stayed 'Checked In' forever,
		even after every guest had left. That kept finished stays sitting in the Advance
		Liability Register and made 'in house' counts wrong.
		"""
		if self.status in ("Cancelled", "Draft"):
			return

		states = [
			frappe.db.get_value("Hotel Reservation", line.reservation, "status")
			for line in self.rooms
			if line.reservation
		]
		if not states:
			return

		live = [s for s in states if s not in ("Checked Out", "Cancelled", "No Show")]

		if not live:
			# Every room has left, been cancelled, or was a no-show.
			settled = "Completed" if any(s == "Checked Out" for s in states) else "Cancelled"
			if self.status != settled:
				self.db_set("status", settled)
		elif any(s == "Checked In" for s in states) and self.status != "Checked In":
			self.db_set("status", "Checked In")


# ---------------------------------------------------------------------- whitelisted
@frappe.whitelist()
def confirm_booking(booking):
	doc = frappe.get_doc("Hotel Booking", booking)
	doc.check_permission("write")
	return doc.confirm()


@frappe.whitelist()
def hold_booking(booking, hold_hours=24):
	doc = frappe.get_doc("Hotel Booking", booking)
	doc.check_permission("write")
	return doc.set_tentative(hold_hours)


@frappe.whitelist()
def cancel_booking(booking, reason=None, cancellation_charge=0):
	doc = frappe.get_doc("Hotel Booking", booking)
	doc.check_permission("write")
	return doc.cancel_booking(reason, cancellation_charge)


def release_expired_holds():
	"""Scheduled: drop Tentative holds whose expiry has passed so the rooms free up."""
	expired = frappe.get_all(
		"Hotel Booking",
		filters={
			"status": "Tentative",
			"hold_expiry": ["<", now_datetime()],
		},
		pluck="name",
	)
	for name in expired:
		try:
			booking = frappe.get_doc("Hotel Booking", name)
			# A hold that took money is a real commitment; leave it for a human.
			if flt(booking.advance_received) > 0:
				continue
			booking.db_set("status", "Cancelled")
			booking.add_comment("Info", _("Hold expired at {0} and was released.").format(
				booking.hold_expiry
			))
			booking.release_enquiry(
				_("Tentative hold {0} expired and the rooms were released.").format(booking.name)
			)
		except Exception:
			frappe.log_error(f"Could not release expired hold {name}", "Hotel Booking hold release")

	# No explicit commit: the scheduler commits after a successful job, and committing
	# here would end whatever transaction the caller is in — which silently defeated the
	# rollback in the test suites and leaked records onto the live site.
	return len(expired)


def sync_booking_for_reservation(reservation_name):
	"""Called when a reservation checks out or is cancelled, to move its booking on."""
	booking = frappe.db.get_value("Hotel Reservation", reservation_name, "hotel_booking")
	if not booking or not frappe.db.exists("Hotel Booking", booking):
		return
	try:
		frappe.get_doc("Hotel Booking", booking).sync_status_from_reservations()
	except Exception:
		# A booking bookkeeping failure must never block a guest checking out.
		frappe.log_error(
			f"Could not sync booking {booking} from reservation {reservation_name}",
			"Hotel Booking status sync",
		)
