"""v0_1_0 — remove the client's old Pick-Up Location Select from Sales Order.

The Link ``custom_pick_up_location`` (v0_0_9) replaced it. Any order whose Link
is still empty is filled from the Select first; if one still can't be mapped the
Select is kept and the orders are printed. See pickup_location_setup.remove_old_select.
"""

from ls_foods.setup import pickup_location_setup


def execute():
	leftovers = pickup_location_setup.remove_old_select()
	if leftovers:
		print(f"Old pick-up Select kept — no matching location for: {', '.join(leftovers)}")
