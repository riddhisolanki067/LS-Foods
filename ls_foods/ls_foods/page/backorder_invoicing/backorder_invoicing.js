// LS Foods — Backorders & Invoicing.
//
// One screen for a whole delivery run: list the open Sales Order lines (filter
// by pick-up location, customer, item, order date), say which items did not
// come in, and create one invoice per order for everything else in one click.
// Server side: ls_foods/order_invoicing.py.
//
// Backordered Items table — one row per item that did not come in: the item
// is held back on every order shown.
// Single lines can also be unticked, or their "To Invoice" lowered, in the
// Order Lines table. Nothing is stored for a backorder: the line stays on its
// order, still to be invoiced, and is listed here again until it is.

frappe.pages["backorder-invoicing"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Backorders & Invoicing"),
		single_column: true,
	});
	wrapper.ls_backorders = new LSBackorderInvoicing(page);
};

frappe.pages["backorder-invoicing"].on_page_show = function (wrapper) {
	const tool = wrapper.ls_backorders;
	if (tool && tool.take_route_options()) tool.load();
};

class LSBackorderInvoicing {
	constructor(page) {
		this.page = page;
		this.orders = [];
		this.bo_rows = []; // [{item_code, item_name, item_ctrl}]
		this.only_orders = null;
		this.inject_style();
		this.make_filters();
		this.make_body();
		this.page.set_primary_action(__("Create Invoices"), () => this.confirm_create(), "file-text");
		this.page.add_menu_item(__("Sales Orders"), () => frappe.set_route("List", "Sales Order"));
		this.page.add_menu_item(__("Sales Invoices"), () => frappe.set_route("List", "Sales Invoice"));
		this.take_route_options();
		this.load();
	}

	// Opened from the Sales Order list with orders ticked: show only those.
	take_route_options() {
		const opts = frappe.route_options;
		if (!(opts && opts.sales_orders)) return false;
		this.only_orders = opts.sales_orders;
		frappe.route_options = null;
		return true;
	}

	// ---------------------------------------------------------------- layout

	make_filters() {
		const change = () => {
			this.only_orders = null;
			this.load();
		};
		const add = (fieldname, label, fieldtype, options) =>
			this.page.add_field({ fieldname, label: __(label), fieldtype, options, change });
		this.filters = {
			pick_up_location: add("pick_up_location", "Pick-Up Location", "Link", "Pick-Up Location"),
			customer: add("customer", "Customer", "Link", "Customer"),
			item_code: add("item_code", "Orders with Item", "Link", "Item"),
			from_date: add("from_date", "Order Date From", "Date"),
			to_date: add("to_date", "Order Date To", "Date"),
		};
	}

	make_body() {
		const $b = $(this.page.body).addClass("lsbo");
		$b.html(`
			<div class="lsbo-section">
				<div class="lsbo-h">${__("Backordered Items")}</div>
				<div class="lsbo-muted">${__(
					"One row per item that did not come in. It is held back on every order below and stays on the orders to invoice later."
				)}</div>
				<table class="table table-bordered table-sm lsbo-bo">
					<thead><tr>
						<th style="width:34px">#</th>
						<th style="width:30%">${__("Item")}</th>
						<th>${__("Item Name")}</th>
						<th class="text-right" style="width:120px">${__("On Orders")}</th>
						<th style="width:34px"></th>
					</tr></thead>
					<tbody></tbody>
				</table>
				<button class="btn btn-default btn-xs lsbo-bo-add">${__("Add Row")}</button>
			</div>
			<div class="lsbo-section">
				<div class="lsbo-bar">
					<div class="lsbo-h">${__("Order Lines")}</div>
					<div class="lsbo-summary"></div>
				</div>
				<div class="lsbo-tools lsbo-muted"></div>
				<div class="lsbo-lines-wrap"></div>
			</div>
		`);
		this.$bo = $b.find(".lsbo-bo tbody");
		this.$lines = $b.find(".lsbo-lines-wrap");
		this.$summary = $b.find(".lsbo-summary");
		this.$tools = $b.find(".lsbo-tools");

		$b.find(".lsbo-bo-add").on("click", () => this.add_bo_row());
		this.$bo.on("click", ".lsbo-bo-del", (e) => {
			const i = $(e.currentTarget).closest("tr").index();
			this.bo_rows.splice(i, 1);
			$(e.currentTarget).closest("tr").remove();
			if (!this.bo_rows.some((r) => !r.item_code)) this.add_bo_row();
			this.renumber_bo();
			this.apply_backorders();
		});

		// Order header row: invoice this order or skip it.
		this.$lines.on("change", ".lsbo-order-check", (e) => {
			this.order($(e.currentTarget).data("order")).skip = !e.currentTarget.checked;
			// A skipped order takes no share of a shortage: re-spread it.
			this.apply_backorders();
		});
		// Line: tick = invoice all of it, untick = backorder all of it.
		this.$lines.on("change", ".lsbo-line-check", (e) => {
			const l = this.line_of(e.currentTarget);
			l.to_invoice = e.currentTarget.checked ? l.pending : 0;
			this.render_lines();
		});
		this.$lines.on("change", ".lsbo-line-qty", (e) => {
			const l = this.line_of(e.currentTarget);
			l.to_invoice = Math.min(Math.max(flt(e.currentTarget.value), 0), l.pending);
			this.render_lines();
		});
		this.$tools.on("click", "[data-action]", (e) => {
			const action = $(e.currentTarget).data("action");
			if (action === "held") {
				this.only_held = !this.only_held;
				this.render_lines();
				return;
			}
			this.orders.forEach((o) => (o.skip = action === "none"));
			this.apply_backorders();
		});

		this.add_bo_row();
	}

