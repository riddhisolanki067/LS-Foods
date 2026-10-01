"""LS Foods — case pricing and weight on the Sales Invoice and Sales Order.

The model
---------
Items are **stocked and sold in Cases** — ``Item.stock_uom = Case``. There is no
fixed number of pounds in a case and no attempt is made to pretend there is: the
weight of a case is a property of the shipment, so it is typed on the invoice
line.

    Item master : Stock UOM = Case
                  Weight UOM = Lb
                  Weight Per Unit = nominal lb in one case   (a default only)

    Invoice line: Qty              = number of cases
                  Case Weight (lb) = ACTUAL lb in one case, entered by the user
                  Unit Price       = Rate / Case Weight  ->  $ per lb
                  Rate             = price of one case
                  Amount           = Qty x Rate           (weight never moves it)
                  Line Weight (lb) = Qty x Case Weight
    Document    : Total Weight (lb)

Because the stock unit IS the case, there are no UOM conversions anywhere: no
conversion factors to maintain, no second price list, nothing to keep in step.
Qty is cases, stock is cases, the price is per case.

How it hangs together
---------------------
``weight_per_unit`` is ERPNext's "weight of one stock unit" — which here already
means pounds per case. Feed it and ``total_weight`` (Qty x weight) and
``total_net_weight`` (the document total) both follow natively; nothing in this
module recalculates them.

The user does not type into ``weight_per_unit`` directly, for one practical
reason: it sits at index 67 in Sales Invoice Item, after ``rate`` and ``amount``,
and Frappe renders grid columns in field order — so it can only ever appear as
the last column, which is the wrong place for the field someone has to fill in.
``custom_case_weight`` is the same number in a position we control (just after
Qty/UOM), and ``mirror_case_weight`` copies it across on **before_validate**, in
time for ERPNext's own weight and total calculations to pick it up.

Why the typed weight survives the save
--------------------------------------
``weight_per_unit`` is listed in ``force_item_fields``
(``accounts_controller.py:90``), which reads as though the item master always
wins. It does not. The value forced back comes from
``get_item_details.py:486``::

    "weight_per_unit": args.get("weight_per_unit") or item.get("weight_per_unit")

and ``args`` is ``item.as_dict()`` — the row. A line carrying a weight keeps it;
a blank line gets the item's nominal weight as its default. Verified on a saved
invoice rather than assumed.

The Sales Order carries the same columns and the same hooks (2026-10-01):
``custom_case_weight`` / ``custom_unit_price`` exist on Sales Order Item under
the same fieldnames, so the weight typed on an order maps onto the invoice made
from it. "Invoice" below reads "order" just as well.

⚠ The rule the weight total rests on: **every item must have Weight UOM = Lb**.
``calculate_total_net_weight`` (``taxes_and_totals.py:665``) adds the lines'
``total_weight`` with **no unit conversion**, so one item in Kg silently
corrupts the invoice total.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate, nowdate

CASE_WEIGHT_FIELD = "custom_case_weight"
UNIT_PRICE_FIELD = "custom_unit_price"
ALLOW_ZERO_RATE_FIELD = "custom_allow_zero_rate"

# Item flag for beef/hog shares (fixed deposit on the order, hanging weight on
# the invoice). The $/lb itself is an Item Price in the "Per Pound" price list.
PRICED_PER_LB_FIELD = "custom_priced_per_lb"
PER_LB_PRICE_LIST = "Per Pound"

NATIVE_WEIGHT_FIELD = "weight_per_unit"


def mirror_case_weight(doc, method=None):
	"""``before_validate`` — keep Case Weight (lb) and ``weight_per_unit`` as one number.

	Runs before the controller so ERPNext's own machinery does the arithmetic:
	``get_item_details`` keeps the row's weight, ``total_weight`` becomes
	Qty x weight, and ``total_net_weight`` sums the lines. Nothing here
	recomputes any of that.

	Push only. The opposite direction — showing the item's nominal weight in the
	column when the user has typed nothing — cannot happen here: on a new row
	``weight_per_unit`` is still empty at before_validate, because
	``get_item_details`` does not run until the controller's own validate. That
	half is done in :func:`set_unit_price`, by which time it is populated.
	"""
	for row in doc.get("items") or []:
		typed = flt(row.get(CASE_WEIGHT_FIELD))
		if typed:
			row.set(NATIVE_WEIGHT_FIELD, typed)


def price_per_lb(item_code, customer=None, on_date=None):
	"""The item's $/lb from the **Per Pound** price list, or 0 if it has none.

	The client keeps two prices per item, both as ordinary Item Prices loaded by
	Data Import:

	    Standard Selling  the case price (flyer PRICE column) — and, for a beef/hog
	                      share, its fixed DEPOSIT ($600 / $1,200 / $2,400)
	    Per Pound         the $/lb (flyer PER LB. column)

	The Per Pound price is stored in the item's own stock UOM (Case) and the list
	*name* says it is per pound: an Item Price in UOM "Pound" is refused unless
	Pound is in the item's UOM table with a FIXED lb-per-case factor
	(item_price.py), and these cases vary in weight.

	A customer-specific Per Pound price wins over the general one; validity dates
	are honoured.
	"""
	if not item_code:
		return 0.0
	cache_key = ("ls_foods_price_per_lb", item_code, customer or "", str(on_date or ""))
	cached = frappe.local.cache.get(cache_key) if hasattr(frappe.local, "cache") else None
	if cached is not None:
		return cached

	on_date = getdate(on_date or nowdate())
	rows = frappe.get_all(
		"Item Price",
		filters={"price_list": PER_LB_PRICE_LIST, "item_code": item_code, "selling": 1},
		fields=["price_list_rate", "customer", "valid_from", "valid_upto"],
		order_by="valid_from desc, creation desc",
	)
	rows = [
		r
		for r in rows
		if (not r.customer or r.customer == customer)
		and (not r.valid_from or getdate(r.valid_from) <= on_date)
		and (not r.valid_upto or getdate(r.valid_upto) >= on_date)
	]
	rows.sort(key=lambda r: 0 if r.customer else 1)
	price = flt(rows[0].price_list_rate) if rows else 0.0
	if hasattr(frappe.local, "cache"):
		frappe.local.cache[cache_key] = price
	return price


def is_share(item_code):
	"""Beef/hog share: ordered at a fixed deposit, invoiced by hanging weight."""
	return cint(frappe.get_cached_value("Item", item_code, PRICED_PER_LB_FIELD)) if item_code else 0


def _line_weight(row):
	"""Pounds in ONE unit on this line: typed case/hanging weight, else nominal."""
	return (
		flt(row.get(CASE_WEIGHT_FIELD))
		or flt(row.get(NATIVE_WEIGHT_FIELD))
		or flt(frappe.get_cached_value("Item", row.item_code, NATIVE_WEIGHT_FIELD))
	)


def apply_per_lb_pricing(doc, method=None):
	"""``before_validate`` (Sales Order + Sales Invoice) — Rate = $/lb x weight.

	For every line whose item has a **Per Pound** price:

	    Unit Price ($/lb)  = the Per Pound price — read-only, never typed
	    Case Weight (lb)   = weight of ONE unit (a case, or a share's hanging
	                         weight); falls back to the item's nominal weight
	    Rate (case price)  = Unit Price x Case Weight
	    Amount             = Qty x Rate

	so a heavy or light case is charged for what it actually weighs (client's
	rule, 2026-09-26). Lines with no Per Pound price keep the case price from
	Standard Selling, and Unit Price is then derived (:func:`set_unit_price`).

	One exception: a beef/hog **share on a Sales Order** stays at its Standard
	Selling price, which is the fixed deposit — the weight is not known yet. The
	invoice made from that order re-prices it here by hanging weight, and the
	deposit comes off as the advance (share_billing.py).

	With no weight at all the line is left alone at its case price, and
	:func:`warn_missing_case_weight` says so.

	Runs before the controller, which keeps a row's own price_list_rate and rate
	(it only fills them when empty), so ERPNext's totals follow.
	"""
	is_invoice = doc.doctype == "Sales Invoice"
	on_date = doc.get("posting_date") or doc.get("transaction_date")
	for row in doc.get("items") or []:
		if not row.item_code:
			continue
		share = is_share(row.item_code)
		if row.meta.has_field(PRICED_PER_LB_FIELD):
			row.set(PRICED_PER_LB_FIELD, share)
		if share and not is_invoice:
			continue

		per_lb = price_per_lb(row.item_code, doc.get("customer"), on_date)
		if not per_lb:
			continue

		weight = _line_weight(row)
		if row.meta.has_field(CASE_WEIGHT_FIELD) and not flt(row.get(CASE_WEIGHT_FIELD)):
			row.set(CASE_WEIGHT_FIELD, weight)
		if weight:
			row.set(NATIVE_WEIGHT_FIELD, weight)
		if row.meta.has_field(UNIT_PRICE_FIELD):
			row.set(UNIT_PRICE_FIELD, per_lb)
		if not weight:
			continue

		price = flt(per_lb * weight, row.precision("price_list_rate"))
		row.price_list_rate = price
		row.rate = flt(price * (1 - flt(row.discount_percentage) / 100), row.precision("rate"))


@frappe.whitelist()
def get_per_lb_prices(item_codes, customer=None, on_date=None):
	"""For the form: {item_code: {"per_lb": $/lb, "share": 0/1}} for items with a Per Pound price."""
	codes = frappe.parse_json(item_codes) if isinstance(item_codes, str) else item_codes
	out = {}
	for code in set(codes or []):
		per_lb = price_per_lb(code, customer, on_date)
		if per_lb or is_share(code):
			out[code] = {"per_lb": per_lb, "share": is_share(code)}
	return out


def set_unit_price(doc, method=None):
	"""``validate`` (Sales Order + Sales Invoice) — fill Unit Price: what one pound works out to on this line.

	``Rate / Case Weight``. This is the only figure ERPNext cannot supply: with
	the case as the stock unit, the standard "Rate of Stock UOM" is just the case
	price again (the conversion factor is 1), so it can never answer "what is
	this per pound". Recomputed from the weight actually on the row, so a heavy
	or light shipment shows its true per-pound price.

	Runs on validate, once the controller has settled ``rate`` and fetched the
	item's nominal weight — which is also why the fallback below lives here and
	not in :func:`mirror_case_weight`. ``sales_invoice.js`` keeps the same figure
	live while the user is typing.
	"""
	is_order = doc.doctype == "Sales Order"
	on_date = doc.get("posting_date") or doc.get("transaction_date")
	for row in doc.get("items") or []:
		# Nothing typed: show the item's nominal case weight, so the operator can
		# see the default being accepted instead of an empty box. It is only a
		# display fallback — total_weight was already computed from the same
		# number by the controller.
		if not flt(row.get(CASE_WEIGHT_FIELD)):
			row.set(CASE_WEIGHT_FIELD, flt(row.get(NATIVE_WEIGHT_FIELD)))

		# A share on an order is charged its fixed deposit; deposit / weight is
		# not a price per lb, so the column stays empty until it is invoiced.
		if is_order and is_share(row.item_code):
			row.set(UNIT_PRICE_FIELD, 0.0)
			continue

		# Lines priced from the Per Pound list already carry Unit Price.
		if price_per_lb(row.item_code, doc.get("customer"), on_date):
			continue

		case_weight = flt(row.get(CASE_WEIGHT_FIELD))

		row.set(
			UNIT_PRICE_FIELD,
			flt(flt(row.get("rate")) / case_weight, row.precision(UNIT_PRICE_FIELD))
			if case_weight
			else 0.0,
		)


def warn_missing_case_weight(doc, method=None):
	"""``validate`` — warn, never block, on a line with no case weight.

	Without one the line contributes nothing to Total Weight (lb) and the Unit
	Price column stays blank. That is almost always an item whose nominal weight
	was never filled in — a data gap, not an accounting error, so it does not
	stop the invoice going out.

	Non-stock lines are skipped: a charge such as the per-lb Beef Processing
	Fee carries no weight of its own — giving it one would count the same
	pounds twice in Total Weight (lb).
	"""
	missing = [
		row
		for row in (doc.get("items") or [])
		if flt(row.qty)
		and not flt(row.get(CASE_WEIGHT_FIELD))
		and cint(frappe.get_cached_value("Item", row.item_code, "is_stock_item"))
	]
	if not missing:
		return

	frappe.msgprint(
		_("No case weight on row(s) {0}. They will not count towards Total Weight (lb).").format(
			", ".join(str(row.idx) for row in missing)
		),
		title=_("Missing case weight"),
		indicator="orange",
	)


def validate_zero_rate(doc, method=None):
	"""``before_submit`` — refuse to submit a line priced at zero.

	ERPNext leaves ``rate`` at 0.00 when it cannot find a price — silently, with
	no warning, and the invoice submits for $0.00. Genuinely free lines (samples,
	replacements, goodwill) are still possible by ticking Allow Zero Rate, which
	keeps the decision visible on the document instead of buried in a setting.
	"""
	if cint(doc.get(ALLOW_ZERO_RATE_FIELD)):
		return

	unpriced = [row for row in (doc.get("items") or []) if flt(row.qty) and not flt(row.rate)]
	if not unpriced:
		return

	rows = "<br>".join(
		_("Row {0}: {1}").format(row.idx, frappe.bold(row.item_code)) for row in unpriced
	)
	frappe.throw(
		_("These rows have no price. Check the item has an Item Price, or tick {0}.").format(
			frappe.bold(_("Allow Zero Rate"))
		)
		+ f"<br><br>{rows}",
		title=_("Nothing to charge"),
	)
