import frappe
from frappe import _
from frappe.utils import cint, getdate, flt, nowdate

from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import BLOCKED_STATUSES
from hospitality_core.hospitality_core.api import tariff
import json

@frappe.whitelist()
def get_pos_data(arrival, departure, arrival_time=None, departure_time=None):
    """Live room inventory for a date+time range, priced for the actual stay.

    Every room comes back in one of four states, because the desk acts differently on
    each: Available (sell it), Reserved (someone is booked or holding it — check them
    in when they arrive), Occupied (a guest is in house — check them out), Maintenance.
    Reserved used to be folded into Occupied, and a room held on a Tentative booking was
    not blocked at all, so a booking made in the CRM did not show up here.

    Blocking follows api.availability, the same rule the booking engine enforces.
    """
    from hospitality_core.hospitality_core.api import availability as av

    from hospitality_core.hospitality_core.api.stay_policy import get_stay_times

    check_in_time, check_out_time = get_stay_times()
    if getdate(departure) <= getdate(arrival):
        return {"rooms": [], "room_types": [], "held": {},
                "check_in_time": check_in_time, "check_out_time": check_out_time}

    # Rooms are allocated by night; times are the standard ones and do not matter.
    start, end = av._window(arrival, departure)

    rooms = frappe.get_all("Hotel Room",
        fields=["name", "room_type", "status", "is_enabled", "floor"],
        order_by="room_type asc, name asc"
    )

    # One catalog read gives capacity, tariff and amenities for every category.
    room_types = tariff.get_room_type_catalog()
    type_map = {rt["name"]: rt for rt in room_types}

    # Price each category once for this exact window rather than per room card.
    quote_map = {}
    for rt in room_types:
        try:
            quote_map[rt["name"]] = tariff.quote_stay(rt["name"], arrival, departure)
        except Exception:
            # A category with a broken tariff must not take the whole grid down.
            quote_map[rt["name"]] = None

    occupants = _occupants(av, start, end)
    held = av._soft_holds(start, end)

    pos_rooms = []
    for room in rooms:
        occupant = occupants.get(room.name)
        # Both blocking statuses collapse into one unsellable bucket here; the POS
        # only needs to know the room cannot be sold, not why.
        if not room.is_enabled or room.status in BLOCKED_STATUSES:
            status = "Maintenance"
        elif occupant:
            status = "Occupied" if occupant["status"] == "Checked In" else "Reserved"
        else:
            status = "Available"

        rt = type_map.get(room.room_type) or {}
        quote = quote_map.get(room.room_type)

        pos_rooms.append({
            "name": room.name,
            "room_type": room.room_type,
            "status": status,
            "occupant": occupant,
            "floor": room.floor,
            # `rate` stays the headline nightly figure the card shows; `stay_total` is
            # what the cart actually charges for these dates.
            "rate": flt(rt.get("default_rate")),
            "weekend_rate": flt(rt.get("weekend_rate")),
            "has_weekend_premium": bool(rt.get("has_weekend_premium")),
            "stay_total": flt(quote["total"]) if quote else 0.0,
            "average_nightly": flt(quote["average_nightly"]) if quote else 0.0,
            "nights_breakdown": quote["nights"] if quote else [],
            "max_occupancy": cint(rt.get("max_occupancy")),
            "bedroom_configuration": rt.get("bedroom_configuration"),
            "amenities": rt.get("amenities", []),
            "extra_bed_adult_rate": flt(rt.get("extra_bed_adult_rate")),
            "extra_bed_child_rate": flt(rt.get("extra_bed_child_rate")),
        })

    return {
        "rooms": pos_rooms,
        "room_types": room_types,
        # Rooms of a type promised on a booking without a room number yet. They do not
        # block a particular card, but selling past them oversells the category.
        "held": held,
        "today": nowdate(),
        "check_in_time": check_in_time,
        "check_out_time": check_out_time,
    }


