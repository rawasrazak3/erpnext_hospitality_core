"""Canonical room availability for Hospitality Core.

Before this module the same overlap rule was re-implemented five times — a Python loop in
`reservation.check_availability`, a batched copy in `check_bulk_availability`, raw SQL in
`reservation.get_available_rooms_for_picker`, more raw SQL in `hotel_pos.get_pos_data`,
and again in the availability tool and tape chart. They drifted: some respected
`is_enabled`, some did not; some understood times, some assumed whole days.

Everything that needs to know whether a room is free should call `get_availability` or
`get_free_rooms` here.

Two kinds of thing occupy a room:

  1. A Hotel Reservation in a blocking status. A real room is assigned.
  2. An unassigned Hotel Booking Room line on a Tentative or Confirmed booking — a
     "soft hold". The guest has a room type but no room number yet, so it consumes
     capacity of that type without blocking any particular room.

Soft holds are counted against room-type capacity, never against a specific room, which
is what lets a sales agent hold two cottages on a call without deciding which two.
"""

import frappe
from frappe import _
from frappe.utils import cint, getdate

from hospitality_core.hospitality_core.api.reservation import _make_datetime

# Reservation statuses that occupy a room. "Tentative" is included so a hold placed by
# the CRM blocks inventory the moment it is created.
BLOCKING_RESERVATION_STATUSES = ("Tentative", "Reserved", "Checked In")

# Booking statuses whose unassigned room lines consume room-type capacity.
BLOCKING_BOOKING_STATUSES = ("Tentative", "Confirmed", "Checked In")

DEFAULT_ARRIVAL_TIME = "14:00:00"
DEFAULT_DEPARTURE_TIME = "12:00:00"


def _window(arrival_date, departure_date, arrival_time=None, departure_time=None):
	"""The half-open datetime window a stay occupies."""
	start = _make_datetime(arrival_date, arrival_time, DEFAULT_ARRIVAL_TIME)
	end = _make_datetime(departure_date, departure_time, DEFAULT_DEPARTURE_TIME)
	if end <= start:
		frappe.throw(_("Departure must be after arrival."))
	return start, end


def _overlapping_reservations(start, end, room=None, room_type=None, ignore_reservation=None,
                              ignore_booking=None):
	"""Reservations that overlap the window. Overlap is `new_start < old_end AND
	new_end > old_start`, evaluated on full datetimes rather than dates so a same-day
	turnaround (12:00 out, 14:00 in) is not treated as a clash."""
	conditions = ["r.status IN %(statuses)s"]
	params = {
		"statuses": BLOCKING_RESERVATION_STATUSES,
		"start": start,
		"end": end,
		"in_t": DEFAULT_ARRIVAL_TIME,
		"out_t": DEFAULT_DEPARTURE_TIME,
	}

	if room:
		conditions.append("r.room = %(room)s")
		params["room"] = room
	if room_type:
		conditions.append("r.room_type = %(room_type)s")
		params["room_type"] = room_type
	if ignore_reservation:
		conditions.append("r.name != %(ignore_reservation)s")
		params["ignore_reservation"] = ignore_reservation
	if ignore_booking and frappe.get_meta("Hotel Reservation").has_field("hotel_booking"):
		conditions.append("IFNULL(r.hotel_booking, '') != %(ignore_booking)s")
		params["ignore_booking"] = ignore_booking

	conditions.append(
		"""CAST(CONCAT(r.arrival_date, ' ',
			IFNULL(NULLIF(r.arrival_time, ''), %(in_t)s)) AS DATETIME) < %(end)s"""
	)
	conditions.append(
		"""CAST(CONCAT(r.departure_date, ' ',
			IFNULL(NULLIF(r.departure_time, ''), %(out_t)s)) AS DATETIME) > %(start)s"""
	)

	return frappe.db.sql(
		"""
		SELECT r.name, r.room, r.room_type, r.guest, r.status,
		       r.arrival_date, r.departure_date
		FROM `tabHotel Reservation` r
		WHERE {conditions}
		""".format(conditions=" AND ".join(conditions)),
		params,
		as_dict=True,
	)


