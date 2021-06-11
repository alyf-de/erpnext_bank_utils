from __future__ import unicode_literals
from frappe import _


def get_data():  # noqa: D103
    return [
        {
            "label": _("Bank Utils"),
            "icon": "octicon octicon-git-compare",
            "items": [
                {
                    "type": "doctype",
                    "name": "Bank Utils Settings",
                    "label": _("Settings"),
                    "description": _("Configure default values for the bank wizard.")
                },
                {
                    "type": "page",
                    "name": "bank_wizard",
                    "label": _("Bank Wizard"),
                    "description": _("Import and match transactions")
                }
            ]
        }
    ]
