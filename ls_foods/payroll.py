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
	if not doc.company or not (doc.earnings or doc.deductions):
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

	def add(account, debit=0.0, credit=0.0):
		debit, credit = flt(debit, precision), flt(credit, precision)
		if not debit and not credit:
			return
		lines.append({
			"account": account,
			"debit_in_account_currency": debit,
			"credit_in_account_currency": credit,
			"cost_center": cost_center,
		})
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
