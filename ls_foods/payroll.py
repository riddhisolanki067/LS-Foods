"""LS Foods household payroll — Salary Slip document events.

This replaces the DB-resident Server Script "Salary Slip - Set YTD Gross Pay".
It is wired in hooks.py via:

    doc_events = {"Salary Slip": {"before_validate": "ls_foods.payroll.set_ytd_gross_pay"}}

Why this exists: the US household tax formulas on the salary components need a
year-to-date gross figure (to apply the FICA $3,000 / FUTA-SUTA $1,000 start
thresholds and the SS $184,500 / FUTA $7,000 / SUTA $9,500 wage-base caps).
ERPNext does not supply a usable YTD value during salary-formula evaluation, so
we compute it here, before validation runs, and stash it on the read-only
Salary Slip field ``custom_ytd_gross_pay``. The component formulas then read it.

Unlike a Server Script, an app hook runs regardless of the bench-level
``server_script_enabled`` flag — which removes the single biggest fragility of
the previous no-app deployment.
"""

import frappe
from frappe import _
from frappe.utils import flt

from ls_foods.reimbursement_payroll import (
	mark_claims_paid,
	reimbursement_journal_lines,
	unlink_claims,
)


def set_ytd_gross_pay(doc, method=None):
	"""Before Validate on Salary Slip.

	Fill ``custom_ytd_gross_pay`` with the employee's calendar-year gross pay
	from prior **submitted** salary slips (slips whose pay period ends strictly
	before this slip's start date). This is the figure the threshold/cap
	formulas on the salary components read.
	"""
	ytd = 0
	if doc.employee and doc.start_date:
		year_start = str(frappe.utils.getdate(doc.start_date).year) + "-01-01"
		rows = frappe.get_all(
			"Salary Slip",
			filters={
				"employee": doc.employee,
				"docstatus": 1,
				"start_date": [">=", year_start],
				"end_date": ["<", doc.start_date],
				"name": ["!=", doc.name or ""],
			},
			fields=["sum(gross_pay) as total"],
		)
		if rows and rows[0].get("total"):
			ytd = rows[0].get("total")
	doc.custom_ytd_gross_pay = ytd


def set_mtd_gross_pay(doc, method=None):
	"""Validate on Salary Slip.

	Fill ``custom_mtd_gross_pay`` with the employee's **month-to-date** gross pay,
	grouped by the slip's ``posting_date`` (NOT the pay-period start/end). This is
	a true MTD figure: the sum of ``gross_pay`` from prior **submitted** slips
	whose posting_date falls in the same calendar month, PLUS this slip's own
	gross_pay. So when two separate slips are posted in the same month, the later
	slip shows the running month total.

	Runs on ``validate`` (not before_validate) because ``gross_pay`` is only
	computed during the standard Salary Slip validate, and we need it to include
	the current slip.

	To make this behave like ``custom_ytd_gross_pay`` instead (prior periods only,
	excluding the current slip), drop the ``+ flt(doc.gross_pay)`` below and wire
	it under ``before_validate`` in hooks.py.
	"""
	mtd = 0
	if doc.employee and doc.posting_date:
		pdate = frappe.utils.getdate(doc.posting_date)
		month_start = pdate.replace(day=1)
		next_month = frappe.utils.add_months(month_start, 1)  # first day of next month
		rows = frappe.get_all(
			"Salary Slip",
			filters=[
				["employee", "=", doc.employee],
				["docstatus", "=", 1],
				["posting_date", ">=", month_start],
				["posting_date", "<", next_month],
				["name", "!=", doc.name or ""],
			],
			fields=["sum(gross_pay) as total"],
		)
		if rows and rows[0].get("total"):
			mtd = flt(rows[0].get("total"))
	doc.custom_mtd_gross_pay = flt(mtd) + flt(doc.gross_pay)


