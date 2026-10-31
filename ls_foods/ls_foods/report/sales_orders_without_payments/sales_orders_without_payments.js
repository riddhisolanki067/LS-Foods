frappe.query_reports["Sales Orders Without Payments"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "customer",
			label: __("Customer"),
			fieldtype: "Link",
			options: "Customer",
		},
		{
			fieldname: "amended_only",
			label: __("Amended Orders Only"),
			fieldtype: "Check",
		},
		{
			fieldname: "with_payments_only",
			label: __("Customer Has Unallocated Payment"),
			fieldtype: "Check",
		},
	],
};
