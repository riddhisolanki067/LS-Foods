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
  under it. The deposit comes off as the advance (Get Advances), so the invoice
  is simply part-paid.
- Nothing is billed twice: the deposit is money received, not a sales line.

:func:`invoice_view` / :func:`order_view` shape a document for the print
formats, which lay it out like the client's item build sheet.
"""

import frappe
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

	Qty = share qty x hanging weight (lb), so the fee always follows the weight
	that was typed. A processing line keeps any rate typed on it (hog processing
	runs $1-$2/lb); a new one takes the fee item's price-list rate. Lines whose
	share has been removed are dropped. Runs after ``apply_per_lb_pricing`` so
	the share's weight is settled.
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

		weight = flt(row.get(CASE_WEIGHT_FIELD)) or flt(row.get(NATIVE_WEIGHT_FIELD))
		matches = existing.get(row.item_code) or []
		fee = matches.pop(0) if matches else None
		if not fee:
			fee = doc.append("items", {"item_code": fee_item, SHARE_ITEM_FIELD: row.item_code})
			doc.items.remove(fee)
			fee.warehouse = row.warehouse
			fee.cost_center = row.cost_center
		fee.qty = flt(row.qty) * weight
		ordered.append(fee)

	doc.items = ordered
	for idx, row in enumerate(doc.items, start=1):
		row.idx = idx


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

	return frappe._dict(
		shares=shares,
		others=others,
		shares_total=sum(s.subtotal for s in shares),
		shares_balance=sum(s.balance for s in shares),
		deposits=sum(s.deposit for s in shares),
		others_total=sum(flt(r.amount) for r in others),
		# Cases + shares; a processing line's qty is pounds, not units.
		total_units=sum(flt(r.qty) for r in doc.items if not r.get(SHARE_ITEM_FIELD)),
	)


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
