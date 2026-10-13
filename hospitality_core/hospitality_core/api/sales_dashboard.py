"""The owner's sales numbers: what was earned, what was collected, what is owed.

One place computes every figure, and both the Sales Dashboard page and the Hotel Sales
Report read it, so the two never disagree.

Definitions — kept deliberately plain, because the owner reads them as money:

  Revenue      what the stay earned, by the night it was earned: room rent, extra beds,
               services and cancellation charges posted on guests' bills, less the
               discounts given. Amounts include GST (the folio is tax-inclusive).
               Copies of a charge mirrored onto a company or group master bill are
               excluded, so nothing is counted twice.
  Collections  money received (Payment Entries linked to a bill or a booking), by the
               day it was received and by mode of payment. Split into advances (paid
               against a booking before arrival) and settlements (paid on a guest's
               bill). Refunds are money paid back.
  Advances     received in the period, applied to rooms at check-in in the period, and
               the advance money held right now for guests who have not stayed yet.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, date_diff, flt, getdate, nowdate

from hospitality_core.hospitality_core.api.utils import NON_REVENUE_ITEM_CODES, get_tax_config

ROOM_ITEMS = ("ROOM-RENT", "EXTRA-BED")
DISCOUNT_ITEMS = ("DISCOUNT", "COMPLIMENTARY")
CANCELLATION_ITEMS = ("CANCELLATION-FEE",)
STAY_STATUSES = ("Reserved", "Checked In", "Checked Out")


def _range(from_date, to_date):
	start = getdate(from_date or nowdate())
	end = getdate(to_date or start)
	if end < start:
		start, end = end, start
	if date_diff(end, start) > 731:
		frappe.throw(_("Choose a period of two years or less."))
	return start, end


def _days(start, end):
	day, out = start, []
	while day <= end:
		out.append(day)
		day = getdate(add_days(day, 1))
	return out


def _bucket(day, group_by):
	"""The label a date falls under for Day / Week / Month grouping."""
	day = getdate(day)
	if group_by == "Week":
		monday = getdate(add_days(day, -day.weekday()))
		return str(monday)
	if group_by == "Month":
		return day.strftime("%Y-%m-01")
	return str(day)


# ------------------------------------------------------------------ revenue
def _revenue_lines(start, end):
	"""Revenue and discount lines on guests' bills, one row per line."""
	return frappe.db.sql(
		"""
		SELECT ft.posting_date, ft.item, ft.amount, f.reservation,
		       IFNULL(r.room_type, '') AS room_type
		FROM `tabFolio Transaction` ft
		JOIN `tabGuest Folio` f ON f.name = ft.parent
		LEFT JOIN `tabHotel Reservation` r ON r.name = f.reservation
		WHERE ft.posting_date BETWEEN %(start)s AND %(end)s
		  AND ft.is_void = 0
		  AND IFNULL(ft.reference_doctype, '') != 'Folio Transaction'
		  AND IFNULL(f.is_company_master, 0) = 0
		  AND (ft.item IN %(discounts)s OR (ft.amount > 0 AND ft.item NOT IN %(non_revenue)s))
		""",
		{
			"start": start, "end": end,
			"discounts": DISCOUNT_ITEMS,
			"non_revenue": tuple(NON_REVENUE_ITEM_CODES),
		},
		as_dict=True,
	)


def _classify(item):
	if item in DISCOUNT_ITEMS:
		return "discount"
	if item in ROOM_ITEMS:
		return "room"
	if item in CANCELLATION_ITEMS:
		return "cancellation"
	return "extras"


