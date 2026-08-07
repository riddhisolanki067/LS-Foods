# Copyright (c) 2026, Riddhi and contributors
# For license information, please see license.txt

"""Expense Reimbursement Register — one line per expense, not per claim.

The Expense Claim list view answers "what is outstanding right now"; this
answers "what did we reimburse, for what, and when". It goes one level deeper
than the list because the four dates the client cares about live at two levels:
the expense date is on the row, while the request / approval / paid dates belong
to the claim. Joining them is the only way to see all four side by side.

Auto-generated rows (the mirror ls_foods maintains for the Purchased Items
table) are excluded — they would double-count against the Purchased Items they
summarise. Set the "Show Purchased Items Detail" filter to see those instead.
"""

import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns():
	return [
		{
			"label": _("Request"),
			"fieldname": "expense_claim",
			"fieldtype": "Link",
			"options": "Expense Claim",
			"width": 130,
		},
		{"label": _("Request Date"), "fieldname": "request_date", "fieldtype": "Date", "width": 105},
		{
			"label": _("Employee"),
			"fieldname": "employee",
			"fieldtype": "Link",
			"options": "Employee",
			"width": 110,
		},
		{"label": _("Employee Name"), "fieldname": "employee_name", "fieldtype": "Data", "width": 150},
		{"label": _("Expense Date"), "fieldname": "expense_date", "fieldtype": "Date", "width": 105},
		{
			"label": _("Expense Claim Type"),
			"fieldname": "expense_type",
			"fieldtype": "Link",
			"options": "Expense Claim Type",
			"width": 160,
		},
		{"label": _("Qty"), "fieldname": "qty", "fieldtype": "Float", "width": 70, "precision": 2},
		{"label": _("Rate"), "fieldname": "rate", "fieldtype": "Currency", "width": 90},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 110},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Approval Date"), "fieldname": "approval_date", "fieldtype": "Date", "width": 110},
		{"label": _("Paid Date"), "fieldname": "paid_date", "fieldtype": "Date", "width": 100},
		{
			"label": _("Paid via Salary Slip"),
			"fieldname": "salary_slip",
			"fieldtype": "Link",
			"options": "Salary Slip",
			"width": 170,
		},
		{"label": _("Receipt"), "fieldname": "receipt", "fieldtype": "Data", "width": 80},
		{
			"label": _("Account"),
			"fieldname": "account",
			"fieldtype": "Link",
			"options": "Account",
			"width": 200,
		},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 150,
		},
	]


def get_data(filters):
	conditions, values = build_conditions(filters)

	rows = frappe.db.sql(
		f"""
		select
			ec.name                          as expense_claim,
			ec.custom_request_date           as request_date,
			ec.employee                      as employee,
			ec.employee_name                 as employee_name,
			ecd.expense_date                 as expense_date,
			ecd.expense_type                 as expense_type,
			ecd.custom_qty                   as qty,
			ecd.custom_rate                  as rate,
			ecd.sanctioned_amount            as amount,
			ec.custom_reimbursement_status   as status,
			ec.custom_approval_date          as approval_date,
			ec.custom_paid_date              as paid_date,
			ec.custom_salary_slip            as salary_slip,
			ecd.custom_receipt               as receipt_url,
			ecd.default_account              as account,
			ec.company                       as company
		from `tabExpense Claim` ec
		inner join `tabExpense Claim Detail` ecd
			on ecd.parent = ec.name and ecd.parenttype = 'Expense Claim'
		where ec.docstatus < 2
			and ifnull(ecd.custom_auto_generated, 0) = 0
			{conditions}
		order by ec.custom_request_date desc, ec.name desc, ecd.idx asc
		""",
		values,
		as_dict=True,
	)

	for row in rows:
		# A clickable word beats a raw /files/... path in a register someone reads.
		row["receipt"] = (
			f'<a href="{row.receipt_url}" target="_blank">{_("View")}</a>' if row.receipt_url else ""
		)

	return rows


def build_conditions(filters):
	"""Optional filters, parameterised — never string-formatted into the SQL."""
	conditions = []
	values = {}

	if filters.get("company"):
		conditions.append("and ec.company = %(company)s")
		values["company"] = filters.company

	if filters.get("employee"):
		conditions.append("and ec.employee = %(employee)s")
		values["employee"] = filters.employee

	if filters.get("expense_type"):
		conditions.append("and ecd.expense_type = %(expense_type)s")
		values["expense_type"] = filters.expense_type

	if filters.get("status"):
		conditions.append("and ec.custom_reimbursement_status = %(status)s")
		values["status"] = filters.status

	# The date range applies to whichever date the user is actually asking about,
	# because "everything approved in July" and "everything paid in July" are
	# different questions and both get asked.
	date_field = {
		"Request Date": "ec.custom_request_date",
		"Expense Date": "ecd.expense_date",
		"Approval Date": "ec.custom_approval_date",
		"Paid Date": "ec.custom_paid_date",
	}.get(filters.get("date_type") or "Request Date", "ec.custom_request_date")

	if filters.get("from_date"):
		conditions.append(f"and {date_field} >= %(from_date)s")
		values["from_date"] = filters.from_date

	if filters.get("to_date"):
		conditions.append(f"and {date_field} <= %(to_date)s")
		values["to_date"] = filters.to_date

	return "\n\t\t\t".join(conditions), values
