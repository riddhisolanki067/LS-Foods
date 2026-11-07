"""LS Foods — link a customer's unallocated payments to a Sales Order.

Cancelling a Sales Order takes its payments off it, and the amended order starts
with none. ERPNext's Payment Reconciliation only offers invoices, so this gives
the order a "Retrieve Payments" button. The linking itself is ERPNext's own
``reconcile_against_document``, the same call the Reconciliation tool makes: the
Payment Entry gets a reference row, the General Ledger is left alone (the money
stays in the customer's account until invoiced) and Advance Paid is recalculated.
"""

import json

import frappe
from frappe import _
from frappe.utils import flt


def _order(sales_order):
	so = frappe.get_doc("Sales Order", sales_order)
	so.check_permission("read")
	if so.docstatus != 1:
		frappe.throw(_("Payments can only be linked to a submitted Sales Order."))
	if so.status == "Closed":
		frappe.throw(_("Sales Order {0} is closed.").format(so.name))
	return so


def order_balance(so):
	return flt(flt(so.rounded_total or so.grand_total) - flt(so.advance_paid), so.precision("grand_total"))


def _available(so):
	return frappe.get_all(
		"Payment Entry",
		filters={
			"docstatus": 1,
			"payment_type": "Receive",
			"party_type": "Customer",
			"party": so.customer,
			"company": so.company,
			"unallocated_amount": [">", 0],
		},
		fields=["name", "posting_date", "reference_no", "paid_amount", "unallocated_amount", "paid_from"],
		order_by="posting_date asc, creation asc",
	)


@frappe.whitelist()
def get_available_payments(sales_order):
	so = _order(sales_order)
	return {"balance": order_balance(so), "payments": _available(so)}


@frappe.whitelist(methods=["POST"])
def link_payments(sales_order, allocations):
	"""``allocations``: [{"payment_entry": name, "amount": 100.0}, ...]"""
	from erpnext.accounts.utils import reconcile_against_document

	frappe.has_permission("Payment Entry", "write", throw=True)
	so = _order(sales_order)
	if isinstance(allocations, str):
		allocations = json.loads(allocations)
	allocations = [a for a in allocations if flt(a.get("amount")) > 0]
	if not allocations:
		frappe.throw(_("Enter an amount for at least one payment."))

	available = {p.name: p for p in _available(so)}
	balance = order_balance(so)
	total = flt(sum(flt(a["amount"]) for a in allocations), so.precision("grand_total"))
	if total > balance:
		frappe.throw(
			_("The amounts total {0}, but only {1} is left to pay on this order.").format(
				frappe.format(total, {"fieldtype": "Currency"}),
				frappe.format(balance, {"fieldtype": "Currency"}),
			)
		)

	entries = []
	for row in allocations:
		payment = available.get(row["payment_entry"])
		if not payment:
			frappe.throw(_("{0} has no unallocated amount left for this customer.").format(row["payment_entry"]))
		amount = flt(row["amount"])
		if amount > flt(payment.unallocated_amount):
			frappe.throw(
				_("{0} has only {1} unallocated.").format(
					payment.name, frappe.format(payment.unallocated_amount, {"fieldtype": "Currency"})
				)
			)
		entries.append(
			frappe._dict(
				voucher_type="Payment Entry",
				voucher_no=payment.name,
				voucher_detail_no=None,
				against_voucher_type="Sales Order",
				against_voucher=so.name,
				account=payment.paid_from,
				party_type="Customer",
				party=so.customer,
				dr_or_cr="credit_in_account_currency",
				unadjusted_amount=flt(payment.unallocated_amount),
				unreconciled_amount=flt(payment.unallocated_amount),
				allocated_amount=amount,
				grand_total=flt(so.rounded_total or so.grand_total),
				outstanding_amount=balance,
				exchange_rate=1,
			)
		)

	before = flt(so.advance_paid)
	reconcile_against_document(entries)

	# Advance Paid comes from the advance ledger. If it did not move, the order
	# would look unpaid with the payment tied up: undo the whole link.
	advance_paid = flt(frappe.db.get_value("Sales Order", so.name, "advance_paid"))
	if flt(advance_paid - before - total, so.precision("grand_total")):
		frappe.throw(_("The payment could not be linked: Advance Paid on the order did not update."))

	return {"linked": [e.voucher_no for e in entries], "advance_paid": advance_paid}
