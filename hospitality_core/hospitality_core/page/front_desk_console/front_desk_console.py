"""Backend for the Front Desk Console (/app/front-desk-console).

This page is the hotel's home screen: the shift's work (arrivals, departures,
occupancy) plus the jumping-off point to every other part of the system. So the
load has to be one round trip — `get_console_data` returns the day's lists, the
headline numbers, and the live badge counts the navigation hub renders.

Every count is permission-guarded. A Hotel Sales Agent has no read on Hotel Room
and would otherwise get a PermissionError on a page that is now their landing
screen; a hidden tile is the right failure, not a broken page.
"""

import frappe
from frappe.utils import flt, nowdate

from hospitality_core.hospitality_core.api import telephony
from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import BLOCKED_STATUSES

# An enquiry sitting in one of these stages is still live sales work. Mirrors
# hotel_crm.OPEN_TYPES — the CRM console and this page must agree on "open" or the
# badge here disagrees with the queue the agent lands in.
OPEN_ENQUIRY_TYPES = ("Open", "Ongoing")

SEARCH_LIMIT = 8

# A guest reads their number out over the phone; what is stored may be "+91 90721 40018"
# or "9072140018". Hotel Enquiry has an indexed mobile_key for exactly this, but Guest and
# Hotel Booking do not, so their phone columns are normalised in SQL at query time. That
# is a scan, which is why it only runs when the query is actually phone-shaped — and both
# tables are one row per guest/booking, not one per call.
PHONE_STRIP = " ", "+", "-", "(", ")", "."


def _digits(column):
	expr = column
	for ch in PHONE_STRIP:
		expr = f"REPLACE({expr}, '{ch}', '')"
	return expr

# Past this many unattended calls the exact number stops being useful — nobody clears
# a 300-call backlog today, and counting it costs a full scan every page load.
CALL_BADGE_CAP = 99


@frappe.whitelist()
def get_console_data(target_date=None):
	if not target_date:
		target_date = nowdate()

	# 1. Fetch Arrivals for specific date
	# Include 'Checked Out' in arrivals list if they arrived AND left on the target date (Day Use)
	arrivals = frappe.db.sql(
		"""
        SELECT res.name, g.full_name as guest_name, res.status, res.room, res.room_type,
               res.arrival_date, res.arrival_time, g.mobile_no
        FROM `tabHotel Reservation` res
        LEFT JOIN `tabGuest` g ON res.guest = g.name
        WHERE res.arrival_date = %s
        AND res.status IN ('Reserved', 'Checked In', 'Checked Out')
        ORDER BY res.status DESC, g.full_name ASC
    """,
		(target_date,),
		as_dict=True,
	)

	# 2. Fetch Departures for specific date
	departures = frappe.db.sql(
		"""
        SELECT res.name, g.full_name as guest_name, res.status, res.room, res.room_type,
               res.departure_date, res.departure_time, g.mobile_no, f.outstanding_balance as folio_balance
        FROM `tabHotel Reservation` res
        LEFT JOIN `tabGuest` g ON res.guest = g.name
        LEFT JOIN `tabGuest Folio` f ON res.folio = f.name
        WHERE res.departure_date = %s
        AND res.status IN ('Checked In', 'Checked Out')
        ORDER BY res.status ASC, res.room ASC
    """,
		(target_date,),
		as_dict=True,
	)

	# 3. Stats Calculation (Date Sensitive)
	total_rooms = frappe.db.count("Hotel Room", {"is_enabled": 1})

	# Calculate In-House (Night Occupancy) using datetime comparison
	# Logic: Arrived (datetime) <= Now AND Departing (datetime) > Now
	# This captures:
	#   - Old Check-ins (Stayovers)
	#   - New Check-ins (Arrivals)
	# It Excludes:
	#   - Due Outs (Departing Today before their checkout time)
	in_house_count = (
		frappe.db.sql(
			"""
        SELECT COUNT(*) FROM `tabHotel Reservation`
        WHERE CAST(CONCAT(arrival_date, ' ', IFNULL(NULLIF(arrival_time, ''), '14:00:00')) AS DATETIME) <= %s
        AND CAST(CONCAT(departure_date, ' ', IFNULL(NULLIF(departure_time, ''), '12:00:00')) AS DATETIME) > %s
        AND status = 'Checked In'
    """,
			(f"{target_date} 14:00:00", f"{target_date} 14:00:00"),
		)[0][0]
		or 0
	)

	# Arrivals Pending (Reserved for this date)
	# These represent potential In-House guests for tonight who haven't arrived yet.
	arrivals_pending = len([a for a in arrivals if a.status == "Reserved"])

	# Departures Pending (Checked In with departure on this date)
	# These are guests physically present right now but expected to leave.
	departures_pending = len([d for d in departures if d.status == "Checked In"])

	# Available Rooms Calculation
	# Logic: Total - (Currently In House for Night + Reserved Arrivals) - OOO
	# Note: A room that checks out today is available for a new arrival tonight.
	# Maintenance blocks a room just as Out of Order does, so both come out of the
	# sellable count or the console would offer rooms the engine then refuses.
	ooo_rooms = frappe.db.count(
		"Hotel Room", {"status": ["in", BLOCKED_STATUSES], "is_enabled": 1}
	)

	# Committed Rooms = People staying tonight + People arriving tonight
	committed_rooms = in_house_count + arrivals_pending

	available = total_rooms - committed_rooms - ooo_rooms
	if available < 0:
		available = 0

	occupancy_pct = 0
	if total_rooms > 0:
		occupancy_pct = flt((in_house_count / total_rooms) * 100, 1)

	return {
		"arrivals": arrivals,
		"departures": departures,
		"stats": {
			"total_rooms": total_rooms,
			"in_house": in_house_count,
			"occupancy_pct": occupancy_pct,
			"arrivals_pending": arrivals_pending,
			"departures_pending": departures_pending,
			"available": available,
		},
		"nav": get_nav_counts(),
		"user": {
			"name": frappe.session.user,
			"first_name": frappe.db.get_value("User", frappe.session.user, "first_name") or "",
		},
	}


