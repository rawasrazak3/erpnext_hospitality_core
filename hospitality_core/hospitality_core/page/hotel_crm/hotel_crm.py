"""Backend for the Hotel CRM sales console (/app/hotel-crm).

The console is built for a phone sales team handling 200+ calls a day, so the queries
here are shaped around "what do I work on next" rather than generic list views: work
queues, one-call-per-row context, and a single save that returns the refreshed record.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime, nowdate

from hospitality_core.hospitality_core.api import availability, telephony

# Queues the left-hand list can show.
QUEUE_DUE = "due"
QUEUE_MINE = "mine"
QUEUE_ALL = "all"
QUEUE_CALLS = "calls"

OPEN_TYPES = ("Open", "Ongoing")


@frappe.whitelist()
def get_console_data():
    """Everything the console needs once at load: masters and queue counts."""
    statuses = frappe.get_all(
        "Hotel Enquiry Status",
        fields=["name", "status_name", "color", "position", "type"],
        order_by="position asc",
    )
    sources = frappe.get_all(
        "Hotel Enquiry Source", filters={"is_active": 1}, fields=["name"], order_by="name asc"
    )
    lost_reasons = frappe.get_all("Hotel Lost Reason", fields=["name"], order_by="name asc")
    room_types = frappe.get_all(
        "Hotel Room Type",
        fields=["name", "default_rate", "max_adults", "max_children"],
        order_by="name asc",
    )

    return {
        "statuses": statuses,
        "sources": [s.name for s in sources],
        "lost_reasons": [r.name for r in lost_reasons],
        "room_types": room_types,
        "counts": get_queue_counts(),
        "user": frappe.session.user,
    }


@frappe.whitelist()
def get_queue_counts():
    open_statuses = _open_status_names()
    if not open_statuses:
        return {"due": 0, "mine": 0, "all": 0, "calls": 0}

    due = frappe.db.count(
        "Hotel Enquiry",
        {"status": ["in", open_statuses], "next_follow_up": ["<=", now_datetime()]},
    )
    mine = frappe.db.count(
        "Hotel Enquiry", {"status": ["in", open_statuses], "enquiry_owner": frappe.session.user}
    )
    all_open = frappe.db.count("Hotel Enquiry", {"status": ["in", open_statuses]})
    calls = len(telephony.get_unlinked_calls(limit=200))

    return {"due": due, "mine": mine, "all": all_open, "calls": calls}


@frappe.whitelist()
def get_enquiries(queue=QUEUE_ALL, search=None, status=None, source=None, limit=60):
    """The work queue. `search` matches name or phone and ignores the queue filter,
    because a sales user searching mid-call wants the record wherever it sits."""
    if queue == QUEUE_CALLS and not search:
        return {"type": "calls", "rows": telephony.get_unlinked_calls(limit=limit)}

    filters = {}
    or_filters = None

    if search:
        key = telephony.match_key(search)
        if key:
            # Match the normalised key, not the raw field: a number stored as
            # "+91 98470 11111" never LIKE-matches the digits "9847011111".
            or_filters = [["mobile_key", "like", f"%{key}%"], ["alt_mobile_key", "like", f"%{key}%"]]
        else:
            or_filters = [["guest_name", "like", f"%{search}%"], ["name", "like", f"%{search}%"]]
    else:
        open_statuses = _open_status_names()
        if queue == QUEUE_DUE:
            filters["status"] = ["in", open_statuses]
            filters["next_follow_up"] = ["<=", now_datetime()]
        elif queue == QUEUE_MINE:
            filters["status"] = ["in", open_statuses]
            filters["enquiry_owner"] = frappe.session.user
        elif queue == QUEUE_ALL:
            filters["status"] = ["in", open_statuses]

    if status:
        filters["status"] = status
    if source:
        filters["source"] = source

    rows = frappe.get_all(
        "Hotel Enquiry",
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name", "guest_name", "mobile_no", "status", "status_type", "source",
            "enquiry_owner", "check_in_date", "check_out_date", "nights",
            "quoted_total", "next_follow_up", "last_contacted", "modified",
        ],
        order_by="COALESCE(next_follow_up, modified) asc" if queue == QUEUE_DUE else "modified desc",
        limit=cint(limit),
    )

    colors = {
        s.name: s.color
        for s in frappe.get_all("Hotel Enquiry Status", fields=["name", "color"])
    }
    for row in rows:
        row["status_color"] = colors.get(row.get("status"), "Gray")

    return {"type": "enquiries", "rows": rows}


@frappe.whitelist()
def get_enquiry(name):
    """One enquiry plus everything the centre and right panes render."""
    doc = frappe.get_doc("Hotel Enquiry", name)
    doc.check_permission("read")

    data = doc.as_dict()
    data["calls"] = telephony.get_calls_for_enquiry(name)
    data["status_color"] = frappe.db.get_value("Hotel Enquiry Status", doc.status, "color")
    return data


@frappe.whitelist()
def save_enquiry(payload):
    """Create or update an enquiry from the console.

    One round trip: the console sends the whole editable form and gets the saved record
    back, so the UI never has to guess what the server computed (nights, quoted total).
    """
    data = json.loads(payload) if isinstance(payload, str) else payload

    name = data.get("name")
    if name and frappe.db.exists("Hotel Enquiry", name):
        doc = frappe.get_doc("Hotel Enquiry", name)
    else:
        doc = frappe.new_doc("Hotel Enquiry")

    for field in (
        "guest_name", "mobile_no", "alt_mobile", "email", "city", "status", "source",
        "enquiry_owner", "hotel_reception", "check_in_date", "check_out_date",
        "adults", "children", "flexible_dates", "budget", "next_follow_up",
        "lost_reason", "lost_notes", "notes",
    ):
        if field in data:
            doc.set(field, data.get(field) or None)

    if "room_lines" in data:
        doc.set("room_lines", [])
        for line in data.get("room_lines") or []:
            if not line.get("room_type"):
                continue
            doc.append("room_lines", {
                "room_type": line.get("room_type"),
                "qty": cint(line.get("qty")) or 1,
                "adults": cint(line.get("adults")),
                "children": cint(line.get("children")),
                "rate_quoted": flt(line.get("rate_quoted")),
            })

    doc.save()

    # A call the user was working from becomes attached to the enquiry they just created.
    call_log = data.get("link_call_log")
    if call_log and frappe.db.exists("CRM Call Log", call_log):
        frappe.db.set_value("CRM Call Log", call_log, "custom_hotel_enquiry", doc.name,
                            update_modified=False)

    return get_enquiry(doc.name)


@frappe.whitelist()
def set_status(enquiry, status, lost_reason=None, lost_notes=None):
    """Move an enquiry along the pipeline — used by the board's drag-and-drop."""
    doc = frappe.get_doc("Hotel Enquiry", enquiry)
    doc.status = status
    if lost_reason:
        doc.lost_reason = lost_reason
    if lost_notes:
        doc.lost_notes = lost_notes
    doc.save()
    return {"name": doc.name, "status": doc.status, "status_type": doc.status_type}


