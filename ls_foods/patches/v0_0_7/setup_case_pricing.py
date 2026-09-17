"""v0_0_7 — case pricing and weight on the Sales Invoice.

Idempotent; re-runnable. Items are stocked and sold in **Cases**, so most of
what the client asked for already exists under standard field names and this
mostly exposes and relabels them:

  * makes ``weight_per_unit`` editable on Sales Invoice Item and relabels it
    **Case Weight (lb)** — the box where the actual pounds in a case are typed,
    per line (it is already editable on Sales Order Item and Delivery Note Item);
  * surfaces ``total_weight`` as **Line Weight (lb)** and ``total_net_weight`` as
    **Total Weight (lb)**;
  * adds ``custom_unit_price`` (rate / case weight) and ``custom_allow_zero_rate``;
  * rebalances the item grid, which ERPNext ships over Frappe's column budget;
  * seeds the ``Case`` UOM and installs the "LS Foods Invoice" print format.

It touches **no item data**. Stock UOM, Weight UOM and the nominal case weight
are the client's own master data. Stock UOM in particular cannot be changed once
an item has moved stock (``check_stock_uom_with_bin``), so a patch must never
guess at it.
"""

import frappe

from ls_foods.setup import case_pricing_setup


def execute():
	case_pricing_setup.run()
	frappe.clear_cache()
