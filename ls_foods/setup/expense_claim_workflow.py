"""LS Foods — the Expense Claim (reimbursement) Workflow.

Why a Workflow now, when reimbursement_setup.py argued against one
--------------------------------------------------------------------
The first cut of this module deliberately had NO Frappe Workflow: ERPNext's own
approval gate (``Expense Claim.on_submit`` throws unless ``approval_status`` is
Approved or Rejected) already forces an approval step, and stacking a Workflow on
top usually means two state machines fighting over one document.

The client asked for the visible Draft -> Approved / Rejected -> Paid lifecycle,
so it is built here — but built so that there is still only ONE state machine:

  * Every workflow state carries ``update_field = approval_status``, so clicking
    **Approve** or **Reject** is what sets the standard field ERPNext already
    keys off. The Workflow drives the standard field; it does not shadow it.
  * ``Paid`` has no incoming transition and nobody can click it. It is stamped by
    ``ls_foods.reimbursement.stamp_workflow_state`` the moment the paying voucher
    (Salary Slip accrual JE, Journal Entry or Payment Entry) is submitted, and
    un-stamped when that voucher is cancelled. Payment is a fact about the
    ledger, never an opinion someone clicks.
  * ``Cancelled`` is reachable from Approved / Rejected only, and only while the
    claim has not been paid. To void a paid claim you cancel the PAYMENT first,
    which returns the claim to Approved and re-opens Cancel. That ordering is
    the point: it stops a cancelled claim leaving a paid payable behind.

``custom_reimbursement_status`` (Requested / Approved / Paid, the client's own
words) is untouched and still derived from docstatus + approval_status + status.
The workflow state is a second *display* of the same truth, not a second source
of it — ``stamp_workflow_state`` copies one into the other.

Roles, and the trap behind them
-------------------------------
``Expense Claim.approval_status`` is a **permlevel 1** field. On save Frappe
silently RESETS permlevel fields the user cannot write, so if an approver's roles
have no permlevel-1 write access their Approve click sets approval_status back to
Draft and the submit then fails with "Approval Status must be 'Approved' or
'Rejected'". Only HR Manager, HR User and Expense Approver have that access on
Expense Claim, which is why the Approve/Reject transitions are limited to
Expense Approver and HR Manager — anything wider would produce that error.

Everything here is idempotent: re-running rewrites the states and transitions to
match this file, so the app is the source of truth and a hand-edit in the UI is
reverted on the next ``bench migrate``.
"""

import frappe

WORKFLOW_NAME = "LS Foods Expense Claim"
DOCTYPE = "Expense Claim"
STATE_FIELD = "workflow_state"

# state, doc_status, update_field, update_value, allow_edit, style
#
# allow_edit is only the *form* read-only gate (frappe.workflow.is_read_only), and
# a state may legitimately appear more than once to list several editing roles —
# that is how Draft is editable both by an employee raising their own claim and by
# the office. The FIRST row for a state is the one apply_workflow reads for
# doc_status / update_field, so keep those identical across duplicates.
STATES = [
	("Draft", "0", "approval_status", "Draft", "HR User", ""),
	("Draft", "0", "approval_status", "Draft", "Employee", ""),
	("Approved", "1", "approval_status", "Approved", "HR User", "Primary"),
	("Rejected", "1", "approval_status", "Rejected", "HR User", "Danger"),
	("Paid", "1", "approval_status", "Approved", "HR User", "Success"),
	("Cancelled", "2", "", "", "HR User", ""),
]

# state, action, next_state, allowed role, condition
#
# ONE role per action, deliberately. Frappe renders one Actions-menu item per
# matching transition and does not de-duplicate, so listing Approve twice (once
# for Expense Approver, once for HR Manager) gives anyone holding both roles TWO
# identical "Approve" buttons. Expense Approver is the right single choice: it is
# ERPNext's own role for this job and one of the three that can write the
# permlevel-1 approval_status. Whoever signs off needs that role ticked on their
# User — see warn_if_approver_cannot_approve, which says so on the claim itself.
TRANSITIONS = [
	("Draft", "Approve", "Approved", "Expense Approver", ""),
	("Draft", "Reject", "Rejected", "Expense Approver", ""),
	# Cancelling is the accounting reversal, so it is HR Manager only and never
	# available on a claim that has already been paid.
	("Approved", "Cancel", "Cancelled", "HR Manager", 'doc.status != "Paid"'),
	("Rejected", "Cancel", "Cancelled", "HR Manager", ""),
]

