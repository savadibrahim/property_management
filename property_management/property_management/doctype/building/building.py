import frappe
from frappe import _

from property_management.hierarchy import (
	OwnedDocument,
	apply_owner,
	prevent_delete_with_allocation_history,
)
from property_management.names import assign_new_name, sync_building_tree


class Building(OwnedDocument):
	def autoname(self):
		self.building_name = (self.building_name or "").strip()
		assign_new_name(self, self.building_name)

	def validate(self):
		if not self.status:
			self.status = "Active"
		self.building_name = (self.building_name or "").strip()
		apply_owner(self)

	def on_update(self):
		sync_building_tree(self)

	def on_trash(self):
		prevent_delete_with_allocation_history(self)
