"""LS Foods — HR Settings configuration.

Retirement age
--------------
``Employee.date_of_retirement`` is auto-filled by HRMS whenever Date of Birth is
entered on the Employee form. The calculation lives in
``hrms.overrides.employee_master.get_retirement_date`` and is simply::

    date_of_retirement = date_of_birth + HR Settings.retirement_age (years)

HR Settings ships with the field BLANK, and the code falls back to 60. LS Foods
wants 65, so we set the standard setting rather than override the calculation.

Why configuration instead of code: the retirement age is a policy value, not
business logic. Setting it here means the standard HRMS field, the Employee form
JS, and any future HRMS feature that reads ``retirement_age`` all stay
consistent. An override would have to be maintained across upgrades.

NOTE: HRMS only recomputes the retirement date when Date of Birth is *changed*
on the form. Existing employees keep whatever was computed under the old age, so
``backfill_retirement_dates()`` re-derives them once.
"""

import frappe
from frappe.utils import add_years, cint, getdate

RETIREMENT_AGE = 65


def run():
	"""Idempotent. Called from after_install and the v0_0_2 patch."""
	set_retirement_age()
	backfill_retirement_dates()


def set_retirement_age(age=RETIREMENT_AGE):
	settings = frappe.get_single("HR Settings")
	if cint(settings.retirement_age) == cint(age):
		return
	settings.retirement_age = age
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()


def backfill_retirement_dates(age=None):
	"""Recompute date_of_retirement = date_of_birth + retirement_age for every
	employee whose stored date does not already match.

	Only touches employees that HAVE a date of birth. Uses db_set so no Employee
	validation/notification side effects fire for what is a derived field.
	"""
	age = cint(age or frappe.db.get_single_value("HR Settings", "retirement_age") or RETIREMENT_AGE)
	updated = []

	for emp in frappe.get_all(
		"Employee",
		filters={"date_of_birth": ["is", "set"]},
		fields=["name", "employee_name", "date_of_birth", "date_of_retirement"],
	):
		expected = add_years(getdate(emp.date_of_birth), age)
		if emp.date_of_retirement and getdate(emp.date_of_retirement) == expected:
			continue
		frappe.db.set_value("Employee", emp.name, "date_of_retirement", expected, update_modified=False)
		updated.append((emp.name, emp.employee_name, str(emp.date_of_retirement), str(expected)))

	if updated:
		frappe.db.commit()
	return updated
