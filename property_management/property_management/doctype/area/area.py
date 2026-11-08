import frappe
from frappe import _

from property_management.hierarchy import (
	OwnedDocument,
	assert_unique,
	copy_owner_from,
	prevent_delete_with_allocation_history,
	update_area_counts,
	update_flat_counts,
)
from property_management.names import assign_new_name, sync_area_tree


class Area(OwnedDocument):
	def autoname(self):
		self.area_name = (self.area_name or "").strip()
		if not self.flat:
			frappe.throw(_("Flat is required."))
		flat_number, building = frappe.db.get_value("Flat", self.flat, ["flat_number", "building"]) or (
			None,
			None,
		)
		if not flat_number:
			frappe.throw(_("Flat {0} was not found.").format(self.flat))
		building_name = frappe.db.get_value("Building", building, "building_name")
		assign_new_name(self, building_name, flat_number, self.area_name)

	def validate(self):
		if not self.status:
			self.status = "Active"
		self.area_name = (self.area_name or "").strip()
		copy_owner_from(self, "Flat", self.flat)
		self.building = frappe.db.get_value("Flat", self.flat, "building")
		if not (self.area_code or "").strip():
			self.area_code = self.area_name
		assert_unique(
			"Area",
			"area_name",
			self.area_name,
			{"flat": self.flat},
			self.name,
		)

	def on_update(self):
		sync_area_tree(self)
		update_area_counts(self.name)
		update_flat_counts(self.flat)

	def on_trash(self):
		prevent_delete_with_allocation_history(self)

	def after_delete(self):
		update_flat_counts(self.flat)
