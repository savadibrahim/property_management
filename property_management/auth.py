import re

from werkzeug.exceptions import HTTPException
from werkzeug.utils import redirect

import frappe
from frappe import _
from frappe.utils import cint, getdate, today

from property_management.install import ROLE_PROPERTY_SUPER_ADMIN, ROLE_PROPERTY_USER
from property_management.permissions import PRIVILEGED_ROLES, is_privileged, is_property_user


class _PasswordChangeRedirect(HTTPException, frappe.Redirect):
	"""Werkzeug HTTPException so frappe.app.application returns a redirect response from before_request."""

	code = 302
	description = "Redirect to /property-password"

	def __init__(self, location="/property-password", http_status_code=302):
		HTTPException.__init__(self, description=self.description)
		frappe.Redirect.__init__(self, http_status_code=http_status_code)
		self.location = location

	def get_response(self, environ=None, scope=None):
		return redirect(self.location, code=self.http_status_code)

MOBILE_RE = re.compile(r"^[0-9]{8,15}$")
SYNTHETIC_EMAIL_DOMAIN = "users.property.local"

# Paths a signed-in user may hit before replacing the password issued by the super admin.
PASSWORD_CHANGE_PATHS = {
	"/property-password",
	"/website_script.js",
	"/favicon.ico",
	"/api/method/logout",
	"/api/method/property_management.api.change_own_password",
}
PASSWORD_CHANGE_PREFIXES = ("/assets/", "/socket.io")

# Desk workspace for privileged accounts. A property user opens the User Report.
DESK_HOME = "/desk/property-management"
USER_REPORT_HOME = "/desk/property-management/user-report"


def normalize_mobile(mobile):
	"""Login username is the mobile number, digits only, country code included."""
	raw = re.sub(r"[\s\-().]", "", (mobile or "").strip())
	if raw.startswith("+"):
		raw = raw[1:]
	if not MOBILE_RE.fullmatch(raw or ""):
		frappe.throw(
			_("Enter the mobile number as 8 to 15 digits, including the country code. This number is the username.")
		)
	return raw


def synthetic_email(mobile):
	"""User.name must be an email. The address is not the login id."""
	return f"{normalize_mobile(mobile)}@{SYNTHETIC_EMAIL_DOMAIN}"


def resolve_user(login_id, throw=True):
	login_id = (login_id or "").strip()
	if not login_id:
		if throw:
			frappe.throw(_("User is required"))
		return None

	if frappe.db.exists("User", login_id):
		return login_id

	for fieldname in ("username", "mobile_no"):
		name = frappe.db.get_value("User", {fieldname: login_id}, "name")
		if name:
			return name

	digits = re.sub(r"\D", "", login_id)
	if digits and digits != login_id:
		name = frappe.db.get_value("User", {"username": digits}, "name") or frappe.db.get_value(
			"User", {"mobile_no": digits}, "name"
		)
		if name:
			return name

	if throw:
		frappe.throw(_("No property user matches {0}.").format(login_id))
	return None


def get_profile(user):
	"""Return the Property User Profile for a Frappe User.

	before_login and on_login run before the session is switched to the logging-in
	user (the session is Guest or a previous signed-in user). PropertyUserProfile
	inherits OwnedDocument, which checks read permission on load, so load the
	profile with ignore_permissions during internal auth/API lookups.
	"""
	name = frappe.db.get_value("Property User Profile", {"user": user}, "name")
	if not name:
		return None
	if frappe.session.user == user:
		return frappe.get_doc("Property User Profile", name)

	previous = frappe.flags.get("ignore_permissions")
	frappe.flags.ignore_permissions = True
	try:
		return frappe.get_doc("Property User Profile", name)
	finally:
		frappe.flags.ignore_permissions = previous


def is_managed_account(user):
	"""Accounts whose password reset stays with the Property Super Admin."""
	if frappe.db.exists("Property User Profile", {"user": user}):
		return True
	roles = set(frappe.get_roles(user))
	if ROLE_PROPERTY_USER in roles and not roles.intersection(PRIVILEGED_ROLES):
		return True
	return False


def account_expiry_reached(profile):
	if not profile or not profile.account_expiry:
		return False
	return getdate(profile.account_expiry) < getdate(today())


def must_change_password(user):
	if not user or user in ("Guest", "Administrator"):
		return False
	value = frappe.db.get_value("Property User Profile", {"user": user}, "must_change_password")
	return bool(cint(value))


