import frappe
from frappe.tests.classes.integration_test_case import IntegrationTestCase

from property_management.testing import make_bed_stack, make_property_user, make_super_admin, unique_digits

test_records = []


class TestBuilding(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_property_user_cannot_read_another_users_building(self):
		frappe.set_user("Administrator")
		user_a = make_property_user("User A")
		user_b = make_property_user("User B")
		super_admin = make_super_admin()

		frappe.set_user(user_a["user"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "Building",
					"building_name": "Not Theirs",
					"building_code": f"X-{unique_digits(6)}",
					"status": "Active",
					"owner_user": user_b["user"],
				}
			).insert()

		building = frappe.get_doc(
			{
				"doctype": "Building",
				"building_name": "Block A",
				"building_code": f"A-{unique_digits(6)}",
				"status": "Active",
			}
		).insert()
		self.assertEqual(building.owner_user, user_a["user"])

		frappe.set_user(user_b["user"])
		visible = frappe.get_list("Building", filters={"name": building.name}, pluck="name")
		self.assertEqual(visible, [])
		self.assertFalse(frappe.has_permission("Building", "read", building.name))
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Building", building.name)
		forged = frappe.get_doc(
			{
				"doctype": "Building",
				"name": building.name,
				"building_name": "Stolen",
				"building_code": building.building_code,
				"status": "Active",
				"owner_user": user_b["user"],
			}
		)
		with self.assertRaises(frappe.PermissionError):
			forged.save()

		frappe.clear_cache(user=super_admin)
		frappe.set_user(super_admin)
		same = frappe.get_doc("Building", building.name)
		self.assertEqual(same.name, building.name)

	def test_record_name_is_the_hierarchy(self):
		frappe.set_user("Administrator")
		user_a = make_property_user("Name Owner A")
		user_b = make_property_user("Name Owner B")
		code = unique_digits(6)

		frappe.set_user(user_a["user"])
		building, flat, area, bed = make_bed_stack(code)
		self.assertEqual(building.name, f"Harbour {code}")
		self.assertEqual(flat.name, f"Harbour {code}-F-{code}")
		self.assertEqual(area.name, f"Harbour {code}-F-{code}-Bedroom 1")
		self.assertEqual(bed.name, f"Harbour {code}-F-{code}-Bedroom 1-1")

		building.building_name = f"Harbour West {code}"
		building.save()
		renamed_bed = frappe.db.get_value(
			"Bed", {"building": f"Harbour West {code}", "bed_number": "1"}, "name"
		)
		self.assertEqual(renamed_bed, f"Harbour West {code}-F-{code}-Bedroom 1-1")

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Building",
					"building_name": f"Harbour West {code}",
					"status": "Active",
				}
			).insert()

		frappe.set_user(user_b["user"])
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Building",
					"building_name": f"Harbour West {code}",
					"status": "Active",
				}
			).insert()

	def test_property_user_only_sees_own_user_in_owner_user_search(self):
		from frappe.desk.search import search_link

		frappe.set_user("Administrator")
		user_a = make_property_user("Search Owner A")
		user_b = make_property_user("Search Owner B")

		frappe.set_user(user_a["user"])
		visible_users = frappe.get_list("User", pluck="name")
		self.assertEqual(visible_users, [user_a["user"]])

		link_results = search_link(
			doctype="User",
			txt="",
			reference_doctype="Building",
			link_fieldname="owner_user",
		)
		returned_names = [row["value"] for row in link_results]
		self.assertEqual(returned_names, [user_a["user"]])
		self.assertEqual(link_results[0]["label"], "Search Owner A")
		self.assertNotIn(user_b["user"], returned_names)
		self.assertFalse(frappe.has_permission("User", "read", user_b["user"]))
		self.assertTrue(frappe.has_permission("User", "read", user_a["user"]))