# ------------------------------------------------------------------ payments
def _payments(start, end):
	"""Hotel receipts and refunds in the window, each tagged advance / settlement / refund."""
	rows = frappe.db.sql(
		"""
		SELECT pe.name, pe.posting_date, pe.payment_type, pe.mode_of_payment,
		       pe.paid_amount AS amount, pe.reference_no, pe.party_name, pe.party,
		       pe.guest_folio, pe.hotel_booking,
		       IFNULL(f.is_booking_master, 0) AS booking_master,
		       IFNULL(f.room, '') AS room, IFNULL(g.full_name, '') AS guest_name
		FROM `tabPayment Entry` pe
		LEFT JOIN `tabGuest Folio` f ON f.name = pe.guest_folio
		LEFT JOIN `tabGuest` g ON g.name = f.guest
		WHERE pe.docstatus = 1
		  AND pe.posting_date BETWEEN %(start)s AND %(end)s
		  AND (IFNULL(pe.guest_folio, '') != '' OR IFNULL(pe.hotel_booking, '') != '')
		ORDER BY pe.posting_date DESC, pe.creation DESC
		""",
		{"start": start, "end": end},
		as_dict=True,
	)
	for row in rows:
		if row.payment_type == "Pay":
			row.kind = "Refund"
		elif row.hotel_booking or cint(row.booking_master):
			row.kind = "Advance"
		else:
			row.kind = "Settlement"
		row.mode_of_payment = row.mode_of_payment or _("Unspecified")
		row.guest_name = row.guest_name or row.party_name or row.party
		row.amount = flt(row.amount)
	return rows


def _advances_applied(start, end):
	"""Advance money moved onto room bills at check-in, by day."""
	return frappe.db.sql(
		"""
		SELECT ft.posting_date, -SUM(ft.amount) AS amount
		FROM `tabFolio Transaction` ft
		JOIN `tabGuest Folio` f ON f.name = ft.parent
		WHERE ft.item = 'ADVANCE-TRANSFER' AND ft.amount < 0 AND ft.is_void = 0
		  AND IFNULL(f.is_booking_master, 0) = 0
		  AND ft.posting_date BETWEEN %(start)s AND %(end)s
		GROUP BY ft.posting_date
		""",
		{"start": start, "end": end},
		as_dict=True,
	)


def _advance_held():
	"""Advance money held right now, per booking: credit still on its advance bill."""
	rows = frappe.db.sql(
		"""
		SELECT b.name AS booking, b.guest_name, b.status, b.arrival_date, b.departure_date,
		       b.total_amount, -f.outstanding_balance AS held
		FROM `tabGuest Folio` f
		JOIN `tabHotel Booking` b ON b.booking_folio = f.name
		WHERE IFNULL(f.is_booking_master, 0) = 1 AND f.outstanding_balance < -0.009
		ORDER BY b.arrival_date ASC
		""",
		as_dict=True,
	)
	for r in rows:
		r.held = flt(r.held, 2)
		r.refundable = r.status in ("Cancelled", "No Show")
	return rows


# ------------------------------------------------------------------ occupancy
def _room_count():
	return frappe.db.count("Hotel Room", {"is_enabled": 1}) or 0


def _nights_sold(start, end):
	"""Room nights sold per night.

	The larger of two counts, per night: stays on the books that include the night
	(arrived, in house or confirmed — what future nights have) and room nights actually
	charged on guests' bills that night (what past nights really sold, even for a stay
	whose reservation was later changed or cancelled).
	"""
	charged = {
		str(r.posting_date): cint(r.n)
		for r in frappe.db.sql(
			"""
			SELECT ft.posting_date, COUNT(*) AS n
			FROM `tabFolio Transaction` ft
			JOIN `tabGuest Folio` f ON f.name = ft.parent
			WHERE ft.item = 'ROOM-RENT' AND ft.is_void = 0
			  AND IFNULL(ft.reference_doctype, '') != 'Folio Transaction'
			  AND IFNULL(f.is_company_master, 0) = 0
			  AND ft.posting_date BETWEEN %(start)s AND %(end)s
			GROUP BY ft.posting_date
			""",
			{"start": start, "end": end},
			as_dict=True,
		)
	}
	rows = frappe.db.sql(
		"""
		SELECT arrival_date, departure_date FROM `tabHotel Reservation`
		WHERE status IN %(statuses)s
		  AND arrival_date <= %(end)s AND departure_date > %(start)s
		""",
		{"statuses": STAY_STATUSES, "start": start, "end": end},
		as_dict=True,
	)
	per_day = {}
	for r in rows:
		day = max(getdate(r.arrival_date), start)
		last = min(getdate(r.departure_date), getdate(add_days(end, 1)))
		while day < last:
			per_day[str(day)] = per_day.get(str(day), 0) + 1
			day = getdate(add_days(day, 1))
	for key, n in charged.items():
		per_day[key] = max(per_day.get(key, 0), n)
	return per_day


