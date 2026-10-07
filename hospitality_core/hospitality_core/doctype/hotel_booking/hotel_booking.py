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

from hospitality_core.hospitality_core.api import availability, stay_policy, tariff

# Statuses from which a booking may still be confirmed.
CONFIRMABLE = ("Draft", "Tentative")
# Statuses where reservations should exist.
LIVE = ("Confirmed", "Checked In")


def _share(total, parts, index):
	"""`total` divided `parts` ways, with the remainder going to the earlier rooms."""
	total, parts = cint(total), max(cint(parts), 1)
	return total // parts + (1 if index < total % parts else 0)


def _split_line(line, room_count):
	"""Per-room shares of everything a booking line counts per line.

	Guests and beds are divided rather than copied: three rooms held for six guests
	would otherwise each claim all six, and the booking would bill three times the beds.
	"""
	room_count = max(cint(room_count), 1)
	return [
		{
			"adults": _share(line.get("adults"), room_count, i),
			"children": _share(line.get("children"), room_count, i),
			"extra_beds_adult": _share(line.get("extra_beds_adult"), room_count, i),
			"extra_beds_child": _share(line.get("extra_beds_child"), room_count, i),
		}
		for i in range(room_count)
	]


class HotelBooking(Document):
	def validate(self):
		self.validate_dates()
		# Every stay runs from the standard check-in time to the standard check-out time
		# (Hospitality Accounting Settings); rooms are allocated by night.
		from hospitality_core.hospitality_core.api.stay_policy import apply_stay_times
		apply_stay_times(self)
		self.calculate_totals()
		# A resync after a date move has nothing new to say about capacity or rooms, and
		# repeating the capacity notice on every check-in and extension is just noise.
		if not self.flags.skip_room_validation:
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

		The property charges more on weekends and holidays, so a flat multiplication
		understates any stay touching one. `quote_stay` walks the nights.

		A rate someone typed is an agreement with the guest, so a line marked
		`is_rate_overridden` keeps its rate and only has its amounts recomputed around
		it. Without that, saving the booking would silently undo what the agent agreed.

		The discount belongs to the booking rather than to a room line — one figure is
		agreed for the whole stay — so lines total to a subtotal and the discount comes
		off that once.
		"""
		from hospitality_core.hospitality_core.api.tariff import apply_discount

		subtotal = 0.0
		for line in self.rooms:
			arrival, departure = self._line_window(line)
			line.nights = (getdate(departure) - getdate(arrival)).days if arrival and departure else cint(self.nights)

			quote = self._quote_line(line)
			if quote:
				# Extra beds auto-fill for a party over capacity; write them back so the
				# booking records what the guest is actually being given.
				line.extra_beds_adult = quote["extra_beds_adult"]
				line.extra_beds_child = quote["extra_beds_child"]
				line.extra_bed_amount = quote["extra_bed_total"]
				line.amount = quote["gross_total"]
				if not cint(line.is_rate_overridden):
					# Room only — the beds are already in `extra_bed_amount` and in
					# `amount`. See HotelEnquiry.calculate_quote.
					line.rate = quote["average_room_nightly"]
			else:
				line.amount = flt(line.rate) * max(cint(line.qty), 1) * max(cint(line.nights), 1)
				line.extra_bed_amount = 0

			line.gross_amount = line.amount
			subtotal += flt(line.amount)

		self.total_before_discount = subtotal
		self.discount_amount, self.total_amount = apply_discount(
			subtotal, self.discount_type, self.discount_value
		)

		# Once rooms are reserved, the discount that counts is the one the folio posts:
		# each reservation carries it per night (see reservation_discount), so a stay
		# that is extended or shortened gets that discount on every night it actually
		# stays. Mirror it here, or the booking's balance due disagrees with the bill.
		if any(line.get("reservation") for line in self.rooms):
			discount = sum(self._posted_discount(line, subtotal) for line in self.rooms)
			discount = min(max(flt(discount, 2), 0.0), subtotal)
			self.discount_amount = discount
			self.total_amount = flt(subtotal - discount, 2)
		self.advance_received = sum(
			flt(p.amount) if p.payment_type == "Advance" else -flt(p.amount)
			for p in self.payments
		)
		self.balance_due = flt(self.total_amount) - flt(self.advance_received)

	def _posted_discount(self, line, subtotal):
		"""The discount this line's folio receives over its stay."""
		amount = flt(line.amount)
		if not line.get("reservation"):
			# Not reserved yet: its share of the booking-level discount.
			if not self.discount_type or flt(self.discount_value) <= 0 or subtotal <= 0:
				return 0.0
			if str(self.discount_type).strip() == "Percentage":
				return amount * min(flt(self.discount_value), 100.0) / 100.0
			return flt(self.discount_value) * amount / subtotal

		res = frappe.db.get_value(
			"Hotel Reservation", line.reservation,
			["discount_type", "discount_value", "is_complimentary", "status"], as_dict=True,
		) or {}
		if res.get("status") == "Cancelled":
			return 0.0
		if cint(res.get("is_complimentary")):
			return amount
		kind = str(res.get("discount_type") or "").strip()
		if kind == "Percentage":
			return amount * flt(res.get("discount_value")) / 100.0
		if kind == "Amount":
			return min(flt(res.get("discount_value")) * max(cint(line.nights), 1), amount)
		return 0.0

	def _line_window(self, line):
		"""The dates a room line is actually staying.

		Once a line has a reservation, that reservation is the truth: a stay extended at
		the desk, shortened by an early departure, or auto-extended by the night audit
		moves the reservation, and the booking has to be priced on what the guest is
		really staying — otherwise the booking total and balance due stay frozen at the
		original quote while the folio keeps charging.
		"""
		if line.get("reservation"):
			window = frappe.db.get_value(
				"Hotel Reservation", line.reservation,
				["arrival_date", "departure_date", "status"], as_dict=True,
			)
			if window and window.status not in ("Cancelled",):
				return window.arrival_date, window.departure_date
		return self.arrival_date, self.departure_date

	def _quote_line(self, line):
		"""Server-priced quote for one room line, or None if it cannot be priced yet."""
		arrival, departure = self._line_window(line)
		if not (line.room_type and arrival and departure):
			return None
		if getdate(departure) <= getdate(arrival):
			return None
		try:
			return tariff.quote_stay(
				line.room_type, arrival, departure,
				qty=line.qty, adults=line.adults, children=line.children,
				extra_beds_adult=line.get("extra_beds_adult"),
				extra_beds_child=line.get("extra_beds_child"),
				rate_override=line.rate if cint(line.get("is_rate_overridden")) else None,
			)
		except Exception:
			# A category with a broken tariff should not block saving the booking;
			# the line falls back to whatever rate the agent typed.
			frappe.log_error(
				f"Could not price {line.room_type} on {self.name}", "Hotel Booking pricing"
			)
			return None

	def validate_capacity(self):
		"""Tell the desk when a line is over capacity; never block the sale.

		The property sells over Max Allowed by putting in extra beds, so refusing the
		booking was wrong — `calculate_totals` has already added and priced the beds by
		the time this runs. All that is left is to say so, and to flag the one case the
		beds cannot fix: a category with no extra-bed rate set.
		"""
		for line in self.rooms:
			if not line.room_type:
				continue

			rates = frappe.db.get_value(
				"Hotel Room Type", line.room_type,
				["max_occupancy", "extra_bed_adult_rate", "extra_bed_child_rate"],
				as_dict=True,
			) or {}
			max_occupancy = cint(rates.get("max_occupancy"))
			if not max_occupancy:
				continue

			capacity = max_occupancy * max(cint(line.qty), 1)
			guests = cint(line.adults) + cint(line.children)
			beds = cint(line.get("extra_beds_adult")) + cint(line.get("extra_beds_child"))
			if guests <= capacity:
				continue

			if not (flt(rates.get("extra_bed_adult_rate")) or flt(rates.get("extra_bed_child_rate"))):
				frappe.msgprint(
					_("Row {0}: {1} guests exceed the {2} that {3} sleeps, and no extra "
					  "bed rate is set on that category, so the extra guests are not "
					  "being charged for.").format(
						line.idx, guests, capacity, line.room_type
					),
					indicator="orange", alert=True,
				)
				continue

			frappe.msgprint(
				_("Row {0}: {1} guests over the {2} that {3} sleeps — {4} extra bed(s) "
				  "added, {5}.").format(
					line.idx, guests, capacity, line.room_type, beds,
					frappe.utils.fmt_money(flt(line.extra_bed_amount)),
				),
				indicator="blue", alert=True,
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
				ignore_reservation=line.reservation, ignore_booking=self.name,
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
		always exactly one room. Guests and extra beds are divided across those rooms
		rather than copied, or three rooms held for six guests would each claim all six
		and the booking would bill three times the beds.
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
			shares = _split_line(line, len(rooms))

			for room, share in zip(rooms, shares):
				taken.add(room)
				row = line.as_dict()
				row.update({"name": None, "room": room, "qty": 1})
				row.update(share)
				expanded.append(row)

		self.set("rooms", [])
		for row in expanded:
			row.pop("idx", None)
			self.append("rooms", row)
		self.save(ignore_permissions=True)

	def reservation_discount(self, line):
		"""This line's share of the booking's discount, as the reservation stores it.

		Two conversions happen here, and both matter:

		  * The discount is agreed once for the booking, so an Amount is apportioned
		    across the rooms in proportion to what each contributes to the subtotal —
		    a suite carries more of it than a tent house.
		  * A reservation's Amount discount is applied by the night audit to *every
		    night*, so the room's share is then divided by the number of nights.

		A Percentage needs neither conversion: the same percentage off each night is
		the same percentage off the whole stay.
		"""
		if not self.discount_type or flt(self.discount_value) <= 0:
			return None, 0.0

		if str(self.discount_type).strip() == "Percentage":
			return "Percentage", flt(self.discount_value)

		subtotal = flt(self.total_before_discount)
		if subtotal <= 0:
			return None, 0.0

		share = flt(self.discount_amount) * (flt(line.amount) / subtotal)
		nights = max(cint(self.nights), 1)
		return "Amount", flt(share / nights, 2)

	def create_reservations(self):
		"""One Hotel Reservation per assigned room. Idempotent."""
		for line in self.rooms:
			if line.reservation and frappe.db.exists("Hotel Reservation", line.reservation):
				continue
			if not line.room:
				frappe.throw(_("Row {0} has no room assigned.").format(line.idx))

			discount_type, discount_value = self.reservation_discount(line)

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
				# Everything agreed on the line travels with the reservation: the rate
				# the agent settled on, the discount, the extra beds and the note. The
				# night audit reads these, so the folio and the invoice match the quote.
				"agreed_rate": flt(line.rate) if cint(line.is_rate_overridden) else None,
				"is_rate_overridden": cint(line.is_rate_overridden),
				"discount_type": discount_type,
				"discount_value": discount_value,
				"extra_beds_adult": cint(line.extra_beds_adult),
				"extra_beds_child": cint(line.extra_beds_child),
				"remarks": self.remarks or None,
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

		# Money kept from the advance is revenue: invoice it, and leave only the
		# refundable remainder as credit on the booking folio.
		if flt(cancellation_charge) > 0 and flt(self.advance_received) > 0:
			from hospitality_core.hospitality_core.api.invoicing import create_cancellation_invoice

			invoice = create_cancellation_invoice(self.name, cancellation_charge)
			if invoice:
				self.add_comment("Info", _("Cancellation charge invoiced on {0}.").format(invoice))

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
			# Every room has left, been cancelled, or was a no-show. A booking whose only
			# outcome is a no-show stays "No Show" rather than "Cancelled": it usually
			# holds an advance that someone has to decide about.
			if any(s == "Checked Out" for s in states):
				settled = "Completed"
			elif any(s == "No Show" for s in states):
				settled = "No Show"
			else:
				settled = "Cancelled"
			if self.status != settled:
				self.db_set("status", settled)
		elif any(s == "Checked In" for s in states) and self.status != "Checked In":
			self.db_set("status", "Checked In")


	def sync_window_from_reservations(self):
		"""Stretch the booking's dates over its rooms and reprice it.

		Called whenever a reservation's dates move (extension, early departure, date
		change, night-audit overstay). Saving runs calculate_totals, which prices every
		line on its reservation's real window, so total and balance due follow the stay.
		"""
		windows = [
			frappe.db.get_value(
				"Hotel Reservation", line.reservation,
				["arrival_date", "departure_date", "status"], as_dict=True,
			)
			for line in self.rooms
			if line.reservation
		]
		windows = [w for w in windows if w and w.status not in ("Cancelled", "No Show")]
		if not windows:
			return

		self.arrival_date = min(getdate(w.arrival_date) for w in windows)
		self.departure_date = max(getdate(w.departure_date) for w in windows)
		# A guest who checks in and leaves the same day still paid for one night; keep
		# the booking window at least that long so it stays valid.
		if self.departure_date <= self.arrival_date:
			self.departure_date = frappe.utils.add_days(self.arrival_date, 1)
		self.flags.ignore_validate_update_after_submit = True
		# The rooms are already reserved; re-running the availability check against
		# their own reservations is pointless and the date move was validated upstream.
		self.flags.skip_room_validation = True
		self.save(ignore_permissions=True)

	def change_dates(self, arrival_date, departure_date):
		"""Move a booking that has not arrived yet to new dates.

		The common "guest postponed" case. Every room keeps its room if it is free on
		the new dates; if it is not, another free room of the same category is taken so
		the change still goes through. The booking is then repriced for the new nights —
		a stay moved onto a weekend costs more, and the balance due says so.
		"""
		arrival_date, departure_date = getdate(arrival_date), getdate(departure_date)
		if departure_date <= arrival_date:
			frappe.throw(_("Departure must be after arrival."))
		if self.status not in ("Draft", "Tentative", "Confirmed"):
			frappe.throw(_("Only a booking that has not checked in can change dates. "
			               "Use Extend Stay on the reservation for a guest in house."))

		old = (self.arrival_date, self.departure_date)
		old_total = flt(self.total_amount)
		moved = []

		taken = set()
		for line in self.rooms:
			if not line.room:
				continue
			result = availability.is_room_free(
				line.room, arrival_date, departure_date,
				self.arrival_time, self.departure_time,
				ignore_reservation=line.reservation, ignore_booking=self.name,
			)
			room = line.room
			if not result["free"] or room in taken:
				free = [
					r for r in availability.get_free_rooms(
						arrival_date, departure_date, room_type=line.room_type,
						arrival_time=self.arrival_time, departure_time=self.departure_time,
						ignore_booking=self.name,
					)
					if r not in taken
				]
				if not free:
					frappe.throw(_("No {0} room is free from {1} to {2}.").format(
						line.room_type, arrival_date, departure_date
					))
				moved.append(f"{line.room} → {free[0]}")
				room = free[0]
			taken.add(room)

			if line.reservation:
				frappe.db.set_value("Hotel Reservation", line.reservation, {
					"arrival_date": arrival_date,
					"departure_date": departure_date,
					"room": room,
					**stay_policy.stay_time_values(),
				})
				folio = frappe.db.get_value("Hotel Reservation", line.reservation, "folio")
				if folio:
					frappe.db.set_value("Guest Folio", folio, "room", room)
			line.room = room

		self.arrival_date, self.departure_date = arrival_date, departure_date
		self.flags.skip_room_validation = True
		self.save(ignore_permissions=True)

		note = _("Dates changed from {0} – {1} to {2} – {3}. Total {4} → {5}.").format(
			old[0], old[1], arrival_date, departure_date,
			frappe.utils.fmt_money(old_total), frappe.utils.fmt_money(self.total_amount),
		)
		if moved:
			note += " " + _("Rooms reassigned: {0}.").format(", ".join(moved))
		self.add_comment("Info", note)
		return {
			"total_amount": self.total_amount,
			"previous_total": old_total,
			"balance_due": self.balance_due,
			"moved": moved,
		}


# ---------------------------------------------------------------------- whitelisted
@frappe.whitelist()
def change_booking_dates(booking, arrival_date, departure_date):
	doc = frappe.get_doc("Hotel Booking", booking)
	doc.check_permission("write")
	return doc.change_dates(arrival_date, departure_date)


@frappe.whitelist()
def preview_booking_dates(booking, arrival_date, departure_date):
	"""What a date change would cost, without saving anything."""
	doc = frappe.get_doc("Hotel Booking", booking)
	doc.check_permission("read")
	if getdate(departure_date) <= getdate(arrival_date):
		frappe.throw(_("Departure must be after arrival."))

	new_subtotal = 0.0
	for line in doc.rooms:
		quote = tariff.quote_stay(
			line.room_type, arrival_date, departure_date,
			qty=line.qty, adults=line.adults, children=line.children,
			extra_beds_adult=line.get("extra_beds_adult"),
			extra_beds_child=line.get("extra_beds_child"),
			rate_override=line.rate if cint(line.get("is_rate_overridden")) else None,
		)
		new_subtotal += flt(quote["gross_total"])

	_discount, new_total = tariff.apply_discount(new_subtotal, doc.discount_type, doc.discount_value)
	return {
		"nights": (getdate(departure_date) - getdate(arrival_date)).days,
		"previous_total": flt(doc.total_amount),
		"new_total": flt(new_total),
		"difference": flt(new_total) - flt(doc.total_amount),
		"advance_received": flt(doc.advance_received),
		"new_balance": flt(new_total) - flt(doc.advance_received),
	}


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
		doc = frappe.get_doc("Hotel Booking", booking)
		doc.sync_status_from_reservations()
		doc.reload()
		doc.sync_window_from_reservations()
	except Exception:
		# A booking bookkeeping failure must never block a guest checking out.
		frappe.log_error(
			f"Could not sync booking {booking} from reservation {reservation_name}",
			"Hotel Booking status sync",
		)
