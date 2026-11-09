import frappe
from frappe.tests.classes.integration_test_case import IntegrationTestCase
from frappe.utils import cint, flt, today

from property_management.testing import make_allocation, make_bed_stack, make_property_user, make_tenant, unique_digits

test_records = []


class TestBedAllocation(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.owner = make_property_user("Landlord")
		frappe.set_user(self.owner["user"])
		self.building, self.flat, self.area, self.bed = make_bed_stack(unique_digits(6))

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_second_active_allocation_is_rejected(self):
		first_tenant = make_tenant("First Tenant")
		make_allocation(self.bed.name, first_tenant.name)
		# Even if occupancy was forced back to Vacant, a second active row is refused.
		frappe.db.set_value("Bed", self.bed.name, "occupancy_status", "Vacant", update_modified=False)

		second_tenant = make_tenant("Second Tenant")
		with self.assertRaises(frappe.ValidationError):
			make_allocation(self.bed.name, second_tenant.name)

		active = frappe.get_all(
			"Bed Allocation",
			filters={"bed": self.bed.name, "allocation_status": "Active"},
			pluck="name",
		)
		self.assertEqual(len(active), 1)

	def test_inactive_area_or_flat_blocks_allocation(self):
		tenant = make_tenant("Waiting Tenant")
		self.area.status = "Inactive"
		self.area.save()
		with self.assertRaises(frappe.ValidationError):
			make_allocation(self.bed.name, tenant.name)

		self.area.status = "Active"
		self.area.save()
		self.flat.status = "Inactive"
		self.flat.save()
		with self.assertRaises(frappe.ValidationError):
			make_allocation(self.bed.name, tenant.name)

	def test_vacate_frees_bed_and_keeps_amounts(self):
		tenant = make_tenant("Leaving Tenant")
		allocation = make_allocation(self.bed.name, tenant.name, monthly_rent=1800, deposit_amount=750)
		self.bed.reload()
		self.assertEqual(self.bed.occupancy_status, "Occupied")
		self.assertEqual(self.bed.current_tenant, tenant.name)

		with self.assertRaises(frappe.ValidationError):
			allocation.vacate()

		allocation.vacate(vacating_date=today())
		allocation.reload()
		self.bed.reload()
		tenant.reload()

		self.assertEqual(allocation.allocation_status, "Vacated")
		self.assertEqual(str(allocation.vacating_date), str(today()))
		self.assertEqual(cint(allocation.generate_rent), 0)
		self.assertEqual(flt(allocation.monthly_rent), 1800)
		self.assertEqual(flt(allocation.deposit_amount), 750)
		self.assertTrue(frappe.db.exists("Bed Allocation", allocation.name))
		self.assertEqual(self.bed.occupancy_status, "Vacant")
		self.assertFalse(self.bed.current_tenant)
		self.assertFalse(self.bed.current_allocation)
		self.assertEqual(tenant.status, "Vacated")
		self.assertFalse(tenant.current_bed)

		replacement = make_tenant("Next Tenant")
		again = make_allocation(self.bed.name, replacement.name)
		self.bed.reload()
		self.assertEqual(again.allocation_status, "Active")
		self.assertEqual(self.bed.occupancy_status, "Occupied")
		self.assertEqual(self.bed.current_tenant, replacement.name)
		self.assertEqual(self.bed.current_allocation, again.name)

	def test_maintenance_bed_cannot_be_allocated(self):
		self.bed.occupancy_status = "Maintenance"
		self.bed.save()
		tenant = make_tenant("Maintenance Tenant")
		with self.assertRaises(frappe.ValidationError):
			make_allocation(self.bed.name, tenant.name)

	def test_moving_a_tenant_keeps_both_allocations(self):
		tenant = make_tenant("Moving Tenant")
		first = make_allocation(self.bed.name, tenant.name, monthly_rent=1000, deposit_amount=200)
		first.vacate(vacating_date=today())
		second_bed = frappe.get_doc(
			{
				"doctype": "Bed",
				"bed_number": "2",
				"area": self.area.name,
				"status": "Active",
				"occupancy_status": "Vacant",
			}
		).insert()
		second = make_allocation(second_bed.name, tenant.name, monthly_rent=1100, deposit_amount=200)

		history = frappe.get_all(
			"Bed Allocation",
			filters={"tenant": tenant.name},
			fields=["name", "allocation_status", "bed"],
		)
		self.assertEqual(len(history), 2)
		first.reload()
		second_bed.reload()
		tenant.reload()
		self.assertEqual(first.allocation_status, "Vacated")
		self.assertEqual(cint(first.generate_rent), 0)
		self.assertEqual(second.allocation_status, "Active")
		self.assertEqual(second_bed.occupancy_status, "Occupied")
		self.assertEqual(second_bed.current_allocation, second.name)
		self.assertEqual(tenant.status, "Active")
		self.assertEqual(tenant.current_bed, second_bed.name)
		self.bed.reload()
		self.assertEqual(self.bed.occupancy_status, "Vacant")
		self.assertFalse(self.bed.current_allocation)

		with self.assertRaises(frappe.ValidationError):
			first.reload()
			first.allocation_status = "Active"
			first.vacating_date = None
			first.save()

	def test_allocation_history_blocks_delete(self):
		tenant = make_tenant("Kept Tenant")
		allocation = make_allocation(self.bed.name, tenant.name)
		# Property User has Delete on the hierarchy, so the on_trash guards run.
		for doc in (self.building, self.flat, self.area, self.bed, tenant):
			with self.assertRaises(frappe.ValidationError):
				doc.delete()
		# Bed Allocation grants no Delete permission, so the role check fails first.
		with self.assertRaises(frappe.PermissionError):
			allocation.delete()
		# A user who bypasses that role check still cannot remove the history row.
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Bed Allocation", allocation.name).delete()

	def test_allocation_creates_tenant_deposit_when_deposit_amount_is_set(self):
		tenant = make_tenant("Deposit Tenant")
		allocation = make_allocation(self.bed.name, tenant.name, monthly_rent=1500, deposit_amount=500)
		deposits = frappe.get_all(
			"Tenant Deposit",
			filters={"bed_allocation": allocation.name},
			fields=[
				"name",
				"tenant",
				"tenant_name",
				"owner_user",
				"building",
				"flat",
				"area",
				"bed",
				"status",
				"deposit_due",
				"balance",
			],
		)
		self.assertEqual(len(deposits), 1)
		self.assertEqual(deposits[0].tenant, tenant.name)
		self.assertEqual(deposits[0].tenant_name, "Deposit Tenant")
		self.assertEqual(frappe.get_meta("Tenant Deposit").show_title_field_in_link, 1)
		self.assertEqual(frappe.get_meta("Tenant Deposit").title_field, "tenant_name")
		self.assertEqual(deposits[0].owner_user, self.owner["user"])
		self.assertEqual(deposits[0].building, self.building.name)
		self.assertEqual(deposits[0].flat, self.flat.name)
		self.assertEqual(deposits[0].area, self.area.name)
		self.assertEqual(deposits[0].bed, self.bed.name)
		self.assertEqual(deposits[0].status, "Active")
		self.assertEqual(flt(deposits[0].deposit_due), 500)
		self.assertEqual(flt(deposits[0].balance), 0)

		allocation.deposit_amount = 750
		allocation.remarks = "Updated remarks"
		allocation.save()
		self.assertEqual(frappe.db.count("Tenant Deposit", {"bed_allocation": allocation.name}), 1)
		self.assertEqual(
			flt(frappe.db.get_value("Tenant Deposit", deposits[0].name, "deposit_due")),
			750,
		)

		second_bed = frappe.get_doc(
			{
				"doctype": "Bed",
				"bed_number": "3",
				"area": self.area.name,
				"status": "Active",
				"occupancy_status": "Vacant",
			}
		).insert()
		no_deposit_tenant = make_tenant("No Deposit Tenant")
		zero_allocation = make_allocation(
			second_bed.name, no_deposit_tenant.name, monthly_rent=1200, deposit_amount=0
		)
		self.assertFalse(frappe.db.exists("Tenant Deposit", {"bed_allocation": zero_allocation.name}))

	def test_property_user_cannot_open_another_users_tenant_or_allocation(self):
		frappe.set_user("Administrator")
		other = make_property_user("Other Landlord")
		frappe.set_user(other["user"])
		_building, _flat, _area, bed = make_bed_stack(unique_digits(6))
		tenant = make_tenant("Hidden Tenant")
		allocation = make_allocation(bed.name, tenant.name)

		frappe.set_user(self.owner["user"])
		self.assertEqual(frappe.get_list("Tenant", filters={"name": tenant.name}, pluck="name"), [])
		self.assertFalse(frappe.has_permission("Tenant", "read", tenant.name))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Tenant", tenant.name)
		self.assertEqual(
			frappe.get_list("Bed Allocation", filters={"name": allocation.name}, pluck="name"),
			[],
		)
		self.assertFalse(frappe.has_permission("Bed Allocation", "read", allocation.name))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Bed Allocation", allocation.name)
