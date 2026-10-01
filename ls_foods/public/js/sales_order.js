// LS Foods — Sales Order.
//
// The item grid is the invoice's: Case Weight (lb), Unit Price, Line Weight (lb).
// custom_case_weight is the entry box; weight_per_unit is the field ERPNext's own
// weight maths reads (see sales_invoice.js for why there are two).
//
// Items with a Per Pound price: Rate = $/lb x Case Weight (lb) (per_lb_pricing.js).
// A beef/hog share is ordered at its Standard Selling price, which IS the fixed
// deposit ($600 quarter / $1,200 half / $2,400 whole beef). The hanging-weight
// charge and processing are billed on the final invoice (share_billing.py).
//
// ls_foods/case_pricing.py does all of this again on save; this file is only
// about what happens while somebody is typing.

frappe.ui.form.on("Sales Order Item", {
	custom_case_weight(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row) return;

		// Triggers ERPNext's own weight_per_unit handler, which recomputes the
		// line's total_weight and the document's total_net_weight.
		frappe.model.set_value(cdt, cdn, "weight_per_unit", flt(row.custom_case_weight));
		// Priced per lb: the weight moves the price. Otherwise the case price
		// stays and Unit Price is worked out from it.
		if (ls_foods_per_lb.reprice(frm, cdt, cdn, "custom_case_weight")) return;
		ls_foods_order_unit_price(frm, cdt, cdn);
	},

	rate(frm, cdt, cdn) {
		ls_foods_order_unit_price(frm, cdt, cdn);
	},

	items_add(frm, cdt, cdn) {
		ls_foods_order_unit_price(frm, cdt, cdn);
	},

	item_code(frm, cdt, cdn) {
		ls_foods_per_lb.on_item(frm, cdt, cdn, "custom_case_weight");
		// The item's nominal case weight arrives with the rest of the item
		// details, a moment after the item is chosen.
		setTimeout(() => {
			const row = locals[cdt][cdn];
			if (!row) return;
			if (!flt(row.custom_case_weight) && flt(row.weight_per_unit)) {
				frappe.model.set_value(cdt, cdn, "custom_case_weight", flt(row.weight_per_unit));
			}
			ls_foods_order_unit_price(frm, cdt, cdn);
		}, 800);
	},
});

// Case-priced lines only: Unit Price = case price / case weight. A line priced
// from the Per Pound list already shows its $/lb, and a share shows none — its
// rate here is the deposit, and deposit / weight is not a price per lb.
function ls_foods_order_unit_price(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row || ls_foods_per_lb.is_per_lb(frm, row)) return;

	const known = ls_foods_per_lb.prices(frm)[row.item_code];
	const case_weight = flt(row.custom_case_weight);
	frappe.model.set_value(
		cdt,
		cdn,
		"custom_unit_price",
		case_weight && !(known && known.share) ? flt(row.rate) / case_weight : 0
	);
}

// Delivery Date on a row is not mandatory. It is not a field property — ERPNext's
// SalesOrderController.toggle_delivery_date() marks the grid column required
// whenever Order Type is Sales, so no Property Setter can switch it off; the
// method is replaced on this form instead. Nothing is lost: on save the server
// copies the order's Delivery Date onto every row left blank
// (SalesOrder.validate_delivery_date). Matters more now the column is out of
// the grid — a required field nobody can see would block the save.
function ls_foods_row_delivery_date_optional(frm) {
	const optional = () => {
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		if (grid) grid.toggle_reqd("delivery_date", false);
	};
	if (frm.cscript) frm.cscript.toggle_delivery_date = optional;
	optional();
}

// Share deposits: Deposit Due is totalled on save (ls_foods/share_deposit.py).
// "Collect Deposit" opens a Payment Entry against this order for whatever is
// still owed — a standard advance that the final invoice pulls in with Get Advances.
frappe.ui.form.on("Sales Order", {
	onload_post_render(frm) {
		ls_foods_per_lb.hydrate(frm);
	},
	refresh(frm) {
		ls_foods_per_lb.hydrate(frm);
		ls_foods_row_delivery_date_optional(frm);
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
