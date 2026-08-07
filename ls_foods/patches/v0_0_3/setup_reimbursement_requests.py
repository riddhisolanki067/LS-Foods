"""v0_0_3 — Expense Reimbursement Request: dates, status, Qty x Rate, receipts,
and paying approved claims out through the Salary Slip.

Idempotent; re-runnable. What it does:

  1. Adds the request / approval / paid date fields, the Requested-Approved-Paid
     status and the expense-type summary to Expense Claim.
  2. Replaces the mileage-only Miles / Rate per Mile pair on the expense rows
     with the generic Qty / Rate pair, and DELETES the two old custom fields.
     Any values already captured are copied across first (there were no claims
     on this site when the change was written, so this is belt-and-braces).
  3. Adds the Receipt attachment plus the Receipt Required switch on Expense
     Claim Type, exempting Mileage.
  4. Adds the Reimbursements tab to the Salary Slip.
  5. Backfills the status / summary / request date on any claim that already
     exists, so the new list columns are not blank for historical records.
"""

import frappe

from ls_foods.setup import reimbursement_setup


def execute():
	_carry_mileage_values_to_qty_rate()

	# Creates the new fields, drops the deprecated ones, sets the list columns,
	# seeds Receipt Required per claim type.
	reimbursement_setup.run()

	_backfill_existing_claims()

	frappe.clear_cache()


def _carry_mileage_values_to_qty_rate():
	"""Copy Miles / Rate per Mile into Qty / Rate before the old fields go.

	Runs BEFORE reimbursement_setup so the source columns still exist as custom
	fields; the target columns are created by an earlier `bench migrate` pass or
	by this same run, so guard on both sides.
	"""
	table = "tabExpense Claim Detail"
	columns = {c.get("Field") or c.get("column_name") for c in frappe.db.sql(f"desc `{table}`", as_dict=True)}

	if not {"custom_miles", "custom_rate_per_mile"} <= columns:
		return
	if not {"custom_qty", "custom_rate"} <= columns:
		return

	frappe.db.sql(
		f"""update `{table}`
		    set custom_qty  = custom_miles,
		        custom_rate = custom_rate_per_mile
		  where ifnull(custom_miles, 0) != 0
		    and ifnull(custom_qty, 0) = 0"""
	)
	frappe.db.commit()


def _backfill_existing_claims():
	"""Fill the new derived fields on claims created before this change.

	Uses direct writes rather than a save() loop: submitted claims cannot be
	saved, and every one of these fields is derived, so there is nothing for
	validation to protect.
	"""
	claims = frappe.get_all(
		"Expense Claim",
		fields=["name", "docstatus", "approval_status", "status", "posting_date"],
	)

	for claim in claims:
		types = frappe.get_all(
			"Expense Claim Detail",
			filters={"parent": claim.name, "parenttype": "Expense Claim"},
			pluck="expense_type",
		)
		seen = []
		for t in types:
			if t and t not in seen:
				seen.append(t)

		if claim.docstatus == 2:
			status = "Cancelled"
		elif claim.approval_status == "Rejected":
			status = "Rejected"
		elif claim.docstatus == 0:
			status = "Approved" if claim.approval_status == "Approved" else "Requested"
		elif claim.status == "Paid":
			status = "Paid"
		else:
			status = "Approved"

		values = {
			"custom_expense_type_summary": ", ".join(seen)[:140],
			"custom_reimbursement_status": status,
		}
		if not frappe.db.get_value("Expense Claim", claim.name, "custom_request_date"):
			values["custom_request_date"] = claim.posting_date
		if status in ("Approved", "Paid") and not frappe.db.get_value(
			"Expense Claim", claim.name, "custom_approval_date"
		):
			values["custom_approval_date"] = claim.posting_date

		frappe.db.set_value("Expense Claim", claim.name, values, update_modified=False)

	frappe.db.commit()
