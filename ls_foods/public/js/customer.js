// LS Foods — Customer master.
//
// The server does the work (ls_foods/customer_master.py). This adds the two
// things that only make sense in the browser:
//
//   * a button to pull Addresses and the Contact into the grids, for a customer
//     whose details were entered on those forms rather than here, and
//   * a plain-language hint on the Customer ID, which fills itself on save.

frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Load from Address & Contact"),
			() => {
				frappe.call({
					method: "ls_foods.customer_master.load_from_address_and_contact",
					args: { customer: frm.doc.name },
					freeze: true,
					freeze_message: __("Loading addresses and contact details…"),
					callback(r) {
						frm.reload_doc();
						frappe.show_alert({
							message: r.message
								? __("Addresses and contact details loaded.")
								: __("Already up to date."),
							indicator: "green",
						});
					},
				});
			},
			__("Contact & Address")
		);
	},

	onload(frm) {
		frm.set_df_property(
			"custom_customer_id",
			"description",
			frm.is_new()
				? __("Leave blank to get the next number automatically.")
				: __("Changing this must keep it unique across customers.")
		);
	},
});
