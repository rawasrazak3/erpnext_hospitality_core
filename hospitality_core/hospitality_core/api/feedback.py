"""Guest feedback: a public, login-free form and the WhatsApp hand-off used at check-out.

The link handed to a guest is `/feedback?ref=<reservation>&t=<signature>`. The signature is
an HMAC over the reservation name with the site secret, so the page can greet the guest by
name and tie the response to the right stay without anyone being able to walk the
reservation series. An unsigned `/feedback` still works — that is the lobby QR code case —
it just collects the room number from the guest instead.
"""

import hashlib
import hmac
import json
from urllib.parse import quote, urlencode

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, get_url, now_datetime, strip_html

from hospitality_core.hospitality_core.api.utils import get_hotel_name
from hospitality_core.hospitality_core.doctype.guest_feedback.guest_feedback import RATING_FIELDS

# Free text the guest types. Generous, but bounded — this is an unauthenticated endpoint.
MAX_TEXT_LENGTH = 2000

# Areas a guest can flag that are not scored on the 1-5 scale.
EXTRA_ISSUE_AREAS = ("Noise", "Other")

# Every rated area is also reportable, so the two lists can never drift apart.
# Must stay in step with the `area` options on Guest Feedback Issue.
VALID_ISSUE_AREAS = {label for _field, label in RATING_FIELDS} | set(EXTRA_ISSUE_AREAS)


def _secret():
    from frappe.utils.verified_command import get_secret

    return get_secret()


def _sign(reservation: str) -> str:
    """Short HMAC tying a feedback link to one reservation."""
    return hmac.new(
        _secret().encode(), f"guest-feedback:{reservation}".encode(), hashlib.sha256
    ).hexdigest()[:20]


def _is_valid_token(reservation: str, token: str) -> bool:
    if not reservation or not token:
        return False
    return hmac.compare_digest(_sign(reservation), token)


def get_feedback_url(reservation: str | None = None) -> str:
    """Public URL of the feedback form, signed when it belongs to a specific stay."""
    if not reservation:
        return get_url("/feedback")

    params = urlencode({"ref": reservation, "t": _sign(reservation)})
    return f"{get_url('/feedback')}?{params}"


def _digits_only(mobile: str | None) -> str:
    """wa.me wants the number in international form with no punctuation."""
    return "".join(ch for ch in (mobile or "") if ch.isdigit())


@frappe.whitelist()
def get_whatsapp_feedback_link(reservation: str) -> dict:
    """Everything the desk needs to open a pre-filled WhatsApp chat with the guest.

    This only builds a `wa.me` redirect — the message is sent by the staff member from
    their own WhatsApp, nothing is transmitted from the server.
    """
    res = frappe.get_doc("Hotel Reservation", reservation)
    res.check_permission("read")

    guest_name = mobile = ""
    if res.guest:
        guest_name, mobile = frappe.db.get_value("Guest", res.guest, ["full_name", "mobile_no"]) or ("", "")

    first_name = (guest_name or "").strip().split(" ")[0]
    feedback_url = get_feedback_url(reservation)

    message = _(
        "Hello {0}, thank you for staying with {1}.\n\n"
        "Your room was {2}. Before you go, would you tell us how we did? "
        "It takes under a minute and no login is needed:\n{3}\n\n"
        "Your feedback goes straight to our management team."
    ).format(first_name or _("Guest"), get_hotel_name(), res.room or "-", feedback_url)

    digits = _digits_only(mobile)

    return {
        "reservation": reservation,
        "guest_name": guest_name,
        "mobile_no": mobile,
        "has_mobile": bool(digits),
        "feedback_url": feedback_url,
        "message": message,
        # Empty number still opens WhatsApp with the message, so the agent can pick the chat.
        "whatsapp_url": f"https://wa.me/{digits}?text={quote(message)}",
    }


