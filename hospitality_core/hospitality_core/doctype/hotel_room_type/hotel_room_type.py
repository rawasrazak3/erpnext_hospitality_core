"""A room category: its bed layout, occupancy ceiling, tariff and amenities.

The property prices a stay on three axes, all held here:

  1. A nightly tariff that differs on weekends (`default_rate` vs `weekend_rate`).
     It covers the room for up to `max_occupancy` guests.
  2. A per-head, per-day unit price — the tariff divided by `max_occupancy` — for when
     a group is sold by headcount rather than by room. Also weekend-split.
  3. An extra-bed charge per night for a guest beyond `max_occupancy`, priced
     differently for an adult and a child.

`rate_for_date` and `per_head_rate_for_date` are the only places that decide which side
of the weekday/weekend split a date falls on, so the rule lives in one spot.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, getdate

# Saturday and Sunday nights carry the weekend tariff. Python's weekday() is
# Monday=0 ... Saturday=5, Sunday=6.
WEEKEND_WEEKDAYS = (5, 6)

# Cache key for the resolved holiday dates of one Holiday List. Cleared whenever a
# Holiday List is saved (see hooks.doc_events).
HOLIDAY_CACHE = "hospitality_tariff_holidays"


def is_weekend(date):
	"""True for a Saturday or Sunday night."""
	return getdate(date).weekday() in WEEKEND_WEEKDAYS


def get_tariff_holiday_list():
	"""Which Holiday List decides premium dates.

	Set it on Hospitality Accounting Settings to price the property on its own
	calendar; otherwise the company's default list is used, so a site that already
	maintains one for payroll gets holiday pricing without configuring anything twice.
	"""
	configured = frappe.db.get_single_value("Hospitality Accounting Settings", "holiday_list")
	if configured:
		return configured

	company = frappe.db.get_single_value("Hospitality Accounting Settings", "company") \
		or frappe.defaults.get_user_default("Company")
	if company:
		return frappe.db.get_value("Company", company, "default_holiday_list")
	return None


def get_holiday_dates(holiday_list=None):
	"""The set of dates in a Holiday List, as ISO strings. Cached per list.

	A tariff quote walks every night of a stay, so without the cache a fortnight's
	booking would be fourteen round trips to the same child table.
	"""
	holiday_list = holiday_list or get_tariff_holiday_list()
	if not holiday_list:
		return set()

	cached = frappe.cache().hget(HOLIDAY_CACHE, holiday_list)
	if cached is not None:
		return set(cached)

	dates = {
		str(d)
		for d in frappe.get_all(
			"Holiday",
			filters={"parent": holiday_list, "parenttype": "Holiday List"},
			pluck="holiday_date",
		)
	}
	frappe.cache().hset(HOLIDAY_CACHE, holiday_list, list(dates))
	return dates


def clear_holiday_cache(doc=None, method=None):
	"""Drop the cached dates. Hooked to Holiday List saves and deletes."""
	frappe.cache().delete_key(HOLIDAY_CACHE)


def is_holiday(date, holiday_list=None):
	"""True when the date appears in the property's Holiday List."""
	return str(getdate(date)) in get_holiday_dates(holiday_list)


def rate_class(date, holiday_list=None):
	"""Why a night is priced the way it is: "Holiday", "Weekend" or "Weekday".

	Holiday wins the label when a date is both, because that is the reason a guest
	will ask about.
	"""
	if is_holiday(date, holiday_list):
		return "Holiday"
	if is_weekend(date):
		return "Weekend"
	return "Weekday"


def is_premium_date(date, holiday_list=None):
	"""True when the night is charged at the weekend tariff.

	That is a Saturday, a Sunday, or any date the Holiday List names — the property
	prices a public holiday the same as a weekend.
	"""
	return rate_class(date, holiday_list) != "Weekday"


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
		for field in ("default_rate", "weekend_rate", "per_head_rate_weekday",
		              "per_head_rate_weekend", "extra_bed_adult_rate",
		              "extra_bed_child_rate"):
			if flt(self.get(field)) < 0:
				frappe.throw(_("{0} cannot be negative.").format(_(self.meta.get_label(field))))

		# A blank weekend rate means "same as weekday", which is how the smaller
		# categories are priced. Store it explicitly so reports never have to guess.
		if not flt(self.weekend_rate):
			self.weekend_rate = self.default_rate

		# The per-head columns are the tariff divided by the headcount it covers. Derive
		# them when left blank so a category is never quotable at zero per head.
		occupancy = cint(self.max_occupancy) or 1
		if not flt(self.per_head_rate_weekday):
			self.per_head_rate_weekday = flt(self.default_rate) / occupancy
		if not flt(self.per_head_rate_weekend):
			self.per_head_rate_weekend = flt(self.weekend_rate) / occupancy

	def rate_for_date(self, date):
		"""Nightly tariff for the night beginning on `date`."""
		if is_premium_date(date) and flt(self.weekend_rate):
			return flt(self.weekend_rate)
		return flt(self.default_rate)

	def per_head_rate_for_date(self, date):
		"""Per-head, per-day unit price for the night beginning on `date`."""
		if is_premium_date(date):
			return flt(self.per_head_rate_weekend or self.per_head_rate_weekday)
		return flt(self.per_head_rate_weekday)

	def extra_bed_rate(self, adults=0, children=0):
		"""Nightly cost of `adults` + `children` extra beds beyond `max_occupancy`."""
		return (cint(adults) * flt(self.extra_bed_adult_rate)) + (
			cint(children) * flt(self.extra_bed_child_rate)
		)


@frappe.whitelist()
def get_rate_for_date(room_type, date):
	"""Nightly tariff for one room type on one date, weekend rule applied."""
	rates = frappe.db.get_value(
		"Hotel Room Type", room_type, ["default_rate", "weekend_rate"], as_dict=True
	)
	if not rates:
		return 0.0
	if is_premium_date(date) and flt(rates.weekend_rate):
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
			"pricing_basis", "default_rate", "weekend_rate", "per_head_rate_weekday",
			"per_head_rate_weekend", "extra_bed_adult_rate", "extra_bed_child_rate",
		],
		as_dict=True,
	)
