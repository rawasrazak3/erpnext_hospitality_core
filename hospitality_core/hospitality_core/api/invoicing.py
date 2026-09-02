import frappe
from frappe import _
from frappe.utils import flt
from hospitality_core.hospitality_core.api.utils import get_hotel_company

@frappe.whitelist()
def create_invoice_from_folio(folio_name):
    """
    Generates a Sales Invoice for all unbilled transactions in the Folio.
    """
    folio = frappe.get_doc("Guest Folio", folio_name)
    
    # Determine Customer
    # If Folio has a specific Company linked, use that. Otherwise, check Guest -> Customer link.
    customer = folio.company
    if not customer:
        guest_doc = frappe.get_doc("Guest", folio.guest)
        if guest_doc.customer:
            customer = guest_doc.customer
        else:
            frappe.throw(_("Please link a Customer (Company) to this Folio or the Guest Profile to generate an Invoice."))

    # Identify Unbilled Transactions
    items_to_bill = []
    transaction_ids = []
    
    company = get_hotel_company()
    
    # Fetch default Cost Center for this Company
    default_cost_center = frappe.db.get_single_value("Hospitality Accounting Settings", "cost_center")
    if not default_cost_center:
        default_cost_center = frappe.get_cached_value('Company', company, 'cost_center')

    for trans in folio.transactions:
        if not trans.is_invoiced and not trans.is_void:
            income_account = get_income_account(trans.item, company)
            
            if not income_account:
                frappe.throw(_("Could not determine Income Account for Item {0} in Company {1}. Please check Item or Item Group accounting defaults.").format(trans.item, company))

            items_to_bill.append({
                "item_code": trans.item,
                "description": trans.description,
                "qty": trans.qty,
                "rate": trans.amount / trans.qty if trans.qty else 0,
                "income_account": income_account,
                "cost_center": default_cost_center
            })
            transaction_ids.append(trans.name)
    
    if not items_to_bill:
        frappe.throw(_("No unbilled transactions found to invoice."))

    # Create Sales Invoice
    si = frappe.new_doc("Sales Invoice")
    si.customer = customer
    si.company = company
    si.guest_folio = folio.name
    si.posting_date = frappe.utils.nowdate()
    si.due_date = frappe.utils.nowdate()
    si.set("items", items_to_bill)
    
    # Set Taxes (Optional: Fetch from Template)
    # si.set_taxes() 

    si.save()
    
    # Link Invoice to Transactions (to prevent double billing)
    for row_name in transaction_ids:
        frappe.db.set_value("Folio Transaction", row_name, {
            "is_invoiced": 1,
            "reference_doctype": "Sales Invoice",
            "reference_name": si.name
        })
    
    return si.name

def get_income_account(item_code, company):
    """
    Resolves the Income Account for an Item in the given Company.
    Order: Item Default > Item Group Default > Company Default
    """
    account = None

    # 1. Check 'Item Default' child table
    account = frappe.db.get_value("Item Default", {"parent": item_code, "company": company}, "income_account")

    # 2. Check Item Group Default child table
    if not account:
        item_group = frappe.db.get_value("Item", item_code, "item_group")
        if item_group:
            # In v15+, defaults are in 'Item Group Default' child table
            account = frappe.db.get_value("Item Group Default", {"parent": item_group, "company": company}, "income_account")

    # 3. Fallback to Hospitality Accounting Settings Income Account
    if not account:
        account = frappe.db.get_single_value("Hospitality Accounting Settings", "income_account")

    # 4. Fallback to Company Default
    if not account:
        account = frappe.get_cached_value('Company', company, 'default_income_account')
        
    return account

def cancel_sales_invoice(doc, method=None):
    """
    Hook: Sales Invoice (on_cancel)
    Logic: Unlinks all Folio Transactions from the Sales Invoice so they can be re-invoiced.
    """
    if not doc.get("guest_folio"):
        return

    transactions = frappe.get_all("Folio Transaction", filters={
        "reference_doctype": "Sales Invoice",
        "reference_name": doc.name
    })

    if transactions:
        for t in transactions:
            frappe.db.set_value("Folio Transaction", t.name, {
                "is_invoiced": 0,
                "reference_doctype": None,
                "reference_name": None
            })
        
        frappe.msgprint(_("Folio Transactions unlinked from cancelled Sales Invoice {0}.").format(doc.name))