// Copyright (c) 2026, Riddhi and contributors
// For license information, please see license.txt

frappe.query_reports["Seasonal Supplier Quantities"] = {
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
			// one View per tab of the client's workbook
			fieldname: "view",
			label: __("View"),
			fieldtype: "Select",
			options: ["All Locations", "Pick-Up Locations", "Home Delivery", "Totals"].join("\n"),
			default: "All Locations",
			reqd: 1,
			on_change: (report) => {
				// a location left over from the Pick-Up view would be hidden but still set
				if (
					report.get_filter_value("view") !== "Pick-Up Locations" &&
					report.get_filter_value("pick_up_location")
				) {
					report.set_filter_value("pick_up_location", ""); // refreshes on its own
				} else {
					report.refresh();
				}
			},
		},
		{
			// empty = every pick-up location together; one picked = that location's tab
			fieldname: "pick_up_location",
			label: __("Pick-Up Location"),
			fieldtype: "Link",
			options: "Pick-Up Location",
			depends_on: "eval:doc.view == 'Pick-Up Locations'",
			get_query: () => ({ filters: { is_home_delivery: 0, disabled: 0 } }),
		},
		{
			fieldname: "show_order_lines",
			label: __("Show Each Order Line"),
			fieldtype: "Check",
			depends_on: "eval:doc.view != 'Totals'",
		},
	],

	onload(report) {
		report.page.add_inner_button(__("Download Workbook"), () => {
			open_url_post(
				"/api/method/ls_foods.ls_foods.report.seasonal_supplier_quantities.seasonal_supplier_quantities.download_workbook",
				{ filters: JSON.stringify(report.get_filter_values()) }
			);
		});
	},

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && data.is_total_row) {
			value = `<b>${value}</b>`;
		}
		return value;
	},
};
