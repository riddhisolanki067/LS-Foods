"""LS Foods — custom beef / hog shares: the order, the deposit and the final bill.

How the client bills a share (confirmed by the client, 2026-09-26)
------------------------------------------------------------------
1. **Order.** The customer orders 1 quarter, half or whole beef and pays a
   FIXED deposit: $600 / $1,200 / $2,400 (hogs: $200 per half). The deposit
   never depends on weight or price.
2. **Final invoice.** Once the hanging weight is known, two charges are shown —
   hanging weight x price per lb, and hanging weight x processing fee per lb —
   and the deposit is deducted to show what is still owed.

How that maps onto standard ERPNext
-----------------------------------
- The share item's **Item Price is the deposit** (the order sheet's PRICE
  column). So the Sales Order line prices at $2,400 with no custom code, and
  the order's deposit is collected as an advance against it
  (``share_deposit.make_deposit_entry``).
- On the invoice made from that order, the same line is re-priced by weight
  (``case_pricing.apply_per_lb_pricing``) — it becomes the hanging-weight
  charge — and :func:`sync_processing_rows` adds the processing line right
  under it, blank: staff type its qty and rate from the processor's bill. The deposit comes off as the advance (Get Advances), so the invoice
  is simply part-paid.
- Nothing is billed twice: the deposit is money received, not a sales line.

:func:`invoice_view` / :func:`order_view` shape a document for the print
formats, which lay it out like the client's item build sheet.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from ls_foods.case_pricing import CASE_WEIGHT_FIELD, NATIVE_WEIGHT_FIELD, PRICED_PER_LB_FIELD

PROCESSING_ITEM_FIELD = "custom_processing_item"  # Item: which fee goes with this share
SHARE_ITEM_FIELD = "custom_share_item"  # Sales Invoice Item: this row is the processing for that share

# Deposits are counted in the client's own units: quarters of a beef, halves of a hog.
SHARE_UNITS = {
	"Beef": ("Quarter Beef Deposit", {"whole": 4, "half": 2, "quarter": 1}),
	"Pork": ("Half Hog Deposit", {"whole": 2, "half": 1}),
}


# ---------------------------------------------------------------------------
# Invoice: the processing line
# ---------------------------------------------------------------------------


def sync_processing_rows(doc, method=None):
	"""Sales Invoice ``before_validate`` — one processing line under each share line.

	A new processing line comes in BLANK — no qty, no rate — and staff type both
	from the processor's bill (client's call, 2026-10-28: the fee is not a fixed
	$/lb and weight x rate never matched the bill to the cent). Whatever is typed
	is never recalculated. Lines whose share has been removed are dropped.

	ERPNext refuses a zero-qty line on save, so the check is lifted while the
	only zero-qty lines are processing lines; :func:`validate_processing_rows`
	makes sure they are filled in before submit.
	"""
	rows = doc.get("items") or []
	existing = {}
	for row in rows:
		if row.get(SHARE_ITEM_FIELD):
			existing.setdefault(row.get(SHARE_ITEM_FIELD), []).append(row)

	ordered = []
	for row in rows:
		if row.get(SHARE_ITEM_FIELD):
			continue  # re-placed under its share below
		ordered.append(row)

		if not cint(row.get(PRICED_PER_LB_FIELD)):
			continue
		fee_item = frappe.get_cached_value("Item", row.item_code, PROCESSING_ITEM_FIELD)
		if not fee_item:
			continue

		matches = existing.get(row.item_code) or []
		fee = matches.pop(0) if matches else None
		if not fee:
			# price_list_rate / rate set to 0 (not None) so the controller's
			# get_item_details does not fill in the fee item's list price.
			fee = doc.append(
				"items",
				{
					"item_code": fee_item,
					SHARE_ITEM_FIELD: row.item_code,
					"qty": 0,
					"price_list_rate": 0,
					"rate": 0,
				},
			)
			doc.items.remove(fee)
			fee.warehouse = row.warehouse
			fee.cost_center = row.cost_center
		ordered.append(fee)

	doc.items = ordered
	for idx, row in enumerate(doc.items, start=1):
		row.idx = idx

	# Lift ERPNext's zero-qty check only while every zero-qty line is a blank
	# processing line; undo our own lift on the next save if that stops being true.
	if doc.flags.get("ls_processing_zero_qty"):
		doc.flags.allow_zero_qty = doc.flags.ls_processing_zero_qty = False
	zero_qty = [row for row in doc.items if not flt(row.qty)]
	if zero_qty and all(row.get(SHARE_ITEM_FIELD) for row in zero_qty):
		doc.flags.allow_zero_qty = doc.flags.ls_processing_zero_qty = True


def validate_processing_rows(doc, method=None):
	"""Sales Invoice ``before_submit`` — a processing line must have its qty and rate typed in."""
	blank = [row for row in doc.items if row.get(SHARE_ITEM_FIELD) and not (flt(row.qty) and flt(row.rate))]
	if not blank:
		return
	rows = "<br>".join(
		_("Row {0}: {1} (Qty {2}, Rate {3})").format(row.idx, frappe.bold(row.item_code), flt(row.qty), flt(row.rate))
		for row in blank
	)
	frappe.throw(
		_("Enter the processing Qty and Rate from the processor's bill before submitting.") + f"<br><br>{rows}",
		title=_("Processing not filled in"),
	)


def apply_share_deposit(doc, method=None):
	"""Sales Invoice ``validate`` — a new share invoice takes the deposit off.

	The share is invoiced on its own, after the order's other items (Backorders
	& Invoicing leaves its deposit on the order). Made from the order with
	Create > Sales Invoice, the invoice would not pull the deposit in by itself
	(automatic allocation is off), so on its first save the payments made on the
	order are allocated here. It runs after the controller's validate, when the
	share is re-priced and the processing line priced, and the totals are
	worked out again with the advances in. Only once: whatever staff change on the Advances table
	afterwards stays.
	"""
	if not doc.is_new() or doc.docstatus != 0 or doc.get("is_return") or doc.get("is_pos"):
		return
	if doc.get("advances") or cint(doc.get("allocate_advances_automatically")):
		return
	if not any(row.get("so_detail") and cint(row.get(PRICED_PER_LB_FIELD)) for row in doc.items):
		return
	doc.set_advances()
	doc.calculate_taxes_and_totals()


# ---------------------------------------------------------------------------
# Deposit units (quarters / halves) — for the printed deposit line
# ---------------------------------------------------------------------------


def share_units(item_code):
	"""(label, units) for a share item, e.g. ("Quarter Beef Deposit", 4) for a whole beef.

	Read from the item's variant attributes ("Whole Beef", "Half Hog", …), falling
	back to its name ("1/2", "1/4"). Returns (None, 0) when it cannot tell — the
	print then shows the deposit as a single amount.
	"""
	group = frappe.get_cached_value("Item", item_code, "item_group")
	label, units = SHARE_UNITS.get(group, (None, {}))
	if not label:
		return None, 0

	words = " ".join(
		frappe.get_all("Item Variant Attribute", filters={"parent": item_code}, pluck="attribute_value")
		+ [frappe.get_cached_value("Item", item_code, "item_name") or ""]
	).lower()
	words = words.replace("1/4", "quarter").replace("1/2", "half")
	for size in ("whole", "half", "quarter"):
		if size in words and size in units:
			return label, units[size]
	return None, 0


def _deposit_for(row):
	"""The deposit taken for this share: its Sales Order line's amount."""
	if row.get("so_detail"):
		return flt(frappe.db.get_value("Sales Order Item", row.so_detail, "amount"))
	return 0.0


