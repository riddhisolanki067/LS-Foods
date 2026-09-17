// LS Foods — Sales Invoice.
//
// Items are stocked and sold in Cases, so "Case Weight (lb)" is simply the
// pounds in one case. The user types it per line; everything else follows.
//
// custom_case_weight is the entry box (positioned where it belongs in the grid);
// weight_per_unit is the field ERPNext's own weight maths reads. Pushing one
// into the other here makes ERPNext recalculate Line Weight and Total Weight
// (lb) live, exactly as if the standard field had been edited.
//
// ls_foods/case_pricing.py does the same on before_validate, so an invoice made
// by API, Data Import or from a Sales Order lands correct with no browser
// involved. This file is only about what happens while somebody is typing.

frappe.ui.form.on("Sales Invoice Item", {
	custom_case_weight(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row) return;

		// Triggers ERPNext's own weight_per_unit handler, which recomputes the
		// line's total_weight and the document's total_net_weight.
		frappe.model.set_value(cdt, cdn, "weight_per_unit", flt(row.custom_case_weight));
		ls_foods_set_unit_price(cdt, cdn);
	},

	rate(frm, cdt, cdn) {
		ls_foods_set_unit_price(cdt, cdn);
	},

	items_add(frm, cdt, cdn) {
		ls_foods_set_unit_price(cdt, cdn);
	},

	item_code(frm, cdt, cdn) {
		// The item's nominal case weight arrives with the rest of the item
		// details, a moment after the item is chosen.
		setTimeout(() => {
			const row = locals[cdt][cdn];
			if (!row) return;
			if (!flt(row.custom_case_weight) && flt(row.weight_per_unit)) {
				frappe.model.set_value(cdt, cdn, "custom_case_weight", flt(row.weight_per_unit));
			}
			ls_foods_set_unit_price(cdt, cdn);
		}, 800);
	},
});

function ls_foods_set_unit_price(cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!row) return;

	const case_weight = flt(row.custom_case_weight);
	frappe.model.set_value(
		cdt,
		cdn,
		"custom_unit_price",
		case_weight ? flt(row.rate) / case_weight : 0
	);
}
