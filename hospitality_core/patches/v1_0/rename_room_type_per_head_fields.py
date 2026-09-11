"""Rename the room type per-head rate fields to match what they actually hold.

They were added as `extra_person_rate_*`, on the reading that the property's
"W/Head/Day" and "WE/Head/Day" columns were a surcharge for guests beyond the base
headcount. They are not: across all eight categories the column equals
`rate / max_occupancy` exactly, so it is the per-head unit price of the room, and a
guest beyond Max Allowed is charged through the extra-bed rates instead.

`rename_field` only works while the new column does not yet exist. A `bench migrate`
syncs the DocType JSON before running post-model-sync patches, so by the time this runs
the new column is usually already there and empty, with the old one still holding the
data. Handle both orders: rename when we can, otherwise copy across and drop the stale
column.
"""

import frappe
from frappe.model.utils.rename_field import rename_field

RENAMES = [
	("extra_person_rate_weekday", "per_head_rate_weekday"),
	("extra_person_rate_weekend", "per_head_rate_weekend"),
]


def execute():
	if not frappe.db.table_exists("Hotel Room Type"):
		return

	frappe.reload_doc("hospitality_core", "doctype", "hotel_room_type")

	for old, new in RENAMES:
		has_old = frappe.db.has_column("Hotel Room Type", old)
		has_new = frappe.db.has_column("Hotel Room Type", new)

		if not has_old:
			continue

		if not has_new:
			rename_field("Hotel Room Type", old, new)
			continue

		# Both columns exist: carry the values over where the new one is still empty,
		# then drop the old column so it cannot drift.
		frappe.db.sql(
			"""
			UPDATE `tabHotel Room Type`
			SET `{new}` = `{old}`
			WHERE IFNULL(`{new}`, 0) = 0 AND IFNULL(`{old}`, 0) != 0
			""".format(new=new, old=old)
		)
		frappe.db.sql_ddl(
			"ALTER TABLE `tabHotel Room Type` DROP COLUMN `{0}`".format(old)
		)

	# Derive anything still blank, so no category is quotable at zero per head.
	frappe.db.sql(
		"""
		UPDATE `tabHotel Room Type`
		SET per_head_rate_weekday = default_rate / max_occupancy
		WHERE IFNULL(per_head_rate_weekday, 0) = 0 AND IFNULL(max_occupancy, 0) > 0
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabHotel Room Type`
		SET per_head_rate_weekend = IFNULL(NULLIF(weekend_rate, 0), default_rate) / max_occupancy
		WHERE IFNULL(per_head_rate_weekend, 0) = 0 AND IFNULL(max_occupancy, 0) > 0
		"""
	)

	frappe.db.commit()
