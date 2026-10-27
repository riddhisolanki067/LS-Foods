"""LS Foods — Backorders & Invoicing screen (page ``backorder-invoicing``).

Why this exists
---------------
When a delivery comes in short (10 cases of Coconut Palm Sugar and 2 of Hard
Red Wheat did not arrive), every affected order used to be opened one by one:
Create > Sales Invoice, delete the missing lines from the invoice, save. The
screen lists the open order lines of all orders for a pick-up location /
customer / date range in one table, takes a table of backordered items (an
item with or without a short quantity), and creates one invoice per order for
everything else in one go. This module does the server side: the open lines
and the invoices.

How the invoices are made
-------------------------
Exactly the way the Sales Order's own Create > Sales Invoice makes them —
ERPNext's ``make_sales_invoice`` mapper, given only the chosen order lines
(its ``filtered_children`` argument) — so prices, case weights, per-lb
repricing, taxes, the link back to the order line (billed amount, % billed)
and the deposits all come out the same as an invoice made by hand. Only the
quantity of a partly backordered line is changed afterwards. Deposits and
payments made against the order are pulled in ("allocate advances
automatically"), so the invoice shows what is still owed.

What a backorder is
-------------------
Nothing extra is stored. A backordered line is simply an order line that is
not (fully) invoiced yet: the order stays "To Bill", and the screen lists
the line again until it is invoiced once the goods arrive.
Lines already on a DRAFT invoice are counted as taken, so the same goods are
never put on two invoices.

Beef / hog shares
-----------------
The screen invoices the OTHER items of an order that has a share; the share
itself is never put on these invoices. It is billed later, once the hanging
weight is known, on its own invoice made from the order (Create > Sales
Invoice: hanging weight x $/lb plus the processing line, share_billing.py,
less the deposit). So the share's DEPOSIT stays on the order: only what was
paid beyond the deposits of the shares still to come is taken off the first
invoice, and its print shows the deposit held for the share
(share_billing.held_shares).

Left out of the screen: orders that are Closed, Completed or On Hold.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from ls_foods.case_pricing import is_share

# Below this, a quantity is rounding noise.
EPS = 0.0001


@frappe.whitelist()
def get_open_orders(
	pick_up_location=None,
	customer=None,
	item_code=None,
	from_date=None,
	to_date=None,
	sales_orders=None,
):
	"""Open order lines still to be invoiced, grouped by order, oldest order first."""
	frappe.has_permission("Sales Order", "read", throw=True)

	filters = [
		["docstatus", "=", 1],
		["status", "not in", ["Closed", "Completed", "On Hold"]],
		["per_billed", "<", 99.99],
	]
	if pick_up_location:
		filters.append(["custom_pick_up_location", "=", pick_up_location])
	if customer:
		filters.append(["customer", "=", customer])
	if from_date:
		filters.append(["transaction_date", ">=", getdate(from_date)])
	if to_date:
		filters.append(["transaction_date", "<=", getdate(to_date)])
	names = frappe.parse_json(sales_orders) if isinstance(sales_orders, str) else sales_orders
	if names:
		filters.append(["name", "in", names])

	orders = frappe.get_list(
		"Sales Order",
		filters=filters,
		fields=[
			"name",
			"customer",
			"customer_name",
			"transaction_date",
			"custom_pick_up_location as pick_up_location",
			"rounded_total",
			"grand_total",
			"advance_paid",
			"per_billed",
			"currency",
		],
		order_by="transaction_date asc, name asc",
		limit_page_length=0,
	)
	if not orders:
		return {"orders": []}

	by_name = {o.name: o for o in orders}
	items = frappe.get_all(
		"Sales Order Item",
		filters={"parent": ["in", list(by_name)], "parenttype": "Sales Order"},
		fields=[
			"name",
			"parent",
			"idx",
			"item_code",
			"item_name",
			"item_group",
			"uom",
			"qty",
			"returned_qty",
			"rate",
			"amount",
			"custom_case_weight",
		],
		order_by="parent asc, idx asc",
		limit_page_length=0,
	)
	invoiced = _invoiced_qty([i.name for i in items])
	drafts = _draft_invoices(list(by_name))
	locations = dict(frappe.get_all("Pick-Up Location", fields=["name", "location_name"], as_list=True))

	lines = {}
	for row in items:
		if not row.item_code or not flt(row.qty):
			continue
		done = invoiced.get(row.name, {})
		pending = flt(row.qty) - flt(row.returned_qty) - flt(done.get("billed")) - flt(done.get("draft"))
		if pending <= EPS:
			continue
		stock = cint(frappe.get_cached_value("Item", row.item_code, "is_stock_item"))
		lines.setdefault(row.parent, []).append(
			{
				"so_detail": row.name,
				"idx": row.idx,
				"item_code": row.item_code,
				"item_name": row.item_name,
				"item_group": row.item_group,
				"uom": row.uom,
				"qty": flt(row.qty),
				"invoiced": flt(done.get("billed")) + flt(done.get("draft")),
				"pending": pending,
				"rate": flt(row.rate),
				"case_weight": flt(row.custom_case_weight),
				# Delivery Charge / Late Fee / FREE: they go with the goods,
				# they are never backordered themselves.
				"is_fee": 0 if stock else 1,
			}
		)
		if is_share(row.item_code):
			# Shown, never invoiced here: its deposit stays on the order.
			lines[row.parent][-1].update(
				is_share=1, deposit_per_unit=flt(row.amount) / flt(row.qty) if flt(row.qty) else 0
			)

	out = []
	for o in orders:
		# Only a share left (its other items invoiced): nothing for this screen.
		if not any(not l["is_fee"] and not l.get("is_share") for l in lines.get(o.name, [])):
			continue
		if item_code and not any(l["item_code"] == item_code for l in lines[o.name]):
			continue
		o.pick_up_location_name = locations.get(o.pick_up_location) or o.pick_up_location or ""
		o.order_total = flt(o.rounded_total or o.grand_total)
		o.lines = lines[o.name]
		# Partly invoiced already: what is left was backordered last time.
		o.partly_invoiced = 1 if flt(o.per_billed) > 0 or any(l["invoiced"] for l in o.lines) else 0
		o.draft_invoices = drafts.get(o.name, [])
		out.append(o)
	return {"orders": out}


@frappe.whitelist()
def create_invoice(sales_order, lines, submit=0):
	"""One invoice for ``sales_order`` holding only ``lines`` ({so_detail: qty}).

	Returns ``{"name", "status", "grand_total", "outstanding",
	"error"}``. A failed submit leaves the draft in place and says why (no
	stock, …).
	"""
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	frappe.has_permission("Sales Invoice", "create", throw=True)
	lines = frappe.parse_json(lines) if isinstance(lines, str) else lines
	lines = {k: flt(v) for k, v in (lines or {}).items() if flt(v) > EPS}
	if not lines:
		return {"error": _("Nothing to invoice.")}

	try:
		so = frappe.get_doc("Sales Order", sales_order)
		so.check_permission("read")
		if so.docstatus != 1 or so.status in ("Closed", "Completed", "On Hold"):
			frappe.throw(_("{0} is {1}.").format(so.name, so.status))

		# Re-check against the database: someone may have invoiced these lines
		# since the lines were fetched.
		invoiced = _invoiced_qty([row.name for row in so.items])
		held_deposit = 0.0  # deposits of shares that stay on the order
		for row in so.items:
			done = invoiced.get(row.name, {})
			pending = flt(row.qty) - flt(row.returned_qty) - flt(done.get("billed")) - flt(done.get("draft"))
			share = is_share(row.item_code)
			if share and pending > EPS:
				held_deposit += flt(row.amount) / flt(row.qty) * pending
			if row.name not in lines:
				continue
			if share:
				frappe.throw(
					_("Row {0} {1}: a share is invoiced from the order once the hanging weight is known.").format(
						row.idx, row.item_code
					)
				)
			if lines[row.name] > pending + EPS:
				frappe.throw(
					_("Row {0} {1}: only {2} left to invoice, {3} asked.").format(
						row.idx, row.item_code, f"{pending:g}", f"{lines[row.name]:g}"
					)
				)

		si = make_sales_invoice(so.name, args={"filtered_children": list(lines)})
		mapped = {r.so_detail for r in si.items}
		if missing := set(lines) - mapped:
			frappe.throw(_("{0} line(s) could not be put on the invoice.").format(len(missing)))
		for row in si.items:
			row.qty = lines[row.so_detail]
		# Deposits / payments made against the order come off the invoice.
		si.allocate_advances_automatically = 1
		si.insert()
		# ERPNext works out the totals BEFORE it pulls the advances in
		# (AccountsController.validate), so the first save leaves Total Advance
		# at 0 and the whole amount outstanding. A second save counts them.
		if si.advances:
			si.save()
		if si.advances and held_deposit > EPS:
			_keep_share_deposits(si, held_deposit)
		frappe.db.commit()
	except Exception as e:
		frappe.db.rollback()
		frappe.clear_messages()
		return {"error": _message(e)}

	out = {"name": si.name, "status": "Draft"}
	if cint(submit):
		try:
			frappe.db.savepoint("ls_invoice_submit")
			si.submit()
			out["status"] = "Submitted"
		except Exception as e:
			frappe.db.rollback(save_point="ls_invoice_submit")
			frappe.clear_messages()
			si.reload()
			out["error"] = _("Saved as draft, not submitted: {0}").format(_message(e))
	out.update(grand_total=flt(si.rounded_total or si.grand_total), outstanding=flt(si.outstanding_amount))
	return out


def _keep_share_deposits(si, held_deposit):
	"""Leave the deposits of shares still to come unallocated on the order.

	ERPNext takes every payment on the order off this invoice. A share not on
	it yet keeps its deposit for its own invoice: only what was paid beyond
	those deposits is applied here. Allocation is then fixed by hand (automatic
	allocation would undo it on save).
	"""
	available = sum(flt(a.advance_amount) for a in si.advances)
	allocated = sum(flt(a.allocated_amount) for a in si.advances)
	left = min(allocated, max(available - held_deposit, 0))
	if left >= allocated - EPS:
		return
	si.allocate_advances_automatically = 0
	for a in si.advances:
		a.allocated_amount = min(flt(a.advance_amount), left)
		left -= a.allocated_amount
	si.save()


def _invoiced_qty(so_details):
	"""{so_detail: {"billed": qty on submitted invoices, "draft": qty on draft invoices}}."""
	if not so_details:
		return {}
	rows = frappe.get_all(
		"Sales Invoice Item",
		filters={"so_detail": ["in", so_details], "docstatus": ["<", 2]},
		fields=["so_detail", "docstatus", "sum(qty) as qty"],
		group_by="so_detail, docstatus",
		limit_page_length=0,
	)
	out = {}
	for r in rows:
		out.setdefault(r.so_detail, {})["billed" if r.docstatus == 1 else "draft"] = flt(r.qty)
	return out


def _draft_invoices(sales_orders):
	"""{sales_order: [draft invoice names]} — shown on the order so nobody doubles up."""
	rows = frappe.get_all(
		"Sales Invoice Item",
		filters={"sales_order": ["in", sales_orders], "docstatus": 0},
		fields=["sales_order", "parent"],
		group_by="sales_order, parent",
		limit_page_length=0,
	)
	out = {}
	for r in rows:
		out.setdefault(r.sales_order, []).append(r.parent)
	return out


def _message(e):
	"""The readable part of an exception: the frappe.throw text, without HTML."""
	from frappe.utils import strip_html

	return strip_html(str(e) or e.__class__.__name__)