# ------------------------------------------------------------------ bookings
def _bookings(start, end):
	return frappe.db.sql(
		"""
		SELECT name, status, IFNULL(booking_source, '') AS source, total_amount,
		       advance_received, nights, DATE(creation) AS created,
		       (SELECT COUNT(*) FROM `tabHotel Booking Room` l WHERE l.parent = b.name) AS rooms
		FROM `tabHotel Booking` b
		WHERE DATE(b.creation) BETWEEN %(start)s AND %(end)s
		""",
		{"start": start, "end": end},
		as_dict=True,
	)


def _enquiries(start, end):
	row = frappe.db.sql(
		"""
		SELECT COUNT(*) AS total, SUM(IFNULL(converted, 0)) AS converted
		FROM `tabHotel Enquiry` WHERE DATE(creation) BETWEEN %(start)s AND %(end)s
		""",
		{"start": start, "end": end},
		as_dict=True,
	)[0]
	return cint(row.total), cint(row.converted)


# ------------------------------------------------------------------ position now
def _receivables_now():
	"""What is owed right now: in-house bills, check-outs not yet settled, and the
	balance on bookings arriving in the next 7 days."""
	from hospitality_core.hospitality_core.api.advance import get_advance_balance

	today = getdate(nowdate())
	stays = frappe.db.sql(
		"""
		SELECT r.name, r.hotel_booking, r.departure_date, f.outstanding_balance
		FROM `tabHotel Reservation` r
		JOIN `tabGuest Folio` f ON f.name = r.folio
		WHERE r.status = 'Checked In'
		""",
		as_dict=True,
	)
	in_house, pending, pending_count = 0.0, 0.0, 0
	advance_cache = {}
	for s in stays:
		if s.hotel_booking and s.hotel_booking not in advance_cache:
			advance_cache[s.hotel_booking] = get_advance_balance(s.hotel_booking)
		due = max(flt(s.outstanding_balance) - advance_cache.get(s.hotel_booking, 0.0), 0.0)
		if getdate(s.departure_date) < today:
			pending += due
			pending_count += 1
		else:
			in_house += due

	arriving = flt(frappe.db.sql(
		"""
		SELECT SUM(GREATEST(balance_due, 0)) FROM `tabHotel Booking`
		WHERE status IN ('Tentative', 'Confirmed')
		  AND arrival_date BETWEEN %s AND %s
		""",
		(today, add_days(today, 7)),
	)[0][0])

	return {
		"in_house": flt(in_house, 2),
		"checkout_pending": flt(pending, 2),
		"checkout_pending_count": pending_count,
		"arriving_7_days": flt(arriving, 2),
		"in_house_count": len(stays) - pending_count,
	}


