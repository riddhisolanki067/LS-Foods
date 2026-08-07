// =========================================================================
// LS Foods — Employee Reimbursement additions to the standard Expense Claim.
// Wired in hooks.py: doctype_js = {"Expense Claim": "public/js/expense_claim.js"}
//
// All of it is cosmetic/live-feedback only — the authoritative calculation is
// server-side in ls_foods/reimbursement.py, so an import or API call gets the
// same numbers.
//   1. Expense rows: Amount = Qty x Rate, as you type. On a mileage claim type
//      the two columns are relabelled Miles / Rate per Mile and the rate is
//      pre-filled from the type — same arithmetic, familiar words.
//   2. Receipt reminder for the types that require one.
//   3. Purchased Items rows: Amount = Qty x Rate, running total, warehouse and
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

	refresh(frm) {
		ls_show_receipt_warning(frm);
	},

	validate(frm) {
		ls_recalculate_stock_total(frm);
	},

	// Child-table row removal fires on the PARENT form handler.
	custom_stock_items_remove(frm) {
		ls_recalculate_stock_total(frm);
	},

	expenses_add(frm) {
		ls_show_receipt_warning(frm);
	},
});

// ------------------------------------------------------------- expense rows
frappe.ui.form.on("Expense Claim Detail", {
	expense_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.expense_type) return;

		frappe.db.get_value(
			"Expense Claim Type",
			row.expense_type,
			["custom_is_mileage", "custom_default_rate_per_mile", "custom_receipt_required"],
			(r) => {
				if (!r) return;
				frappe.model.set_value(cdt, cdn, "custom_is_mileage_type", r.custom_is_mileage ? 1 : 0);
				frappe.model.set_value(
					cdt,
					cdn,
					"custom_receipt_required",
					r.custom_receipt_required ? 1 : 0
				);
				if (!flt(row.custom_qty)) frappe.model.set_value(cdt, cdn, "custom_qty", 1);
				if (r.custom_is_mileage && !flt(row.custom_rate)) {
					frappe.model.set_value(cdt, cdn, "custom_rate", r.custom_default_rate_per_mile);
				}
				ls_relabel_qty_rate(frm, row);
				ls_show_receipt_warning(frm);
			}
		);
	},

	custom_qty: (frm, cdt, cdn) => ls_calculate_expense_row(frm, cdt, cdn),
	custom_rate: (frm, cdt, cdn) => ls_calculate_expense_row(frm, cdt, cdn),

	// Amount typed directly (no rate) — back-fill the rate so Qty x Rate still
	// reconciles, mirroring what the server does on save.
	amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.custom_rate)) return;
		const qty = flt(row.custom_qty) || 1;
		frappe.model.set_value(cdt, cdn, "custom_qty", qty);
		frappe.model.set_value(cdt, cdn, "custom_rate", flt(row.amount) / qty);
		frappe.model.set_value(cdt, cdn, "sanctioned_amount", flt(row.amount));
	},

	custom_receipt(frm) {
		ls_show_receipt_warning(frm);
	},

	form_render(frm, cdt, cdn) {
		ls_relabel_qty_rate(frm, locals[cdt][cdn]);
	},
});

function ls_calculate_expense_row(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!flt(row.custom_rate)) return; // rate drives it; blank rate = manual amount

	const amount = flt(row.custom_qty) * flt(row.custom_rate);
	frappe.model.set_value(cdt, cdn, "amount", amount);
	frappe.model.set_value(cdt, cdn, "sanctioned_amount", amount);
}

// Mileage is the same Qty x Rate as everything else — only the words change, so
// an employee logging a trip sees "Miles", not "Qty".
function ls_relabel_qty_rate(frm, row) {
	if (!row) return;
	const grid = frm.fields_dict.expenses && frm.fields_dict.expenses.grid;
	if (!grid) return;

	const qty_df = frappe.meta.get_docfield("Expense Claim Detail", "custom_qty", row.name);
	const rate_df = frappe.meta.get_docfield("Expense Claim Detail", "custom_rate", row.name);
	if (!qty_df || !rate_df) return;

	qty_df.label = row.custom_is_mileage_type ? __("Miles") : __("Qty");
	rate_df.label = row.custom_is_mileage_type ? __("Rate per Mile") : __("Rate");
}

// A receipt is blocked at SUBMIT server-side; this is the early warning so it is
// not a surprise at the last step.
function ls_show_receipt_warning(frm) {
	frm.dashboard.clear_headline();
	if (frm.doc.docstatus !== 0) return;

	const missing = (frm.doc.expenses || []).filter(
		(r) => r.custom_receipt_required && !r.custom_receipt && !r.custom_auto_generated
	).length;
	const missing_stock = (frm.doc.custom_stock_items || []).filter((r) => !r.receipt).length;

	if (missing + missing_stock > 0) {
		frm.dashboard.set_headline(
			__("{0} row(s) still need a receipt attached — required before submitting.", [
				missing + missing_stock,
			]),
			"orange"
		);
	}
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

	receipt(frm) {
		ls_show_receipt_warning(frm);
	},
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
