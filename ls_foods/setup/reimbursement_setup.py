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
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

MODULE = "Ls Foods"

MILEAGE_TYPE = "Mileage"
STOCK_TYPE = "Stock / Supplies Purchase"

# Fallback name used only if a company has no "Stock Received But Not Billed"
# and no default expense account configured.
PAYABLE_ACCOUNT_NAME = "Employee Reimbursements Payable"


# Superseded by the generic custom_qty / custom_rate pair (2026-08-07). Mileage is
# now just "qty x rate" with the labels swapped, so there is ONE amount mechanism
# on an expense row instead of two. Deleted by the v0_0_3 patch.
DEPRECATED_FIELDS = [
	"Expense Claim Detail-custom_miles",
	"Expense Claim Detail-custom_rate_per_mile",
]

# Status the payroll clerk sees, in the client's own vocabulary. Derived from the
# standard docstatus / approval_status / status trio — see reimbursement.py::
# set_reimbursement_status for the mapping and why we don't use a Workflow.
STATUS_FIELD = "custom_reimbursement_status"
STATUS_OPTIONS = "\n".join(["", "Draft", "Requested", "Approved", "Rejected", "Paid", "Cancelled"])

# What the payroll person wants to see in the Expense Reimbursement list, in order.
LIST_VIEW_FIELDS = [
	"custom_request_date",
	"custom_expense_type_summary",
	"grand_total",
	"custom_approval_date",
]
# Standard columns pushed off the list to make room for the four above.
LIST_VIEW_FIELDS_TO_HIDE = ["total_claimed_amount", "total_amount_reimbursed"]


