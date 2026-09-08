import frappe
from frappe import _
from frappe.utils import flt
from hospitality_core.hospitality_core.api.utils import (
    get_hotel_company,
    get_receivable_account,
    get_tax_breakdown,
    get_tax_config,
)


def make_gl_entries_for_folio_transaction(txn_doc, method=None):
    """
    Creates GL entries for a Folio Transaction (Charge).
    dr Receivable / cr Suspense (with GST split)
    """
    if flt(txn_doc.amount) <= 0 or txn_doc.item in ["PAYMENT", "DISCOUNT", "COMPLIMENTARY"]:
        return

    # Handle Cancellation/Void
    is_cancelled = False
    if method == "on_cancel" or txn_doc.docstatus == 2 or getattr(txn_doc, "is_void", 0):
        is_cancelled = True

    # Skip if originated from POS Invoice (POS Invoice creates its own GL entries)
    if txn_doc.reference_doctype == "POS Invoice":
        return

    settings = frappe.get_single("Hospitality Accounting Settings")
    company = getattr(settings, "company", None) or get_hotel_company()
    
    if not settings.receivable_account or not settings.income_suspense_account:
        frappe.throw(_("Please configure Receivable Account and Income Suspense Account in Hospitality Accounting Settings before posting charges."))
    
    # 1. Identify Customer (Party)
    guest_folio = frappe.get_doc("Guest Folio", txn_doc.parent)
    customer = guest_folio.company
    
    if not customer:
        customer = frappe.db.get_value("Guest", guest_folio.guest, "customer")
    
    if not customer:
        return

    # 2. Check if already created (matching this specific flow: original or reversal)
    check_debit = flt(txn_doc.amount) if not is_cancelled else 0
    if frappe.db.exists("GL Entry", {
        "remarks": ["like", f"%Ref: {txn_doc.name}%"],
        "debit": check_debit,
        "account": settings.receivable_account,
        "is_cancelled": 1 if is_cancelled else 0
    }):
        return

    gl_entries = []
    
    # Debit Receivable
    gl_entries.append(frappe.get_doc({
        "doctype": "GL Entry",
        "posting_date": txn_doc.posting_date,
        "account": settings.receivable_account,
        "party_type": "Customer",
        "party": customer,
        "debit": flt(txn_doc.amount) if not is_cancelled else 0,
        "credit": 0 if not is_cancelled else flt(txn_doc.amount),
        "voucher_type": "Guest Folio",
        "voucher_no": txn_doc.parent,
        "remarks": f"{txn_doc.description} (Ref: {txn_doc.name})",
        "is_cancelled": 1 if is_cancelled else 0,
        "cost_center": settings.cost_center,
        "company": company
    }))

    # Credits — GST-inclusive split
    total_amount = flt(txn_doc.amount)
    breakdown = get_tax_breakdown(total_amount)
    
    net_amount = breakdown["net_amount"]
    cgst_amount = breakdown["cgst_amount"]
    sgst_amount = breakdown["sgst_amount"]

    # 1. Credit Suspense (Net Revenue)
    gl_entries.append(frappe.get_doc({
        "doctype": "GL Entry",
        "posting_date": txn_doc.posting_date,
        "account": settings.income_suspense_account,
        "debit": 0 if not is_cancelled else net_amount,
        "credit": net_amount if not is_cancelled else 0,
        "voucher_type": "Guest Folio",
        "voucher_no": txn_doc.parent,
        "remarks": f"{txn_doc.description} (Net) (Ref: {txn_doc.name})",
        "is_cancelled": 1 if is_cancelled else 0,
        "cost_center": settings.cost_center,
        "company": company
    }))

    # 2. Credit CGST
    cgst_account = getattr(settings, "cgst_account", None)
    if cgst_amount > 0 and cgst_account:
        gl_entries.append(frappe.get_doc({
            "doctype": "GL Entry",
            "posting_date": txn_doc.posting_date,
            "account": cgst_account,
            "debit": 0 if not is_cancelled else cgst_amount,
            "credit": cgst_amount if not is_cancelled else 0,
            "voucher_type": "Guest Folio",
            "voucher_no": txn_doc.parent,
            "remarks": f"CGST ({breakdown['gst_rate']/2}%) for {txn_doc.name}",
            "is_cancelled": 1 if is_cancelled else 0,
            "cost_center": settings.cost_center,
            "company": company
        }))

    # 3. Credit SGST
    sgst_account = getattr(settings, "sgst_account", None)
    if sgst_amount > 0 and sgst_account:
        gl_entries.append(frappe.get_doc({
            "doctype": "GL Entry",
            "posting_date": txn_doc.posting_date,
            "account": sgst_account,
            "debit": 0 if not is_cancelled else sgst_amount,
            "credit": sgst_amount if not is_cancelled else 0,
            "voucher_type": "Guest Folio",
            "voucher_no": txn_doc.parent,
            "remarks": f"SGST ({breakdown['gst_rate']/2}%) for {txn_doc.name}",
            "is_cancelled": 1 if is_cancelled else 0,
            "cost_center": settings.cost_center,
            "company": company
        }))

    for entry in gl_entries:
        entry.insert(ignore_permissions=True)

