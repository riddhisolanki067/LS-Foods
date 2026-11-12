// LS Foods — enter buying lines by Item Code OR by Supplier Part Number.
// Server side and the rules for which number is saved: ls_foods/supplier_part.py.
//
// 1. The Item Code dropdown also finds items by supplier part number: the
//    standard query keeps its filters, only the method is swapped for ours.
// 2. Typing a number into the Supplier Part Number column fills the Item Code
//    (asks which item when several share the number).
//
// This file is included in all six buying forms; the guard registers the
// handlers once however many of them get opened.

if (!window.ls_foods_supplier_part_loaded) {
	window.ls_foods_supplier_part_loaded = true;

	const CORE_ITEM_QUERY = "erpnext.controllers.queries.item_query";
	const LS_ITEM_QUERY = "ls_foods.supplier_part.item_query";
	const BUYING = {
		"Material Request": "Material Request Item",
		"Request for Quotation": "Request for Quotation Item",
		"Supplier Quotation": "Supplier Quotation Item",
		"Purchase Order": "Purchase Order Item",
		"Purchase Receipt": "Purchase Receipt Item",
		"Purchase Invoice": "Purchase Invoice Item",
	};

	// ERPNext sets the item_code query in the form's setup/onload; refresh comes
	// later, so wrap whatever query is there.
	const use_part_no_search = (frm) => {
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		const field = grid && grid.get_field("item_code");
		if (!field || (field.get_query && field.get_query.ls_foods_part_no)) return;
		const standard = field.get_query;
		const wrapped = function (...args) {
			const q = (standard ? standard.apply(this, args) : null) || {};
			if (!q.query || q.query === CORE_ITEM_QUERY) q.query = LS_ITEM_QUERY;
			return q;
		};
		wrapped.ls_foods_part_no = true;
		field.get_query = wrapped;
	};

	// The Supplier Part Number column is a dropdown (Autocomplete) fed by the Item
	// Suppliers table: only that item's numbers once an Item Code is picked, only
	// the document supplier's numbers on documents that have one.
	const use_part_no_dropdown = (frm) => {
		const grid = frm.fields_dict.items && frm.fields_dict.items.grid;
		const field = grid && grid.get_field("supplier_part_no");
		if (!field || field.get_query) return;
		field.get_query = (doc, cdt, cdn) => {
			const row = locals[cdt] && locals[cdt][cdn];
			return {
				query: "ls_foods.supplier_part.part_no_query",
				params: {
					supplier: frm.doc.supplier || null,
					item_code: (row && row.item_code) || null,
				},
			};
		};
	};

	const fill_item_from_part_no = (frm, cdt, cdn) => {
		const row = locals[cdt][cdn];
		const part_no = (row.supplier_part_no || "").trim();
		if (!part_no) return;
		const supplier = frm.doc.supplier || null;

		frappe
			.xcall("ls_foods.supplier_part.find_items_by_part_no", { part_no, supplier })
			.then((items) => {
				// already the right item (e.g. ERPNext just filled the number in)
				if (items.some((i) => i.item_code === row.item_code)) return;
				if (!items.length) {
					// pick-from-list only: drop a typed number that matches nothing
					frappe.model.set_value(cdt, cdn, "supplier_part_no", "");
					frappe.show_alert({
						message: supplier
							? __("No item has Supplier Part Number {0} for {1}", [part_no, supplier])
							: __("No item has Supplier Part Number {0}", [part_no]),
						indicator: "orange",
					});
					return;
				}
				const unique = [...new Set(items.map((i) => i.item_code))];
				if (unique.length === 1) return set_item(items[0]);

				const dialog = new frappe.ui.Dialog({
					title: __("Supplier Part Number {0}", [part_no]),
					fields: [
						{
							fieldname: "choice",
							fieldtype: "Select",
							label: __("Item"),
							reqd: 1,
							options: items.map((i, n) => ({
								value: String(n),
								label: `${i.item_code}: ${i.item_name} (${i.supplier})`,
							})),
						},
					],
					primary_action_label: __("Select"),
					primary_action({ choice }) {
						dialog.hide();
						set_item(items[cint(choice)]);
					},
				});
				dialog.show();
			});

		function set_item(item) {
			frappe.model.set_value(cdt, cdn, "item_code", item.item_code);
			// On Material Request / RFQ (no supplier) ERPNext's item lookup does not
			// know the number; put the typed one back once it has finished.
			frappe.after_ajax(() => {
				if (row.item_code === item.item_code && !row.supplier_part_no) {
					frappe.model.set_value(cdt, cdn, "supplier_part_no", item.supplier_part_no);
				}
			});
		}
	};

	for (const [doctype, child] of Object.entries(BUYING)) {
		frappe.ui.form.on(doctype, {
			refresh(frm) {
				use_part_no_search(frm);
				use_part_no_dropdown(frm);
			},
		});
		frappe.ui.form.on(child, { supplier_part_no: fill_item_from_part_no });
	}
}
