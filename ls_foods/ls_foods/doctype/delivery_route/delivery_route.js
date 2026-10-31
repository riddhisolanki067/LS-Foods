// Delivery Route: paste the route's Sales Order Nos., save, download one PDF
// of their invoices in that order (see delivery_route.py).

frappe.ui.form.on("Delivery Route", {
	refresh(frm) {
		// The stops follow the pasted list: rows are not added or removed by hand.
		frm.set_df_property("stops", "cannot_add_rows", true);
		frm.set_df_property("stops", "cannot_delete_rows", true);
		frm.set_df_property("invoice_choices", "cannot_add_rows", true);
		frm.set_df_property("invoice_choices", "cannot_delete_rows", true);
		render_check(frm);

		if (!frm.is_new() && (frm.doc.stops || []).some((s) => s.sales_order)) {
			frm.add_custom_button(__("Download Invoices PDF"), () => download_pdf(frm)).addClass(
				"btn-primary"
			);
		}
	},

	route_date: offer_existing,
	vehicle: offer_existing,
});

function download_pdf(frm) {
	const open_pdf = (count) => {
		const url =
			"/api/method/ls_foods.ls_foods.doctype.delivery_route.delivery_route.download_invoices_pdf?name=" +
			encodeURIComponent(frm.doc.name);
		frappe.show_alert({
			message: __("Preparing {0} invoice(s)…", [count]),
			indicator: "blue",
		});
		window.open(url);
	};
	// The refresh picks up invoices made since the last save (a backorder
	// invoice) and saves only if something moved. frm.save() is for unsaved edits
	// alone: on an unchanged form it stops at "No changes in document".
	const go = () =>
		frappe
			.xcall("ls_foods.ls_foods.doctype.delivery_route.delivery_route.refresh_route", {
				name: frm.doc.name,
			})
			.then((r) => (r.changed ? frm.reload_doc().then(() => r) : r))
			.then((r) => {
				if (r.awaiting_choice.length) {
					frappe.msgprint({
						title: __("Choose the Invoices"),
						indicator: "orange",
						message: __(
							"These orders have several invoices. Tick the one(s) to include in the Orders With Several Invoices table: {0}",
							[r.awaiting_choice.map(frappe.utils.escape_html).join(", ")]
						),
					});
					frm.scroll_to_field("invoice_choices");
				} else if (!r.invoices) {
					frappe.msgprint(__("No invoices to print on this route."));
				} else {
					open_pdf(r.invoices);
				}
			});
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
	const choices = frm.doc.invoice_choices || [];
	const rows_of = (s) => choices.filter((c) => c.sales_order === s.sales_order);
	const selected = (s) => {
		const rows = rows_of(s);
		return rows.length ? rows.filter((c) => c.include) : s.sales_invoice ? [s] : [];
	};
	const printing = stops.filter((s) => s.print_invoice && selected(s).length);
	const choose = stops.filter((s) => s.print_invoice && rows_of(s).length && !selected(s).length);
	const missing = stops.filter((s) => s.sales_order && !s.sales_invoice && !rows_of(s).length);
	const problems = stops.filter((s) => !s.sales_order);
	const skipped = stops.filter((s) => !s.print_invoice && (s.sales_invoice || rows_of(s).length));
	const seen = {};
	let count = 0;
	let total = 0;
	printing.forEach((s) =>
		selected(s).forEach((row) => {
			const invoice = row.sales_invoice;
			if (seen[invoice]) return;
			seen[invoice] = true;
			count++;
			total += row.grand_total || 0;
		})
	);

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
			<div style="font-size: var(--text-lg)"><b>${count}</b> ${__("invoice(s) will print")}
				<span class="text-muted">· ${format_currency(total)}</span></div>
			${block(choose, "orange", __("Choose an invoice"), (s) => `${s.sales_order} ${s.customer_name || ""}`)}
			${block(missing, "orange", __("No invoice"), (s) => `${s.sales_order} ${s.customer_name || ""}`)}
			${block(problems, "red", __("Not printed"), (s) => s.note)}
			${block(skipped, "gray", __("Unticked"), (s) => `${s.sales_order} ${s.note || ""}`)}
		</div>`);
}

frappe.ui.form.on("Delivery Route Stop", {
	print_invoice: render_check,
});

frappe.ui.form.on("Delivery Route Invoice", {
	include: render_check,
});
