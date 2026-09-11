import frappe
from frappe import _
from frappe.utils import add_days, cint, nowdate, getdate, flt

from hospitality_core.hospitality_core.api.folio import sync_folio_balance, mirror_to_company_folio, mirror_to_group_folio
from hospitality_core.hospitality_core.api.tariff import nightly_rate, _rates_for

def run_daily_audit():
    """
    Scheduled Job: Runs at 2 PM daily.
    1. Auto-cancels no-show reservations (arrival passed, still Reserved).
    2. Checks for Overstays and extends departure date for ALL checked-in rooms.
    3. Posts Room Rent + Discounts for all rooms currently Checked In.
    4. SKIPS posting if a Room Rent charge already exists for the current date.
    """
    posting_date = nowdate()

    # Step 1: Cancel no-shows before anything else
    cancel_no_shows(posting_date)

    # Step 2: Fetch active reservations with Discount settings
    active_reservations = frappe.get_all("Hotel Reservation", 
        filters={"status": "Checked In"},
        fields=[
            "name", "guest", "room", "room_type", "rate_plan", 
            "departure_date", "company", "folio",
            "is_complimentary", "discount_type", "discount_value",
            "is_company_guest", "is_group_guest", "group_booking"
        ]
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
                    frappe.db.set_value("Hotel Room", res.room, "status", "Available")
                doc.add_comment("Info", _(
                    "Marked No Show (Night Audit): guest did not arrive on {0}. "
                    "An advance was received, so this reservation was NOT cancelled — "
                    "apply the cancellation policy and refund or transfer the balance."
                ).format(res.arrival_date))
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
    # Step A: Handle overstay FIRST — regardless of whether we will bill today.
    # This ensures departure dates are always extended for ALL checked-in rooms
    # even if billing was already done (e.g. via check-in billing at 8 AM).
    # If today is their departure date (or past it) and they are still Checked In, they overstayed.
    if getdate(res.departure_date) <= getdate(posting_date):
        handle_overstay(res)

    # Step B: Skip billing if already charged today to avoid duplicates
    if already_charged_today(res.folio, posting_date, room=res.room):
        return False

    # Step C: Get Base Rate and post room charge
    daily_rate = get_rate(res.rate_plan, res.room_type, posting_date)
    daily_rate += get_extra_bed_charge(res, posting_date)

    if daily_rate > 0:
        post_room_charge(res, daily_rate, posting_date)
        return True
        
    return False

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

def handle_overstay(res):
    """Extend a guest who is still in-house past their departure date.

    The extension bypasses validation by design (the guest is physically in the room),
    but that means it can silently overlap an incoming reservation for the same room.
    Check first and flag the clash for the front desk rather than creating a double
    booking nobody notices until the next guest is standing at the counter.
    """
    from hospitality_core.hospitality_core.api.availability import is_room_free

    new_departure = add_days(nowdate(), 1)

    clash = is_room_free(
        res.room, nowdate(), new_departure, ignore_reservation=res.name
    )

    frappe.db.set_value("Hotel Reservation", res.name, {
        "departure_date": new_departure,
        "departure_time": "12:00:00",
        "_user_tags": "Overstay"
    })

    doc = frappe.get_doc("Hotel Reservation", res.name)
    if clash.get("free"):
        doc.add_comment("Info", _("Auto-Extended: Guest still in-house at 2 PM."))
    else:
        doc.add_comment("Info", _(
            "Auto-Extended: guest still in-house at 2 PM, but room {0} is also booked — "
            "{1}. Move one of the two."
        ).format(res.room, clash.get("reason")))
        frappe.log_error(
            f"Overstay on {res.name} clashes with {clash.get('reservation')} in room {res.room}",
            "Night Audit overstay clash",
        )

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


def get_rate(rate_plan, room_type, date):
    """The nightly tariff for one night of one reservation.

    A Rate Plan is a negotiated override and wins outright while it is in force. With no
    plan (or outside its validity window) the room type's own tariff applies, and that
    tariff is weekday/weekend split — the property charges more Friday through Sunday.
    """
    if rate_plan:
        plan = frappe.get_doc("Room Rate Plan", rate_plan)
        if getdate(plan.valid_from) <= getdate(date) <= getdate(plan.valid_to):
            return plan.rate

    return nightly_rate(_rates_for(room_type), date)

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
        "description": f"Room Charge - {res.room}",
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

def ensure_item_exists(code, name):
    if not frappe.db.exists("Item", code):
        item = frappe.new_doc("Item")
        item.item_code = code
        item.item_name = name
        item.item_group = "Services"
        item.is_stock_item = 0
        item.insert(ignore_permissions=True)