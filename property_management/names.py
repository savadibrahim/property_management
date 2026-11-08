import frappe
from frappe import _

# The name column is varchar(140). The combination has to fit.
MAX_NAME_LENGTH = 140


def hierarchy_name(*parts):
	"""Join Building, Flat, Area, and Bed labels with a hyphen."""
	cleaned = []
	for part in parts:
		text = " ".join((part or "").split())
		if not text:
			frappe.throw(_("Building, flat, area, and bed names cannot be blank."))
		cleaned.append(text)
	name = "-".join(cleaned)
	if len(name) > MAX_NAME_LENGTH:
		frappe.throw(
			_("The name is longer than {0} characters. Shorten one of the names.").format(MAX_NAME_LENGTH)
		)
	return name


def assign_new_name(doc, *parts):
	doc.name = _available_name(doc.doctype, None, *parts)


def sync_building_tree(building):
	"""Keep Building, Flat, Area, and Bed document names equal to their labels."""
	if frappe.flags.in_hierarchy_rename or not building.name:
		return
	building_name = (building.building_name or "").strip()
	frappe.flags.in_hierarchy_rename = True
	try:
		building_docname = _rename("Building", building.name, hierarchy_name(building_name))
		building.name = building_docname
		_rename_flats(building_docname, building_name)
	finally:
		frappe.flags.in_hierarchy_rename = False


def sync_flat_tree(flat):
	if frappe.flags.in_hierarchy_rename or not flat.name:
		return
	building_name = _building_name(flat.building)
	frappe.flags.in_hierarchy_rename = True
	try:
		flat.name = _rename("Flat", flat.name, hierarchy_name(building_name, flat.flat_number))
		_rename_areas(flat.name, building_name, flat.flat_number)
	finally:
		frappe.flags.in_hierarchy_rename = False


def sync_area_tree(area):
	if frappe.flags.in_hierarchy_rename or not area.name:
		return
	flat_number, building = _flat_parts(area.flat)
	building_name = _building_name(building)
	frappe.flags.in_hierarchy_rename = True
	try:
		area.name = _rename(
			"Area", area.name, hierarchy_name(building_name, flat_number, area.area_name)
		)
		_rename_beds(area.name, building_name, flat_number, area.area_name)
	finally:
		frappe.flags.in_hierarchy_rename = False


def sync_bed_name(bed):
	if frappe.flags.in_hierarchy_rename or not bed.name:
		return
	area_name, flat = frappe.db.get_value("Area", bed.area, ["area_name", "flat"])
	flat_number, building = _flat_parts(flat)
	building_name = _building_name(building)
	frappe.flags.in_hierarchy_rename = True
	try:
		bed.name = _rename(
			"Bed",
			bed.name,
			hierarchy_name(building_name, flat_number, area_name, bed.bed_number),
		)
	finally:
		frappe.flags.in_hierarchy_rename = False


def sync_all_hierarchy_names():
	for name in frappe.get_all("Building", pluck="name"):
		building = frappe.get_doc("Building", name)
		sync_building_tree(building)


def _rename_flats(building, building_name):
	for flat in frappe.get_all("Flat", {"building": building}, ["name", "flat_number"]):
		flat_name = _rename("Flat", flat.name, hierarchy_name(building_name, flat.flat_number))
		_rename_areas(flat_name, building_name, flat.flat_number)


def _rename_areas(flat, building_name, flat_number):
	for area in frappe.get_all("Area", {"flat": flat}, ["name", "area_name"]):
		area_name = _rename(
			"Area", area.name, hierarchy_name(building_name, flat_number, area.area_name)
		)
		_rename_beds(area_name, building_name, flat_number, area.area_name)


def _rename_beds(area, building_name, flat_number, area_name):
	for bed in frappe.get_all("Bed", {"area": area}, ["name", "bed_number"]):
		_rename(
			"Bed",
			bed.name,
			hierarchy_name(building_name, flat_number, area_name, bed.bed_number),
		)


def _building_name(building):
	building_name = frappe.db.get_value("Building", building, "building_name")
	if not building_name:
		frappe.throw(_("Building {0} was not found.").format(building))
	return building_name


def _flat_parts(flat):
	parts = frappe.db.get_value("Flat", flat, ["flat_number", "building"])
	if not parts:
		frappe.throw(_("Flat {0} was not found.").format(flat))
	return parts


def _available_name(doctype, current, *parts):
	new_name = hierarchy_name(*parts)
	if current == new_name:
		return new_name
	if frappe.db.exists(doctype, new_name):
		frappe.throw(_("{0} {1} already exists.").format(doctype, new_name))
	return new_name


def _rename(doctype, old, new):
	if not old or old == new:
		return old or new
	if frappe.db.exists(doctype, new):
		frappe.throw(_("{0} {1} already exists.").format(doctype, new))
	# force is required because these DocTypes are named by script, not by the Rename action.
	frappe.rename_doc(doctype, old, new, force=True, show_alert=False)
	return new
