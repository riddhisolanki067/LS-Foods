"""LS Foods — Employee Reimbursement (Expense Claim extensions).

Wired in hooks.py::

    "Expense Claim": {
        "before_validate": "ls_foods.reimbursement.sync_reimbursement_rows",
        "on_submit":       "ls_foods.reimbursement.post_stock_entry",
        "on_cancel":       "ls_foods.reimbursement.cancel_stock_entry",
    }

Read ``ls_foods/setup/reimbursement_setup.py`` first — it explains WHY this is
built on the standard Expense Claim and lays out the double entry produced.

Three jobs:

1. **Mileage** — for rows on a claim type flagged ``custom_is_mileage``, set
   ``amount = miles x rate_per_mile`` server-side. The client script does the
   same live on the form; this is the authoritative copy so an import or an API
   call can't slip a wrong number past.

2. **Mirror the Purchased Items table into the Expenses table** — the Expense
   Claim's grand total, its GL entry and the amount payable to the employee all
   derive from ``expenses``. Purchased Items are therefore folded in as ONE
   auto-maintained row per account used, tagged ``custom_auto_generated``. The
   rows are rebuilt from scratch on every save, so the two tables can never drift
   apart. This runs on ``before_validate`` so the standard validate then computes
   the totals with the rows already in place.

3. **Post the Stock Entry** — on submit, items that maintain stock are received
   into their warehouse by a Material Receipt whose Difference Account is the
   same account used on the mirrored expense row, so the two entries net to
   Dr Inventory / Cr Employee Payable. On cancel the Stock Entry is cancelled.
"""

import frappe
from frappe import _
from frappe.utils import flt

from ls_foods.setup.reimbursement_setup import (
	STOCK_TYPE,
	_clearing_account,
	ensure_claim_type_accounts,
)

# ===================================================================
#  before_validate — mileage amounts + mirror stock rows into expenses
# ===================================================================


def sync_reimbursement_rows(doc, method=None):
	set_default_cost_centers(doc)
	set_mileage_amounts(doc)
	sync_stock_items_to_expenses(doc)


def set_default_cost_centers(doc):
	"""Fill a blank cost center from the company default.

	ERPNext hard-throws on submit if ANY expense row has no cost center, but only
	the Expense Claim form's JS fills it in. Anything created by script, import or
	API therefore fails at submit with a confusing row-level error. Mirroring the
	form's behaviour server-side closes that gap — and our auto-generated rows need
	it too.
	"""
	if not doc.company:
		return

	company_cc = frappe.get_cached_value("Company", doc.company, "cost_center")
	if not doc.cost_center:
		doc.cost_center = company_cc

	for row in doc.get("expenses") or []:
		if not row.cost_center:
			row.cost_center = doc.cost_center or company_cc


def set_mileage_amounts(doc):
	"""amount = miles x rate per mile, for rows on a mileage-flagged claim type."""
	for row in doc.get("expenses") or []:
		if not row.get("custom_is_mileage_type"):
			# fetch_from only fires on the form; resolve it here for API/import paths
			if not row.expense_type:
				continue
			if not frappe.get_cached_value("Expense Claim Type", row.expense_type, "custom_is_mileage"):
				continue
			row.custom_is_mileage_type = 1

		if not flt(row.custom_rate_per_mile):
			row.custom_rate_per_mile = flt(
				frappe.get_cached_value(
					"Expense Claim Type", row.expense_type, "custom_default_rate_per_mile"
				)
			)

		amount = flt(flt(row.custom_miles) * flt(row.custom_rate_per_mile), row.precision("amount"))
		row.amount = amount
		# Sanctioned defaults to claimed; only raise it, never silently cut an
		# approver's reduction back up.
		if flt(row.sanctioned_amount) > amount or not flt(row.sanctioned_amount):
			row.sanctioned_amount = amount


def sync_stock_items_to_expenses(doc):
	"""Rebuild the auto-generated expense rows that mirror ``custom_stock_items``."""
	rows = doc.get("custom_stock_items") or []

	# Always drop the previous auto rows first — that makes this idempotent and
	# stops stale amounts surviving a deleted/edited stock row. Reassign the
	# surviving child docs themselves (not copies) so their names/idx survive.
	expenses = doc.get("expenses") or []
	kept = [r for r in expenses if not r.get("custom_auto_generated")]
	if len(kept) != len(expenses):
		doc.expenses = kept
		for i, r in enumerate(kept, start=1):
			r.idx = i

	doc.custom_total_stock_amount = 0
	if not rows:
		return

	_ensure_stock_expense_type_account(doc.company)

	total = 0.0
	by_account = {}

	for row in rows:
		if not row.item_code:
			continue

		item = frappe.get_cached_doc("Item", row.item_code)

		# Catch these here rather than letting the Stock Entry blow up on submit,
		# where the message is far less obvious.
		if item.has_variants:
			frappe.throw(
				_("Row {0}: {1} is a template item — pick the specific variant that was bought.").format(
					row.idx, frappe.bold(row.item_code)
				),
				title=_("Cannot Receive a Template Item"),
			)
		if item.disabled:
			frappe.throw(
				_("Row {0}: item {1} is disabled.").format(row.idx, frappe.bold(row.item_code))
			)

		row.is_stock_item = item.is_stock_item
		if not row.uom:
			row.uom = item.stock_uom
		if not row.expense_account:
			row.expense_account = resolve_account(row, doc.company)
		if not row.cost_center:
			row.cost_center = doc.cost_center or frappe.get_cached_value("Company", doc.company, "cost_center")
		if row.is_stock_item and not row.warehouse:
			row.warehouse = _default_warehouse(row.item_code, doc.company)

		row.amount = flt(flt(row.qty) * flt(row.rate), row.precision("amount"))
		total += row.amount
		by_account.setdefault((row.expense_account, row.cost_center), 0.0)
		by_account[(row.expense_account, row.cost_center)] += row.amount

	doc.custom_total_stock_amount = flt(total, doc.precision("custom_total_stock_amount"))

	for (account, cost_center), amount in by_account.items():
		if not flt(amount):
			continue
		doc.append(
			"expenses",
			{
				"expense_date": doc.posting_date or frappe.utils.nowdate(),
				"expense_type": STOCK_TYPE,
				"default_account": account,
				"cost_center": cost_center,
				"description": _("Items purchased by employee — see Purchased Items table"),
				"amount": amount,
				"sanctioned_amount": amount,
				"custom_auto_generated": 1,
			},
		)


