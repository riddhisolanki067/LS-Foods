"""Supplier Part Number on every buying item grid.

Staff can enter a line either by our Item Code or by the supplier's part number,
on Material Request, Request for Quotation, Supplier Quotation, Purchase Order,
Purchase Receipt and Purchase Invoice.

The part number lives on the Item's Suppliers table (Item Supplier), one per
supplier. Three pieces:

* ``item_query`` — the Item Code dropdown also finds items by supplier part
  number. It wraps ERPNext's own ``item_query`` (same filters, same columns), so
  everything the standard search does still applies; part-number matches are
  listed first and labelled. On a document with a Supplier, only that supplier's
  part numbers match.
* ``find_items_by_part_no`` — typing a number into the Supplier Part Number
  column fills the Item Code (see public/js/supplier_part.js).
* ``set_supplier_part_no`` (before_validate) — the saved number is always the
  one on the Item: the document supplier's, or, on Material Request / RFQ which
  have no supplier, the number the user picked if it belongs to the item, else
  the item's only part number. A number that belongs to no supplier of that item
  is never saved.

Purchase Order / Receipt, Supplier Quotation and RFQ lines carry the standard
``supplier_part_no``; Material Request and Purchase Invoice lines get a custom
field of the same name, so ERPNext's item lookup and document mapping fill it.
"""

import copy
import json
from collections import defaultdict

import frappe
from frappe import _

CORE_ITEM_QUERY = "erpnext.controllers.queries.item_query"


def _item_suppliers(filters, fields=("parent", "supplier", "supplier_part_no"), limit=None):
	filters = {"parenttype": "Item", "parentfield": "supplier_items", **filters}
	return frappe.get_all("Item Supplier", filters=filters, fields=list(fields), limit=limit)


# ---------------------------------------------------------------- Item search


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def item_query(doctype, txt, searchfield, start, page_len, filters, as_dict=False):
	from erpnext.controllers.queries import item_query as core_item_query

	if isinstance(filters, str):
		filters = json.loads(filters)
	supplier = filters.get("supplier") if isinstance(filters, dict) else None

	# ERPNext's query mutates its filters, so each call gets its own copy.
	results = core_item_query(
		doctype, txt, searchfield, start, page_len, copy.deepcopy(filters), as_dict=as_dict
	)
	txt = (txt or "").strip()
	if not txt or int(start or 0):
		return results

	part_filters = {"supplier_part_no": ["like", f"%{txt}%"]}
	if supplier:
		part_filters["supplier"] = supplier
	matches = _item_suppliers(part_filters, limit=int(page_len) * 3)
	if not matches:
		return results

	# exact number first, then numbers that start with it, then the rest
	needle = txt.casefold()
	matches.sort(
		key=lambda m: (
			m.supplier_part_no.casefold() != needle,
			not m.supplier_part_no.casefold().startswith(needle),
			m.supplier_part_no,
		)
	)
	part_of = {}
	for m in matches:
		part_of.setdefault(m.parent, m.supplier_part_no)

	# The standard query, limited to those items, so its filters (purchase item,
	# not disabled, no templates, permissions) apply to part-number hits too.
	name_filter = ["in", list(part_of)]
	scoped = copy.deepcopy(filters) if filters else {}
	if isinstance(scoped, dict):
		scoped["name"] = name_filter
	else:
		scoped.append(["Item", "name", *name_filter])
	hits = core_item_query(doctype, "", searchfield, 0, len(part_of), scoped, as_dict=as_dict)

	def name_of(row):
		return row["name"] if as_dict else row[0]

	order = list(part_of)
	hits = sorted(hits, key=lambda r: order.index(name_of(r)))
	label = _("Supplier Part {0}")
	labelled = []
	for row in hits:
		if as_dict:
			row = dict(row, supplier_part_no=label.format(part_of[row["name"]]))
		else:
			row = (row[0], label.format(part_of[row[0]]), *row[1:])
		labelled.append(row)

	seen = set(part_of)
	rest = [row for row in results if name_of(row) not in seen]
	return (labelled + rest)[: int(page_len)]


@frappe.whitelist()
def part_no_query(txt="", supplier=None, item_code=None):
	"""Part numbers for the Supplier Part Number dropdown (numbers only).

	Narrowed by the row's Item Code and the document's Supplier when set; starts-with
	matches come first, then alphabetical.
	"""
	frappe.has_permission("Item", "read", throw=True)
	txt = (txt or "").strip()
	filters = {"supplier_part_no": ["is", "set"]}
	if txt:
		filters["supplier_part_no"] = ["like", f"%{txt}%"]
	if supplier:
		filters["supplier"] = supplier
	if item_code:
		filters["parent"] = item_code
	rows = _item_suppliers(filters, fields=("parent", "supplier_part_no"))
	if not rows:
		return []
	live = set(
		frappe.get_all(
			"Item",
			filters={"name": ["in", list({r.parent for r in rows})], "disabled": 0, "has_variants": 0},
			pluck="name",
		)
	)
	needle = txt.casefold()
	numbers = {r.supplier_part_no.strip() for r in rows if r.parent in live and r.supplier_part_no.strip()}
	return sorted(numbers, key=lambda n: (not n.casefold().startswith(needle), n.casefold()))[:100]


@frappe.whitelist()
def find_items_by_part_no(part_no, supplier=None):
	"""Items whose Suppliers table has this part number (this supplier's only, if given)."""
	frappe.has_permission("Item", "read", throw=True)
	part_no = (part_no or "").strip()
	if not part_no:
		return []
	filters = {"supplier_part_no": part_no}
	if supplier:
		filters["supplier"] = supplier
	rows = _item_suppliers(filters)
	if not rows:
		return []
	items = {
		i.name: i
		for i in frappe.get_all(
			"Item",
			filters={"name": ["in", [r.parent for r in rows]], "disabled": 0, "has_variants": 0},
			fields=["name", "item_name"],
		)
	}
	return [
		{
			"item_code": r.parent,
			"item_name": items[r.parent].item_name,
			"supplier": r.supplier,
			"supplier_part_no": r.supplier_part_no,
		}
		for r in rows
		if r.parent in items
	]


# ------------------------------------------------------------ before_validate


def set_supplier_part_no(doc, method=None):
	item_codes = list({row.item_code for row in doc.items if row.item_code})
	if not item_codes:
		return
	supplier = doc.get("supplier")

	if supplier:
		part_nos = {
			r.parent: r.supplier_part_no
			for r in _item_suppliers({"parent": ["in", item_codes], "supplier": supplier})
		}
		for row in doc.items:
			row.supplier_part_no = part_nos.get(row.item_code)
		return

	# No supplier on the document (Material Request, RFQ).
	options = defaultdict(list)
	for r in _item_suppliers({"parent": ["in", item_codes], "supplier_part_no": ["is", "set"]}):
		if r.supplier_part_no not in options[r.parent]:
			options[r.parent].append(r.supplier_part_no)
	for row in doc.items:
		choices = options.get(row.item_code, [])
		typed = (row.supplier_part_no or "").strip().casefold()
		keep = next((c for c in choices if c.casefold() == typed), None) if typed else None
		row.supplier_part_no = keep or (choices[0] if len(choices) == 1 else None)
