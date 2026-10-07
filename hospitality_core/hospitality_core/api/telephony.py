"""Bridge between CRM Call Log (fed by the Android sync app) and Hotel Enquiry.

The Android handsets post call history to `CRM Call Log` via `crm_mobile_sync.api`.
That app resolves a number to a CRM Lead or CRM Deal and never creates anything; it has
no knowledge of the hotel side. This module adds the hotel half: an incoming call log is
matched to a Hotel Enquiry by phone number, and a sales user can turn an unmatched call
into an enquiry in one action.

Nothing here changes crm_mobile_sync or the Android app.
"""

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

# India: compare the last 10 digits, which survives +91 / 0 / spacing differences
# between what the handset reports and what a sales user types. Change to 8 for GCC.
MATCH_DIGITS = 10

# Statuses CRM Call Log uses for a call that never connected. ingest_calls maps Android's
# MISSED/REJECTED/BLOCKED to "No Answer", and also rewrites a "Completed" call of zero
# seconds to "No Answer", so this one value covers every unanswered case the app produces.
# Lives here rather than in a report because the reports and the Call History console all
# have to agree on what "unanswered" means.
UNANSWERED_STATUSES = ("No Answer", "Missed", "Busy", "Failed")


def match_key(number):
    """Reduce a phone number to the digits used for matching, or '' if unusable."""
    if not number:
        return ""
    digits = "".join(ch for ch in str(number) if ch.isdigit())
    return digits[-MATCH_DIGITS:] if len(digits) >= 6 else ""


def find_enquiry_by_number(number):
    """Most recently touched open enquiry for this number, else the most recent one."""
    key = match_key(number)
    if not key:
        return None

    rows = frappe.db.sql(
        """
        SELECT he.name, hes.type AS status_type
        FROM `tabHotel Enquiry` he
        LEFT JOIN `tabHotel Enquiry Status` hes ON hes.name = he.status
        WHERE he.mobile_key = %(key)s OR he.alt_mobile_key = %(key)s
        ORDER BY (hes.type IN ('Open', 'Ongoing')) DESC, he.modified DESC
        LIMIT 1
        """,
        {"key": key},
        as_dict=True,
    )
    return rows[0].name if rows else None


def link_call_to_enquiry(doc, method=None):
    """doc_events hook: CRM Call Log after_insert.

    Stamps the matching Hotel Enquiry on the call log and refreshes that enquiry's
    last-contacted time. Deliberately best-effort — a telephony failure must never stop
    a call log from being recorded, since the handset treats an error as a retry.
    """
    if not frappe.get_meta("CRM Call Log").has_field("custom_hotel_enquiry"):
        return
    if doc.get("custom_hotel_enquiry"):
        return

    try:
        # An outgoing call is to the guest; an incoming call is from them.
        number = doc.get("to") if doc.get("type") == "Outgoing" else doc.get("from")
        key = match_key(number)

        if key and frappe.get_meta("CRM Call Log").has_field("custom_number_key"):
            doc.db_set("custom_number_key", key, update_modified=False)

        enquiry = find_enquiry_by_number(number)
        if not enquiry:
            return

        doc.db_set("custom_hotel_enquiry", enquiry, update_modified=False)
        frappe.db.set_value(
            "Hotel Enquiry", enquiry, "last_contacted", doc.get("start_time") or now_datetime(),
            update_modified=False,
        )
        if not frappe.db.get_value("Hotel Enquiry", enquiry, "first_call_log"):
            frappe.db.set_value("Hotel Enquiry", enquiry, "first_call_log", doc.name,
                                update_modified=False)
    except Exception:
        frappe.log_error(
            f"Could not link call log {doc.name} to a Hotel Enquiry",
            "Hotel CRM telephony link",
        )


