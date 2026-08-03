"""LS Foods US household payroll — idempotent, company-wide setup.

This packages the *standard, reusable* payroll engine so it deploys with the app.
It is NOT tied to any one employee — you onboard employees the normal way and
assign them the salary structure (see the deployment guide).

What it sets up (idempotent — safe to re-run):

  1. Custom fields (company-wide):
       Employee.custom_rate_per_hour          - the worker's hourly rate
       Employee.custom_social_security_number - mandatory SSN
       Salary Slip.custom_hours_worked        - hours entered each pay period
       Salary Slip.custom_ytd_gross_pay       - read-only, auto-filled by the hook
     Also exported as fixtures (fixtures/custom_field.json).
  2. Ten salary components with the US tax formulas (no max(); the salary-formula
     sandbox forbids it). Existing components keep their GL-account mappings —
     only formulas/flags are updated.
  3. The "Household" weekly salary structure (1 earning + 9 deductions), submitted,
     for COMPANY below. Assign it to each hourly employee (per-employee UI step).
  4. Disables the legacy "Salary Slip - Set YTD Gross Pay" Server Script — the
     app's before_validate hook (ls_foods.payroll.set_ytd_gross_pay) now owns YTD.

Invoked from:
  - hooks.py  -> after_install = "ls_foods.setup.payroll_setup.run"
  - patches   -> ls_foods/patches/v0_0_1/setup_household_payroll.py
  - manually  -> bench --site SITE execute ls_foods.setup.payroll_setup.run

NOT created (per deployment decision; do per-site): GL accounts / component
account mappings, and the company's default Payroll Payable account.

Tax spec (source: client images + Notes.txt, 2026-06-11):
  Employee-side (reduce net pay):
    Social Security 6.2%  - starts YTD>=$3,000, cap $184,500
    Medicare        1.45% - starts YTD>=$3,000, no cap
    Indiana State   2.95% - always
    LaGrange County 1.65% - always
    Federal income tax    - NOT withheld
  Employer-side (do NOT reduce net pay):
    Social Security 6.2%  - starts YTD>=$3,000, cap $184,500
    Medicare        1.45% - starts YTD>=$3,000, no cap
    FUTA            0.6%  - starts $1,000, cap $7,000   (legally quarterly; YTD proxy)
    Indiana SUI/SUTA 2.5% - starts $1,000, cap $9,500   (legally quarterly; YTD proxy)
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

# ============================ CONFIG ============================
COMPANY = "Loren Slabaugh"          # company the Household structure is built for
STRUCTURE_NAME = "Household"
IN_STATE_RATE = 0.0295              # Indiana state income tax
LAGRANGE_RATE = 0.0165             # LaGrange County local income tax
MODULE = "Ls Foods"                 # app module (for custom-field fixture export)
LEGACY_SERVER_SCRIPT = "Salary Slip - Set YTD Gross Pay"

# ---- formulas (salary-formula sandbox has NO max(); written as conditionals) ----
SS_FORMULA = (
	"0 if custom_ytd_gross_pay < 3000 else (gross_pay * 0.062 "
	"if (custom_ytd_gross_pay + gross_pay) <= 184500 else "
	"((184500 - custom_ytd_gross_pay) * 0.062 if custom_ytd_gross_pay < 184500 else 0))"
)
MED_FORMULA = "0 if custom_ytd_gross_pay < 3000 else gross_pay * 0.0145"
FUTA_FORMULA = (
	"0 if custom_ytd_gross_pay < 1000 else (gross_pay * 0.006 "
	"if (custom_ytd_gross_pay + gross_pay) <= 7000 else "
	"((7000 - custom_ytd_gross_pay) * 0.006 if custom_ytd_gross_pay < 7000 else 0))"
)
SUTA_FORMULA = (
	"0 if custom_ytd_gross_pay < 1000 else (gross_pay * 0.025 "
	"if (custom_ytd_gross_pay + gross_pay) <= 9500 else "
	"((9500 - custom_ytd_gross_pay) * 0.025 if custom_ytd_gross_pay < 9500 else 0))"
)
INSIT_FORMULA = "gross_pay * %s" % IN_STATE_RATE
LIT_FORMULA = "gross_pay * %s" % LAGRANGE_RATE
HRW_FORMULA = "custom_hours_worked * custom_rate_per_hour"

# (name, abbr, type, formula_or_None, do_not_include_in_total, is_tax_applicable)
COMPONENTS = [
	("Hourly Wage", "HRW", "Earning", HRW_FORMULA, 0, 1),
	("FICA Social Security - Employee", "SSE", "Deduction", SS_FORMULA, 0, 0),
	("FICA Medicare Tax - Employee", "MCE", "Deduction", MED_FORMULA, 0, 0),
	("Federal Income Tax", "FIT", "Deduction", None, 0, 0),          # not withheld
	("IN State Income Tax", "INSIT", "Deduction", INSIT_FORMULA, 0, 0),
	("LaGrange County Income Tax", "LIT", "Deduction", LIT_FORMULA, 0, 0),
	("FICA Social Security - Employer", "SSR", "Deduction", SS_FORMULA, 1, 0),
	("FICA Medicare - Employer", "MCR", "Deduction", MED_FORMULA, 1, 0),
	("Federal Unemployment Tax", "FUTA", "Deduction", FUTA_FORMULA, 1, 0),
	("IN State Unemployment Tax", "INSUTA", "Deduction", SUTA_FORMULA, 1, 0),
]

CUSTOM_FIELDS = {
	"Employee": [
		{
			"fieldname": "custom_social_security_number",
			"label": "Social Security Number",
			"fieldtype": "Data",
			"insert_after": "salutation",
			"reqd": 1,
			"module": MODULE,
		},
		{
			"fieldname": "custom_rate_per_hour",
			"label": "Rate per Hour",
			"fieldtype": "Currency",
			"insert_after": "salary_mode",
			"description": "Hourly pay rate. Hourly Wage = Hours Worked x Rate per Hour.",
			"module": MODULE,
		},
	],
	"Salary Slip": [
		{
			"fieldname": "custom_hours_worked",
			"label": "Hours Worked",
			"fieldtype": "Float",
			"precision": "2",
			"insert_after": "payment_days",
			"description": "Total hours worked this pay period. Enter each week.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_ytd_gross_pay",
			"label": "YTD Gross Pay (prior periods)",
			"fieldtype": "Currency",
			"insert_after": "custom_hours_worked",
			"read_only": 1,
			"description": "Auto-filled by the ls_foods before_validate hook from prior "
			"submitted slips this calendar year. Do not edit.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_mtd_gross_pay",
			"label": "MTD Gross Pay (this month)",
			"fieldtype": "Currency",
			"insert_after": "custom_ytd_gross_pay",
			"read_only": 1,
			"description": "Auto-filled by the ls_foods validate hook: month-to-date "
			"gross pay grouped by posting date (prior submitted slips this month + "
			"this slip). Do not edit.",
			"module": MODULE,
		},
		# --- payment tracking -------------------------------------------------
		# The standard `journal_entry` field on Salary Slip holds the ACCRUAL
		# entry posted by ls_foods.payroll on submit. The payout is a second,
		# separate Journal Entry, so it needs its own link — without it the
		# "Make Payment Entry" button had no reliable way to tell whether a slip
		# had actually been paid.
		{
			"fieldname": "custom_payment_section",
			"label": "Payment",
			"fieldtype": "Section Break",
			"insert_after": "journal_entry",
			"collapsible": 1,
			"module": MODULE,
		},
		{
			"fieldname": "custom_payment_date",
			"label": "Payment Date",
			"fieldtype": "Date",
			"insert_after": "custom_payment_section",
			"read_only": 1,
			"description": "Date the employee was actually paid. Set from the Make "
			"Payment Entry dialog; it is the posting date of the payment Journal Entry.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_payment_journal_entry",
			"label": "Payment Journal Entry",
			"fieldtype": "Link",
			"options": "Journal Entry",
			"insert_after": "custom_payment_date",
			"read_only": 1,
			"description": "The payout entry (Dr Payroll Payable / Cr Bank). Separate "
			"from the accrual entry in the Journal Entry field above.",
			"module": MODULE,
		},
	],
}


def ensure_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	# Pin module so `export-fixtures --app ls_foods` picks up exactly these fields.
	for dt, fields in CUSTOM_FIELDS.items():
		for f in fields:
			name = "%s-%s" % (dt, f["fieldname"])
			if frappe.db.exists("Custom Field", name):
				frappe.db.set_value("Custom Field", name, "module", MODULE, update_modified=False)
	print("   custom fields ready")


def ensure_components():
	for name, abbr, ctype, formula, dnit, tax in COMPONENTS:
		if frappe.db.exists("Salary Component", name):
			d = frappe.get_doc("Salary Component", name)
			d.do_not_include_in_total = dnit
			d.depends_on_payment_days = 0
			if ctype == "Earning":
				d.is_tax_applicable = tax
			if formula is None:
				d.amount_based_on_formula = 0
				d.formula = ""
				d.amount = 0
			else:
				d.amount_based_on_formula = 1
				d.formula = formula
			# NOTE: child `accounts` table intentionally left untouched -> existing
			# GL-account mappings are preserved.
			d.save()
			print("   updated component:", name)
		else:
			doc = {
				"doctype": "Salary Component",
				"salary_component": name,
				"salary_component_abbr": abbr,
				"type": ctype,
				"do_not_include_in_total": dnit,
				"depends_on_payment_days": 0,
			}
			if ctype == "Earning":
				doc["is_tax_applicable"] = tax
			if formula is None:
				doc.update({"amount_based_on_formula": 0, "amount": 0})
			else:
				doc.update({"amount_based_on_formula": 1, "formula": formula})
			frappe.get_doc(doc).insert()
			print("   created component:", name)


def ensure_structure():
	if not frappe.db.exists("Company", COMPANY):
		print("   !! company '%s' not found -- skipping salary structure. "
		      "Create the company, then re-run the setup." % COMPANY)
		return
	if frappe.db.exists("Salary Structure", STRUCTURE_NAME) and \
			frappe.db.get_value("Salary Structure", STRUCTURE_NAME, "docstatus") == 1:
		print("   structure '%s' already submitted -- left untouched." % STRUCTURE_NAME)
		return
	if frappe.db.exists("Salary Structure", STRUCTURE_NAME):
		ss = frappe.get_doc("Salary Structure", STRUCTURE_NAME)
	else:
		ss = frappe.new_doc("Salary Structure")
		ss.name = STRUCTURE_NAME
	ss.company = COMPANY
	ss.currency = frappe.db.get_value("Company", COMPANY, "default_currency") or "USD"
	ss.is_active = "Yes"
	ss.payroll_frequency = "Weekly"
	ss.salary_slip_based_on_timesheet = 0
	ss.set("earnings", [])
	ss.set("deductions", [])
	ss.append("earnings", {
		"salary_component": "Hourly Wage",
		"amount_based_on_formula": 1,
		"formula": HRW_FORMULA,
		"depends_on_payment_days": 0,
	})
	for name, abbr, ctype, formula, dnit, tax in COMPONENTS:
		if ctype != "Deduction":
			continue
		row = {"salary_component": name, "do_not_include_in_total": dnit, "depends_on_payment_days": 0}
		if formula is None:
			row.update({"amount_based_on_formula": 0, "amount": 0})
		else:
			row.update({"amount_based_on_formula": 1, "formula": formula})
		ss.append("deductions", row)
	ss.save()
	ss.submit()
	print("   structure '%s' submitted (earnings=%s deductions=%s)" % (
		ss.name, len(ss.earnings), len(ss.deductions)))


def disable_legacy_server_script():
	if frappe.db.exists("Server Script", LEGACY_SERVER_SCRIPT):
		if not frappe.db.get_value("Server Script", LEGACY_SERVER_SCRIPT, "disabled"):
			frappe.db.set_value("Server Script", LEGACY_SERVER_SCRIPT, "disabled", 1)
			print("   disabled legacy server script (app hook now owns YTD)")


def run():
	"""Idempotent, company-wide US-payroll setup. Safe to re-run.

	Sets up the reusable engine only — NOT any specific employee. Onboard
	employees and assign them the '%s' structure as a normal UI step.
	""" % STRUCTURE_NAME
	print("== LS Foods US household payroll setup (company-wide) ==")
	print("== 1. custom fields ==")
	ensure_custom_fields()
	print("== 2. salary components ==")
	ensure_components()
	print("== 3. salary structure ==")
	ensure_structure()
	print("== 4. legacy server script ==")
	disable_legacy_server_script()
	frappe.db.commit()
	print("== DONE -- engine ready. Assign the structure to employees in the UI. ==")
