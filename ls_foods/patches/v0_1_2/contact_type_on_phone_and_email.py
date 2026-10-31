"""v0_1_2 — Type (Landline / Mobile Phone / Fax) on Contact's phone and email rows.

The Customer's grids carry it in their own DocTypes. Existing rows stay blank.
"""

from ls_foods.setup import customer_setup


def execute():
	customer_setup.run()
