// =========================================================================
// LS Foods — Expense Reimbursement Request list view.
// Wired in hooks.py: doctype_list_js = {"Expense Claim": ".../expense_claim_list.js"}
//
// The payroll clerk works from this list, so it is coloured by the client's own
// three-word vocabulary (Requested -> Approved -> Paid) rather than by the
// standard Draft/Unpaid/Paid, which says the same thing in accounting terms but
// not in hers.
//
// NOTE: HRMS ships its own expense_claim_list.js that sets `add_fields`. This
// file loads after it, so we EXTEND the existing settings object instead of
// replacing it — otherwise `company` would stop being fetched and the standard
// list would lose it.
//
// NOTE 2: while the Draft -> Approved/Rejected -> Paid Workflow is active it wins
// the indicator — frappe.get_indicator checks the workflow state field before it
// ever calls get_indicator here — and colours the row from Workflow State.style
// instead (blue Approved, green Paid, red Rejected, grey Draft/Cancelled: the same
// scheme as below, on purpose). get_indicator is kept as the fallback for a site
// where the workflow is switched off, which is the one thing that would otherwise
// silently drop the colouring back to the standard Draft/Unpaid/Paid.
// =========================================================================

frappe.listview_settings["Expense Claim"] = Object.assign(
	{},
	frappe.listview_settings["Expense Claim"] || {},
	{
		add_fields: [
			...((frappe.listview_settings["Expense Claim"] || {}).add_fields || []),
			"custom_reimbursement_status",
			"custom_paid_date",
		],

		get_indicator(doc) {
			const map = {
				Requested: "orange",
				Approved: "blue",
				Paid: "green",
				Rejected: "red",
				Cancelled: "grey",
				Draft: "grey",
			};
			const status = doc.custom_reimbursement_status;
			if (!status) return [__(doc.status), "grey", "status,=," + doc.status];

			return [
				__(status),
				map[status] || "grey",
				"custom_reimbursement_status,=," + status,
			];
		},
	}
);
