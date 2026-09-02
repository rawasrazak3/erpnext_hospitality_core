import re
import frappe
from frappe import _
from frappe.model.document import Document


class Guest(Document):
    def validate(self):
        if not self.customer:
            customer = frappe.new_doc("Customer")
            customer.customer_name = self.full_name
            customer.customer_type = "Individual"
            customer.flags.ignore_permissions = True
            customer.insert()
            self.customer = customer.name

        self.validate_aadhaar()
        self.validate_pan()
        self.validate_gstin()

    def validate_aadhaar(self):
        """Validates Aadhaar number format: must be exactly 12 digits."""
        if not self.aadhaar_number:
            return

        # Remove spaces and hyphens for validation
        aadhaar = re.sub(r"[\s\-]", "", self.aadhaar_number)

        if not aadhaar.isdigit() or len(aadhaar) != 12:
            frappe.throw(
                _("Aadhaar Number must be exactly 12 digits. Got: {0}").format(
                    self.aadhaar_number
                )
            )

        # First digit cannot be 0 or 1
        if aadhaar[0] in ("0", "1"):
            frappe.throw(_("Aadhaar Number cannot start with 0 or 1."))

        # Store in formatted form: XXXX XXXX XXXX
        self.aadhaar_number = f"{aadhaar[:4]} {aadhaar[4:8]} {aadhaar[8:12]}"

    def validate_pan(self):
        """Validates PAN format: ABCDE1234F (5 letters, 4 digits, 1 letter)."""
        if not self.pan_number:
            return

        pan = self.pan_number.strip().upper()

        if not re.match(r"^[A-Z]{5}[0-9]{4}[A-Z]$", pan):
            frappe.throw(
                _("PAN Number must be in format ABCDE1234F. Got: {0}").format(
                    self.pan_number
                )
            )

        self.pan_number = pan

    def validate_gstin(self):
        """Validates GSTIN format: 15-character alphanumeric."""
        if not self.gstin:
            return

        gstin = self.gstin.strip().upper()

        if not re.match(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}$", gstin):
            frappe.throw(
                _("GSTIN must be a valid 15-character GST Identification Number. Got: {0}").format(
                    self.gstin
                )
            )

        self.gstin = gstin


@frappe.whitelist()
def get_guest_stats(guest):
    """Returns stay history and financial summary for a guest."""
    # 1. Stays & Last Room
    stays = frappe.get_all("Hotel Reservation", 
        filters={"guest": guest, "status": "Checked Out"},
        fields=["name", "room"],
        order_by="departure_date desc",
        limit=1
    )
    
    total_stays = frappe.db.count("Hotel Reservation", {"guest": guest, "status": "Checked Out"})
    last_room = stays[0].room if stays else None

    # 2. Financials (Total Spend from Closed Folios)
    financials = frappe.db.sql("""
        SELECT COALESCE(SUM(total_charges), 0) as total
        FROM `tabGuest Folio`
        WHERE guest = %s AND status = 'Closed'
    """, (guest,), as_dict=True)[0]
    
    total_spend = financials.total or 0.0
    avg_rate = (total_spend / total_stays) if total_stays else 0

    return {
        "total_stays": total_stays,
        "last_room": last_room,
        "total_spend": total_spend,
        "avg_rate": avg_rate
    }