# ===================================================================
#  Accrual Journal Entry on standalone Salary Slip submit/cancel
# ===================================================================
# When a Salary Slip is submitted on its own (NOT through a Payroll Entry),
# HRMS posts NOTHING to the ledger. These hooks build + submit the payroll
# accrual Journal Entry directly from the slip, so a single salary slip is all
# you need each week. EVERYTHING is derived at runtime — accounts come from each
# component's Salary Component Account mapping, the payable account from the
# company, the cost center from employee/department/company, and debit-vs-credit
# from the component type, its do_not_include_in_total flag, and each account's
# root_type. No account numbers, company names, component names, or rates are
# hardcoded.
#
# Correct double-entry it produces, per slip:
#   Earnings                      -> Debit  the mapped (expense) account
#   Employee deductions (dnit=0)  -> Credit the mapped (payable) account  (reduces net)
#   Employer costs      (dnit=1)  -> Debit the Expense account + Credit the
#                                    Liability account  (does NOT reduce net pay)
#   Net pay (balancing figure)    -> Credit the company Payroll Payable account
#
# Wired in hooks.py:
#   "Salary Slip": {
#       "on_submit": "ls_foods.payroll.post_accrual_journal_entry",
#       "on_cancel": "ls_foods.payroll.reverse_accrual_journal_entry",
#   }


def _payroll_payable_account(company):
	return frappe.get_cached_value("Company", company, "default_payroll_payable_account")


def _payroll_cost_center(doc):
	"""Employee payroll cost center -> department -> company default. All derived."""
	cc = None
	if doc.employee:
		cc = frappe.db.get_value("Employee", doc.employee, "payroll_cost_center")
		if not cc:
			dept = frappe.db.get_value("Employee", doc.employee, "department")
			if dept:
				cc = frappe.db.get_value("Department", dept, "payroll_cost_center")
	if not cc:
		cc = frappe.get_cached_value("Company", doc.company, "cost_center")
	return cc


def _component_accounts(component, company):
	"""GL account(s) mapped to a salary component for this company (dynamic)."""
	return frappe.get_all(
		"Salary Component Account",
		filters={"parent": component, "company": company},
		pluck="account",
	)


