// LS Foods — Sales Order list: "Update Weights from Items" for the ticked orders.
// Same rule as the form button (ls_foods/order_weight_refresh.py): every line
// whose weight differs from the item master gets the item's weight; lines already
// delivered or invoiced, shares and non-stock lines are left alone.
frappe.listview_settings["Sales Order"] = frappe.listview_settings["Sales Order"] || {};
(function (settings) {
	const original = settings.onload;
	settings.onload = function (listview) {
		if (original) original.apply(this, arguments);
		listview.page.add_actions_menu_item(__("Update Weights from Items"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) return;
			frappe.confirm(
				__("Copy the item master's weight onto every differing line of {0} order(s)?", [names.length]),
				() =>
					frappe.call({
						method: "ls_foods.order_weight_refresh.apply_weight_changes_bulk",
						args: { sales_orders: names },
						freeze: true,
						callback(r) {
							const res = r.message || {};
							const lines = Object.entries(res).map(([n, v]) =>
								v.error
									? `${n}: <span class="text-danger">${frappe.utils.escape_html(v.error)}</span>`
									: `${n}: ${v.updated} line(s)` +
									  (v.overpaid ? ` <span class="text-warning">${__("paid {0} more than the new total", [format_currency(v.overpaid)])}</span>` : "")
							);
							frappe.msgprint(lines.join("<br>"), __("Weights updated"));
							listview.refresh();
						},
					})
			);
		});
	};
})(frappe.listview_settings["Sales Order"]);
