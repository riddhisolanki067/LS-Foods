app_name = "ls_foods"
app_title = "Ls Foods"
app_publisher = "Riddhi"
app_description = "Ls Food"
app_email = "riddhi@gmail.com"
app_license = "mit"

# Apps
# ------------------

required_apps = ["frappe", "erpnext", "hrms"]

# Fixtures
# ------------------
# Ship the household-payroll custom fields with the app (module = "Ls Foods").
fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "Ls Foods"]]},
	{"dt": "Print Format", "filters": [["module", "=", "Ls Foods"]]},
]

# Document Events
# ------------------
# before_validate: fill Salary Slip.custom_ytd_gross_pay so the US household tax
#   formulas can apply YTD thresholds / wage-base caps (replaces the legacy
#   "Salary Slip - Set YTD Gross Pay" Server Script). MUST run here so the value
#   is present before the salary-component formulas are evaluated.
# validate: (1) net pay in words, (2) fill custom_mtd_gross_pay — month-to-date
#   gross grouped by posting_date, incl. the current slip (needs gross_pay, which
#   is computed during the standard validate, so it runs on validate not before).
# before_submit: refuse to submit a slip with no Hours Worked — the Hourly Wage
#   formula is custom_hours_worked * custom_rate_per_hour, so a blank value
#   silently produces a $0 slip. The form warns on save too (payment_entry.js).
# on_submit / on_cancel: post / reverse the payroll accrual Journal Entry directly
#   from a standalone Salary Slip, so one slip a week is all that's needed (no
#   Payroll Entry). Fully dynamic — accounts come from the component mappings,
#   nothing hardcoded. Auto-skipped when a Payroll Entry drives the submit.
#
# Expense Claim = the Employee Reimbursement module (mileage, expenses, and
#   stock/supplies purchases that increase inventory). See ls_foods/reimbursement.py
#   and setup/reimbursement_setup.py for the design rationale and the double entry.
# before_validate: compute row amounts (Qty x Rate) and mirror the Purchased
#   Items table into the standard Expenses table, so the claim total / GL /
#   payable include it.
# validate: derive the Requested/Approved/Paid status, the expense-type summary
#   and the approval date.
# before_submit: block a claim with a missing receipt (per Expense Claim Type).
# on_submit / on_cancel: post / cancel the Material Receipt Stock Entry.
#
# Salary Slip "Reimbursements" tab: approved claims are selected there and paid
#   out with the wages. apply_reimbursements adds the total to NET pay only —
#   never to gross_pay, because every tax formula on this site is keyed off
#   gross_pay and a reimbursement is not taxable wages. The accrual JE then
#   debits the Employee Reimbursements Payable (referencing the claim, which is
#   what marks it Paid). See ls_foods/reimbursement_payroll.py.
doc_events = {
	"Salary Slip": {
		"before_validate": "ls_foods.payroll.set_ytd_gross_pay",
		"validate": [
			# ORDER MATTERS. apply_reimbursements adjusts net_pay, so it has to run
			# before the amount-in-words is written from it.
			"ls_foods.reimbursement_payroll.apply_reimbursements",
			"ls_foods.setup.payment_entry.set_net_pay_in_words",
			"ls_foods.payroll.set_mtd_gross_pay",
		],
		"before_submit": "ls_foods.setup.payment_entry.validate_hours_worked",
		"on_submit": "ls_foods.payroll.post_accrual_journal_entry",
		"on_cancel": "ls_foods.payroll.reverse_accrual_journal_entry",
	},
	"Expense Claim": {
		"before_validate": "ls_foods.reimbursement.sync_reimbursement_rows",
		"validate": "ls_foods.reimbursement.finalize_reimbursement_fields",
		"before_submit": "ls_foods.reimbursement.validate_receipts",
		"on_submit": "ls_foods.reimbursement.post_stock_entry",
		"on_cancel": "ls_foods.reimbursement.cancel_stock_entry",
	},
	# HRMS already recalculates an Expense Claim's reimbursed amount and standard
	# status from any voucher that references it. These carry that through to the
	# Requested/Approved/Paid field and the paid date. ls_foods is installed last,
	# so these run after the HRMS handlers on the same events.
	"Journal Entry": {
		"on_submit": "ls_foods.reimbursement.sync_claims_from_voucher",
		"on_cancel": "ls_foods.reimbursement.sync_claims_from_voucher",
		"on_update_after_submit": "ls_foods.reimbursement.sync_claims_from_voucher",
	},
	"Payment Entry": {
		"on_submit": "ls_foods.reimbursement.sync_claims_from_voucher",
		"on_cancel": "ls_foods.reimbursement.sync_claims_from_voucher",
		"on_update_after_submit": "ls_foods.reimbursement.sync_claims_from_voucher",
	},
}

# Installation
# ------------------
# Set up the company-wide payroll engine: custom fields, salary components, the
# Household salary structure, and disable the legacy server script. Idempotent;
# also runs on migrate via patches.txt. Does NOT seed any specific employee.
after_install = [
	"ls_foods.setup.payroll_setup.run",
	"ls_foods.setup.hr_settings.run",
	"ls_foods.setup.reimbursement_setup.run",
]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "ls_foods",
# 		"logo": "/assets/ls_foods/logo.png",
# 		"title": "Ls Foods",
# 		"route": "/ls_foods",
# 		"has_permission": "ls_foods.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/ls_foods/css/ls_foods.css"
# app_include_js = "/assets/ls_foods/js/ls_foods.js"

# include js, css files in header of web template
# web_include_css = "/assets/ls_foods/css/ls_foods.css"
# web_include_js = "/assets/ls_foods/js/ls_foods.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "ls_foods/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Salary Slip": "public/js/payment_entry.js",
	"Expense Claim": "public/js/expense_claim.js",
}
doctype_list_js = {"Expense Claim": "public/js/expense_claim_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "ls_foods/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "ls_foods.utils.jinja_methods",
# 	"filters": "ls_foods.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "ls_foods.install.before_install"
# after_install = "ls_foods.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "ls_foods.uninstall.before_uninstall"
# after_uninstall = "ls_foods.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "ls_foods.utils.before_app_install"
# after_app_install = "ls_foods.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "ls_foods.utils.before_app_uninstall"
# after_app_uninstall = "ls_foods.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "ls_foods.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"ls_foods.tasks.all"
# 	],
# 	"daily": [
# 		"ls_foods.tasks.daily"
# 	],
# 	"hourly": [
# 		"ls_foods.tasks.hourly"
# 	],
# 	"weekly": [
# 		"ls_foods.tasks.weekly"
# 	],
# 	"monthly": [
# 		"ls_foods.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "ls_foods.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "ls_foods.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "ls_foods.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["ls_foods.utils.before_request"]
# after_request = ["ls_foods.utils.after_request"]

# Job Events
# ----------
# before_job = ["ls_foods.utils.before_job"]
# after_job = ["ls_foods.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"ls_foods.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

