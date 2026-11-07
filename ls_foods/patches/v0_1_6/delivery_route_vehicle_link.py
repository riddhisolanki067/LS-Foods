"""v0_1_6 — Delivery Route's Vehicle becomes a drop list of the Vehicle list.

The field keeps its name and its column (Data -> Link), so every route keeps
the text it had; there is nothing to copy and no old field left over. This makes
sure each of those texts is a Vehicle, so the existing routes still save:
a missing one is created with that text as its License Plate (the Vehicle's
name), make and model the same text. The Vehicle's other details (odometer,
fuel, unit) are left for the client to fill in.
"""

import frappe


def execute():
	used = frappe.get_all(
		"Delivery Route", filters={"vehicle": ["is", "set"]}, pluck="vehicle", distinct=True
	)
	for name in {v.strip() for v in used if v and v.strip()}:
		if frappe.db.exists("Vehicle", name):
			continue
		vehicle = frappe.new_doc("Vehicle")
		vehicle.update({"license_plate": name, "make": name, "model": name})
		vehicle.flags.ignore_mandatory = True
		vehicle.insert(ignore_permissions=True)