def _ensure_stock_expense_type_account(company):
	"""ERPNext's ``get_expense_claim_account`` throws if a claim type has no
	account mapped for the company. Our auto rows always carry an explicit
	``default_account``, but the lookup can still run — so make sure a mapping
	exists. Normally seeded at install/migrate; this covers a company added later.
	"""
	if not company:
		return
	if frappe.db.exists("Expense Claim Account", {"parent": STOCK_TYPE, "company": company}):
		return
	ensure_claim_type_accounts()


# ===================================================================
#  Account resolution
# ===================================================================


def resolve_account(row, company):
	"""Which account does this purchased item post to?

	Stock item  -> the clearing account ("Stock Received But Not Billed"). The
	               Stock Entry credits the same account, so it nets to zero and
	               the real debit lands on Inventory. The item's own expense
	               account is hit later as COGS, on consumption/sale.
	Non-stock   -> the expense account attached to the item (Item Defaults, then
	               Item Group, then the company default). Straight to P&L.
	"""
	if row.get("is_stock_item"):
		return _clearing_account(company) or _item_expense_account(row.item_code, company)
	return _item_expense_account(row.item_code, company)


def _item_expense_account(item_code, company):
	account = frappe.db.get_value(
		"Item Default", {"parent": item_code, "company": company}, "expense_account"
	)
	if account:
		return account

	item_group = frappe.get_cached_value("Item", item_code, "item_group")
	if item_group:
		account = frappe.db.get_value(
			"Item Default", {"parent": item_group, "company": company}, "expense_account"
		)
		if account:
			return account

	return frappe.get_cached_value("Company", company, "default_expense_account")


@frappe.whitelist()
def get_reimbursement_item_details(item_code, company):
	"""Called by expense_claim.js when an Item is picked on a Purchased Items row.

	Returns the same defaults the server would apply on save, so the form shows
	the real account/warehouse immediately instead of after the first save.
	"""
	item = frappe.get_cached_doc("Item", item_code)
	row = frappe._dict({"item_code": item_code, "is_stock_item": item.is_stock_item})

	return {
		"is_stock_item": item.is_stock_item,
		"stock_uom": item.stock_uom,
		"expense_account": resolve_account(row, company),
		"warehouse": _default_warehouse(item_code, company) if item.is_stock_item else None,
	}


def _default_warehouse(item_code, company):
	return frappe.db.get_value(
		"Item Default", {"parent": item_code, "company": company}, "default_warehouse"
	) or frappe.db.get_single_value("Stock Settings", "default_warehouse")


# ===================================================================
#  on_submit / on_cancel — the Stock Entry
# ===================================================================


def post_stock_entry(doc, method=None):
	"""Receive the employee-purchased stock items into the warehouse."""
	if doc.get("custom_stock_entry"):
		return  # idempotent re-submit guard

	stock_rows = [r for r in (doc.get("custom_stock_items") or []) if r.is_stock_item and flt(r.qty)]
	if not stock_rows:
		return

	se = frappe.new_doc("Stock Entry")
	se.stock_entry_type = "Material Receipt"
	se.purpose = "Material Receipt"
	se.company = doc.company
	se.set_posting_time = 1
	se.posting_date = doc.posting_date
	se.posting_time = frappe.utils.nowtime()
	se.remarks = _("Items purchased by {0} — Expense Claim {1}").format(
		doc.employee_name or doc.employee, doc.name
	)

	for row in stock_rows:
		if not row.warehouse:
			frappe.throw(
				_("Row {0}: set a Target Warehouse for stock item {1}.").format(row.idx, row.item_code)
			)
		se.append(
			"items",
			{
				"item_code": row.item_code,
				"qty": flt(row.qty),
				"uom": row.uom,
				"basic_rate": flt(row.rate),
				"t_warehouse": row.warehouse,
				# Difference account == the account on the claim row, so the
				# Expense Claim's debit and this credit cancel out.
				"expense_account": row.expense_account,
				"cost_center": row.cost_center,
				"allow_zero_valuation_rate": 1 if not flt(row.rate) else 0,
			},
		)

	se.flags.ignore_permissions = True
	se.insert()
	se.submit()

	doc.db_set("custom_stock_entry", se.name, update_modified=False)
	frappe.msgprint(
		_("Stock Entry {0} posted — inventory updated.").format(
			frappe.utils.get_link_to_form("Stock Entry", se.name)
		),
		alert=True,
		indicator="green",
	)


def cancel_stock_entry(doc, method=None):
	"""Reverse the Material Receipt when the claim is cancelled."""
	se = doc.get("custom_stock_entry") or frappe.db.get_value(
		"Expense Claim", doc.name, "custom_stock_entry"
	)
	if not se or not frappe.db.exists("Stock Entry", se):
		return

	doc.db_set("custom_stock_entry", "", update_modified=False)
	sdoc = frappe.get_doc("Stock Entry", se)
	if sdoc.docstatus == 1:
		sdoc.flags.ignore_permissions = True
		sdoc.cancel()
