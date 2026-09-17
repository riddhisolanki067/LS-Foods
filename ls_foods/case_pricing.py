"""LS Foods — case pricing and weight on the Sales Invoice.

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

⚠ The rule the weight total rests on: **every item must have Weight UOM = Lb**.
``calculate_total_net_weight`` (``taxes_and_totals.py:665``) adds the lines'
``total_weight`` with **no unit conversion**, so one item in Kg silently
corrupts the invoice total.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

CASE_WEIGHT_FIELD = "custom_case_weight"
UNIT_PRICE_FIELD = "custom_unit_price"
ALLOW_ZERO_RATE_FIELD = "custom_allow_zero_rate"

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


def set_unit_price(doc, method=None):
	"""``validate`` — fill Unit Price: what one pound works out to on this line.

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
	for row in doc.get("items") or []:
		# Nothing typed: show the item's nominal case weight, so the operator can
		# see the default being accepted instead of an empty box. It is only a
		# display fallback — total_weight was already computed from the same
		# number by the controller.
		if not flt(row.get(CASE_WEIGHT_FIELD)):
			row.set(CASE_WEIGHT_FIELD, flt(row.get(NATIVE_WEIGHT_FIELD)))

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
	"""
	missing = [
		row for row in (doc.get("items") or []) if flt(row.qty) and not flt(row.get(CASE_WEIGHT_FIELD))
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
