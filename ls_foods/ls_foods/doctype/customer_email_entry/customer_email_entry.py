# Copyright (c) 2026, Riddhi and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CustomerEmailEntry(Document):
	"""Child table on Customer (fieldname ``custom_email_addresses``).

	Mirrors the ``email_ids`` table of the customer's Contact - the same single
	Contact that holds the phone rows. See ``ls_foods.customer_master``.
	"""

	pass
