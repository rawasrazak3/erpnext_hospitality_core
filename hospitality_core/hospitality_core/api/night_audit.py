import frappe
from frappe import _
from frappe.utils import add_days, cint, nowdate, getdate, flt

from hospitality_core.hospitality_core.api.folio import sync_folio_balance, mirror_to_company_folio, mirror_to_group_folio
from hospitality_core.hospitality_core.api.tariff import nightly_rate, _rates_for

# What the audit reads off each checked-in reservation. get_rate and
# get_extra_bed_charge take their inputs from this row, so a field missing here is a
# charge silently not billed: extra beds and agreed rates were left out, and only the
# check-in night (which uses the full document) billed them.
AUDIT_FIELDS = [
    "name", "guest", "room", "room_type", "rate_plan",
    "arrival_date", "departure_date", "company", "folio",
    "is_complimentary", "discount_type", "discount_value",
    "is_company_guest", "is_group_guest", "group_booking",
    "extra_beds_adult", "extra_beds_child", "agreed_rate", "is_rate_overridden",
    "remarks", "hotel_booking",
]


def run_daily_audit():
    """
    Scheduled Job: Runs at 2 PM daily.
    1. Auto-cancels no-show reservations (arrival passed, still Reserved).
    2. Posts Room Rent + Discounts for each checked-in stay whose booked nights
       include today. Stays past their departure are never extended or charged.
    4. SKIPS posting if a Room Rent charge already exists for the current date.
    """
    posting_date = nowdate()

    # Step 1: Cancel no-shows before anything else
    cancel_no_shows(posting_date)

    # Step 2: Fetch active reservations with Discount settings
    active_reservations = frappe.get_all("Hotel Reservation", 
        filters={"status": "Checked In"},
        fields=AUDIT_FIELDS,
    )

    count = 0
    for res in active_reservations:
        try:
            if process_single_reservation(res, posting_date):
                count += 1
        except Exception as e:
            # Truncate title to 140 characters to prevent CharacterLengthExceededError
            error_title = f"Night Audit Error: {res.name}"
            error_message = f"Night Audit Failure for Reservation {res.name}: {str(e)}"
            frappe.log_error(error_message, error_title)

    if count > 0:
        frappe.msgprint(_("Auto-Bill (2 PM): Posted charges for {0} rooms.").format(count))

def cancel_no_shows(posting_date):
    """
    Handles reservations where the arrival date has passed and the guest never checked in.

    A reservation with money against it is marked "No Show" and LEFT ALONE, because
    cancelling it would strand the guest's advance:

      * This used to force `status = "Cancelled"` with raw `db.set_value`, which skips
        `HotelReservation.process_cancel()` entirely — so the credit-rescue logic that
        writes a Guest Balance Ledger row and a REFUND-TRANSFER never ran. A prepaid
        guest who did not arrive lost the audit trail, and the money sat invisible on a
        cancelled folio with no way to refund it.
      * Unpaid reservations are still cancelled, but now through `process_cancel()` so
        every cancellation takes the same, tested path.

    A "No Show" is a commercial decision (cancellation policy, partial refund, date
    change), so it is deliberately left for a human rather than auto-resolved here.
    """
    no_shows = frappe.get_all("Hotel Reservation",
        filters={
            "status": ["in", ["Tentative", "Reserved"]],
            "arrival_date": ["<", posting_date]
        },
        fields=["name", "folio", "room", "guest", "arrival_date", "hotel_booking"]
    )

    cancelled_count = 0
    no_show_count = 0

    for res in no_shows:
        try:
            if _has_money_against_it(res):
                doc = frappe.get_doc("Hotel Reservation", res.name)
                doc.db_set("status", "No Show")
                if res.room:
                    from hospitality_core.hospitality_core.doctype.hotel_room.hotel_room import refresh_room_status
                    refresh_room_status(res.room)
                doc.add_comment("Info", _(
                    "Marked No Show (Night Audit): guest did not arrive on {0}. "
                    "An advance was received, so this reservation was NOT cancelled — "
                    "apply the cancellation policy and refund or transfer the balance."
                ).format(res.arrival_date))
                # Let the booking show "No Show" too, so its advance is not lost sight of
                # under a booking that still reads Confirmed.
                doc.sync_parent_booking()
                no_show_count += 1
                continue

            # No money involved: cancel through the real state machine.
            doc = frappe.get_doc("Hotel Reservation", res.name)
            doc.process_cancel()
            doc.add_comment("Info", _(
                "Auto-Cancelled (Night Audit): guest did not arrive. Arrival date was {0}."
            ).format(res.arrival_date))
            cancelled_count += 1

        except Exception as e:
            frappe.log_error(
                f"No-Show handling error for {res.name}: {str(e)}",
                f"Night Audit No-Show Error: {res.name}"
            )

    if cancelled_count:
        frappe.msgprint(_("Night Audit: Auto-cancelled {0} no-show reservation(s).").format(cancelled_count))
    if no_show_count:
        frappe.msgprint(_("Night Audit: {0} prepaid reservation(s) marked No Show for review.").format(no_show_count))