def _soft_holds(start, end, room_type=None, ignore_booking=None):
	"""Unassigned booking room lines overlapping the window, counted per room type.

	Returns {room_type: rooms_held}. A line with a room already assigned is skipped —
	its reservation is what blocks, and counting both would double-book against us.
	"""
	if not frappe.db.exists("DocType", "Hotel Booking"):
		return {}

	conditions = [
		"b.status IN %(statuses)s",
		"IFNULL(l.room, '') = ''",
		"IFNULL(l.reservation, '') = ''",
	]
	params = {
		"statuses": BLOCKING_BOOKING_STATUSES,
		"start": start,
		"end": end,
		"in_t": DEFAULT_ARRIVAL_TIME,
		"out_t": DEFAULT_DEPARTURE_TIME,
	}

	if room_type:
		conditions.append("l.room_type = %(room_type)s")
		params["room_type"] = room_type
	if ignore_booking:
		conditions.append("b.name != %(ignore_booking)s")
		params["ignore_booking"] = ignore_booking

	conditions.append(
		"""CAST(CONCAT(b.arrival_date, ' ',
			IFNULL(NULLIF(b.arrival_time, ''), %(in_t)s)) AS DATETIME) < %(end)s"""
	)
	conditions.append(
		"""CAST(CONCAT(b.departure_date, ' ',
			IFNULL(NULLIF(b.departure_time, ''), %(out_t)s)) AS DATETIME) > %(start)s"""
	)

	rows = frappe.db.sql(
		"""
		SELECT l.room_type, SUM(GREATEST(IFNULL(l.qty, 1), 1)) AS held
		FROM `tabHotel Booking Room` l
		JOIN `tabHotel Booking` b ON b.name = l.parent
		WHERE {conditions}
		GROUP BY l.room_type
		""".format(conditions=" AND ".join(conditions)),
		params,
		as_dict=True,
	)
	return {r.room_type: cint(r.held) for r in rows}


@frappe.whitelist()
def get_availability(arrival_date, departure_date, room_type=None, arrival_time=None,
                     departure_time=None, include_soft_holds=True, ignore_reservation=None,
                     ignore_booking=None):
	"""Availability for a stay window.

	Returns:
	    {
	      "arrival": ..., "departure": ..., "nights": n,
	      "room_types": [{room_type, default_rate, total, occupied, held, free}],
	      "rooms": [{name, room_type, floor, status, available, blocked_by}],
	      "total_free": n,
	    }
	"""
	include_soft_holds = cint(include_soft_holds)
	start, end = _window(arrival_date, departure_date, arrival_time, departure_time)

	room_filters = {"is_enabled": 1}
	if room_type:
		room_filters["room_type"] = room_type

	rooms = frappe.get_all(
		"Hotel Room",
		filters=room_filters,
		fields=["name", "room_type", "floor", "status", "hotel_reception"],
		order_by="room_type asc, name asc",
	)

	taken = {}
	for res in _overlapping_reservations(
		start, end, room_type=room_type, ignore_reservation=ignore_reservation,
		ignore_booking=ignore_booking,
	):
		if res.room:
			taken[res.room] = res

	holds = _soft_holds(start, end, room_type=room_type, ignore_booking=ignore_booking) \
		if include_soft_holds else {}

	types = {
		t.name: {
			"room_type": t.name,
			"default_rate": t.default_rate,
			"max_adults": t.max_adults,
			"total": 0,
			"occupied": 0,
			"out_of_order": 0,
			"held": cint(holds.get(t.name)),
			"free": 0,
		}
		for t in frappe.get_all(
			"Hotel Room Type",
			filters={"name": room_type} if room_type else {},
			fields=["name", "default_rate", "max_adults"],
		)
	}

	detail = []
	for room in rooms:
		bucket = types.setdefault(room.room_type, {
			"room_type": room.room_type, "default_rate": 0, "max_adults": 0,
			"total": 0, "occupied": 0, "out_of_order": 0,
			"held": cint(holds.get(room.room_type)), "free": 0,
		})
		bucket["total"] += 1

		blocked_by = None
		if room.status == "Out of Order":
			blocked_by = "Out of Order"
			bucket["out_of_order"] += 1
		elif room.name in taken:
			res = taken[room.name]
			blocked_by = f"{res.status}: {res.name}"
			bucket["occupied"] += 1

		detail.append({
			"name": room.name,
			"room_type": room.room_type,
			"floor": room.floor,
			"status": room.status,
			"hotel_reception": room.hotel_reception,
			"available": blocked_by is None,
			"blocked_by": blocked_by,
		})

	for bucket in types.values():
		physically_free = bucket["total"] - bucket["occupied"] - bucket["out_of_order"]
		# Soft holds consume capacity of the type but never a specific room, so they
		# reduce the free count without marking any room unavailable.
		bucket["free"] = max(physically_free - bucket["held"], 0)

	ordered = sorted(types.values(), key=lambda b: b["room_type"] or "")
	return {
		"arrival": str(start),
		"departure": str(end),
		"nights": (getdate(departure_date) - getdate(arrival_date)).days,
		"room_types": ordered,
		"rooms": detail,
		"total_free": sum(b["free"] for b in ordered),
	}


