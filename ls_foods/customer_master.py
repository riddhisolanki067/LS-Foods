"""LS Foods — Customer master: an automatic Customer ID, and Address / Phone /
Email grids on the Contact & Address tab.

Two requirements, one module, because they live on the same form.


1. Customer ID
--------------
The client numbers customers 1043, 1044, 1045 … and wants that number to carry
on by itself. ``custom_customer_id`` is a **Data** field, unique, editable:

  * ``before_insert`` fills it **only when it is blank**, with the number after
    the highest one already on file. Data (not Int) so a legacy scheme with a
    prefix or leading zeros ("A-1043", "001043") survives the import, and the
    next number keeps the same prefix and width.
  * Typing one in by hand still works — that is the import path and the
    correction path. ``validate`` rejects a duplicate with a readable message
    before MariaDB's unique index throws a raw one.

Why not a Naming Series? A series only drives ``name`` (the docname), and this
site names customers by customer name; and a series cannot be seeded from
numbers that already exist in the legacy data. Why not Int? Because an Int
silently drops "A-" and "00" — and this field exists to match the old system.


2. The three grids
------------------
The legacy screen keeps **many addresses, many phones and many emails on the
CUSTOMER** (not on a named contact person), each with its own Mailing /
Delivery / Current / Primary ticks. ERPNext keeps the same information, but in
separate ``Address`` and ``Contact`` documents reached through the sidebar.

So the grids are a *window*, never a second copy:

    Customer.custom_addresses       <->  Address           (one row = one Address)
    Customer.custom_phone_numbers   <->  Contact.phone_nos  \\  both on ONE Contact
    Customer.custom_email_addresses <->  Contact.email_ids  /   per customer

``on_update`` pushes the grids out to those records; ``Address.on_update`` and
``Contact.on_update`` pull edits made on the real forms back in, so the two
sides cannot drift and a later Customer save cannot overwrite the newer values.
``frappe.flags`` breaks the loop between the two directions.

Keeping the real records is the whole point: Sales Invoice, Delivery Note, the
print formats, the Contacts sidebar and the address pickers all read Address /
Contact. A flat child table would have looked identical and worked nowhere.

**Deleting is never destructive.** Untick *Current* to retire an address — that
mirrors onto the standard ``Address.disabled`` so pickers stop offering it,
while submitted invoices that already print it stay intact. Removing the row
outright does the same thing rather than deleting the Address.


Renaming fields for live
------------------------
Live already carries its own custom fields for these attributes. Every field
name used anywhere in this module is in the block below — change the
*right-hand* side of the maps here and the matching entry in
``ls_foods/setup/customer_setup.py``, and nothing else needs touching.
"""

import re
from contextlib import contextmanager

import frappe
from frappe import _
from frappe.utils import cint, cstr

# ---------------------------------------------------------------------------
# Field names — the only place they are spelled out
# ---------------------------------------------------------------------------

CUSTOMER_ID_FIELD = "custom_customer_id"

ADDRESS_TABLE = "custom_addresses"
PHONE_TABLE = "custom_phone_numbers"
EMAIL_TABLE = "custom_email_addresses"

ADDRESS_ENTRY = "Customer Address Entry"
PHONE_ENTRY = "Customer Phone Entry"
EMAIL_ENTRY = "Customer Email Entry"

# grid fieldname -> fieldname on the real record
ADDRESS_MAP = {
	"address_line1": "address_line1",
	"address_line2": "address_line2",
	"city": "city",
	"state": "state",
	"pincode": "pincode",
	"country": "country",
	"address_type": "address_type",
	"custom_mailing": "custom_mailing",
	"custom_delivery": "custom_delivery",
	"custom_current": "custom_current",
	"custom_turn": "custom_turn",
	"custom_clearance": "custom_clearance",
	"custom_notes": "custom_notes",
}

PHONE_MAP = {
	"phone": "phone",
	"is_primary_phone": "is_primary_phone",
	"custom_ext": "custom_ext",
	"custom_current": "custom_current",
	"custom_notify": "custom_notify",
	"custom_notes": "custom_notes",
}

