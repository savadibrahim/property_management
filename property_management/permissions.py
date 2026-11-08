import frappe

from property_management.install import ROLE_PROPERTY_SUPER_ADMIN, ROLE_PROPERTY_USER

PRIVILEGED_ROLES = ("System Manager", ROLE_PROPERTY_SUPER_ADMIN)
PROFILE_DOCTYPE = "Property User Profile"


def is_privileged(user=None):
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	return bool(roles.intersection(PRIVILEGED_ROLES))


def is_property_user(user=None):
	user = user or frappe.session.user
	return ROLE_PROPERTY_USER in set(frappe.get_roles(user))


def owner_field(doctype):
	if doctype == PROFILE_DOCTYPE:
		return "user"
	return "owner_user"


def permission_query_conditions(user, doctype):
	"""Restrict list/report queries. Privileged roles see every row."""
	user = user or frappe.session.user
	if is_privileged(user):
		return None
	if not is_property_user(user):
		return "1=0"
	column = owner_field(doctype)
	return f"`tab{doctype}`.`{column}` = {frappe.db.escape(user)}"


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Deny document access when the row belongs to someone else.

	Frappe v16 treats a falsy hook result as a deny, so this returns True when
	the user is allowed. It never grants a permission the role does not already have.
	"""
	user = user or frappe.session.user
	if is_privileged(user):
		return True
	if not is_property_user(user):
		return False

	owner = _stored_owner(doc)
	if not owner:
		# Unsaved documents get their owner in validate, which runs after the create check.
		return bool(doc.get("__islocal") or (hasattr(doc, "is_new") and doc.is_new()))
	return owner == user


def _stored_owner(doc):
	"""Use the database owner for a saved row so a client payload cannot claim it."""
	fieldname = owner_field(doc.doctype)
	if not doc.get("__islocal") and doc.get("name"):
		stored = frappe.db.get_value(doc.doctype, doc.name, fieldname)
		if stored:
			return stored
	return doc.get(fieldname)


def has_app_permission():
	user = frappe.session.user
	if user == "Guest":
		return False
	return is_privileged(user) or is_property_user(user)


def query_property_user_profile(user=None):
	return permission_query_conditions(user, "Property User Profile")


def query_building(user=None):
	return permission_query_conditions(user, "Building")


def query_flat(user=None):
	return permission_query_conditions(user, "Flat")


def query_area(user=None):
	return permission_query_conditions(user, "Area")


def query_bed(user=None):
	return permission_query_conditions(user, "Bed")


def query_tenant(user=None):
	return permission_query_conditions(user, "Tenant")


def query_bed_allocation(user=None):
	return permission_query_conditions(user, "Bed Allocation")


def query_cash_bank_account(user=None):
	return permission_query_conditions(user, "Cash Bank Account")


def query_financial_transaction(user=None):
	return permission_query_conditions(user, "Financial Transaction")


def query_rent_invoice(user=None):
	return permission_query_conditions(user, "Rent Invoice")


def query_rent_payment(user=None):
	return permission_query_conditions(user, "Rent Payment")


def query_tenant_deposit(user=None):
	return permission_query_conditions(user, "Tenant Deposit")


def query_deposit_transaction(user=None):
	return permission_query_conditions(user, "Deposit Transaction")


def query_property_expense(user=None):
	return permission_query_conditions(user, "Property Expense")


def query_monthly_revenue(user=None):
	return permission_query_conditions(user, "Monthly Revenue")


def query_rent_billing_log(user=None):
	return permission_query_conditions(user, "Rent Billing Log")


def query_user(user=None, doctype="User"):
	"""Restrict User queries so a Property User only ever sees their own User record."""
	user = user or frappe.session.user
	if is_privileged(user):
		return None
	if not is_property_user(user):
		return "1=0"
	return f"`tabUser`.`name` = {frappe.db.escape(user)}"


def has_user_permission(doc, ptype=None, user=None, debug=False):
	"""Prevent a Property User from reading or selecting another User record."""
	user = user or frappe.session.user
	if is_privileged(user):
		return True
	if not is_property_user(user):
		return False
	doc_name = doc.name if hasattr(doc, "name") else doc
	return doc_name == user


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def user_query(doctype, txt, searchfield, start, page_len, filters):
	"""Standard link query for User. Pins non-privileged Property Users to their own account."""
	from frappe.core.doctype.user.user import user_query as core_user_query

	user = frappe.session.user
	if not is_privileged(user):
		if not is_property_user(user):
			return []
		filters = dict(filters or {})
		filters["name"] = user

	return core_user_query(doctype, txt, searchfield, start, page_len, filters)

