"""Pick-Up Location — where a customer collects an order (or 0, Home Delivery).

The flyer map numbers the pick-up points and the customer writes that number on
the order form, so the number is the thing staff key. The record is therefore
named "<number> - <name>" ("3 - Miller Custom Plastics"): typing 3 in the Sales
Order's Pick-Up Location box finds it, and the order still reads sensibly in a
list, a report or a print without fetching a second field.

Named in code, not by an autoname expression, so that number 0 (Home Delivery)
is certain to print as "0" rather than be dropped as an empty value.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr


class PickUpLocation(Document):
	def autoname(self):
		self.name = f"{cint(self.location_number)} - {cstr(self.location_name).strip()}"

	def validate(self):
		self.location_name = cstr(self.location_name).strip()
		if cint(self.location_number) < 0:
			frappe.throw(_("Location No. cannot be negative."))

		clash = frappe.db.get_value(
			"Pick-Up Location",
			{"location_number": cint(self.location_number), "name": ("!=", self.name)},
			"name",
		)
		if clash:
			frappe.throw(
				_("Location No. {0} is already used by {1}.").format(
					frappe.bold(cint(self.location_number)), frappe.bold(clash)
				),
				title=_("Duplicate Location No."),
			)
