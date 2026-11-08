import frappe
from frappe import _

from property_management.hierarchy import (
	OwnedDocument,
	assert_non_negative,
	assert_unique,
	copy_owner_from,
	prevent_delete_with_allocation_history,
	refresh_counts_for_bed,
)
from property_management.names import assign_new_name, sync_bed_name


class Bed(OwnedDocument):
	def autoname(self):
		self.bed_number = (self.bed_number or "").strip()
		if not self.area:
			frappe.throw(_("Area is required."))
		area_name, flat = frappe.db.get_value("Area", self.area, ["area_name", "flat"]) or (None, None)
		if not area_name:
			frappe.throw(_("Area {0} was not found.").format(self.area))
		flat_parts = frappe.db.get_value("Flat", flat, ["flat_number", "building"])
		if not flat_parts:
			frappe.throw(_("Flat {0} was not found.").format(flat))
		flat_number, building = flat_parts
		building_name = frappe.db.get_value("Building", building, "building_name")
		assign_new_name(self, building_name, flat_number, area_name, self.bed_number)

	def validate(self):
		if not self.status:
			self.status = "Active"
		if not self.occupancy_status:
			self.occupancy_status = "Vacant"
		self.bed_number = (self.bed_number or "").strip()
		copy_owner_from(self, "Area", self.area)
		parent = frappe.db.get_value("Area", self.area, ["flat", "building"], as_dict=True)
		self.flat = parent.flat
		self.building = parent.building
		assert_unique(
			"Bed",
			"bed_number",
			self.bed_number,
			{"area": self.area},
			self.name,
		)
		assert_non_negative(self, "monthly_rent")
		self._keep_occupancy_consistent()

	def on_update(self):
		sync_bed_name(self)
		refresh_counts_for_bed(self.name)

	def on_trash(self):
		prevent_delete_with_allocation_history(self)

	def after_delete(self):
		from property_management.hierarchy import update_area_counts, update_flat_counts

		update_area_counts(self.area)
		update_flat_counts(self.flat)

	def _keep_occupancy_consistent(self):
		active = None
		if self.name and not self.is_new():
			active = frappe.db.get_value(
				"Bed Allocation",
				{"bed": self.name, "allocation_status": "Active"},
				["name", "tenant", "monthly_rent"],
				as_dict=True,
			)
		if active:
			self.occupancy_status = "Occupied"
			self.current_tenant = active.tenant
			self.current_allocation = active.name
			if active.monthly_rent is not None:
				self.monthly_rent = active.monthly_rent
			return

		if self.occupancy_status == "Occupied":
			frappe.throw(_("Allocate a tenant to mark this bed occupied."))
		if self.occupancy_status not in ("Vacant", "Maintenance"):
			self.occupancy_status = "Vacant"
		self.current_tenant = None
		self.current_allocation = None
