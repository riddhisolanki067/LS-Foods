"""LS Foods — Pick-Up Location master and its link on the Sales Order.

The client already tracked this on the Sales Order as a **Select** they built
themselves (``custom_pickup_location``, options "1 - Ma's Pantry" … "10 - Home
Delivery"). A Select can only hold a label: no pick-up time, no address, no
contact, and a new season's change means editing field options. So:

  * ``Pick-Up Location`` is a master (ls_foods/ls_foods/doctype/pick_up_location)
    holding number, name, pick-up time, contact and address.
  * ``custom_pick_up_location`` on Sales Order is a **Link** to it. It is a new
    field rather than the old one converted, because Frappe does not allow a
    Select to be turned into a Link.
  * The old Select was hidden first and, once live orders were moved over,
    removed (patch v0_1_0). Its DB column is left behind by Frappe on purpose.
  * Home Delivery is location **0** (it was option 10 on the old Select).

The locations are seeded once from the 2026 Fall flyer ("Pick-Up Locations",
Saturday, October 24, 2026). After that they are the client's data: the seed
never overwrites a location that already exists.
"""

import re

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint

MODULE = "Ls Foods"
MASTER = "Pick-Up Location"

OLD_SELECT_FIELD = "custom_pickup_location"
LINK_FIELD = "custom_pick_up_location"

HOME_DELIVERY_NUMBER = 0
# Option 10 on the client's old Select was Home Delivery.
OLD_HOME_DELIVERY_NUMBER = 10

CUSTOM_FIELDS = {
	"Sales Order": [
		{
			"fieldname": LINK_FIELD,
			"label": "Pick-Up Location",
			"fieldtype": "Link",
			"options": MASTER,
			# where the old Select sat, so the field keeps its place after the Select is gone
			"insert_after": "tax_id",
			"in_standard_filter": 1,
			"allow_on_submit": 1,
			"description": "Type the number from the order form. 0 is Home Delivery.",
			"module": MODULE,
		},
	],
}

# (number, name, pick-up time, address, city, state, zip) — 2026 Fall flyer.
LOCATIONS = [
	(1, "Ma's Pantry", "8:30 - 9:00 am", "16228 Co Rd 22", "Goshen", "IN", "46528"),
	(2, "R&M Produce Supplies", "9:45 - 10:00 am", "64482 Co Rd 9", "Goshen", "IN", "46526"),
	(3, "Miller Custom Plastics", "10:30 - 11:00 am", "27012 Co Rd 50", "Nappanee", "IN", "46550"),
	(4, "Schwartz Powder Coating", "11:30 - 12:00 pm", "13492 N 950 W", "Nappanee", "IN", "46550"),
	(5, "Battery Tech, LLC", "1:00 - 2:00 pm", "503 Carriage Lane", "Millersburg", "IN", "46543"),
	(6, "Basic Ag", "3:00 - 3:15 pm", "2375 IN-5", "Topeka", "IN", "46571"),
	(7, "Northern Nutrition, LLC", "4:00 - 4:15 pm", "2195 N 700 W", "Shipshewana", "IN", "46565"),
	(8, "Leonard & Miriam Bontrager", None, "5826 7th Rd", "Plymouth", "IN", "46563"),
	(9, "Amzie & Edna Martin", None, "7640 N 150 W", "Rochester", "IN", "46975"),
]


def run():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)
	seed_locations()
	backfill_sales_orders()
	frappe.clear_cache(doctype="Sales Order")


def seed_locations():
	"""Create locations 0-9 from the flyer; leave any that already exist alone."""
	_ensure(HOME_DELIVERY_NUMBER, location_name="Home Delivery", is_home_delivery=1)
	for number, name, time, address, city, state, pincode in LOCATIONS:
		_ensure(
			number,
			location_name=name,
			pickup_time=time,
			address_line1=address,
			city=city,
			state=state,
			pincode=pincode,
		)


def _ensure(number, **values):
	if frappe.db.exists(MASTER, {"location_number": number}):
		return
	frappe.get_doc({"doctype": MASTER, "location_number": number, **values}).insert(ignore_permissions=True)


def remove_old_select():
	"""Delete the client's old Select once every order carries the Link.

	Runs the backfill first, then refuses (returns the leftovers) if any order
	still has a numbered old value and no Link — nothing is lost silently.
	Deleting a Custom Field does not drop its column: the old values stay in
	`tabSales Order` until someone trims the table.
	"""
	name = f"Sales Order-{OLD_SELECT_FIELD}"
	if not frappe.db.exists("Custom Field", name):
		return []

	backfill_sales_orders()
	leftovers = frappe.db.sql_list(
		f"""select name from `tabSales Order`
		     where `{OLD_SELECT_FIELD}` regexp '^ *[0-9]' and ifnull(`{LINK_FIELD}`, '') = ''"""
	)
	if leftovers:
		return leftovers

	frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
	frappe.clear_cache(doctype="Sales Order")
	return []


def backfill_sales_orders():
	"""Point existing orders at the master, from the number on their old Select.

	"3 - Miller Custom Plastics" -> location 3; "10 - Home Delivery" -> location 0.
	Only orders whose Link is still empty are touched, and only that one column —
	``modified`` is left alone. Returns {old value: orders updated}.
	"""
	if not frappe.db.has_column("Sales Order", OLD_SELECT_FIELD):
		return {}

	by_number = {
		cint(row.location_number): row.name
		for row in frappe.get_all(MASTER, fields=["name", "location_number"])
	}
	done = {}
	for (old,) in frappe.db.sql(
		f"""select distinct `{OLD_SELECT_FIELD}` from `tabSales Order`
		     where ifnull(`{OLD_SELECT_FIELD}`, '') != '' and ifnull(`{LINK_FIELD}`, '') = ''"""
	):
		match = re.match(r"\s*(\d+)", old)
		if not match:
			continue
		number = cint(match.group(1))
		if number == OLD_HOME_DELIVERY_NUMBER:
			number = HOME_DELIVERY_NUMBER
		location = by_number.get(number)
		if not location:
			continue
		frappe.db.sql(
			f"""update `tabSales Order` set `{LINK_FIELD}` = %s
			     where `{OLD_SELECT_FIELD}` = %s and ifnull(`{LINK_FIELD}`, '') = ''""",
			(location, old),
		)
		done[old] = frappe.db.sql("select row_count()")[0][0]
	return done
