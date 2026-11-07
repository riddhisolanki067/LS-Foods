"""LS Foods — editable billing / shipping address on Sales Order and Sales Invoice,
draft and submitted. Logic and the rules: ls_foods/order_address.py.

The Address links get Allow on Submit; the address text gets Allow on Submit and
loses Read Only. Only property setters, so the standard fields stay standard.

Idempotent — safe on every ``bench migrate``.
"""

import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

DOCTYPES = ("Sales Order", "Sales Invoice")
LINKS = ("customer_address", "shipping_address_name")
TEXTS = ("address_display", "shipping_address")
TEXT_HELP = "Type a one-off address here, or pick an Address above. Clear it and save to reload it from the Address."


def run():
	for dt in DOCTYPES:
		for fieldname in LINKS:
			make_property_setter(dt, fieldname, "allow_on_submit", 1, "Check", validate_fields_for_doctype=False)
		for fieldname in TEXTS:
			make_property_setter(dt, fieldname, "allow_on_submit", 1, "Check", validate_fields_for_doctype=False)
			make_property_setter(dt, fieldname, "read_only", 0, "Check", validate_fields_for_doctype=False)
			make_property_setter(dt, fieldname, "description", TEXT_HELP, "Text", validate_fields_for_doctype=False)
		frappe.clear_cache(doctype=dt)