CUSTOM_FIELDS = {
	# ---------------------------------------------------------------- claim
	"Expense Claim": [
		{
			"fieldname": "custom_request_date",
			"label": "Request Date",
			"fieldtype": "Date",
			"insert_after": "column_break_5",
			"default": "Today",
			"reqd": 1,
			"in_list_view": 1,
			"in_standard_filter": 1,
			"description": "When the employee asked to be reimbursed. Independent of the "
			"expense date on each row and of the Posting Date that drives the GL.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_expense_type_summary",
			"label": "Expense Claim Type",
			"fieldtype": "Data",
			"insert_after": "custom_request_date",
			"read_only": 1,
			"in_list_view": 1,
			"description": "The claim type(s) on this request, kept in step with the "
			"Expenses table so the list can be read at a glance.",
			"module": MODULE,
		},
		{
			"fieldname": STATUS_FIELD,
			"label": "Reimbursement Status",
			"fieldtype": "Select",
			"options": STATUS_OPTIONS,
			"insert_after": "approval_status",
			"read_only": 1,
			"in_standard_filter": 1,
			"description": "Requested -> Approved -> Paid. Derived from the standard "
			"approval status and the amount actually reimbursed.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_approval_date",
			"label": "Approval Date",
			"fieldtype": "Date",
			"insert_after": STATUS_FIELD,
			"allow_on_submit": 1,
			"in_list_view": 1,
			"description": "Stamped with today's date the first time this claim is marked "
			"Approved. Editable — back-date it if the approval actually happened earlier.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_paid_date",
			"label": "Paid Date",
			"fieldtype": "Date",
			"insert_after": "custom_approval_date",
			"read_only": 1,
			"allow_on_submit": 1,
			"depends_on": "custom_paid_date",
			"description": "Set from the Salary Slip (or Payment Entry) that reimbursed it.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_salary_slip",
			"label": "Paid via Salary Slip",
			"fieldtype": "Link",
			"options": "Salary Slip",
			"insert_after": "custom_paid_date",
			"read_only": 1,
			"allow_on_submit": 1,
			"depends_on": "custom_salary_slip",
			"module": MODULE,
		},
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
			"fieldname": "custom_receipt_required",
			"label": "Receipt Required",
			"fieldtype": "Check",
			"insert_after": "custom_is_mileage_type",
			"fetch_from": "expense_type.custom_receipt_required",
			"read_only": 1,
			"hidden": 1,
			"module": MODULE,
		},
		{
			"fieldname": "custom_qty",
			"label": "Qty",
			"fieldtype": "Float",
			"precision": "2",
			"insert_after": "custom_receipt_required",
			"default": "1",
			"description": "Miles driven, units bought, nights stayed - whatever the rate is "
			"charged per. Amount = Qty x Rate.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_rate",
			"label": "Rate",
			"fieldtype": "Currency",
			"insert_after": "custom_qty",
			"description": "Price per unit from the receipt. For mileage this defaults to the "
			"rate on the Expense Claim Type. Leave blank to type the Amount directly.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_receipt",
			"label": "Receipt",
			"fieldtype": "Attach",
			"insert_after": "default_account",
			"description": "Required for every expense type except mileage (controlled by "
			"Receipt Required on the Expense Claim Type).",
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
	# ---------------------------------------------------------- salary slip
	# The payroll half: approved claims are picked up here and paid out with the
	# wages. Placed in its own tab at the END of the form so nothing standard
	# shifts position. See ls_foods/reimbursement_payroll.py.
	"Salary Slip": [
		{
			"fieldname": "custom_reimbursements_tab",
			"label": "Reimbursements",
			"fieldtype": "Tab Break",
			"insert_after": "leave_details",
			"module": MODULE,
		},
		{
			"fieldname": "custom_reimbursements",
			"label": "Expense Reimbursements",
			"fieldtype": "Table",
			"options": "Salary Slip Reimbursement",
			"insert_after": "custom_reimbursements_tab",
			"description": "Approved, unpaid expense claims for this employee. Use "
			"<b>Get Approved Reimbursements</b> to pull them in. These are added to the "
			"net pay but NOT to gross pay — a reimbursement is not wages, so it must not "
			"be taxed.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_total_reimbursement",
			"label": "Total Reimbursement",
			"fieldtype": "Currency",
			"insert_after": "custom_reimbursements",
			"read_only": 1,
			"description": "Added to Net Pay after deductions.",
			"module": MODULE,
		},
	],
	# ----------------------------------------------------------- claim type
	"Expense Claim Type": [
		{
			"fieldname": "custom_receipt_required",
			"label": "Receipt Required",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "description",
			"description": "Block submitting a claim that has a row of this type with no "
			"receipt attached. Ticked by default; untick it for mileage, where there is "
			"nothing to photograph.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_is_mileage",
			"label": "Is Mileage Reimbursement",
			"fieldtype": "Check",
			"insert_after": "custom_receipt_required",
			"description": "Relabels Qty / Rate to Miles / Rate per Mile on claim rows of "
			"this type and seeds the rate below. The amount is still Qty x Rate.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_default_rate_per_mile",
			"label": "Default Rate per Mile",
			"fieldtype": "Currency",
			"insert_after": "custom_is_mileage",
			"depends_on": "custom_is_mileage",
			"description": "E.g. the IRS standard mileage rate for the year. Seeds Rate on "
			"every mileage row; the employee never types it.",
			"module": MODULE,
		},
	],
}


def run():
	"""Idempotent. Called from after_install and the v0_0_2 / v0_0_3 patches."""
	ensure_custom_fields()
	drop_deprecated_fields()
	ensure_list_view()
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


def drop_deprecated_fields():
	"""Remove custom fields this app no longer owns.

	``create_custom_fields`` only ever adds, so a field we stop shipping would
	otherwise linger on the form forever. Dropping the Custom Field leaves the
	column in the table (Frappe never drops columns) — harmless, and it keeps any
	historical value readable via SQL if it is ever needed.
	"""
	for name in DEPRECATED_FIELDS:
		if frappe.db.exists("Custom Field", name):
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	frappe.db.commit()


def ensure_list_view():
	"""Make the Expense Claim list show what the payroll clerk actually needs.

	Marlene's four columns are Request Date, Expense Claim Type, Amount and
	Approval Date. Frappe only gives a list a handful of columns, so the two
	standard amount columns that duplicate Grand Total are pushed off to make
	room. All of this is Property Setters, so it is reversible from
	Customize Form without touching HRMS.
	"""
	for fieldname in LIST_VIEW_FIELDS:
		make_property_setter(
			"Expense Claim", fieldname, "in_list_view", 1, "Check", validate_fields_for_doctype=False
		)
	for fieldname in LIST_VIEW_FIELDS_TO_HIDE:
		make_property_setter(
			"Expense Claim", fieldname, "in_list_view", 0, "Check", validate_fields_for_doctype=False
		)
	# Let the clerk search a claim by its type straight from the awesomebar.
	make_property_setter(
		"Expense Claim",
		None,
		"search_fields",
		"employee,employee_name,custom_expense_type_summary",
		"Data",
		for_doctype=True,
		validate_fields_for_doctype=False,
	)
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
	# Mileage is the one type with nothing to photograph — there is no receipt for
	# driving your own car. Every other type keeps the default of 1.
	frappe.db.set_value(
		"Expense Claim Type", MILEAGE_TYPE, "custom_receipt_required", 0, update_modified=False
	)

	# Existing types pre-date the field, so NULL them up to the intended default
	# rather than leaving receipts silently unenforced.
	frappe.db.sql(
		"""update `tabExpense Claim Type`
		   set custom_receipt_required = 1
		 where ifnull(custom_receipt_required, '') = '' and name != %s""",
		(MILEAGE_TYPE,),
	)

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
	"""Map a default account per company on EVERY claim type, where missing.

	This is what makes "the employee just picks a type" actually work. ERPNext
	resolves the GL account for an expense row from the claim type's Accounts
	table (``get_expense_claim_account``) and **throws** when there is no row for
	the claim's company — so a type with an empty Accounts table is not merely
	unconfigured, it is unusable. Five of the seven types on this site were in
	exactly that state, which means the first employee to pick "Food" would have
	hit a hard error instead of a saved request.

	The account seeded is a working PLACEHOLDER, not a recommendation: the
	company's default expense account. Pointing Food at Meals, Travel at Travel
	and so on is a one-field change per type on the Expense Claim Type form, and
	nothing here ever overwrites a mapping that already exists.
	"""
	claim_types = frappe.get_all("Expense Claim Type", pluck="name")
	companies = frappe.get_all("Company", pluck="name")

	for claim_type in claim_types:
		ect = None
		for company in companies:
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
