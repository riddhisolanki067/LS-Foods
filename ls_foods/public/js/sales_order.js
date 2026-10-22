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
		if (frm.doc.docstatus < 2 && !["Closed", "Completed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Update Weights from Items"), () => ls_foods_weight_dialog(frm));
		}
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

// "Update Weights from Items": an item's weight was missing or wrong when the
// line was added, and has since been corrected on the item. Shows each line
// whose weight differs from the item master and copies the ticked ones across —
// also on a submitted order (ls_foods/order_weight_refresh.py).
function ls_foods_weight_dialog(frm) {
	frappe.call({
		method: "ls_foods.order_weight_refresh.get_weight_changes",
		args: { sales_order: frm.doc.name },
		freeze: true,
		callback(r) {
			const changes = r.message || [];
			if (!changes.length) {
				frappe.msgprint(__("Every line already has the item's current weight."));
				return;
			}
			const money = changes.some((c) => c.new_rate !== c.old_rate);
			const body = changes
				.map(
					(c) => `<tr>
						<td><input type="checkbox" class="ls-weight-row" data-row="${c.row}" checked></td>
						<td>${c.idx}</td>
						<td>${frappe.utils.escape_html(c.item_code)}<br><small class="text-muted">${frappe.utils.escape_html(c.item_name || "")}</small></td>
						<td class="text-right">${c.qty}</td>
						<td class="text-right">${c.old_weight} → <b>${c.new_weight}</b></td>
						${money ? `<td class="text-right">${c.new_rate !== c.old_rate ? `${format_currency(c.old_rate, frm.doc.currency)} → <b>${format_currency(c.new_rate, frm.doc.currency)}</b>` : __("no change")}</td>` : ""}
					</tr>`
				)
				.join("");
			const d = new frappe.ui.Dialog({
				title: __("Update Weights from Items"),
				size: "large",
				fields: [{ fieldtype: "HTML", fieldname: "rows" }],
				primary_action_label: __("Update Ticked Lines"),
				primary_action() {
					const rows = d.$wrapper.find(".ls-weight-row:checked").map((i, el) => $(el).data("row")).get();
					if (!rows.length) return;
					frappe.call({
						method: "ls_foods.order_weight_refresh.apply_weight_changes",
						args: { sales_order: frm.doc.name, rows },
						freeze: true,
						callback(res) {
							d.hide();
							const out = res.message || {};
							frappe.show_alert({
								message: __("{0} line(s) updated", [out.updated || 0]),
								indicator: "green",
							});
							if (out.overpaid) {
								frappe.msgprint(
									__("The order total is now {0} less than what has already been paid against it.", [
										format_currency(out.overpaid, frm.doc.currency),
									]),
									__("Paid more than the order total")
								);
							}
							frm.reload_doc();
						},
					});
				},
			});
			d.fields_dict.rows.$wrapper.html(`
				<p class="text-muted">${__("Case Weight, Line Weight and Unit Price ($/lb) are copied from the item. The case price stays as it is")}${
					money ? __(", except for items priced per lb, where the price follows the weight") : ""
				}.</p>
				<table class="table table-bordered table-sm">
					<thead><tr><th></th><th>#</th><th>${__("Item")}</th><th>${__("Qty")}</th><th>${__("Case Weight (lb)")}</th>${
						money ? `<th>${__("Rate")}</th>` : ""
					}</tr></thead>
					<tbody>${body}</tbody>
				</table>`);
			d.show();
		},
	});
}
