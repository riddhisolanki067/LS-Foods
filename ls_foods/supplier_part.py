"""Supplier Part Number on the Purchase Invoice lines.

Purchase Order and Purchase Receipt lines already carry the standard
``supplier_part_no``; Purchase Invoice Item is the one without it. The custom
field takes the same name, so ERPNext's own item lookup fills it when an item is
picked and the PO/PR mapping copies it. The number lives on the Item's Suppliers
table, per supplier, so this hook keeps each line right when the Supplier is
changed after the items, or the order line had none.
"""

import frappe


def set_supplier_part_no(doc, method=None):
	item_codes = [row.item_code for row in doc.items if row.item_code]
	part_nos = {}
	if doc.supplier and item_codes:
		part_nos = dict(
			frappe.get_all(
				"Item Supplier",
				filters={"parenttype": "Item", "parent": ["in", item_codes], "supplier": doc.supplier},
				fields=["parent", "supplier_part_no"],
				as_list=True,
			)
		)
	for row in doc.items:
		row.supplier_part_no = part_nos.get(row.item_code)
