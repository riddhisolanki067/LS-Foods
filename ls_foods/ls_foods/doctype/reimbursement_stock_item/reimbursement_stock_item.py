# Copyright (c) 2026, Riddhi and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class ReimbursementStockItem(Document):
	"""Child table on Expense Claim (fieldname ``custom_stock_items``).

	One row = one thing the employee bought out of pocket. If the Item maintains
	stock, submitting the claim posts a Stock Entry (Material Receipt) so the
	inventory goes up; if it does not, the amount is charged straight to the
	item's expense account. Either way the employee is reimbursed through the
	standard Expense Claim payable. See ``ls_foods/reimbursement.py``.
	"""

	pass