def _occupants(av, start, end):
    """{room: who is in it or booked into it} for the window.

    A checked-in guest wins over a later arrival in the same window: the desk needs to
    see the person physically in the room first.
    """
    rows = av._overlapping_reservations(start, end)
    guests = {
        g.name: g
        for g in frappe.get_all(
            "Guest",
            filters={"name": ["in", list({r.guest for r in rows if r.guest}) or [""]]},
            fields=["name", "full_name", "mobile_no"],
        )
    }
    bookings = {
        r.name: r.hotel_booking
        for r in frappe.get_all(
            "Hotel Reservation",
            filters={"name": ["in", [r.name for r in rows] or [""]]},
            fields=["name", "hotel_booking"],
        )
    }

    today = getdate(nowdate())
    out = {}
    for r in rows:
        if not r.room:
            continue
        current = out.get(r.room)
        if current and current["status"] == "Checked In":
            continue
        g = guests.get(r.guest) or {}
        out[r.room] = {
            "reservation": r.name,
            "booking": bookings.get(r.name),
            "status": r.status,
            "guest": r.guest,
            "guest_name": g.get("full_name") or r.guest,
            "mobile_no": g.get("mobile_no"),
            "arrival_date": str(r.arrival_date),
            "departure_date": str(r.departure_date),
            "arrives_today": getdate(r.arrival_date) <= today and r.status != "Checked In",
            "departs_today": getdate(r.departure_date) <= today and r.status == "Checked In",
        }

    for h in av._room_holds(start, end):
        if h.room in out:
            continue
        out[h.room] = {
            "reservation": None,
            "booking": h.booking,
            "status": h.status,
            "guest": h.guest,
            "guest_name": h.guest_name or h.guest,
            "mobile_no": None,
            "arrival_date": str(h.arrival_date),
            "departure_date": str(h.departure_date),
            "arrives_today": getdate(h.arrival_date) <= today,
            "departs_today": False,
        }
    return out


def _split_party(room_count, adults, children):
    """Spread a party across rooms as evenly as the numbers allow.

    Four adults over two rooms is 2 and 2; five is 3 and 2. The remainder goes to the
    earlier rooms, which is what a front desk does by hand.
    """
    room_count = max(room_count, 1)
    split = []
    for i in range(room_count):
        split.append((
            adults // room_count + (1 if i < adults % room_count else 0),
            children // room_count + (1 if i < children % room_count else 0),
        ))
    return split


def plan_party(rooms, adults, children):
    """Work out how a party is distributed across the selected rooms.

    Over capacity is a sale, not an error: the overflow becomes extra beds at each
    category's rates. Returns one entry per room with its guests and its beds, plus the
    totals the desk needs to see.
    """
    if not rooms:
        frappe.throw(_("Select at least one room."))

    adults, children = cint(adults), cint(children)
    guests = adults + children

    capacities = []
    for room in rooms:
        room_type = frappe.db.get_value("Hotel Room", room, "room_type")
        capacities.append(cint(
            frappe.db.get_value("Hotel Room Type", room_type, "max_occupancy")
        ) or 1)

    total_capacity = sum(capacities)
    split = _split_party(len(rooms), adults, children)

    plan = []
    for room, capacity, (room_adults, room_children) in zip(rooms, capacities, split):
        bed_adults, bed_children = tariff.auto_extra_beds(
            capacity, room_adults, room_children, 1
        )
        plan.append({
            "room": room,
            "adults": room_adults,
            "children": room_children,
            "extra_beds_adult": bed_adults,
            "extra_beds_child": bed_children,
        })

    return {
        "rooms": plan,
        "guests": guests,
        "capacity": total_capacity,
        "over_capacity": max(guests - total_capacity, 0),
        "extra_beds": sum(
            p["extra_beds_adult"] + p["extra_beds_child"] for p in plan
        ),
    }


@frappe.whitelist()
def search_guests(query):
    """Quick guest search by name or phone."""
    if not query or len(query) < 2:
        return []
    return frappe.get_all("Guest",
        filters=[
            ["Guest", "full_name", "like", f"%{query}%"]
        ],
        or_filters=[
            ["Guest", "mobile_no", "like", f"%{query}%"]
        ],
        fields=["name", "full_name", "mobile_no", "email_id"],
        limit=10
    )

def _resolve_pos_guest(data):
    """The Guest for a POS booking: the one picked, an existing one with the same
    phone number, or a new one."""
    guest = data.get("guest")
    if not data.get("is_new_guest"):
        return guest

    gd = data.get("guest_details", {}) or {}

    # Reuse an existing Guest with this phone number instead of blindly inserting.
    # Without this, a guest who booked by phone gets a SECOND Guest record at the
    # desk, and their advance ends up stranded on the first one's folio.
    existing = find_guest_by_phone(gd.get("phone"))
    if existing:
        current = frappe.db.get_value(
            "Guest", existing, ["email_id", "address", "aadhaar_number", "pan_number"],
            as_dict=True,
        ) or {}
        # Fill in anything the desk collected that we did not already hold.
        updates = {}
        for field, value in (
            ("email_id", gd.get("email")),
            ("address", gd.get("address")),
            ("aadhaar_number", gd.get("aadhaar")),
            ("pan_number", gd.get("pan")),
        ):
            if value and not current.get(field):
                updates[field] = value
        if updates:
            frappe.db.set_value("Guest", existing, updates)
        return existing

    new_guest = frappe.get_doc({
        "doctype": "Guest",
        "full_name": gd.get("full_name"),
        "guest_type": gd.get("guest_type") or "Regular",
        "gender": gd.get("gender") or None,
        "mobile_no": gd.get("phone"),
        "email_id": gd.get("email"),
        "address": gd.get("address") or None,
        "nationality": gd.get("nationality") or "Indian",
        "aadhaar_number": gd.get("aadhaar") or None,
        "pan_number": gd.get("pan") or None,
        "special_requests": gd.get("special_requests") or None
    })
    new_guest.insert(ignore_permissions=True)
    return new_guest.name