# Which date a board filter means. "Enquired" is when the lead came in, which is what
# "who enquired this week" asks; "staying" is when they want the room, which is what
# "who is arriving next month" asks. They answer different questions, so both are offered.
BOARD_DATE_FIELDS = {"enquired": "creation", "staying": "check_in_date"}


@frappe.whitelist()
def get_board(date_field=None, from_date=None, to_date=None, room_type=None):
    """Enquiries grouped by status for the Kanban view.

    Cards carry the requested rooms and the guest's stated budget, because a pipeline
    that shows only a name is a list of strangers: the agent working it needs to see
    who is asking for four cottages at a high budget before deciding who to call first.

    `room_type` narrows the board to enquiries asking for that type, and the returned
    `room_demand` counts every type across the date range whatever the narrowing is —
    that breakdown is the answer to "how much is this room being asked for in these
    dates", and it has to stay visible while one type is selected or the filter would
    hide the comparison that makes it useful.
    """
    statuses = frappe.get_all(
        "Hotel Enquiry Status",
        fields=["name", "color", "position", "type"],
        order_by="position asc",
    )

    filters = {"status": ["in", [s.name for s in statuses]]}

    column = BOARD_DATE_FIELDS.get(date_field or "enquired", "creation")
    if from_date and to_date:
        # Whole-day inclusive on both ends: `creation` is a datetime, so a plain
        # "<= to_date" would silently drop everything that came in after midnight
        # on the last day of the range.
        filters[column] = ["between", [from_date, to_date]]
    elif from_date:
        filters[column] = [">=", from_date]
    elif to_date:
        filters[column] = ["<=", to_date]

    rows = frappe.get_all(
        "Hotel Enquiry",
        filters=filters,
        fields=[
            "name", "guest_name", "mobile_no", "status", "source", "enquiry_owner",
            "check_in_date", "check_out_date", "nights", "quoted_total", "budget",
            "next_follow_up", "creation", "adults", "children",
        ],
        order_by="modified desc",
        limit=500,
    )

    _attach_room_requests(rows)

    # Demand is measured before the room filter, so the chips keep showing every type.
    room_demand = _summarise_demand(rows)

    if room_type:
        rows = [r for r in rows if any(x["room_type"] == room_type for x in r["rooms"])]

    grouped = {s.name: [] for s in statuses}
    for row in rows:
        grouped.setdefault(row.status, []).append(row)

    return {
        "statuses": statuses,
        "grouped": grouped,
        "total": len(rows),
        "date_field": date_field or "enquired",
        "room_type": room_type or None,
        "room_demand": room_demand,
    }


