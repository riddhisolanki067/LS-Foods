"""LS Foods — Employee Reimbursement module setup.

Design decision (worth being able to defend to the client)
----------------------------------------------------------
Marlene asked for "a Reimbursement module". ERPNext already ships one: the
**Expense Claim** (HR > Expense Claim). Out of the box it does two of the three
things she asked for:

  * reimburse an employee for out-of-pocket spend, and
  * let you **designate the account** each line is booked to — that is the
    standard ``Expense Claim Detail.default_account`` field, which becomes the
    debit in the claim's GL entry (credit = the employee payable).

It does NOT do the third thing: increase inventory when the employee bought
stock. So rather than build a parallel module (which would mean re-inventing
approval, payable, Payment Entry, ageing and reporting), we EXTEND Expense Claim
with what it is missing:

  1. **Mileage** — ``custom_miles`` x ``custom_rate_per_mile`` on the expense
     row, driven by a "Mileage" Expense Claim Type carrying the default rate.
  2. **Stock / supplies purchases** — a ``custom_stock_items`` child table where
     you name the Item, qty, rate and warehouse. On submit ls_foods posts a
     Stock Entry (Material Receipt) so inventory goes up.

Accounting produced (see ls_foods/reimbursement.py for the code)
---------------------------------------------------------------
For a row whose Item **maintains stock**:

    Stock Entry     Dr  Stock In Hand (warehouse account)      100
                        Cr  Account on the row (clearing)          100
    Expense Claim   Dr  Account on the row (clearing)          100
                        Cr  Employee Payable                       100
    ------------------------------------------------------------------
    Net             Dr  Inventory 100 / Cr Employee Payable 100

  The clearing account defaults to the company's standard "Stock Received But
  Not Billed" — goods are in hand, the employee has not been paid back yet. It
  nets to zero because the SAME account is used on both legs. The item's own
  expense account is hit later, on consumption/sale (COGS) — that is correct
  accrual accounting: buying stock is an asset swap, not an expense.

For a row whose Item does **not** maintain stock (supplies, consumables):

    Expense Claim   Dr  Item's expense account                 100
                        Cr  Employee Payable                       100

  Charged straight to P&L, using the expense account attached to the Item, which
  is what Marlene described.

Both are driven off the same "Account" field on the row, so she can always
override it and designate a different account.

Everything here is idempotent — safe to re-run via ``bench migrate``.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

MODULE = "Ls Foods"

MILEAGE_TYPE = "Mileage"
STOCK_TYPE = "Stock / Supplies Purchase"

# Fallback name used only if a company has no "Stock Received But Not Billed"
# and no default expense account configured.
PAYABLE_ACCOUNT_NAME = "Employee Reimbursements Payable"


CUSTOM_FIELDS = {
	# ---------------------------------------------------------------- claim
	"Expense Claim": [
		{
			"fieldname": "custom_stock_reimbursement_section",
			"label": "Stock / Supplies Purchased by Employee",
			"fieldtype": "Section Break",
			"insert_after": "expenses",
			"collapsible": 1,
			"collapsible_depends_on": "custom_stock_items",
			"description": "Things the employee bought out of pocket. Items that maintain "
			"stock are received into the warehouse by a Stock Entry when this claim is "
			"submitted; everything else is charged straight to the account on the row.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_stock_items",
			"label": "Purchased Items",
			"fieldtype": "Table",
			"options": "Reimbursement Stock Item",
			"insert_after": "custom_stock_reimbursement_section",
			"module": MODULE,
		},
		{
			"fieldname": "custom_total_stock_amount",
			"label": "Total Purchased Items",
			"fieldtype": "Currency",
			"insert_after": "custom_stock_items",
			"read_only": 1,
			"depends_on": "custom_stock_items",
			"description": "Mirrored into the Expenses table as a single auto-maintained "
			"row so the claim total, the GL entry and the amount payable to the employee "
			"all include these purchases.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_stock_entry",
			"label": "Stock Entry",
			"fieldtype": "Link",
			"options": "Stock Entry",
			"insert_after": "custom_total_stock_amount",
			"read_only": 1,
			"depends_on": "custom_stock_entry",
			"description": "Material Receipt posted on submit for the stock items above.",
			"module": MODULE,
		},
	],
	# ----------------------------------------------------------- claim rows
	"Expense Claim Detail": [
		{
			"fieldname": "custom_is_mileage_type",
			"label": "Is Mileage Type",
			"fieldtype": "Check",
			"insert_after": "expense_type",
			"fetch_from": "expense_type.custom_is_mileage",
			"read_only": 1,
			"hidden": 1,
			"module": MODULE,
		},
		{
			"fieldname": "custom_miles",
			"label": "Miles",
			"fieldtype": "Float",
			"precision": "2",
			"insert_after": "custom_is_mileage_type",
			"depends_on": "custom_is_mileage_type",
			"mandatory_depends_on": "custom_is_mileage_type",
			"description": "Amount = Miles x Rate per Mile.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_rate_per_mile",
			"label": "Rate per Mile",
			"fieldtype": "Currency",
			"insert_after": "custom_miles",
			"depends_on": "custom_is_mileage_type",
			"fetch_from": "expense_type.custom_default_rate_per_mile",
			"fetch_if_empty": 1,
			"description": "Defaults from the Expense Claim Type. Override per trip if needed.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_auto_generated",
			"label": "Auto Generated",
			"fieldtype": "Check",
			"insert_after": "sanctioned_amount",
			"read_only": 1,
			"hidden": 1,
			"description": "Set on the row ls_foods maintains for the Purchased Items table. "
			"Do not edit that row by hand — it is rebuilt on every save.",
			"module": MODULE,
		},
	],
	# ----------------------------------------------------------- claim type
	"Expense Claim Type": [
		{
			"fieldname": "custom_is_mileage",
			"label": "Is Mileage Reimbursement",
			"fieldtype": "Check",
			"insert_after": "description",
			"description": "Show Miles / Rate per Mile on claim rows of this type and "
			"compute the amount as Miles x Rate per Mile.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_default_rate_per_mile",
			"label": "Default Rate per Mile",
			"fieldtype": "Currency",
			"insert_after": "custom_is_mileage",
			"depends_on": "custom_is_mileage",
			"description": "E.g. the IRS standard mileage rate for the year.",
			"module": MODULE,
		},
	],
}


def run():
	"""Idempotent. Called from after_install and the v0_0_2 patch."""
	ensure_custom_fields()
	ensure_expense_claim_types()
	ensure_payable_accounts()


def ensure_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	# Pin module so `bench export-fixtures --app ls_foods` picks up exactly these.
	for dt, fields in CUSTOM_FIELDS.items():
		for f in fields:
			name = f"{dt}-{f['fieldname']}"
			if frappe.db.exists("Custom Field", name):
				frappe.db.set_value("Custom Field", name, "module", MODULE, update_modified=False)
	frappe.db.commit()


def ensure_expense_claim_types():
	"""Create the two claim types the module leans on, with an account per company.

	ERPNext refuses to save an expense row whose claim type has no default account
	mapped for the company (``get_expense_claim_account`` throws), so a claim type
	with an empty Accounts table is unusable. We therefore seed each company with
	its default expense account.

	That is a placeholder, not a recommendation: Mileage should really point at the
	client's auto/travel expense account. It is a one-field change per company on
	the Expense Claim Type form, and we never overwrite a mapping that already
	exists.
	"""
	if not frappe.db.exists("Expense Claim Type", MILEAGE_TYPE):
		doc = frappe.new_doc("Expense Claim Type")
		doc.expense_type = MILEAGE_TYPE
		doc.description = "Reimbursement for business miles driven in a personal vehicle."
		doc.insert(ignore_permissions=True)

	frappe.db.set_value("Expense Claim Type", MILEAGE_TYPE, "custom_is_mileage", 1, update_modified=False)

	if not frappe.db.exists("Expense Claim Type", STOCK_TYPE):
		doc = frappe.new_doc("Expense Claim Type")
		doc.expense_type = STOCK_TYPE
		doc.description = (
			"Auto-maintained by ls_foods for the Purchased Items table on an Expense "
			"Claim. Do not use this type manually."
		)
		doc.insert(ignore_permissions=True)

	ensure_claim_type_accounts()
	frappe.db.commit()


def ensure_claim_type_accounts():
	"""Map a default account per company on our two claim types, where missing."""
	for claim_type in (MILEAGE_TYPE, STOCK_TYPE):
		ect = None
		for company in frappe.get_all("Company", pluck="name"):
			if frappe.db.exists("Expense Claim Account", {"parent": claim_type, "company": company}):
				continue

			# Stock/supplies rows always carry their own explicit account, so the
			# clearing account is the honest default there.
			account = (
				_clearing_account(company) if claim_type == STOCK_TYPE else None
			) or _default_expense_account(company)
			if not account:
				continue

			ect = ect or frappe.get_doc("Expense Claim Type", claim_type)
			ect.append("accounts", {"company": company, "default_account": account})

		if ect:
			ect.flags.ignore_permissions = True
			ect.save()


def _clearing_account(company):
	return frappe.get_cached_value("Company", company, "stock_received_but_not_billed")


def _default_expense_account(company):
	return frappe.get_cached_value("Company", company, "default_expense_account") or frappe.db.get_value(
		"Account", {"company": company, "is_group": 0, "root_type": "Expense"}, "name"
	)


def ensure_payable_accounts():
	"""Set ``Company.default_expense_claim_payable_account`` where it is missing.

	An Expense Claim cannot be submitted without a payable account, and none of the
	three LS Foods companies had one set.

	We create a DEDICATED "Employee Reimbursements Payable" account per company
	rather than reusing an existing liability. Reusing Wages Payable would blend
	"we owe you for hours worked" with "we owe you for the groceries you bought",
	and reusing the supplier payable would put employees in the AP ageing. Both
	still reconcile by party, but the trial balance line stops meaning one thing —
	and that is exactly the line an accountant reads first.

	Only ever fills a BLANK setting — never overwrites the client's choice, so
	Marlene can point this at any account she prefers from Company master.
	"""
	set_for = []

	for company in frappe.get_all("Company", pluck="name"):
		current = frappe.db.get_value("Company", company, "default_expense_claim_payable_account")
		if current:
			continue

		account = _create_reimbursement_payable_account(company)
		if account:
			frappe.db.set_value(
				"Company", company, "default_expense_claim_payable_account", account, update_modified=False
			)
			set_for.append((company, account))

	if set_for:
		frappe.db.commit()
	return set_for


def _create_reimbursement_payable_account(company):
	"""Last resort: make a payable account under the company's payable group."""
	abbr = frappe.get_cached_value("Company", company, "abbr")
	name = f"{PAYABLE_ACCOUNT_NAME} - {abbr}"
	if frappe.db.exists("Account", name):
		return name

	parent = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "account_type": "Payable"},
		"name",
	) or frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": "Liability", "parent_account": ["is", "not set"]},
		"name",
	)
	if not parent:
		return None

	acc = frappe.new_doc("Account")
	acc.account_name = PAYABLE_ACCOUNT_NAME
	acc.parent_account = parent
	acc.company = company
	acc.account_type = "Payable"
	acc.root_type = "Liability"
	acc.is_group = 0
	acc.insert(ignore_permissions=True)
	return acc.name
