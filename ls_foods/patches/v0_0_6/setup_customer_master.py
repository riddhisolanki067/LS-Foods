"""v0_0_6 — Customer master: the Customer ID and the Address / Phone / Email grids.

Idempotent; re-runnable. What it does:

  1. Creates the custom fields (the ID on Customer, the three grids on the
     Contact & Address tab, and the extra attributes on Address / Contact Phone
     / Contact Email), and backfills the Current tick so existing records do not
     read as retired.
  2. Fills the grids from the Addresses and Contact each customer already has,
     so nothing looks empty on the first open. Same code path as the "Load from
     Address & Contact" button, so the two cannot diverge.

It deliberately does NOT number the customers that are already on the site —
see ``customer_master.number_existing_customers`` for why that is a decision and
not a migration step. New customers are numbered from the moment this runs.
"""

import frappe

from ls_foods import customer_master
from ls_foods.setup import customer_setup


def execute():
	customer_setup.install()

	_load_existing_contact_details()

	frappe.clear_cache()


def _load_existing_contact_details():
	for name in frappe.get_all("Customer", pluck="name", order_by="creation asc"):
		try:
			customer_master.load_from_address_and_contact(name)
			frappe.db.commit()
		except Exception:
			# One bad master must not stop the migrate. Anything skipped here can
			# be picked up later with the button on the form.
			frappe.db.rollback()
			frappe.log_error(
				title="ls_foods: could not load contact details",
				message=f"Customer {name}\n\n{frappe.get_traceback()}",
			)