def count_unlinked_calls(cap=99):
    """How many unattended calls are waiting, counted rather than measured.

    `len(get_unlinked_calls(...))` pins at whatever limit was passed, so a badge fed
    that way reads "200" forever once the queue is busy. Counting is capped instead,
    and the caller renders the cap as "99+" — the exact size of a backlog nobody is
    going to clear today is not information worth a full table scan.
    """
    rows = frappe.db.sql(
        """
        SELECT COUNT(*) FROM (
            SELECT 1
            FROM `tabCRM Call Log` cl
            WHERE (cl.custom_hotel_enquiry IS NULL OR cl.custom_hotel_enquiry = '')
              AND IFNULL(cl.custom_number_key, '') != ''
              AND NOT EXISTS (
                    SELECT 1 FROM `tabHotel Enquiry` he
                    WHERE he.mobile_key = cl.custom_number_key
                       OR he.alt_mobile_key = cl.custom_number_key
              )
            LIMIT %(cap)s
        ) capped
        """,
        {"cap": int(cap)},
    )
    return rows[0][0] if rows else 0


@frappe.whitelist()
def get_unlinked_calls(limit=50, only_mine=False):
    """Calls that matched no enquiry — the sales console's 'unattended calls' queue."""
    # "Unattended" means no enquiry exists for this number at all — not merely that the
    # link field is blank. Calls logged before their enquiry was created have a blank
    # link but are not unattended.
    conditions = [
        "(cl.custom_hotel_enquiry IS NULL OR cl.custom_hotel_enquiry = '')",
        """NOT EXISTS (
            SELECT 1 FROM `tabHotel Enquiry` he
            WHERE he.mobile_key = cl.custom_number_key
               OR he.alt_mobile_key = cl.custom_number_key
        )""",
        "IFNULL(cl.custom_number_key, '') != ''",
    ]
    params = {"limit": int(limit)}

    if frappe.utils.cint(only_mine) and frappe.get_meta("CRM Call Log").has_field("custom_agent"):
        conditions.append("cl.custom_agent = %(user)s")
        params["user"] = frappe.session.user

    return frappe.db.sql(
        """
        SELECT cl.name, cl.`from`, cl.`to`, cl.type, cl.status, cl.duration,
               cl.start_time, cl.custom_contact_name, cl.custom_agent
        FROM `tabCRM Call Log` cl
        WHERE {conditions}
        ORDER BY cl.start_time DESC
        LIMIT %(limit)s
        """.format(conditions=" AND ".join(conditions)),
        params,
        as_dict=True,
    )


@frappe.whitelist()
def get_calls_for_enquiry(enquiry):
    """Call history for an enquiry: everything linked to it, plus anything else from
    the same number that was logged before the enquiry existed."""
    doc = frappe.db.get_value(
        "Hotel Enquiry", enquiry, ["mobile_key", "alt_mobile_key"], as_dict=True
    )
    if not doc:
        return []

    keys = [k for k in (doc.mobile_key, doc.alt_mobile_key) if k]
    if not keys:
        keys = ["\x00"]  # match nothing rather than everything

    return frappe.db.sql(
        """
        SELECT cl.name, cl.`from`, cl.`to`, cl.type, cl.status, cl.duration,
               cl.start_time, cl.custom_contact_name, cl.custom_agent,
               cl.custom_hotel_enquiry
        FROM `tabCRM Call Log` cl
        WHERE cl.custom_hotel_enquiry = %(enquiry)s
           OR cl.custom_number_key IN %(keys)s
        ORDER BY cl.start_time DESC
        LIMIT 100
        """,
        {"enquiry": enquiry, "keys": tuple(keys)},
        as_dict=True,
    )


@frappe.whitelist()
def create_enquiry_from_call(call_log, guest_name=None, source=None):
    """Turn an unmatched call into a Hotel Enquiry and link the call back to it."""
    call = frappe.get_doc("CRM Call Log", call_log)

    existing = call.get("custom_hotel_enquiry")
    if existing and frappe.db.exists("Hotel Enquiry", existing):
        return existing

    number = call.get("to") if call.get("type") == "Outgoing" else call.get("from")
    if not match_key(number):
        frappe.throw(_("Call {0} has no usable phone number.").format(call_log))

    already = find_enquiry_by_number(number)
    if already:
        call.db_set("custom_hotel_enquiry", already, update_modified=False)
        return already

    enquiry = frappe.get_doc({
        "doctype": "Hotel Enquiry",
        "guest_name": guest_name or call.get("custom_contact_name") or f"Caller {number}",
        "mobile_no": number,
        "source": source or _default_source(call),
        "enquiry_owner": call.get("custom_agent") or frappe.session.user,
        "first_call_log": call.name,
        "last_contacted": call.get("start_time") or now_datetime(),
    })
    enquiry.insert(ignore_permissions=True)

    call.db_set("custom_hotel_enquiry", enquiry.name, update_modified=False)
    return enquiry.name


