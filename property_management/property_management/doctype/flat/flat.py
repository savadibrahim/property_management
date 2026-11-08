import frappe
from frappe import _

from property_management.hierarchy import (
	OwnedDocument,
	assert_unique,
	copy_owner_from,
	prevent_delete_with_allocation_history,
	update_flat_counts,
)
from property_management.names import assign_new_name, sync_flat_tree


class Flat(OwnedDocument):
	def autoname(self):
		self.flat_number = (self.flat_number or "").strip()
		if not self.building:
			frappe.throw(_("Building is required."))
		building_name = frappe.db.get_value("Building", self.building, "building_name")
		if not building_name:
			frappe.throw(_("Building {0} was not found.").format(self.building))
		assign_new_name(self, building_name, self.flat_number)

	def validate(self):
		if not self.status:
			self.status = "Active"
		self.flat_number = (self.flat_number or "").strip()
		copy_owner_from(self, "Building", self.building)
		assert_unique(
			"Flat",
			"flat_number",
			self.flat_number,
			{"building": self.building},
			self.name,
		)

	def on_update(self):
		sync_flat_tree(self)
		update_flat_counts(self.name)

	def on_trash(self):
		prevent_delete_with_allocation_history(self)
