// =========================================================================
// LS Foods — Salary Slip form additions.
// Wired in hooks.py: doctype_js = {"Salary Slip": "public/js/payment_entry.js"}
//
//   1. Hours Worked guard — pops a warning on save if the Payment Days tab's
//      Hours Worked is blank. (Submitting is blocked server-side; see
//      ls_foods/setup/payment_entry.py::validate_hours_worked.)
//   2. Make Payment Entry — now asks for the Payment Date, which becomes the
//      Journal Entry's posting date, and can leave the JE as a draft so the
//      date stays editable.
// =========================================================================

frappe.ui.form.on("Salary Slip", {
	refresh(frm) {
		ls_show_hours_warning(frm);

		if (frm.doc.docstatus !== 1) return;

		if (frm.doc.custom_payment_journal_entry) {
			ls_render_paid_state(frm);
		} else {
			frm.add_custom_button(
				__("Make Payment Entry"),
				() => ls_show_payment_dialog(frm),
				__("Payment")
			);
		}
	},

	custom_hours_worked(frm) {
		ls_show_hours_warning(frm);
	},

	validate(frm) {
		// Draft save: warn but do not block, so a half-entered slip can still be
		// parked. Submit is blocked server-side.
		if (frm.doc.docstatus === 0 && !flt(frm.doc.custom_hours_worked)) {
			frappe.msgprint({
				title: __("Hours Worked Missing"),
				indicator: "orange",
				message: __(
					"<b>Hours Worked has not been entered.</b><br><br>" +
						"Enter the hours for this pay period on the <b>Payment Days</b> tab. " +
						"Pay is calculated as Hours Worked &times; Rate per Hour, so this slip " +
						"will show zero gross pay until you do — and it cannot be submitted."
				),
			});
		}
	},
});

// ------------------------------------------------------------ hours warning
function ls_show_hours_warning(frm) {
	frm.dashboard.clear_headline();
	if (frm.doc.docstatus === 2) return;

	if (!flt(frm.doc.custom_hours_worked)) {
		frm.dashboard.set_headline(
			__("Hours Worked is empty — enter it on the Payment Days tab."),
			"orange"
		);
	}
}

// ------------------------------------------------------------ paid state UI
function ls_render_paid_state(frm) {
	const je = frm.doc.custom_payment_journal_entry;

	frappe.db.get_value("Journal Entry", je, ["docstatus", "posting_date"]).then((r) => {
		const data = r.message || {};

		if (data.docstatus === 2) {
			// Payment was cancelled — allow a fresh one.
			frm.add_custom_button(
				__("Make Payment Entry"),
				() => ls_show_payment_dialog(frm),
				__("Payment")
			);
			return;
		}

		const label = data.docstatus === 1 ? __("Paid") : __("Payment Entry drafted");
		frm.dashboard.add_indicator(
			`${label}: ${frappe.format(data.posting_date, { fieldtype: "Date" })}`,
			data.docstatus === 1 ? "green" : "orange"
		);

		frm.add_custom_button(
			__("View Payment Entry"),
			() => frappe.set_route("Form", "Journal Entry", je),
			__("Payment")
		);

		// Editing the date is only offered while the JE is still a draft —
		// a submitted JE's posting date is locked (cancel & amend instead).
		if (data.docstatus === 0) {
			frm.add_custom_button(
				__("Edit Payment Date"),
				() => ls_show_edit_date_dialog(frm, data.posting_date),
				__("Payment")
			);
		}
	});
}

// --------------------------------------------------------- payment dialogs
function ls_show_payment_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Make Payment Entry"),
		fields: [
			{
				label: __("Payment Account"),
				fieldname: "payment_account",
				fieldtype: "Link",
				options: "Account",
				reqd: 1,
				description: __(
					"Account from which the salary amount will be paid (e.g. Bank or Cash account)"
				),
				get_query() {
					return { filters: { company: frm.doc.company, is_group: 0 } };
				},
			},
			{
				label: __("Payment Date"),
				fieldname: "payment_date",
				fieldtype: "Date",
				reqd: 1,
				default: frappe.datetime.get_today(),
				description: __(
					"The date the employee was actually paid. Becomes the Journal Entry's posting date."
				),
			},
			{ fieldtype: "Column Break" },
			{
				label: __("Net Pay"),
				fieldname: "net_pay",
				fieldtype: "Currency",
				default: frm.doc.net_pay,
				read_only: 1,
				options: "currency",
			},
			{
				label: __("Submit Journal Entry"),
				fieldname: "submit_je",
				fieldtype: "Check",
				default: 1,
				description: __(
					"Untick to leave the Journal Entry as a draft — the payment date stays editable " +
						"until you submit it. Once submitted the date is locked and must be changed " +
						"by cancelling and amending."
				),
			},
		],
		primary_action_label: __("Proceed"),
		primary_action(values) {
			d.disable_primary_action();
			frappe.call({
				method: "ls_foods.setup.payment_entry.create_salary_payment_entry",
				args: {
					salary_slip: frm.doc.name,
					payment_account: values.payment_account,
					payment_date: values.payment_date,
					submit_je: values.submit_je ? 1 : 0,
				},
				freeze: true,
				freeze_message: __("Creating Journal Entry..."),
				callback(r) {
					d.enable_primary_action();
					if (!r.message) return;
					d.hide();
					frappe.show_alert({
						message: __("Journal Entry {0} created", [r.message]),
						indicator: "green",
					});
					frappe.set_route("Form", "Journal Entry", r.message);
				},
				error() {
					d.enable_primary_action();
				},
			});
		},
	});
	d.show();
}

function ls_show_edit_date_dialog(frm, current_date) {
	const d = new frappe.ui.Dialog({
		title: __("Edit Payment Date"),
		fields: [
			{
				label: __("Payment Date"),
				fieldname: "payment_date",
				fieldtype: "Date",
				reqd: 1,
				default: current_date,
			},
		],
		primary_action_label: __("Update"),
		primary_action(values) {
			frappe.call({
				method: "ls_foods.setup.payment_entry.update_payment_date",
				args: { salary_slip: frm.doc.name, payment_date: values.payment_date },
				freeze: true,
				callback(r) {
					if (!r.message) return;
					d.hide();
					frappe.show_alert({
						message: __("Payment date updated on {0}", [r.message]),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
		},
	});
	d.show();
}
