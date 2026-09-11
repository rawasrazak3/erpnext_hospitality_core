# Copyright (c) 2026, FRC Consulting and contributors
# For license information, please see license.txt

"""Day-by-day room availability forecast.

Reads through `api.availability`, the same engine the CRM console, the POS and the
booking confirmation use. It previously ran its own SQL that counted only
Reserved/Checked In reservations, so it ignored tentative holds and any reservation in
the Tentative state — meaning the front desk could sell a room the sales team was
holding, and this report would disagree with the availability the agent had just quoted.
"""

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

from hospitality_core.hospitality_core.api import availability


def execute(filters=None):
    filters = filters or {}
    return get_columns(), get_data(filters)


def get_columns():
    return [
        {"label": _("Date"), "fieldname": "date", "fieldtype": "Date", "width": 110},
        {"label": _("Room Type"), "fieldname": "room_type", "fieldtype": "Link",
         "options": "Hotel Room Type", "width": 150},
        {"label": _("Total Rooms"), "fieldname": "total_rooms", "fieldtype": "Int", "width": 100},
        {"label": _("Blocked"), "fieldname": "ooo", "fieldtype": "Int", "width": 110,
         "description": _("Rooms held off inventory by status — Maintenance or Out of Order")},
        {"label": _("Occupied / Sold"), "fieldname": "sold", "fieldtype": "Int", "width": 120,
         "description": _("Rooms with a reservation covering this night")},
        {"label": _("Held"), "fieldname": "held", "fieldtype": "Int", "width": 90,
         "description": _("Tentative holds with no room assigned yet — capacity is committed")},
        {"label": _("Available"), "fieldname": "available", "fieldtype": "Int", "width": 100},
        {"label": _("Occupancy %"), "fieldname": "occupancy_pct", "fieldtype": "Percent",
         "width": 110},
    ]


def get_data(filters):
    start = getdate(filters.get("from_date"))
    end = getdate(filters.get("to_date"))
    if not (start and end) or end < start:
        return []

    # A runaway range would mean one availability pass per day; keep it sane.
    if (end - start).days > 180:
        frappe.throw(_("Please choose a range of 180 days or less."))

    room_type = filters.get("room_type")
    reception = filters.get("hotel_reception")
    data = []

    current = start
    while current <= end:
        night = str(current)
        # One night: arrive this date, depart the next.
        snapshot = availability.get_availability(
            night, add_days(night, 1), room_type=room_type, include_soft_holds=True
        )

        # The engine reports per room type across the property; narrow to one reception
        # by counting only its rooms when that filter is set.
        reception_rooms = None
        if reception:
            reception_rooms = {
                r["room_type"]
                for r in snapshot["rooms"]
                if r.get("hotel_reception") == reception
            }

        for bucket in snapshot["room_types"]:
            if reception_rooms is not None and bucket["room_type"] not in reception_rooms:
                continue

            total = bucket["total"]
            ooo = bucket["out_of_order"]
            sold = bucket["occupied"]
            held = bucket["held"]

            net_inventory = total - ooo
            committed = sold + held
            occupancy = (committed / net_inventory * 100.0) if net_inventory > 0 else 0.0

            data.append({
                "date": night,
                "room_type": bucket["room_type"],
                "total_rooms": total,
                "ooo": ooo,
                "sold": sold,
                "held": held,
                "available": bucket["free"],
                "occupancy_pct": flt(occupancy, 1),
            })

        current = add_days(current, 1)

    return data
