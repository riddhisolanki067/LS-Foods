# Copyright (c) 2026, Riddhi and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CustomerPhoneEntry(Document):
	"""Child table on Customer (fieldname ``custom_phone_numbers``).

	Mirrors the ``phone_nos`` table of the customer's Contact. The legacy screen
	keeps phone numbers on the CUSTOMER, not on a named contact person, so all
	rows land on a single Contact - see ``ls_foods.customer_master``.
	"""

	pass
