"""v0_1_1 — Supplier Part Number column on the Purchase Invoice lines. See supplier_part_setup."""

from ls_foods.setup import supplier_part_setup


def execute():
	supplier_part_setup.run()
