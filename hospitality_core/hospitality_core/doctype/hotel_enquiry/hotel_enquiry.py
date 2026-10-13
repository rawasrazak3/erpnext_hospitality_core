# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, getdate, now_datetime


class HotelEnquiry(Document):
	def validate(self):
		self.guard_booked_date_change()
		self.set_default_status()
		self.normalise_mobile()
		self.calculate_nights()
		self.sync_room_lines()
		self.calculate_quote()
		self.validate_lost_reason()
		self.guard_lost_while_booked()
		self.stamp_follow_ups()

	# ------------------------------------------------------------ booked enquiries
	def _booked_dates_changed(self):
		before = self.get_doc_before_save()
		if not before or not self.hotel_booking or self.flags.from_booking:
			return None
		if (str(before.check_in_date) == str(self.check_in_date)
				and str(before.check_out_date) == str(self.check_out_date)):
			return None
		status = frappe.db.get_value("Hotel Booking", self.hotel_booking, "status")
		return status

	def guard_booked_date_change(self):
		"""A guest already in house is re-dated from the stay, not from the enquiry."""
		status = self._booked_dates_changed()
		if status in ("Checked In", "Completed"):
			frappe.throw(_(
				"Booking {0} is {1}. Change the stay from Hotel POS › Guests (Extend / Change Dates)."
			).format(self.hotel_booking, status))

	def on_update(self):
		"""New dates on an enquiry that is already booked move the booking with them.

		Agents changed the dates here and, seeing nothing happen to the booking, made a
		second enquiry and booking for the new dates — leaving the old room blocked and
		the advance recorded twice. Now the booking (and its rooms) follows the enquiry.
		"""
		status = self._booked_dates_changed()
		if status not in ("Draft", "Tentative", "Confirmed", "No Show"):
			return
		booking = frappe.get_doc("Hotel Booking", self.hotel_booking)
		result = booking.change_dates(self.check_in_date, self.check_out_date)
		msg = _("Booking {0} moved to {1} – {2}. New total {3}.").format(
			booking.name, frappe.format(self.check_in_date, "Date"), frappe.format(self.check_out_date, "Date"),
			frappe.utils.fmt_money(result.get("total_amount")),
		)
		if result.get("moved"):
			msg += " " + _("Rooms reassigned: {0}.").format(", ".join(result["moved"]))
		frappe.msgprint(msg, indicator="green", alert=True)

	def before_insert(self):
		if not self.enquiry_owner:
			self.enquiry_owner = frappe.session.user

	def set_default_status(self):
		if not self.status:
			self.status = get_default_status()
		self.status_type = frappe.db.get_value("Hotel Enquiry Status", self.status, "type")

	def normalise_mobile(self):
		"""Store numbers as typed, but keep an indexed digits-only key alongside.

		A handset reports "919072140018" while an agent types "+91 90721 40018"; both
		must find the same enquiry. Matching on the key turns call linkage and phone
		search into indexed lookups instead of a REGEXP_REPLACE scan of every row.
		"""
		from hospitality_core.hospitality_core.api.telephony import match_key

		if self.mobile_no:
			self.mobile_no = self.mobile_no.strip()
		self.mobile_key = match_key(self.mobile_no)
		self.alt_mobile_key = match_key(self.alt_mobile)

	def sync_room_lines(self):
		"""A line names the room the guest is offered; its type follows from the room.

		One room is one line (quantity 1), and the same room cannot be offered twice on
		one enquiry. A line with only a room type — how requests were taken before
		rooms could be chosen — is still accepted as "any room of this type".
		"""
		seen = set()
		for line in self.room_lines:
			if not line.room:
				if not line.room_type:
					frappe.throw(_("Row {0}: choose a room.").format(line.idx))
				continue
			if line.room in seen:
				frappe.throw(_("Room {0} is on this enquiry twice.").format(line.room))
			seen.add(line.room)
			room_type = frappe.db.get_value("Hotel Room", line.room, "room_type")
			if not room_type:
				frappe.throw(_("Row {0}: room {1} does not exist.").format(line.idx, line.room))
			line.room_type = room_type
			line.qty = 1

	def calculate_nights(self):
		if self.check_in_date and self.check_out_date:
			if getdate(self.check_out_date) <= getdate(self.check_in_date):
				frappe.throw(_("Check Out must be after Check In."))
			self.nights = date_diff(self.check_out_date, self.check_in_date)
		else:
			self.nights = 0

	def calculate_quote(self):
		"""Price each requested room line through the canonical tariff engine.

		The quote an agent gives on the phone is the number the guest will be billed, so
		it is priced the same way the folio will be: weekend and holiday nights at the
		premium rate, extra beds added for a party over capacity, then the line's
		discount off the gross.

		A rate the agent typed wins over all of that — `is_rate_overridden` marks it, and
		from then on nothing recomputes the rate, only the amounts around it.

		The discount is a property of the enquiry, not of a room line: an agent agrees
		one figure off the whole quote. So lines total to a subtotal and the discount
		comes off that once.
		"""
		from hospitality_core.hospitality_core.api.tariff import apply_discount

		subtotal = 0.0
		for line in self.room_lines:
			line.nights = cint(self.nights)
			quote = self._quote_line(line)

			if quote:
				line.extra_beds_adult = quote["extra_beds_adult"]
				line.extra_beds_child = quote["extra_beds_child"]
				line.extra_bed_amount = quote["extra_bed_total"]
				line.amount = quote["gross_total"]
				if not cint(line.is_rate_overridden):
					# The room-only rate, not the all-in one: `extra_bed_amount` sits
					# beside it and `amount` already counts the beds once. Storing the
					# all-in figure here charged them twice — on screen, and again the
					# moment an agent nudged the rate and it came back as an agreed rate.
					line.rate_quoted = quote["average_room_nightly"]
			else:
				# No usable dates yet: fall back to the flat arithmetic so a half-filled
				# enquiry still shows a number.
				line.amount = flt(line.rate_quoted) * max(cint(line.qty), 1) * max(cint(line.nights), 1)
				line.extra_bed_amount = 0

			line.gross_amount = line.amount
			subtotal += flt(line.amount)

		self.quoted_subtotal = subtotal
		self.discount_amount, self.quoted_total = apply_discount(
			subtotal, self.discount_type, self.discount_value
		)

	def _quote_line(self, line):
		"""Server-priced quote for one enquiry line, or None if it cannot be priced."""
		if not (line.room_type and self.check_in_date and self.check_out_date):
			return None
		if getdate(self.check_out_date) <= getdate(self.check_in_date):
			return None

		from hospitality_core.hospitality_core.api.tariff import quote_stay

		try:
			return quote_stay(
				line.room_type, self.check_in_date, self.check_out_date,
				qty=line.qty, adults=line.adults, children=line.children,
				extra_beds_adult=line.get("extra_beds_adult"),
				extra_beds_child=line.get("extra_beds_child"),
				rate_override=line.rate_quoted if cint(line.get("is_rate_overridden")) else None,
			)
		except Exception:
			# A category with a broken tariff must not stop an agent saving an enquiry.
			frappe.log_error(
				f"Could not price {line.room_type} on enquiry {self.name}",
				"Hotel Enquiry pricing",
			)
			return None

	def guard_lost_while_booked(self):
		"""An enquiry with a live booking cannot be marked lost: the room stays held."""
		if self.status_type != "Lost" or not self.hotel_booking:
			return
		status = frappe.db.get_value("Hotel Booking", self.hotel_booking, "status")
		if status in ("Draft", "Tentative", "Confirmed", "Checked In", "No Show"):
			frappe.throw(_("Booking {0} is {1}. Cancel the booking first (it releases the room), then mark the enquiry lost.").format(
				self.hotel_booking, status))

	def validate_lost_reason(self):
		if self.status_type == "Lost" and not self.lost_reason:
			frappe.throw(_("Select a Lost Reason before marking this enquiry {0}.").format(self.status))

	def stamp_follow_ups(self):
		"""Attribute each new follow-up row and keep last_contacted in step."""
		latest = None
		for row in self.follow_ups:
			if not row.user:
				row.user = frappe.session.user
			if not row.follow_up_at:
				row.follow_up_at = now_datetime()
			if row.outcome == "Connected" and (not latest or row.follow_up_at > latest):
				latest = row.follow_up_at
		if latest:
			self.last_contacted = latest


def get_default_status():
	"""First Open status by position, so the pipeline's leftmost column is the default."""
	status = frappe.db.get_value(
		"Hotel Enquiry Status", {"type": "Open"}, "name", order_by="position asc"
	)
	return status or frappe.db.get_value("Hotel Enquiry Status", {}, "name", order_by="position asc")


@frappe.whitelist()
def log_follow_up(enquiry, outcome, remarks=None, next_follow_up=None, call_log=None):
	"""Append a follow-up to an enquiry and optionally set the next callback time.

	This is the single action a sales user performs dozens of times a day, so it is a
	whitelisted method rather than a form save: it touches only the rows it needs.
	"""
	doc = frappe.get_doc("Hotel Enquiry", enquiry)
	doc.append("follow_ups", {
		"follow_up_at": now_datetime(),
		"outcome": outcome,
		"remarks": remarks,
		"user": frappe.session.user,
		"call_log": call_log,
	})
	if next_follow_up:
		doc.next_follow_up = next_follow_up
	doc.save()
	return {"name": doc.name, "last_contacted": doc.last_contacted, "next_follow_up": doc.next_follow_up}
