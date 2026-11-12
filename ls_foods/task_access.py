"""Whoever a Task is assigned to can read, edit and share it.

Assigning a Task (the sidebar "Assigned To", or an Assignment Rule) creates a
ToDo. ERPNext only shares the Task when the assignee cannot read it at all, and
then read-only, so an assignee without the Projects role could open their task
but not update it. This shares it with read, write and share as soon as the
assignment is open, the same access the Task's owner has been giving by hand.

It runs before ERPNext's own check, which then finds the assignee can read the
Task and does not replace this share with a read-only one. Taking the
assignment away does not remove the share.
"""

import frappe
from frappe.share import add_docshare

DOCTYPE = "Task"


def share_with_assignee(todo, method=None):
	"""ToDo on_update (also runs on insert)."""
	if todo.reference_type != DOCTYPE or not todo.reference_name or not todo.allocated_to:
		return
	if todo.status != "Open":
		return
	already = frappe.db.exists(
		"DocShare",
		{
			"share_doctype": DOCTYPE,
			"share_name": todo.reference_name,
			"user": todo.allocated_to,
			"read": 1,
			"write": 1,
			"share": 1,
		},
	)
	if already:
		return
	add_docshare(
		DOCTYPE,
		todo.reference_name,
		todo.allocated_to,
		read=1,
		write=1,
		share=1,
		flags={"ignore_share_permission": True},
	)


# ------------------------------------------------------- Allocated To / Recurring


def assign_allocated_to(task, method=None):
	"""Task on_update: the "Allocated To" field assigns the Task to that user.

	Changing it moves the assignment (the previous person's open assignment is
	closed); clearing it removes it. The assignment is an ordinary ToDo, so the
	sidebar, the To Do list and the share above (share_with_assignee) all work.
	"""
	from frappe.desk.form import assign_to

	new = task.get("custom_allocated_to")
	before = task.get_doc_before_save()
	old = before.get("custom_allocated_to") if before else None
	if new == old:
		return

	if old:
		assign_to.set_status(DOCTYPE, task.name, assign_to=old, status="Cancelled", ignore_permissions=True)
	if new and not frappe.db.exists(
		"ToDo",
		{"reference_type": DOCTYPE, "reference_name": task.name, "allocated_to": new, "status": "Open"},
	):
		assign_to.add(
			{
				"assign_to": [new],
				"doctype": DOCTYPE,
				"name": task.name,
				"description": task.subject,
				"notify": 1,
			}
		)


def check_recurring(task, method=None):
	"""Task validate: "Is Recurring" cannot be cleared while an Auto Repeat runs it."""
	if task.is_new() or task.get("custom_is_recurring"):
		return
	if _active_repeats(task.name):
		frappe.throw(
			frappe._("This task repeats through an Auto Repeat. Disable or delete the Auto Repeat first, then untick Is Recurring.")
		)


def _active_repeats(task_name):
	return frappe.db.count(
		"Auto Repeat", {"reference_doctype": DOCTYPE, "reference_document": task_name, "disabled": 0}
	)


def repeat_changed(repeat, method=None):
	"""Auto Repeat after_insert / on_update / on_trash: keep Task.Is Recurring truthful."""
	if repeat.reference_doctype != DOCTYPE or not frappe.db.exists(DOCTYPE, repeat.reference_document):
		return
	remaining = frappe.db.count(
		"Auto Repeat",
		{
			"reference_doctype": DOCTYPE,
			"reference_document": repeat.reference_document,
			"disabled": 0,
			"name": ["!=", repeat.name] if method == "on_trash" else ["like", "%"],
		},
	)
	if remaining:
		frappe.db.set_value(DOCTYPE, repeat.reference_document, "custom_is_recurring", 1, update_modified=False)
	elif method == "on_trash" or repeat.disabled:
		frappe.db.set_value(DOCTYPE, repeat.reference_document, "custom_is_recurring", 0, update_modified=False)