EMAIL_MAP = {
	"email_id": "email_id",
	"is_primary": "is_primary",
	"custom_current": "custom_current",
	"custom_notes": "custom_notes",
}

SYNC_FLAG = "ls_foods_customer_sync"


# ---------------------------------------------------------------------------
# 1. Customer ID
# ---------------------------------------------------------------------------


def set_customer_id(doc, method=None):
	"""``before_insert`` on Customer — number the record if it came in blank.

	Runs on before_insert (not validate) so a Data Import that carries the
	legacy number keeps it, and so the value is settled before anything else
	reads it. ``doc.name`` does not exist yet at this point — nothing here
	needs it.
	"""
	if cstr(doc.get(CUSTOMER_ID_FIELD)).strip():
		return

	doc.set(CUSTOMER_ID_FIELD, next_customer_id())


def prepare_customer_master(doc, method=None):
	"""``validate`` on Customer — tidy and check everything the form collects."""
	validate_customer_id(doc)
	_fill_address_defaults(doc)
	_check_grid(doc, PHONE_TABLE, "phone", "is_primary_phone", _("phone number"))
	_check_grid(doc, EMAIL_TABLE, "email_id", "is_primary", _("email address"))


def validate_customer_id(doc, method=None):
	value = cstr(doc.get(CUSTOMER_ID_FIELD)).strip()
	if not value:
		return

	doc.set(CUSTOMER_ID_FIELD, value)

	clash = frappe.db.get_value(
		"Customer", {CUSTOMER_ID_FIELD: value, "name": ("!=", doc.name)}, "name"
	)
	if clash:
		frappe.throw(
			_("Customer ID {0} is already used by {1}.").format(frappe.bold(value), frappe.bold(clash)),
			title=_("Duplicate Customer ID"),
		)


_ID_PATTERN = re.compile(r"^(.*?)(\d+)$")


def next_customer_id() -> str:
	"""The number after the highest Customer ID on file.

	The newest numbered customer decides the *scheme* (any prefix, and the zero
	padding); the highest number using that same scheme decides the number. So
	1043 -> 1044, 001043 -> 001044, A-1043 -> A-1044. With nothing on file yet,
	numbering starts at 1 — import the legacy numbers first and it picks up
	from them instead.

	``for update`` holds the rows for the rest of the request's transaction, so
	two customers created at the same moment cannot both read 1043 and both try
	to write 1044 (the unique index would reject the loser outright).
	"""
	rows = frappe.db.sql(
		f"""select `{CUSTOMER_ID_FIELD}` as cid
		      from `tabCustomer`
		     where ifnull(`{CUSTOMER_ID_FIELD}`, '') != ''
		     order by creation desc
		       for update""",
		as_dict=True,
	)

	parsed = [p for p in (_split_id(row.cid) for row in rows) if p]
	if not parsed:
		return "1"

	prefix = parsed[0][1]
	same_scheme = [p for p in parsed if p[1] == prefix] or parsed
	number = max(p[0] for p in same_scheme)
	width = max(p[2] for p in same_scheme)

	return _format_id(number + 1, prefix, width)


def _increment(value) -> str:
	"""The number after ``value``, keeping its prefix and zero padding."""
	parsed = _split_id(value)
	if not parsed:
		return "1"

	number, prefix, width = parsed

	return _format_id(number + 1, prefix, width)


def _format_id(number, prefix, width) -> str:
	return f"{prefix}{number:0{width}d}"