STATE_STYLES = {state: style for state, _ds, _uf, _uv, _ae, style in STATES}


def run():
	"""Idempotent. Called from reimbursement_setup.run()."""
	ensure_workflow_states()
	ensure_action_masters()
	ensure_workflow()
	backfill_workflow_state()


def ensure_workflow_states():
	"""Frappe ships Approved / Rejected / Pending only — create the rest.

	The style is what colours the indicator on the list and in the form heading
	(Workflow State.style -> frappe.get_indicator), which is the whole point of
	the client's request: the record shows its own status.
	"""
	for state, style in STATE_STYLES.items():
		if frappe.db.exists("Workflow State", state):
			if style and frappe.db.get_value("Workflow State", state, "style") != style:
				frappe.db.set_value("Workflow State", state, "style", style, update_modified=False)
			continue

		frappe.get_doc(
			{"doctype": "Workflow State", "workflow_state_name": state, "style": style}
		).insert(ignore_permissions=True)


def ensure_action_masters():
	for action in sorted({t[1] for t in TRANSITIONS}):
		if not frappe.db.exists("Workflow Action Master", action):
			frappe.get_doc(
				{"doctype": "Workflow Action Master", "workflow_action_name": action}
			).insert(ignore_permissions=True)


def ensure_workflow():
	doc = (
		frappe.get_doc("Workflow", WORKFLOW_NAME)
		if frappe.db.exists("Workflow", WORKFLOW_NAME)
		else frappe.new_doc("Workflow")
	)

	doc.workflow_name = WORKFLOW_NAME
	doc.document_type = DOCTYPE
	doc.workflow_state_field = STATE_FIELD
	doc.is_active = 1
	# 0 = let the workflow state BE the record's status indicator. That is the
	# client's actual requirement ("show as a status of the record"); with 1 the
	# list would keep showing the standard Draft/Unpaid/Paid instead.
	doc.override_status = 0
	# Left off deliberately: HRMS already emails the approver (notify_approver on
	# insert, notify_approval_status on update). Turning this on as well would
	# send two mails per step.
	doc.send_email_alert = 0

	doc.set("states", [])
	for state, doc_status, update_field, update_value, allow_edit, _style in STATES:
		doc.append(
			"states",
			{
				"state": state,
				"doc_status": doc_status,
				"update_field": update_field or None,
				"update_value": update_value or None,
				"allow_edit": allow_edit,
			},
		)

	doc.set("transitions", [])
	for state, action, next_state, allowed, condition in TRANSITIONS:
		doc.append(
			"transitions",
			{
				"state": state,
				"action": action,
				"next_state": next_state,
				"allowed": allowed,
				"condition": condition or None,
				# The office raises and approves most claims on the employee's
				# behalf, so the creator must be able to approve. Tighten by
				# ticking Prevent Self Expense Approval in HR Settings AND
				# unticking this — both, because the HR Settings guard is skipped
				# whenever a workflow exists.
				"allow_self_approval": 1,
			},
		)

	doc.flags.ignore_permissions = True
	doc.save()
	frappe.db.commit()


def backfill_workflow_state():
	"""Give every existing claim the state its standard fields already imply.

	Frappe's own backfill (Workflow.update_default_workflow_status) only knows
	docstatus, so it would label every submitted claim "Approved" — including the
	rejected and the already-paid ones. This runs after it and corrects them.
	"""
	claims = frappe.get_all(
		DOCTYPE,
		fields=["name", "docstatus", "approval_status", "status", STATE_FIELD],
	)

	for claim in claims:
		state = derive_state(claim)
		if claim.get(STATE_FIELD) != state:
			frappe.db.set_value(DOCTYPE, claim.name, STATE_FIELD, state, update_modified=False)

	frappe.db.commit()


def derive_state(claim):
	"""docstatus / approval_status / status -> workflow state. One mapping, used
	by the backfill and by ls_foods.reimbursement.stamp_workflow_state."""
	if claim.get("docstatus") == 2:
		return "Cancelled"
	if claim.get("approval_status") == "Rejected":
		return "Rejected"
	if claim.get("docstatus") == 0:
		return "Draft"
	return "Paid" if claim.get("status") == "Paid" else "Approved"