# ------------------------------------------------------------------ assemble
def _summarise(start, end):
	"""Every headline figure for one window."""
	revenue = {"room": 0.0, "extras": 0.0, "cancellation": 0.0, "discount": 0.0}
	by_type = {}
	room_nights_charged = 0
	for line in _revenue_lines(start, end):
		kind = _classify(line.item)
		revenue[kind] += flt(line.amount)
		if kind == "room":
			if line.item == "ROOM-RENT":
				room_nights_charged += 1
			key = line.room_type or _("Other")
			by_type[key] = by_type.get(key, 0.0) + flt(line.amount)

	gross = revenue["room"] + revenue["extras"] + revenue["cancellation"]
	discounts = -revenue["discount"]
	net = gross - discounts
	gst_rate = flt(get_tax_config()["gst_rate"])
	gst = net - net / (1 + gst_rate / 100.0) if gst_rate > 0 else 0.0

	payments = _payments(start, end)
	receipts = sum(p.amount for p in payments if p.kind != "Refund")
	refunds = sum(p.amount for p in payments if p.kind == "Refund")
	advances_received = sum(p.amount for p in payments if p.kind == "Advance")
	applied = sum(flt(a.amount) for a in _advances_applied(start, end))

	rooms = _room_count()
	days = date_diff(end, start) + 1
	nights = _nights_sold(start, end)
	sold = sum(nights.values())
	capacity = rooms * days
	room_revenue = revenue["room"]

	bookings = _bookings(start, end)
	enquiries, converted = _enquiries(start, end)

	return {
		"revenue": {
			"gross": flt(gross, 2),
			"room": flt(revenue["room"], 2),
			"extras": flt(revenue["extras"], 2),
			"cancellation": flt(revenue["cancellation"], 2),
			"discounts": flt(discounts, 2),
			"net": flt(net, 2),
			"gst": flt(gst, 2),
			"gst_rate": gst_rate,
			"ex_gst": flt(net - gst, 2),
		},
		"collections": {
			"receipts": flt(receipts, 2),
			"refunds": flt(refunds, 2),
			"net": flt(receipts - refunds, 2),
			"advances": flt(advances_received, 2),
			"settlements": flt(receipts - advances_received, 2),
		},
		"advances": {"received": flt(advances_received, 2), "applied": flt(applied, 2)},
		"occupancy": {
			"rooms": rooms,
			"days": days,
			"nights_sold": sold,
			"occupancy_pct": flt(sold / capacity * 100, 1) if capacity else 0.0,
			"adr": flt(room_revenue / room_nights_charged, 2) if room_nights_charged else 0.0,
			"revpar": flt(room_revenue / capacity, 2) if capacity else 0.0,
			"nights_charged": room_nights_charged,
		},
		"bookings": {
			"count": len(bookings),
			"value": flt(sum(flt(b.total_amount) for b in bookings if b.status != "Cancelled"), 2),
			"rooms": sum(cint(b.rooms) for b in bookings),
			"cancelled": sum(1 for b in bookings if b.status == "Cancelled"),
			"no_show": sum(1 for b in bookings if b.status == "No Show"),
			"enquiries": enquiries,
			"converted": converted,
			"conversion_pct": flt(converted / enquiries * 100, 1) if enquiries else 0.0,
		},
		"_payments": payments,
		"_nights": nights,
		"_by_type": by_type,
		"_bookings": bookings,
	}


@frappe.whitelist()
def get_dashboard(from_date=None, to_date=None):
	"""Everything the Sales Dashboard shows for a period, with the previous period of
	the same length for comparison."""
	frappe.has_permission("Guest Folio", "read", throw=True)
	start, end = _range(from_date, to_date)
	length = date_diff(end, start) + 1
	prev_end = getdate(add_days(start, -1))
	prev_start = getdate(add_days(prev_end, -(length - 1)))

	cur = _summarise(start, end)
	prev = _summarise(prev_start, prev_end)

	# Daily series for the trend: revenue earned and money collected per day.
	daily = {str(d): {"date": str(d), "revenue": 0.0, "collections": 0.0} for d in _days(start, end)}
	for line in _revenue_lines(start, end):
		daily[str(line.posting_date)]["revenue"] += flt(line.amount)
	for p in cur["_payments"]:
		sign = -1 if p.kind == "Refund" else 1
		daily[str(p.posting_date)]["collections"] += sign * p.amount
	rooms = cur["occupancy"]["rooms"]
	for key, row in daily.items():
		sold = cur["_nights"].get(key, 0)
		row["revenue"] = flt(row["revenue"], 2)
		row["collections"] = flt(row["collections"], 2)
		row["occupancy_pct"] = flt(sold / rooms * 100, 1) if rooms else 0.0
		row["nights_sold"] = sold

	# Collections by mode, split into advances, settlements and refunds.
	modes = {}
	for p in cur["_payments"]:
		m = modes.setdefault(p.mode_of_payment, {
			"mode": p.mode_of_payment, "advance": 0.0, "settlement": 0.0, "refund": 0.0, "count": 0,
		})
		m[p.kind.lower()] += p.amount
		m["count"] += 1
	for m in modes.values():
		m["net"] = flt(m["advance"] + m["settlement"] - m["refund"], 2)
	mode_rows = sorted(modes.values(), key=lambda m: -m["net"])

	sources = {}
	for b in cur["_bookings"]:
		s = sources.setdefault(b.source or _("Not set"), {"source": b.source or _("Not set"), "count": 0, "value": 0.0})
		s["count"] += 1
		if b.status != "Cancelled":
			s["value"] += flt(b.total_amount)
	source_rows = sorted(sources.values(), key=lambda s: (-s["value"], -s["count"]))

	type_rows = sorted(
		({"room_type": k, "revenue": flt(v, 2)} for k, v in cur["_by_type"].items()),
		key=lambda r: -r["revenue"],
	)

	held = _advance_held()

	payments = [
		{
			"name": p.name, "date": str(p.posting_date), "guest": p.guest_name, "room": p.room,
			"mode": p.mode_of_payment, "kind": p.kind, "amount": p.amount,
			"reference": p.reference_no if p.reference_no not in (p.guest_folio, p.hotel_booking) else "",
			"booking": p.hotel_booking,
		}
		for p in cur["_payments"][:60]
	]

	for key in ("_payments", "_nights", "_by_type", "_bookings"):
		cur.pop(key)
		prev.pop(key)

	return {
		"from_date": str(start), "to_date": str(end), "days": length,
		"previous": {"from_date": str(prev_start), "to_date": str(prev_end), **prev},
		**cur,
		"daily": list(daily.values()),
		"modes": mode_rows,
		"sources": source_rows,
		"room_types": type_rows,
		"advance_held": {
			"total": flt(sum(h.held for h in held), 2),
			"refundable": flt(sum(h.held for h in held if h.refundable), 2),
			"bookings": held[:12],
			"count": len(held),
		},
		"receivables": _receivables_now(),
		"payments": payments,
		"currency": frappe.defaults.get_global_default("currency") or "INR",
	}


