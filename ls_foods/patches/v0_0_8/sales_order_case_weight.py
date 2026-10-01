"""v0_0_8 — the invoice's Case Weight / Unit Price / Line Weight grid on the Sales Order.

Idempotent; re-runnable.

  * ``case_pricing_setup.run()`` adds ``custom_case_weight`` and
    ``custom_unit_price`` to Sales Order Item and lays its grid out like Sales
    Invoice Item's.
  * Orders already on file typed their weight straight into ``weight_per_unit``
    (the only box there was). Their two new columns would open empty beside a
    filled Line Weight, so they are filled from what the row already holds:

        Case Weight (lb) = weight_per_unit
        Unit Price       = rate / weight_per_unit     (blank on a beef/hog share,
                                                       whose rate is its deposit)

    Only the two new columns are written, and only where they are still empty.
    No rate, amount, weight or total on any order changes — submitted ones
    included — and ``modified`` is left alone.
"""

import frappe

from ls_foods.case_pricing import (
	CASE_WEIGHT_FIELD,
	NATIVE_WEIGHT_FIELD,
	PRICED_PER_LB_FIELD,
	UNIT_PRICE_FIELD,
)
from ls_foods.setup import case_pricing_setup


def execute():
	case_pricing_setup.run()

	frappe.db.sql(
		f"""
		update `tabSales Order Item` soi
		  left join `tabItem` item on item.name = soi.item_code
		   set soi.`{CASE_WEIGHT_FIELD}` = soi.`{NATIVE_WEIGHT_FIELD}`,
		       soi.`{UNIT_PRICE_FIELD}` = if(
		           ifnull(item.`{PRICED_PER_LB_FIELD}`, 0) = 1,
		           0,
		           round(soi.rate / soi.`{NATIVE_WEIGHT_FIELD}`, 2)
		       )
		 where ifnull(soi.`{CASE_WEIGHT_FIELD}`, 0) = 0
		   and ifnull(soi.`{NATIVE_WEIGHT_FIELD}`, 0) != 0
		"""
	)

	frappe.clear_cache()
