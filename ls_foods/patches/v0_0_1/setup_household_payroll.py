"""Run the idempotent, company-wide payroll setup on migrate.

Ensures the custom fields, salary components, the Household salary structure, and
disabling of the legacy server script all land when the app is migrated onto a
site (in addition to after_install). Does NOT seed any specific employee.
"""

from ls_foods.setup.payroll_setup import run


def execute():
	run()
