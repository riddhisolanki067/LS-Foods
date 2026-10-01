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
#   and the approval date; warn if the named approver holds no role that can
#   actually approve (approval_status is permlevel 1).
# before_submit: block a claim with a missing receipt (per Expense Claim Type).
# on_submit / on_cancel: post / cancel the Material Receipt Stock Entry, then put
#   the Workflow state back in step with the standard fields — the Draft ->
#   Approved/Rejected -> Paid workflow lives in setup/expense_claim_workflow.py and
#   Paid/Cancelled are stamped, never clicked.
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
		"on_submit": [
			"ls_foods.reimbursement.post_stock_entry",
			# LAST: HRMS's own on_submit has recalculated status by now, and an
			# "Is Paid" claim is Paid the moment it is submitted.
			"ls_foods.reimbursement.stamp_workflow_state",
		],
		"on_cancel": [
			"ls_foods.reimbursement.cancel_stock_entry",
			"ls_foods.reimbursement.stamp_workflow_state",
		],
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
	# Customer master — see ls_foods/customer_master.py for the full rationale.
	# before_insert: fill custom_customer_id when it is blank (1043 -> 1044).
	#   before_insert, not validate, so a Data Import carrying the legacy number
	#   keeps it.
	# validate: reject a duplicate Customer ID with a readable message, supply
	#   Country / Address Type on the address rows, and hold the phone and email
	#   grids to Contact's one-primary rule before Contact throws its own.
	# on_update: push the three grids out to the real Address and Contact
	#   records. on_update, not validate, because their Dynamic Link cannot be
	#   validated against a Customer that is not in the database yet.
	"Customer": {
		"before_insert": "ls_foods.customer_master.set_customer_id",
		"validate": "ls_foods.customer_master.prepare_customer_master",
		"on_update": "ls_foods.customer_master.sync_addresses_and_contact",
	},
	# The other direction: an edit made on the Address or Contact form itself
	# comes back into the grid, so the customer's next save cannot push stale
	# values over newer ones. frappe.flags breaks the loop between the two.
	"Address": {
		"on_update": "ls_foods.customer_master.pull_address_into_customers",
		"on_trash": "ls_foods.customer_master.drop_address_from_customers",
	},
	"Contact": {
		"on_update": "ls_foods.customer_master.pull_contact_into_customers",
	},
	# Case pricing and weight — see ls_foods/case_pricing.py.
	# Items are stocked and sold in Cases — the stock unit IS the case, so there
	#   are no UOM conversions anywhere and "Case Weight (lb)" is just the pounds
	#   in one case, typed per line. See ls_foods/case_pricing.py.
	# validate: fill Unit Price (rate / case weight) — the only figure ERPNext
	#   cannot hold, because with the case as the stock unit its "Rate of Stock
	#   UOM" is the case price over again; and warn (never block) on a line with
	#   no case weight.
	# before_submit: refuse an unpriced row. An item with only a Case Item Price
	#   sold in its own Stock UOM silently prices at 0.00 — verified on the bench.
	"Sales Invoice": {
		# before_validate: copy Case Weight (lb) into the standard weight_per_unit
		#   BEFORE the controller runs, so ERPNext's own maths produces Line
		#   Weight and Total Weight (lb). Nothing here recalculates them.
		#   Then price per-lb items (beef shares): Rate = Unit Price x Case Weight,
		#   and keep one processing line (weight x fee) under each share.
		#   See ls_foods/share_billing.py.
		"before_validate": [
			"ls_foods.case_pricing.mirror_case_weight",
			"ls_foods.case_pricing.apply_per_lb_pricing",
			"ls_foods.share_billing.sync_processing_rows",
		],
		"validate": [
			"ls_foods.case_pricing.set_unit_price",
			"ls_foods.case_pricing.warn_missing_case_weight",
		],
		"before_submit": "ls_foods.case_pricing.validate_zero_rate",
	},
	# Sales Order: items with a Per Pound price are priced $/lb x case weight
	#   (estimated weight until invoiced). A beef/hog share stays at its price-list
	#   price — the FIXED deposit — and Deposit Due totals those lines.
	#   The item grid matches the invoice's — Case Weight (lb), Unit Price, Line
	#   Weight (lb) — so the same weight and unit-price hooks run here.
	"Sales Order": {
		"before_validate": [
			"ls_foods.case_pricing.mirror_case_weight",
			"ls_foods.case_pricing.apply_per_lb_pricing",
		],
		"validate": [
			"ls_foods.case_pricing.set_unit_price",
			"ls_foods.case_pricing.warn_missing_case_weight",
			"ls_foods.share_deposit.set_deposit_due",
		],
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
	"ls_foods.setup.customer_setup.install",
	"ls_foods.setup.case_pricing_setup.run",
]

# Re-applies the Expense Claim field properties that the fixture import would
# otherwise revert (fixtures import AFTER patches on migrate) and rebuilds the
# Draft -> Approved/Rejected -> Paid workflow from code.
after_migrate = [
	"ls_foods.setup.reimbursement_setup.after_migrate",
	# Idempotent. Runs on every migrate so the Property Setters and the print
	# format are re-applied from code — a patch only ever runs once, and the
	# Print Format record in the database is what actually renders, so without
	# this a change to templates/sales_invoice_case_weight.html would never
	# reach a deployed site.
	"ls_foods.setup.case_pricing_setup.run",
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
	"Customer": "public/js/customer.js",
	"Sales Invoice": ["public/js/per_lb_pricing.js", "public/js/sales_invoice.js"],
	"Sales Order": ["public/js/per_lb_pricing.js", "public/js/sales_order.js"],
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
# Print formats lay beef/hog shares out like the client's item build sheet.
jinja = {
	"methods": [
		"ls_foods.share_billing.invoice_view",
		"ls_foods.share_billing.order_view",
	],
}
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

