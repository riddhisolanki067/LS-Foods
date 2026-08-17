"""v0_0_5 — Expense Claim: purchase dates, an open approver field, and the
Draft -> Approved/Rejected -> Paid workflow.

Idempotent; re-runnable. What it does:

  1. Adds the **Approver / Approver Name** fields and hides the standard Expense
     Approver, whose link query throws unless an approver is pre-set on the
     Employee or the Department (LS Foods has neither — whoever signs off picks
     themselves). Existing claims have their standard approver copied into the
     new field so nothing is lost.
  2. Greys out the auto-maintained Purchased Items mirror row in the Expenses
     table, per row, and back-fills the new **Date** column on Purchased Items
     rows from the claim's posting date so the mirror rows keep their date.
  3. Creates the workflow, the Workflow States it needs (Draft / Paid /
     Cancelled did not exist) and the Cancel action, then gives every existing
     claim the state its standard fields already imply.

The workflow itself is rebuilt from ls_foods/setup/expense_claim_workflow.py on
every run, so that file — not the UI — is the source of truth.
"""

import frappe

from ls_foods.setup import reimbursement_setup


def execute():
	# Creates the new custom fields, applies the property setters (hidden standard
	# approver, per-row read-only on the auto rows), and builds the workflow with
	# its backfill.
	reimbursement_setup.run()

	_backfill_purchase_dates()
	_backfill_approver()

	frappe.clear_cache()


def _backfill_purchase_dates():
	"""Give pre-existing Purchased Items rows a date.

	The column is mandatory from now on, and a blank one would make the mirrored
	expense row undated. The claim's posting date is the only honest value
	available retrospectively — it is what the mirror row used to be stamped with.
	"""
	table = "tabReimbursement Stock Item"
	columns = {
		c.get("Field") or c.get("column_name") for c in frappe.db.sql(f"desc `{table}`", as_dict=True)
	}
	if "expense_date" not in columns:
		return

	frappe.db.sql(
		f"""update `{table}` item
		      join `tabExpense Claim` claim on claim.name = item.parent
		       set item.expense_date = claim.posting_date
		     where ifnull(item.expense_date, '') = ''"""
	)
	frappe.db.commit()


def _backfill_approver():
	"""Copy the standard Expense Approver into the new field on existing claims.

	Direct writes: submitted claims cannot be saved, and this is the same value
	moving between two fields — there is nothing for validation to check.
	"""
	claims = frappe.get_all(
		"Expense Claim",
		filters={"expense_approver": ["is", "set"]},
		fields=["name", "expense_approver", "custom_approver"],
	)

	for claim in claims:
		if claim.custom_approver:
			continue

		name = frappe.db.get_value("User", claim.expense_approver, "full_name")
		frappe.db.set_value(
			"Expense Claim",
			claim.name,
			{"custom_approver": claim.expense_approver, "custom_approver_name": name},
			update_modified=False,
		)

	frappe.db.commit()
