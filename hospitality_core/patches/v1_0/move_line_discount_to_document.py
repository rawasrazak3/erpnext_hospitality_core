"""Move the discount and remarks from the room lines up onto the document.

They were added per line, but a discount is agreed once for a whole quote and a remark
is about the stay, not about one room type. Keeping them per line also made the booking
arithmetic ambiguous: two lines could each carry a fixed amount, and neither the folio
nor the invoice had a single figure to show the guest.

Any values already captured per line are folded up before the columns go:

  * A fixed Amount is summed — two lines at 500 each become 1,000 off the document.
  * A Percentage is carried up only when every discounted line agrees on it; otherwise
    it is converted to the equivalent amount, because one percentage cannot represent
    two different ones.
  * Remarks are joined, so nothing an agent typed is lost.

Frappe does not drop columns when fields are removed from a DocType, so this also
clears the stale ones rather than leaving them to drift.
"""

import frappe
from frappe.utils import flt

# (child doctype, parent doctype, parent's subtotal field, the line's amount field)
TABLES = [
	("Enquiry Room Line", "Hotel Enquiry", "quoted_subtotal", "amount"),
	("Hotel Booking Room", "Hotel Booking", "total_before_discount", "amount"),
]

OLD_COLUMNS = ["discount_type", "discount_value", "discount_amount", "remarks"]


def execute():
	for child, parent, subtotal_field, amount_field in TABLES:
		if not frappe.db.table_exists(child):
			continue

		frappe.reload_doc("hospitality_core", "doctype", frappe.scrub(child))
		frappe.reload_doc("hospitality_core", "doctype", frappe.scrub(parent))

		if frappe.db.has_column(child, "discount_type"):
			_lift(child, parent, subtotal_field, amount_field)

		for column in OLD_COLUMNS:
			if frappe.db.has_column(child, column):
				frappe.db.sql_ddl(
					"ALTER TABLE `tab{0}` DROP COLUMN `{1}`".format(child, column)
				)

	frappe.db.commit()


def _lift(child, parent, subtotal_field, amount_field):
	"""Fold each parent's line-level discounts and remarks into the parent itself."""
	rows = frappe.db.sql(
		"""
		SELECT parent, discount_type, discount_value, discount_amount,
		       remarks, `{amount}` AS amount
		FROM `tab{child}`
		WHERE IFNULL(discount_value, 0) != 0 OR IFNULL(remarks, '') != ''
		""".format(child=child, amount=amount_field),
		as_dict=True,
	)

	by_parent = {}
	for row in rows:
		by_parent.setdefault(row.parent, []).append(row)

	for name, lines in by_parent.items():
		if not frappe.db.exists(parent, name):
			continue

		discounted = [l for l in lines if flt(l.discount_value)]
		percentages = {
			flt(l.discount_value) for l in discounted
			if str(l.discount_type or "").strip() == "Percentage"
		}
		amounts = [l for l in discounted if str(l.discount_type or "").strip() == "Amount"]

		values = {}
		if discounted:
			if percentages and not amounts and len(percentages) == 1:
				# Every line agreed on the same percentage: it carries up as-is.
				values["discount_type"] = "Percentage"
				values["discount_value"] = percentages.pop()
			else:
				# Mixed or differing: the only faithful single figure is the total that
				# was actually being taken off.
				values["discount_type"] = "Amount"
				values["discount_value"] = sum(
					flt(l.discount_amount) or _line_discount(l) for l in discounted
				)

		notes = [str(l.remarks).strip() for l in lines if l.remarks]
		if notes:
			existing = frappe.db.get_value(parent, name, "remarks")
			values["remarks"] = " | ".join(([existing] if existing else []) + notes)

		if values:
			frappe.db.set_value(parent, name, values, update_modified=False)


def _line_discount(line):
	"""Recompute a line's discount when the stored amount is missing."""
	if str(line.discount_type or "").strip() == "Percentage":
		return flt(line.amount) * (min(flt(line.discount_value), 100.0) / 100.0)
	return flt(line.discount_value)
