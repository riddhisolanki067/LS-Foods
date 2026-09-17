"""LS Foods — Customer master setup: the custom fields behind the Customer ID
and the Address / Phone / Email grids.

Everything here is idempotent (``create_custom_fields`` only ever inserts), so
it is safe on ``bench migrate`` and safe to re-run by hand.

Renaming for live
-----------------
Live already carries its own custom fields for the address and phone
attributes. To adopt those names, change the ``fieldname`` here **and** the
right-hand side of the matching map in ``ls_foods/customer_master.py`` — those
two files are the only places a field name appears. Note that
``create_custom_fields`` skips a field that already exists, so re-pointing the
maps at live's existing fields needs no data move at all.

The grid columns (``Customer Address Entry`` and friends) are ordinary DocType
fields owned by this app, so they keep their names either way; only the
right-hand side of the maps changes.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from ls_foods.customer_master import (
	ADDRESS_ENTRY,
	ADDRESS_TABLE,
	CUSTOMER_ID_FIELD,
	EMAIL_ENTRY,
	EMAIL_TABLE,
	PHONE_ENTRY,
	PHONE_TABLE,
)

MODULE = "Ls Foods"

NOTIFY_OPTIONS = "\nText\nCall\nEmail"

CUSTOM_FIELDS = {
	"Customer": [
		{
			"fieldname": CUSTOMER_ID_FIELD,
			"label": "Customer ID",
			"fieldtype": "Data",
			"insert_after": "customer_name",
			"unique": 1,
			"no_copy": 1,
			"bold": 1,
			"in_standard_filter": 1,
			"description": (
				"The client's own customer number. Left blank it is filled on save with "
				"the number after the highest one on file. Type one in to keep a legacy "
				"number or to correct it."
			),
			"module": MODULE,
		},
		{
			"fieldname": "custom_ls_contact_section",
			"label": "Addresses, Phone Numbers & Emails",
			"fieldtype": "Section Break",
			"insert_after": "last_name",
			"module": MODULE,
		},
		{
			"fieldname": ADDRESS_TABLE,
			"label": "Addresses",
			"fieldtype": "Table",
			"options": ADDRESS_ENTRY,
			"insert_after": "custom_ls_contact_section",
			"description": (
				"Each row is a real Address document. Untick Current to retire one — the "
				"Address is disabled, never deleted, so documents that already print it "
				"stay intact."
			),
			"module": MODULE,
		},
		{
			"fieldname": PHONE_TABLE,
			"label": "Phone Numbers",
			"fieldtype": "Table",
			"options": PHONE_ENTRY,
			"insert_after": ADDRESS_TABLE,
			"description": "Kept in step with the Phone Nos table of the customer's contact.",
			"module": MODULE,
		},
		{
			"fieldname": EMAIL_TABLE,
			"label": "Email Addresses",
			"fieldtype": "Table",
			"options": EMAIL_ENTRY,
			"insert_after": PHONE_TABLE,
			"description": "Kept in step with the Email IDs table of the customer's contact.",
			"module": MODULE,
		},
	],
	"Address": [
		{
			"fieldname": "custom_mailing",
			"label": "Mailing",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "is_shipping_address",
			"module": MODULE,
		},
		{
			"fieldname": "custom_delivery",
			"label": "Delivery",
			"fieldtype": "Check",
			"default": "0",
			"insert_after": "custom_mailing",
			"module": MODULE,
		},
		{
			"fieldname": "custom_current",
			"label": "Current",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "custom_delivery",
			"description": "Unticking this disables the address, so pickers stop offering it.",
			"module": MODULE,
		},
		{
			"fieldname": "custom_turn",
			"label": "Turn",
			"fieldtype": "Data",
			"insert_after": "custom_current",
			"module": MODULE,
		},
		{
			"fieldname": "custom_clearance",
			"label": "Clearance",
			"fieldtype": "Data",
			"insert_after": "custom_turn",
			"module": MODULE,
		},
		{
			"fieldname": "custom_notes",
			"label": "Notes",
			"fieldtype": "Small Text",
			"insert_after": "custom_clearance",
			"module": MODULE,
		},
	],
	"Contact Phone": [
		{
			"fieldname": "custom_ext",
			"label": "Ext",
			"fieldtype": "Data",
			"insert_after": "phone",
			"module": MODULE,
		},
		{
			"fieldname": "custom_current",
			"label": "Current",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "is_primary_mobile_no",
			"module": MODULE,
		},
		{
			"fieldname": "custom_notify",
			"label": "Notify",
			"fieldtype": "Select",
			"options": NOTIFY_OPTIONS,
			"insert_after": "custom_current",
			"module": MODULE,
		},
		{
			"fieldname": "custom_notes",
			"label": "Notes",
			"fieldtype": "Small Text",
			"insert_after": "custom_notify",
			"module": MODULE,
		},
	],
	"Contact Email": [
		{
			"fieldname": "custom_current",
			"label": "Current",
			"fieldtype": "Check",
			"default": "1",
			"insert_after": "is_primary",
			"module": MODULE,
		},
		{
			"fieldname": "custom_notes",
			"label": "Notes",
			"fieldtype": "Small Text",
			"insert_after": "custom_current",
			"module": MODULE,
		},
	],
}


def run():
	"""Create the custom fields. Idempotent — safe on every migrate."""
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)

	for doctype in ("Customer", "Address", "Contact", "Contact Phone", "Contact Email"):
		frappe.clear_cache(doctype=doctype)


def install():
	"""``run()`` plus the one-shot backfill. Called from ``after_install`` and
	from the v0_0_6 patch — both of which run exactly once."""
	run()
	backfill_current_flags()


def backfill_current_flags():
	"""Give rows that pre-date the Current tick the right value.

	``create_custom_fields`` adds the column but does not go back and apply the
	default to what is already there, and a blank Current reads as "retired" —
	the first Customer save would then disable every address the customer has.
	An address is current unless it is already disabled; a phone or email row
	has nothing that says otherwise, so it is current.

	**One-shot on purpose.** Re-running this would un-retire everything the user
	has since unticked, which is why it is not part of ``run()``.
	"""
	frappe.db.sql(
		"""update `tabAddress`
		      set custom_current = 1
		    where ifnull(custom_current, 0) = 0
		      and ifnull(disabled, 0) = 0"""
	)

	for table in ("tabContact Phone", "tabContact Email"):
		frappe.db.sql(f"update `{table}` set custom_current = 1 where ifnull(custom_current, 0) = 0")

	frappe.db.commit()
