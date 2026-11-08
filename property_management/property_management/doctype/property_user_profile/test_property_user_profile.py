from werkzeug.exceptions import HTTPException

import frappe
from frappe.tests.classes.integration_test_case import IntegrationTestCase
from frappe.utils import add_days, cint, today

from property_management.api import change_own_password, create_property_user
from property_management.auth import DESK_HOME, assert_login_allowed, before_request, on_login
from property_management.install import ROLE_PROPERTY_SUPER_ADMIN, ROLE_PROPERTY_USER, ensure_roles
from property_management.testing import future_expiry, make_property_user, unique_mobile

test_records = []


class TestPropertyUserProfile(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_roles_are_created_with_desk_access(self):
		ensure_roles()
		for role_name in (ROLE_PROPERTY_SUPER_ADMIN, ROLE_PROPERTY_USER):
			role = frappe.get_doc("Role", role_name)
			self.assertEqual(cint(role.desk_access), 1)
			self.assertEqual(cint(role.disabled), 0)

	def test_create_property_user_uses_mobile_as_username(self):
		frappe.set_user("Administrator")
		mobile = unique_mobile()
		created = create_property_user("Amina Hassan", mobile, "initial-pass-1", future_expiry())
		user = frappe.get_doc("User", created["user"])
		profile = frappe.get_doc("Property User Profile", created["property_user_profile"])

		self.assertEqual(user.username, mobile)
		self.assertEqual(user.mobile_no, mobile)
		self.assertEqual(profile.mobile_number, mobile)
		self.assertEqual(cint(profile.must_change_password), 1)
		self.assertNotIn("password", profile.as_dict())
		self.assertTrue(ROLE_PROPERTY_USER in {row.role for row in user.roles})
		self.assertFalse(user.new_password)

	def test_property_user_cannot_create_users(self):
		frappe.set_user("Administrator")
		created = make_property_user()
		frappe.set_user(created["user"])
		with self.assertRaises(frappe.PermissionError):
			create_property_user("Other Person", unique_mobile(), "initial-pass-1", future_expiry())

	def test_login_check_allows_active_account_as_guest(self):
		"""before_login still runs as Guest; loading the profile must not PermissionError."""
		frappe.set_user("Administrator")
		created = make_property_user()
		frappe.set_user("Guest")
		assert_login_allowed(created["user"])

	def test_login_check_allows_switching_from_another_property_user(self):
		"""Signing in while another Property User session is active must not PermissionError."""
		frappe.set_user("Administrator")
		first = make_property_user()
		second = make_property_user()
		frappe.set_user(first["user"])
		assert_login_allowed(second["user"])

	def test_recreate_missing_property_user_profile(self):
		"""A Property Super Admin can recreate a deleted Property User Profile for an existing User."""
		frappe.set_user("Administrator")
		mobile = unique_mobile()
		created = create_property_user("Savad", mobile, "initial-pass-1", future_expiry())
		frappe.delete_doc(
			"Property User Profile", created["property_user_profile"], ignore_permissions=True, force=True
		)

		recreated = create_property_user("Savad Updated", mobile, "new-temp-pass-1", future_expiry(60))
		self.assertEqual(recreated["user"], created["user"])
		self.assertTrue(frappe.db.exists("Property User Profile", recreated["property_user_profile"]))

	def test_expired_account_is_blocked(self):
		frappe.set_user("Administrator")
		created = make_property_user()
		profile = frappe.get_doc("Property User Profile", created["property_user_profile"])
		profile.account_expiry = add_days(today(), -1)
		profile.save(ignore_permissions=True)

		# Login hooks evaluate the profile before the session is created.
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			assert_login_allowed(created["user"])

	def test_guest_reset_is_refused_for_property_user(self):
		frappe.set_user("Administrator")
		created = make_property_user()
		user = frappe.get_doc("User", created["user"])

		frappe.set_user("Guest")
		frappe.local.form_dict = frappe._dict()
		with self.assertRaises(frappe.PermissionError):
			user.validate_reset_password()

		frappe.set_user(created["user"])
		frappe.local.form_dict = frappe._dict()
		with self.assertRaises(frappe.PermissionError):
			user.validate_reset_password()

		frappe.local.form_dict = frappe._dict(new_password="a-different-pass-1")
		user.validate_reset_password()

	def test_password_page_loads_controller_and_desk_home(self):
		"""Frappe loads www/property-password.html from www/property_password.py, not the hyphenated filename."""
		from frappe.website.page_renderers.template_page import TemplatePage

		page = TemplatePage("property-password")
		page.init_context()
		page.set_pymodule()
		self.assertEqual(page.pymodule_name, "property_management.www.property_password")

		frappe.set_user("Administrator")
		created = make_property_user()
		frappe.set_user(created["user"])
		page.update_context()
		self.assertEqual(page.context.desk_home, DESK_HOME)

	def test_on_login_opens_property_desk(self):
		frappe.set_user("Administrator")
		created = make_property_user()
		frappe.db.set_value(
			"Property User Profile",
			created["property_user_profile"],
			"must_change_password",
			0,
			update_modified=False,
		)
		frappe.set_user(created["user"])
		frappe.local.flags.home_page = None
		on_login(frappe._dict(user=created["user"]))
		self.assertEqual(frappe.local.flags.home_page, DESK_HOME)

	def test_on_login_opens_password_page_when_change_is_required(self):
		frappe.set_user("Administrator")
		created = make_property_user()
		frappe.set_user(created["user"])
		frappe.local.flags.home_page = None
		on_login(frappe._dict(user=created["user"]))
		self.assertEqual(frappe.local.flags.home_page, "/property-password")

	def test_before_request_raises_http_redirect_when_must_change_password(self):
		"""before_request must raise an HTTPException redirect so frappe.app.application returns 302 instead of a 301 Server Error."""
		frappe.set_user("Administrator")
		created = make_property_user()
		frappe.set_user(created["user"])
		previous_request = getattr(frappe.local, "request", None)
		frappe.local.request = frappe._dict(path="/desk")
		try:
			with self.assertRaises(HTTPException) as ctx:
				before_request()
			response = ctx.exception.get_response()
			self.assertEqual(response.status_code, 302)
			self.assertEqual(response.headers.get("Location"), "/property-password")
		finally:
			frappe.local.request = previous_request

	def test_change_own_password_wrong_current_password_does_not_raise_auth_error(self):
		"""Wrong old_password must raise ValidationError, not AuthenticationError (which clears session cookies in app.py)."""
		frappe.set_user("Administrator")
		created = make_property_user()
		frappe.set_user(created["user"])
		with self.assertRaises(frappe.ValidationError) as ctx:
			change_own_password("wrong-current-pass", "StrongNewPass-99!")
		self.assertNotIsInstance(ctx.exception, frappe.AuthenticationError)
