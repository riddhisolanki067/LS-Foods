// Copyright (c) 2026, Riddhi and contributors
// For license information, please see license.txt

frappe.query_reports["Expense Reimbursement Register"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: ["", "Requested", "Approved", "Paid", "Rejected"].join("\n"),
		},
		{
			fieldname: "expense_type",
			label: __("Expense Claim Type"),
			fieldtype: "Link",
			options: "Expense Claim Type",
		},
		{
			// "Approved in July" and "paid in July" are different questions —
			// this picks which date the range below applies to.
			fieldname: "date_type",
			label: __("Date Range Applies To"),
			fieldtype: "Select",
			options: ["Request Date", "Expense Date", "Approval Date", "Paid Date"].join("\n"),
			default: "Request Date",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -3),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
	],

	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (column.fieldname === "status" && data && data.status) {
			const colour = {
				Requested: "orange",
				Approved: "blue",
				Paid: "green",
				Rejected: "red",
			}[data.status];
			if (colour) value = `<span class="indicator-pill ${colour}">${data.status}</span>`;
		}

		return value;
	},
};