# ---------------------------------------------------------------------------
# Print views
# ---------------------------------------------------------------------------


def invoice_view(doc):
	"""Group a Sales Invoice into share blocks + other lines, for the print format."""
	fees = {}
	for row in doc.items:
		if row.get(SHARE_ITEM_FIELD):
			fees.setdefault(row.get(SHARE_ITEM_FIELD), []).append(row)

	shares, others = [], []
	for row in doc.items:
		if row.get(SHARE_ITEM_FIELD):
			continue
		if not cint(row.get(PRICED_PER_LB_FIELD)):
			others.append(row)
			continue

		fee = (fees.get(row.item_code) or [None]).pop(0) if fees.get(row.item_code) else None
		subtotal = flt(row.amount) + flt(fee.amount if fee else 0)
		deposit = _deposit_for(row)
		label, units = share_units(row.item_code)
		shares.append(
			frappe._dict(
				row=row,
				fee=fee,
				weight=flt(row.qty) * (flt(row.get(CASE_WEIGHT_FIELD)) or flt(row.get(NATIVE_WEIGHT_FIELD))),
				subtotal=subtotal,
				deposit=deposit,
				deposit_label=label or "Deposit",
				deposit_units=units or 1,
				deposit_each=deposit / (units or 1),
				balance=subtotal - deposit,
			)
		)

	held = held_shares(doc)
	return frappe._dict(
		shares=shares,
		others=others,
		held=held,
		held_deposit=sum(h.deposit for h in held),
		shares_total=sum(s.subtotal for s in shares),
		shares_balance=sum(s.balance for s in shares),
		deposits=sum(s.deposit for s in shares),
		others_total=sum(flt(r.amount) for r in others),
		# Cases + shares; a processing line's qty is pounds, not units.
		total_units=sum(flt(r.qty) for r in doc.items if not r.get(SHARE_ITEM_FIELD)),
	)