def _default_source(call):
    """WhatsApp calls are tagged by the sync app; everything else is a phone call.

    Source is mandatory on Hotel Enquiry, so this must always return something: a call
    that reached the hotel is a real lead, and losing it because a master row was
    renamed would be worse than attributing it to the wrong channel. Falls back to any
    active source, then to creating "Phone Call".
    """
    channel = call.get("custom_channel")
    if channel == "WhatsApp" and frappe.db.exists("Hotel Enquiry Source", "WhatsApp"):
        return "WhatsApp"
    if frappe.db.exists("Hotel Enquiry Source", "Phone Call"):
        return "Phone Call"

    fallback = frappe.db.get_value("Hotel Enquiry Source", {"is_active": 1}, "name") \
        or frappe.db.get_value("Hotel Enquiry Source", {}, "name")
    if fallback:
        return fallback

    return frappe.get_doc({
        "doctype": "Hotel Enquiry Source", "source_name": "Phone Call", "is_active": 1
    }).insert(ignore_permissions=True).name


def backfill_call_keys(batch=5000):
    """Populate custom_number_key on call logs written before the field existed, then
    link any that match an enquiry.

    Idempotent — safe to re-run. Returns (keyed, linked).
    """
    meta = frappe.get_meta("CRM Call Log")
    if not meta.has_field("custom_number_key"):
        return 0, 0

    rows = frappe.db.sql(
        """
        SELECT name, `from`, `to`, type
        FROM `tabCRM Call Log`
        WHERE IFNULL(custom_number_key, '') = ''
        LIMIT %s
        """,
        (batch,),
        as_dict=True,
    )

    keyed = 0
    for row in rows:
        number = row.to if row.type == "Outgoing" else row.get("from")
        key = match_key(number)
        if not key:
            continue
        frappe.db.set_value("CRM Call Log", row.name, "custom_number_key", key,
                            update_modified=False)
        keyed += 1

    # Link everything that now has a key and a matching enquiry.
    linked = frappe.db.sql(
        """
        UPDATE `tabCRM Call Log` cl
        JOIN `tabHotel Enquiry` he
          ON he.mobile_key = cl.custom_number_key OR he.alt_mobile_key = cl.custom_number_key
        SET cl.custom_hotel_enquiry = he.name
        WHERE IFNULL(cl.custom_hotel_enquiry, '') = ''
          AND IFNULL(cl.custom_number_key, '') != ''
        """
    )
    # Caller decides when to commit; `bench execute` and the scheduler both do it for us.
    linked_count = frappe.db.sql(
        "SELECT COUNT(*) FROM `tabCRM Call Log` WHERE IFNULL(custom_hotel_enquiry,'') != ''"
    )[0][0]
    print(f"keyed {keyed} call log(s); {linked_count} now linked to an enquiry")
    return keyed, linked_count


# --- Handset / medium resolution ----------------------------------------------------
#
# "Which of our numbers did this call go through?" The answer lives in three places
# depending on how the call was recorded, so the reports share one expression rather
# than each guessing:
#
#   1. CRM Call Log.medium  -- crm_mobile_sync writes the handset's own SIM number here,
#      and the Twilio/Exotel handlers write the provider line. Preferred when set.
#   2. CRM Device.phone_number via custom_device -- covers rows ingested before the
#      medium write was added, since the device record still knows its number.
#   3. Our side of the call itself -- `from` on an outgoing call, `to` on an incoming
#      one. Always present, because both are reqd=1, so no row is left without a line.