@frappe.whitelist()
def get_free_rooms(arrival_date, departure_date, room_type=None, arrival_time=None,
                   departure_time=None, limit=None, ignore_reservation=None,
                   ignore_booking=None):
	"""Room names that are physically free for the window, in a stable order.

	Soft holds are deliberately NOT applied here: this answers "which rooms can I assign
	right now", and assigning a room is exactly what converts a hold into a reservation.
	"""
	data = get_availability(
		arrival_date, departure_date, room_type=room_type,
		arrival_time=arrival_time, departure_time=departure_time,
		include_soft_holds=False, ignore_reservation=ignore_reservation,
		ignore_booking=ignore_booking,
	)
	free = [r["name"] for r in data["rooms"] if r["available"]]
	return free[: cint(limit)] if limit else free


def assign_rooms(room_type, qty, arrival_date, departure_date, arrival_time=None,
                 departure_time=None, ignore_booking=None, exclude=None):
	"""Pick `qty` free rooms of a type, or throw naming what is short.

	Used when a booking is confirmed and its type-only holds have to become real rooms.
	"""
	qty = max(cint(qty), 1)
	exclude = set(exclude or [])

	free = [
		room
		for room in get_free_rooms(
			arrival_date, departure_date, room_type=room_type,
			arrival_time=arrival_time, departure_time=departure_time,
			ignore_booking=ignore_booking,
		)
		if room not in exclude
	]

	if len(free) < qty:
		frappe.throw(
			_("Only {0} {1} room(s) are free for {2} to {3}, but {4} are needed.").format(
				len(free), room_type, arrival_date, departure_date, qty
			)
		)
	return free[:qty]


@frappe.whitelist()
def is_room_free(room, arrival_date, departure_date, arrival_time=None, departure_time=None,
                 ignore_reservation=None):
	"""Non-throwing check for one room. Returns {"free": bool, "reason": str|None}."""
	enabled, status = frappe.db.get_value("Hotel Room", room, ["is_enabled", "status"]) or (0, None)
	if not enabled:
		return {"free": False, "reason": _("Room {0} is disabled.").format(room)}
	if status == "Out of Order":
		return {"free": False, "reason": _("Room {0} is Out of Order.").format(room)}

	start, end = _window(arrival_date, departure_date, arrival_time, departure_time)
	clashes = _overlapping_reservations(start, end, room=room, ignore_reservation=ignore_reservation)
	if clashes:
		c = clashes[0]
		return {
			"free": False,
			"reason": _("Room {0} is {1} for {2} ({3} to {4}).").format(
				room, c.status, c.guest, c.arrival_date, c.departure_date
			),
			"reservation": c.name,
		}
	return {"free": True, "reason": None}
