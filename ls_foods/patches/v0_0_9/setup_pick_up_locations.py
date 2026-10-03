"""v0_0_9 — Pick-Up Location master, seeded from the 2026 Fall flyer, and its link on the Sales Order.

Idempotent; re-runnable. See ls_foods/setup/pickup_location_setup.py.

  * adds the Link field ``custom_pick_up_location`` to Sales Order;
  * creates locations 0 (Home Delivery) to 9 where they do not exist yet;
  * hides the Select the client built for this (kept, with its data);
  * points every existing order at the matching location (old option 10,
    Home Delivery, becomes location 0).
"""

import frappe

from ls_foods.setup import pickup_location_setup


def execute():
	frappe.reload_doc("ls_foods", "doctype", "pick_up_location")
	pickup_location_setup.run()
