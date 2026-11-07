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
