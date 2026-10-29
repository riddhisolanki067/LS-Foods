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

Which invoice: the order's last CREATED invoice that is not cancelled and not
a return, draft or submitted. An order with several invoices (backorders: the
first invoice went out earlier, the later one carries what was held back) prints
only that last one. Creation, not posting date: a draft's posting date moves to
the day it is opened again, so an old draft can look newer than the backorder
invoice. The stops are rebuilt on every save, so a new invoice is picked up.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, cstr, flt

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
		"""Rebuild the stops from the pasted list, keeping the Print ticks."""
		kept = {s.sales_order: s for s in self.stops if s.sales_order and s.sales_invoice}
		seen_orders, seen_invoices = {}, {}
		self.stops = []

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
			chosen = invoices[0]
			stop.sales_invoice = chosen.name
			stop.invoice_status = _("Submitted") if chosen.docstatus == 1 else _("Draft")
			stop.grand_total = flt(chosen.rounded_total or chosen.grand_total)
			stop.print_invoice = cint(prev.print_invoice) if prev else 1

			notes = [note] if note else []
			if len(invoices) > 1:
				notes.append(_("{0} invoices on this order, printing the last one").format(len(invoices)))
			if chosen.name in seen_invoices:
				# One invoice covering two listed orders is printed once.
				stop.print_invoice = 0
				notes.append(_("Same invoice as stop {0}").format(seen_invoices[chosen.name]))
			else:
				seen_invoices[chosen.name] = stop.idx
			stop.note = "; ".join(notes)

		self.total_orders = len([s for s in self.stops if s.sales_order])
		self.invoices_to_print = len([s for s in self.stops if s.sales_invoice and s.print_invoice])


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
	"""The order's invoices that can go on the truck, last created first."""
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
		fields=["name", "docstatus", "grand_total", "rounded_total"],
		order_by="creation desc",
	)


@frappe.whitelist()
def download_invoices_pdf(name):
	"""One PDF of the route's ticked invoices, in stop order, each starting on a new page."""
	from frappe.utils.pdf import get_pdf
	from frappe.www.printview import get_print_style, get_rendered_template

	route = frappe.get_doc("Delivery Route", name)
	route.check_permission("read")
	invoices = [s.sales_invoice for s in route.stops if s.sales_invoice and s.print_invoice]
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
