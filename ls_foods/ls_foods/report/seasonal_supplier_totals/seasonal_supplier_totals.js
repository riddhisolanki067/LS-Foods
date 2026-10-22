// Copyright (c) 2026, Riddhi and contributors
// For license information, please see license.txt

frappe.query_reports["Seasonal Supplier Totals"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "from_date",
			label: __("Order Date From"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("Order Date To"),
			fieldtype: "Date",
		},
		{
			// empty = every supplier
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
		},
		{
			// empty = every location, Home Delivery included
			fieldname: "pick_up_location",
			label: __("Pick-Up Location"),
			fieldtype: "MultiSelectList",
			options: "Pick-Up Location",
			get_data: (txt) => frappe.db.get_link_options("Pick-Up Location", txt, { disabled: 0 }),
		},
		{
			fieldname: "hide_zero_rows",
			label: __("Hide Locations With No Orders"),
			fieldtype: "Check",
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.is_total_row) {
			value = `<b>${value}</b>`;
		}
		return value;
	},
};
