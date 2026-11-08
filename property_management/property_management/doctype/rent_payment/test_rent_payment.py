import frappe
from frappe.tests.classes.integration_test_case import IntegrationTestCase
from frappe.utils import flt

from property_management.finance import apply_invoice_allocation
from property_management.property_management.doctype.rent_payment.rent_payment import open_invoices
from property_management.testing import (
	make_allocation,
	make_bed_stack,
	make_property_user,
	make_tenant,
	unique_digits,
)

test_records = []


class TestRentPayment(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.owner = make_property_user("Payment Landlord")
		frappe.set_user(self.owner["user"])
		self.building, self.flat, self.area, self.bed = make_bed_stack(unique_digits(6))
		self.tenant = make_tenant("Paying Tenant")
		self.allocation = make_allocation(self.bed.name, self.tenant.name, monthly_rent=1000, deposit_amount=0)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def make_invoice(self, rent, month, billing_date):
		invoice = frappe.get_doc(
			{
				"doctype": "Rent Invoice",
				"tenant": self.tenant.name,
				"bed_allocation": self.allocation.name,
				"billing_month": month,
				"billing_date": billing_date,
				"due_date": billing_date,
				"rent_amount": rent,
			}
		).insert()
		invoice.submit()
		return invoice

	def test_open_invoices_use_the_amount_still_due(self):
		first = self.make_invoice(1000, "2026-10", "2026-10-01")
		second = self.make_invoice(800, "2026-11", "2026-11-01")
		rows = open_invoices(self.tenant.name)
		self.assertEqual([row.name for row in rows], [first.name, second.name])
		self.assertEqual(flt(rows[0].outstanding), 1000)
		self.assertEqual(flt(rows[1].outstanding), 800)

		apply_invoice_allocation(first.name, 400)
		rows = open_invoices(self.tenant.name)
		self.assertEqual([row.name for row in rows], [first.name, second.name])
		self.assertEqual(flt(rows[0].outstanding), 600)
		self.assertEqual(flt(rows[1].outstanding), 800)

		apply_invoice_allocation(first.name, 600)
		rows = open_invoices(self.tenant.name)
		self.assertEqual([row.name for row in rows], [second.name])
		self.assertEqual(flt(rows[0].outstanding), 800)
