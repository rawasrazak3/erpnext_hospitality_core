"""Idempotent accounting setup for Hospitality Core.

`Hospitality Accounting Settings` is a Single that every money path in this app reads
(`api/utils.py` resolves accounts from it, `api/accounting.py` posts GL entries against
them). Shipped empty, it leaves the app in a state where charges and payments cannot
post at all.

This module creates the accounts the app needs but that a stock ERPNext chart of
accounts does not provide, then fills the Single. Safe to re-run: every step checks for
an existing record first, and nothing already configured is overwritten.

Run with:
    bench --site <site> execute hospitality_core.setup_accounting.configure
"""

import frappe
from frappe import _

# Accounts this app needs beyond a stock chart of accounts.
# (settings fieldname, account name, parent group, root type, account type)
REQUIRED_ACCOUNTS = [
    (
        "income_suspense_account",
        "Unearned Room Revenue",
        "Current Liabilities",
        "Liability",
        "",
    ),
    (
        "advance_liability_account",
        "Advances from Guests",
        "Current Liabilities",
        "Liability",
        "",
    ),
    ("cgst_account", "CGST", "Duties and Taxes", "Liability", "Tax"),
    ("sgst_account", "SGST", "Duties and Taxes", "Liability", "Tax"),
    ("igst_account", "IGST", "Duties and Taxes", "Liability", "Tax"),
]


def get_default_company():
    company = frappe.db.get_single_value("Hospitality Accounting Settings", "company")
    if company:
        return company

    companies = frappe.get_all("Company", pluck="name", limit=2)
    if len(companies) == 1:
        return companies[0]
    if not companies:
        frappe.throw(_("No Company exists. Create one before configuring Hospitality Core."))
    frappe.throw(
        _("More than one Company exists. Set the company on Hospitality Accounting Settings first.")
    )


def ensure_account(account_name, parent_group, root_type, account_type, company, abbr):
    """Return an existing account of this name under the company, else create it."""
    full_name = f"{account_name} - {abbr}"
    if frappe.db.exists("Account", full_name):
        return full_name

    existing = frappe.db.get_value(
        "Account", {"account_name": account_name, "company": company, "is_group": 0}, "name"
    )
    if existing:
        return existing

    parent = f"{parent_group} - {abbr}"
    if not frappe.db.exists("Account", parent):
        parent = frappe.db.get_value(
            "Account", {"account_name": parent_group, "company": company, "is_group": 1}, "name"
        )
    if not parent:
        frappe.throw(
            _("Cannot create {0}: parent group {1} not found for company {2}.").format(
                account_name, parent_group, company
            )
        )

    account = frappe.get_doc({
        "doctype": "Account",
        "account_name": account_name,
        "parent_account": parent,
        "company": company,
        "root_type": root_type,
        "is_group": 0,
        "account_type": account_type or None,
    })
    account.insert(ignore_permissions=True)
    return account.name


def find_account(company, account_types, root_type=None):
    filters = {"company": company, "is_group": 0, "account_type": ["in", account_types]}
    if root_type:
        filters["root_type"] = root_type
    return frappe.db.get_value("Account", filters, "name")


def configure():
    company = get_default_company()
    abbr = frappe.db.get_value("Company", company, "abbr")
    settings = frappe.get_single("Hospitality Accounting Settings")

    settings.company = company
    if not settings.hotel_name:
        settings.hotel_name = company

    # Accounts that already exist in a stock chart of accounts.
    if not settings.receivable_account:
        settings.receivable_account = (
            frappe.db.get_value("Company", company, "default_receivable_account")
            or find_account(company, ["Receivable"])
        )
    if not settings.income_account:
        settings.income_account = (
            frappe.db.get_value("Company", company, "default_income_account")
            or find_account(company, ["Income Account"], root_type="Income")
        )
    if not settings.cost_center:
        settings.cost_center = frappe.db.get_value("Company", company, "cost_center") or frappe.db.get_value(
            "Cost Center", {"company": company, "is_group": 0}, "name"
        )

    # Accounts this app has to create.
    for fieldname, account_name, parent_group, root_type, account_type in REQUIRED_ACCOUNTS:
        if not settings.get(fieldname):
            settings.set(
                fieldname,
                ensure_account(account_name, parent_group, root_type, account_type, company, abbr),
            )

    if not settings.default_gst_rate:
        settings.default_gst_rate = 12

    # The stay policy. These two Time fields ship blank and have been seen holding a
    # timestamp rather than a time of day, which silently breaks every arrival/departure
    # datetime the booking code builds from them.
    if not settings.billing_policy:
        settings.billing_policy = "Fixed Time"
    if not _is_valid_time(settings.standard_check_in_time):
        settings.standard_check_in_time = "14:00:00"
    if not _is_valid_time(settings.standard_check_out_time):
        settings.standard_check_out_time = "12:00:00"

    settings.save(ignore_permissions=True)
    frappe.db.commit()

    print(f"Hospitality Accounting Settings configured for {company}:")
    for field in (
        "receivable_account",
        "income_account",
        "income_suspense_account",
        "advance_liability_account",
        "cgst_account",
        "sgst_account",
        "cost_center",
        "billing_policy",
        "standard_check_in_time",
        "standard_check_out_time",
    ):
        print(f"  {field:28} = {settings.get(field)}")


def _is_valid_time(value):
    """A usable check-in/out time: present, and a plain time of day rather than a
    timestamp that was written into the Time field by mistake."""
    if not value:
        return False
    text = str(value)
    # A stray timestamp shows up as sub-second precision on a field that should be
    # a round clock time (e.g. "00:21:02.191127").
    if "." in text:
        return False
    return True
