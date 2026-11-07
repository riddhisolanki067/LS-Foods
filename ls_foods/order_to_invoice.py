"""Sales Order header fields carried onto its Sales Invoice.

ERPNext's mapper copies a field only when both doctypes have it under the same
name. Project, Cost Center (the client's "Department"), Price List, Currency,
Source Warehouse and Order Source already share their names; Pick-Up Location
does not (Sales Order ``custom_pick_up_location``, Sales Invoice
``custom_pickup_location``), so it never came across.

* ``make_sales_invoice`` (override of ERPNext's Create > Sales Invoice) sets
  every field from the order, so the new invoice shows them before it is saved.
* ``fill_from_order`` (Sales Invoice before_insert) fills the ones still empty,
  for invoices made another way (Get Items From > Sales Order, Backorders &
  Invoicing). It never overwrites what the user chose on the new invoice.

An invoice made from several orders takes a field only when those orders agree.
"""

import frappe
from erpnext.selling.doctype.sales_order import sales_order as erpnext_sales_order

# Sales Order field -> Sales Invoice field
FIELDS = {
	"custom_pick_up_location": "custom_pickup_location",
	"custom_order_source": "custom_order_source",
	"project": "project",
	"cost_center": "cost_center",
	"selling_price_list": "selling_price_list",
	"currency": "currency",
	"set_warehouse": "set_warehouse",
}


def order_values(si):
	"""{invoice field: value} the invoice's orders agree on."""
	orders = list({row.sales_order for row in si.get("items") or [] if row.get("sales_order")})
	if not orders:
		return {}
	so_meta, si_meta = frappe.get_meta("Sales Order"), frappe.get_meta("Sales Invoice")
	fields = {s: i for s, i in FIELDS.items() if so_meta.has_field(s) and si_meta.has_field(i)}
	rows = frappe.get_all("Sales Order", filters={"name": ["in", orders]}, fields=list(fields))
	values = {}
	for so_field, si_field in fields.items():
		found = {row[so_field] for row in rows if row[so_field]}
		if len(found) == 1:
			values[si_field] = found.pop()
	return values


@frappe.whitelist()
def make_sales_invoice(source_name, target_doc=None, ignore_permissions=False, args=None):
	si = erpnext_sales_order.make_sales_invoice(
		source_name, target_doc=target_doc, ignore_permissions=ignore_permissions, args=args
	)
	si.update(order_values(si))
	return si


def fill_from_order(si, method=None):
	for fieldname, value in order_values(si).items():
		if not si.get(fieldname):
			si.set(fieldname, value)
