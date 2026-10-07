"""Backend for the Call History console (/app/call-history).

The question this page answers is "who has been ringing us, how many times, and did
anyone get back to them" — so the unit on screen is a *number*, not a call. A guest who
rang six times is one person to call back, not six rows to read past; the six calls are
there when you open them.

Every figure is derived from `custom_number_key`, the last-10-digits column the telephony
bridge stamps on each call log. It is indexed, and it is the same key Hotel Enquiry
matches on, so "has anyone dealt with this caller" is a keyed lookup rather than a
normalise-and-compare over the whole enquiry table.

The list is deliberately two queries deep: one aggregate to rank the numbers and one
lookup to decorate the page of numbers that survived. Joining the enquiry in during the
aggregate fans the group out per matching enquiry and silently multiplies the counts.
"""

import frappe
from frappe import _
from frappe.utils import cint, nowdate

from hospitality_core.hospitality_core.api.telephony import UNANSWERED_STATUSES, handset_sql

PAGE_SIZE = 40

# A number with more history than this is a relationship, not a follow-up: the desk
# needs the recent shape of it, not every call since the handset was commissioned.
CALLS_PER_NUMBER = 200

# The guest's own number: ours is the other end of the call.
GUEST_NUMBER = "CASE WHEN cl.type = 'Outgoing' THEN cl.`to` ELSE cl.`from` END"

# No enquiry exists for this number at all — not merely that the link field on the call
# is blank, which is also true of calls logged before their enquiry was created.
NO_ENQUIRY = """NOT EXISTS (
	SELECT 1 FROM `tabHotel Enquiry` he
	WHERE he.mobile_key = cl.custom_number_key OR he.alt_mobile_key = cl.custom_number_key
)"""

VIEWS = ("all", "followup", "missed", "today")

# Keys a search may pull in before it is more useful to ask the user to be specific.
SEARCH_KEY_LIMIT = 300


def _guard():
	if not frappe.has_permission("CRM Call Log", "read"):
		frappe.throw(_("Not permitted to read call logs"), frappe.PermissionError)


def _per_number_sql(where="", having="", order="last_time DESC", limit_sql=""):
	"""One row per number, with the whole of that number's history behind each figure.

	`talk_seconds` counts connected calls only, so a run of unanswered dials does not
	read as time spent with the guest.
	"""
	return f"""
		SELECT
			cl.custom_number_key AS number_key,
			COUNT(*) AS calls,
			SUM(cl.type = 'Incoming') AS incoming,
			SUM(cl.type = 'Outgoing') AS outgoing,
			SUM(cl.status IN %(unanswered)s) AS missed,
			SUM(cl.status = 'Completed') AS connected,
			SUM(CASE WHEN cl.status = 'Completed' THEN IFNULL(cl.duration, 0) ELSE 0 END)
				AS talk_seconds,
			SUM(DATE(cl.start_time) = %(today)s) AS calls_today,
			MAX(cl.start_time) AS last_time,
			MIN(cl.start_time) AS first_time,
			MAX({NO_ENQUIRY}) AS no_enquiry
		FROM `tabCRM Call Log` cl
		WHERE IFNULL(cl.custom_number_key, '') != '' {where}
		GROUP BY cl.custom_number_key
		{having}
		ORDER BY {order}
		{limit_sql}
	"""


def _having_for(view):
	"""Views that can only be decided once a number's whole history is in hand.

	"Missed" means nobody ever got through — a number with one missed call and one
	conversation has been dealt with, and putting it in the callback queue sends an
	agent to ring a guest they already spoke to.
	"""
	if view == "missed":
		return "HAVING connected = 0 AND missed > 0"
	if view == "followup":
		return "HAVING no_enquiry = 1"
	if view == "today":
		return "HAVING calls_today > 0"
	return ""


@frappe.whitelist()
def get_overview(view="all", search=None, sort="recent", start=0, page_size=PAGE_SIZE):
	"""The number list, the totals above it, and the count behind each tab."""
	_guard()

	view = view if view in VIEWS else "all"
	start, page_size = cint(start), cint(page_size) or PAGE_SIZE
	search = (search or "").strip()

	params = {"unanswered": UNANSWERED_STATUSES, "today": nowdate()}
	where = ""

	# A search is answered from the whole log, whatever tab is open: someone typing a
	# number mid-call wants that caller found, not told they are on the wrong tab.
	if search:
		keys = _search_keys(search)
		if not keys:
			return {
				"totals": _empty_totals(),
				"tabs": _tab_counts(params),
				"numbers": [],
				"has_more": False,
				"view": view,
				"search": search,
			}
		where = " AND cl.custom_number_key IN %(keys)s"
		params["keys"] = tuple(keys)
		having = ""
	else:
		having = _having_for(view)

	order = "calls DESC, last_time DESC" if sort == "calls" else "last_time DESC"

	# One row past the page, so "load more" is offered only when there is more.
	params["limit"] = page_size + 1
	params["offset"] = start
	rows = frappe.db.sql(
		_per_number_sql(where, having, order, "LIMIT %(limit)s OFFSET %(offset)s"),
		params,
		as_dict=True,
	)

	has_more = len(rows) > page_size
	rows = rows[:page_size]
	_decorate(rows)

	return {
		"totals": _totals(where, having, params),
		"tabs": _tab_counts(params),
		"numbers": rows,
		"has_more": has_more,
		"view": view,
		"search": search,
	}


