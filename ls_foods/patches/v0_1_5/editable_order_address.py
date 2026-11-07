"""v0_1_5 — billing / shipping address editable on Sales Order and Sales Invoice. See order_address_setup."""

from ls_foods.setup import order_address_setup


def execute():
	order_address_setup.run()
