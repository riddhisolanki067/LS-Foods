"""LS Foods — Task and Issue screen additions (live Tasks 56, 57, 58).

Task
  * Is Recurring (Check, default off). Recurrence itself is ERPNext's Auto Repeat,
    switched on for Task here; the checkbox is the visible switch for it (see
    public/js/task.js and ls_foods/task_access.py).
  * Allocated To (Link User): setting it assigns the Task to that person, as the
    sidebar "Assigned To" would (task_access.assign_allocated_to).
  * Reference Type / Reference Name: the same pair the To Do screen has, to point a
    Task at any document (e.g. a Stock Reconciliation).

Issue
  * Opening Date editable (ERPNext ships it read-only).
  * Phone Number and Source. Source has the same list as Order Source on Sales
    Order and Sales Invoice (order_source_setup).

Idempotent — safe on every ``bench migrate``.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

MODULE = "Ls Foods"
SOURCE_OPTIONS = "\nEmail\nMail\nPhone\nVoicemail\nOther"


def run():
	create_custom_fields(
		{
			"Task": [
				{
					"fieldname": "custom_is_recurring",
					"label": "Is Recurring",
					"fieldtype": "Check",
					"default": "0",
					"insert_after": "priority",
					"no_copy": 0,
					"description": "Tick, then set how often it repeats (Auto Repeat).",
				},
				{
					"fieldname": "custom_allocation_section",
					"label": "Allocation",
					"fieldtype": "Section Break",
					"insert_after": "description",
				},
				{
					"fieldname": "custom_allocated_to",
					"label": "Allocated To",
					"fieldtype": "Link",
					"options": "User",
					"insert_after": "custom_allocation_section",
					"description": "Assigns the task to this person automatically.",
					"in_standard_filter": 1,
					"no_copy": 1,
				},
				{
					"fieldname": "custom_allocation_column",
					"fieldtype": "Column Break",
					"insert_after": "custom_allocated_to",
				},
				{
					"fieldname": "custom_reference_type",
					"label": "Reference Type",
					"fieldtype": "Link",
					"options": "DocType",
					"insert_after": "custom_allocation_column",
				},
				{
					"fieldname": "custom_reference_name",
					"label": "Reference Name",
					"fieldtype": "Dynamic Link",
					"options": "custom_reference_type",
					"insert_after": "custom_reference_type",
				},
				# What Frappe's own Customize Form adds when Auto Repeat is switched
				# on for a doctype; the property setter alone does not create it.
				{
					"fieldname": "auto_repeat",
					"label": "Auto Repeat",
					"fieldtype": "Link",
					"options": "Auto Repeat",
					"insert_after": "custom_reference_name",
					"read_only": 1,
					"no_copy": 1,
					"print_hide": 1,
				},
			],
			"Issue": [
				{
					"fieldname": "custom_phone_number",
					"label": "Phone Number",
					"fieldtype": "Data",
					"options": "Phone",
					"insert_after": "raised_by",
				},
				{
					"fieldname": "custom_source",
					"label": "Source",
					"fieldtype": "Select",
					"options": SOURCE_OPTIONS,
					"insert_after": "issue_type",
					"in_standard_filter": 1,
				},
			],
		},
		ignore_validate=True,
	)
	for dt in ("Task", "Issue"):
		for f in frappe.get_all("Custom Field", filters={"dt": dt, "fieldname": ["like", "custom_%"]}, pluck="name"):
			frappe.db.set_value("Custom Field", f, "module", MODULE, update_modified=False)

	# Task: Auto Repeat available (the Repeat button + Auto Repeat records).
	make_property_setter("Task", None, "allow_auto_repeat", 1, "Check", for_doctype=True)
	# Issue: Opening Date is typed in, not stamped.
	make_property_setter("Issue", "opening_date", "read_only", 0, "Check", validate_fields_for_doctype=False)

	for dt in ("Task", "Issue"):
		frappe.clear_cache(doctype=dt)