def _search_keys(search):
	"""Numbers a search text refers to, resolved before anything is aggregated.

	Matching inside the aggregate would count only the rows that matched — a caller
	found by the name on one of their calls would then show a call count of 1.
	"""
	digits = "".join(ch for ch in search if ch.isdigit())
	conditions = ["cl.custom_contact_name LIKE %(like)s"]
	args = {"like": f"%{search}%", "limit": SEARCH_KEY_LIMIT}

	if digits:
		conditions.append("cl.custom_number_key LIKE %(digits)s")
		args["digits"] = f"%{digits}%"

	rows = frappe.db.sql(
		f"""
		SELECT DISTINCT cl.custom_number_key
		FROM `tabCRM Call Log` cl
		WHERE IFNULL(cl.custom_number_key, '') != '' AND ({" OR ".join(conditions)})
		LIMIT %(limit)s
		""",
		args,
	)
	keys = [r[0] for r in rows]

	# The guest may be known to the hotel under a name that never reached a handset,
	# so an enquiry match brings its number in even with nothing in the call log's own
	# contact column.
	for key in frappe.db.sql(
		"""
		SELECT mobile_key FROM `tabHotel Enquiry`
		WHERE guest_name LIKE %(like)s AND IFNULL(mobile_key, '') != ''
		LIMIT %(limit)s
		""",
		args,
	):
		if key[0] not in keys:
			keys.append(key[0])

	return keys


def _totals(where, having, params):
	"""The figures above the list, for whatever is currently being listed."""
	inner = _per_number_sql(where, having)
	row = frappe.db.sql(
		f"""
		SELECT COUNT(*) AS numbers,
		       IFNULL(SUM(calls), 0) AS calls,
		       IFNULL(SUM(incoming), 0) AS incoming,
		       IFNULL(SUM(outgoing), 0) AS outgoing,
		       IFNULL(SUM(missed), 0) AS missed,
		       IFNULL(SUM(connected), 0) AS connected,
		       IFNULL(SUM(talk_seconds), 0) AS talk_seconds,
		       IFNULL(SUM(no_enquiry), 0) AS no_enquiry
		FROM ({inner}) g
		""",
		params,
		as_dict=True,
	)
	return row[0] if row else _empty_totals()


def _empty_totals():
	return {
		"numbers": 0, "calls": 0, "incoming": 0, "outgoing": 0,
		"missed": 0, "connected": 0, "talk_seconds": 0, "no_enquiry": 0,
	}


def _tab_counts(params):
	"""How many numbers sit behind each tab. Counted once, over the same grouping the
	list itself uses, so a tab never promises rows the list cannot show."""
	row = frappe.db.sql(
		f"""
		SELECT COUNT(*) AS `all`,
		       IFNULL(SUM(no_enquiry = 1), 0) AS followup,
		       IFNULL(SUM(connected = 0 AND missed > 0), 0) AS missed,
		       IFNULL(SUM(calls_today > 0), 0) AS today
		FROM ({_per_number_sql()}) g
		""",
		{"unanswered": params["unanswered"], "today": params["today"]},
		as_dict=True,
	)
	return row[0] if row else {"all": 0, "followup": 0, "missed": 0, "today": 0}


