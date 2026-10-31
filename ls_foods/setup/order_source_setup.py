"""LS Foods — Order Source: how an order reached the office, on Sales Order and Sales Invoice.

A custom Select rather than ERPNext's own ``source``: that is a Link to the CRM's
Lead Source master, on a tab further down, and means where a customer came from.
The same fieldname on both means the invoice takes it from the order when it is
made. It can be set on a submitted order, since the orders already on file were
entered before the field existed.

Idempotent — safe on every ``bench migrate``.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Ls Foods"
FIELD = {
	"fieldname": "custom_order_source",
	"label": "Order Source",
	"fieldtype": "Select",
	"options": "\nEmail\nMail\nPhone\nVoicemail\nOther",
	"allow_on_submit": 1,
	"in_standard_filter": 1,
	"module": MODULE,
}


def run():
	create_custom_fields(
		{
			"Sales Order": [{**FIELD, "insert_after": "custom_pick_up_location"}],
			"Sales Invoice": [{**FIELD, "insert_after": "due_date"}],
		},
		ignore_validate=True,
	)
	for doctype in ("Sales Order", "Sales Invoice"):
		frappe.clear_cache(doctype=doctype)
