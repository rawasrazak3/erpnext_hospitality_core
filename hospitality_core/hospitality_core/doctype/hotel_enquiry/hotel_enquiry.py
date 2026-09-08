# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff, flt, getdate, now_datetime


class HotelEnquiry(Document):
	def validate(self):
		self.set_default_status()
		self.normalise_mobile()
		self.calculate_nights()
		self.calculate_quote()
		self.validate_lost_reason()
		self.stamp_follow_ups()

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

	def calculate_nights(self):
		if self.check_in_date and self.check_out_date:
			if getdate(self.check_out_date) <= getdate(self.check_in_date):
				frappe.throw(_("Check Out must be after Check In."))
			self.nights = date_diff(self.check_out_date, self.check_in_date)
		else:
			self.nights = 0

	def calculate_quote(self):
		"""Price each requested room line at rooms x nights x rate."""
		total = 0.0
		for line in self.room_lines:
			line.nights = cint(self.nights)
			line.amount = flt(line.rate_quoted) * max(cint(line.qty), 1) * max(cint(line.nights), 1)
			total += flt(line.amount)
		self.quoted_total = total

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