def handle_payment_income_realization(payment_doc, folio_id, amount, cancel=0):
    """
    Transfers amount from Suspense to Income upon Payment.
    dr Suspense / cr Income
    Only the Net portion is transferred, as Taxes were already split into 
    total liability accounts during the Folio Transaction (Charge).
    """
    settings = frappe.get_single("Hospitality Accounting Settings")
    company = getattr(settings, "company", None) or get_hotel_company()

    # An advance for a future stay is not revenue on the day it is collected — the guest
    # has not stayed yet, and the matching room charge will not exist until check-in or
    # the night audit, possibly in a later period. Park it against the advance liability
    # account instead; api.advance.apply_advance releases it into suspense when the money
    # is actually applied to a room folio.
    if frappe.db.get_value("Guest Folio", folio_id, "is_booking_master"):
        park_advance_as_liability(payment_doc, folio_id, amount, cancel=cancel)
        return

    # Calculate Net portion using configured GST rate
    breakdown = get_tax_breakdown(abs(flt(amount)))
    net_amount = breakdown["net_amount"]
    
    if not settings.income_suspense_account or not settings.income_account:
        frappe.throw(_("Please configure Income Account and Income Suspense Account in Hospitality Accounting Settings before recording payments."))

    gl_entries = []

    # Debit Suspense
    gl_entries.append(frappe.get_doc({
        "doctype": "GL Entry",
        "posting_date": payment_doc.posting_date,
        "account": settings.income_suspense_account,
        "party_type": payment_doc.get("party_type"),
        "party": payment_doc.get("party"),
        "debit": net_amount if not cancel else 0,
        "credit": 0 if not cancel else net_amount,
        "voucher_type": "Payment Entry",
        "voucher_no": payment_doc.name,
        "remarks": f"Income Realization (Net) for Folio {folio_id}",
        "cost_center": settings.cost_center,
        "company": company
    }))

    # Credit Income
    gl_entries.append(frappe.get_doc({
        "doctype": "GL Entry",
        "posting_date": payment_doc.posting_date,
        "account": settings.income_account,
        "party_type": payment_doc.get("party_type"),
        "party": payment_doc.get("party"),
        "debit": 0 if not cancel else net_amount,
        "credit": net_amount if not cancel else 0,
        "voucher_type": "Payment Entry",
        "voucher_no": payment_doc.name,
        "remarks": f"Income Realization (Net) for Folio {folio_id}",
        "cost_center": settings.cost_center,
        "company": company
    }))

    for entry in gl_entries:
        entry.insert(ignore_permissions=True)

def park_advance_as_liability(payment_doc, folio_id, amount, cancel=0):
    """Hold an advance as a liability instead of recognising income.

    dr Receivable / cr Advance Liability — the guest has paid, and the resort now owes
    them a stay. Reversed into income suspense by api.advance.apply_advance at check-in.
    """
    settings = frappe.get_single("Hospitality Accounting Settings")
    company = getattr(settings, "company", None) or get_hotel_company()
    liability = settings.get("advance_liability_account")

    if not liability:
        frappe.throw(_(
            "Set an Advance Liability Account in Hospitality Accounting Settings "
            "before taking advances for future stays."
        ))

    gross = abs(flt(amount))
    receivable = settings.receivable_account or get_receivable_account(company)

    for account, debit, credit in (
        (receivable, gross, 0.0),
        (liability, 0.0, gross),
    ):
        frappe.get_doc({
            "doctype": "GL Entry",
            "posting_date": payment_doc.posting_date,
            "account": account,
            "party_type": payment_doc.get("party_type"),
            "party": payment_doc.get("party"),
            "debit": credit if cancel else debit,
            "credit": debit if cancel else credit,
            "voucher_type": "Payment Entry",
            "voucher_no": payment_doc.name,
            "remarks": f"Advance held for Booking Folio {folio_id}",
            "cost_center": settings.cost_center,
            "company": company,
        }).insert(ignore_permissions=True)


