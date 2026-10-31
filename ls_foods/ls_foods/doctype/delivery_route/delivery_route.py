"""Delivery Route — the print order of a day's deliveries.

Staff build the route outside ERPNext (OptimoRoute Report → routing →
spreadsheet), then paste the spreadsheet's Order ID column here, in delivery
order. The route lists each order with the invoice that goes on the truck, and
"Download Invoices PDF" gives one PDF of those invoices, one invoice per page
(each starts on a new sheet), in exactly the pasted order.

One route per date and vehicle (it is the record's name). When the route
changes, the new list is pasted over the old one on the same record; that is
what the old screen's "All deliveries scheduled for this date will be deleted!"
did, without anything being deleted here.

Which invoice: an order with one invoice (not cancelled, not a return, draft or
submitted) prints it. An order with several (backorders) is listed in the "Orders
With Several Invoices" table and staff tick which to include; several may be
ticked, and they print oldest first. Nothing is guessed: the dates cannot say
which one belongs on the truck, so the PDF waits until each such order has a
choice. A tick lasts while the order's invoices stay the same; when a new invoice
appears on the order, the choice is asked for again.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, flt, getdate

PRINT_FORMAT = "LS Foods Invoice"

# Spreadsheet header cells that come along when the whole column is copied.
HEADERS = {"orderid", "order id", "order ids", "order", "sales order", "sales order no", "name", "id"}


class DeliveryRoute(Document):
	def autoname(self):
		self.vehicle = cstr(self.vehicle).strip()
		self.name = f"{self.route_date} {self.vehicle}".strip()
		if frappe.db.exists("Delivery Route", self.name):
			frappe.throw(
				_("There is already a route for {0}. Open it and paste the new list there.").format(
					frappe.bold(self.name)
				),
				title=_("Route Exists"),
			)

	def validate(self):
		orders = parse_order_ids(self.order_ids)
		if not orders:
			frappe.throw(_("Paste at least one Sales Order No."))
		self.order_ids = "\n".join(orders)
		self.build_stops(orders)

	def build_stops(self, orders):
		"""Rebuild the stops and invoice choices from the pasted list, keeping Print and Include ticks."""
		kept = {s.sales_order: s for s in self.stops if s.sales_order}
		ticks = {}
		for row in self.invoice_choices:
			ticks.setdefault(row.sales_order, {})[row.sales_invoice] = cint(row.include)
		seen_orders, seen_invoices = {}, {}
		self.stops, self.invoice_choices = [], []

		for typed in orders:
			stop = self.append("stops", {"print_invoice": 0})
			if typed in seen_orders:
				stop.note = _("{0} is listed twice (stop {1})").format(typed, seen_orders[typed])
				continue

			so, note = resolve_order(typed)
			if not so:
				stop.note = note
				continue
			seen_orders[typed] = seen_orders[so.name] = stop.idx
			stop.sales_order, stop.customer_name = so.name, so.customer_name

			invoices = order_invoices(so.name)
			if not invoices:
				stop.note = note or _("No invoice yet")
				continue

			prev = kept.get(so.name)
			stop.print_invoice = (
				cint(prev.print_invoice) if prev and (prev.sales_invoice or so.name in ticks) else 1
			)
			chosen = invoices if len(invoices) == 1 else self.add_choices(so, invoices, ticks.get(so.name))
			self.fill_stop(stop, chosen, len(invoices), note, seen_invoices)

		self.total_orders = len([s for s in self.stops if s.sales_order])
		self.invoices_to_print = len(self.invoices_in_print_order())

	def add_choices(self, so, invoices, ticks):
		"""List an order's invoices for staff to tick; returns the ticked ones."""
		# A new invoice on the order means the earlier choice was made without it.
		ticks = ticks if ticks and set(ticks) == {i.name for i in invoices} else {}
		chosen = []
		for invoice in invoices:
			include = ticks.get(invoice.name, 0)
			self.append(
				"invoice_choices",
				{
					"sales_order": so.name,
					"customer_name": so.customer_name,
					"sales_invoice": invoice.name,
					"created_on": getdate(invoice.creation),
					"invoice_status": status_label(invoice),
					"grand_total": invoice_total(invoice),
					"include": include,
				},
			)
			if include:
				chosen.append(invoice)
		return chosen

	def fill_stop(self, stop, chosen, invoice_count, note, seen_invoices):
		notes = [note] if note else []
		if len(chosen) == 1:
			stop.sales_invoice = chosen[0].name
			stop.invoice_status = status_label(chosen[0])
		stop.grand_total = sum(invoice_total(i) for i in chosen)

		if invoice_count > 1:
			if chosen:
				notes.append(
					_("{0} of {1} invoices chosen: {2}").format(
						len(chosen), invoice_count, ", ".join(i.name for i in chosen)
					)
				)
			else:
				notes.append(_("{0} invoices: choose below").format(invoice_count))

		repeats = [i.name for i in chosen if i.name in seen_invoices]
		if chosen and len(repeats) == len(chosen):
			# One invoice covering two listed orders is printed once.
			stop.print_invoice = 0
		for invoice in repeats:
			notes.append(_("{0} is also on stop {1}").format(invoice, seen_invoices[invoice]))
		for invoice in chosen:
			seen_invoices.setdefault(invoice.name, stop.idx)
		stop.note = "; ".join(notes)

	def ticked_invoices(self):
		ticked = {}
		for row in self.invoice_choices:
			if row.include:
				ticked.setdefault(row.sales_order, []).append(row.sales_invoice)
		return ticked

	def invoices_in_print_order(self):
		"""The invoices the PDF holds, in stop order; one on two stops prints once."""
		ticked = self.ticked_invoices()
		invoices = []
		for stop in self.stops:
			if not stop.print_invoice:
				continue
			for invoice in ticked.get(stop.sales_order) or ([stop.sales_invoice] if stop.sales_invoice else []):
				if invoice not in invoices:
					invoices.append(invoice)
		return invoices

	def orders_awaiting_choice(self):
		"""Orders set to print whose several invoices have none ticked."""
		listed = {row.sales_order for row in self.invoice_choices}
		ticked = self.ticked_invoices()
		return [
			s.sales_order
			for s in self.stops
			if s.print_invoice and s.sales_order in listed and s.sales_order not in ticked
		]

	def state(self):
		"""What the screen shows, to tell whether a rebuild changed anything."""
		return (
			[
				(s.sales_order, s.customer_name, s.sales_invoice, s.invoice_status, flt(s.grand_total, 2),
				 cint(s.print_invoice), s.note or "")
				for s in self.stops
			],
			[
				(c.sales_order, c.sales_invoice, cstr(c.created_on), c.invoice_status, flt(c.grand_total, 2),
				 cint(c.include))
				for c in self.invoice_choices
			],
		)


