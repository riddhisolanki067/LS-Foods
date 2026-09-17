"""LS Foods — setup for case pricing and weight on the Sales Invoice.

Items are stocked and sold in **Cases**. Nearly everything the client asked for
is already in ERPNext under names that do not look like what they are, so most
of this file is Property Setters that expose and rename standard fields rather
than new ones.

    Client's column      Where it comes from
    -------------------  ---------------------------------------------------
    Case Weight (lb)     custom_case_weight -> mirrored to weight_per_unit
    Unit Price           custom_unit_price  (rate / case weight)
    Case Price           rate
    Line Weight (lb)     total_weight       (qty x weight_per_unit, native)
    Total Weight (lb)    total_net_weight   (document total, native)

Only two fields are new, and only because ERPNext has nowhere to put them:
``custom_case_weight`` is the **entry box** for pounds in a case, and
``custom_unit_price`` is the per-pound figure. Everything else is standard.

Why Case Weight is not just ``weight_per_unit`` itself: that field sits at index
67 on Sales Invoice Item, after ``rate`` and ``amount``, and Frappe renders grid
columns in field order — so it could only ever appear as the **last** column,
which is the wrong place for the one field somebody has to fill in. The custom
field holds the same number where we want it, and ``mirror_case_weight`` copies
it into ``weight_per_unit`` on before_validate so every native weight
calculation still drives the totals.

Grid budget
-----------
Frappe gives a child table **11 column units including the row number**
(``grid.js:setup_visible_columns``). Sales Invoice Item ships at **13**, so
ERPNext is already dropping columns off the right-hand edge. The layout below is
set deliberately and comes to exactly 11:

    idx 1 + item_code 2 + qty 1 + case weight 1 + unit price 1
          + line weight 1 + rate 1 + amount 2  =  10, + uom 1 = 11

``warehouse`` and ``uom`` come out where needed to make room — every item sells
in its own stock UOM here, so the UOM column repeats "Case" on every line and
earns its place least. All of it is Property Setters: revert any from Customize
Form without touching code.

Idempotent — safe on every ``bench migrate``.
"""

import os

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from ls_foods.case_pricing import (
	ALLOW_ZERO_RATE_FIELD,
	CASE_WEIGHT_FIELD,
	NATIVE_WEIGHT_FIELD,
	UNIT_PRICE_FIELD,
)

MODULE = "Ls Foods"
CASE_UOM = "Case"

PRINT_FORMAT = "LS Foods Invoice"
TEMPLATE = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
	"templates",
	"sales_invoice_case_weight.html",
)

CASE_WEIGHT_LABEL = "Case Weight (lb)"
CASE_WEIGHT_HELP = (
	"Actual pounds in one case for this shipment. Defaults to the item's nominal "
	"weight — type over it with the weighed figure. Drives Unit Price, Line Weight "
	"and the invoice's Total Weight (lb). It never changes the price."
)

CUSTOM_FIELDS = {
	"Sales Invoice Item": [
		{
			"fieldname": CASE_WEIGHT_FIELD,
			"label": CASE_WEIGHT_LABEL,
			"fieldtype": "Float",
			"insert_after": "stock_qty",
			"in_list_view": 1,
			"columns": 1,
			"print_hide": 0,
			"description": CASE_WEIGHT_HELP,
			"module": MODULE,
		},
		{
			"fieldname": UNIT_PRICE_FIELD,
			"label": "Unit Price",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": CASE_WEIGHT_FIELD,
			"read_only": 1,
			"in_list_view": 1,
			"columns": 1,
			"print_hide": 0,
			"description": (
				"What one pound works out to on this line — Rate divided by Case Weight. "
				"Recalculates when the case weight is changed."
			),
			"module": MODULE,
		}
	],
	"Sales Invoice": [
		{
			"fieldname": ALLOW_ZERO_RATE_FIELD,
			"label": "Allow Zero Rate",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "update_stock",
			"print_hide": 1,
			"description": (
				"Lets this invoice be submitted with unpriced rows — samples, "
				"replacements, goodwill. Leave unticked and ls_foods blocks a submit "
				"where any row has a quantity but no rate."
			),
			"module": MODULE,
		}
	],
}