def number_existing_customers(start=None, dry_run=False):
	"""Give every customer that has no Customer ID one, oldest first.

	**Deliberately not part of the migrate.** On a site where the legacy numbers
	have not been imported yet, numbering would start at 1 and the client's
	customers would come out 1, 2, 3 instead of 1043, 1044, 1045 — and undoing
	that means touching every master. So it is a decision to be made once, with
	eyes open:

	    # after importing the legacy numbers - just carries on from the highest
	    bench --site <site> execute ls_foods.customer_master.number_existing_customers

	    # nothing imported: state where the sequence begins
	    bench --site <site> execute ls_foods.customer_master.number_existing_customers \
	        --kwargs "{'start': 1043, 'dry_run': True}"

	``dry_run`` prints what it would do and writes nothing.

	Written straight to the column: this is one field moving into place, and a
	full save would fire every other validation on the site (and ERPNext's own
	primary-contact creation) on masters nobody has touched.
	"""
	names = frappe.get_all(
		"Customer",
		filters={CUSTOMER_ID_FIELD: ("in", (None, ""))},
		pluck="name",
		order_by="creation asc",
	)

	assigned = []
	previous = None

	for name in names:
		if previous is not None:
			# Carry on from what this run just handed out. A dry run writes
			# nothing, so re-reading the table would return the same number
			# every time round.
			number = _increment(previous)
		elif start is not None and not _highest_customer_id():
			number = cstr(start)
		else:
			number = next_customer_id()

		assigned.append((name, number))
		previous = number

		if dry_run:
			print(f"{name} -> {number}")
			continue

		frappe.db.set_value("Customer", name, CUSTOMER_ID_FIELD, number, update_modified=False)
		frappe.db.commit()

	print(f"{len(assigned)} customer(s) {'would be' if dry_run else ''} numbered")

	return assigned


def _highest_customer_id():
	return frappe.db.get_value("Customer", {CUSTOMER_ID_FIELD: ("is", "set")}, "name")


def _split_id(value):
	"""'A-001043' -> (1043, 'A-', 6). None when there is no number to carry on."""
	match = _ID_PATTERN.match(cstr(value).strip())
	if not match:
		return None

	prefix, digits = match.group(1), match.group(2)
	return int(digits), prefix, len(digits)


# ---------------------------------------------------------------------------
# 2a. Grid housekeeping (runs on validate, before anything is written out)
# ---------------------------------------------------------------------------


def _fill_address_defaults(doc):
	"""Supply the two fields Address insists on but the legacy screen has no
	column for: Country and Address Type.

	Address Type is inferred from the ticks — a delivery-only address is a
	Shipping address, anything else is Billing — and stays editable on the row.
	"""
	country = _default_country()

	for row in doc.get(ADDRESS_TABLE) or []:
		if not row.country:
			row.country = country
		if not row.address_type:
			row.address_type = (
				"Shipping" if cint(row.custom_delivery) and not cint(row.custom_mailing) else "Billing"
			)


def _check_grid(doc, table, value_field, primary_field, label):
	"""Reject duplicates, and hold the grid to Contact's one-primary rule.

	Contact throws "Only one Email ID can be set as primary" from deep inside
	frappe when a second primary reaches it — this catches it on the grid the
	user is actually looking at. Contact also force-ticks the only row when
	there is exactly one; doing the same here keeps the two sides identical, so
	the change-detection below does not see a phantom difference every save.
	"""
	rows = doc.get(table) or []
	if not rows:
		return

	seen = set()
	keep = []
	for row in rows:
		key = cstr(row.get(value_field)).strip().lower()
		if key and key in seen:
			# A duplicate the user just typed is a mistake worth stopping for. The
			# same duplicate arriving from a Contact that already holds it twice is
			# not the user's doing, and throwing here would make that Contact
			# unsavable from its own form — drop the row and carry on.
			if not frappe.flags.get(SYNC_FLAG):
				frappe.throw(
					_("{0} {1} is listed twice.").format(label.title(), frappe.bold(row.get(value_field)))
				)
			continue
		seen.add(key)
		keep.append(row)

	if len(keep) != len(rows):
		doc.set(table, keep)
		rows = keep

	primaries = [row for row in rows if cint(row.get(primary_field))]
	if len(primaries) > 1:
		frappe.throw(_("Only one {0} can be marked Primary.").format(label))
	if not primaries and len(rows) == 1:
		rows[0].set(primary_field, 1)


