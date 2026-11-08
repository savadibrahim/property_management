import frappe
from frappe.tests.classes.integration_test_case import IntegrationTestCase
from frappe.utils import flt, getdate

from property_management.billing import generate_rent_invoices, revise_rent
from property_management.testing import make_bed_stack, make_property_user, make_tenant, unique_digits

test_records = []


class TestMonthlyBilling(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		settings = frappe.get_single("Property Settings")
		settings.billing_day = 1
		settings.due_days_after_billing = 7
		settings.prorate_partial_months = 1
		settings.save()
		self.owner = make_property_user("Billing Landlord")
		frappe.set_user(self.owner["user"])
		self.building, self.flat, self.area, self.bed = make_bed_stack(unique_digits(6))
		self.tenant = make_tenant("Billed Tenant")

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def allocate(self, start, rent=3100, billing_start=None):
		return frappe.get_doc(
			{
				"doctype": "Bed Allocation",
				"tenant": self.tenant.name,
				"bed": self.bed.name,
				"allocation_status": "Active",
				"allocation_date": start,
				"billing_start_date": billing_start or start,
				"monthly_rent": rent,
				"generate_rent": 1,
			}
		).insert()

	def schedule_for(self, allocation):
		name = frappe.db.get_value("Monthly Revenue", {"bed_allocation": allocation.name}, "name")
		self.assertTrue(name)
		return name

	def invoice_for(self, allocation, billing_month):
		name = frappe.db.get_value(
			"Rent Invoice",
			{"bed_allocation": allocation.name, "billing_month": billing_month, "docstatus": 1},
			"name",
		)
		self.assertTrue(name)
		return frappe.get_doc("Rent Invoice", name)

	def test_catch_up_does_not_repeat(self):
		allocation = self.allocate("2026-01-01", rent=1000)
		schedule = self.schedule_for(allocation)
		first = generate_rent_invoices(as_of="2026-03-15", monthly_revenue=schedule)
		self.assertEqual(first["created"], 3)
		self.assertEqual(first["failed"], 0)
		months = frappe.get_all(
			"Rent Invoice",
			filters={"bed_allocation": allocation.name, "docstatus": 1},
			pluck="billing_month",
			order_by="billing_month asc",
		)
		self.assertEqual(months, ["2026-01", "2026-02", "2026-03"])
		second = generate_rent_invoices(as_of="2026-03-15", monthly_revenue=schedule)
		self.assertEqual(second["created"], 0)
		self.assertGreaterEqual(second["skipped"], 3)
		self.assertEqual(
			frappe.db.count("Rent Invoice", {"bed_allocation": allocation.name, "docstatus": 1}),
			3,
		)

	def test_proration_for_first_and_final_month(self):
		allocation = self.allocate("2026-01-20", rent=3100)
		schedule = self.schedule_for(allocation)
		generate_rent_invoices(as_of="2026-01-31", monthly_revenue=schedule)
		january = self.invoice_for(allocation, "2026-01")
		self.assertEqual(flt(january.rent_amount), flt(3100 * 12 / 31, 2))
		self.assertEqual(getdate(january.due_date), getdate("2026-01-27"))
		allocation.vacate(vacating_date="2026-02-10")
		generate_rent_invoices(as_of="2026-03-31", monthly_revenue=schedule)
		february = self.invoice_for(allocation, "2026-02")
		self.assertEqual(flt(february.rent_amount), flt(3100 * 10 / 28, 2))
		self.assertFalse(
			frappe.db.exists("Rent Invoice", {"bed_allocation": allocation.name, "billing_month": "2026-03"})
		)
		january.reload()
		self.assertEqual(january.docstatus, 1)
		self.assertEqual(flt(january.outstanding), flt(january.rent_amount))

	def test_start_day_clamps_in_february(self):
		allocation = self.allocate("2026-01-31", rent=900)
		schedule = self.schedule_for(allocation)
		generate_rent_invoices(as_of="2026-02-28", monthly_revenue=schedule)
		january = self.invoice_for(allocation, "2026-01")
		february = self.invoice_for(allocation, "2026-02")
		self.assertEqual(getdate(january.billing_date), getdate("2026-01-31"))
		self.assertEqual(getdate(february.billing_date), getdate("2026-02-28"))
		self.assertEqual(getdate(february.due_date), getdate("2026-03-07"))

	def test_invoice_waits_until_the_start_day(self):
		allocation = self.allocate("2026-03-15", rent=800)
		schedule = self.schedule_for(allocation)
		early = generate_rent_invoices(as_of="2026-03-14", monthly_revenue=schedule)
		self.assertEqual(early["created"], 0)
		self.assertFalse(frappe.db.exists("Rent Invoice", {"bed_allocation": allocation.name}))
		opened = generate_rent_invoices(as_of="2026-03-15", monthly_revenue=schedule)
		self.assertEqual(opened["created"], 1)
		self.assertEqual(getdate(self.invoice_for(allocation, "2026-03").billing_date), getdate("2026-03-15"))
		before_april = generate_rent_invoices(as_of="2026-04-14", monthly_revenue=schedule)
		self.assertEqual(before_april["created"], 0)
		april = generate_rent_invoices(as_of="2026-04-15", monthly_revenue=schedule)
		self.assertEqual(april["created"], 1)
		self.assertEqual(getdate(self.invoice_for(allocation, "2026-04").billing_date), getdate("2026-04-15"))

	def test_future_revision_keeps_submitted_invoice(self):
		allocation = self.allocate("2026-01-01", rent=1000)
		schedule = self.schedule_for(allocation)
		generate_rent_invoices(as_of="2026-01-31", monthly_revenue=schedule)
		revise_rent(schedule, "2026-02-01", 2000, remarks="February increase")
		generate_rent_invoices(as_of="2026-02-01", monthly_revenue=schedule)
		january = self.invoice_for(allocation, "2026-01")
		february = self.invoice_for(allocation, "2026-02")
		self.assertEqual(flt(january.rent_amount), 1000)
		self.assertEqual(flt(february.rent_amount), 2000)
		self.assertEqual(len(frappe.get_doc("Monthly Revenue", schedule).revisions), 2)

	def test_turned_off_rent_skips_and_a_failed_period_can_retry(self):
		allocation = self.allocate("2026-01-01", rent=0)
		schedule = self.schedule_for(allocation)
		failed = generate_rent_invoices(as_of="2026-01-31", monthly_revenue=schedule)
		self.assertEqual(failed["created"], 0)
		self.assertEqual(failed["failed"], 1)
		self.assertFalse(frappe.db.exists("Rent Invoice", {"bed_allocation": allocation.name}))
		self.assertTrue(
			frappe.db.exists(
				"Rent Billing Log",
				{"monthly_revenue": schedule, "billing_month": "2026-01", "outcome": "Failed"},
			)
		)
		# The opening revision already uses this date, so correct that row and retry.
		doc = frappe.get_doc("Monthly Revenue", schedule)
		doc.revisions[0].monthly_rent = 1000
		doc.save()
		retried = generate_rent_invoices(as_of="2026-01-31", monthly_revenue=schedule)
		self.assertEqual(retried["created"], 1)
		self.assertEqual(retried["failed"], 0)
		self.assertTrue(frappe.db.exists("Rent Invoice", {"bed_allocation": allocation.name, "docstatus": 1}))

	def test_second_bed_with_generation_off_is_skipped(self):
		second_bed = frappe.get_doc(
			{
				"doctype": "Bed",
				"bed_number": "9",
				"area": self.area.name,
				"status": "Active",
				"occupancy_status": "Vacant",
			}
		).insert()
		allocation = frappe.get_doc(
			{
				"doctype": "Bed Allocation",
				"tenant": self.tenant.name,
				"bed": second_bed.name,
				"allocation_status": "Active",
				"allocation_date": "2026-04-01",
				"billing_start_date": "2026-04-01",
				"monthly_rent": 500,
				"generate_rent": 0,
			}
		).insert()
		self.assertFalse(frappe.db.exists("Monthly Revenue", {"bed_allocation": allocation.name}))
		result = generate_rent_invoices(as_of="2026-04-30")
		self.assertEqual(result["created"], 0)
		self.assertFalse(frappe.db.exists("Rent Invoice", {"bed_allocation": allocation.name}))

	def test_duplicate_period_is_rejected(self):
		allocation = self.allocate("2026-01-01", rent=1000)
		schedule = self.schedule_for(allocation)
		generate_rent_invoices(as_of="2026-01-31", monthly_revenue=schedule)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Rent Invoice",
					"tenant": self.tenant.name,
					"bed_allocation": allocation.name,
					"billing_month": "2026-01",
					"billing_date": "2026-01-01",
					"due_date": "2026-01-08",
					"rent_amount": 1000,
				}
			).insert()

	def test_other_user_cannot_generate_or_open_the_schedule(self):
		allocation = self.allocate("2026-01-01", rent=1000)
		schedule = self.schedule_for(allocation)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			generate_rent_invoices(monthly_revenue=schedule)
		frappe.set_user("Administrator")
		other = make_property_user("Other Billing User")
		frappe.set_user(other["user"])
		with self.assertRaises(frappe.PermissionError):
			generate_rent_invoices(monthly_revenue=schedule)
		with self.assertRaises(frappe.PermissionError):
			revise_rent(schedule, "2026-05-01", 50)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Monthly Revenue", schedule)
		self.assertFalse(frappe.db.exists("Rent Invoice", {"bed_allocation": allocation.name}))