def redirect_pos_income_to_suspense(pos_invoice, method=None):
    """
    Hook: POS Invoice (on_submit/on_cancel)
    Redirects the portion charged to room from Income to Suspense.
    dr Income / cr Suspense
    """
    is_cancelled = False
    if method == "on_cancel" or pos_invoice.docstatus == 2:
        is_cancelled = True

    room_charge_amount = 0
    for pay in pos_invoice.payments:
        if pay.mode_of_payment == "Guest Account":
            room_charge_amount += flt(pay.amount)

    if room_charge_amount <= 0:
        return

    settings = frappe.get_single("Hospitality Accounting Settings")
    company = getattr(settings, "company", None) or pos_invoice.company or get_hotel_company()
    
    if not settings.income_account or not settings.income_suspense_account:
        frappe.throw(_("Please configure Income Account and Income Suspense Account in Hospitality Accounting Settings before submitting POS Invoices."))
    
    from erpnext.accounts.general_ledger import make_gl_entries
    
    gl_entries = []

    # 1. Debit Income (Reduce Realized Income)
    gl_entries.append(frappe._dict({
        "account": settings.income_account,
        "party_type": "Customer",
        "party": pos_invoice.customer,
        "debit": abs(flt(room_charge_amount)),
        "credit": 0,
        "posting_date": pos_invoice.posting_date,
        "voucher_type": "POS Invoice",
        "voucher_no": pos_invoice.name,
        "remarks": f"Deferring Income for Room Charge (Invoice {pos_invoice.name})",
        "cost_center": settings.cost_center,
        "company": company
    }))

    # 2. Credit Suspense (Increase Unearned)
    gl_entries.append(frappe._dict({
        "account": settings.income_suspense_account,
        "party_type": "Customer",
        "party": pos_invoice.customer,
        "debit": 0,
        "credit": abs(flt(room_charge_amount)),
        "posting_date": pos_invoice.posting_date,
        "voucher_type": "POS Invoice",
        "voucher_no": pos_invoice.name,
        "remarks": f"Deferring Income for Room Charge (Invoice {pos_invoice.name})",
        "cost_center": settings.cost_center,
        "company": company
    }))

    if gl_entries:
        make_gl_entries(gl_entries, cancel=is_cancelled, adv_adj=True)

def reclassify_pos_taxes(pos_invoice, method=None):
    """
    Hook: POS Invoice (on_submit/on_cancel)
    Deducts taxes from the full income realized by ERPNext POS and reclassifies them.
    Uses configured GST rate for tax split.
    dr Income (or Suspense if Room Charge) / cr CGST, SGST
    """
    is_cancelled = False
    if method == "on_cancel" or pos_invoice.docstatus == 2:
        is_cancelled = True

    if pos_invoice.grand_total <= 0:
        return

    settings = frappe.get_single("Hospitality Accounting Settings")
    company = getattr(settings, "company", None) or pos_invoice.company or get_hotel_company()

    if not settings.income_account or not settings.income_suspense_account:
        frappe.throw(_("Please configure Income Account and Income Suspense Account in Hospitality Accounting Settings before submitting POS Invoices."))

    from erpnext.accounts.general_ledger import make_gl_entries

    total_amount = flt(pos_invoice.grand_total, 2)
    breakdown = get_tax_breakdown(total_amount)
    
    cgst_amount = breakdown["cgst_amount"]
    sgst_amount = breakdown["sgst_amount"]
    total_tax = breakdown["total_tax"]
    
    # Determine Source of Funds (Income vs Suspense)
    room_charge_paid = 0
    for pay in pos_invoice.payments:
        if pay.mode_of_payment == "Guest Account":
            room_charge_paid += flt(pay.amount, 2)
            
    if room_charge_paid > total_amount:
        room_charge_paid = total_amount

    suspense_ratio = room_charge_paid / total_amount if total_amount > 0 else 0
    
    tax_from_suspense = flt(total_tax * suspense_ratio, 2)
    tax_from_income = flt(total_tax - tax_from_suspense, 2)

    gl_entries = []

    # 1. Debit Income (Tax portion of Cash/Card sales)
    if tax_from_income > 0:
        gl_entries.append(frappe._dict({
            "account": settings.income_account,
            "party_type": "Customer",
            "party": pos_invoice.customer,
            "debit": tax_from_income,
            "credit": 0,
            "posting_date": pos_invoice.posting_date,
            "voucher_type": "POS Invoice",
            "voucher_no": pos_invoice.name,
            "remarks": f"Tax Reclassification (Income) for POS {pos_invoice.name}",
            "cost_center": settings.cost_center,
            "company": company
        }))

    # 2. Debit Suspense (Tax portion of Room Charges)
    if tax_from_suspense > 0:
        gl_entries.append(frappe._dict({
            "account": settings.income_suspense_account,
            "party_type": "Customer",
            "party": pos_invoice.customer,
            "debit": tax_from_suspense,
            "credit": 0,
            "posting_date": pos_invoice.posting_date,
            "voucher_type": "POS Invoice",
            "voucher_no": pos_invoice.name,
            "remarks": f"Tax Reclassification (Suspense) for POS {pos_invoice.name}",
            "cost_center": settings.cost_center,
            "company": company
        }))

    # 3. Credit CGST
    cgst_account = getattr(settings, "cgst_account", None)
    if cgst_amount > 0 and cgst_account:
        gl_entries.append(frappe._dict({
            "account": cgst_account,
            "debit": 0,
            "credit": cgst_amount,
            "posting_date": pos_invoice.posting_date,
            "voucher_type": "POS Invoice",
            "voucher_no": pos_invoice.name,
            "remarks": f"CGST ({breakdown['gst_rate']/2}%) for POS {pos_invoice.name}",
            "cost_center": settings.cost_center,
            "company": company
        }))

    # 4. Credit SGST
    sgst_account = getattr(settings, "sgst_account", None)
    if sgst_amount > 0 and sgst_account:
        gl_entries.append(frappe._dict({
            "account": sgst_account,
            "debit": 0,
            "credit": sgst_amount,
            "posting_date": pos_invoice.posting_date,
            "voucher_type": "POS Invoice",
            "voucher_no": pos_invoice.name,
            "remarks": f"SGST ({breakdown['gst_rate']/2}%) for POS {pos_invoice.name}",
            "cost_center": settings.cost_center,
            "company": company
        }))

    if gl_entries:
        make_gl_entries(gl_entries, cancel=is_cancelled, adv_adj=True)

