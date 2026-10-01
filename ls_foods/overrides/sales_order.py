"""LS Foods — a Sales Order may be saved with no Delivery Date at all.

ERPNext insists on one: ``SalesOrder.validate_delivery_date`` throws "Please
enter Delivery Date" when Order Type is Sales and neither the header nor any
row carries a date. Neither field is marked mandatory, so no Property Setter
reaches it, and a ``doc_events`` hook cannot stop a throw raised inside the
controller's own ``validate`` — hence a class override, kept to that one method.

The alternative ERPNext offers, ticking *Skip Delivery Note*, also lets the date
go — but it takes the order out of delivery tracking (status "To Bill", no
Delivery Note button). The client's orders are still delivered, so the override
only removes the demand for a date and leaves everything else standard.

When a date IS entered, anywhere, the standard method runs untouched: header
and rows are kept in step and a date before the order date is still refused.
The matching form-side switch is in ``public/js/sales_order.js``.
"""

from erpnext.selling.doctype.sales_order.sales_order import SalesOrder


class LSFoodsSalesOrder(SalesOrder):
	def validate_delivery_date(self):
		if self.delivery_date or any(row.delivery_date for row in self.get("items")):
			return super().validate_delivery_date()

		# The standard method finishes with this check; keep it.
		self.validate_sales_mntc_quotation()