def _summarise_demand(rows):
    """Enquiries and rooms wanted per room type, for the date range on screen.

    `enquiries` is how many guests asked; `qty` is how many rooms they asked for
    between them. They differ whenever anyone wants more than one room, and the
    second is the number that matters against inventory.
    """
    demand = {}
    for row in rows:
        for line in row.get("rooms") or []:
            bucket = demand.setdefault(line["room_type"], {"enquiries": 0, "qty": 0})
            bucket["qty"] += line["qty"]
        # Count each enquiry once per type however many lines it has for it.
        for rt in {line["room_type"] for line in (row.get("rooms") or [])}:
            demand[rt]["enquiries"] += 1

    return [
        {"room_type": rt, "enquiries": v["enquiries"], "qty": v["qty"]}
        for rt, v in sorted(demand.items(), key=lambda kv: (-kv[1]["qty"], kv[0]))
    ]


def _attach_room_requests(rows):
    """Summarise each enquiry's requested rooms in one query rather than per card.

    500 cards would otherwise be 500 child-table reads on every board load.
    """
    if not rows:
        return

    lines = frappe.get_all(
        "Enquiry Room Line",
        filters={"parent": ["in", [r.name for r in rows]], "parenttype": "Hotel Enquiry"},
        fields=["parent", "room_type", "qty"],
        order_by="idx asc",
    )

    by_parent = {}
    for line in lines:
        if not line.room_type:
            continue
        by_parent.setdefault(line.parent, []).append(
            {"room_type": line.room_type, "qty": cint(line.qty) or 1}
        )

    for row in rows:
        requested = by_parent.get(row.name, [])
        row["rooms"] = requested
        row["rooms_total"] = sum(r["qty"] for r in requested)


def _open_status_names():
    return frappe.get_all(
        "Hotel Enquiry Status", filters={"type": ["in", OPEN_TYPES]}, pluck="name"
    )


# ---------------------------------------------------------------------- conversion
@frappe.whitelist()
def get_stay_availability(arrival_date, departure_date, exclude_enquiry=None):
    """Live availability for the dates a guest is asking about.

    This is what lets an agent answer "do you have two cottages next weekend" without
    leaving the call. Goes through the canonical availability engine so the answer is the
    same one the POS and the tape chart would give.

    On top of the hard numbers it reports *competing demand*: other open enquiries that
    want an overlapping stay. Those are not holds and deliberately do not reduce `free` —
    an enquiry is interest, not inventory. But an agent quoting the last cottage needs to
    know two colleagues are quoting the same one to different guests, which is exactly the
    double-sell the room-request section existed to prevent and could not see.
    """
    if not (arrival_date and departure_date):
        return None
    try:
        data = availability.get_availability(arrival_date, departure_date)
        data["contention"] = _competing_enquiries(arrival_date, departure_date, exclude_enquiry)
        return data
    except Exception as e:
        return {"error": str(e)}