def get_period_rows(from_date, to_date, group_by="Day"):
	"""Rows for the Hotel Sales Report: one per day / week / month, plus the modes seen."""
	start, end = _range(from_date, to_date)
	group_by = group_by if group_by in ("Day", "Week", "Month") else "Day"
	rooms = _room_count()

	rows = {}

	def row_for(day):
		key = _bucket(day, group_by)
		return rows.setdefault(key, {
			"period": key, "nights_sold": 0, "capacity": 0, "nights_charged": 0,
			"room": 0.0, "extras": 0.0, "cancellation": 0.0, "discounts": 0.0,
			"advances": 0.0, "settlements": 0.0, "refunds": 0.0, "applied": 0.0,
			"bookings": 0, "booking_value": 0.0, "modes": {},
		})

	nights = _nights_sold(start, end)
	for day in _days(start, end):
		r = row_for(day)
		r["capacity"] += rooms
		r["nights_sold"] += nights.get(str(day), 0)

	for line in _revenue_lines(start, end):
		r = row_for(line.posting_date)
		kind = _classify(line.item)
		if kind == "discount":
			r["discounts"] += -flt(line.amount)
		else:
			r[kind] += flt(line.amount)
			if line.item == "ROOM-RENT":
				r["nights_charged"] += 1

	modes_seen = set()
	for p in _payments(start, end):
		r = row_for(p.posting_date)
		if p.kind == "Refund":
			r["refunds"] += p.amount
			r["modes"][p.mode_of_payment] = r["modes"].get(p.mode_of_payment, 0.0) - p.amount
		else:
			r["advances" if p.kind == "Advance" else "settlements"] += p.amount
			r["modes"][p.mode_of_payment] = r["modes"].get(p.mode_of_payment, 0.0) + p.amount
		modes_seen.add(p.mode_of_payment)

	for a in _advances_applied(start, end):
		row_for(a.posting_date)["applied"] += flt(a.amount)

	for b in _bookings(start, end):
		r = row_for(b.created)
		r["bookings"] += 1
		if b.status != "Cancelled":
			r["booking_value"] += flt(b.total_amount)

	gst_rate = flt(get_tax_config()["gst_rate"])
	out = []
	for key in sorted(rows):
		r = rows[key]
		net = r["room"] + r["extras"] + r["cancellation"] - r["discounts"]
		r["net_revenue"] = flt(net, 2)
		r["gst"] = flt(net - net / (1 + gst_rate / 100.0), 2) if gst_rate > 0 else 0.0
		r["occupancy_pct"] = flt(r["nights_sold"] / r["capacity"] * 100, 1) if r["capacity"] else 0.0
		r["adr"] = flt(r["room"] / r["nights_charged"], 2) if r["nights_charged"] else 0.0
		r["collections"] = flt(r["advances"] + r["settlements"] - r["refunds"], 2)
		out.append(r)
	return out, sorted(modes_seen)
