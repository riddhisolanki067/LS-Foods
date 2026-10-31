"""LS Foods — Supplier Part Number column on the Purchase Invoice item grid.

Grid budget is 11 units including the row number (see case_pricing_setup). The
grid ships full (item_code 3, qty 2, rate 3, amount 2), so qty and rate each give
up a unit for the new column:

    idx 1 + item_code 3 + supplier_part_no 2 + qty 1 + rate 2 + amount 2  =  11

Idempotent — safe on every ``bench migrate``.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

DOCTYPE = "Purchase Invoice Item"


def run():
	create_custom_fields(
		{
			DOCTYPE: [
				{
					"fieldname": "supplier_part_no",
					"label": "Supplier Part Number",
					"fieldtype": "Data",
					"insert_after": "item_code",
					"read_only": 1,
					"in_list_view": 1,
					"columns": 2,
					"module": "Ls Foods",
				}
			]
		},
		update=True,
	)
	for fieldname, columns in (("qty", 1), ("rate", 2)):
		make_property_setter(DOCTYPE, fieldname, "columns", columns, "Int", validate_fields_for_doctype=False)
	frappe.clear_cache(doctype=DOCTYPE)