def _competing_enquiries(arrival_date, departure_date, exclude_enquiry=None):
    """Open enquiries whose requested stay overlaps this window, by room type.

    Overlap is the standard half-open rule the availability engine uses: a stay ending on
    the day another begins is not a clash, because the room turns over that morning.
    """
    open_statuses = _open_status_names()
    if not open_statuses:
        return {"by_type": {}, "total": 0, "enquiries": []}

    rows = frappe.db.sql(
        """
        SELECT e.name, e.guest_name, e.enquiry_owner, e.status,
               e.check_in_date, e.check_out_date,
               rl.room_type, rl.qty
        FROM `tabHotel Enquiry` e
        LEFT JOIN `tabEnquiry Room Line` rl
               ON rl.parent = e.name AND rl.parenttype = 'Hotel Enquiry'
        WHERE e.status IN %(statuses)s
          AND e.check_in_date IS NOT NULL AND e.check_out_date IS NOT NULL
          AND e.check_in_date < %(departure)s
          AND e.check_out_date > %(arrival)s
          AND (%(exclude)s IS NULL OR e.name != %(exclude)s)
        ORDER BY e.modified DESC
        """,
        {
            "statuses": tuple(open_statuses),
            "arrival": arrival_date,
            "departure": departure_date,
            "exclude": exclude_enquiry,
        },
        as_dict=True,
    )

    by_type = {}
    seen = {}
    for row in rows:
        if row.room_type:
            bucket = by_type.setdefault(row.room_type, {"qty": 0, "enquiries": 0})
            bucket["qty"] += cint(row.qty) or 1
            bucket["enquiries"] += 1
        # One entry per enquiry for the tooltip, however many room lines it carries.
        if row.name not in seen:
            seen[row.name] = {
                "name": row.name,
                "guest_name": row.guest_name,
                "owner": row.enquiry_owner,
                "status": row.status,
                "check_in_date": str(row.check_in_date) if row.check_in_date else None,
                "check_out_date": str(row.check_out_date) if row.check_out_date else None,
                "mine": row.enquiry_owner == frappe.session.user,
            }

    return {"by_type": by_type, "total": len(seen), "enquiries": list(seen.values())[:12]}


def get_or_create_guest(enquiry):
    """Find the Guest behind an enquiry by phone, or create one.

    Matching on the normalised number rather than the name avoids the duplicate-guest
    problem the POS has, where every walk-in insert created a fresh Guest record.
    """
    if enquiry.guest and frappe.db.exists("Guest", enquiry.guest):
        return enquiry.guest

    key = telephony.match_key(enquiry.mobile_no)
    if key:
        existing = frappe.db.sql(
            """
            SELECT name FROM `tabGuest`
            WHERE RIGHT(REGEXP_REPLACE(IFNULL(mobile_no, ''), '[^0-9]', ''), 10) = %s
            ORDER BY modified DESC LIMIT 1
            """,
            (key,),
        )
        if existing:
            return existing[0][0]

    guest = frappe.get_doc({
        "doctype": "Guest",
        "full_name": enquiry.guest_name,
        "mobile_no": enquiry.mobile_no,
        "email_id": enquiry.email,
        "guest_type": "Regular",
    })
    guest.insert(ignore_permissions=True)
    return guest.name


@frappe.whitelist()
def create_booking_from_enquiry(enquiry, action="hold", hold_hours=24):
    """Turn an enquiry into a Hotel Booking.

    `action` is "hold" (Tentative, blocks inventory but assigns no rooms) or "confirm"
    (assigns rooms and creates reservations).
    """
    doc = frappe.get_doc("Hotel Enquiry", enquiry)
    doc.check_permission("write")

    if doc.hotel_booking and frappe.db.exists("Hotel Booking", doc.hotel_booking):
        return {"booking": doc.hotel_booking, "created": False}

    if not (doc.check_in_date and doc.check_out_date):
        frappe.throw(_("Set check-in and check-out dates before creating a booking."))
    if not doc.room_lines:
        frappe.throw(_("Add at least one room to the enquiry before creating a booking."))

    guest = get_or_create_guest(doc)

    booking = frappe.get_doc({
        "doctype": "Hotel Booking",
        "guest": guest,
        "enquiry": doc.name,
        "hotel_reception": doc.hotel_reception,
        "booking_source": doc.source,
        "arrival_date": doc.check_in_date,
        "departure_date": doc.check_out_date,
        "adults": doc.adults,
        "children": doc.children,
        "status": "Draft",
        "rooms": [
            {
                "room_type": line.room_type,
                "qty": line.qty,
                "adults": line.adults,
                "children": line.children,
                "rate": line.rate_quoted,
            }
            for line in doc.room_lines
        ],
    })
    booking.insert(ignore_permissions=True)

    if action == "confirm":
        booking.confirm()
    else:
        booking.set_tentative(hold_hours)

    booking.reload()
    frappe.db.set_value("Hotel Enquiry", doc.name, {"hotel_booking": booking.name, "guest": guest})

    return {
        "booking": booking.name,
        "created": True,
        "status": booking.status,
        "total_amount": booking.total_amount,
        "guest": guest,
    }


@frappe.whitelist()
def get_booking(booking):
    """Booking summary for the console's booking panel."""
    doc = frappe.get_doc("Hotel Booking", booking)
    doc.check_permission("read")
    from hospitality_core.hospitality_core.api.advance import get_advance_balance

    data = doc.as_dict()
    data["unapplied_advance"] = get_advance_balance(booking)
    return data
