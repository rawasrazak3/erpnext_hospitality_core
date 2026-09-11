"""A room category: its bed layout, occupancy ceiling, tariff and amenities.

The property prices a stay on three axes, all held here:

  1. A nightly tariff that differs on weekends (`default_rate` vs `weekend_rate`).
  2. A per-head, per-day charge for guests beyond the base headcount, which also
     differs on weekends (`extra_person_rate_weekday` / `..._weekend`).
  3. A flat extra-bed charge, priced differently for an adult and a child.

`rate_for_date` and `extra_person_rate_for_date` are the only places that decide which
side of that weekday/weekend split a date falls on, so the rule lives in one spot.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

# Friday night through Sunday night is charged at the weekend tariff: a guest arriving
# Friday and leaving Monday pays weekend for Fri/Sat/Sun. Python's weekday() is
# Monday=0 ... Friday=4, Saturday=5, Sunday=6.
WEEKEND_WEEKDAYS = (4, 5, 6)


def is_weekend(date):
	return getdate(date).weekday() in WEEKEND_WEEKDAYS


class HotelRoomType(Document):
	def validate(self):
		self.set_occupancy_defaults()
		self.validate_rates()

	def set_occupancy_defaults(self):
		"""`max_occupancy` is the number the property actually quotes ("Max Allowed").
		`max_adults` / `max_children` are advisory splits shown in the CRM and POS, so
		keep them inside the ceiling rather than letting the two disagree."""
		if cint(self.max_occupancy) < 1:
			frappe.throw(_("Max Allowed must be at least 1."))

		if cint(self.max_adults) > cint(self.max_occupancy):
			self.max_adults = self.max_occupancy
		if cint(self.max_children) > cint(self.max_occupancy):
			self.max_children = self.max_occupancy

	def validate_rates(self):
		for field in ("default_rate", "weekend_rate", "extra_person_rate_weekday",
		              "extra_person_rate_weekend", "extra_bed_adult_rate",
		              "extra_bed_child_rate"):
			if flt(self.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(self.meta.get_label(field))))

		# A blank weekend rate means "same as weekday", which is how the smaller
		# categories are priced. Store it explicitly so reports never have to guess.
		if not flt(self.weekend_rate):
			self.weekend_rate = self.default_rate
		if not flt(self.extra_person_rate_weekend):
			self.extra_person_rate_weekend = self.extra_person_rate_weekday

	def rate_for_date(self, date):
		"""Nightly tariff for the night beginning on `date`."""
		if is_weekend(date) and flt(self.weekend_rate):
			return flt(self.weekend_rate)
		return flt(self.default_rate)

	def extra_person_rate_for_date(self, date):
		"""Per-head, per-day charge for guests beyond `max_occupancy`'s base."""
		if is_weekend(date):
			return flt(self.extra_person_rate_weekend or self.extra_person_rate_weekday)
		return flt(self.extra_person_rate_weekday)


@frappe.whitelist()
def get_rate_for_date(room_type, date):
	"""Nightly tariff for one room type on one date, weekend rule applied."""
	rates = frappe.db.get_value(
		"Hotel Room Type", room_type, ["default_rate", "weekend_rate"], as_dict=True
	)
	if not rates:
		return 0.0
	if is_weekend(date) and flt(rates.weekend_rate):
		return flt(rates.weekend_rate)
	return flt(rates.default_rate)


@frappe.whitelist()
def get_tariff(room_type):
	"""Everything the front desk needs to quote a stay for a room type."""
	return frappe.db.get_value(
		"Hotel Room Type",
		room_type,
		[
			"name", "bedroom_configuration", "max_occupancy", "max_adults", "max_children",
			"default_rate", "weekend_rate", "extra_person_rate_weekday",
			"extra_person_rate_weekend", "extra_bed_adult_rate", "extra_bed_child_rate",
		],
		as_dict=True,
	)
