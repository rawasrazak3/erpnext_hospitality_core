"""Pinnacle's real room inventory, as supplied by the property.

This replaces the placeholder demo property (three invented types, five numbered rooms)
that the app shipped with while the real list was unconfirmed.

Two things to know about the shape of this data:

  1. The property names its units instead of numbering them — "Pinnacle Suite",
     "Red Hut", "Germany". That name goes in `Hotel Room.room_number`, which is the
     unit's identity everywhere else in the system.

  2. The tariff sheet prices by *category*, not by unit. Five of the units are
     one-of-a-kind and so are their own category; the other seven share three
     categories (Single Glass House, Double Glass House, Tent House) whose members are
     identical in layout, capacity, amenities and price. `ROOM_TYPES` below is those
     eight categories and `ROOMS` maps each named unit onto one.

    bench --site <site> execute hospitality_core.property_data.load_property
    bench --site <site> execute hospitality_core.property_data.reset_property
"""

import frappe

RECEPTION = "Pinnacle Main"

# Extra-bed charges are flat across every category on the property's sheet, and are what
# a guest beyond Max Allowed costs.
EXTRA_BED_ADULT = 1200
EXTRA_BED_CHILD = 500

# Amenity defaults: every unit on the property has these.
BASE_AMENITIES = {
	"has_tea_coffee_toiletries": 1,
	"has_wifi": 1,
	"has_tv": 1,
	"has_fridge": 0,
	"has_private_pool": 0,
}


def _amenities(**overrides):
	return {**BASE_AMENITIES, **overrides}


ROOM_TYPES = [
	{
		"room_type_name": "Pinnacle Suite",
		"bedroom_configuration": "3BH",
		"no_of_bedrooms": 3,
		"max_occupancy": 10,
		"default_rate": 16800,
		"weekend_rate": 18900,
		"per_head_rate_weekday": 1680,
		"per_head_rate_weekend": 1890,
		"description": "Three-bedroom suite with a private pool and fridge.",
		**_amenities(has_fridge=1, has_private_pool=1),
	},
	{
		"room_type_name": "White House",
		"bedroom_configuration": "2BH",
		"no_of_bedrooms": 2,
		"max_occupancy": 8,
		"default_rate": 12600,
		"weekend_rate": 14800,
		"per_head_rate_weekday": 1575,
		"per_head_rate_weekend": 1850,
		"description": "Two-bedroom house.",
		**_amenities(),
	},
	{
		"room_type_name": "Pool Side Villa",
		"bedroom_configuration": "1 Bed Room 2 Beds",
		"no_of_bedrooms": 1,
		"max_occupancy": 5,
		"default_rate": 7870,
		"weekend_rate": 7870,
		"per_head_rate_weekday": 1574,
		"per_head_rate_weekend": 1574,
		"description": "One bedroom with two beds, beside the pool.",
		**_amenities(),
	},
	{
		"room_type_name": "Red Hut",
		"bedroom_configuration": "1B",
		"no_of_bedrooms": 1,
		"max_occupancy": 5,
		"default_rate": 7870,
		"weekend_rate": 7870,
		"per_head_rate_weekday": 1574,
		"per_head_rate_weekend": 1574,
		"description": "Single-bedroom hut.",
		**_amenities(),
	},
	{
		"room_type_name": "Pool Villa",
		"bedroom_configuration": "4BH",
		"no_of_bedrooms": 4,
		"max_occupancy": 12,
		"default_rate": 16800,
		"weekend_rate": 18900,
		"per_head_rate_weekday": 1400,
		"per_head_rate_weekend": 1575,
		"description": "Four-bedroom villa with a private pool.",
		**_amenities(has_private_pool=1),
	},
	{
		"room_type_name": "Single Glass House",
		"bedroom_configuration": "1B",
		"no_of_bedrooms": 1,
		"max_occupancy": 4,
		"default_rate": 5280,
		"weekend_rate": 6300,
		"per_head_rate_weekday": 1320,
		"per_head_rate_weekend": 1575,
		"description": "Single glass house. No television.",
		**_amenities(has_tv=0),
	},
	{
		"room_type_name": "Double Glass House",
		"bedroom_configuration": "2B",
		"no_of_bedrooms": 1,
		"max_occupancy": 5,
		"default_rate": 7870,
		"weekend_rate": 7870,
		"per_head_rate_weekday": 1574,
		"per_head_rate_weekend": 1574,
		"description": "Double glass house, two beds. No television.",
		**_amenities(has_tv=0),
	},
	{
		"room_type_name": "Tent House",
		"bedroom_configuration": "1B",
		"no_of_bedrooms": 1,
		"max_occupancy": 5,
		"default_rate": 5250,
		"weekend_rate": 5250,
		"per_head_rate_weekday": 1050,
		"per_head_rate_weekend": 1050,
		"description": "Single-bedroom tent house. No television.",
		**_amenities(has_tv=0),
	},
]

