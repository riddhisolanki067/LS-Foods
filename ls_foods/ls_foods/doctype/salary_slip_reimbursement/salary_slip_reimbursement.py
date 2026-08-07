# Copyright (c) 2026, Riddhi and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class SalarySlipReimbursement(Document):
	"""Child table on Salary Slip (fieldname ``custom_reimbursements``).

	One row = one approved, unpaid Expense Claim being reimbursed with this
	paycheck. The payroll clerk fetches them with the "Get Approved
	Reimbursements" button and can reassign the expense account per row before
	submitting. See ``ls_foods/reimbursement_payroll.py`` for the fetch, the
	net-pay arithmetic and the journal entry.
	"""

	pass
