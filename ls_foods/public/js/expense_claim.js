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
//   4. Approver: an open list of users, because LS Foods has no fixed approver.
//      Mirrored into the standard (hidden) Expense Approver field.
// =========================================================================

frappe.ui.form.on("Expense Claim", {
	setup(frm) {
		// Any enabled user can be named as the approver — the whole reason this field
		// exists is that the standard Expense Approver link query returns only the
		// approver pre-set on the Employee or the Department, and throws when neither
		// is set. Narrow this to a role here if the client ever wants it fixed.
		frm.set_query("custom_approver", () => ({
			filters: { enabled: 1, user_type: "System User" },
		}));

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
		ls_hide_submit_without_workflow_action(frm);
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

	// Mirror the approver into the standard field on the form too, not only on the
	// server. HR Settings > "Expense Approver Mandatory" makes the standard field
	// reqd, and the client-side mandatory check runs BEFORE the server ever sees
	// the document — so a hidden empty field would block the save even though the
	// server was about to fill it.
	custom_approver(frm) {
		if (frm.doc.custom_approver !== frm.doc.expense_approver) {
			frm.set_value("expense_approver", frm.doc.custom_approver);
		}
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
	//
	// Mileage is excluded: there the employee enters Miles and nothing else, and
	// the rate is the company's, held on the Expense Claim Type. Accepting a typed
	// amount would let someone reimburse themselves at a rate of their choosing.
	amount(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.custom_rate)) return;

		if (row.custom_is_mileage_type) {
			frappe.model.set_value(cdt, cdn, "amount", 0);
			frappe.model.set_value(cdt, cdn, "sanctioned_amount", 0);
			frappe.msgprint({
				title: __("Enter Miles, Not Amount"),
				indicator: "orange",
				message: __(
					"Mileage is paid at the rate on the <b>{0}</b> expense claim type — enter " +
						"the miles driven and the amount is worked out for you.<br><br>" +
						"The amount is zero because no <b>Default Rate per Mile</b> has been set " +
						"on that type yet. Ask the bookkeeper to set it; it only has to be done once.",
					[row.expense_type]
				),
			});
			return;
		}

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

// With the Draft -> Approved/Rejected -> Paid workflow active, approving IS the
// submit. Frappe hides the Submit button only for users who have a workflow action
// available, so a colleague without the Expense Approver role is still offered a
// Submit — and ERPNext then refuses it with "Approval Status must be 'Approved' or
// 'Rejected'", an error that explains nothing. Leave them Save, which is all they
// are meant to do: raise the request and let the approver act on it.
//
// (Same shape as HRMS's own show_save_button, used there for the no-self-approval
// case, so the form behaves one way throughout.)
function ls_hide_submit_without_workflow_action(frm) {
	if (frm.doc.docstatus !== 0 || frm.is_new()) return;
	if (!frappe.model.has_workflow(frm.doctype)) return;
	// get_transitions throws server-side on a document with no state, which only
	// happens if the workflow was added while this one was open.
	if (!frm.doc.workflow_state) return;

	frappe.workflow.get_transitions(frm.doc).then((transitions) => {
		const mine = (transitions || []).filter((t) => frappe.user_roles.includes(t.allowed));
		if (mine.length) return; // Frappe has already replaced the button with Actions

		frm.page.set_primary_action(__("Save"), () => frm.save());
	});
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