def create_expense_gl_entries(expense_doc, method=None):
    """
    Hook: Hospitality Expense (on_submit/on_cancel)
    """
    is_cancelled = False
    if method == "on_cancel" or expense_doc.docstatus == 2:
        is_cancelled = True

    if not expense_doc.expense_account or not expense_doc.payment_account:
        expense_doc.set_account_details()
        if not expense_doc.expense_account or not expense_doc.payment_account:
            frappe.throw(_("Expense Account and Payment Account are required for GL entries."))

    gl_entries = []
    company = expense_doc.company or get_hotel_company()

    # 1. Debit Expense Account (Net Amount)
    gl_entries.append(frappe.get_doc({
        "doctype": "GL Entry",
        "posting_date": expense_doc.expense_date,
        "account": expense_doc.expense_account,
        "debit": abs(flt(expense_doc.amount)) if not is_cancelled else 0,
        "credit": 0 if not is_cancelled else abs(flt(expense_doc.amount)),
        "voucher_type": "Hospitality Expense",
        "voucher_no": expense_doc.name,
        "remarks": f"Expense: {expense_doc.expense_category} - {expense_doc.description or ''}",
        "is_cancelled": 1 if is_cancelled else 0,
        "cost_center": expense_doc.cost_center,
        "company": company
    }))

    # 2. Debit Tax Accounts (if any)
    for tax in expense_doc.get("taxes"):
        if flt(tax.tax_amount) > 0:
            gl_entries.append(frappe.get_doc({
                "doctype": "GL Entry",
                "posting_date": expense_doc.expense_date,
                "account": tax.account_head,
                "debit": abs(flt(tax.tax_amount)) if not is_cancelled else 0,
                "credit": 0 if not is_cancelled else abs(flt(tax.tax_amount)),
                "voucher_type": "Hospitality Expense",
                "voucher_no": expense_doc.name,
                "remarks": f"Tax: {tax.description or tax.account_head} for {expense_doc.name}",
                "is_cancelled": 1 if is_cancelled else 0,
                "cost_center": expense_doc.cost_center,
                "company": company
            }))

    # 3. Credit Payment Account (Grand Total)
    gl_entries.append(frappe.get_doc({
        "doctype": "GL Entry",
        "posting_date": expense_doc.expense_date,
        "account": expense_doc.payment_account,
        "debit": 0 if not is_cancelled else abs(flt(expense_doc.grand_total)),
        "credit": abs(flt(expense_doc.grand_total)) if not is_cancelled else 0,
        "voucher_type": "Hospitality Expense",
        "voucher_no": expense_doc.name,
        "remarks": f"Payment via {expense_doc.paid_via} for {expense_doc.name}",
        "is_cancelled": 1 if is_cancelled else 0,
        "cost_center": expense_doc.cost_center,
        "company": company
    }))

    for entry in gl_entries:
        entry.insert(ignore_permissions=True)