def parse_order_ids(text):
	"""Order numbers from pasted text, in order: first cell of each line, headers dropped."""
	out = []
	for line in cstr(text).splitlines():
		cell = re.split(r"[\t,;]", line, maxsplit=1)[0].strip().strip("\"'").strip()
		if cell and cell.lower() not in HEADERS:
			out.append(cell.upper() if cell.lower().startswith("sal-ord") else cell)
	return out


def resolve_order(name):
	"""(Sales Order row, note). A cancelled order is followed to its amendment."""
	so = frappe.db.get_value(
		"Sales Order", name, ["name", "customer_name", "docstatus"], as_dict=True
	)
	if not so:
		return None, _("{0}: no such Sales Order").format(name)
	note = ""
	while so.docstatus == 2:
		amended = frappe.db.get_value(
			"Sales Order", {"amended_from": so.name}, ["name", "customer_name", "docstatus"], as_dict=True
		)
		if not amended:
			return None, _("{0} is cancelled").format(name)
		so, note = amended, _("{0} was cancelled, amended as {1}").format(name, amended.name)
	return so, note


def order_invoices(sales_order):
	"""The order's invoices that can go on the truck, oldest first."""
	parents = frappe.get_all(
		"Sales Invoice Item",
		filters={"sales_order": sales_order, "parenttype": "Sales Invoice", "docstatus": ["<", 2]},
		pluck="parent",
		distinct=True,
	)
	if not parents:
		return []
	return frappe.get_all(
		"Sales Invoice",
		filters={"name": ["in", parents], "docstatus": ["<", 2], "is_return": 0},
		fields=["name", "docstatus", "grand_total", "rounded_total", "creation"],
		order_by="creation asc",
	)


def status_label(invoice):
	return _("Submitted") if invoice.docstatus == 1 else _("Draft")


def invoice_total(invoice):
	return flt(invoice.rounded_total or invoice.grand_total)


@frappe.whitelist(methods=["POST"])
def refresh_route(name):
	"""Pick up invoices made since the last save, without needing a change on the form.

	Saves only when something moved, so downloading the same route again and again
	leaves the record as it is.
	"""
	route = frappe.get_doc("Delivery Route", name)
	route.check_permission("read")
	before = route.state()
	route.build_stops(parse_order_ids(route.order_ids))
	changed = route.state() != before
	if changed and route.has_permission("write"):
		route.save()
	return {
		"changed": changed,
		"awaiting_choice": route.orders_awaiting_choice(),
		"invoices": len(route.invoices_in_print_order()),
	}


@frappe.whitelist()
def download_invoices_pdf(name):
	"""One PDF of the route's ticked invoices, in stop order, each starting on a new page."""
	from frappe.utils.pdf import get_pdf
	from frappe.www.printview import get_print_style, get_rendered_template

	route = frappe.get_doc("Delivery Route", name)
	route.check_permission("read")
	awaiting = route.orders_awaiting_choice()
	if awaiting:
		frappe.throw(_("Choose the invoice to include for: {0}").format(", ".join(awaiting)))
	invoices = route.invoices_in_print_order()
	if not invoices:
		frappe.throw(_("No invoices to print on this route."))

	# All invoices go into ONE html page, each in its own block that starts a
	# new sheet, and wkhtmltopdf runs once. (Printing them one by one and
	# joining the PDFs takes a few seconds per invoice: a full route would run
	# past the request time limit.)
	print_format = frappe.get_doc("Print Format", PRINT_FORMAT)
	meta = frappe.get_meta("Sales Invoice")
	bodies = []
	for invoice in invoices:
		doc = frappe.get_doc("Sales Invoice", invoice)
		doc.check_permission("print")
		bodies.append(get_rendered_template(doc, print_format=print_format, meta=meta, no_letterhead=1))
	body = "".join(
		f'<div class="ls-route-invoice" style="page-break-before: {"always" if i else "auto"}">{b}</div>'
		for i, b in enumerate(bodies)
	)
	html = frappe.render_template(
		"frappe/www/printview.html",
		{
			"body": body,
			"print_style": get_print_style(None, print_format),
			"title": _("Route {0}").format(route.name),
			"lang": frappe.local.lang,
			"layout_direction": "ltr",
		},
	)

	frappe.local.response.filename = f"Route {route.name} Invoices.pdf"
	frappe.local.response.filecontent = get_pdf(html)
	frappe.local.response.type = "pdf"