	add_bo_row() {
		const $tr = $(`<tr>
			<td class="lsbo-bo-idx"></td>
			<td class="lsbo-bo-item"></td>
			<td class="lsbo-bo-name lsbo-muted"></td>
			<td class="text-right lsbo-bo-on"></td>
			<td><a class="lsbo-bo-del" title="${__("Remove")}">&times;</a></td>
		</tr>`).appendTo(this.$bo);
		const row = { item_code: "", item_name: "" };
		row.item_ctrl = frappe.ui.form.make_control({
			parent: $tr.find(".lsbo-bo-item"),
			df: {
				fieldtype: "Link",
				options: "Item",
				fieldname: "bo_item",
				placeholder: __("Item"),
				change: () => {
					const v = row.item_ctrl.get_value() || "";
					if (v === row.item_code) return;
					row.item_code = v;
					row.item_name = "";
					const line = this.all_lines().find((l) => l.item_code === v);
					if (line) row.item_name = line.item_name;
					else if (v) frappe.db.get_value("Item", v, "item_name").then((r) => {
						row.item_name = (r.message || {}).item_name || "";
						this.render_bo();
					});
					this.apply_backorders();
					// Always keep one empty row to type the next item into.
					if (v && this.bo_rows[this.bo_rows.length - 1] === row) this.add_bo_row();
				},
			},
			render_input: true,
			only_input: true,
		});
		this.bo_rows.push(row);
		this.renumber_bo();
	}

	renumber_bo() {
		this.$bo.find("tr").each((i, tr) => $(tr).find(".lsbo-bo-idx").text(i + 1));
	}

	// ------------------------------------------------------------------ data

	load() {
		const args = {};
		Object.entries(this.filters).forEach(([k, f]) => (args[k] = f.get_value() || null));
		if (this.only_orders) args.sales_orders = this.only_orders;
		this.$lines.html(`<div class="lsbo-empty">${__("Loading open orders…")}</div>`);
		frappe.call({
			method: "ls_foods.order_invoicing.get_open_orders",
			args,
			callback: (r) => {
				const res = r.message || {};
				this.shares_skipped = res.shares_skipped || 0;
				this.applied_items = [];
				this.orders = (res.orders || []).map((o) => {
					o.skip = false;
					o.lines.forEach((l) => (l.to_invoice = l.pending));
					return o;
				});
				this.bo_rows.forEach((row) => {
					const line = this.all_lines().find((l) => l.item_code === row.item_code);
					if (line) row.item_name = line.item_name;
				});
				this.apply_backorders();
			},
		});
	}

	all_lines() {
		return this.orders.flatMap((o) => o.lines);
	}

	order(name) {
		return this.orders.find((o) => o.name === name);
	}

	line_of(el) {
		const o = this.order($(el).closest("tr").data("order"));
		return o.lines.find((x) => x.so_detail === $(el).closest("tr").data("line"));
	}

	// Lines of an item on the orders, oldest order first (the server's order).
	item_lines(item) {
		const out = [];
		this.orders.forEach((o) => o.lines.forEach((l) => l.item_code === item && !l.is_fee && out.push({ o, l })));
		return out;
	}

