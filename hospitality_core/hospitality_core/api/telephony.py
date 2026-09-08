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
from frappe.utils import now_datetime

# India: compare the last 10 digits, which survives +91 / 0 / spacing differences
# between what the handset reports and what a sales user types. Change to 8 for GCC.
MATCH_DIGITS = 10


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
    """WhatsApp calls are tagged by the sync app; everything else is a phone call."""
    channel = call.get("custom_channel")
    if channel == "WhatsApp" and frappe.db.exists("Hotel Enquiry Source", "WhatsApp"):
        return "WhatsApp"
    return "Phone Call" if frappe.db.exists("Hotel Enquiry Source", "Phone Call") else None


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
