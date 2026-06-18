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