def _has_money_against_it(res):
    """True if cancelling this reservation would strand money."""
    if res.get("hotel_booking"):
        if flt(frappe.db.get_value("Hotel Booking", res.hotel_booking, "advance_received")) > 0.01:
            return True

    if not res.get("folio"):
        return False

    # Any non-void payment or credit already on the folio.
    total = frappe.db.sql("""
        SELECT SUM(amount) FROM `tabFolio Transaction`
        WHERE parent = %s AND is_void = 0
    """, (res.folio,))[0][0]
    return flt(total) < -0.01

def process_single_reservation(res, posting_date):
    """Post the room charges due on one in-house stay, up to posting_date.

    A stay is the nights arrival_date <= night < departure_date, so the departure date
    itself is never charged. A guest still marked Checked In after their departure
    (staff forgot to check them out) is NOT extended and NOT charged: the room is
    already free for the next guest, and only an explicit Extend adds nights. This used
    to call handle_overstay, which pushed the departure out a day and billed another
    night every afternoon, blocking the room for whoever had booked it next.
    """
    return bool(post_due_nights(res, posting_date))


def post_due_nights(res, upto=None):
    """Charge every booked night from the first one billed up to `upto` not yet billed.

    Usually that is just tonight. It also catches up nights the 2 PM audit could not
    have known about — a stay extended after the audit ran, or an overdue guest who is
    extended because they really stayed — so extending always bills the nights it adds.
    Nights before the first charge (before the guest checked in) are never billed.
    Returns the number of nights posted.
    """
    upto = getdate(upto or nowdate())
    departure = getdate(res.departure_date)
    last_night = min(upto, add_days(departure, -1))

    # A voided night counts as handled: someone waived it on purpose, and catching up
    # must not quietly charge it again.
    billed = {
        getdate(d) for d in frappe.db.sql_list(
            """SELECT DISTINCT posting_date FROM `tabFolio Transaction`
            WHERE parent=%s AND item IN %s""",
            (res.folio, tuple(get_room_rent_item_codes()) or ("ROOM-RENT",)),
        )
    }
    if not billed:
        # Not charged yet: check-in posts the first night. Until then post only a
        # night that is due today and inside the stay.
        start = getdate(res.get("arrival_date") or upto)
        if start > upto:
            return 0
        nights = [upto] if start <= upto <= last_night else []
    else:
        nights = []
        night = min(billed)
        while night <= last_night:
            if night not in billed:
                nights.append(night)
            night = getdate(add_days(night, 1))

    posted = 0
    for night in nights:
        if already_charged_today(res.folio, night, room=res.room):
            continue
        daily_rate = get_rate(res.rate_plan, res.room_type, night, reservation=res)
        daily_rate += get_extra_bed_charge(res, night)
        if daily_rate > 0:
            post_room_charge(res, daily_rate, night)
            posted += 1
    return posted

def already_charged_today(folio_name, date, room=None):
    filters = {
        "parent": folio_name,
        "posting_date": date,
        "is_void": 0,
        "item": ["in", get_room_rent_item_codes()] 
    }
    if room:
        # Crucial for Group Payer Folio which contains mirrored charges for many rooms
        filters["description"] = ["like", f"%{room}%"]
        
    return frappe.db.exists("Folio Transaction", filters)

def get_room_rent_item_codes():
    return frappe.db.sql_list("SELECT name FROM `tabItem` WHERE item_code='ROOM-RENT' OR item_group='Accommodation'")

def get_extra_bed_charge(res, date=None):
    """Nightly extra-bed charge for a reservation, or 0 if it has none.

    Extra beds are what a guest beyond the room's Max Allowed costs, and they are
    charged for every night of the stay alongside the room itself.
    """
    adults = cint(res.get("extra_beds_adult"))
    children = cint(res.get("extra_beds_child"))
    if not (adults or children):
        return 0.0

    beds = frappe.db.get_value(
        "Hotel Room Type", res.room_type,
        ["extra_bed_adult_rate", "extra_bed_child_rate"], as_dict=True,
    ) or {}
    return (adults * flt(beds.get("extra_bed_adult_rate"))) + (
        children * flt(beds.get("extra_bed_child_rate"))
    )


def get_rate(rate_plan, room_type, date, reservation=None):
    """The nightly tariff for one night of one reservation.

    Precedence, highest first:

      1. An agreed rate on the reservation. A sales agent negotiated it with the guest,
         so nothing downstream may quietly recompute it — this is what carries a price
         changed in the CRM all the way to the invoice.
      2. A Rate Plan, while it is in force.
      3. The room type's own tariff, weekday/weekend split.
    """
    agreed = _agreed_rate(reservation)
    if agreed is not None:
        return agreed

    if rate_plan:
        plan = frappe.get_doc("Room Rate Plan", rate_plan)
        if getdate(plan.valid_from) <= getdate(date) <= getdate(plan.valid_to):
            return plan.rate

    return nightly_rate(_rates_for(room_type), date)