# The twelve sellable units, in the order the property lists them. `floor` doubles as the
# block/zone label the housekeeping board groups by.
ROOMS = [
	{"room_number": "Pinnacle Suite", "room_type": "Pinnacle Suite", "floor": "Main Block"},
	{"room_number": "White House", "room_type": "White House", "floor": "Main Block"},
	{"room_number": "Pool Side Villa", "room_type": "Pool Side Villa", "floor": "Pool Side"},
	{"room_number": "Red Hut", "room_type": "Red Hut", "floor": "Main Block"},
	{"room_number": "Pool Villa", "room_type": "Pool Villa", "floor": "Pool Side"},
	{"room_number": "Germany", "room_type": "Single Glass House", "floor": "Glass House Zone"},
	{"room_number": "France", "room_type": "Single Glass House", "floor": "Glass House Zone"},
	{"room_number": "Argentina", "room_type": "Double Glass House", "floor": "Glass House Zone"},
	{"room_number": "Brazil", "room_type": "Double Glass House", "floor": "Glass House Zone"},
	{"room_number": "China", "room_type": "Tent House", "floor": "Tent Zone"},
	{"room_number": "Japan", "room_type": "Tent House", "floor": "Tent Zone"},
	{"room_number": "Korea", "room_type": "Tent House", "floor": "Tent Zone"},
]


def _occupancy_split(max_occupancy):
	"""The sheet gives one "Max Allowed" headcount and no adult/child split.

	`max_adults` and `max_children` are advisory figures the CRM and POS display, so
	allow any mix up to the ceiling rather than inventing a split the property never
	quoted. `max_occupancy` stays the number that actually governs.
	"""
	return {"max_adults": max_occupancy, "max_children": max_occupancy}


def load_property():
	"""Create (or update in place) the room types and units. Safe to re-run."""
	if not frappe.db.exists("Hotel Reception", RECEPTION):
		frappe.get_doc(
			{"doctype": "Hotel Reception", "reception_name": RECEPTION}
		).insert(ignore_permissions=True)
		print(f"created Hotel Reception: {RECEPTION}")

	for spec in ROOM_TYPES:
		name = spec["room_type_name"]
		values = {
			**spec,
			**_occupancy_split(spec["max_occupancy"]),
			"extra_bed_adult_rate": EXTRA_BED_ADULT,
			"extra_bed_child_rate": EXTRA_BED_CHILD,
			"is_active": 1,
		}

		if frappe.db.exists("Hotel Room Type", name):
			doc = frappe.get_doc("Hotel Room Type", name)
			doc.update(values)
			doc.save(ignore_permissions=True)
			print(f"updated Hotel Room Type: {name}")
		else:
			frappe.get_doc(dict(doctype="Hotel Room Type", **values)).insert(
				ignore_permissions=True
			)
			print(f"created Hotel Room Type: {name} @ {spec['default_rate']}")

	for room in ROOMS:
		name = room["room_number"]
		values = {
			"room_type": room["room_type"],
			"floor": room["floor"],
			"hotel_reception": RECEPTION,
			"is_enabled": 1,
		}

		if frappe.db.exists("Hotel Room", name):
			doc = frappe.get_doc("Hotel Room", name)
			doc.update(values)
			doc.save(ignore_permissions=True)
			print(f"updated Hotel Room: {name}")
		else:
			frappe.get_doc({
				"doctype": "Hotel Room",
				"room_number": name,
				"status": "Available",
				**values,
			}).insert(ignore_permissions=True)
			print(f"created Hotel Room: {name} ({room['room_type']})")

	frappe.db.commit()
	print_inventory()


def print_inventory():
	print("\nInventory:")
	total = 0
	for rt in frappe.get_all(
		"Hotel Room Type",
		fields=["name", "bedroom_configuration", "max_occupancy", "default_rate", "weekend_rate"],
		order_by="name",
	):
		count = frappe.db.count("Hotel Room", {"room_type": rt.name})
		total += count
		print(
			f"  {rt.name:22} {rt.bedroom_configuration or '':20} "
			f"max {rt.max_occupancy:>2}  {rt.default_rate:>9,.0f} / {rt.weekend_rate:>9,.0f}  "
			f"{count} unit(s)"
		)
	print(f"  {'':22} {'':20} {'':>6} {'':>21}  {total} units total")


def reset_property():
	"""Delete every room and room type, then load the list above.

	Refuses to run if any room still has a reservation against it — clear the
	transactional data first (see `wipe_transactions`) or the delete would orphan folios.
	"""
	blocked = frappe.get_all(
		"Hotel Reservation", fields=["name", "room"], filters={"room": ["is", "set"]}, limit=5
	)
	if blocked:
		frappe.throw(
			"Rooms still have reservations against them "
			f"({', '.join(b.name for b in blocked)}). Clear those first."
		)

	for room in frappe.get_all("Hotel Room", pluck="name"):
		frappe.delete_doc("Hotel Room", room, ignore_permissions=True, force=True)
	for rt in frappe.get_all("Hotel Room Type", pluck="name"):
		frappe.delete_doc("Hotel Room Type", rt, ignore_permissions=True, force=True)

	frappe.db.commit()
	print("cleared existing rooms and room types")
	load_property()
