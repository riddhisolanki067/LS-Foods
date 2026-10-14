// Copyright (c) 2026, Riddhi and contributors
// For license information, please see license.txt

frappe.query_reports["Supplier Wholesale Order"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "supplier",
			label: __("Supplier"),
			fieldtype: "Link",
			options: "Supplier",
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
			// pallet order in the trailer, not the flyer numbers: first click = Label #1
			fieldname: "label_order",
			label: __("Label Order"),
			fieldtype: "MultiSelectList",
			options: "Pick-Up Location",
			description: __("Click the locations in pallet order: first click = Label #1"),
			get_data: (txt) => frappe.db.get_link_options("Pick-Up Location", txt, { disabled: 0 }),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && (data.is_total_row || data.is_label_row || data.is_vendor_row)) {
			value = `<b>${value}</b>`;
		}
		return value;
	},
};