@frappe.whitelist()
def get_nav_counts():
	"""Live badges for the navigation hub.

	A tile with nothing waiting behind it shows no badge at all — a row of zeros
	trains people to stop reading the numbers.
	"""
	counts = {}

	if frappe.has_permission("Hotel Enquiry", "read"):
		open_statuses = frappe.get_all(
			"Hotel Enquiry Status", filters={"type": ["in", OPEN_ENQUIRY_TYPES]}, pluck="name"
		)
		if open_statuses:
			counts["enquiries_due"] = frappe.db.count(
				"Hotel Enquiry",
				{"status": ["in", open_statuses], "next_follow_up": ["<=", frappe.utils.now_datetime()]},
			)
			counts["enquiries_open"] = frappe.db.count(
				"Hotel Enquiry", {"status": ["in", open_statuses]}
			)

	if frappe.has_permission("CRM Call Log", "read"):
		# Capped: the badge renders CALL_BADGE_CAP as "99+" rather than claiming an
		# exact number it did not actually count.
		counts["calls_unlinked"] = telephony.count_unlinked_calls(cap=CALL_BADGE_CAP)
		counts["calls_unlinked_cap"] = CALL_BADGE_CAP

	if frappe.has_permission("Hotel Booking", "read"):
		# What the desk has to honour: money is in, the guest has not arrived yet.
		counts["bookings_due"] = frappe.db.count(
			"Hotel Booking",
			{"status": ["in", ("Confirmed", "Tentative")], "arrival_date": [">=", nowdate()]},
		)

	if frappe.has_permission("Hotel Room", "read"):
		counts["rooms_dirty"] = frappe.db.count("Hotel Room", {"status": "Dirty", "is_enabled": 1})
		counts["rooms_ooo"] = frappe.db.count(
			"Hotel Room", {"status": ["in", BLOCKED_STATUSES], "is_enabled": 1}
		)

	if frappe.has_permission("Hotel Maintenance Request", "read"):
		counts["maintenance_open"] = frappe.db.count(
			"Hotel Maintenance Request", {"status": ["in", ("Reported", "In Progress")]}
		)

	return counts


