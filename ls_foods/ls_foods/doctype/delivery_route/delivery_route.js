// Delivery Route: paste the route's Sales Order Nos., save, download one PDF
// of their invoices in that order (see delivery_route.py).

frappe.ui.form.on("Delivery Route", {
	setup(frm) {
		// Only the order's own invoices can be picked on a stop.
		frm.set_query("sales_invoice", "stops", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn];
			return {
				filters: [
					["Sales Invoice Item", "sales_order", "=", row.sales_order || ""],
					["Sales Invoice", "docstatus", "<", 2],
					["Sales Invoice", "is_return", "=", 0],
				],
			};
		});
	},

	refresh(frm) {
		// The stops follow the pasted list: rows are not added or removed by hand.
		frm.set_df_property("stops", "cannot_add_rows", true);
		frm.set_df_property("stops", "cannot_delete_rows", true);
		render_check(frm);

		if (!frm.is_new() && frm.doc.invoices_to_print) {
			frm.add_custom_button(__("Download Invoices PDF"), () => download_pdf(frm)).addClass(
				"btn-primary"
			);
		}
	},

	route_date: offer_existing,
	vehicle: offer_existing,
});

function download_pdf(frm) {
	const go = () => {
		const url =
			"/api/method/ls_foods.ls_foods.doctype.delivery_route.delivery_route.download_invoices_pdf?name=" +
			encodeURIComponent(frm.doc.name);
		frappe.show_alert({
			message: __("Preparing {0} invoice(s)…", [frm.doc.invoices_to_print]),
			indicator: "blue",
		});
		window.open(url);
	};
	// Unsaved paste or ticks: save first so the PDF matches the screen.
	frm.is_dirty() ? frm.save().then(go) : go();
}

// A route for this date and vehicle already exists: replace its list there.
function offer_existing(frm) {
	if (!frm.is_new() || !frm.doc.route_date) return;
	const name = `${frm.doc.route_date} ${(frm.doc.vehicle || "").trim()}`.trim();
	frappe.db.exists("Delivery Route", name).then((exists) => {
		if (!exists) return;
		frappe.confirm(
			__("There is already a route for {0}. Open it and paste the new list there?", [
				frappe.utils.escape_html(name),
			]),
			() => frappe.set_route("Form", "Delivery Route", name)
		);
	});
}

// What will and will not print, above the table.
function render_check(frm) {
	const field = frm.get_field("route_check");
	if (frm.is_new() || !(frm.doc.stops || []).length) {
		field.$wrapper.html(
			`<div class="text-muted small" style="padding-top: 28px">${__(
				"Paste the orders and save: the print order appears below."
			)}</div>`
		);
		return;
	}
	const stops = frm.doc.stops;
	const printing = stops.filter((s) => s.sales_invoice && s.print_invoice);
	const missing = stops.filter((s) => s.sales_order && !s.sales_invoice);
	const problems = stops.filter((s) => !s.sales_order);
	const skipped = stops.filter((s) => s.sales_invoice && !s.print_invoice);
	const total = printing.reduce((t, s) => t + (s.grand_total || 0), 0);

	const list = (rows, text) =>
		rows
			.map((s) => `<li>${__("Stop {0}", [s.idx])}: ${frappe.utils.escape_html(text(s))}</li>`)
			.join("");
	const block = (rows, color, title, text) =>
		rows.length
			? `<div style="margin-top: 10px"><span class="indicator-pill ${color}">${title}</span>
				<ul class="small" style="margin: 6px 0 0; padding-left: 18px">${list(rows, text)}</ul></div>`
			: "";

	field.$wrapper.html(`
		<div style="padding-top: 22px">
			<div style="font-size: var(--text-lg)"><b>${printing.length}</b> ${__("invoice(s) will print")}
				<span class="text-muted">· ${format_currency(total)}</span></div>
			${block(missing, "orange", __("No invoice"), (s) => `${s.sales_order} ${s.customer_name || ""}`)}
			${block(problems, "red", __("Not printed"), (s) => s.note)}
			${block(skipped, "gray", __("Unticked"), (s) => `${s.sales_order} ${s.note || ""}`)}
		</div>`);
}

frappe.ui.form.on("Delivery Route Stop", {
	print_invoice: render_check,
	sales_invoice(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.sales_invoice) return;
		frappe.db
			.get_value("Sales Invoice", row.sales_invoice, ["docstatus", "grand_total", "rounded_total"])
			.then(({ message: si }) => {
				frappe.model.set_value(cdt, cdn, {
					invoice_status: si.docstatus == 1 ? __("Submitted") : __("Draft"),
					grand_total: si.rounded_total || si.grand_total,
				});
				render_check(frm);
			});
	},
});
