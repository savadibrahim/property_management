import frappe
from frappe import _
from frappe.utils import getdate, today

from property_management.hierarchy import (
	OwnedDocument,
	assert_non_negative,
	assert_status_active,
	copy_owner_from,
	refresh_tenant_status,
	sync_bed_occupancy,
)


class BedAllocation(OwnedDocument):
	def validate(self):
		if not self.allocation_status:
			self.allocation_status = "Active"
		self._reject_reopening()
		copy_owner_from(self, "Bed", self.bed)
		bed = frappe.db.get_value(
			"Bed",
			self.bed,
			["area", "flat", "building", "status", "occupancy_status"],
			as_dict=True,
		)
		self.area = bed.area
		self.flat = bed.flat
		self.building = bed.building

		self._validate_tenant()
		self._validate_dates()
		assert_non_negative(self, "monthly_rent", "deposit_amount")

		if self.allocation_status == "Active":
			if self.generate_rent is None:
				self.generate_rent = 1
			self._validate_active_allocation(bed)
		elif self.allocation_status == "Vacated":
			if not self.vacating_date:
				frappe.throw(_("Vacating Date is required."))
			# Stop future rent. Historical monthly_rent and deposit_amount stay on this row.
			# TODO Phase 4–5: do not write off receivables when Generate Rent is turned off.
			self.generate_rent = 0
		else:
			frappe.throw(_("Allocation Status must be Active or Vacated."))

	def on_update(self):
		sync_bed_occupancy(self.bed)
		refresh_tenant_status(self.tenant)
		from property_management.billing import sync_monthly_revenue
		from property_management.finance import sync_tenant_deposit

		sync_monthly_revenue(self)
		sync_tenant_deposit(self)

	def on_trash(self):
		frappe.throw(
			_(
				"Bed allocations stay on record so vacating a bed does not erase rent or deposit figures. Vacate the allocation instead of deleting it."
			)
		)

	@frappe.whitelist(methods=["POST"])
	def vacate(self, vacating_date=None):
		"""Close occupancy and keep this row.

		The bed becomes Vacant and loses Current Tenant and Current Allocation.
		Generate Rent is turned off so a later billing run skips this row.
		TODO Phase 4–5: do not write off receivables or zero deposit_amount / monthly_rent.
		"""
		self.check_permission("write")
		if self.allocation_status != "Active":
			frappe.throw(_("Only an active allocation can be vacated."))
		if not vacating_date:
			frappe.throw(_("Vacating Date is required."))
		# Outstanding rent invoices and financial transactions stay as they are.
		# TODO Phase 5: do not write off receivables here. Payments and explicit
		# receivable adjustments are the only ways to change an invoice balance.
		from property_management.finance import leave_receivables_unchanged

		leave_receivables_unchanged(self.name)
		self.allocation_status = "Vacated"
		self.vacating_date = getdate(vacating_date)
		self.generate_rent = 0
		self.save()
		return {
			"name": self.name,
			"allocation_status": self.allocation_status,
			"vacating_date": str(self.vacating_date),
			"bed": self.bed,
			"generate_rent": 0,
		}

	def _reject_reopening(self):
		if self.is_new() or not self.name:
			return
		previous = frappe.db.get_value("Bed Allocation", self.name, "allocation_status")
		if previous == "Vacated" and self.allocation_status == "Active":
			frappe.throw(
				_("A vacated allocation stays on record. Create a new allocation to place the tenant again.")
			)

	def _validate_tenant(self):
		if not self.tenant:
			frappe.throw(_("Tenant is required"))
		if not frappe.has_permission("Tenant", "read", self.tenant):
			frappe.throw(_("Tenant {0} is not available.").format(self.tenant), frappe.PermissionError)
		tenant_owner, tenant_status = frappe.db.get_value("Tenant", self.tenant, ["owner_user", "status"])
		if tenant_owner != self.owner_user:
			frappe.throw(_("The tenant belongs to another user."), frappe.PermissionError)
		if tenant_status == "Inactive":
			frappe.throw(_("Tenant {0} is inactive.").format(self.tenant))

	def _validate_dates(self):
		if self.allocation_date:
			self.allocation_date = getdate(self.allocation_date)
		else:
			self.allocation_date = today()
		if self.billing_start_date:
			self.billing_start_date = getdate(self.billing_start_date)
		if self.vacating_date:
			self.vacating_date = getdate(self.vacating_date)
			if self.allocation_date and self.vacating_date < self.allocation_date:
				frappe.throw(_("Vacating Date cannot be before Allocation Date."))

	def _validate_active_allocation(self, bed):
		if self.vacating_date:
			frappe.throw(_("Clear Vacating Date or set Allocation Status to Vacated."))
		if bed.status != "Active":
			frappe.throw(_("Bed {0} is not active.").format(self.bed))
		assert_status_active("Area", self.area)
		assert_status_active("Flat", self.flat)
		assert_status_active("Building", self.building)

		current_occupancy = bed.occupancy_status or "Vacant"
		if not self._is_same_active_row() and current_occupancy != "Vacant":
			frappe.throw(
				_("Bed {0} is {1}. Only a vacant bed can take a tenant.").format(
					self.bed, current_occupancy
				)
			)

		other_bed = frappe.db.get_value(
			"Bed Allocation",
			{"bed": self.bed, "allocation_status": "Active", "name": ["!=", self.name]},
			"name",
		)
		if other_bed:
			frappe.throw(_("Bed {0} already has an active allocation ({1}).").format(self.bed, other_bed))

		other_tenant = frappe.db.get_value(
			"Bed Allocation",
			{"tenant": self.tenant, "allocation_status": "Active", "name": ["!=", self.name]},
			"name",
		)
		if other_tenant:
			frappe.throw(
				_("Tenant {0} already has an active allocation ({1}).").format(self.tenant, other_tenant)
			)

		if not self.is_new():
			previous_bed, previous_tenant = frappe.db.get_value(
				"Bed Allocation", self.name, ["bed", "tenant"]
			)
			if previous_bed and previous_bed != self.bed:
				frappe.throw(_("Bed cannot be changed. Vacate this allocation and create another."))
			if previous_tenant and previous_tenant != self.tenant:
				frappe.throw(_("Tenant cannot be changed. Vacate this allocation and create another."))

	def _is_same_active_row(self):
		if self.is_new() or not self.name:
			return False
		return (
			frappe.db.get_value("Bed Allocation", self.name, "allocation_status") == "Active"
		)
