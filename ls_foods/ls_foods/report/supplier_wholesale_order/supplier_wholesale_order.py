# Copyright (c) 2026, Riddhi and contributors
# For license information, please see license.txt

"""Supplier Wholesale Order — one supplier's items, grouped by pallet label.

Replaces the client's per-supplier "Purchase Order" document. Each label is
one pick-up location; the label numbers follow the order the pallets are
stacked in the semi trailer, NOT the flyer's location numbers, so the user
clicks the locations in the Label Order filter in pallet order (first click =
Label #1).

Supplier is optional: left empty, every supplier gets its own section (labels
numbered from #1 per supplier, then a supplier total), items without a supplier
last under "No Vendor".

A location that has orders for the supplier but was not clicked still gets a
label, after the clicked ones, so nothing ordered drops off the sheet.

Lines come from the Seasonal Supplier Quantities query (draft and submitted orders,
stock items only, vendor = the item's first Item Supplier row), so the two
reports always agree.
"""

import frappe
from frappe import _
from frappe.utils import flt

from ls_foods.ls_foods.report.seasonal_supplier_quantities.seasonal_supplier_quantities import (
	NO_VENDOR,
	get_lines,
	get_location_filter,
)

NO_LOCATION = "No Pick-Up Location"


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Description"), "fieldname": "item_name", "fieldtype": "Data", "width": 420},
		{"label": _("Product Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 120},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "precision": 2, "width": 80},
		{"label": _("Weight (lbs.)"), "fieldname": "weight", "fieldtype": "Float", "precision": 2, "width": 110},
		{"label": _("Total Weight"), "fieldname": "total_weight", "fieldtype": "Float", "precision": 2, "width": 120},
	]


def get_label_locations(picked, used):
	"""Clicked locations first, in click order; then any other location that has
	orders, in flyer order (Home Delivery last, as in the sample)."""
	locations = {
		l.name: l
		for l in frappe.get_all(
			"Pick-Up Location", fields=["name", "location_number", "location_name", "city", "is_home_delivery"]
		)
	}
	order = [p for p in picked if p in locations]
	rest = sorted(
		(u for u in used if u not in order and u != NO_LOCATION),
		key=lambda n: (
			flt(locations[n].is_home_delivery) if n in locations else 2,
			locations[n].location_number if n in locations else 999,
		),
	)
	order += rest
	if NO_LOCATION in used:
		order.append(NO_LOCATION)
	return order, locations


def label_title(n, name, location):
	if not location:
		return _("Label #{0} ({1})").format(n, _(name))
	title = location.location_name or name
	if location.city:
		title = f"{title}, {location.city}"
	return _("Label #{0} ({1})").format(n, title)


def get_data(filters):
	lines = get_lines(filters)
	if filters.supplier:
		lines = [d for d in lines if d.vendor == filters.supplier]

	# vendor -> location -> item_code -> sums
	vendors = {}
	for d in lines:
		items = vendors.setdefault(d.vendor or "", {}).setdefault(d.pick_up_location or NO_LOCATION, {})
		g = items.get(d.item_code)
		if not g:
			g = items[d.item_code] = frappe._dict(item_name=d.item_name, item_code=d.item_code, qty=0, total_weight=0)
		g.qty += flt(d.qty)
		g.total_weight += flt(d.total_weight)

	picked = get_location_filter({"pick_up_location": filters.label_order})
	all_vendors = not filters.supplier

	rows = []
	grand_qty = grand_weight = 0
	for vendor in sorted(vendors, key=lambda v: (not v, v)):
		vendor_name = vendor or _(NO_VENDOR)
		if all_vendors:
			rows.append({"item_name": vendor_name, "is_vendor_row": 1})
		qty, weight = add_labels(rows, vendors[vendor], picked)
		if all_vendors:
			rows.append(
				{
					"item_name": _("{0} TOTAL").format(vendor_name),
					"qty": qty,
					"total_weight": flt(weight, 2),
					"is_total_row": 1,
				}
			)
			rows.append({})
		grand_qty += qty
		grand_weight += weight

	if rows:
		rows.append(
			{"item_name": _("GRAND TOTAL"), "qty": grand_qty, "total_weight": flt(grand_weight, 2), "is_total_row": 1}
		)
	return rows


def add_labels(rows, groups, picked):
	"""One supplier's labels (numbered from #1 for each supplier's truck);
	returns the supplier's qty and weight."""
	order, locations = get_label_locations(picked, groups)
	total_qty = total_weight = 0
	label_no = 0
	for name in order:
		items = groups.get(name)
		if not items:
			continue  # a clicked location with nothing from this supplier keeps no label
		label_no += 1
		rows.append({"item_name": label_title(label_no, name, locations.get(name)), "is_label_row": 1})
		qty = weight = 0
		for g in sorted(items.values(), key=lambda g: g.item_code):
			rows.append(
				{
					"item_name": g.item_name,
					"item_code": g.item_code,
					"qty": g.qty,
					"weight": flt(g.total_weight / g.qty, 2) if g.qty else 0,
					"total_weight": flt(g.total_weight, 2),
				}
			)
			qty += g.qty
			weight += g.total_weight
		rows.append({"item_name": _("TOTALS"), "qty": qty, "total_weight": flt(weight, 2), "is_total_row": 1})
		rows.append({})
		total_qty += qty
		total_weight += weight
	return total_qty, total_weight
