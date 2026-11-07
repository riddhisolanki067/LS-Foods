"""LS Foods — editable Supplier Part Number column on every buying item grid.

Staff enter a line by Item Code or by supplier part number (see
ls_foods/supplier_part.py), so the column is editable and sits right after Item
Code on all six grids. Purchase Order / Receipt, Supplier Quotation and RFQ items
have the standard field (hidden, read-only) — property setters show it; Material
Request and Purchase Invoice items get a custom field of the same name.

Grid budget is 11 units including the row number (see case_pricing_setup), and
every grid already ships full, so each one gives up 2 units:

    Material Request        item 2 + part 2 + required by 2 + qty 1 + warehouse 2 + uom 1
    Request for Quotation   item 2 + part 2 + required by 2 + qty 1 + uom 1 + warehouse 2
    Supplier Quotation      item 2 + part 2 + qty 1 + uom 1 + rate 2 + amount 2
    Purchase Order          item 2 + part 2 + qty 1 + uom 1 + rate 2 + amount 2
                            (Required By leaves the grid; each line still takes
                             the header's date and it stays editable in the row)
    Purchase Receipt        item 2 + part 2 + accepted qty 1 + rejected qty 1 + rate 2 + amount 2
    Purchase Invoice        item 3 + part 2 + qty 1 + rate 2 + amount 2

Idempotent — safe on every ``bench migrate``.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

PART_FIELD = {
	"fieldname": "supplier_part_no",
	"label": "Supplier Part Number",
	"fieldtype": "Data",
	"insert_after": "item_code",
	"read_only": 0,
	"in_list_view": 1,
	"columns": 2,
	"module": "Ls Foods",
}

CUSTOM_FIELD_DOCTYPES = ("Material Request Item", "Purchase Invoice Item")
STANDARD_FIELD_DOCTYPES = (
	"Request for Quotation Item",
	"Supplier Quotation Item",
	"Purchase Order Item",
	"Purchase Receipt Item",
)

# (doctype, fieldname, property, value, property_type)
GRID = [
	("Material Request Item", "item_code", "columns", 2, "Int"),
	("Material Request Item", "warehouse", "columns", 2, "Int"),
	("Request for Quotation Item", "qty", "columns", 1, "Int"),
	("Request for Quotation Item", "uom", "columns", 1, "Int"),
	("Supplier Quotation Item", "qty", "columns", 1, "Int"),
	("Supplier Quotation Item", "uom", "columns", 1, "Int"),
	("Purchase Order Item", "schedule_date", "in_list_view", 0, "Check"),
	("Purchase Receipt Item", "item_code", "columns", 2, "Int"),
	("Purchase Receipt Item", "qty", "columns", 1, "Int"),
	("Purchase Invoice Item", "qty", "columns", 1, "Int"),
	("Purchase Invoice Item", "rate", "columns", 2, "Int"),
]


def run():
	create_custom_fields({dt: [dict(PART_FIELD)] for dt in CUSTOM_FIELD_DOCTYPES}, update=True)

	for dt in STANDARD_FIELD_DOCTYPES:
		for prop, value, ptype in (
			("hidden", 0, "Check"),
			("read_only", 0, "Check"),
			("in_list_view", 1, "Check"),
			("columns", 2, "Int"),
		):
			make_property_setter(dt, "supplier_part_no", prop, value, ptype, validate_fields_for_doctype=False)

	for dt, fieldname, prop, value, ptype in GRID:
		make_property_setter(dt, fieldname, prop, value, ptype, validate_fields_for_doctype=False)

	for dt in CUSTOM_FIELD_DOCTYPES + STANDARD_FIELD_DOCTYPES:
		frappe.clear_cache(doctype=dt)
