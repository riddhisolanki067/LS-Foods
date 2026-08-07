"""LS Foods — paying approved expense reimbursements out with the paycheck.

This is the second half of the reimbursement flow. ``ls_foods/reimbursement.py``
handles the request itself (Expense Claim); this module handles what the payroll
clerk does with an approved one.

Wired in hooks.py::

    "Salary Slip": {
        "validate":  "ls_foods.reimbursement_payroll.apply_reimbursements",
        "on_submit": (handled inside ls_foods.payroll.post_accrual_journal_entry)
    }

THE ONE THING TO UNDERSTAND HERE
--------------------------------
A reimbursement is **not wages**. The employee is being paid back for money they
already spent; it is not income, it is not subject to FICA / FUTA / SUTA / income
tax withholding, and it must not appear in W-2 gross wages.

That matters on this site more than most, because every tax component in the
Household salary structure is a hand-written formula keyed off ``gross_pay``::

    FICA Social Security - Employee:  gross_pay * 0.062  (with YTD thresholds)
    IN State Income Tax:              gross_pay * 0.0295
    ... and six more

So if reimbursements were added as an ordinary Earning row they would land in
``gross_pay`` and every one of those formulas would quietly tax them — and
``custom_ytd_gross_pay`` would drift too, moving the FICA/FUTA/SUTA wage-base
caps. That is a real tax error, not a cosmetic one.

Hence the design: reimbursements are held in their OWN table, they never touch
``gross_pay``, and the total is added to ``net_pay`` after deductions are worked
out. The pay stub reads:

    Gross Pay                 (wages only — taxable)
    less Deductions           (computed on wages only)
    plus Reimbursements       (not taxed)
    = Net Pay

The alternative — rewriting all nine tax formulas onto a new "taxable wages"
base — would have put the already-verified withholding engine at risk to gain
nothing. This way the tax engine is untouched.

THE ACCOUNTING
--------------
The Expense Claim already booked the expense when it was submitted::

    Expense Claim   Dr  <expense account from the claim type>   84.00
                        Cr  Employee Reimbursements Payable         84.00

So the paycheck must NOT book the expense a second time. It clears the payable::

    Salary Slip JE  Dr  Employee Reimbursements Payable         84.00
                        Cr  Payroll Payable (net pay)               84.00

and the existing payment entry then pays Payroll Payable out of the bank, wages
and reimbursement together, in one payment — which is exactly what the employee
sees in their account.

If the clerk reassigns the expense account on a row, the same journal entry also
carries a reclassification::

                    Dr  <new account>                          84.00
                        Cr  <account the claim posted to>          84.00

which nets to zero against the payable leg, so the paycheck total is unaffected
and the cost simply lands where the clerk decided it belongs.

Marking the claim Paid is left to HRMS: the payable line carries
``reference_type = "Expense Claim"``, and HRMS's own Journal Entry hook reads
that, recalculates ``total_amount_reimbursed`` and flips the status to Paid.
``ls_foods.reimbursement.sync_claims_from_voucher`` then carries it through to
the Requested/Approved/Paid field and stamps the paid date.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

from hrms.hr.doctype.expense_claim.expense_claim import get_outstanding_amount_for_claim


# ===================================================================
#  Fetching approved claims onto the slip
# ===================================================================


@frappe.whitelist()
def get_approved_reimbursements(salary_slip=None, employee=None, company=None, upto_date=None):
	"""Rows for the "Get Approved Reimbursements" button on the Salary Slip.

	Only claims that are genuinely payable are offered:
	  * submitted (docstatus 1) and approval_status = Approved,
	  * for THIS employee and THIS company,
	  * with something still outstanding,
	  * not already sitting on another salary slip that is drafted or submitted.

	``upto_date`` defaults to the slip's end date, so a claim approved after the
	pay period closed rolls into the next run rather than silently backdating
	itself into a period that has already been reported.
	"""
	if salary_slip and not (employee and company):
		slip = frappe.db.get_value(
			"Salary Slip", salary_slip, ["employee", "company", "end_date"], as_dict=True
		)
		if slip:
			employee = employee or slip.employee
			company = company or slip.company
			upto_date = upto_date or slip.end_date

	if not employee:
		frappe.throw(_("Select an Employee first."))

	filters = {
		"employee": employee,
		"docstatus": 1,
		"approval_status": "Approved",
		"status": ["!=", "Paid"],
	}
	if company:
		filters["company"] = company
	if upto_date:
		filters["custom_approval_date"] = ["<=", getdate(upto_date)]

	claims = frappe.get_all(
		"Expense Claim",
		filters=filters,
		fields=[
			"name",
			"custom_expense_type_summary",
			"custom_request_date",
			"custom_approval_date",
			"remark",
		],
		order_by="custom_approval_date asc, name asc",
	)

	claimed_elsewhere = _claims_on_other_slips(employee, exclude_slip=salary_slip)

	rows = []
	for claim in claims:
		if claim.name in claimed_elsewhere:
			continue

		outstanding = get_outstanding_amount_for_claim(claim.name)
		if flt(outstanding) <= 0:
			continue

		account, cost_center = _claim_expense_account(claim.name)
		rows.append(
			{
				"expense_claim": claim.name,
				"expense_type": claim.custom_expense_type_summary,
				"request_date": claim.custom_request_date,
				"approval_date": claim.custom_approval_date,
				"outstanding_amount": flt(outstanding),
				"amount": flt(outstanding),
				"expense_account": account,
				"original_account": account,
				"cost_center": cost_center,
				"description": claim.remark,
			}
		)

	return rows


def _claims_on_other_slips(employee, exclude_slip=None):
	"""Claims already parked on another **draft** slip.

	Only drafts. A draft's amount has not been posted anywhere yet, so it is
	invisible to the outstanding-amount calculation — fetch the same claim onto
	two drafts and both would happily claim the full balance, with the second one
	only failing at submit, which is a confusing place to find out.

	A SUBMITTED slip is deliberately not blocking. Its payment has already
	reduced the claim's outstanding amount, so paying a claim over two pay runs
	(the instalment case the Amount field is there for) is both safe and
	intentional: the outstanding check in ``_validate_row`` caps the second slip
	at whatever is genuinely left, and HRMS's own journal-entry check enforces
	the same ceiling independently.
	"""
	filters = [
		["Salary Slip", "employee", "=", employee],
		["Salary Slip", "docstatus", "=", 0],
		["Salary Slip Reimbursement", "expense_claim", "is", "set"],
	]
	if exclude_slip:
		filters.append(["Salary Slip", "name", "!=", exclude_slip])

	rows = frappe.get_all(
		"Salary Slip",
		filters=filters,
		fields=["`tabSalary Slip Reimbursement`.expense_claim as claim"],
	)
	return {r.claim for r in rows if r.claim}


def _claim_expense_account(claim_name):
	"""The account (and cost center) an Expense Claim actually debited.

	Returns ``(None, cost_center)`` when the claim spread itself across more than
	one account — there is no single account to reclassify from in that case, so
	the Expense Account column is left blank and the reclass is skipped rather
	than guessed at. The payable is still cleared correctly either way.
	"""
	rows = frappe.get_all(
		"Expense Claim Detail",
		filters={"parent": claim_name, "parenttype": "Expense Claim"},
		fields=["default_account", "cost_center"],
	)
	accounts = {r.default_account for r in rows if r.default_account}
	cost_centers = {r.cost_center for r in rows if r.cost_center}

	account = accounts.pop() if len(accounts) == 1 else None
	cost_center = cost_centers.pop() if len(cost_centers) == 1 else None
	return account, cost_center


# ===================================================================
#  validate — totals and the net pay adjustment
# ===================================================================


def apply_reimbursements(doc, method=None):
	"""Salary Slip ``validate``, running AFTER the standard HRMS validate.

	HRMS has by now computed gross_pay, every deduction, net_pay, the rounded
	total, the words and the YTD/MTD net figures. We add the reimbursement total
	on top of the net-pay side of that — and deliberately leave gross_pay alone,
	for the tax reasons in this module's docstring.

	Ordering note: this is registered BEFORE ``set_net_pay_in_words`` in hooks.py
	so the amount in words on the pay stub matches the adjusted net pay.
	"""
	rows = doc.get("custom_reimbursements") or []

	total = 0.0
	for row in rows:
		_validate_row(doc, row)
		total += flt(row.amount)

	total = flt(total, doc.precision("custom_total_reimbursement") or 2)
	doc.custom_total_reimbursement = total

	if not total:
		return

	precision = doc.precision("net_pay") or 2
	doc.net_pay = flt(flt(doc.net_pay) + total, precision)
	doc.rounded_total = flt(round(doc.net_pay), precision)
	doc.base_net_pay = flt(flt(doc.net_pay) * flt(doc.exchange_rate or 1), precision)
	doc.base_rounded_total = flt(round(doc.base_net_pay), precision)

	# HRMS accumulates these from net_pay during its own validate, so they need
	# the same top-up to stay consistent with the figure on the stub.
	doc.year_to_date = flt(flt(doc.year_to_date) + total, precision)
	doc.month_to_date = flt(flt(doc.month_to_date) + total, precision)

	doc.set_net_total_in_words()


def _validate_row(doc, row):
	"""Guard every reimbursement row before it can affect the paycheck."""
	if not row.expense_claim:
		frappe.throw(_("Reimbursements row {0}: pick an Expense Claim.").format(row.idx))

	claim = frappe.db.get_value(
		"Expense Claim",
		row.expense_claim,
		["employee", "company", "docstatus", "approval_status", "employee_name"],
		as_dict=True,
	)
	if not claim:
		frappe.throw(_("Reimbursements row {0}: {1} no longer exists.").format(row.idx, row.expense_claim))

	if claim.docstatus != 1:
		frappe.throw(
			_("Reimbursements row {0}: Expense Claim {1} is not submitted.").format(
				row.idx, frappe.bold(row.expense_claim)
			)
		)

	if claim.approval_status != "Approved":
		frappe.throw(
			_(
				"Reimbursements row {0}: Expense Claim {1} has not been approved "
				"(approval status is {2}). Only approved claims can be paid."
			).format(row.idx, frappe.bold(row.expense_claim), claim.approval_status)
		)

	if claim.employee != doc.employee:
		frappe.throw(
			_("Reimbursements row {0}: Expense Claim {1} belongs to {2}, not {3}.").format(
				row.idx, frappe.bold(row.expense_claim), claim.employee_name, doc.employee_name
			)
		)

	if claim.company != doc.company:
		frappe.throw(
			_("Reimbursements row {0}: Expense Claim {1} is for company {2}, not {3}.").format(
				row.idx, frappe.bold(row.expense_claim), claim.company, doc.company
			)
		)

	# Guard against the same claim being paid twice — here, and on another slip.
	duplicates = [
		r for r in (doc.get("custom_reimbursements") or []) if r.expense_claim == row.expense_claim
	]
	if len(duplicates) > 1:
		frappe.throw(
			_("Expense Claim {0} is listed more than once in Reimbursements.").format(
				frappe.bold(row.expense_claim)
			)
		)

	if row.expense_claim in _claims_on_other_slips(doc.employee, exclude_slip=doc.name):
		frappe.throw(
			_(
				"Expense Claim {0} is already on another <b>draft</b> salary slip for {1}. "
				"Remove it from one of them, or submit that slip first."
			).format(frappe.bold(row.expense_claim), doc.employee_name)
		)

	outstanding = flt(get_outstanding_amount_for_claim(row.expense_claim))
	row.outstanding_amount = outstanding

	if flt(row.amount) <= 0:
		row.amount = outstanding

	if flt(row.amount) > outstanding:
		frappe.throw(
			_(
				"Reimbursements row {0}: {1} is more than the {2} still outstanding "
				"on Expense Claim {3}."
			).format(
				row.idx,
				frappe.format(flt(row.amount), {"fieldtype": "Currency"}),
				frappe.format(outstanding, {"fieldtype": "Currency"}),
				frappe.bold(row.expense_claim),
			)
		)

	if not row.original_account:
		row.original_account, default_cc = _claim_expense_account(row.expense_claim)
		if not row.cost_center:
			row.cost_center = default_cc


# ===================================================================
#  Journal entry lines — called from ls_foods.payroll
# ===================================================================


def reimbursement_journal_lines(doc):
	"""Extra Journal Entry lines for the reimbursements on this slip.

	Returned as ``(account, debit, credit, cost_center, party_type, party,
	reference_type, reference_name)`` tuples for ``ls_foods.payroll`` to fold into
	the payroll accrual entry — one entry per slip rather than a second voucher,
	so the ledger shows one payroll transaction per pay run.

	Two kinds of line:

    1. Dr Employee Reimbursements Payable, party = the employee, referenced back
       to the Expense Claim. Clears what the claim credited, and the reference is
       what makes HRMS mark the claim Paid. Debits push the balancing figure up,
       so the Payroll Payable credit — the net pay — grows by the same amount.

    2. When the clerk reassigned the account: Dr new / Cr original. Equal and
       opposite, so the paycheck total does not move; only the cost's home does.
	"""
	lines = []

	for row in doc.get("custom_reimbursements") or []:
		amount = flt(row.amount)
		if not amount:
			continue

		payable = _reimbursement_payable_account(doc.company, row.expense_claim)
		cost_center = row.cost_center or None

		lines.append(
			{
				"account": payable,
				"debit": amount,
				"credit": 0.0,
				"cost_center": cost_center,
				"party_type": "Employee",
				"party": doc.employee,
				"reference_type": "Expense Claim",
				"reference_name": row.expense_claim,
			}
		)

		# Reclassification, only when there is genuinely something to move.
		if row.expense_account and row.original_account and row.expense_account != row.original_account:
			lines.append(
				{
					"account": row.expense_account,
					"debit": amount,
					"credit": 0.0,
					"cost_center": cost_center,
				}
			)
			lines.append(
				{
					"account": row.original_account,
					"debit": 0.0,
					"credit": amount,
					"cost_center": cost_center,
				}
			)

	return lines


def _reimbursement_payable_account(company, claim_name=None):
	"""The account the claim credited, so we debit exactly that one back.

	Reads the claim's own ``payable_account`` first rather than assuming the
	company default — if the default was changed between the claim being
	submitted and payday, the claim's own value is the one carrying the balance.
	"""
	account = frappe.db.get_value("Expense Claim", claim_name, "payable_account") if claim_name else None
	account = account or frappe.get_cached_value(
		"Company", company, "default_expense_claim_payable_account"
	)

	if not account:
		frappe.throw(
			_(
				"Set <b>Default Expense Claim Payable Account</b> on company {0} before "
				"paying reimbursements through payroll."
			).format(company)
		)
	return account


# ===================================================================
#  After the accrual JE is posted — stamp the claims
# ===================================================================


def mark_claims_paid(doc, journal_entry):
	"""Record which slip paid each claim.

	HRMS has already flipped the claim to Paid (it reads the Expense Claim
	reference off the journal entry via its own hook) and
	``ls_foods.reimbursement.sync_claims_from_voucher`` has stamped the paid date.
	All that is left is the back-link, so the claim tells you which paycheck it
	went out on.
	"""
	for row in doc.get("custom_reimbursements") or []:
		if not row.expense_claim:
			continue
		frappe.db.set_value(
			"Expense Claim",
			row.expense_claim,
			{"custom_salary_slip": doc.name},
			update_modified=False,
		)


def unlink_claims(doc):
	"""Salary Slip cancelled — drop the back-link.

	The paid status and paid date are reversed by
	``sync_claims_from_voucher`` when the accrual journal entry is cancelled;
	this only clears the pointer to a slip that no longer pays anything.
	"""
	for row in doc.get("custom_reimbursements") or []:
		if not row.expense_claim:
			continue
		if frappe.db.get_value("Expense Claim", row.expense_claim, "custom_salary_slip") == doc.name:
			frappe.db.set_value(
				"Expense Claim", row.expense_claim, {"custom_salary_slip": None}, update_modified=False
			)
