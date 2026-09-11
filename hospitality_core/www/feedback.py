"""Public, login-free guest feedback form served at /feedback.

Opened from the WhatsApp link handed over at check-out (`?ref=...&t=...`), or bare from a
QR code in the lobby, in which case the guest types their own room number.
"""

import frappe
from frappe import _

from hospitality_core.hospitality_core.api.feedback import EXTRA_ISSUE_AREAS, get_public_context
from hospitality_core.hospitality_core.api.utils import get_hotel_name
from hospitality_core.hospitality_core.doctype.guest_feedback.guest_feedback import RATING_FIELDS

# Every response is personal to one guest; nothing here may be served from cache.
no_cache = 1
sitemap = 0


def get_context(context):
    context.no_cache = 1
    context.title = _("Share Your Feedback")

    stay = get_public_context(
        frappe.form_dict.get("ref"),
        frappe.form_dict.get("t"),
    )

    try:
        context.hotel_name = get_hotel_name()
    except Exception:
        # The form must still open on a site where the hotel company is not configured yet.
        context.hotel_name = frappe.db.get_default("company") or _("Our Hotel")

    context.stay = stay
    # `area` is the canonical value stored on the document; `label` is what the guest reads.
    context.rating_fields = [
        {"fieldname": f, "area": label, "label": _(label)} for f, label in RATING_FIELDS
    ]
    context.extra_issue_areas = [{"area": a, "label": _(a)} for a in EXTRA_ISSUE_AREAS]
    # Passed to the page rather than read from Jinja, so the template needs no request access.
    context.token = frappe.form_dict.get("t") or ""
    context.rating_fieldnames = [f for f, _label in RATING_FIELDS]

    return context