# (doctype, fieldname, property, type, value)
PROPERTY_SETTERS = [
	# --- weight_per_unit is the engine behind Case Weight, not the entry box --
	# Relabelled so the row's expanded form does not show a second, differently
	# named "Weight Per Unit" that holds the identical figure.
	("Sales Invoice Item", NATIVE_WEIGHT_FIELD, "label", "Data", "Case Weight (lb) — applied"),
	# Out of the grid: it holds the same number as the Case Weight column and
	# would render as a duplicate (and blow the 11-column budget).
	("Sales Invoice Item", NATIVE_WEIGHT_FIELD, "in_list_view", "Check", 0),
	# Sales Order Item and Delivery Note Item already allow it to be typed
	# directly, and have room for it in their own grids.
	("Sales Order Item", NATIVE_WEIGHT_FIELD, "label", "Data", CASE_WEIGHT_LABEL),
	("Delivery Note Item", NATIVE_WEIGHT_FIELD, "label", "Data", CASE_WEIGHT_LABEL),
	# --- the line weight -----------------------------------------------------
	("Sales Invoice Item", "total_weight", "label", "Data", "Line Weight (lb)"),
	("Sales Invoice Item", "total_weight", "in_list_view", "Check", 1),
	("Sales Invoice Item", "total_weight", "columns", "Int", 1),
	("Sales Invoice Item", "total_weight", "print_hide", "Check", 0),
	# --- make room (see the module docstring) --------------------------------
	("Sales Invoice Item", "item_code", "columns", "Int", 2),
	("Sales Invoice Item", "qty", "columns", "Int", 1),
	("Sales Invoice Item", "uom", "columns", "Int", 1),
	("Sales Invoice Item", "uom", "in_list_view", "Check", 1),
	("Sales Invoice Item", "rate", "columns", "Int", 1),
	("Sales Invoice Item", "amount", "columns", "Int", 2),
	("Sales Invoice Item", "warehouse", "in_list_view", "Check", 0),
	("Sales Invoice Item", "stock_qty", "in_list_view", "Check", 0),
	("Sales Invoice Item", "stock_uom_rate", "in_list_view", "Check", 0),
	# --- the document total --------------------------------------------------
	("Sales Invoice", "total_net_weight", "label", "Data", "Total Weight (lb)"),
	("Sales Order", "total_net_weight", "label", "Data", "Total Weight (lb)"),
	("Delivery Note", "total_net_weight", "label", "Data", "Total Weight (lb)"),
]


def run():
	_ensure_case_uom()
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)

	for doctype, fieldname, prop, proptype, value in PROPERTY_SETTERS:
		make_property_setter(doctype, fieldname, prop, value, proptype, for_doctype=False)

	install_print_format()

	for doctype in ("Sales Invoice", "Sales Invoice Item", "Sales Order Item", "Delivery Note Item"):
		frappe.clear_cache(doctype=doctype)


def _ensure_case_uom():
	"""Seed ``Case`` as a whole-number UOM.

	Whole-number matters: ``validate_uom_is_integer`` then refuses half a case.
	Safe to create — no *global* UOM Conversion Factor exists for Case, so
	``Item.validate_uom_conversion_factor`` cannot silently overwrite anything.
	"""
	if frappe.db.exists("UOM", CASE_UOM):
		if not frappe.db.get_value("UOM", CASE_UOM, "must_be_whole_number"):
			frappe.db.set_value("UOM", CASE_UOM, "must_be_whole_number", 1)
		return

	frappe.get_doc({"doctype": "UOM", "uom_name": CASE_UOM, "must_be_whole_number": 1}).insert(
		ignore_permissions=True
	)


def install_print_format():
	"""Push ``templates/sales_invoice_case_weight.html`` into the Print Format record.

	The database record is what actually renders — editing the template file
	alone changes nothing on screen. Keeping the file as the source of truth and
	pushing it from here means the format is versioned in git and re-applied by
	every migrate, instead of living only in the database.
	"""
	with open(TEMPLATE) as f:
		html = f.read()

	if frappe.db.exists("Print Format", PRINT_FORMAT):
		frappe.db.set_value("Print Format", PRINT_FORMAT, {"html": html, "disabled": 0})
		return

	frappe.get_doc(
		{
			"doctype": "Print Format",
			"name": PRINT_FORMAT,
			"doc_type": "Sales Invoice",
			"module": MODULE,
			"standard": "No",
			"custom_format": 1,
			"print_format_type": "Jinja",
			"font_size": 9,
			"margin_top": 12,
			"margin_bottom": 12,
			"html": html,
		}
	).insert(ignore_permissions=True)