	// Every item in the Backordered Items table is held back on every order
	// being invoiced. An item taken out of the table (or changed to another) is
	// filled again; lines of other items keep whatever was typed on them.
	apply_backorders() {
		const items = [...new Set(this.bo_rows.map((r) => r.item_code).filter(Boolean))];
		(this.applied_items || []).filter((item) => !items.includes(item)).forEach((item) =>
			this.item_lines(item).forEach(({ l }) => (l.to_invoice = l.pending))
		);
		this.applied_items = items;
		items.forEach((item) => this.item_lines(item).forEach(({ o, l }) => (l.to_invoice = o.skip ? l.pending : 0)));
		this.render_lines();
	}

	// What an order will invoice: the goods being sent, plus its charge lines
	// (delivery, late fee, free-item credit) — never the charges alone while
	// the goods are still to come.
	invoice_lines(o) {
		if (o.skip) return [];
		const goods = o.lines.filter((l) => !l.is_fee && l.to_invoice > 0);
		if (o.lines.some((l) => !l.is_fee) && !goods.length) return [];
		return o.lines.filter((l) => l.to_invoice > 0);
	}

	totals() {
		const t = { orders: 0, lines: 0, held: 0, amount: 0 };
		this.orders.forEach((o) => {
			const inv = this.invoice_lines(o);
			if (inv.length) t.orders++;
			t.lines += inv.length;
			t.amount += inv.reduce((s, l) => s + l.to_invoice * l.rate, 0);
			t.held += o.lines.filter((l) => !l.is_fee && l.to_invoice < l.pending).length;
		});
		return t;
	}

	// ---------------------------------------------------------------- render

	render_bo() {
		this.bo_rows.forEach((row, i) => {
			const $tr = this.$bo.find("tr").eq(i);
			const lines = row.item_code ? this.item_lines(row.item_code) : [];
			$tr.find(".lsbo-bo-name").text(row.item_name || "");
			$tr.find(".lsbo-bo-on").text(row.item_code ? fmt_qty(lines.reduce((s, { l }) => s + l.pending, 0)) : "");
		});
	}

	render_lines() {
		this.render_bo();
		const t = this.totals();
		const cur = (this.orders[0] && this.orders[0].currency) || frappe.defaults.get_default("currency");
		this.$summary.html(
			__("{0} invoice(s) · {1} line(s) · {2} backordered · {3}", [
				`<b>${t.orders}</b>`,
				t.lines,
				`<span class="lsbo-red-text">${t.held}</span>`,
				`<b>${format_currency(t.amount, cur)}</b>`,
			])
		);
		this.$tools.html(
			`${__("{0} open orders", [this.orders.length])}${this.only_orders ? ` · ${__("only the orders ticked in the list")}` : ""}${
				this.shares_skipped ? ` · ${__("{0} order(s) with a beef/hog share not shown — invoice those from the order", [this.shares_skipped])}` : ""
			} · <a data-action="all">${__("Select all")}</a> · <a data-action="none">${__("Select none")}</a> · <a data-action="held">${
				this.only_held ? __("Show all orders") : __("Show only orders with backorders")
			}</a>`
		);
		if (!this.orders.length) {
			this.$lines.html(`<div class="lsbo-empty">${__("No open orders to invoice for these filters.")}</div>`);
			return;
		}
		const body = this.orders
			.filter((o) => !this.only_held || o.lines.some((l) => !l.is_fee && l.to_invoice < l.pending))
			.map((o) => this.order_rows(o))
			.join("");
		this.$lines.html(`<table class="table table-bordered table-sm lsbo-lines">
			<thead><tr>
				<th style="width:30px"></th>
				<th style="width:110px">${__("Item")}</th>
				<th>${__("Description")}</th>
				<th class="text-right" style="width:95px">${__("Ordered")}</th>
				<th class="text-right" style="width:80px">${__("Invoiced")}</th>
				<th class="text-right" style="width:100px">${__("To Invoice")}</th>
				<th class="text-right" style="width:100px">${__("Backordered")}</th>
				<th class="text-right" style="width:100px">${__("Amount")}</th>
			</tr></thead>
			<tbody>${body}</tbody>
		</table>`);
	}