@frappe.whitelist()
def search(query=None):
	"""One box, every record a front desk gets asked about by name or phone.

	A guest on the phone gives a name or a number, never a docname, and the desk
	should not have to guess whether that person is a reservation, a booking or
	still an enquiry. Each block is permission-guarded and skipped silently, so a
	sales agent searching sees enquiries and bookings and no reservation leak.
	"""
	query = (query or "").strip()
	if len(query) < 2:
		return []

	like = f"%{query}%"
	phone_key = telephony.match_key(query)
	results = []

	if frappe.has_permission("Hotel Reservation", "read"):
		rows = frappe.db.sql(
			"""
            SELECT res.name, g.full_name AS title, res.status, res.room,
                   res.arrival_date, res.departure_date
            FROM `tabHotel Reservation` res
            LEFT JOIN `tabGuest` g ON res.guest = g.name
            WHERE g.full_name LIKE %(like)s OR res.name LIKE %(like)s
               OR res.room LIKE %(like)s
               OR (%(phone_key)s != '' AND {guest_digits} LIKE %(phone_like)s)
            ORDER BY res.arrival_date DESC
            LIMIT %(limit)s
        """.format(guest_digits=_digits("g.mobile_no")),
			{
				"like": like,
				"phone_key": phone_key,
				"phone_like": f"%{phone_key}",
				"limit": SEARCH_LIMIT,
			},
			as_dict=True,
		)
		for r in rows:
			results.append(
				{
					"doctype": "Hotel Reservation",
					"name": r.name,
					"title": r.title or r.name,
					"subtitle": _stay_line(r.room, r.arrival_date, r.departure_date),
					"status": r.status,
				}
			)

	if frappe.has_permission("Hotel Booking", "read"):
		rows = frappe.db.sql(
			"""
            SELECT b.name, b.guest_name AS title, b.status, b.arrival_date, b.departure_date
            FROM `tabHotel Booking` b
            WHERE (
                    b.guest_name LIKE %(like)s OR b.name LIKE %(like)s
                    OR (%(phone_key)s != '' AND {booking_digits} LIKE %(phone_like)s)
                  )
              AND b.docstatus < 2
            ORDER BY b.arrival_date DESC
            LIMIT %(limit)s
        """.format(booking_digits=_digits("b.mobile_no")),
			{
				"like": like,
				"phone_key": phone_key,
				"phone_like": f"%{phone_key}",
				"limit": SEARCH_LIMIT,
			},
			as_dict=True,
		)
		for r in rows:
			results.append(
				{
					"doctype": "Hotel Booking",
					"name": r.name,
					"title": r.title or r.name,
					"subtitle": _stay_line(None, r.arrival_date, r.departure_date),
					"status": r.status,
				}
			)

	if frappe.has_permission("Hotel Enquiry", "read"):
		# mobile_key is the indexed digits-only column the telephony bridge maintains,
		# so a phone search hits an index instead of scanning every enquiry.
		conditions = ["e.guest_name LIKE %(like)s", "e.name LIKE %(like)s"]
		params = {"like": like, "limit": SEARCH_LIMIT}
		if phone_key:
			conditions.append("e.mobile_key = %(phone_key)s")
			params["phone_key"] = phone_key
		rows = frappe.db.sql(
			f"""
            SELECT e.name, e.guest_name AS title, e.status, e.check_in_date, e.check_out_date
            FROM `tabHotel Enquiry` e
            WHERE {" OR ".join(conditions)}
            ORDER BY e.modified DESC
            LIMIT %(limit)s
        """,
			params,
			as_dict=True,
		)
		for r in rows:
			results.append(
				{
					"doctype": "Hotel Enquiry",
					"name": r.name,
					"title": r.title or r.name,
					"subtitle": _stay_line(None, r.check_in_date, r.check_out_date),
					"status": r.status,
				}
			)

	if frappe.has_permission("Guest", "read"):
		rows = frappe.db.sql(
			"""
            SELECT name, full_name, mobile_no
            FROM `tabGuest`
            WHERE full_name LIKE %(like)s
               OR (%(phone_key)s != '' AND {guest_digits} LIKE %(phone_like)s)
            ORDER BY modified DESC
            LIMIT %(limit)s
        """.format(guest_digits=_digits("mobile_no")),
			{
				"like": like,
				"phone_key": phone_key,
				"phone_like": f"%{phone_key}",
				"limit": SEARCH_LIMIT,
			},
			as_dict=True,
		)
		for r in rows:
			results.append(
				{
					"doctype": "Guest",
					"name": r.name,
					"title": r.full_name or r.name,
					"subtitle": r.mobile_no or "",
					"status": None,
				}
			)

	return results


def _stay_line(room, arrival, departure):
	parts = []
	if room:
		parts.append(str(room))
	if arrival:
		parts.append(frappe.utils.formatdate(arrival, "d MMM"))
	if departure:
		parts.append("→ " + frappe.utils.formatdate(departure, "d MMM"))
	return " · ".join(parts)
