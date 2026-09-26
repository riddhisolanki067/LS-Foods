// LS Foods — Sales Order.
//
// Items with a Per Pound price: Rate = $/lb x Case Weight (lb) (per_lb_pricing.js).
// A beef/hog share is ordered at its Standard Selling price, which IS the fixed
// deposit ($600 quarter / $1,200 half / $2,400 whole beef). The hanging-weight
// charge and processing are billed on the final invoice (share_billing.py).

frappe.ui.form.on("Sales Order Item", {
	item_code(frm, cdt, cdn) {
		ls_foods_per_lb.on_item(frm, cdt, cdn, "weight_per_unit");
	},
	weight_per_unit(frm, cdt, cdn) {
		ls_foods_per_lb.reprice(frm, cdt, cdn, "weight_per_unit");
	},
});

// Share deposits: Deposit Due is totalled on save (ls_foods/share_deposit.py).
// "Collect Deposit" opens a Payment Entry against this order for whatever is
// still owed — a standard advance that the final invoice pulls in with Get Advances.
frappe.ui.form.on("Sales Order", {
	onload_post_render(frm) {
		ls_foods_per_lb.hydrate(frm);
	},
	refresh(frm) {
		ls_foods_per_lb.hydrate(frm);
		const owed = flt(frm.doc.custom_deposit_due) - flt(frm.doc.advance_paid);
		if (frm.doc.docstatus !== 1 || owed <= 0 || ["Closed", "Completed"].includes(frm.doc.status)) {
			return;
		}
		frm.add_custom_button(
			__("Collect Deposit ({0})", [format_currency(owed, frm.doc.currency)]),
			() =>
				frappe.call({
					method: "ls_foods.share_deposit.make_deposit_entry",
					args: { sales_order: frm.doc.name },
					callback(r) {
						if (!r.message) return;
						const doc = frappe.model.sync(r.message)[0];
						frappe.set_route("Form", doc.doctype, doc.name);
					},
				}),
			__("Create")
		);
	},
});