def get_public_context(reference: str | None, token: str | None) -> dict:
    """Guest-safe details for prefilling the form. Never called from a whitelisted method."""
    blank = {
        "reservation": None,
        "guest": None,
        "guest_name": "",
        "first_name": "",
        "room": "",
        "already_submitted": False,
    }

    if not _is_valid_token(reference, token):
        return blank

    res = frappe.db.get_value(
        "Hotel Reservation", reference, ["name", "guest", "room"], as_dict=True
    )
    if not res:
        return blank

    guest_name = frappe.db.get_value("Guest", res.guest, "full_name") if res.guest else ""

    return {
        "reservation": res.name,
        "guest": res.guest,
        "guest_name": guest_name or "",
        "first_name": (guest_name or "").strip().split(" ")[0],
        "room": res.room or "",
        "already_submitted": bool(
            frappe.db.exists("Guest Feedback", {"reservation": res.name})
        ),
    }


def _clean_text(value) -> str:
    """Guests type prose, not markup. Strip tags and cap the length."""
    if not value:
        return ""
    return strip_html(str(value)).strip()[:MAX_TEXT_LENGTH]


def _clean_rating(value) -> int:
    rating = cint(value)
    return rating if 1 <= rating <= 5 else 0


@frappe.whitelist(allow_guest=True)
@rate_limit(limit=10, seconds=60 * 60)
def submit_feedback(payload: str | dict) -> dict:
    """Record one guest's feedback. No login, so everything here is treated as hostile input."""
    data = json.loads(payload) if isinstance(payload, str) else (payload or {})

    reservation = None
    guest = None
    source = "Web"

    reference = data.get("reservation")
    token = data.get("token")
    if _is_valid_token(reference, token) and frappe.db.exists("Hotel Reservation", reference):
        reservation = reference
        guest = frappe.db.get_value("Hotel Reservation", reservation, "guest")
        source = "WhatsApp Link"

        if frappe.db.exists("Guest Feedback", {"reservation": reservation}):
            return {
                "ok": False,
                "already_submitted": True,
                "message": _("We have already received your feedback for this stay. Thank you!"),
            }

    ratings = {field: _clean_rating(data.get(field)) for field, _label in RATING_FIELDS}
    overall = _clean_rating(data.get("overall_rating"))
    what_went_well = _clean_text(data.get("what_went_well"))
    improvements = _clean_text(data.get("improvements"))

    issues = []
    for row in data.get("issues") or []:
        area = (row or {}).get("area")
        if area in VALID_ISSUE_AREAS:
            issues.append({"area": area, "details": _clean_text(row.get("details"))})

    if not any(ratings.values()) and not overall and not issues and not improvements:
        frappe.throw(_("Please rate at least one area or tell us what we can improve."))

    would_recommend = data.get("would_recommend")
    if would_recommend not in ("Yes", "Maybe", "No"):
        would_recommend = ""

    doc = frappe.get_doc(
        {
            "doctype": "Guest Feedback",
            "reservation": reservation,
            "guest": guest,
            "guest_name": _clean_text(data.get("guest_name"))[:140],
            "room": _resolve_room(data.get("room"), reservation),
            "mobile_no": _clean_text(data.get("mobile_no"))[:20],
            "email_id": _clean_text(data.get("email_id"))[:140],
            "overall_rating": overall,
            "what_went_well": what_went_well,
            "improvements": improvements,
            "would_recommend": would_recommend,
            "issues": issues,
            "status": "New",
            "source": source,
            "submitted_on": now_datetime(),
            "submitted_from_ip": frappe.local.request_ip,
            **ratings,
        }
    )

    if reservation:
        arrival, departure = frappe.db.get_value(
            "Hotel Reservation", reservation, ["arrival_date", "departure_date"]
        )
        doc.arrival_date = arrival
        doc.departure_date = departure

    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "ok": True,
        "name": doc.name,
        "needs_follow_up": doc.needs_follow_up,
        "message": _("Thank you — your feedback has reached our management team."),
    }


def _resolve_room(room, reservation):
    """Trust the reservation's room over anything typed into the form."""
    if reservation:
        return frappe.db.get_value("Hotel Reservation", reservation, "room")

    room = _clean_text(room)[:140]
    return room if room and frappe.db.exists("Hotel Room", room) else None