	order_rows(o) {
		const inv = this.invoice_lines(o);
		const amount = inv.reduce((s, l) => s + l.to_invoice * l.rate, 0);
		const notes = [];
		if (o.partly_invoiced) notes.push(__("partly invoiced"));
		(o.draft_invoices || []).forEach((n) =>
			notes.push(`<a href="/app/sales-invoice/${encodeURIComponent(n)}" target="_blank">${__("draft invoice {0}", [esc(n)])}</a>`)
		);
		if (!o.skip && !inv.length) notes.push(__("nothing to invoice"));
		const head = `<tr class="lsbo-order ${o.skip ? "lsbo-skip" : ""}" data-order="${esc(o.name)}">
			<td><input type="checkbox" class="lsbo-order-check" data-order="${esc(o.name)}" ${o.skip ? "" : "checked"} title="${__("Invoice this order")}"></td>
			<td colspan="6">
				<a href="/app/sales-order/${encodeURIComponent(o.name)}" target="_blank">${esc(o.name)}</a>
				· <b>${esc(o.customer_name)}</b>
				<span class="lsbo-muted">· ${esc(o.pick_up_location_name || "")} · ${frappe.datetime.str_to_user(o.transaction_date)}
				· ${__("Paid")} ${format_currency(o.advance_paid, o.currency)}${notes.length ? " · " + notes.join(" · ") : ""}</span>
			</td>
			<td class="text-right"><b>${format_currency(amount, o.currency)}</b></td>
		</tr>`;
		const lines = o.lines
			.map((l) => {
				const held = l.is_fee ? 0 : flt(l.pending - l.to_invoice, 6);
				const off = o.skip ? "disabled" : "";
				return `<tr data-order="${esc(o.name)}" data-line="${esc(l.so_detail)}" class="${held > 0 ? "lsbo-held" : ""} ${o.skip ? "lsbo-skip" : ""}">
					<td><input type="checkbox" class="lsbo-line-check" ${l.to_invoice > 0 ? "checked" : ""} ${off}></td>
					<td>${esc(l.item_code)}</td>
					<td>${esc(l.item_name)}${l.is_fee ? ` <span class="lsbo-muted">(${__("charge")})</span>` : ""}</td>
					<td class="text-right">${fmt_qty(l.qty)} <span class="lsbo-muted">${esc(l.uom || "")}</span></td>
					<td class="text-right">${l.invoiced ? fmt_qty(l.invoiced) : ""}</td>
					<td class="text-right"><input type="number" class="form-control input-xs lsbo-line-qty" min="0" max="${l.pending}" step="any" value="${l.to_invoice}" ${off}></td>
					<td class="text-right">${held > 0 ? `<span class="lsbo-red-text">${fmt_qty(held)}</span>` : ""}</td>
					<td class="text-right">${format_currency(l.to_invoice * l.rate, o.currency)}</td>
				</tr>`;
			})
			.join("");
		return head + lines;
	}

	// ---------------------------------------------------------------- create

