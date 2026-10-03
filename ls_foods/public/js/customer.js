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

// Primary is the billing address — ticking it on one row unticks the others.
// Address Type mirrors the server's rule (customer_master._address_type):
// Shipping when Delivery is ticked and Primary is not, otherwise Billing.
frappe.ui.form.on("Customer Address Entry", {
	custom_primary(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.custom_primary) {
			(frm.doc.custom_addresses || []).forEach((other) => {
				if (other.name !== row.name && other.custom_primary) {
					frappe.model.set_value(other.doctype, other.name, "custom_primary", 0);
				}
			});
		}
		ls_foods_set_address_type(cdt, cdn);
	},
	custom_delivery(frm, cdt, cdn) {
		ls_foods_set_address_type(cdt, cdn);
	},
	custom_addresses_add(frm, cdt, cdn) {
		ls_foods_set_address_type(cdt, cdn);
	},
});

function ls_foods_set_address_type(cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row) return;
	const type = row.custom_delivery && !row.custom_primary ? "Shipping" : "Billing";
	if (row.address_type !== type) frappe.model.set_value(cdt, cdn, "address_type", type);
}
