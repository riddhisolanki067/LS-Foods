"""v0_0_2 — Employee Reimbursement module, retirement age 65, payment date fields.

Idempotent; re-runnable. Covers the four changes requested by the client:

  1. Retirement age 65  -> ls_foods.setup.hr_settings
  2. Reimbursement      -> ls_foods.setup.reimbursement_setup
  3. Hours Worked guard -> code only (hooks.py before_submit), nothing to patch
  4. Payment date       -> new Salary Slip custom fields in payroll_setup
"""

import frappe

from ls_foods.setup import hr_settings, payroll_setup, reimbursement_setup


def execute():
	# New Salary Slip payment-tracking fields (custom_payment_date /
	# custom_payment_journal_entry) live in the payroll field map.
	payroll_setup.ensure_custom_fields()

	hr_settings.run()
	reimbursement_setup.run()

	frappe.clear_cache()
