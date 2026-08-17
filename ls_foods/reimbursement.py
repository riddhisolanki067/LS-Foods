"""LS Foods — Employee Reimbursement (Expense Claim extensions).

Wired in hooks.py::

    "Expense Claim": {
        "before_validate": "ls_foods.reimbursement.sync_reimbursement_rows",
        "validate":        "ls_foods.reimbursement.finalize_reimbursement_fields",
        "before_submit":   "ls_foods.reimbursement.validate_receipts",
        "on_submit":       "ls_foods.reimbursement.post_stock_entry",
        "on_cancel":       "ls_foods.reimbursement.cancel_stock_entry",
    }
    "Journal Entry" / "Payment Entry": {
        "on_submit" / "on_cancel": "ls_foods.reimbursement.sync_claims_from_voucher",
    }

Read ``ls_foods/setup/reimbursement_setup.py`` first — it explains WHY this is
built on the standard Expense Claim and lays out the double entry produced. The
payroll half of the flow — picking approved claims up on a Salary Slip and
paying them out with the wages — lives in ``ls_foods/reimbursement_payroll.py``.

Jobs:

1. **Amount = Qty x Rate** on every expense row — one mechanism for mileage
   (120 miles x $0.70), for stock bought off a receipt (10 x $3.50) and for a
   one-off (1 x $50). Mileage is not special-cased any more; it is a claim type
   that seeds the rate and relabels the columns. The client script does the same
   arithmetic live on the form; this is the authoritative copy so an import or
   an API call can't slip a wrong number past.

1a. **Request / approval / paid dates and the Requested-Approved-Paid status**,
   all derived, never typed — see ``finalize_reimbursement_fields``.

1b. **Receipts** — blocked at submit for every claim type except the ones
   flagged otherwise (Mileage ships exempt). See ``validate_receipts``.

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

from ls_foods.setup.expense_claim_workflow import STATE_FIELD, derive_state
from ls_foods.setup.reimbursement_setup import (
	STOCK_TYPE,
	_clearing_account,
	_default_expense_account,
	ensure_claim_type_accounts,
)

# The role the workflow's Approve / Reject transitions are granted to. Two things
# have to be true of it and are true of Expense Approver: it must be able to write
# Expense Claim.approval_status, which is **permlevel 1** — Frappe silently RESETS a
# permlevel field the user cannot write, so the Approve click would revert the status
# to Draft and the submit would then fail with "Approval Status must be 'Approved' or
# 'Rejected'" — and it must be the ONLY role on the transition, or a user holding
# several gets one duplicate Approve button per role.
APPROVER_ROLES = ("Expense Approver",)

# ===================================================================
#  before_validate — mileage amounts + mirror stock rows into expenses
# ===================================================================


def sync_reimbursement_rows(doc, method=None):
	set_request_date(doc)
	set_approver(doc)
	set_default_cost_centers(doc)
	set_row_amounts(doc)
	sync_stock_items_to_expenses(doc)


def set_approver(doc):
	"""Keep ``custom_approver`` and the standard ``expense_approver`` in step.

	The custom field is the one on the form (the standard one is hidden — see
	reimbursement_setup.ensure_field_properties for why its link query is unusable
	here), but HRMS itself reads ``expense_approver``: it shares the document with
	that user (``share_doc_with_approver`` on every update), emails them when the
	claim is raised, and drives the approver's list in the HR mobile app off it.
	So the custom field WINS and is copied into the standard one, and an older
	claim that only has the standard value has it copied back the other way.
	"""
	if doc.get("custom_approver"):
		if doc.get("expense_approver") != doc.custom_approver:
			doc.expense_approver = doc.custom_approver
	elif doc.get("expense_approver"):
		doc.custom_approver = doc.expense_approver


def set_request_date(doc):
	"""The date the employee asked to be reimbursed.

	Deliberately its OWN field rather than reusing ``posting_date``: posting_date
	is the GL date and the accountant may well want to post a late-arriving claim
	into the current period, while the request date is a fact about the employee's
	request that must not move. Same reasoning separates the expense date (on each
	row), the approval date and the paid date — all four are independent.
	"""
	if not doc.get("custom_request_date"):
		doc.custom_request_date = doc.get("posting_date") or frappe.utils.nowdate()


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


def set_row_amounts(doc):
	"""Amount = Qty x Rate on every expense row.

	ONE mechanism for all expense types, which is what Marlene asked for: mileage
	is 120 miles x $0.70, a stock purchase is 10 units x $3.50 straight off the
	receipt, and a one-off is 1 x $50. Mileage is not a special case any more — it
	is just a claim type that pre-fills the rate and relabels the two columns
	(expense_claim.js does the relabelling).

	Rate is what drives the calculation. If the employee leaves Rate blank and
	types an Amount instead, we back-fill Rate from Amount / Qty rather than
	zeroing what they typed — so both directions of data entry work and the Qty
	column is never empty for reporting.

	**Mileage is the exception, deliberately.** On a mileage row the employee
	enters miles ONLY; the rate comes from the Expense Claim Type master and the
	amount is always miles x that rate. A hand-typed amount is overwritten rather
	than accepted, because the whole point of a mileage rate held centrally is
	that nobody gets to reimburse themselves at their own rate. If the master
	rate is blank the amount would silently be zero, so ``validate_mileage_rate``
	warns on save and blocks the submit instead of letting a $0 claim through.

	This is the authoritative copy; the form does the same arithmetic live so the
	number moves as you type, but an import or an API call gets the same result.
	"""
	for row in doc.get("expenses") or []:
		if not row.expense_type:
			continue

		# fetch_from only fires on the form; resolve the flags here too so an
		# import or API call behaves identically.
		claim_type = frappe.get_cached_value(
			"Expense Claim Type",
			row.expense_type,
			["custom_is_mileage", "custom_default_rate_per_mile", "custom_receipt_required"],
			as_dict=True,
		) or frappe._dict()

		row.custom_is_mileage_type = 1 if claim_type.get("custom_is_mileage") else 0
		row.custom_receipt_required = 1 if claim_type.get("custom_receipt_required") else 0

		if row.custom_is_mileage_type and not flt(row.custom_rate):
			row.custom_rate = flt(claim_type.get("custom_default_rate_per_mile"))

		qty = flt(row.custom_qty) or 1.0
		row.custom_qty = qty

		if flt(row.custom_rate):
			row.amount = flt(qty * flt(row.custom_rate), row.precision("amount"))
		elif row.custom_is_mileage_type:
			# Mileage with no rate on the master. Do NOT reverse-engineer a rate
			# from whatever was typed in Amount — that would be the employee
			# setting their own mileage rate. Zero it and let validate_mileage_rate
			# say why.
			row.amount = 0.0
		elif flt(row.amount):
			# Amount typed directly — derive the rate so Qty x Rate still reconciles.
			row.custom_rate = flt(flt(row.amount) / qty, row.precision("custom_rate"))

		amount = flt(row.amount, row.precision("amount"))
		# Sanctioned defaults to claimed; only raise it, never silently cut an
		# approver's reduction back up.
		if flt(row.sanctioned_amount) > amount or not flt(row.sanctioned_amount):
			row.sanctioned_amount = amount


def sync_stock_items_to_expenses(doc):
	"""Rebuild the auto-generated expense rows that mirror ``custom_stock_items``.

	The mirror rows are grouped by **account + cost center + date**, and the date
	comes from the ``Date`` column on the Purchased Items row. That grouping key is
	the fix for a real complaint: the Expense Date on a mirrored row used to be
	stamped with the claim's posting date on every save, so editing it in the
	Expenses table appeared to "jump back to today". The date is now a fact about
	the purchase, entered where the purchase is entered, and the Expenses row
	follows it (the field is greyed out on auto rows so it is clear which one to
	edit). Two receipts from different days therefore produce two dated rows
	instead of one lump.
	"""
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
		if not row.expense_date:
			row.expense_date = doc.posting_date or frappe.utils.nowdate()
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
		# Every part of the key is coerced to a string so the sort below cannot trip
		# over a None (cost center can legitimately be empty on a company with none).
		key = (row.expense_account or "", row.cost_center or "", str(row.expense_date or ""))
		by_account.setdefault(key, 0.0)
		by_account[key] += row.amount

	doc.custom_total_stock_amount = flt(total, doc.precision("custom_total_stock_amount"))

	for (account, cost_center, expense_date), amount in sorted(by_account.items()):
		if not flt(amount):
			continue
		doc.append(
			"expenses",
			{
				"expense_date": expense_date or None,
				"expense_type": STOCK_TYPE,
				"default_account": account or None,
				"cost_center": cost_center or None,
				"description": _(
					"Items purchased by employee on {0} — see Purchased Items table"
				).format(frappe.utils.formatdate(expense_date) if expense_date else ""),
				"amount": amount,
				"sanctioned_amount": amount,
				# The row aggregates several items into one account, so a real Qty
				# would be meaningless — 1 x the total keeps Qty x Rate honest.
				"custom_qty": 1,
				"custom_rate": amount,
				# The receipts live on the Purchased Items rows, which are validated
				# in their own right; don't ask for a second copy here.
				"custom_receipt_required": 0,
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
#  validate — request status, summary, approval date
# ===================================================================


def finalize_reimbursement_fields(doc, method=None):
	"""Runs on ``validate``, i.e. AFTER the standard Expense Claim validate has
	computed the totals and set ``status``. Everything here is derived, never
	typed."""
	set_expense_type_summary(doc)
	set_approval_date(doc)
	set_reimbursement_status(doc)
	warn_if_approver_cannot_approve(doc)
	validate_mileage_rate(doc, hard=False)


def warn_if_approver_cannot_approve(doc):
	"""Say so on save if the chosen approver will not be able to approve.

	``approval_status`` is a permlevel 1 field on Expense Claim. Frappe does not
	refuse a permlevel write it disallows — it silently RESETS the value on save.
	So an approver whose roles have no permlevel-1 write access clicks Approve, the
	status quietly reverts to Draft, and the submit then fails with "Approval Status
	must be 'Approved' or 'Rejected'" — an error that says nothing about roles. The
	workflow's transitions are already limited to the roles that work; this catches
	the other half, someone being named as approver who cannot act.

	A warning, not a block: naming the approver and granting them the role are two
	different people's jobs, and a claim should still be savable in between.
	"""
	approver = doc.get("custom_approver") or doc.get("expense_approver")
	if not approver or doc.docstatus != 0:
		return

	roles = set(frappe.get_roles(approver))
	if roles & set(APPROVER_ROLES):
		return

	frappe.msgprint(
		_(
			"{0} does not have the <b>{1}</b> role, so the <b>Approve</b> and "
			"<b>Reject</b> actions will not appear for them on this claim.<br><br>"
			"Tick that role on their User record, or name someone who already has it."
		).format(frappe.bold(approver), ", ".join(APPROVER_ROLES)),
		title=_("Approver Cannot Approve"),
		indicator="orange",
	)


def validate_mileage_rate(doc, hard=False):
	"""A mileage row is worthless without a rate — say so early, block at submit.

	The rate lives on the Expense Claim Type (``Default Rate per Mile``), which is
	the whole point: one number, maintained by the bookkeeper, applied to every
	employee. But a blank one does not fail loudly on its own — it just produces
	``miles x 0 = $0.00``, and a $0 claim is the kind of thing that gets submitted,
	approved and paid before anyone notices.

	Warn on save so the person filling the claim in sees it immediately; hard-block
	at submit, the same warn-then-block shape used for Hours Worked on the Salary
	Slip and for receipts here, so the site behaves one way throughout.
	"""
	offenders = []
	for row in doc.get("expenses") or []:
		if not row.get("custom_is_mileage_type"):
			continue
		if flt(row.get("custom_rate")):
			continue
		offenders.append((row.idx, row.expense_type))

	if not offenders:
		return

	types = sorted({t for _idx, t in offenders})
	links = ", ".join(
		frappe.utils.get_link_to_form("Expense Claim Type", t) for t in types
	)
	message = _(
		"No <b>Default Rate per Mile</b> is set on {0}, so the mileage row(s) "
		"{1} calculate to zero.<br><br>"
		"Open the Expense Claim Type and enter the rate per mile — it is applied "
		"to every claim from then on, so it only has to be set once."
	).format(links, ", ".join(str(idx) for idx, _t in offenders))

	if hard:
		frappe.throw(message, title=_("Mileage Rate Not Set"))

	frappe.msgprint(message, title=_("Mileage Rate Not Set"), indicator="orange")


def set_expense_type_summary(doc):
	"""Flatten the row-level claim types into one parent field.

	Marlene wants Expense Claim Type as a column in the list she works from, but
	the type lives on the child rows and a claim can hold several. Rather than
	force one claim per expense, we surface the distinct types joined together —
	so a single-expense claim (the normal case) reads exactly as she expects, and
	a mixed one still tells you what is in it.
	"""
	seen = []
	for row in doc.get("expenses") or []:
		if row.expense_type and row.expense_type not in seen:
			seen.append(row.expense_type)

	summary = ", ".join(seen)
	if len(summary) > 140:
		summary = f"{seen[0]} + {len(seen) - 1} more"
	doc.custom_expense_type_summary = summary


def set_approval_date(doc):
	"""Stamp the approval date the first time the claim is marked Approved.

	Only ever fills a BLANK value, and the field stays editable — Marlene was
	explicit that the approval date must be able to differ from the request and
	expense dates, which includes back-dating an approval that really happened
	last week. Clearing it again when a claim is un-approved keeps the field
	honest rather than leaving a stale date behind.
	"""
	if doc.approval_status == "Approved":
		if not doc.get("custom_approval_date"):
			doc.custom_approval_date = frappe.utils.nowdate()
	elif doc.docstatus == 0:
		doc.custom_approval_date = None


def set_reimbursement_status(doc):
	"""Derive the client's three-word status from the standard fields.

	Requested -> Approved -> Paid, mapped off ``docstatus`` / ``approval_status``
	/ ``status`` rather than kept as a second source of truth. Nothing here can
	drift, because nothing here is stored independently.

	The Draft -> Approved/Rejected -> Paid **Workflow** added later is a second
	*display* of this same derivation, not a second source: its transitions write
	the standard ``approval_status`` that this function reads, and its Paid state
	is stamped from here by ``stamp_workflow_state``. See
	setup/expense_claim_workflow.py for the full argument.
	"""
	if doc.docstatus == 2:
		doc.custom_reimbursement_status = "Cancelled"
		return

	if doc.approval_status == "Rejected":
		doc.custom_reimbursement_status = "Rejected"
		return

	if doc.docstatus == 0:
		# Saved but not yet put through by the approver — the employee has asked.
		doc.custom_reimbursement_status = (
			"Approved" if doc.approval_status == "Approved" else "Requested"
		)
		return

	# Submitted: the standard status already knows whether it has been reimbursed.
	doc.custom_reimbursement_status = "Paid" if doc.status == "Paid" else "Approved"


# ===================================================================
#  before_submit — receipts
# ===================================================================


def validate_receipts(doc, method=None):
	"""Refuse to submit a claim that is missing a receipt.

	Enforced at SUBMIT, not on save, so a half-finished request can still be
	parked as a draft — the same trade-off already used for Hours Worked on the
	Salary Slip (warn on save, block on submit), kept consistent so the site
	behaves one way throughout.

	Which types need a receipt is configuration, not code: the
	``Receipt Required`` checkbox on each Expense Claim Type. It ships ticked for
	everything except Mileage, because there is no receipt for driving your own
	car — but if the client later decides meals under $10 don't need one either,
	that is a checkbox, not a change request.

	Also the last gate on the mileage rate — a claim whose mileage rows compute to
	zero must not reach the ledger.

	**A rejection is exempt from both.** ERPNext records a rejection by SUBMITTING
	the claim with approval_status = Rejected (it zeroes every sanctioned amount, so
	nothing reaches the ledger). Enforcing receipts on that path would mean a claim
	could not be turned down precisely because the receipt everyone is waiting for
	is missing — the approver would have to delete the employee's request instead of
	answering it.
	"""
	if doc.approval_status == "Rejected":
		return

	validate_mileage_rate(doc, hard=True)

	missing = []

	for row in doc.get("expenses") or []:
		if row.get("custom_auto_generated"):
			continue  # its receipts sit on the Purchased Items rows below
		required = row.get("custom_receipt_required")
		if required is None:
			required = frappe.get_cached_value(
				"Expense Claim Type", row.expense_type, "custom_receipt_required"
			)
		if required and not row.get("custom_receipt"):
			missing.append(_("Expenses row {0} ({1})").format(row.idx, row.expense_type))

	for row in doc.get("custom_stock_items") or []:
		if not row.get("receipt"):
			missing.append(_("Purchased Items row {0} ({1})").format(row.idx, row.item_code))

	if not missing:
		return

	frappe.throw(
		_("Attach a receipt to the following before submitting:<br><br>{0}").format(
			"<br>".join(missing)
		),
		title=_("Receipt Missing"),
	)


# ===================================================================
#  Payment vouchers — keep the paid state in step
# ===================================================================


def sync_claims_from_voucher(doc, method=None):
	"""Journal Entry / Payment Entry submit or cancel.

	HRMS already recalculates ``total_amount_reimbursed`` and the standard
	``status`` from the voucher's Expense Claim references (its own hooks on the
	same events, which run before ours because ls_foods installs last). All that
	is left is to carry that through to the three ls_foods fields the payroll
	clerk reads.
	"""
	table, field = (
		("accounts", "reference_type")
		if doc.doctype == "Journal Entry"
		else ("references", "reference_doctype")
	)

	for row in doc.get(table) or []:
		if row.get(field) == "Expense Claim" and row.get("reference_name"):
			refresh_reimbursement_state(row.reference_name, voucher=doc)


def stamp_workflow_state(doc, method=None):
	"""Keep the Workflow state AND the Reimbursement Status on the standard fields,
	on submit and on cancel.

	The workflow itself handles the states a person clicks. Two it cannot:

	* **Paid** — nobody approves a payment into existence; it becomes true when the
	  Salary Slip accrual JE, Journal Entry or Payment Entry that references the
	  claim is submitted, and HRMS's own handler has already recalculated
	  ``status`` by then. Also stamped here at submit for an "Is Paid" claim, which
	  is Paid the moment it is submitted.
	* **Cancelled** — a claim can be cancelled programmatically (an amend, a script,
	  a cancelled Stock Entry chain) rather than through the workflow action, and a
	  cancelled document showing "Approved" as its status is exactly the drift a
	  workflow is supposed to prevent.

	``custom_reimbursement_status`` is stamped from the same derivation for one
	specific reason: it is normally filled on ``validate``, and **cancel does not
	run validate** (``Document._save`` skips ``_validate`` when the action is
	cancel). Without this, a cancelled claim kept reading "Approved" in the list
	the payroll clerk works from.

	Written with ``db_set``: the document is submitted or cancelled, so a normal
	save would be refused, and both values are derived — there is nothing here for
	validation to protect.
	"""
	state = derive_state(
		{"docstatus": doc.docstatus, "approval_status": doc.approval_status, "status": doc.status}
	)

	if doc.get(STATE_FIELD) != state:
		doc.db_set(STATE_FIELD, state, update_modified=False)

	# The two vocabularies agree on everything a submitted or cancelled claim can
	# be (Approved / Rejected / Paid / Cancelled); they differ only on a draft,
	# which is "Requested" to the client and never reaches this function.
	if doc.get("custom_reimbursement_status") != state:
		doc.db_set("custom_reimbursement_status", state, update_modified=False)


def refresh_reimbursement_state(claim_name, voucher=None):
	"""Re-derive status / paid date / paying slip on an already-submitted claim.

	Uses ``db_set``-style writes on purpose: the claim is submitted, so a normal
	save would be rejected, and these are all derived fields that no one types.
	"""
	claim = frappe.db.get_value(
		"Expense Claim",
		claim_name,
		["docstatus", "approval_status", "status", "custom_paid_date", "custom_salary_slip"],
		as_dict=True,
	)
	if not claim:
		return

	if claim.docstatus == 2:
		status = "Cancelled"
	elif claim.approval_status == "Rejected":
		status = "Rejected"
	elif claim.status == "Paid":
		status = "Paid"
	else:
		status = "Approved"

	# The workflow state says the same thing in the words the client asked for, and
	# this is where Paid arrives (and leaves again, if the payment is cancelled).
	values = {"custom_reimbursement_status": status, STATE_FIELD: derive_state(claim)}

	if status == "Paid":
		if not claim.custom_paid_date:
			values["custom_paid_date"] = (
				voucher.get("posting_date") if voucher else None
			) or frappe.utils.nowdate()
	else:
		# Payment reversed — don't leave a paid date on an unpaid claim.
		values["custom_paid_date"] = None
		values["custom_salary_slip"] = None

	frappe.db.set_value("Expense Claim", claim_name, values, update_modified=False)


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

	# Last resort: the company default, and failing that ANY real expense account.
	# The final fallback matters more than it looks — company "Loren Slabaugh" has
	# no default expense account and no "Stock Received But Not Billed" set, so
	# without it every Purchased Items row resolved to nothing and the employee
	# was met with a mandatory-field error on a column they are not supposed to
	# have to think about. A placeholder the bookkeeper can re-point beats a form
	# that will not save.
	return _default_expense_account(company)


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

	# A rejection is also a submit (ERPNext's way of recording one), and it zeroes
	# every sanctioned amount — so there is nothing owed and nothing was bought on
	# the company's behalf. Receiving the goods anyway would put stock on the books
	# that no payable ever balances.
	if doc.approval_status == "Rejected":
		return

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
