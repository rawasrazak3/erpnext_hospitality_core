import frappe
from frappe import _
from frappe.utils import flt


def get_hotel_company():
    """
    Returns the company name configured for the hospitality module.
    Resolution order:
        1. Hospitality Accounting Settings → company
        2. frappe.db.get_default("company")
    Throws an error if neither is configured.
    """
    company = None

    try:
        company = frappe.db.get_single_value("Hospitality Accounting Settings", "company")
    except Exception:
        pass

    if not company:
        company = frappe.db.get_default("company")

    if not company:
        frappe.throw(_(
            "No company configured for Hospitality Core. "
            "Please set the Company in Hospitality Accounting Settings."
        ))

    return company


def get_hotel_name():
    """
    Returns a human-friendly hotel name for display in messages.
    Falls back to the company name if hotel_name is not set.
    """
    hotel_name = None

    try:
        hotel_name = frappe.db.get_single_value("Hospitality Accounting Settings", "hotel_name")
    except Exception:
        pass

    if not hotel_name:
        hotel_name = get_hotel_company()

    return hotel_name


def get_receivable_account(company=None):
    """
    Returns the default receivable account for the hotel company.
    """
    if not company:
        company = get_hotel_company()

    account = frappe.db.get_value("Company", company, "default_receivable_account")
    if not account:
        frappe.throw(_(
            "No Default Receivable Account found for '{0}'. "
            "Please configure it in Company settings."
        ).format(company))

    return account


def get_mop_account(mode_of_payment, company=None):
    """
    Returns the default account for a given Mode of Payment under the hotel company.
    """
    if not company:
        company = get_hotel_company()

    account = frappe.db.get_value(
        "Mode of Payment Account",
        {"parent": mode_of_payment, "company": company},
        "default_account"
    )

    if not account:
        # Try without company filter as fallback
        account = frappe.db.get_value(
            "Mode of Payment Account",
            {"parent": mode_of_payment},
            "default_account"
        )

    if not account:
        frappe.throw(_(
            "No account configured for Mode of Payment '{0}' under '{1}'. "
            "Please add a default account for it."
        ).format(mode_of_payment, company))

    return account


def get_cash_account(company=None):
    """
    Returns the default cash account for the hotel company.
    """
    if not company:
        company = get_hotel_company()

    cash_account = frappe.db.get_value("Company", company, "default_cash_account")
    if not cash_account:
        cash_account = frappe.db.get_value(
            "Account", {"account_type": "Cash", "company": company}, "name"
        )

    return cash_account


def get_tax_config():
    """
    Returns the tax configuration from Hospitality Accounting Settings.
    Returns a dict with: gst_rate, cgst_rate, sgst_rate, enable_igst,
    cgst_account, sgst_account, igst_account.
    """
    settings = frappe.get_single("Hospitality Accounting Settings")

    gst_rate = flt(getattr(settings, "default_gst_rate", 12))
    half_rate = flt(gst_rate / 2, 2)

    return {
        "gst_rate": gst_rate,
        "cgst_rate": half_rate,
        "sgst_rate": half_rate,
        "enable_igst": getattr(settings, "enable_igst", 0),
        "cgst_account": getattr(settings, "cgst_account", None),
        "sgst_account": getattr(settings, "sgst_account", None),
        "igst_account": getattr(settings, "igst_account", None),
    }


def get_tax_breakdown(total_amount, gst_rate=None):
    """
    Returns a breakdown of a GST-inclusive amount.
    Total = Net + GST
    GST = CGST (half) + SGST (half)

    Example at 12% GST:
        Total = Net * 1.12
        Net = Total / 1.12
        CGST = Net * 0.06
        SGST = Net * 0.06
    """
    total_amount = flt(total_amount)

    if gst_rate is None:
        try:
            gst_rate = flt(frappe.db.get_single_value(
                "Hospitality Accounting Settings", "default_gst_rate"
            ))
        except Exception:
            gst_rate = 12  # Default GST rate

    if gst_rate <= 0:
        return {
            "net_amount": total_amount,
            "cgst_amount": 0,
            "sgst_amount": 0,
            "total_tax": 0,
            "total_amount": total_amount,
            "gst_rate": 0,
        }

    divisor = 1 + (gst_rate / 100)
    net_amount = flt(total_amount / divisor, 2)
    half_rate = gst_rate / 2

    cgst_amount = flt(net_amount * (half_rate / 100), 2)
    sgst_amount = flt(net_amount * (half_rate / 100), 2)

    # Adjust net for rounding differences to ensure total matches
    total_tax = cgst_amount + sgst_amount
    net_amount = flt(total_amount - total_tax, 2)

    return {
        "net_amount": net_amount,
        "cgst_amount": cgst_amount,
        "sgst_amount": sgst_amount,
        "total_tax": total_tax,
        "total_amount": total_amount,
        "gst_rate": gst_rate,
    }


# Item codes that move money between folios rather than earning it.
#
# These are NOT revenue and must be excluded from every revenue query. The existing
# predicate `reference_doctype != 'Payment Entry' OR reference_doctype IS NULL` does not
# catch them: transfers carry no Payment Entry reference, so the `IS NULL` branch lets
# them straight through and they were being counted as sales. `Room Only Sales` and
# `Hotel Performance Analytics` happened to be safe only because they filter by item
# code, which is why those two disagreed with the EOD report for the same date.
NON_REVENUE_ITEM_CODES = (
    "PAYMENT",
    "REFUND",
    "TRANSFER",
    "TRANSFER-GROUP",
    "REFUND-TRANSFER",
    "BALANCE-TRANSFER",
    "ADVANCE-TRANSFER",
)


def revenue_item_filter(alias="ft"):
    """SQL fragment excluding money movements from a Folio Transaction revenue query.

    Usage:
        WHERE ... {filter}
    with `.format(filter=revenue_item_filter("ft"))`.
    """
    prefix = f"{alias}." if alias else ""
    codes = ", ".join(f"'{code}'" for code in NON_REVENUE_ITEM_CODES)
    return (
        f"AND ({prefix}reference_doctype != 'Payment Entry' "
        f"OR {prefix}reference_doctype IS NULL) "
        f"AND IFNULL({prefix}item, '') NOT IN ({codes})"
    )
