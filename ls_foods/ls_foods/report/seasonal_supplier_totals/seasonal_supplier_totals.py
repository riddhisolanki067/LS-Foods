# Copyright (c) 2026, Riddhi and contributors
# For license information, please see license.txt

"""Seasonal Supplier Totals — the "Totals" tab of the client's workbook as its
own report: quantity and weight per vendor per pick-up location.

Same lines as Seasonal Supplier Quantities (draft + submitted orders, stock
items only, vendor = the item's first Item Supplier row), so the two reports
always agree. Orders with no pick-up location are not in any location row.
"""

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

from ls_foods.ls_foods.report.seasonal_supplier_quantities.seasonal_supplier_quantities import (
	NO_VENDOR,
	get_lines,
	get_location_filter,
	get_locations,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{"label": _("Vendor"), "fieldname": "vendor", "fieldtype": "Data", "width": 220},
		{"label": _("Location"), "fieldname": "location", "fieldtype": "Data", "width": 260},
		{"label": _("Total Qty"), "fieldname": "qty", "fieldtype": "Float", "precision": 2, "width": 110},
		{"label": _("Total Weight"), "fieldname": "total_weight", "fieldtype": "Float", "precision": 2, "width": 120},
	]


def get_data(filters):
	lines = get_lines(filters)
	if filters.supplier:
		lines = [d for d in lines if d.vendor == filters.supplier]
	picked = get_location_filter(filters)

	sums = defaultdict(lambda: [0.0, 0.0])
	vendors = set()
	for d in lines:
		if not d.pick_up_location or (picked and d.pick_up_location not in picked):
			continue
		vendors.add(d.vendor or "")
		s = sums[(d.vendor or "", d.pick_up_location)]
		s[0] += flt(d.qty)
		s[1] += flt(d.total_weight)

	# Home Delivery first, then by flyer number; a disabled location that still
	# has orders must not drop out
	locations = [l.name for l in get_locations()]
	locations += sorted({loc for _v, loc in sums if loc not in locations})
	if picked:
		locations = [l for l in locations if l in picked]

	rows = []
	grand_qty = grand_weight = 0
	for vendor in sorted(vendors, key=lambda v: (not v, v)):
		vendor_name = vendor or _(NO_VENDOR)
		qty = weight = 0
		for loc in locations:
			q, w = sums.get((vendor, loc), (0.0, 0.0))
			if filters.hide_zero_rows and not q:
				continue
			rows.append({"vendor": vendor_name, "location": loc, "qty": q, "total_weight": flt(w, 2)})
			qty += q
			weight += w
		rows.append(
			{
				"vendor": _("{0} Totals").format(vendor_name),
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
			{"vendor": _("GRAND TOTAL"), "qty": grand_qty, "total_weight": flt(grand_weight, 2), "is_total_row": 1}
		)
	return rows
