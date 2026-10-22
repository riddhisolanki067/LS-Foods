"""LS Foods — bring a Sales Order's case weights back in line with the item master.

Why this exists
---------------
An order line takes its case weight from the item when the line is added
(``custom_case_weight`` / ``weight_per_unit``, see case_pricing.py). If the item
had no weight at that moment the line is saved with 0 lb — no Line Weight, no
Unit Price, missing from the supplier and pick-up weight reports — and once the
order is submitted nobody can type the weight in: neither field is "allow on
submit". ERPNext's own **Update Items** button cannot help either: it changes
rate and qty, and only rescales ``total_weight`` on lines that already have one
(``update_child_qty_rate``, accounts_controller.py).

What it changes
---------------
For each line where the order's weight differs from the item's current Weight
Per Unit:

    Case Weight (lb)  = item weight          (custom_case_weight + weight_per_unit)
    Line Weight (lb)  = Qty x item weight    (total_weight)
    Unit Price ($/lb) = Rate / Case Weight   — or the Per Pound price, unchanged
    Rate              = Per Pound price x weight, ONLY for items priced per lb
    Order Total Weight (lb) is re-added from the lines.

For a case-priced item the case price (Rate) and therefore the order total and
anything already paid against it are left exactly as they are — the weight only
feeds the weight columns and the $/lb shown beside the price. For an item priced
per lb the weight IS the price, so the rate moves too, and that goes through
ERPNext's standard Update Items code so totals, payment schedule, credit limit
and billing status are worked out the standard way.

Lines that are never touched: anything already delivered or invoiced (the
weight now lives on that Delivery Note / Invoice), beef/hog shares (their weight
is the hanging weight, known only at invoicing), non-stock lines (fees carry no
weight) and items whose master has no weight.

Every change on a submitted order is saved as a normal document Version, so the
form's timeline shows old and new values row by row.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt

from ls_foods.case_pricing import (
	CASE_WEIGHT_FIELD,
	NATIVE_WEIGHT_FIELD,
	UNIT_PRICE_FIELD,
	is_share,
	price_per_lb,
)


def _changes(doc):
	"""The lines of ``doc`` whose weight would change, as plain dicts for the dialog."""
	on_date = doc.get("transaction_date")
	out = []
	for row in doc.get("items") or []:
		if not row.item_code or flt(row.delivered_qty) or flt(row.billed_amt):
			continue
		item = frappe.get_cached_value(
			"Item", row.item_code, ["is_stock_item", NATIVE_WEIGHT_FIELD], as_dict=True
		)
		if not item or not cint(item.is_stock_item) or is_share(row.item_code):
			continue

		new_weight = flt(item.get(NATIVE_WEIGHT_FIELD))
		old_weight = flt(row.get(CASE_WEIGHT_FIELD)) or flt(row.get(NATIVE_WEIGHT_FIELD))
		if not new_weight or abs(new_weight - old_weight) < 0.0001:
			continue

		per_lb = price_per_lb(row.item_code, doc.get("customer"), on_date)
		new_rate = flt(row.rate)
		if per_lb:
			new_rate = flt(
				per_lb * new_weight * (1 - flt(row.discount_percentage) / 100), row.precision("rate")
			)
		out.append(
			{
				"row": row.name,
				"idx": row.idx,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"qty": flt(row.qty),
				"old_weight": old_weight,
				"new_weight": new_weight,
				"old_rate": flt(row.rate),
				"new_rate": new_rate,
				"per_lb": per_lb,
				"discount_percentage": flt(row.discount_percentage),
			}
		)
	return out


def _check(doc):
	doc.check_permission("write")
	if doc.docstatus == 2:
		frappe.throw(_("{0} is cancelled.").format(doc.name))
	if doc.status in ("Closed", "Completed"):
		frappe.throw(_("{0} is {1}; weights can no longer be changed.").format(doc.name, doc.status))


@frappe.whitelist()
def get_weight_changes(sales_order):
	"""For the form's dialog: the lines whose weight differs from the item master."""
	doc = frappe.get_doc("Sales Order", sales_order)
	_check(doc)
	return _changes(doc)


