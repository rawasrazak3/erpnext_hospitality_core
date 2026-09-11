import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt

# The areas the guest is asked to rate, in the order they appear on the public form.
# Kept here so the web form, the DocType and the follow-up rules cannot drift apart.
RATING_FIELDS = (
    ("room_neatness", "Room Neatness"),
    ("food_quality", "Food & Beverage"),
    ("air_conditioning", "Air Conditioning"),
    ("television", "Television"),
    ("other_electronics", "Other Electronics"),
    ("maintenance", "Maintenance"),
    ("wifi", "Wi-Fi / Internet"),
    ("staff_service", "Staff Service"),
    ("check_in_experience", "Check-in / Check-out"),
    ("value_for_money", "Value for Money"),
)

# A rating at or below this is a complaint, not a score, so it raises the follow-up flag.
POOR_RATING = 2


class GuestFeedback(Document):
    def validate(self):
        self.clamp_ratings()
        self.set_average_rating()
        self.set_follow_up_flag()

    def clamp_ratings(self):
        """Ratings are 1-5; 0 means the guest skipped the area. Anything else is noise."""
        for fieldname in ("overall_rating", *[f for f, _label in RATING_FIELDS]):
            value = cint(self.get(fieldname))
            if value < 0 or value > 5:
                frappe.throw(
                    _("{0} must be between 1 and 5.").format(_(self.meta.get_label(fieldname)))
                )

    def set_average_rating(self):
        scores = [cint(self.get(f)) for f, _label in RATING_FIELDS if cint(self.get(f))]
        if cint(self.overall_rating):
            scores.append(cint(self.overall_rating))

        self.average_rating = flt(sum(scores) / len(scores), 2) if scores else 0

    def set_follow_up_flag(self):
        """Flag anything a manager should read today rather than at month end."""
        poor = any(
            0 < cint(self.get(f)) <= POOR_RATING
            for f in ("overall_rating", *[f for f, _label in RATING_FIELDS])
        )
        self.needs_follow_up = 1 if (poor or self.issues or self.would_recommend == "No") else 0