def _stay_times(arrival_date_str=None, arrival_time_str=None, departure_time_str=None):
    """Arrival and departure times: always the property's standard ones.

    A walk-in arriving at 11 AM still holds the room from the standard check-in time,
    so a guest leaving that day is never a clash; checking in early is allowed anyway.
    The arguments are accepted for compatibility and ignored.
    """
    from hospitality_core.hospitality_core.api.stay_policy import get_stay_times

    return get_stay_times()


@frappe.whitelist()
def submit_pos_booking(payload):
    """Book rooms from the POS as a confirmed Hotel Booking.

    This used to create bare Hotel Reservations with no booking behind them, which left
    POS bookings outside everything the rest of the system keys on: they could not take
    an advance (a reservation's folio is Provisional until check-in), they did not
    appear with the CRM's bookings, and a POS discount was applied per room per night
    instead of off the total the cart showed. Going through Hotel Booking gives POS and
    CRM bookings one lifecycle.

    Optional in the payload:
      advance_amount / mode_of_payment / reference_no — money taken now;
      check_in_now — check the guest straight in (arrival must be today).
    """
    from hospitality_core.hospitality_core.api.advance import record_advance

    data = json.loads(payload) if isinstance(payload, str) else payload

    guest = _resolve_pos_guest(data)
    if not guest:
        frappe.throw(_("Guest is required to create a booking."))

    rooms = data.get("rooms", [])
    arrival_date_str = data.get("arrival")
    departure_date_str = data.get("departure")
    arrival_time_str, departure_time_str = _stay_times(
        arrival_date_str, data.get("arrival_time"), data.get("departure_time")
    )

    adults = cint(data.get("adults") or 1)
    children = cint(data.get("children") or 0)

    # The party is spread across the selected rooms so each reservation carries a
    # believable headcount, and anything over a room's capacity becomes extra beds
    # priced from its category.
    plan = plan_party(rooms, adults, children)

    # A rate typed at the desk applies to every room in this booking; the discount comes
    # off the booking total exactly as the cart showed it.
    rate_override = flt(data.get("rate_override")) or 0

    booking = frappe.get_doc({
        "doctype": "Hotel Booking",
        "guest": guest,
        "hotel_reception": frappe.db.get_value("Hotel Reception", filters={}),
        "booking_source": data.get("booking_source")
            or ("Walk-in" if frappe.db.exists("Hotel Enquiry Source", "Walk-in") else None),
        "arrival_date": arrival_date_str,
        "arrival_time": arrival_time_str,
        "departure_date": departure_date_str,
        "departure_time": departure_time_str,
        "adults": adults,
        "children": children,
        "status": "Draft",
        "discount_type": data.get("discount_type") or None,
        "discount_value": flt(data.get("discount_value")),
        "remarks": (data.get("remarks") or "").strip() or None,
        "special_requests": ((data.get("guest_details") or {}).get("special_requests") or None),
        "rooms": [
            {
                "room": entry["room"],
                "room_type": frappe.db.get_value("Hotel Room", entry["room"], "room_type"),
                "qty": 1,
                "adults": entry["adults"],
                "children": entry["children"],
                "extra_beds_adult": entry["extra_beds_adult"],
                "extra_beds_child": entry["extra_beds_child"],
                "rate": rate_override or 0,
                "is_rate_overridden": 1 if rate_override else 0,
            }
            for entry in plan["rooms"]
        ],
    })
    booking.insert(ignore_permissions=True)
    booking.confirm()
    booking.reload()

    advance = None
    if flt(data.get("advance_amount")) > 0:
        advance = record_advance(
            booking.name, flt(data.get("advance_amount")), data.get("mode_of_payment") or "Cash",
            reference_no=data.get("reference_no") or None,
        )

    checked_in = []
    if cint(data.get("check_in_now")):
        if getdate(arrival_date_str) > getdate(frappe.utils.nowdate()):
            frappe.throw(_("Only a stay arriving today can be checked in now."))
        result = checkin_arrival(booking=booking.name)
        checked_in = result.get("checked_in") or []

    booking.reload()
    return {
        "success": True,
        "booking": booking.name,
        "reservations": [line.reservation for line in booking.rooms if line.reservation],
        "guest": guest,
        "total_amount": booking.total_amount,
        "advance_received": booking.advance_received,
        "balance_due": booking.balance_due,
        "payment_entry": (advance or {}).get("payment_entry"),
        "checked_in": checked_in,
        "extra_beds": plan["extra_beds"],
        "over_capacity": plan["over_capacity"],
    }


