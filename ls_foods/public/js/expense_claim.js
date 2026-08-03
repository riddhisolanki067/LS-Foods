// =========================================================================
// LS Foods — Employee Reimbursement additions to the standard Expense Claim.
// Wired in hooks.py: doctype_js = {"Expense Claim": "public/js/expense_claim.js"}
//
// Two jobs, both cosmetic/live-feedback only — the authoritative calculation is
// server-side in ls_foods/reimbursement.py, so an import or API call gets the
// same numbers.
//   1. Mileage rows: Amount = Miles x Rate per Mile, as you type.
//   2. Purchased Items rows: Amount = Qty x Rate, running total, warehouse and
//      account defaults pulled from the Item.
// =========================================================================

frappe.ui.form.on("Expense Claim", {
	setup(frm) {
		// Only real (non-group) accounts of this company can be designated.
		frm.set_query("expense_account", "custom_stock_items", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("warehouse", "custom_stock_items", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("cost_center", "custom_stock_items", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
	},

	validate(frm) {
		ls_recalculate_stock_total(frm);
	},

	// Child-table row removal fires on the PARENT form handler.
	custom_stock_items_remove(frm) {
		ls_recalculate_stock_total(frm);
	},
});

// ------------------------------------------------------------------ mileage
frappe.ui.form.on("Expense Claim Detail", {
	expense_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.expense_type) return;

		frappe.db.get_value(
			"Expense Claim Type",
			row.expense_type,
			["custom_is_mileage", "custom_default_rate_per_mile"],
			(r) => {
				if (!r) return;
				frappe.model.set_value(cdt, cdn, "custom_is_mileage_type", r.custom_is_mileage ? 1 : 0);
				if (r.custom_is_mileage && !row.custom_rate_per_mile) {
					frappe.model.set_value(
						cdt,
						cdn,
						"custom_rate_per_mile",
						r.custom_default_rate_per_mile
					);
				}
			}
		);
	},

	custom_miles: (frm, cdt, cdn) => ls_calculate_mileage(frm, cdt, cdn),
	custom_rate_per_mile: (frm, cdt, cdn) => ls_calculate_mileage(frm, cdt, cdn),
});

function ls_calculate_mileage(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row.custom_is_mileage_type) return;

	const amount = flt(row.custom_miles) * flt(row.custom_rate_per_mile);
	frappe.model.set_value(cdt, cdn, "amount", amount);
	frappe.model.set_value(cdt, cdn, "sanctioned_amount", amount);
}

// ---------------------------------------------------------- purchased items
frappe.ui.form.on("Reimbursement Stock Item", {
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.item_code) return;

		frappe.call({
			method: "ls_foods.reimbursement.get_reimbursement_item_details",
			args: { item_code: row.item_code, company: frm.doc.company },
			callback(r) {
				if (!r.message) return;
				const d = r.message;
				frappe.model.set_value(cdt, cdn, "is_stock_item", d.is_stock_item);
				frappe.model.set_value(cdt, cdn, "uom", d.stock_uom);
				frappe.model.set_value(cdt, cdn, "expense_account", d.expense_account);
				if (d.is_stock_item && !row.warehouse) {
					frappe.model.set_value(cdt, cdn, "warehouse", d.warehouse);
				}
			},
		});
	},

	qty: (frm, cdt, cdn) => ls_calculate_stock_row(frm, cdt, cdn),
	rate: (frm, cdt, cdn) => ls_calculate_stock_row(frm, cdt, cdn),
});

function ls_calculate_stock_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	frappe.model.set_value(cdt, cdn, "amount", flt(row.qty) * flt(row.rate));
	ls_recalculate_stock_total(frm);
}

function ls_recalculate_stock_total(frm) {
	let total = 0;
	(frm.doc.custom_stock_items || []).forEach((row) => {
		total += flt(row.qty) * flt(row.rate);
	});
	frm.set_value("custom_total_stock_amount", total);
}