def post_accrual_journal_entry(doc, method=None):
	"""On Salary Slip submit: build + submit the accrual Journal Entry from the
	slip's own components. Skipped when submitted via a Payroll Entry (HRMS posts
	its own accrual there) or when an active accrual JE already exists."""
	if frappe.flags.get("via_payroll_entry"):
		return
	existing = doc.get("journal_entry")
	if existing and frappe.db.get_value("Journal Entry", existing, "docstatus") == 1:
		return  # already has an active accrual JE (idempotent / re-submit guard)
	if not doc.company or not (doc.earnings or doc.deductions or doc.get("custom_reimbursements")):
		return

	company = doc.company
	payable_account = _payroll_payable_account(company)
	if not payable_account:
		frappe.throw(_(
			"Set <b>Default Payroll Payable Account</b> on company {0} to auto-post "
			"the payroll journal entry."
		).format(company))

	cost_center = _payroll_cost_center(doc)
	precision = frappe.get_precision("Journal Entry Account", "debit_in_account_currency") or 2

	lines = []
	totals = {"debit": 0.0, "credit": 0.0}

	def add(account, debit=0.0, credit=0.0, **extra):
		debit, credit = flt(debit, precision), flt(credit, precision)
		if not debit and not credit:
			return
		line = {
			"account": account,
			"debit_in_account_currency": debit,
			"credit_in_account_currency": credit,
			"cost_center": cost_center,
		}
		# Reimbursement lines carry their own cost center, a party (the payable
		# account demands one) and the Expense Claim reference that lets HRMS mark
		# the claim Paid.
		line.update({k: v for k, v in extra.items() if v})
		lines.append(line)
		totals["debit"] += debit
		totals["credit"] += credit

	def accounts_for(component):
		accts = _component_accounts(component, company)
		if not accts:
			frappe.throw(_("Set a GL account for salary component {0} (company {1}).")
			             .format(component, company))
		return accts

	# Earnings -> debit their (expense) account
	for e in doc.earnings:
		amt = flt(e.amount, precision)
		if not amt:
			continue
		for acct in accounts_for(e.salary_component):
			add(acct, debit=amt)

	# Deductions
	for d in doc.deductions:
		amt = flt(d.amount, precision)
		if not amt:
			continue
		dnit = frappe.get_cached_value("Salary Component", d.salary_component, "do_not_include_in_total")
		accts = accounts_for(d.salary_component)
		if not dnit:
			# Employee withholding -> credit payable account(s); reduces net pay
			for acct in accts:
				add(acct, credit=amt)
		else:
			# Employer cost -> book expense (debit) + payable (credit) by root_type;
			# does NOT reduce net pay
			for acct in accts:
				if frappe.get_cached_value("Account", acct, "root_type") == "Expense":
					add(acct, debit=amt)
				else:
					add(acct, credit=amt)

	# Expense reimbursements riding on this paycheck.
	#   Dr Employee Reimbursements Payable  -> clears what the Expense Claim
	#      credited when it was submitted; the expense itself was booked then, so
	#      it is deliberately NOT booked again here.
	#   Dr new / Cr old                     -> only when the payroll clerk
	#      reassigned the account; nets to zero, so the paycheck is unaffected.
	# Because these are net debits, the balancing figure below grows by the same
	# amount — i.e. Payroll Payable is credited with wages AND reimbursement, and
	# the existing payment entry pays the employee once, for the total.
	# See ls_foods/reimbursement_payroll.py for the full rationale.
	for line in reimbursement_journal_lines(doc):
		add(
			line["account"],
			debit=line.get("debit"),
			credit=line.get("credit"),
			cost_center=line.get("cost_center"),
			party_type=line.get("party_type"),
			party=line.get("party"),
			reference_type=line.get("reference_type"),
			reference_name=line.get("reference_name"),
		)

	# Net pay -> credit Payroll Payable (balancing figure; guarantees a clean entry)
	net = flt(totals["debit"] - totals["credit"], precision)
	if net > 0:
		add(payable_account, credit=net)
	elif net < 0:
		add(payable_account, debit=-net)

	if flt(totals["debit"] - totals["credit"], precision) != 0:
		frappe.throw(_("Payroll journal entry is unbalanced (Dr {0} vs Cr {1}). "
		               "Check the salary component GL-account mappings.")
		             .format(totals["debit"], totals["credit"]))

	if len(lines) < 2:
		return

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = doc.posting_date or doc.end_date
	# Same as HRMS's payroll accrual: tax payable accounts post without a party.
	je.party_not_required = True
	je.user_remark = _("Payroll accrual for {0} ({1} to {2}) - Salary Slip {3}").format(
		doc.employee_name or doc.employee, doc.start_date, doc.end_date, doc.name)
	for ln in lines:
		je.append("accounts", ln)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()

	doc.db_set("journal_entry", je.name, update_modified=False)

	# HRMS's own Journal Entry hook has already read the Expense Claim references
	# off this entry and flipped those claims to Paid; this only records which
	# paycheck did it.
	mark_claims_paid(doc, je.name)

	frappe.msgprint(_("Posted payroll journal entry {0}.").format(je.name),
	                alert=True, indicator="green")


def reverse_accrual_journal_entry(doc, method=None):
	"""On Salary Slip cancel: unlink and cancel the accrual Journal Entry it created."""
	je = doc.get("journal_entry") or frappe.db.get_value("Salary Slip", doc.name, "journal_entry")
	if doc.get("journal_entry"):
		doc.db_set("journal_entry", "", update_modified=False)
	if je and frappe.db.exists("Journal Entry", je):
		jdoc = frappe.get_doc("Journal Entry", je)
		if jdoc.docstatus == 1:
			jdoc.flags.ignore_permissions = True
			jdoc.cancel()

	# Cancelling the JE already put the claims back to unpaid (HRMS recalculates
	# the reimbursed amount, ls_foods.reimbursement clears the paid date). Drop
	# the back-link to a slip that no longer pays them, so they can be picked up
	# on the next run.
	unlink_claims(doc)