# ---------------------------------------------------------------------------
# Arrivals: pulling a booking made earlier by the sales team.
#
# Until now this page could only ever create a NEW reservation. A guest who booked by
# phone and paid an advance could not be processed at all: their room showed as Occupied
# and was un-clickable, the guest lookup created a duplicate Guest record, and confirming
# threw "Room is already booked". These endpoints are the other half of the flow.
# ---------------------------------------------------------------------------

from hospitality_core.hospitality_core.api import advance as advance_api
from hospitality_core.hospitality_core.api import availability as availability_api
from hospitality_core.hospitality_core.api.telephony import match_key


@frappe.whitelist()
def get_arrivals(date=None, search=None, include_inhouse=0):
    """Bookings and reservations due to arrive.

    Anything still expected on or before `date` is included, so a guest who was due
    yesterday and turns up today is not invisible to the front desk.
    """
    date = date or frappe.utils.nowdate()
    params = {"date": date}
    # No Show is included so a prepaid guest who arrives a day late can still be found
    # and checked in here; checkin_arrival puts their room back in play.
    conditions = [
        "b.status IN ('Confirmed', 'Tentative', 'No Show')",
        "b.arrival_date <= %(date)s",
        # ...but only a recent one; older no-shows are a refund decision, not an arrival.
        "(b.status != 'No Show' OR b.arrival_date >= DATE_SUB(%(date)s, INTERVAL 3 DAY))",
    ]

    if search:
        key = match_key(search)
        if key:
            conditions.append("REPLACE(REPLACE(IFNULL(b.mobile_no,''),' ',''),'-','') LIKE %(like)s")
            params["like"] = f"%{key}%"
        else:
            conditions.append("(b.guest_name LIKE %(txt)s OR b.name LIKE %(txt)s)")
            params["txt"] = f"%{search}%"

    bookings = frappe.db.sql(
        """
        SELECT b.name, b.guest, b.guest_name, b.mobile_no, b.status,
               b.arrival_date, b.departure_date, b.nights,
               b.total_amount, b.advance_received, b.balance_due,
               b.booking_folio,
               (SELECT COUNT(*) FROM `tabHotel Booking Room` r WHERE r.parent = b.name) AS room_count
        FROM `tabHotel Booking` b
        WHERE {conditions}
        ORDER BY b.arrival_date ASC, b.name ASC
        LIMIT 100
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )

    # Walk-in reservations created directly on this page have no Hotel Booking parent,
    # so surface those too or the front desk would not find them here.
    res_conditions = ["r.status = 'Reserved'", "r.arrival_date <= %(date)s",
                      "IFNULL(r.hotel_booking, '') = ''"]
    res_params = {"date": date}
    if search:
        res_conditions.append("(g.full_name LIKE %(txt)s OR g.mobile_no LIKE %(txt)s OR r.name LIKE %(txt)s)")
        res_params["txt"] = f"%{search}%"

    loose = frappe.db.sql(
        """
        SELECT r.name, r.guest, g.full_name AS guest_name, g.mobile_no,
               r.status, r.arrival_date, r.departure_date, r.room, r.room_type, r.folio
        FROM `tabHotel Reservation` r
        LEFT JOIN `tabGuest` g ON g.name = r.guest
        WHERE {conditions}
        ORDER BY r.arrival_date ASC
        LIMIT 100
        """.format(conditions=" AND ".join(res_conditions)),
        res_params,
        as_dict=True,
    )

    return {"bookings": bookings, "reservations": loose, "date": date}


@frappe.whitelist()
def get_arrival_detail(booking=None, reservation=None):
    """Everything the POS needs to check one arrival in."""
    if booking:
        doc = frappe.get_doc("Hotel Booking", booking)
        rooms = []
        for line in doc.rooms:
            rooms.append({
                "idx": line.idx,
                "room_type": line.room_type,
                "room": line.room,
                "reservation": line.reservation,
                "rate": line.rate,
                "amount": line.amount,
                "reservation_status": frappe.db.get_value(
                    "Hotel Reservation", line.reservation, "status"
                ) if line.reservation else None,
            })

        # Free rooms per type, so unassigned lines can be given a room at the desk.
        options = {}
        for line in doc.rooms:
            if line.room or line.room_type in options:
                continue
            options[line.room_type] = availability_api.get_free_rooms(
                doc.arrival_date, doc.departure_date, room_type=line.room_type,
                ignore_booking=doc.name,
            )

        return {
            "type": "booking",
            "name": doc.name,
            "guest": doc.guest,
            "guest_name": doc.guest_name,
            "mobile_no": doc.mobile_no,
            "status": doc.status,
            "arrival_date": doc.arrival_date,
            "departure_date": doc.departure_date,
            "nights": doc.nights,
            "adults": doc.adults,
            "children": doc.children,
            "total_amount": doc.total_amount,
            "advance_received": doc.advance_received,
            "balance_due": doc.balance_due,
            "unapplied_advance": advance_api.get_advance_balance(doc.name),
            "special_requests": doc.special_requests,
            "rooms": rooms,
            "room_options": options,
        }

    if reservation:
        res = frappe.get_doc("Hotel Reservation", reservation)
        guest = frappe.db.get_value(
            "Guest", res.guest, ["full_name", "mobile_no"], as_dict=True
        ) or {}
        return {
            "type": "reservation",
            "name": res.name,
            "guest": res.guest,
            "guest_name": guest.get("full_name"),
            "mobile_no": guest.get("mobile_no"),
            "status": res.status,
            "arrival_date": res.arrival_date,
            "departure_date": res.departure_date,
            "unapplied_advance": 0,
            "rooms": [{
                "idx": 1, "room_type": res.room_type, "room": res.room,
                "reservation": res.name, "reservation_status": res.status,
            }],
            "room_options": {},
        }

    frappe.throw(_("Pass either a booking or a reservation."))


@frappe.whitelist()
def checkin_arrival(booking=None, reservation=None, room_assignments=None):
    """Check a pre-made arrival in, assigning rooms and applying any advance.

    `room_assignments` is {booking_room_idx: room_name} for lines that had no room.
    """
    if reservation and not booking:
        res = frappe.get_doc("Hotel Reservation", reservation)
        res.process_check_in()
        return {"checked_in": [res.name], "advance_applied": 0.0}

    doc = frappe.get_doc("Hotel Booking", booking)
    doc.check_permission("write")

    if doc.status in ("Cancelled", "Completed"):
        frappe.throw(_("Booking {0} is {1}.").format(doc.name, doc.status))

    assignments = room_assignments
    if isinstance(assignments, str):
        assignments = json.loads(assignments or "{}")
    assignments = assignments or {}

    for line in doc.rooms:
        chosen = assignments.get(str(line.idx)) or assignments.get(line.idx)
        if chosen and not line.room:
            line.room = chosen
    doc.save(ignore_permissions=True)
    doc.reload()

    # Tentative bookings arriving as walk-ins still need reservations created.
    if doc.status in ("Draft", "Tentative"):
        doc.confirm()
        doc.reload()
    else:
        doc.create_reservations()
        doc.reload()

    checked_in = []
    applied_total = 0.0

    for line in doc.rooms:
        if not line.reservation:
            continue
        res = frappe.get_doc("Hotel Reservation", line.reservation)
        if res.status == "Reserved":
            res.process_check_in()
            checked_in.append(res.name)
        elif res.status == "No Show":
            # The guest turned up late. Put them back in play rather than making the
            # desk rebuild the booking from scratch.
            res.db_set("status", "Reserved")
            res.reload()
            res.process_check_in()
            checked_in.append(res.name)

        # Spread the advance across the rooms as they check in.
        result = advance_api.apply_advance(doc.name, res.name)
        applied_total += flt(result.get("applied"))

    doc.db_set("status", "Checked In")

    return {
        "booking": doc.name,
        "checked_in": checked_in,
        "advance_applied": applied_total,
        "balance_due": doc.balance_due,
    }


def find_guest_by_phone(mobile_no):
    """Existing Guest with this number, matched on the last 10 digits."""
    key = match_key(mobile_no)
    if not key:
        return None
    rows = frappe.db.sql(
        """
        SELECT name FROM `tabGuest`
        WHERE RIGHT(REGEXP_REPLACE(IFNULL(mobile_no, ''), '[^0-9]', ''), 10) = %s
        ORDER BY modified DESC LIMIT 1
        """,
        (key,),
    )
    return rows[0][0] if rows else None
