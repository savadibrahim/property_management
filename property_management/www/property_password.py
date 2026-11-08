import frappe

from property_management.auth import DESK_HOME, must_change_password

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/property-password"
		raise frappe.Redirect

	if not must_change_password(frappe.session.user):
		frappe.local.flags.redirect_location = DESK_HOME
		raise frappe.Redirect

	context.no_cache = 1
	context.show_sidebar = 0
	context.title = "Change password"
	context.csrf_token = frappe.sessions.get_csrf_token()
	context.desk_home = DESK_HOME
