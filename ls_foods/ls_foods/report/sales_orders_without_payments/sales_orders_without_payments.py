"""Submitted Sales Orders with no payment linked, and what the customer has unallocated.

An order counts as linked when Advance Paid is above zero or a Payment Entry
references it. The available column is per customer: one payment shows on each of
that customer's unlinked orders.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return columns(), rows(filters)


def columns():
	return [
		{"label": _("Sales Order"), "fieldname": "sales_order", "fieldtype": "Link", "options": "Sales Order", "width": 170},
		{"label": _("Amended From"), "fieldname": "amended_from", "fieldtype": "Link", "options": "Sales Order", "width": 170},
		{"label": _("Customer"), "fieldname": "customer", "fieldtype": "Link", "options": "Customer", "width": 90},
		{"label": _("Customer Name"), "fieldname": "customer_name", "fieldtype": "Data", "width": 180},
		{"label": _("Date"), "fieldname": "transaction_date", "fieldtype": "Date", "width": 100},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 130},
		{"label": _("Order Total"), "fieldname": "order_total", "fieldtype": "Currency", "width": 110},
		{"label": _("Customer Unallocated"), "fieldname": "unallocated", "fieldtype": "Currency", "width": 150},
		{"label": _("Unallocated Payments"), "fieldname": "payments", "fieldtype": "Data", "width": 220},
	]


def rows(filters):
	conditions, values = "", {}
	for field in ("company", "customer"):
		if filters.get(field):
			conditions += f" and so.{field} = %({field})s"
			values[field] = filters[field]
	if filters.get("amended_only"):
		conditions += " and ifnull(so.amended_from, '') != ''"

	orders = frappe.db.sql(
		f"""select so.name as sales_order, so.amended_from, so.customer, so.customer_name,
		       so.transaction_date, so.status, so.company,
		       if(so.rounded_total > 0, so.rounded_total, so.grand_total) as order_total
		  from `tabSales Order` so
		 where so.docstatus = 1
		   and so.status != 'Closed'
		   and ifnull(so.advance_paid, 0) = 0
		   and not exists (
		       select 1 from `tabPayment Entry Reference` per
		        where per.reference_doctype = 'Sales Order'
		          and per.reference_name = so.name
		          and per.docstatus = 1
		          and per.allocated_amount > 0
		   )
		   {conditions}
		 order by so.transaction_date desc, so.name desc""",
		values,
		as_dict=True,
	)

	available = {}
	for payment in frappe.get_all(
		"Payment Entry",
		filters={
			"docstatus": 1,
			"payment_type": "Receive",
			"party_type": "Customer",
			"unallocated_amount": [">", 0],
			"party": ["in", list({o.customer for o in orders}) or [""]],
		},
		fields=["name", "party", "company", "unallocated_amount"],
	):
		available.setdefault((payment.company, payment.party), []).append(payment)

	for order in orders:
		payments = available.get((order.company, order.customer), [])
		order.unallocated = sum(p.unallocated_amount for p in payments)
		order.payments = ", ".join(p.name for p in payments)

	if filters.get("with_payments_only"):
		orders = [o for o in orders if o.unallocated]
	return orders