def _agreed_rate(reservation):
    """The reservation's agreed nightly rate, or None when the tariff still applies.

    Accepts a reservation document, a dict, or a name, because the callers differ: the
    night audit holds a row from a SQL read, check-in holds the document itself.
    """
    if reservation is None:
        return None

    if isinstance(reservation, str):
        reservation = frappe.db.get_value(
            "Hotel Reservation", reservation,
            ["is_rate_overridden", "agreed_rate"], as_dict=True,
        ) or {}

    if not cint(reservation.get("is_rate_overridden")):
        return None

    rate = flt(reservation.get("agreed_rate"))
    # A zero agreed rate would mean a free stay; that is what `is_complimentary` is for,
    # so treat it as "not set" rather than silently billing nothing.
    return rate if rate > 0 else None

def post_room_charge(res, base_amount, date):
    """
    Posts Rent AND Discount transaction if applicable.
    Called by Night Audit AND Check-In process.
    Updates: Checks res.is_company_guest to force 'Company' billing and mirroring.
    """
    folio_name = res.folio
    if not folio_name:
        return
        
    ensure_item_exists("ROOM-RENT", "Room Rent")

    # Determine Bill To
    bill_to = "Guest"
    
    # 1. PRIORITY: Check if flagged as Company Guest
    if res.is_company_guest:
        bill_to = "Company"
    # 2. PRIORITY: Check if flagged as Group Guest
    elif res.get("is_group_guest") and res.get("group_booking"):
        bill_to = "Group"
    else:
        # 3. FALLBACK: Check Routing Instructions
        rent_item_group = frappe.db.get_value("Item", "ROOM-RENT", "item_group")
        routings = frappe.get_all("Reservation Routing", filters={"parent": res.name}, fields=["item_group", "bill_to"])
        for rule in routings:
            if rule.item_group == rent_item_group:
                bill_to = rule.bill_to
                break

    # 1. Post Base Charge
    txn = frappe.get_doc({
        "doctype": "Folio Transaction",
        "parent": folio_name,
        "parenttype": "Guest Folio",
        "parentfield": "transactions",
        "posting_date": date,
        "item": "ROOM-RENT", 
        # Remarks ride along on the description because that is the field the Sales
        # Invoice copies, so a note agreed at enquiry time reaches the guest's bill.
        "description": _room_charge_description(res),
        "qty": 1,
        "amount": base_amount,
        "bill_to": bill_to
    }).insert(ignore_permissions=True)

    # EXPLICIT MIRRORING
    if bill_to == "Company":
        mirror_to_company_folio(txn)
    elif bill_to == "Group":
        mirror_to_group_folio(txn)

    # 2. Calculate and Post Discount
    discount_amount = 0.0
    discount_desc = ""
    discount_item = "DISCOUNT"

    if res.get("is_complimentary"):
        discount_amount = base_amount
        discount_desc = "Complimentary Adjustment"
        discount_item = "COMPLIMENTARY"
    elif str(res.discount_type).strip() == "Percentage":
        pct = flt(res.discount_value)
        discount_amount = base_amount * (pct / 100.0)
        discount_desc = f"Room Discount ({pct}%)"
    elif str(res.discount_type).strip() == "Amount":
        discount_amount = flt(res.discount_value)
        discount_desc = "Room Discount (Fixed)"

    if discount_amount > 0:
        ensure_item_exists(discount_item, discount_desc)
        
        disc_txn = frappe.get_doc({
            "doctype": "Folio Transaction",
            "parent": folio_name,
            "parenttype": "Guest Folio",
            "parentfield": "transactions",
            "posting_date": date,
            "item": discount_item, 
            "description": discount_desc,
            "qty": 1,
            "amount": -1 * discount_amount, # Negative for credit/reduction
            "bill_to": bill_to
        }).insert(ignore_permissions=True)

        # EXPLICIT MIRRORING: Mirror discount if applicable
        if bill_to == "Company":
            mirror_to_company_folio(disc_txn)
        elif bill_to == "Group":
            mirror_to_group_folio(disc_txn)

    # Sync Balance
    sync_folio_balance(frappe.get_doc("Guest Folio", folio_name))

def _room_charge_description(res):
    """Folio line text for a room charge, including anything noted about the stay."""
    parts = [f"Room Charge - {res.room}"]

    beds = cint(res.get("extra_beds_adult")) + cint(res.get("extra_beds_child"))
    if beds:
        detail = []
        if cint(res.get("extra_beds_adult")):
            detail.append(f"{cint(res.extra_beds_adult)} adult")
        if cint(res.get("extra_beds_child")):
            detail.append(f"{cint(res.extra_beds_child)} child")
        parts.append("incl. {0} extra bed(s): {1}".format(beds, ", ".join(detail)))

    if res.get("remarks"):
        parts.append(str(res.remarks).strip())

    return " | ".join(parts)


def ensure_item_exists(code, name):
    if not frappe.db.exists("Item", code):
        item = frappe.new_doc("Item")
        item.item_code = code
        item.item_name = name
        item.item_group = "Services"
        item.is_stock_item = 0
        item.insert(ignore_permissions=True)