	confirm_create() {
		const todo = this.orders.filter((o) => this.invoice_lines(o).length);
		if (!todo.length) {
			frappe.msgprint(__("Nothing selected to invoice."));
			return;
		}
		const t = this.totals();
		const d = new frappe.ui.Dialog({
			title: __("Create {0} Invoice(s)", [todo.length]),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${__(
						"One invoice per order, {0} line(s), {1} before deposits. Deposits and payments already made on each order are taken off its invoice. Backordered lines stay on their orders.",
						[t.lines, format_currency(t.amount, todo[0].currency)]
					)}</p>`,
				},
				{
					fieldtype: "Check",
					fieldname: "submit",
					label: __("Submit the invoices now"),
					description: __(
						"Leave unticked to create drafts you can check first. Invoices that update stock can only be submitted when the goods are in the warehouse."
					),
				},
			],
			primary_action_label: __("Create"),
			primary_action: (v) => {
				d.hide();
				this.create(todo, v.submit);
			},
		});
		d.show();
	}

	async create(todo, submit) {
		const results = [];
		for (let i = 0; i < todo.length; i++) {
			const o = todo[i];
			frappe.show_progress(__("Creating invoices"), i, todo.length, `${o.name} — ${o.customer_name}`, true);
			const lines = {};
			this.invoice_lines(o).forEach((l) => (lines[l.so_detail] = l.to_invoice));
			let res;
			try {
				res = await frappe.xcall("ls_foods.order_invoicing.create_invoice", {
					sales_order: o.name,
					lines,
					submit: submit ? 1 : 0,
				});
			} catch (e) {
				res = { error: __("Server error — see the Error Log.") };
			}
			results.push({ order: o, ...res });
		}
		frappe.hide_progress();
		this.show_results(results);
		this.load();
	}

	show_results(results) {
		const made = results.filter((r) => r.name).map((r) => r.name);
		const failed = results.filter((r) => !r.name).length;
		const rows = results
			.map(
				(r) => `<tr>
					<td><a href="/app/sales-order/${encodeURIComponent(r.order.name)}" target="_blank">${esc(r.order.name)}</a><br>
						<span class="text-muted">${esc(r.order.customer_name)}</span></td>
					<td>${r.name ? `<a href="/app/sales-invoice/${encodeURIComponent(r.name)}" target="_blank">${esc(r.name)}</a> <span class="text-muted">${esc(__(r.status))}</span>` : ""}</td>
					<td class="text-right">${r.name ? format_currency(r.grand_total, r.order.currency) : ""}</td>
					<td class="text-right">${r.name ? format_currency(r.outstanding, r.order.currency) : ""}</td>
					<td class="text-danger">${esc(r.error || "")}</td>
				</tr>`
			)
			.join("");
		const d = new frappe.ui.Dialog({
			title: __("{0} invoice(s) created", [made.length]) + (failed ? ` · ${__("{0} failed", [failed])}` : ""),
			size: "extra-large",
			fields: [
				{
					fieldtype: "HTML",
					options: `<table class="table table-bordered table-sm">
						<thead><tr><th>${__("Order")}</th><th>${__("Invoice")}</th><th class="text-right">${__("Total")}</th>
						<th class="text-right">${__("Amount Due")}</th><th>${__("Problem")}</th></tr></thead>
						<tbody>${rows}</tbody></table>`,
				},
			],
			primary_action_label: made.length ? __("Download PDFs") : __("Close"),
			primary_action: () => {
				if (!made.length) return d.hide();
				const params = new URLSearchParams({
					doctype: "Sales Invoice",
					name: JSON.stringify(made),
					format: "LS Foods Invoice",
					no_letterhead: 1,
				});
				window.open(`/api/method/frappe.utils.print_format.download_multi_pdf?${params}`);
			},
		});
		if (made.length) {
			d.set_secondary_action_label(__("Open in Invoice List"));
			d.set_secondary_action(() => frappe.set_route("List", "Sales Invoice", { name: ["in", made] }));
		}
		d.show();
	}

	inject_style() {
		if (document.getElementById("lsbo-style")) return;
		$(`<style id="lsbo-style">
			.lsbo { padding-bottom: 40px; }
			.lsbo-section { margin-bottom: 18px; }
			.lsbo-h { font-weight: 600; font-size: var(--text-md); }
			.lsbo-muted { color: var(--text-muted); font-size: var(--text-sm); }
			.lsbo-red-text { color: var(--red-600, #e53e3e); font-weight: 600; }
			.lsbo-bo { margin: 8px 0 6px; background: var(--card-bg); }
			.lsbo-bo td { vertical-align: middle; }
			.lsbo-bo .frappe-control { margin: 0; }
			.lsbo-bo-del { cursor: pointer; font-weight: 700; color: var(--text-muted); }
			.lsbo-bar { display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }
			.lsbo-tools { margin: 4px 0 8px; } .lsbo-tools a { cursor: pointer; }
			.lsbo-lines { background: var(--card-bg); }
			.lsbo-lines td { vertical-align: middle; }
			.lsbo-lines tr.lsbo-order td { background: var(--subtle-fg, #f4f5f6); border-top: 2px solid var(--border-color); }
			.lsbo-lines tr.lsbo-held td { background: var(--red-50, #fff5f5); }
			.lsbo-lines tr.lsbo-skip td { opacity: .5; }
			.lsbo-line-qty { width: 80px; display: inline-block; text-align: right; }
			.lsbo-empty { padding: 40px; text-align: center; color: var(--text-muted); }
			@media (max-width: 768px) { .lsbo-lines, .lsbo-bo { display: block; overflow-x: auto; } }
		</style>`).appendTo("head");
	}
}

function esc(v) {
	return frappe.utils.escape_html(v == null ? "" : String(v));
}

function fmt_qty(v) {
	return String(flt(v, 3));
}
