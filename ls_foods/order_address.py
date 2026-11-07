"""Billing and shipping address can be changed on an order or invoice, also after
it is submitted. Customers move after they order.

Each address is two fields: the Address link (customer_address /
shipping_address_name) and the text printed on the PDF (address_display /
shipping_address). Both are made editable on Sales Order and Sales Invoice, draft
and submitted (see setup/order_address_setup.py):

* Pick another Address in the link: the text is filled from it (ERPNext's form
  does it as you pick; ``update_after_submit`` makes sure on a submitted one).
* Type straight into the text, for a one-off address: the typed text is kept.
  ERPNext rewrites the text from the link on every save of a draft
  (SellingController.set_customer_address); ``keep_typed_address`` (before_validate)
  and ``restore_typed_address`` (validate, after the controller) put it back.
  The same keeps an order's address text on an invoice made from it.
* Clear the text and save: it is filled from the Address link again (the way
  to pick up an edit made to the Address record itself).

Neither field reaches the ledger, and the site has no Tax Rules, so changing an
address after submit moves no amounts.
"""

import re

from frappe.contacts.doctype.address.address import render_address

PAIRS = (
	("customer_address", "address_display"),
	("shipping_address_name", "shipping_address"),
)


def as_address_html(text):
	"""Typed lines -> ERPNext's address format (``<br>`` line breaks), so the PDF
	prints them on separate lines. Text already in that format is left as is."""
	if not text or not re.search(r"(?<!<br>)\n", text):
		return text
	lines = [line.strip() for line in re.split(r"<br\s*/?>|\n", text)]
	return "<br>\n".join(line for line in lines if line) + "<br>\n"


def keep_typed_address(doc, method=None):
	"""before_validate: remember address text that should survive the save."""
	before = doc.get_doc_before_save()
	keep = {}
	for link, text in PAIRS:
		value = doc.get(text)
		if not value:
			continue  # cleared: let ERPNext fill it from the link
		if before is None or before.get(link) == doc.get(link):
			keep[text] = as_address_html(value)  # a new link means new text (the form filled it)
	doc.flags.ls_foods_typed_address = keep


def restore_typed_address(doc, method=None):
	"""validate: undo ERPNext's re-render of the text kept above."""
	for text, value in (doc.flags.ls_foods_typed_address or {}).items():
		doc.set(text, value)


def update_after_submit(doc, method=None):
	"""before_update_after_submit: a submitted document whose address was changed."""
	before = doc.get_doc_before_save()
	changed = [link for link, _ in PAIRS if before and doc.get(link) != before.get(link)]
	if changed:
		# the address must be one of this customer's (same check ERPNext runs on save)
		doc.validate_party_address(doc.customer, "Customer", doc.customer_address, doc.shipping_address_name)
	for link, text in PAIRS:
		if link in changed and doc.get(link) and doc.get(text) == before.get(text):
			doc.set(text, render_address(doc.get(link), check_permissions=False))
		else:
			doc.set(text, as_address_html(doc.get(text)))
