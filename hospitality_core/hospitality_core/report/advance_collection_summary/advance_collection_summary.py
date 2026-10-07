# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""What the advances for a period add up to, and where they came from.

Advance Collection lists every receipt one per line, which answers "show me the
payments" but not "how much did we take this month, and in what". This is that second
question: the headline totals first, then one row per mode of payment, cashier, day,
booking source or property.

Keyed off the Payment Entry posting date — when the money arrived — so the total
reconciles against the day's banking rather than against arrival dates.

A receipt whose booking has since been deleted is still money the resort took, so it is
counted here and shown under "(booking deleted)" rather than dropped. Advance Collection
inner-joins the booking and silently loses those rows; a financial total that quietly
omits receipts is worse than one that shows an awkward label.
"""

import frappe
from frappe import _
from frappe.utils import flt, formatdate, getdate

# The groupings the summary offers, and how each renders. Keyed by the filter value so
# the SQL column can never come from user input directly.
#
#   filter value: (sql expression, column label, fieldtype, link options)
GROUP_BY = {
    "Mode of Payment": ("pe.mode_of_payment", "Mode of Payment", "Link", "Mode of Payment"),
    "Received By": ("pe.cashier", "Received By", "Link", "User"),
    "Date": ("pe.posting_date", "Date", "Date", None),
    "Booking Source": ("b.booking_source", "Booking Source", "Data", None),
    "Property": ("pe.hotel_reception", "Property", "Link", "Hotel Reception"),
}

DEFAULT_GROUP_BY = "Mode of Payment"


def execute(filters=None):
    filters = filters or {}
    group_by = filters.get("group_by") or DEFAULT_GROUP_BY
    if group_by not in GROUP_BY:
        group_by = DEFAULT_GROUP_BY

    rows = get_data(filters, group_by)
    columns = get_columns(group_by)
    return columns, rows, None, get_chart(rows, group_by), get_report_summary(filters)


def get_columns(group_by):
    expression, label, fieldtype, options = GROUP_BY[group_by]

    first = {"label": _(label), "fieldname": "group_value", "fieldtype": fieldtype, "width": 180}
    if options:
        first["options"] = options
    # A deleted booking leaves no link to follow, so the grouped-by-source column has to
    # be plain text rather than a Link that would 404.
    if group_by == "Booking Source":
        first["fieldtype"] = "Data"

    return [
        first,
        {"label": _("Receipts"), "fieldname": "receipts", "fieldtype": "Int", "width": 90},
        {"label": _("Bookings"), "fieldname": "bookings", "fieldtype": "Int", "width": 90},
        {"label": _("Advances Received"), "fieldname": "advances", "fieldtype": "Currency",
         "width": 160},
        {"label": _("Refunds Paid"), "fieldname": "refunds", "fieldtype": "Currency",
         "width": 130},
        {"label": _("Net Collected"), "fieldname": "net", "fieldtype": "Currency", "width": 150},
        {"label": _("Share"), "fieldname": "share", "fieldtype": "Percent", "width": 90},
    ]


def _where(filters):
    """The receipts in scope, as (sql conditions, params). Shared by both queries so the
    headline totals can never describe a different set of rows than the table does."""
    conditions = [
        "pe.docstatus = 1",
        "IFNULL(pe.hotel_booking, '') != ''",
        "pe.posting_date BETWEEN %(from_date)s AND %(to_date)s",
    ]
    params = {
        "from_date": filters.get("from_date"),
        "to_date": filters.get("to_date"),
    }

    if filters.get("hotel_reception"):
        conditions.append("pe.hotel_reception = %(reception)s")
        params["reception"] = filters.get("hotel_reception")
    if filters.get("mode_of_payment"):
        conditions.append("pe.mode_of_payment = %(mop)s")
        params["mop"] = filters.get("mode_of_payment")
    if filters.get("cashier"):
        conditions.append("pe.cashier = %(cashier)s")
        params["cashier"] = filters.get("cashier")

    return " AND ".join(conditions), params


def get_data(filters, group_by):
    expression = GROUP_BY[group_by][0]
    conditions, params = _where(filters)

    rows = frappe.db.sql(
        """
        SELECT {expression} AS group_value,
               COUNT(*) AS receipts,
               COUNT(DISTINCT pe.hotel_booking) AS bookings,
               SUM(CASE WHEN pe.payment_type = 'Pay' THEN 0 ELSE pe.paid_amount END) AS advances,
               SUM(CASE WHEN pe.payment_type = 'Pay' THEN pe.paid_amount ELSE 0 END) AS refunds
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabHotel Booking` b ON b.name = pe.hotel_booking
        WHERE {conditions}
        GROUP BY {expression}
        ORDER BY {order}
        """.format(
            expression=expression,
            conditions=conditions,
            # Days read in order; everything else reads biggest first, because the
            # question behind a grouped total is "where did most of it come from".
            order="group_value ASC" if group_by == "Date" else "advances DESC",
        ),
        params,
        as_dict=True,
    )

    total_net = sum(flt(r.advances) - flt(r.refunds) for r in rows)
    for r in rows:
        r.net = flt(r.advances) - flt(r.refunds)
        r.share = (r.net / total_net * 100.0) if total_net else 0.0
        if r.group_value in (None, ""):
            r.group_value = _("(booking deleted)") if group_by == "Booking Source" else _("(not set)")
        elif group_by == "Date":
            r.group_value = getdate(r.group_value)

    return rows


def get_report_summary(filters):
    """The headline the report exists to give: how much came in over the period.

    Queried ungrouped rather than by adding the table up. A booking that paid twice on
    different days is one booking, but it lands in two rows when the table is grouped by
    date, so summing the Bookings column would count it twice.
    """
    conditions, params = _where(filters)
    row = frappe.db.sql(
        """
        SELECT COUNT(*) AS receipts,
               COUNT(DISTINCT pe.hotel_booking) AS bookings,
               SUM(CASE WHEN pe.payment_type = 'Pay' THEN 0 ELSE pe.paid_amount END) AS advances,
               SUM(CASE WHEN pe.payment_type = 'Pay' THEN pe.paid_amount ELSE 0 END) AS refunds
        FROM `tabPayment Entry` pe
        LEFT JOIN `tabHotel Booking` b ON b.name = pe.hotel_booking
        WHERE {conditions}
        """.format(conditions=conditions),
        params,
        as_dict=True,
    )
    row = row[0] if row else None
    if not row or not row.receipts:
        return []

    advances = flt(row.advances)
    refunds = flt(row.refunds)
    receipts = int(row.receipts or 0)
    bookings = int(row.bookings or 0)

    summary = [
        {"label": _("Advances Received"), "value": advances, "datatype": "Currency",
         "indicator": "Green"},
        {"label": _("Refunds Paid"), "value": refunds, "datatype": "Currency",
         "indicator": "Red" if refunds else "Grey"},
        {"label": _("Net Collected"), "value": advances - refunds, "datatype": "Currency",
         "indicator": "Blue"},
        {"label": _("Receipts"), "value": receipts, "datatype": "Int"},
        {"label": _("Bookings"), "value": bookings, "datatype": "Int"},
    ]
    if receipts:
        summary.append({
            "label": _("Average Receipt"),
            "value": advances / receipts,
            "datatype": "Currency",
        })
    return summary


def get_chart(rows, group_by):
    if not rows:
        return None

    # A long tail of small groups makes the bars unreadable, so everything past the
    # tenth is folded into one bar rather than shrinking the nine that matter.
    top = rows[:10]
    labels = [_label(r.group_value) for r in top]
    values = [flt(r.net) for r in top]

    if len(rows) > 10:
        labels.append(_("Others"))
        values.append(sum(flt(r.net) for r in rows[10:]))

    return {
        "data": {
            "labels": labels,
            "datasets": [{"name": _("Net Collected"), "values": values}],
        },
        "type": "line" if group_by == "Date" else "bar",
        "fieldtype": "Currency",
        "colors": ["#2563eb"],
    }


def _label(value):
    return formatdate(value) if hasattr(value, "strftime") else str(value)