def handset_sql(call_alias="cl", device_alias="dev"):
    """(join, number_expr, label_expr) for the line a call went through.

    `join` is "" when CRM Device is not linked on the call log, so callers can drop it
    into a query unconditionally.
    """
    meta = frappe.get_meta("CRM Call Log")
    join = ""
    label_expr = "NULL"
    parts = []

    if meta.has_field("medium"):
        parts.append(f"NULLIF({call_alias}.medium, '')")

    if meta.has_field("custom_device") and frappe.db.exists("DocType", "CRM Device"):
        join = (
            f"LEFT JOIN `tabCRM Device` {device_alias} "
            f"ON {device_alias}.name = {call_alias}.custom_device"
        )
        parts.append(f"NULLIF({device_alias}.phone_number, '')")
        label_expr = (
            f"COALESCE(NULLIF({device_alias}.device_label, ''), "
            f"NULLIF({device_alias}.model, ''), {call_alias}.custom_device)"
        )

    parts.append(
        f"NULLIF(CASE WHEN {call_alias}.type = 'Outgoing' "
        f"THEN {call_alias}.`from` ELSE {call_alias}.`to` END, '')"
    )

    return join, f"COALESCE({', '.join(parts)})", label_expr


@frappe.whitelist()
def get_handset_numbers(doctype=None, txt=None, searchfield=None, start=0,
                        page_len=50, filters=None):
    """Handset numbers for the report filters, labelled with the handset they belong to.

    Two sources, merged. CRM Device is the register of handsets and is what a manager
    recognises — "vivo V2432" rather than 8593877773 — so every registered device lists,
    including one that has not called yet. The call log is then the authority on which
    numbers actually appear in the reports, which is how a retired handset's number and
    a provider line with no CRM Device behind it still make the list.

    `txt` matches the number or the label, so typing "vivo" finds the same row as "8593".

    The signature matches frappe's link-query convention, so this can serve a
    MultiSelectList and a Link query without a wrapper.
    """
    if not frappe.has_permission("CRM Call Log", "read"):
        frappe.throw(_("Not permitted to read call logs"), frappe.PermissionError)

    page_len = cint(page_len) or 50
    needle = (txt or "").strip().lower()

    # Registered handsets first: number -> the name a manager would use for it.
    devices = {}
    if frappe.db.exists("DocType", "CRM Device"):
        for dev in frappe.get_all(
            "CRM Device",
            fields=["phone_number", "device_label", "model", "status"],
            limit_page_length=0,
        ):
            number = (dev.phone_number or "").strip()
            if not number:
                continue
            label = dev.device_label or dev.model or _("Handset")
            if dev.status == "Retired":
                label = _("{0} (retired)").format(label)
            devices.setdefault(number, label)

    join, number_expr, _label_expr = handset_sql()
    seen = frappe.db.sql(
        f"""
        SELECT {number_expr} AS number, COUNT(*) AS calls
        FROM `tabCRM Call Log` cl
        {join}
        WHERE IFNULL({number_expr}, '') != ''
        GROUP BY {number_expr}
        ORDER BY calls DESC
        """,
        as_dict=True,
    )

    # MultiSelectList renders `description` beside the value. Numbers that carry calls
    # come first and in volume order, because that is the order a manager looks in;
    # registered handsets with nothing in the log follow, so a silent one is still
    # selectable rather than simply missing.
    out, listed = [], set()
    for row in seen:
        number = (row.number or "").strip()
        if not number or number in listed:
            continue
        listed.add(number)
        label = devices.get(number)
        out.append({
            "value": number,
            "description": (
                _("{0} — {1} calls").format(label, row.calls) if label
                else _("{0} calls").format(row.calls)
            ),
        })

    for number, label in devices.items():
        if number not in listed:
            out.append({"value": number, "description": _("{0} — no calls yet").format(label)})

    if needle:
        out = [o for o in out
               if needle in o["value"].lower() or needle in o["description"].lower()]

    return out[:page_len]
