# Copyright (c) 2026, Riddhi and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CustomerAddressEntry(Document):
	"""Child table on Customer (fieldname ``custom_addresses``).

	One row = one real **Address** document linked to the customer. The row is a
	window onto that Address, not a copy of it: ``ls_foods.customer_master``
	creates/updates the Address on every Customer save and writes the resulting
	name back into ``address``. Everything ERPNext already does with addresses
	(Sales Invoice shipping address, print formats, the Contact & Address
	sidebar) therefore keeps working - the grid is only a faster way to maintain
	them, the way the client's legacy screen did.
	"""

	pass