def _default_country():
	company = frappe.defaults.get_user_default("Company")
	country = company and frappe.db.get_value("Company", company, "country")
	if not country:
		country = frappe.db.get_default("country")
	if not country:
		companies = frappe.get_all("Company", fields=["country"], limit=1)
		country = companies[0].country if companies else None

	return country or "United States"


# ---------------------------------------------------------------------------
# 2b. Customer -> Address / Contact
# ---------------------------------------------------------------------------


def sync_addresses_and_contact(doc, method=None):
	"""``on_update`` on Customer.

	on_update, not validate: an Address or Contact carries a Dynamic Link to the
	customer, and that link cannot be validated against a row that is not in the
	database yet.
	"""
	if frappe.flags.get(SYNC_FLAG):
		return

	with _syncing():
		_push_addresses(doc)
		_push_contact(doc)


def _push_addresses(customer):
	kept = []

	for row in customer.get(ADDRESS_TABLE) or []:
		address = _upsert_address(customer, row)
		kept.append(address.name)
		if row.address != address.name:
			row.db_set("address", address.name, update_modified=False)

	_retire_unlisted_addresses(customer, kept)
	_set_preferred_addresses(customer)


def _upsert_address(customer, row):
	if row.address and frappe.db.exists("Address", row.address):
		address = frappe.get_doc("Address", row.address)
	else:
		address = frappe.new_doc("Address")
		address.address_title = customer.customer_name or customer.name

	dirty = bool(address.is_new())

	for grid_field, target in ADDRESS_MAP.items():
		if _set_if_changed(address, target, row.get(grid_field)):
			dirty = True

	# "Current" is the client's flag; `disabled` is the one ERPNext's address
	# pickers and party defaults actually read. Mirror one onto the other so
	# retiring an address in the grid really retires it.
	if _set_if_changed(address, "disabled", 0 if cint(row.custom_current) else 1):
		dirty = True

	if not any(
		link.link_doctype == "Customer" and link.link_name == customer.name for link in address.links
	):
		address.append("links", {"link_doctype": "Customer", "link_name": customer.name})
		dirty = True

	if dirty:
		address.flags.ignore_permissions = True
		address.save()

	return address


def _retire_unlisted_addresses(customer, kept):
	"""A row taken out of the grid disables its Address; it never deletes it.

	The Address may already be printed on a submitted Sales Invoice or Delivery
	Note. "Stop offering this address" is what the user meant; erasing history
	is not (and Frappe would refuse the delete anyway).
	"""
	for name in _linked_addresses(customer.name):
		if name in kept:
			continue
		if not cint(frappe.db.get_value("Address", name, "disabled")):
			frappe.db.set_value("Address", name, "disabled", 1, update_modified=False)


def _set_preferred_addresses(customer):
	"""Let the grid drive the address ERPNext puts on transactions.

	Rule: the first *current* row ticked Mailing is the preferred billing
	address, the first *current* row ticked Delivery is the preferred shipping
	address; if no current row carries the tick, the first row that does is used.
	Change ``_preferred`` to change the rule — nothing else depends on it.
	"""
	rows = [row for row in (customer.get(ADDRESS_TABLE) or []) if row.address]
	billing = _preferred(rows, "custom_mailing")
	shipping = _preferred(rows, "custom_delivery")

	for name in _linked_addresses(customer.name):
		frappe.db.set_value(
			"Address",
			name,
			{
				"is_primary_address": 1 if name == billing else 0,
				"is_shipping_address": 1 if name == shipping else 0,
			},
			update_modified=False,
		)

	if billing and customer.customer_primary_address != billing:
		from frappe.contacts.doctype.address.address import get_address_display

		customer.db_set("customer_primary_address", billing, update_modified=False)
		customer.db_set("primary_address", get_address_display(billing), update_modified=False)


def _preferred(rows, fieldname):
	ticked = [row for row in rows if cint(row.get(fieldname))]
	current = [row for row in ticked if cint(row.custom_current)]
	chosen = current or ticked

	return chosen[0].address if chosen else None