def assert_login_allowed(user):
	"""Block expired property accounts and Property Users that were not created properly."""
	if not user or user in ("Guest", "Administrator"):
		return

	profile = get_profile(user)
	roles = set(frappe.get_roles(user))
	managed_role = ROLE_PROPERTY_USER in roles and not roles.intersection(PRIVILEGED_ROLES)

	if managed_role and not profile:
		frappe.throw(
			_("This login has no property user profile. A Property Super Admin has to recreate it."),
			frappe.AuthenticationError,
		)

	if profile and not cint(profile.enabled):
		frappe.throw(_("This account is deactivated."), frappe.AuthenticationError)

	if account_expiry_reached(profile):
		frappe.throw(
			_("This account expired on {0}. Ask a Property Super Admin to extend it.").format(
				frappe.format(profile.account_expiry, {"fieldtype": "Date"})
			),
			frappe.AuthenticationError,
		)


def before_login(login_manager=None):
	login_id = ""
	if getattr(frappe, "form_dict", None):
		login_id = frappe.form_dict.get("usr") or ""
	user = resolve_user(login_id, throw=False)
	if user:
		assert_login_allowed(user)


def on_login(login_manager=None):
	user = getattr(login_manager, "user", None) or frappe.session.user
	assert_login_allowed(user)
	# get_home_page reads this before role pages and the user's default workspace.
	# The login page uses it as the post-login location.
	if must_change_password(user):
		frappe.cache.hset("redirect_after_login", user, "/property-password")
		frappe.local.flags.home_page = "/property-password"
		return
	frappe.local.flags.home_page = desk_home(user)


def desk_home(user=None):
	"""Landing desk path after sign-in and after the password is changed."""
	user = user or frappe.session.user
	if is_property_user(user) and not is_privileged(user):
		return USER_REPORT_HOME
	return DESK_HOME


def before_request():
	request = getattr(frappe.local, "request", None)
	user = getattr(frappe.session, "user", None)
	if request is None or not user or user in ("Guest", "Administrator"):
		return

	if _profile_table_missing():
		return

	try:
		assert_login_allowed(user)
	except frappe.AuthenticationError:
		_logout_quietly()
		raise

	if not must_change_password(user):
		_send_property_user_to_report(request, user)
		return

	path = request.path or ""
	if path in PASSWORD_CHANGE_PATHS or path.startswith(PASSWORD_CHANGE_PREFIXES):
		return
	# Login itself must stay reachable so a fresh session can be created.
	if path in ("/login", "/api/method/login"):
		return

	if path.startswith("/api/"):
		frappe.throw(
			_("Change the temporary password before using the desk."),
			frappe.PermissionError,
		)

	frappe.local.flags.redirect_location = "/property-password"
	raise _PasswordChangeRedirect("/property-password")


def extend_bootinfo(bootinfo):
	user = frappe.session.user
	if user in ("Guest", "Administrator") or _profile_table_missing():
		return
	profile = frappe.db.get_value(
		"Property User Profile",
		{"user": user},
		["account_expiry", "must_change_password", "mobile_number"],
		as_dict=True,
	)
	bootinfo.property_management = {
		"must_change_password": bool(profile and cint(profile.must_change_password)),
		"account_expiry": profile.account_expiry if profile else None,
		"mobile_number": profile.mobile_number if profile else None,
	}


def validate_reset_password(doc, method=None):
	"""Stop self-service reset for property accounts.

	Frappe's guest `reset_password` catches errors and still shows a generic
	message, so a property user gets no email and no reset key. A signed-in
	user with no reset key is the first-login change, which is allowed.
	"""
	if not doc or not is_managed_account(doc.name):
		return

	form = getattr(frappe, "form_dict", None) or {}
	# Logged-in password change posts new_password and no reset key.
	# The guest "forgot password" call does not, so it is refused.
	if frappe.session.user == doc.name and form.get("new_password") and not form.get("key"):
		if cint(
			frappe.db.get_value("Property User Profile", {"user": doc.name}, "must_change_password")
		):
			frappe.db.set_value(
				"Property User Profile",
				{"user": doc.name},
				"must_change_password",
				0,
				update_modified=False,
			)
		return

	frappe.throw(
		_("Password reset for this account is done by a Property Super Admin."),
		frappe.PermissionError,
	)


def _send_property_user_to_report(request, user):
	"""A full load of the workspace URL is the app's landing path. Open the report instead."""
	if (getattr(request, "method", None) or "GET") not in ("GET", "HEAD"):
		return
	path = (request.path or "").rstrip("/")
	if path != DESK_HOME:
		return
	target = desk_home(user)
	if target == path:
		return
	frappe.local.flags.redirect_location = target
	raise _PasswordChangeRedirect(target)


def _profile_table_missing():
	return not frappe.db.table_exists("Property User Profile")


def _logout_quietly():
	login_manager = getattr(frappe.local, "login_manager", None)
	if not login_manager:
		return
	try:
		login_manager.logout()
	except Exception:
		frappe.logger("property_management").debug("logout during auth gate failed", exc_info=True)
