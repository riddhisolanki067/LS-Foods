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
]

# Document Events
# ------------------
# before_validate: fill Salary Slip.custom_ytd_gross_pay so the US household tax
#   formulas can apply YTD thresholds / wage-base caps (replaces the legacy
#   "Salary Slip - Set YTD Gross Pay" Server Script).
# on_submit / on_cancel: post / reverse the payroll accrual Journal Entry directly
#   from a standalone Salary Slip, so one slip a week is all that's needed (no
#   Payroll Entry). Fully dynamic — accounts come from the component mappings,
#   nothing hardcoded. Auto-skipped when a Payroll Entry drives the submit.
doc_events = {
	"Salary Slip": {
		"before_validate": "ls_foods.payroll.set_ytd_gross_pay",
		"on_submit": "ls_foods.payroll.post_accrual_journal_entry",
		"on_cancel": "ls_foods.payroll.reverse_accrual_journal_entry",
	},
}

# Installation
# ------------------
# Set up the company-wide payroll engine: custom fields, salary components, the
# Household salary structure, and disable the legacy server script. Idempotent;
# also runs on migrate via patches.txt. Does NOT seed any specific employee.
after_install = "ls_foods.setup.payroll_setup.run"

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
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
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