def held_shares(doc):
	"""Shares of the invoice's orders that are NOT on this invoice and not invoiced yet.

	The Backorders & Invoicing screen invoices an order's other items first; the
	share follows on its own invoice once the hanging weight is known. Its
	deposit stays on the order meanwhile, and the first invoice's print says so.
	"""
	orders = list({r.sales_order for r in doc.items if r.get("sales_order")})
	if not orders or doc.get("is_return"):
		return []
	rows = frappe.get_all(
		"Sales Order Item",
		filters={"parent": ["in", orders], "parenttype": "Sales Order"},
		fields=["name", "parent", "item_code", "item_name", "qty", "returned_qty", "amount"],
		order_by="parent asc, idx asc",
	)
	rows = [r for r in rows if r.item_code and cint(frappe.get_cached_value("Item", r.item_code, PRICED_PER_LB_FIELD))]
	if not rows:
		return []
	on_this = {r.so_detail for r in doc.items if r.get("so_detail")}
	taken = {}
	for r in frappe.get_all(
		"Sales Invoice Item",
		filters={"so_detail": ["in", [r.name for r in rows]], "docstatus": ["<", 2], "parent": ["!=", doc.name or ""]},
		fields=["so_detail", "qty"],
	):
		taken[r.so_detail] = taken.get(r.so_detail, 0) + flt(r.qty)

	out = []
	for r in rows:
		if r.name in on_this:
			continue
		pending = flt(r.qty) - flt(r.returned_qty) - taken.get(r.name, 0)
		if pending <= 0.0001:
			continue
		out.append(
			frappe._dict(
				sales_order=r.parent,
				item_code=r.item_code,
				item_name=r.item_name,
				qty=pending,
				deposit=flt(r.amount) / flt(r.qty) * pending if flt(r.qty) else 0,
			)
		)
	return out


def order_view(doc):
	"""Group a Sales Order into share deposits + other lines, for the print format."""
	shares, others = [], []
	for row in doc.items:
		if cint(frappe.get_cached_value("Item", row.item_code, PRICED_PER_LB_FIELD)):
			label, units = share_units(row.item_code)
			shares.append(
				frappe._dict(
					row=row,
					deposit_label=label or "Deposit",
					deposit_units=flt(row.qty) * (units or 1),
					deposit_each=flt(row.amount) / (flt(row.qty) * (units or 1) or 1),
				)
			)
		else:
			others.append(row)
	return frappe._dict(
		shares=shares,
		others=others,
		deposits=sum(flt(s.row.amount) for s in shares),
		others_total=sum(flt(r.amount) for r in others),
	)
