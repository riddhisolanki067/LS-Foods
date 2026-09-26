"""LS Foods — deposits on custom beef / hog shares.

The client charges a FIXED deposit when a share is ordered — $600 quarter,
$1,200 half, $2,400 whole beef; $200 per half hog — whatever the weight or the
price per lb (confirmed by the client 2026-09-26). That is the share item's
price in the price list, so the Sales Order line for the share already carries
it. This module only:

    Sales Order   Deposit Due   = sum of the share lines (items priced per lb)
                  Advance Paid  standard — what has actually been received

and pre-fills the Payment Entry for whatever is still owed
(:func:`make_deposit_entry`). The payment is a standard advance: with the
company's "Book Advance Payments in Separate Party Account" on, it sits in
Customer Deposits (a liability) until the final invoice deducts it with Get
Advances. Other items on the order (chicken, salmon…) are NOT part of the
deposit — they are paid with the final invoice.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt

from ls_foods.case_pricing import PRICED_PER_LB_FIELD

DEPOSIT_DUE_FIELD = "custom_deposit_due"


def set_deposit_due(doc, method=None):
	"""Sales Order ``validate`` — Deposit Due = the share lines' amount.

	On ``validate`` (not before) so the lines' amounts are already calculated.
	"""
	total = 0.0
	for row in doc.get("items") or []:
		if row.item_code and cint(frappe.get_cached_value("Item", row.item_code, PRICED_PER_LB_FIELD)):
			total += flt(row.amount)

	doc.set(DEPOSIT_DUE_FIELD, flt(total, doc.precision(DEPOSIT_DUE_FIELD)))


def deposit_outstanding(so):
	return flt(so.get(DEPOSIT_DUE_FIELD)) - flt(so.advance_paid)


@frappe.whitelist()
def make_deposit_entry(sales_order):
	"""A draft Payment Entry for the deposit still owed on a submitted Sales Order."""
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	so = frappe.get_doc("Sales Order", sales_order)
	so.check_permission("read")
	if so.docstatus != 1:
		frappe.throw(_("Submit the Sales Order before collecting its deposit."))

	amount = deposit_outstanding(so)
	if amount <= 0:
		frappe.throw(_("The deposit on {0} has already been paid.").format(so.name))

	pe = get_payment_entry("Sales Order", so.name, party_amount=amount)
	pe.paid_amount = pe.received_amount = amount
	for ref in pe.references:
		ref.allocated_amount = amount
	pe.remarks = _("Share deposit for Sales Order {0}").format(so.name)
	return pe
