"""When a stay starts and ends.

A stay is a set of nights: it occupies arrival_date <= night < departure_date. Booking a
room for Saturday means Saturday check-in time to Sunday check-out time, and someone
else can have the room from Sunday. Rooms are therefore allocated by date alone
(see api.availability); the clock times are the property's standard ones from
Hospitality Accounting Settings and are what every booking, reservation, POS screen
and printout shows.

Not checking a guest out never lengthens their stay. Only an explicit Extend does.
"""

import frappe
from frappe.utils import get_time

FALLBACK_CHECK_IN = "14:00:00"
FALLBACK_CHECK_OUT = "12:00:00"


def _as_str(value, fallback):
	if value in (None, ""):
		return fallback
	try:
		return get_time(value).replace(microsecond=0).strftime("%H:%M:%S")
	except Exception:
		return fallback


def get_stay_times():
	"""(check_in, check_out) as "HH:MM:SS" strings from Hospitality Accounting Settings.

	The billing policy setting no longer changes anything: every stay runs from the
	standard check-in time to the standard check-out time.
	"""
	cached = frappe.local.flags.get("hospitality_stay_times")
	if cached:
		return cached

	values = frappe.db.get_value(
		"Hospitality Accounting Settings", "Hospitality Accounting Settings",
		["standard_check_in_time", "standard_check_out_time"], as_dict=True,
	) or {}
	times = (
		_as_str(values.get("standard_check_in_time"), FALLBACK_CHECK_IN),
		_as_str(values.get("standard_check_out_time"), FALLBACK_CHECK_OUT),
	)
	frappe.local.flags.hospitality_stay_times = times
	return times


@frappe.whitelist()
def get_stay_times_for_display():
	"""For the desk: {"check_in": "16:00:00", "check_out": "16:00:00"}."""
	check_in, check_out = get_stay_times()
	return {"check_in": check_in, "check_out": check_out}


def apply_stay_times(doc):
	"""Stamp a booking or reservation (document or dict) with the standard times."""
	check_in, check_out = get_stay_times()
	if isinstance(doc, dict):
		doc["arrival_time"] = check_in
		doc["departure_time"] = check_out
	else:
		doc.arrival_time = check_in
		doc.departure_time = check_out
	return doc


def stay_time_values():
	"""{"arrival_time": ..., "departure_time": ...} for db_set / set_value calls."""
	check_in, check_out = get_stay_times()
	return {"arrival_time": check_in, "departure_time": check_out}
