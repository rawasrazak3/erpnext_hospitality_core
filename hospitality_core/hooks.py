app_name = "hospitality_core"
app_title = "Hospitality Core"
app_publisher = "Gift Braimah"
app_description = "Hotel Management Module"
app_email = "braimahgifted@gmail.com"
app_license = "gpl-2.0"

import os as _os


def _asset(path):
    """/assets/hospitality_core/<path> with a version stamp from the file's mtime.

    Frappe versions only *.bundle.* files; plain files like these were linked with no
    version, and the web server tells browsers to keep /assets for a year. So a changed
    script never reached a browser that had cached the old one — the Hotel POS sat on
    "Loading inventory" for staff still running last week's front_desk.js. The stamp
    changes whenever the file does, so a normal page reload picks up the new code.
    """
    try:
        stamp = int(_os.path.getmtime(_os.path.join(_os.path.dirname(__file__), "public", path)))
    except OSError:
        stamp = 0
    return f"/assets/hospitality_core/{path}?v={stamp}"


app_include_js = [
    _asset("js/hospitality_analytics_final.js"),
    _asset("js/pos_room_selection.js"),
    _asset("js/pos_invoice_auto_print.js"),
    _asset("js/payment_entry_auto_print.js"),
    _asset("js/pos_payment_control.js"),
    _asset("js/room_details.js"),
    _asset("js/front_desk.js"),
]

app_include_css = [
    _asset("css/print_format.css"),
    _asset("css/room_details.css"),
    _asset("css/front_desk.css"),
]


# Document Events
_CLEAR_HOLIDAY_CACHE = (
    "hospitality_core.hospitality_core.doctype.hotel_room_type.hotel_room_type"
    ".clear_holiday_cache"
)

doc_events = {
    # Holiday dates are cached for tariff lookups, so editing the calendar has to
    # invalidate them or a newly added holiday would keep pricing as a weekday.
    "Holiday List": {
        "on_update": _CLEAR_HOLIDAY_CACHE,
        "on_trash": _CLEAR_HOLIDAY_CACHE,
    },
    "Hospitality Accounting Settings": {
        "on_update": _CLEAR_HOLIDAY_CACHE,
    },
    "Guest Folio": {
        "on_update": "hospitality_core.hospitality_core.api.folio.sync_folio_balance"
    },
    # Folio Transaction is a child table and "after_save" is not a Frappe event, so this
    # never ran — every caller syncs the balance itself. The GL posting that used to sit
    # here (accounting.make_gl_entries_for_folio_transaction) is deliberately gone: a
    # stay's revenue and GST are booked by the Sales Invoice made at check-out
    # (api/invoicing.py), and posting them from the folio as well would count them twice.
    "Folio Transaction": {
        "on_trash": "hospitality_core.hospitality_core.api.folio.sync_folio_balance"
    },
    "POS Invoice": {
        "on_submit": [
            "hospitality_core.hospitality_core.api.pos_bridge.process_room_charge",
            "hospitality_core.hospitality_core.api.accounting.redirect_pos_income_to_suspense",
            "hospitality_core.hospitality_core.api.accounting.reclassify_pos_taxes",
            "hospitality_core.hospitality_core.api.stock.post_pos_invoice_stock",
            "hospitality_core.api.composite_item_utils.process_composite_items_in_invoice"
        ],
        "on_cancel": [
            "hospitality_core.hospitality_core.api.pos_bridge.void_room_charge",
            "hospitality_core.hospitality_core.api.accounting.redirect_pos_income_to_suspense",
            "hospitality_core.hospitality_core.api.accounting.reclassify_pos_taxes",
            "hospitality_core.hospitality_core.api.stock.cancel_pos_invoice_stock",
            "hospitality_core.api.composite_item_utils.process_composite_items_in_invoice"
        ]
    },
    "Payment Entry": {
        "before_insert": "hospitality_core.hospitality_core.api.payment_bridge.adjust_payment_date",
        "on_submit": "hospitality_core.hospitality_core.api.payment_bridge.process_payment_entry",
        "on_cancel": "hospitality_core.hospitality_core.api.payment_bridge.process_payment_entry"
    },
    "CRM Call Log": {
        "after_insert": "hospitality_core.hospitality_core.api.telephony.link_call_to_enquiry"
    },
    "Sales Invoice": {
        "before_submit": "hospitality_core.hospitality_core.api.stock.disable_stock_for_consolidated_pos_sales_invoice",
        "on_submit": [
            "hospitality_core.api.composite_item_utils.process_composite_items_in_invoice",
            "hospitality_core.hospitality_core.api.invoicing.settle_parked_advances"
        ],
        "on_cancel": [
            "hospitality_core.api.composite_item_utils.process_composite_items_in_invoice",
            "hospitality_core.hospitality_core.api.invoicing.cancel_sales_invoice"
        ]
    }
    # NOTE: doc_events for "Folio Ledger Adjustment" were removed — no such DocType
    # exists in this or any installed app, and no table exists on any site. The
    # handlers (api.folio.process_ledger_adjustment / cancel_ledger_adjustment) are
    # kept so the hook can be restored if that DocType is ever shipped.
}

after_install = "hospitality_core.setup.after_install"

# Custom fields are declared once in setup.CUSTOM_FIELDS and re-synced on every migrate,
# so adding a field there is all that is needed — no patch per batch. create_custom_fields
# is idempotent, so this is safe to run repeatedly. after_migrate also re-applies the
# single-workspace sidebar on sites that opted in (setup.apply_single_workspace).
after_migrate = "hospitality_core.setup.after_migrate"

# Scheduled Tasks
# changed daily audit to run at 2 PM (14:00) per requirements
scheduler_events = {
    "cron": {
        "0 14 * * *": [
            "hospitality_core.hospitality_core.api.night_audit.run_daily_audit"
        ],
        "0 8 * * *": [
            "hospitality_core.hospitality_core.api.pos_bridge.close_all_open_pos_sessions"
        ],
        # Release expired tentative holds so the rooms go back on sale. Hourly, because a
        # hold that has lapsed is inventory the sales team cannot sell until it clears.
        "0 * * * *": [
            "hospitality_core.hospitality_core.doctype.hotel_booking.hotel_booking.release_expired_holds"
        ],
        # Close the paperwork on stays whose check-out time has passed and that owe
        # nothing. Rooms are already free at that point; this never charges anything.
        "10 * * * *": [
            "hospitality_core.hospitality_core.api.front_desk.auto_check_out"
        ],
        # Look every morning for anything where bookings, stays, rooms, bills and
        # enquiries disagree, and record it (Booking Health Check shows it too).
        "0 7 * * *": [
            "hospitality_core.hospitality_core.api.integrity.daily_check"
        ]
    }
}

# Fixtures
fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Hospitality Core"]]},
    {"dt": "Property Setter", "filters": [["module", "=", "Hospitality Core"]]}
]