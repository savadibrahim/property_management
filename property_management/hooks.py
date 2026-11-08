app_name = "property_management"
app_title = "Property Management"
app_publisher = "Property Management"
app_description = "Property users and the building, flat, area, and bed hierarchy."
app_email = "dev@property.local"
app_license = "MIT"
app_version = "0.1.0"

required_apps = ["frappe"]

before_install = "property_management.install.before_install"
after_install = "property_management.install.after_install"

# Login username is the mobile number. Expiry is enforced before a session exists.
before_login = "property_management.auth.before_login"
on_login = "property_management.auth.on_login"
before_request = ["property_management.auth.before_request"]

# Logged-in visits to "/" use this when the user has no default workspace.
# on_login also sets flags.home_page so the login response uses the same path.
role_home_page = {
	"Property User": "desk/property-management/user-report",
	"Property Super Admin": "desk/property-management",
	"System Manager": "desk/property-management",
}

extend_bootinfo = "property_management.auth.extend_bootinfo"

doc_events = {
	"User": {
		"validate_reset_password": "property_management.auth.validate_reset_password",
	}
}

permission_query_conditions = {
	"User": "property_management.hooks.query_user",
	"Property User Profile": "property_management.permissions.query_property_user_profile",
	"Building": "property_management.permissions.query_building",
	"Flat": "property_management.permissions.query_flat",
	"Area": "property_management.permissions.query_area",
	"Bed": "property_management.permissions.query_bed",
	"Tenant": "property_management.permissions.query_tenant",
	"Bed Allocation": "property_management.permissions.query_bed_allocation",
	"Cash Bank Account": "property_management.permissions.query_cash_bank_account",
	"Financial Transaction": "property_management.permissions.query_financial_transaction",
	"Rent Invoice": "property_management.permissions.query_rent_invoice",
	"Rent Payment": "property_management.permissions.query_rent_payment",
	"Tenant Deposit": "property_management.permissions.query_tenant_deposit",
	"Deposit Transaction": "property_management.permissions.query_deposit_transaction",
	"Property Expense": "property_management.permissions.query_property_expense",
	"Monthly Revenue": "property_management.permissions.query_monthly_revenue",
	"Rent Billing Log": "property_management.permissions.query_rent_billing_log",
}

has_permission = {
	"User": "property_management.hooks.has_user_permission",
	"Property User Profile": "property_management.permissions.has_permission",
	"Building": "property_management.permissions.has_permission",
	"Flat": "property_management.permissions.has_permission",
	"Area": "property_management.permissions.has_permission",
	"Bed": "property_management.permissions.has_permission",
	"Tenant": "property_management.permissions.has_permission",
	"Bed Allocation": "property_management.permissions.has_permission",
	"Cash Bank Account": "property_management.permissions.has_permission",
	"Financial Transaction": "property_management.permissions.has_permission",
	"Rent Invoice": "property_management.permissions.has_permission",
	"Rent Payment": "property_management.permissions.has_permission",
	"Tenant Deposit": "property_management.permissions.has_permission",
	"Deposit Transaction": "property_management.permissions.has_permission",
	"Property Expense": "property_management.permissions.has_permission",
	"Monthly Revenue": "property_management.permissions.has_permission",
	"Rent Billing Log": "property_management.permissions.has_permission",
}

standard_queries = {
	"User": "property_management.hooks.user_query",
}

scheduler_events = {
	"daily": [
		"property_management.billing.generate_due_rent_invoices",
	],
}

add_to_apps_screen = [
	{
		"name": "property_management",
		"logo": "/assets/property_management/images/logo.svg",
		"title": "Property Management",
		"route": "/desk/property-management",
		"has_permission": "property_management.permissions.has_app_permission",
	}
]

app_include_css = "/assets/property_management/css/desk.css"
app_include_js = "/assets/property_management/js/password_gate.js?v=20261108d"

fixtures = [
	{
		"doctype": "Property Setter",
		"filters": [["name", "in", ["User-main-show_title_field_in_link"]]],
	}
]
web_include_js = "/assets/property_management/js/login.js"

doctype_js = {
	"Property User Profile": "public/js/property_user_profile.js",
	"Bed Allocation": "public/js/bed_allocation.js",
}


def query_user(user=None, doctype="User"):
	"""User list filter. The running server may still have a permissions.py with no query_user."""
	import frappe
	from property_management import permissions

	implemented = getattr(permissions, "query_user", None)
	if implemented:
		return implemented(user=user, doctype=doctype)

	user = user or frappe.session.user
	if permissions.is_privileged(user):
		return None
	if not permissions.is_property_user(user):
		return "1=0"
	return f"`tabUser`.`name` = {frappe.db.escape(user)}"


def has_user_permission(doc, ptype=None, user=None, debug=False):
	"""User document check. Falls back when permissions.py has no has_user_permission."""
	from property_management import permissions

	implemented = getattr(permissions, "has_user_permission", None)
	if implemented:
		return implemented(doc, ptype=ptype, user=user, debug=debug)

	import frappe

	user = user or frappe.session.user
	if permissions.is_privileged(user):
		return True
	if not permissions.is_property_user(user):
		return False
	doc_name = doc.name if hasattr(doc, "name") else doc
	return doc_name == user


def user_query(doctype, txt, searchfield, start, page_len, filters):
	"""User link search. Falls back when permissions.py has no user_query."""
	import frappe
	from frappe.core.doctype.user.user import user_query as core_user_query
	from property_management import permissions

	implemented = getattr(permissions, "user_query", None)
	if implemented:
		return implemented(doctype, txt, searchfield, start, page_len, filters)

	user = frappe.session.user
	if not permissions.is_privileged(user):
		if not permissions.is_property_user(user):
			return []
		filters = dict(filters or {})
		filters["name"] = user
	return core_user_query(doctype, txt, searchfield, start, page_len, filters)
