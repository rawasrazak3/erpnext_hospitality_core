import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, nowdate

class LostandFoundItem(Document):
    def validate(self):
        self.validate_dates()
        self.validate_claim()

    def validate_dates(self):
        if getdate(self.found_date) > getdate(nowdate()):
            frappe.throw(_("Found Date cannot be in the future."))

    def validate_claim(self):
        if self.status == "Claimed":
            if not self.claimant_info:
                frappe.throw(_("Please enter Claimant Info before marking as Claimed."))
            
            if not self.claimed_date:
                self.claimed_date = nowdate()
            
            if getdate(self.claimed_date) < getdate(self.found_date):
                frappe.throw(_("Claimed Date cannot be before Found Date."))


# Backwards-compatible alias for the previous class name.
LostAndFoundItem = LostandFoundItem