@frappe.whitelist()
def apply_weight_changes(sales_order, rows=None):
	"""Copy the item master's weight onto the chosen lines (all differing lines if ``rows`` is empty)."""
	doc = frappe.get_doc("Sales Order", sales_order)
	_check(doc)

	rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
	changes = [c for c in _changes(doc) if not rows or c["row"] in rows]
	if not changes:
		return {"updated": 0}

	if doc.docstatus == 0:
		# A draft is simply saved: the case_pricing hooks recompute everything.
		for c in changes:
			row = _row(doc, c["row"])
			row.set(CASE_WEIGHT_FIELD, c["new_weight"])
			row.set(NATIVE_WEIGHT_FIELD, c["new_weight"])
		doc.save()
		return {"updated": len(changes)}

	# Per-lb items: the price follows the weight. Standard Update Items does the
	# money side; every line is passed back as it is, or it would be deleted.
	if any(c["new_rate"] != c["old_rate"] for c in changes):
		from erpnext.controllers.accounts_controller import update_child_qty_rate

		new_rates = {c["row"]: c["new_rate"] for c in changes}
		trans_items = [
			{
				"docname": r.name,
				"item_code": r.item_code,
				"qty": r.qty,
				"rate": new_rates.get(r.name, r.rate),
				"uom": r.uom,
				"conversion_factor": r.conversion_factor,
				"delivery_date": r.delivery_date,
			}
			for r in doc.items
		]
		update_child_qty_rate("Sales Order", json.dumps(trans_items, default=str), doc.name)
		doc = frappe.get_doc("Sales Order", sales_order)
		# Update Items reads the new rate against the OLD list price and books
		# the gap as a margin or a discount. Here the list price itself moved
		# (Per Pound price x new weight), so put it right and keep the line's
		# own discount, as apply_per_lb_pricing does.
		for c in changes:
			if c["per_lb"]:
				r = _row(doc, c["row"])
				r.price_list_rate = flt(c["per_lb"] * c["new_weight"], r.precision("price_list_rate"))
				r.discount_percentage = c["discount_percentage"]
				r.discount_amount = flt(r.price_list_rate - flt(r.rate), r.precision("discount_amount"))
				r.margin_type = ""
				r.margin_rate_or_amount = 0
				r.rate_with_margin = 0

	for c in changes:
		row = _row(doc, c["row"])
		row.set(CASE_WEIGHT_FIELD, c["new_weight"])
		row.set(NATIVE_WEIGHT_FIELD, c["new_weight"])
		row.total_weight = flt(c["new_weight"] * flt(row.stock_qty), row.precision("total_weight"))
		row.set(
			UNIT_PRICE_FIELD,
			c["per_lb"] or flt(flt(row.rate) / c["new_weight"], row.precision(UNIT_PRICE_FIELD)),
		)
	doc.total_net_weight = sum(flt(r.total_weight) for r in doc.items)

	doc.flags.ignore_validate_update_after_submit = True
	doc.save()
	doc.add_comment(
		"Info",
		_("Case weights updated from the item master: {0}").format(
			", ".join(
				f"row {c['idx']} {c['item_code']} {c['old_weight']:g} → {c['new_weight']:g} lb" for c in changes
			)
		),
	)
	out = {"updated": len(changes)}
	# A lighter weight on a per-lb item lowers the order below what was already
	# paid. ERPNext allows that; say so, the credit has to be dealt with.
	overpaid = flt(doc.advance_paid) - flt(doc.rounded_total or doc.grand_total)
	if overpaid > 0.005:
		out["overpaid"] = overpaid
	return out


@frappe.whitelist()
def apply_weight_changes_bulk(sales_orders):
	"""List view action: update every differing line on each order. Returns per-order results."""
	names = frappe.parse_json(sales_orders) if isinstance(sales_orders, str) else sales_orders
	out = {}
	for name in names or []:
		try:
			out[name] = apply_weight_changes(name)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			out[name] = {"error": str(e)}
	return out


def _row(doc, name):
	return next(r for r in doc.items if r.name == name)
