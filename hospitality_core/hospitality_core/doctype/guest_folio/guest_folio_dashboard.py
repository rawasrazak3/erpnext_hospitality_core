from frappe import _

def get_data():
    return {
        'fieldname': 'guest_folio',
        'transactions': [
            {
                'label': _('Billing & Payments'),
                'items': ['Sales Invoice', 'Payment Entry']
            }
        ]
    }
