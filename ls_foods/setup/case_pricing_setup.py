"""LS Foods — setup for case pricing and weight on the Sales Invoice and Sales Order.

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

Sales Order Item gets the identical layout (2026-10-01), so the two documents
are keyed the same way.

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
	PER_LB_PRICE_LIST,
	PRICED_PER_LB_FIELD,
	UNIT_PRICE_FIELD,
)
from ls_foods.share_billing import PROCESSING_ITEM_FIELD, SHARE_ITEM_FIELD
from ls_foods.share_deposit import DEPOSIT_DUE_FIELD

MODULE = "Ls Foods"
CASE_UOM = "Case"

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")

# (print format, doctype, template file). The Sales Order format lays shares out
# like the client's item build sheet; see ls_foods/share_billing.py.
PRINT_FORMATS = [
	("LS Foods Invoice", "Sales Invoice", "sales_invoice_case_weight.html"),
	("LS Foods Order", "Sales Order", "sales_order_share.html"),
]

CASE_WEIGHT_LABEL = "Case Weight (lb)"
CASE_WEIGHT_HELP = (
	"Actual pounds in one case for this shipment. Defaults to the item's nominal "
	"weight — type over it with the weighed figure. Drives Unit Price, Line Weight "
	"and the invoice's Total Weight (lb). It never changes the price."
)

ORDER_CASE_WEIGHT_HELP = (
	"Pounds in one case on this order. Defaults to the item's nominal weight — type "
	"over it with the expected or weighed figure. Drives Line Weight and Total Weight "
	"(lb); on an item with a Per Pound price, Rate = Unit Price x Case Weight."
)

PER_LB_ROW_FLAG = {
	"fieldname": PRICED_PER_LB_FIELD,
	"label": "Priced per lb",
	"fieldtype": "Check",
	"insert_after": "item_code",
	"read_only": 1,
	"hidden": 1,
	"print_hide": 1,
	"module": MODULE,
}

CUSTOM_FIELDS = {
	"Item": [
		{
			"fieldname": PRICED_PER_LB_FIELD,
			"label": "Beef / hog share",
			"fieldtype": "Check",
			"insert_after": "weight_uom",
			"description": (
				"A quarter/half/whole beef or hog. The order charges its Standard Selling "
				"price (the fixed deposit); the invoice charges hanging weight x its "
				"Per Pound price, adds the processing line and deducts the deposit."
			),
			"module": MODULE,
		},
		{
			"fieldname": PROCESSING_ITEM_FIELD,
			"label": "Processing item",
			"fieldtype": "Link",
			"options": "Item",
			"insert_after": PRICED_PER_LB_FIELD,
			"depends_on": f"eval:doc.{PRICED_PER_LB_FIELD}",
			"description": (
				"Fee line added under this share on the final invoice: "
				"hanging weight x the fee's price per lb (e.g. Processing Fee)."
			),
			"module": MODULE,
		},
	],
	"Sales Order": [
		{
			"fieldname": DEPOSIT_DUE_FIELD,
			"label": "Deposit Due",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "in_words",
			"read_only": 1,
			"depends_on": f"eval:doc.{DEPOSIT_DUE_FIELD}",
			"description": "The share lines (fixed deposit per quarter/half/whole). Compare with Advance Paid below.",
			"module": MODULE,
		},
	],
	# The same two columns as the invoice, in the same place, so an order is
	# keyed exactly like the invoice made from it — and, sharing fieldnames, the
	# typed weight carries across when the invoice is created from the order.
	"Sales Order Item": [
		{
			"fieldname": CASE_WEIGHT_FIELD,
			"label": CASE_WEIGHT_LABEL,
			"fieldtype": "Float",
			"insert_after": "stock_qty",
			"in_list_view": 1,
			"columns": 1,
			"print_hide": 0,
			"description": ORDER_CASE_WEIGHT_HELP,
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
				"What one pound works out to on this line — the item's Per Pound price, "
				"or Rate divided by Case Weight. Blank on a beef/hog share: the order "
				"charges its fixed deposit, not a price per lb."
			),
			"module": MODULE,
		},
	],
	"Sales Invoice Item": [
		PER_LB_ROW_FLAG,
		{
			"fieldname": SHARE_ITEM_FIELD,
			"label": "Processing for share",
			"fieldtype": "Link",
			"options": "Item",
			"insert_after": PRICED_PER_LB_FIELD,
			"read_only": 1,
			"print_hide": 1,
			"description": "Set on the processing line added automatically under a beef/hog share.",
			"module": MODULE,
		},
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
				"On beef/hog shares it is the item's price per lb, and "
				"Rate = Unit Price x Case Weight."
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

# Fields from an earlier design (deposit typed on the item; order priced by
# weight). The client confirmed the deposit is the share's fixed price-list
# price and the order is NOT priced by weight, so these go.
OBSOLETE_FIELDS = [
	# $/lb moved from the Item into Item Price ("Per Pound" price list), 2026-09-26.
	"Item-custom_price_per_lb",
	"Item-custom_share_deposit",
	"Sales Order Item-custom_share_deposit",
	"Sales Order Item-custom_priced_per_lb",
]

# (doctype, fieldname, property, type, value)
PROPERTY_SETTERS = [
	# --- weight_per_unit is the engine behind Case Weight, not the entry box --
	# Relabelled so the row's expanded form does not show a second, differently
	# named "Weight Per Unit" that holds the identical figure.
	("Sales Invoice Item", NATIVE_WEIGHT_FIELD, "label", "Data", "Case Weight (lb) — applied"),
	# Out of the grid: it holds the same number as the Case Weight column and
	# would render as a duplicate (and blow the 11-column budget).
	("Sales Invoice Item", NATIVE_WEIGHT_FIELD, "in_list_view", "Check", 0),
	# Delivery Note Item already allows it to be typed directly.
	("Delivery Note Item", NATIVE_WEIGHT_FIELD, "label", "Data", CASE_WEIGHT_LABEL),
	# Sales Order Item: same treatment as the invoice. Read-only because the
	# standard field is editable here, and two boxes for one number would let
	# them disagree — Case Weight (lb) is the one that is typed.
	("Sales Order Item", NATIVE_WEIGHT_FIELD, "label", "Data", "Case Weight (lb) — applied"),
	("Sales Order Item", NATIVE_WEIGHT_FIELD, "in_list_view", "Check", 0),
	("Sales Order Item", NATIVE_WEIGHT_FIELD, "read_only", "Check", 1),
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
	# --- Sales Order Item: the invoice's grid, column for column ---------------
	# Ships at 13 of the 11 units (item 3, delivery date 2, qty 1, rate 2,
	# amount 2, warehouse 2 + idx). Delivery Date and Source Warehouse leave the
	# grid — both are filled from the order header and stay in the row's
	# expanded form for the odd line that differs.
	("Sales Order Item", "total_weight", "label", "Data", "Line Weight (lb)"),
	("Sales Order Item", "total_weight", "in_list_view", "Check", 1),
	("Sales Order Item", "total_weight", "columns", "Int", 1),
	("Sales Order Item", "total_weight", "print_hide", "Check", 0),
	("Sales Order Item", "item_code", "columns", "Int", 2),
	("Sales Order Item", "qty", "columns", "Int", 1),
	("Sales Order Item", "uom", "columns", "Int", 1),
	("Sales Order Item", "uom", "in_list_view", "Check", 1),
	("Sales Order Item", "rate", "columns", "Int", 1),
	("Sales Order Item", "amount", "columns", "Int", 2),
	("Sales Order Item", "delivery_date", "in_list_view", "Check", 0),
	("Sales Order Item", "warehouse", "in_list_view", "Check", 0),
	# --- the document total --------------------------------------------------
	("Sales Invoice", "total_net_weight", "label", "Data", "Total Weight (lb)"),
	("Sales Order", "total_net_weight", "label", "Data", "Total Weight (lb)"),
	("Delivery Note", "total_net_weight", "label", "Data", "Total Weight (lb)"),
]


def run():
	_ensure_case_uom()
	_ensure_per_lb_price_list()
	for name in OBSOLETE_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True)
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	# create_custom_fields only inserts, so a property changed on an existing
	# field has to be written directly. Unit Price is read-only on every line:
	# on shares it is the item's price per lb, never typed.
	frappe.db.set_value(
		"Custom Field",
		f"Sales Invoice Item-{UNIT_PRICE_FIELD}",
		{"read_only": 1, "read_only_depends_on": None},
	)

	for doctype, fieldname, prop, proptype, value in PROPERTY_SETTERS:
		make_property_setter(doctype, fieldname, prop, value, proptype, for_doctype=False)

	install_print_format()

	for doctype in (
		"Item",
		"Sales Order",
		"Sales Order Item",
		"Sales Invoice",
		"Sales Invoice Item",
		"Delivery Note Item",
	):
		frappe.clear_cache(doctype=doctype)


def _ensure_per_lb_price_list():
	"""The selling price list that holds each item's $/lb (flyer PER LB. column).

	Never used as a transaction's price list — ls_foods reads it directly
	(``case_pricing.price_per_lb``) and multiplies by the line's weight.
	"""
	if frappe.db.exists("Price List", PER_LB_PRICE_LIST):
		return
	currency = frappe.db.get_value("Price List", "Standard Selling", "currency") or "USD"
	frappe.get_doc(
		{
			"doctype": "Price List",
			"price_list_name": PER_LB_PRICE_LIST,
			"currency": currency,
			"selling": 1,
			"enabled": 1,
		}
	).insert(ignore_permissions=True)


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
	"""Push each ``templates/*.html`` into its Print Format record.

	The database record is what actually renders — editing the template file
	alone changes nothing on screen. Keeping the file as the source of truth and
	pushing it from here means the format is versioned in git and re-applied by
	every migrate, instead of living only in the database.
	"""
	for name, doctype, template in PRINT_FORMATS:
		with open(os.path.join(TEMPLATES_DIR, template)) as f:
			html = f.read()

		if frappe.db.exists("Print Format", name):
			frappe.db.set_value("Print Format", name, {"html": html, "disabled": 0})
			continue

		frappe.get_doc(
			{
				"doctype": "Print Format",
				"name": name,
				"doc_type": doctype,
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
