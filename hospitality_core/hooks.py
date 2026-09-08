app_name = "hospitality_core"
app_title = "Hospitality Core"
app_publisher = "Gift Braimah"
app_description = "Hotel Management Module"
app_email = "braimahgifted@gmail.com"
app_license = "gpl-2.0"

app_include_js = [
    "/assets/hospitality_core/js/hospitality_analytics_final.js",
    "/assets/hospitality_core/js/pos_room_selection.js",
    "/assets/hospitality_core/js/pos_invoice_auto_print.js",
    "/assets/hospitality_core/js/payment_entry_auto_print.js",
    "/assets/hospitality_core/js/pos_payment_control.js"
]

app_include_css = [
    "/assets/hospitality_core/css/print_format.css"
]


# Document Events
doc_events = {
    "Guest Folio": {
        "on_update": "hospitality_core.hospitality_core.api.folio.sync_folio_balance"
    },
    "Folio Transaction": {
        "after_save": [
            "hospitality_core.hospitality_core.api.folio.sync_folio_balance",
            "hospitality_core.hospitality_core.api.accounting.make_gl_entries_for_folio_transaction"
        ],
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
        "on_submit": "hospitality_core.api.composite_item_utils.process_composite_items_in_invoice",
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
# is idempotent, so this is safe to run repeatedly.
after_migrate = "hospitality_core.setup.setup_custom_fields"

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
        ]
    }
}

# Fixtures
fixtures = [
    {"dt": "Custom Field", "filters": [["module", "=", "Hospitality Core"]]},
    {"dt": "Property Setter", "filters": [["module", "=", "Hospitality Core"]]}
]