def _decorate(rows):
	"""Add the last call and the enquiry to a page of numbers, in two queries.

	Done after the LIMIT so the cost follows what is on screen rather than the size of
	the log.
	"""
	if not rows:
		return

	keys = tuple({r.number_key for r in rows})
	by_key = {r.number_key: r for r in rows}

	# The most recent call carries the number as dialled and the name the handset had,
	# which is what the desk reads the row by.
	last = frappe.db.sql(
		f"""
		SELECT cl.custom_number_key AS number_key, cl.name AS call_log,
		       {GUEST_NUMBER} AS number, cl.custom_contact_name AS contact_name,
		       cl.type, cl.status, cl.start_time, cl.duration, cl.custom_agent
		FROM `tabCRM Call Log` cl
		JOIN (
			SELECT custom_number_key, MAX(start_time) AS mx
			FROM `tabCRM Call Log`
			WHERE custom_number_key IN %(keys)s
			GROUP BY custom_number_key
		) m ON m.custom_number_key = cl.custom_number_key AND cl.start_time = m.mx
		WHERE cl.custom_number_key IN %(keys)s
		""",
		{"keys": keys},
		as_dict=True,
	)
	for row in last:
		target = by_key.get(row.number_key)
		# Two calls can share a timestamp to the second; the first is enough to label
		# the row, and taking both would overwrite one with the other at random.
		if not target or target.get("last_type"):
			continue
		target.update({
			"number": row.number,
			"contact_name": row.contact_name,
			"last_call": row.call_log,
			"last_type": row.type,
			"last_status": row.status,
			"last_duration": row.duration,
			"last_agent": row.custom_agent,
		})

	for row in frappe.db.sql(
		"""
		SELECT he.name, he.guest_name, he.status, he.next_follow_up, he.enquiry_owner,
		       he.mobile_key, he.alt_mobile_key, hes.type AS status_type
		FROM `tabHotel Enquiry` he
		LEFT JOIN `tabHotel Enquiry Status` hes ON hes.name = he.status
		WHERE he.mobile_key IN %(keys)s OR he.alt_mobile_key IN %(keys)s
		ORDER BY (hes.type IN ('Open', 'Ongoing')) DESC, he.modified DESC
		""",
		{"keys": keys},
		as_dict=True,
	):
		for key in (row.mobile_key, row.alt_mobile_key):
			target = by_key.get(key)
			# Ordered open-first, so the first enquiry to land on a number is the one
			# worth showing; a guest who has enquired four times gets the live one.
			if target and not target.get("enquiry"):
				target.update({
					"enquiry": row.name,
					"enquiry_guest": row.guest_name,
					"enquiry_status": row.status,
					"enquiry_status_type": row.status_type,
					"enquiry_owner": row.enquiry_owner,
					"next_follow_up": row.next_follow_up,
				})


@frappe.whitelist()
def get_number(number_key):
	"""One caller: their totals, every call behind them, and who they already are to us."""
	_guard()

	key = (number_key or "").strip()
	if not key:
		frappe.throw(_("No number selected."))

	summary = frappe.db.sql(
		_per_number_sql(" AND cl.custom_number_key = %(key)s"),
		{"key": key, "unanswered": UNANSWERED_STATUSES, "today": nowdate()},
		as_dict=True,
	)
	if not summary:
		return {"number_key": key, "calls": [], "summary": None}

	summary = summary[0]

	join, number_expr, label_expr = handset_sql()
	calls = frappe.db.sql(
		f"""
		SELECT cl.name, cl.`from`, cl.`to`, cl.type, cl.status, cl.duration, cl.start_time,
		       cl.end_time, cl.custom_contact_name AS contact_name, cl.custom_agent AS agent,
		       cl.custom_channel AS channel, cl.custom_sim_slot AS sim_slot,
		       cl.custom_hotel_enquiry AS enquiry, cl.recording_url,
		       {GUEST_NUMBER} AS number, {number_expr} AS line, {label_expr} AS line_label
		FROM `tabCRM Call Log` cl
		{join}
		WHERE cl.custom_number_key = %(key)s
		ORDER BY cl.start_time DESC
		LIMIT %(limit)s
		""",
		{"key": key, "limit": CALLS_PER_NUMBER},
		as_dict=True,
	)

	newest = calls[0] if calls else {}
	number = newest.get("number") or key
	contact_name = next((c.contact_name for c in calls if c.contact_name), None)

	return {
		"number_key": key,
		"number": number,
		"contact_name": contact_name,
		"summary": summary,
		"calls": calls,
		"truncated": len(calls) >= CALLS_PER_NUMBER,
		"enquiry": _enquiry_for(key),
		"guest": _guest_for(key),
	}


def _enquiry_for(key):
	rows = frappe.db.sql(
		"""
		SELECT he.name, he.guest_name, he.status, he.next_follow_up, he.enquiry_owner,
		       he.check_in_date, he.check_out_date, he.last_contacted, hes.type AS status_type
		FROM `tabHotel Enquiry` he
		LEFT JOIN `tabHotel Enquiry Status` hes ON hes.name = he.status
		WHERE he.mobile_key = %(key)s OR he.alt_mobile_key = %(key)s
		ORDER BY (hes.type IN ('Open', 'Ongoing')) DESC, he.modified DESC
		LIMIT 1
		""",
		{"key": key},
		as_dict=True,
	)
	return rows[0] if rows else None


def _guest_for(key):
	"""The guest behind this number, if the hotel already knows them.

	Guest has no match key of its own, so its phone columns are normalised here. One
	row per guest and only for the number on screen, so it is a scan of a small table
	once per selection, not per call.
	"""
	if not frappe.has_permission("Guest", "read"):
		return None

	digits = "REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(IFNULL(mobile_no, ''), ' ', ''), '+', ''), '-', ''), '(', ''), ')', '')"
	rows = frappe.db.sql(
		f"""
		SELECT name, full_name, mobile_no, email_id, guest_type
		FROM `tabGuest`
		WHERE {digits} LIKE %(like)s
		ORDER BY modified DESC
		LIMIT 1
		""",
		{"like": f"%{key}"},
		as_dict=True,
	)
	return rows[0] if rows else None
