// LS Foods — price by the pound, shared by Sales Order and Sales Invoice.
//
// Each item's $/lb is an Item Price in the "Per Pound" price list. For a line
// whose item has one:  Rate (case price) = $/lb x Case Weight (lb). A heavy or
// light case is charged for what it weighs. A beef/hog share on a Sales Order is
// the exception — it stays at its fixed deposit until invoiced.
//
// The server (ls_foods/case_pricing.py apply_per_lb_pricing) applies the same
// rule on every save; this file only keeps the form live while typing.
//
// weight_field: custom_case_weight ("Case Weight (lb)") on both the invoice and
// the order.

window.ls_foods_per_lb = {
	// {item_code: {per_lb, share}} for the items on this form that have one.
	prices(frm) {
		frm.ls_per_lb = frm.ls_per_lb || {};
		return frm.ls_per_lb;
	},

	fetch(frm, codes, callback) {
		codes = (codes || []).filter(Boolean);
		if (!codes.length) return;
		frappe.call({
			method: "ls_foods.case_pricing.get_per_lb_prices",
			args: {
				item_codes: codes,
				customer: frm.doc.customer,
				on_date: frm.doc.posting_date || frm.doc.transaction_date,
			},
			callback(r) {
				const known = ls_foods_per_lb.prices(frm);
				codes.forEach((c) => delete known[c]);
				Object.assign(known, r.message || {});
				callback && callback(known);
			},
		});
	},

	// On open: learn every line's $/lb before anyone types, and show it.
	hydrate(frm) {
		if (frm.doc.docstatus !== 0) return;
		ls_foods_per_lb.fetch(
			frm,
			(frm.doc.items || []).map((r) => r.item_code),
			(known) => {
				(frm.doc.items || []).forEach((row) => {
					const p = known[row.item_code];
					if (!p) return;
					if (frappe.meta.has_field(row.doctype, "custom_priced_per_lb"))
						row.custom_priced_per_lb = p.share;
					if (p.per_lb && frappe.meta.has_field(row.doctype, "custom_unit_price"))
						row.custom_unit_price = p.per_lb;
				});
				frm.refresh_field("items");
			}
		);
	},

	// Item chosen: pick up its $/lb, then price the line once the item's
	// nominal weight has arrived with the rest of the item details.
	on_item(frm, cdt, cdn, weight_field) {
		const row = locals[cdt][cdn];
		if (!row || !row.item_code) return;
		ls_foods_per_lb.fetch(frm, [row.item_code], (known) => {
			const p = known[row.item_code];
			if (!p) return;
			if (frappe.meta.has_field(cdt, "custom_priced_per_lb"))
				frappe.model.set_value(cdt, cdn, "custom_priced_per_lb", p.share);
			if (p.per_lb && frappe.meta.has_field(cdt, "custom_unit_price"))
				frappe.model.set_value(cdt, cdn, "custom_unit_price", p.per_lb);
			setTimeout(() => ls_foods_per_lb.reprice(frm, cdt, cdn, weight_field), 800);
		});
	},

	// True when this line is priced from the Per Pound list on this form.
	is_per_lb(frm, row) {
		const p = row && ls_foods_per_lb.prices(frm)[row.item_code];
		if (!p || !p.per_lb) return false;
		return !(p.share && frm.doctype === "Sales Order");
	},

	// Rate = $/lb x weight. Set via price_list_rate so ERPNext's own handler
	// derives rate (keeping any discount) and recomputes totals.
	reprice(frm, cdt, cdn, weight_field) {
		const row = locals[cdt][cdn];
		if (!ls_foods_per_lb.is_per_lb(frm, row)) return false;

		const per_lb = ls_foods_per_lb.prices(frm)[row.item_code].per_lb;
		const weight = flt(row[weight_field]) || flt(row.weight_per_unit);
		if (!weight) return true;

		frappe.model.set_value(cdt, cdn, "price_list_rate", per_lb * weight);
		ls_foods_per_lb.sync_processing(frm, row, weight);
		return true;
	},

	// The processing line under a share (custom_share_item) follows its weight.
	// The server does the same on save and adds the line if it is missing.
	sync_processing(frm, row, weight) {
		const fee = (frm.doc.items || []).find(
			(r) => r.custom_share_item && r.custom_share_item === row.item_code && r.idx > row.idx
		);
		if (fee) frappe.model.set_value(fee.doctype, fee.name, "qty", flt(row.qty) * weight);
	},
};