def _push_contact(customer):
	"""All the phone and email rows go on ONE Contact per customer.

	That is what the legacy screen means: these belong to the customer, not to a
	named person. Reusing ``customer_primary_contact`` (or the oldest linked
	Contact) also means ERPNext's own Customer.mobile_no / email_id keep
	resolving, since both are fetched from the primary contact.
	"""
	phones = customer.get(PHONE_TABLE) or []
	emails = customer.get(EMAIL_TABLE) or []

	contact = _customer_contact(customer, create=bool(phones or emails))
	if not contact:
		return

	dirty = bool(contact.is_new())
	dirty |= _replace_rows(contact, "phone_nos", phones, PHONE_MAP, "Contact Phone")
	dirty |= _replace_rows(contact, "email_ids", emails, EMAIL_MAP, "Contact Email")

	# One "Primary" tick fills both of Contact's primary flags. Contact.phone
	# comes from is_primary_phone and Contact.mobile_no from is_primary_mobile_no,
	# and Customer.mobile_no is fetched from the latter — leave it unset and the
	# customer's mobile number stays blank for no visible reason.
	for child in contact.phone_nos:
		if cint(child.is_primary_mobile_no) != cint(child.is_primary_phone):
			child.is_primary_mobile_no = cint(child.is_primary_phone)
			dirty = True

	if dirty:
		contact.flags.ignore_permissions = True
		contact.save()

	customer.db_set(
		{
			"customer_primary_contact": contact.name,
			"mobile_no": contact.mobile_no,
			"email_id": contact.email_id,
		},
		update_modified=False,
	)


def _customer_contact(customer, create=False):
	name = customer.customer_primary_contact

	if not name:
		linked = frappe.get_all(
			"Dynamic Link",
			filters={
				"link_doctype": "Customer",
				"link_name": customer.name,
				"parenttype": "Contact",
			},
			pluck="parent",
			order_by="creation asc",
			limit=1,
		)
		name = linked[0] if linked else None

	if name and frappe.db.exists("Contact", name):
		return frappe.get_doc("Contact", name)

	if not create:
		return None

	contact = frappe.new_doc("Contact")
	contact.first_name = (customer.customer_name or customer.name)[:140]
	contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})

	return contact


# ---------------------------------------------------------------------------
# 2c. Address / Contact -> Customer  (edits made on the real forms)
# ---------------------------------------------------------------------------


def pull_address_into_customers(doc, method=None):
	"""``on_update`` on Address.

	Without this the grid goes stale the moment anyone edits the Address form,
	and the customer's next save would quietly push the old values back over the
	new ones.
	"""
	if frappe.flags.get(SYNC_FLAG):
		return

	with _syncing():
		for link in doc.links:
			if link.link_doctype != "Customer" or not frappe.db.exists("Customer", link.link_name):
				continue

			row = frappe.db.get_value(
				ADDRESS_ENTRY,
				{
					"parenttype": "Customer",
					"parent": link.link_name,
					"parentfield": ADDRESS_TABLE,
					"address": doc.name,
				},
				"name",
			)

			values = {grid_field: doc.get(target) for grid_field, target in ADDRESS_MAP.items()}

			if row:
				frappe.db.set_value(ADDRESS_ENTRY, row, values, update_modified=False)
			else:
				customer = frappe.get_doc("Customer", link.link_name)
				customer.append(ADDRESS_TABLE, dict(values, address=doc.name))
				customer.flags.ignore_permissions = True
				customer.save()


def drop_address_from_customers(doc, method=None):
	"""``on_trash`` on Address — take the row out of the grid rather than leave
	it pointing at a document that no longer exists."""
	frappe.db.delete(ADDRESS_ENTRY, {"address": doc.name})


