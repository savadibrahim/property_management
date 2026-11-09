import frappe
from frappe import _

from property_management.auth import normalize_mobile
from property_management.hierarchy import (
	OwnedDocument,
	apply_owner,
	assert_unique,
	prevent_delete_with_allocation_history,
)


class Tenant(OwnedDocument):
	def validate(self):
		if not self.status:
			self.status = "Active"
		apply_owner(self)
		self.mobile = normalize_mobile(self.mobile)
		self.identification_number = (self.identification_number or "").strip()
		if not self.identification_number:
			frappe.throw(_("Identification Number is required."))
		assert_unique(
			"Tenant",
			"mobile",
			self.mobile,
			{"owner_user": self.owner_user},
			self.name,
		)
		assert_unique(
			"Tenant",
			"identification_number",
			self.identification_number,
			{"owner_user": self.owner_user},
			self.name,
		)
		self._validate_status()

	def on_update(self):
		if self.name and self.tenant_name:
			frappe.db.set_value(
				"Tenant Deposit",
				{"tenant": self.name},
				"tenant_name",
				self.tenant_name,
				update_modified=False,
			)

	def on_trash(self):
		prevent_delete_with_allocation_history(self)

	def _validate_status(self):
		"""Active can be placed. Vacated means the last allocation closed. Inactive cannot be placed."""
		if self.status not in ("Active", "Vacated", "Inactive"):
			frappe.throw(_("Status must be Active, Vacated, or Inactive."))
		if self.is_new():
			if self.status == "Vacated":
				frappe.throw(_("A new tenant starts as Active. Vacated is set when an allocation is vacated."))
			return
		active = frappe.db.get_value(
			"Bed Allocation",
			{"tenant": self.name, "allocation_status": "Active"},
			"name",
		)
		if active and self.status in ("Vacated", "Inactive"):
			frappe.throw(
				_("Vacate allocation {0} before marking this tenant {1}.").format(active, self.status)
			)
