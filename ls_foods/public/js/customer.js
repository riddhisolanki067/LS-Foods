// LS Foods — Customer master.
//
// The server does the work (ls_foods/customer_master.py). This adds the two
// things that only make sense in the browser:
//
//   * a button to pull Addresses and the Contact into the grids, for a customer
//     whose details were entered on those forms rather than here, and
//   * a plain-language hint on the Customer ID, which fills itself on save, and
//   * the address grid's ticks behaving as they will on save: one Primary row
//     (the billing address), and Address Type following Primary / Delivery.

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

// Primary and Address Type follow the ticks — mirrors the server's rule
// (customer_master._primary_row / _address_type):
//   Mailing + Current           -> the first such row is Primary, Billing
//   Delivery + Current, no Mailing -> Shipping
frappe.ui.form.on("Customer Address Entry", {
	custom_mailing: (frm) => ls_foods_apply_address_rules(frm),
	custom_delivery: (frm) => ls_foods_apply_address_rules(frm),
	custom_current: (frm) => ls_foods_apply_address_rules(frm),
	custom_addresses_add: (frm) => ls_foods_apply_address_rules(frm),
	custom_addresses_remove: (frm) => ls_foods_apply_address_rules(frm),
});

function ls_foods_apply_address_rules(frm) {
	const rows = (frm.doc.custom_addresses || []).slice().sort((a, b) => a.idx - b.idx);
	const primary = rows.find((row) => row.custom_mailing && row.custom_current);
	rows.forEach((row) => {
		const type = row.custom_delivery && !row.custom_mailing ? "Shipping" : "Billing";
		if (row.address_type !== type) frappe.model.set_value(row.doctype, row.name, "address_type", type);
		const flag = row === primary ? 1 : 0;
		if (cint(row.custom_primary) !== flag) frappe.model.set_value(row.doctype, row.name, "custom_primary", flag);
	});
}