def pull_contact_into_customers(doc, method=None):
	"""``on_update`` on Contact — same idea, for the phone and email grids.

	Only the customer's *designated* contact feeds the grids. A second contact
	person on the same customer is a normal ERPNext record and is left alone.
	"""
	if frappe.flags.get(SYNC_FLAG):
		return

	with _syncing():
		for link in doc.links:
			if link.link_doctype != "Customer" or not frappe.db.exists("Customer", link.link_name):
				continue

			customer = frappe.get_doc("Customer", link.link_name)
			designated = _customer_contact(customer)
			if not designated or designated.name != doc.name:
				continue

			changed = _replace_rows(customer, PHONE_TABLE, doc.phone_nos, PHONE_MAP, PHONE_ENTRY, reverse=True)
			changed |= _replace_rows(customer, EMAIL_TABLE, doc.email_ids, EMAIL_MAP, EMAIL_ENTRY, reverse=True)

			if changed:
				customer.flags.ignore_permissions = True
				customer.save()


# ---------------------------------------------------------------------------
# Pull everything in — the form button, and the backfill for existing customers
# ---------------------------------------------------------------------------


@frappe.whitelist()
def load_from_address_and_contact(customer: str):
	"""Fill the grids from every Address linked to the customer and from its
	Contact. Used by the button on the form and by the v0_0_6 patch, so
	customers that pre-date this feature show what they already have."""
	frappe.has_permission("Customer", "write", doc=customer, throw=True)

	doc = frappe.get_doc("Customer", customer)
	changed = False

	with _syncing():
		changed |= _load_addresses(doc)

		contact = _customer_contact(doc)
		if contact:
			changed |= _replace_rows(doc, PHONE_TABLE, contact.phone_nos, PHONE_MAP, PHONE_ENTRY, reverse=True)
			changed |= _replace_rows(doc, EMAIL_TABLE, contact.email_ids, EMAIL_MAP, EMAIL_ENTRY, reverse=True)

		if changed:
			doc.flags.ignore_permissions = True
			doc.save()

	return changed


def _load_addresses(customer):
	listed = {row.address for row in (customer.get(ADDRESS_TABLE) or []) if row.address}
	changed = False

	for name in _linked_addresses(customer.name):
		if name in listed:
			continue

		address = frappe.get_doc("Address", name)
		values = {grid_field: address.get(target) for grid_field, target in ADDRESS_MAP.items()}
		customer.append(ADDRESS_TABLE, dict(values, address=name))
		changed = True

	return changed


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


@contextmanager
def _syncing():
	"""Break the Customer -> Address/Contact -> Customer loop.

	Both directions are wired up on purpose; this is what stops them calling
	each other forever.
	"""
	frappe.flags[SYNC_FLAG] = True
	try:
		yield
	finally:
		frappe.flags[SYNC_FLAG] = False


def _replace_rows(parent, table, source_rows, field_map, child_doctype, reverse=False):
	"""Rewrite ``parent.<table>`` from ``source_rows``, and say whether it changed.

	``field_map`` is written grid-side -> record-side; ``reverse=True`` reads the
	record side and writes the grid side. Returning False on no-change is what
	keeps an ordinary Customer save from re-saving the Contact (and an ordinary
	Contact save from re-saving the Customer) every single time.
	"""
	pairs = [(v, k) for k, v in field_map.items()] if reverse else list(field_map.items())

	desired = [
		{target: _normalise(child_doctype, target, row.get(source)) for source, target in pairs}
		for row in source_rows
	]
	current = [
		{target: _normalise(child_doctype, target, row.get(target)) for _source, target in pairs}
		for row in parent.get(table) or []
	]

	if current == desired:
		return False

	parent.set(table, [])
	for values in desired:
		parent.append(table, values)

	return True


def _normalise(doctype, fieldname, value):
	if _is_check(doctype, fieldname):
		return cint(value)

	return cstr(value or "").strip() or None


def _set_if_changed(doc, fieldname, value):
	value = _normalise(doc.doctype, fieldname, value)
	if _normalise(doc.doctype, fieldname, doc.get(fieldname)) == value:
		return False

	doc.set(fieldname, value)

	return True


def _is_check(doctype, fieldname):
	field = frappe.get_meta(doctype).get_field(fieldname)

	return bool(field) and field.fieldtype == "Check"


def _linked_addresses(customer):
	return frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Address"},
		pluck="parent",
		order_by="creation asc",
	)
