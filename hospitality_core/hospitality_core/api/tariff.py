"""Canonical pricing and room-type presentation for Hospitality Core.

Before this module every surface priced a stay by multiplying one nightly rate by the
number of nights. That was wrong the moment the property's real tariff sheet arrived:
rates differ on weekends, so a Friday-to-Monday stay in the Pinnacle Suite is not
3 x 16,800 but 3 x 18,900, and a Thursday-to-Sunday stay is neither.

Everything that quotes money for a stay — the POS cart, the booking form, the enquiry
quote, the reservation preview, the night audit — goes through `quote_stay` so they all
produce the same number.

How the property prices a room
------------------------------
`default_rate` is the weekday tariff and `weekend_rate` the premium one, charged on
Saturdays, Sundays and any date in the property's Holiday List; each covers the room for
up to `max_occupancy` guests. The sheet's "W/Head/Day" and
"WE/Head/Day" columns are that tariff divided by `max_occupancy` — the per-head unit
price, used when a group is sold by headcount rather than by room. A guest beyond
`max_occupancy` needs an extra bed, charged per night at the adult or child rate.

So a room type prices one of two ways, chosen by `pricing_basis`:

    Flat Room Rate  nightly tariff, whatever the headcount (up to max_occupancy)
    Per Head        guests x per-head rate for that night

plus extra beds either way.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate

from hospitality_core.hospitality_core.doctype.hotel_room_type.hotel_room_type import (
	get_tariff_holiday_list,
	is_premium_date,
	rate_class,
)

# Fields that together describe a room type to a human: what it is, who fits, what it
# costs, what is in it. Read once here so every surface shows the same card.
CATALOG_FIELDS = [
	"name",
	"bedroom_configuration",
	"no_of_bedrooms",
	"description",
	"is_active",
	"max_occupancy",
	"max_adults",
	"max_children",
	"pricing_basis",
	"default_rate",
	"weekend_rate",
	"per_head_rate_weekday",
	"per_head_rate_weekend",
	"extra_bed_adult_rate",
	"extra_bed_child_rate",
	"has_tea_coffee_toiletries",
	"has_fridge",
	"has_tv",
	"has_wifi",
	"has_private_pool",
]

# (fieldname, short label, emoji). Order is the order they render in, everywhere.
AMENITIES = [
	("has_tv", "TV", "📺"),
	("has_wifi", "Wi-Fi", "📶"),
	("has_fridge", "Fridge", "🧊"),
	("has_private_pool", "Private Pool", "🏊"),
	("has_tea_coffee_toiletries", "Tea/Coffee", "☕"),
]


def amenity_list(row):
	"""The amenities a room type has, as [{key, label, icon}], in display order."""
	return [
		{"key": field, "label": label, "icon": icon}
		for field, label, icon in AMENITIES
		if cint(row.get(field))
	]


def _decorate(row):
	"""Add the derived bits every surface wants so none of them recompute it."""
	row = frappe._dict(row)
	row["amenities"] = amenity_list(row)
	row["amenity_labels"] = [a["label"] for a in row["amenities"]]
	row["room_type"] = row.get("name")
	# A weekend rate equal to the weekday one is not worth showing twice in the UI.
	row["has_weekend_premium"] = flt(row.get("weekend_rate")) > flt(row.get("default_rate"))
	return row


@frappe.whitelist()
def get_room_type_catalog(only_active=True, room_type=None):
	"""Every room type with its capacity, tariff and amenities.

	This is the one read the POS, the CRM console and the booking form use to build
	their room-type pickers, so a category always presents the same way.
	"""
	filters = {}
	if cint(only_active):
		filters["is_active"] = 1
	if room_type:
		filters["name"] = room_type

	rows = frappe.get_all(
		"Hotel Room Type", filters=filters, fields=CATALOG_FIELDS, order_by="name asc"
	)
	return [_decorate(r) for r in rows]


@frappe.whitelist()
def get_room_type_details(room_type):
	"""One room type, decorated. None if it does not exist."""
	rows = get_room_type_catalog(only_active=False, room_type=room_type)
	return rows[0] if rows else None


def _rates_for(room_type):
	row = frappe.db.get_value("Hotel Room Type", room_type, CATALOG_FIELDS, as_dict=True)
	if not row:
		frappe.throw(_("Room Type {0} does not exist.").format(room_type))
	return row


def nightly_rate(rates, date, basis=None, holiday_list=None):
	"""The room's tariff for the night beginning on `date`, before extra beds.

	Premium nights — Saturday, Sunday, or a date in the Holiday List — take the
	weekend side of every rate pair.
	"""
	premium = is_premium_date(date, holiday_list)
	basis = basis or rates.get("pricing_basis") or "Flat Room Rate"

	if basis == "Per Head":
		per_head = flt(
			rates.get("per_head_rate_weekend") if premium
			else rates.get("per_head_rate_weekday")
		)
		# Fall back to deriving it rather than quoting zero if the field is blank.
		if not per_head and cint(rates.get("max_occupancy")):
			base = flt(rates.get("weekend_rate") if premium else rates.get("default_rate"))
			per_head = base / cint(rates["max_occupancy"])
		return per_head

	rate = flt(rates.get("weekend_rate")) if premium else flt(rates.get("default_rate"))
	# A blank weekend rate means "same as weekday".
	return rate or flt(rates.get("default_rate"))


@frappe.whitelist()
def quote_stay(room_type, arrival_date, departure_date, qty=1, adults=0, children=0,
               extra_beds_adult=0, extra_beds_child=0, rate_plan=None, basis=None):
	"""Price one room type for one stay window, night by night.

	Returns a breakdown rather than a single number so the front desk can show the
	guest why a weekend stay costs more than a weekday one.

	    {
	      "nights": [{date, weekend, rate_class, rate, extra_bed, amount}],
	      "room_nights": n, "qty": n,
	      "room_total": x, "extra_bed_total": x, "total": x,
	      "average_nightly": x, "basis": "...", "currency": "INR",
	      "capacity": {...}, "warnings": [...]
	    }
	"""
	qty = max(cint(qty), 1)
	adults, children = cint(adults), cint(children)
	extra_beds_adult, extra_beds_child = cint(extra_beds_adult), cint(extra_beds_child)

	start, end = getdate(arrival_date), getdate(departure_date)
	if end <= start:
		frappe.throw(_("Departure must be after arrival."))

	rates = _rates_for(room_type)
	basis = basis or rates.get("pricing_basis") or "Flat Room Rate"

	# Resolved once for the whole window: a fortnight's stay would otherwise re-read
	# the setting and the holiday table for every night.
	holiday_list = get_tariff_holiday_list()

	# A negotiated Rate Plan overrides the tariff outright while it is in force.
	plan = None
	if rate_plan and frappe.db.exists("Room Rate Plan", rate_plan):
		plan = frappe.db.get_value(
			"Room Rate Plan", rate_plan, ["rate", "valid_from", "valid_to", "active"],
			as_dict=True,
		)

	heads = adults + children
	max_occupancy = cint(rates.get("max_occupancy")) or 1
	bed_adult = flt(rates.get("extra_bed_adult_rate"))
	bed_child = flt(rates.get("extra_bed_child_rate"))
	extra_bed_per_night = (extra_beds_adult * bed_adult) + (extra_beds_child * bed_child)

	nights, room_total = [], 0.0
	current = start
	while current < end:
		if plan and plan.active and getdate(plan.valid_from) <= current <= getdate(plan.valid_to):
			rate = flt(plan.rate)
			source = "Rate Plan"
		else:
			rate = nightly_rate(rates, current, basis, holiday_list)
			source = basis

		# Per-head pricing multiplies by the people actually staying.
		line_rate = rate * max(heads, 1) if basis == "Per Head" and source != "Rate Plan" else rate
		amount = (line_rate + extra_bed_per_night) * qty
		room_total += line_rate * qty

		night_class = rate_class(current, holiday_list)
		nights.append({
			"date": str(current),
			# `weekend` stays in the payload as "is this priced at the premium rate";
			# `rate_class` says which of Weekend or Holiday made it so.
			"weekend": night_class != "Weekday",
			"rate_class": night_class,
			"rate": flt(line_rate, 2),
			"source": source,
			"extra_bed": flt(extra_bed_per_night * qty, 2),
			"amount": flt(amount, 2),
		})
		current = add_days(current, 1)

	extra_bed_total = extra_bed_per_night * qty * len(nights)
	total = room_total + extra_bed_total

	warnings = []
	capacity = max_occupancy * qty
	beds = extra_beds_adult + extra_beds_child
	if heads and heads > capacity + beds:
		warnings.append(
			_("{0} guests exceed the {1} allowed in {2} {3} room(s). Add {4} extra bed(s).")
			.format(heads, capacity, qty, room_type, heads - capacity - beds)
		)

	return {
		"room_type": room_type,
		"basis": basis,
		"qty": qty,
		"nights": nights,
		"room_nights": len(nights) * qty,
		"room_total": flt(room_total, 2),
		"extra_bed_total": flt(extra_bed_total, 2),
		"total": flt(total, 2),
		"average_nightly": flt(total / (len(nights) * qty), 2) if nights else 0.0,
		"currency": frappe.defaults.get_global_default("currency") or "INR",
		"premium_nights": sum(1 for n in nights if n["weekend"]),
		"holiday_nights": sum(1 for n in nights if n["rate_class"] == "Holiday"),
		"holiday_list": holiday_list,
		"capacity": {
			"max_occupancy": max_occupancy,
			"per_booking": capacity,
			"guests": heads,
			"extra_beds": beds,
			"within_capacity": not warnings,
		},
		"warnings": warnings,
	}


@frappe.whitelist()
def quote_rooms(lines, arrival_date, departure_date, rate_plan=None):
	"""Price several room-type lines for one stay window.

	`lines` is a list of {room_type, qty, adults, children, extra_beds_adult,
	extra_beds_child}. Used by the booking form and the POS cart, which both hold more
	than one room type at a time.
	"""
	if isinstance(lines, str):
		lines = frappe.parse_json(lines)

	quotes, total = [], 0.0
	for line in lines or []:
		if not line.get("room_type"):
			continue
		q = quote_stay(
			line["room_type"], arrival_date, departure_date,
			qty=line.get("qty", 1), adults=line.get("adults", 0),
			children=line.get("children", 0),
			extra_beds_adult=line.get("extra_beds_adult", 0),
			extra_beds_child=line.get("extra_beds_child", 0),
			rate_plan=rate_plan or line.get("rate_plan"),
		)
		quotes.append(q)
		total += q["total"]

	return {
		"lines": quotes,
		"total": flt(total, 2),
		"warnings": [w for q in quotes for w in q["warnings"]],
		"currency": frappe.defaults.get_global_default("currency") or "INR",
	}


@frappe.whitelist()
def get_tariff_calendar(from_date, to_date):
	"""Which nights in a range carry the premium tariff, and why.

	The booking and enquiry forms use this to mark holiday nights in their quote so a
	guest can see that the higher rate is a public holiday, not an error.
	"""
	start, end = getdate(from_date), getdate(to_date)
	if end < start:
		return {"days": [], "holiday_list": None}

	holiday_list = get_tariff_holiday_list()
	days, current = [], start
	while current <= end:
		cls = rate_class(current, holiday_list)
		days.append({
			"date": str(current),
			"rate_class": cls,
			"premium": cls != "Weekday",
		})
		current = add_days(current, 1)

	return {
		"days": days,
		"holiday_list": holiday_list,
		"premium_days": sum(1 for d in days if d["premium"]),
	}


@frappe.whitelist()
def get_room_details(room):
	"""One physical unit plus everything its category says about it.

	The tape chart, housekeeping board, Guest 360 and the reservation form all want to
	show "what is this room" — capacity, amenities, tariff — and this is that answer.
	"""
	room_row = frappe.db.get_value(
		"Hotel Room", room,
		["name", "room_number", "room_type", "floor", "status", "is_enabled",
		 "hotel_reception"],
		as_dict=True,
	)
	if not room_row:
		return None

	details = get_room_type_details(room_row.room_type) or {}
	room_row["room_type_details"] = details
	room_row["amenities"] = details.get("amenities", [])
	room_row["amenity_labels"] = details.get("amenity_labels", [])
	room_row["max_occupancy"] = details.get("max_occupancy")
	room_row["bedroom_configuration"] = details.get("bedroom_configuration")
	room_row["default_rate"] = details.get("default_rate")
	room_row["weekend_rate"] = details.get("weekend_rate")
	return room_row
