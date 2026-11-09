"""Desk overview for Super Admin Panel and User Report.

Figures come from the documents that already record occupancy and money.
Occupancy and held deposits are current balances. The date range applies to
flows: recognized rent, collections, deposit movements, and expenses.

Operating profit is recognized rental revenue, plus deposit transferred to
revenue, plus other revenue, minus net expenses. A held deposit is not revenue.
Rent collected is cash, not a second copy of revenue. Cancelled invoices,
receipts, and expenses stay in the transaction list as negative rows, so the
sum nets them once.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, get_first_day, get_last_day, getdate, today

from property_management.auth import resolve_user
from property_management.billing import generate_due_rent_invoices
from property_management.hierarchy import require_readable
from property_management.permissions import is_privileged, is_property_user

MEASURES = {
	"monthly_fixed_rent": (
		"Sum of Monthly Revenue.monthly_rent for Active schedules in the filter. That field follows the latest "
		"rent revision on the schedule. Stopped schedules, including vacated allocations, are excluded. "
		"The date range does not change this figure, and submitted invoices are not rewritten."
	),
	"recognized_rental_revenue": (
		"Submitted Financial Transactions in the date range whose type is Rent Generated or Receivable Adjustment. "
		"Cancelling an invoice posts a negative Receivable Adjustment on the invoice billing date, so that period "
		"is reduced and the invoice amount is not subtracted again."
	),
	"rent_collected": (
		"Submitted Financial Transactions in the date range whose type is Rent Received or Payment Reversal. "
		"Cancelling a receipt posts a negative Payment Reversal on the original receipt date. "
		"This is cash applied to invoices. It is not added to operating profit."
	),
	"allocated_receipts": (
		"Invoice Allocation amounts on submitted Rent Payments dated in the range, for invoices inside the filter. "
		"Cancelled payments are left out. This explains rent collected. It is not a second receipt."
	),
	"advances": (
		"Submitted Rent Payment amount minus the allocations on that payment. "
		"Payment rules require the whole amount to be allocated, so this stays zero unless cash was left unapplied. "
		"An advance is not rent revenue. With a building, flat, or area selected, it is counted only when every "
		"allocation on the payment is inside that filter."
	),
	"outstanding_in_period": (
		"Outstanding still open on submitted Rent Invoices whose billing date is inside the date range. "
		"Drafts and cancelled invoices are excluded."
	),
	"outstanding_open": (
		"Outstanding still open on every submitted Rent Invoice in the filter. The date range is ignored. "
		"Vacating a bed does not clear it."
	),
	"held_deposits": (
		"All submitted Deposit Received, minus Deposit Refunded, minus Deposit Transferred to Revenue, in the filter. "
		"The date range is ignored. Held deposits are not revenue."
	),
	"deposit_received": "Submitted Deposit Received transactions in the date range. Not included in operating profit.",
	"deposit_refunded": "Submitted Deposit Refunded transactions in the date range. Not included in operating profit.",
	"deposit_transferred_to_revenue": (
		"Submitted Deposit Transferred to Revenue transactions in the date range. Included in operating profit."
	),
	"other_revenue": "Submitted Other Revenue transactions in the date range. Included in operating profit.",
	"expenses": (
		"Submitted Expense transactions in the date range. Cancelling an expense posts a negative Expense on the "
		"original date, so the net is zero without subtracting the expense document again."
	),
	"operating_profit": (
		"Recognized rental revenue, plus deposit transferred to revenue, plus other revenue, minus expenses. "
		"Rent collected, held deposits, deposit receipts, and deposit refunds are not part of this figure."
	),
	"occupancy": (
		"Current building, flat, area, and bed counts in the filter. The date range does not change occupancy. "
		"The rate is occupied beds divided by all beds in the filter. Zero beds is a zero rate."
	),
}

LIST_LIMIT = 80


@frappe.whitelist()
def get_overview(owner_user=None, building=None, flat=None, area=None, from_date=None, to_date=None):
	"""Occupancy and money for the signed-in owner, or for every owner when privileged."""
	scope = resolve_scope(owner_user, building, flat, area, from_date, to_date)
	payload = _metrics(scope)
	payload["scope"] = _scope_payload(scope)
	payload["measures"] = MEASURES
	if scope.privileged:
		payload["users"] = _user_rows(scope)
	return payload


@frappe.whitelist()
def get_operations(owner_user=None, building=None, flat=None, area=None, from_date=None, to_date=None):
	"""Hierarchy and the records the User Report can open. Same scope rules as the overview."""
	scope = resolve_scope(owner_user, building, flat, area, from_date, to_date)
	generate_due_rent_invoices(owner=scope.owner)
	return {
		"scope": _scope_payload(scope),
		"hierarchy": _hierarchy(scope),
		"allocations": _limited_docs(
			"Bed Allocation",
			_location_filters(scope),
			[
				"name",
				"tenant",
				"bed",
				"allocation_status",
				"monthly_rent",
				"deposit_amount",
				"allocation_date",
				"vacating_date",
				"generate_rent",
				"building",
				"flat",
				"area",
			],
			"allocation_status asc, modified desc",
		),
		"schedules": _limited_docs(
			"Monthly Revenue",
			_location_filters(scope),
			[
				"name",
				"bed_allocation",
				"status",
				"monthly_rent",
				"start_date",
				"end_date",
				"tenant",
				"bed",
				"building",
				"flat",
				"area",
			],
			"status asc, modified desc",
		),
		"invoices": _limited_docs(
			"Rent Invoice",
			{**_location_filters(scope), "billing_date": ["between", [scope.from_date, scope.to_date]]},
			[
				"name",
				"tenant",
				"billing_month",
				"billing_date",
				"due_date",
				"rent_amount",
				"amount_paid",
				"outstanding",
				"status",
				"docstatus",
				"bed",
			],
			"billing_date desc",
		),
		"payments": _payments(scope),
		"deposits": _limited_docs(
			"Tenant Deposit",
			_location_filters(scope),
			[
				"name",
				"tenant",
				"bed_allocation",
				"bed",
				"status",
				"deposit_due",
				"balance",
				"total_received",
				"total_refunded",
				"total_transferred",
			],
			"modified desc",
		),
		"deposit_transactions": _deposit_transactions(scope),
		"expenses": _limited_docs(
			"Property Expense",
			{**_location_filters(scope), "posting_date": ["between", [scope.from_date, scope.to_date]]},
			[
				"name",
				"posting_date",
				"expense_category",
				"amount",
				"status",
				"docstatus",
				"building",
				"flat",
				"area",
			],
			"posting_date desc",
		),
	}


@frappe.whitelist()
def get_filter_options(owner_user=None, building=None, flat=None):
	"""Buildings, flats, and areas the caller is allowed to filter by."""
	scope = resolve_scope(owner_user, building, flat, None, today(), today())
	building_filters = {}
	if scope.owner:
		building_filters["owner_user"] = scope.owner
	buildings = frappe.get_all(
		"Building",
		filters=building_filters,
		fields=["name", "building_name", "building_code"],
		order_by="building_name asc",
	)
	flats = []
	areas = []
	building_for_flats = scope.building
	if not building_for_flats and scope.flat:
		building_for_flats = frappe.db.get_value("Flat", scope.flat, "building")
	if building_for_flats:
		flat_filters = {"building": building_for_flats}
		if scope.owner:
			flat_filters["owner_user"] = scope.owner
		flats = frappe.get_all(
			"Flat",
			filters=flat_filters,
			fields=["name", "flat_number", "building"],
			order_by="flat_number asc",
		)
	if scope.flat:
		area_filters = {"flat": scope.flat}
		if scope.owner:
			area_filters["owner_user"] = scope.owner
		areas = frappe.get_all(
			"Area",
			filters=area_filters,
			fields=["name", "area_name", "flat", "building"],
			order_by="area_name asc",
		)
	return {
		"owner_user": scope.owner,
		"privileged": scope.privileged,
		"buildings": buildings,
		"flats": flats,
		"areas": areas,
	}


@frappe.whitelist()
def list_property_accounts():
	"""Property logins for the super admin page. Passwords are not selected."""
	_require_super_admin()
	profiles = frappe.get_all(
		"Property User Profile",
		fields=["user", "mobile_number", "enabled", "account_expiry", "must_change_password"],
		order_by="mobile_number asc",
	)
	names = {}
	if profiles:
		for row in frappe.get_all(
			"User",
			filters={"name": ["in", [profile.user for profile in profiles]]},
			fields=["name", "full_name"],
		):
			names[row.name] = row.full_name
	today_date = getdate(today())
	accounts = []
	for profile in profiles:
		expiry = getdate(profile.account_expiry) if profile.account_expiry else None
		accounts.append(
			{
				"user": profile.user,
				"full_name": names.get(profile.user) or profile.user,
				"mobile_number": profile.mobile_number,
				"enabled": cint(profile.enabled),
				"account_expiry": str(expiry) if expiry else None,
				"expired": bool(expiry and expiry < today_date),
				"must_change_password": cint(profile.must_change_password),
			}
		)
	return accounts


def resolve_scope(owner_user=None, building=None, flat=None, area=None, from_date=None, to_date=None):
	"""Apply the caller's role, then reject a location or user they cannot use."""
	user = _require_desk_user()
	privileged = is_privileged(user)
	owner = _resolve_owner_filter(user, privileged, _clean(owner_user))
	building_name = _clean(building)
	flat_name = _clean(flat)
	area_name = _clean(area)

	building_row = _location("Building", building_name, owner)
	flat_row = _location("Flat", flat_name, owner, ["building"])
	area_row = _location("Area", area_name, owner, ["flat", "building"])
	if flat_row and building_row and flat_row.building != building_row.name:
		frappe.throw(_("Flat {0} is not in the selected building.").format(flat_name))
	if area_row and flat_row and area_row.flat != flat_row.name:
		frappe.throw(_("Area {0} is not in the selected flat.").format(area_name))
	if area_row and building_row and area_row.building != building_row.name:
		frappe.throw(_("Area {0} is not in the selected building.").format(area_name))

	period_is_default = not _clean(from_date) and not _clean(to_date)
	if period_is_default:
		start = get_first_day(today())
		end = get_last_day(today())
	else:
		if not _clean(from_date) or not _clean(to_date):
			frappe.throw(_("Enter both a from date and a to date."))
		start = getdate(from_date)
		end = getdate(to_date)
		if start > end:
			frappe.throw(_("From date cannot be after to date."))

	location_owner = None
	for row in (area_row, flat_row, building_row):
		if row:
			location_owner = row.owner_user
			break

	return frappe._dict(
		user=user,
		privileged=privileged,
		owner=owner,
		building=building_row.name if building_row else None,
		flat=flat_row.name if flat_row else None,
		area=area_row.name if area_row else None,
		from_date=start,
		to_date=end,
		period_is_default=period_is_default,
		has_location=bool(building_row or flat_row or area_row),
		location_owner=location_owner,
	)


def _require_desk_user():
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("You need to be logged in."), frappe.PermissionError)
	if is_privileged(user) or is_property_user(user):
		return user
	frappe.throw(_("You cannot open property pages."), frappe.PermissionError)


def _require_super_admin():
	if not is_privileged():
		frappe.throw(
			_("Only a Property Super Admin can manage property users."),
			frappe.PermissionError,
		)


def _resolve_owner_filter(user, privileged, owner_user):
	if privileged:
		if not owner_user:
			return None
		resolved = resolve_user(owner_user)
		if not frappe.db.exists("Property User Profile", {"user": resolved}):
			frappe.throw(_("{0} is not a property user.").format(owner_user))
		return resolved

	if owner_user:
		resolved = resolve_user(owner_user, throw=False)
		if resolved != user:
			frappe.throw(_("You can only view your own records."), frappe.PermissionError)
	return user


def _location(doctype, name, owner, extra_fields=None):
	if not name:
		return None
	require_readable(doctype, name)
	fields = ["name", "owner_user", *(extra_fields or [])]
	row = frappe.db.get_value(doctype, name, fields, as_dict=True)
	if owner and row.owner_user != owner:
		frappe.throw(
			_("{0} {1} belongs to another property user.").format(doctype, name),
			frappe.ValidationError,
		)
	return row


def _metrics(scope):
	occupancy = _occupancy(scope)
	recognized = _sum_transactions(scope, ("Rent Generated", "Receivable Adjustment"), dated=True)
	collected = _sum_transactions(scope, ("Rent Received", "Payment Reversal"), dated=True)
	allocated, advances = _collection_split(scope)
	deposit_received = _sum_transactions(scope, ("Deposit Received",), dated=True)
	deposit_refunded = _sum_transactions(scope, ("Deposit Refunded",), dated=True)
	transferred = _sum_transactions(scope, ("Deposit Transferred to Revenue",), dated=True)
	other_revenue = _sum_transactions(scope, ("Other Revenue",), dated=True)
	expenses = _sum_transactions(scope, ("Expense",), dated=True)
	held = (
		_sum_transactions(scope, ("Deposit Received",), dated=False)
		- _sum_transactions(scope, ("Deposit Refunded",), dated=False)
		- _sum_transactions(scope, ("Deposit Transferred to Revenue",), dated=False)
	)
	money = {
		"monthly_fixed_rent": _monthly_fixed_rent(scope),
		"recognized_rental_revenue": recognized,
		"rent_collected": collected,
		"allocated_receipts": allocated,
		"advances": advances,
		"outstanding_in_period": _outstanding(scope, dated=True),
		"outstanding_open": _outstanding(scope, dated=False),
		"held_deposits": flt(held, 2),
		"deposit_received": deposit_received,
		"deposit_refunded": deposit_refunded,
		"deposit_transferred_to_revenue": transferred,
		"other_revenue": other_revenue,
		"expenses": expenses,
		"operating_profit": flt(recognized + transferred + other_revenue - expenses, 2),
	}
	return {"occupancy": occupancy, "money": money}


def _occupancy(scope):
	buildings = len(_building_rows(scope))
	flats = frappe.get_all("Flat", filters=_flat_filters(scope), pluck="name")
	areas = frappe.get_all("Area", filters=_area_filters(scope), pluck="name")
	beds = frappe.get_all("Bed", filters=_bed_filters(scope), fields=["occupancy_status"])
	occupied = sum(1 for bed in beds if bed.occupancy_status == "Occupied")
	vacant = sum(1 for bed in beds if bed.occupancy_status == "Vacant")
	maintenance = sum(1 for bed in beds if bed.occupancy_status == "Maintenance")
	allocations = frappe.get_all(
		"Bed Allocation",
		filters={**_location_filters(scope), "allocation_status": "Active"},
		pluck="name",
	)
	total_beds = len(beds)
	return {
		"buildings": buildings,
		"flats": len(flats),
		"areas": len(areas),
		"beds": total_beds,
		"beds_occupied": occupied,
		"beds_vacant": vacant,
		"beds_maintenance": maintenance,
		"active_allocations": len(allocations),
		"occupancy_rate": flt(occupied / total_beds, 4) if total_beds else 0.0,
	}


def _monthly_fixed_rent(scope):
	rows = frappe.get_all(
		"Monthly Revenue",
		filters={**_location_filters(scope), "status": "Active"},
		fields=["monthly_rent"],
	)
	return flt(sum(flt(row.monthly_rent) for row in rows), 2)


def _outstanding(scope, dated):
	filters = {**_location_filters(scope), "docstatus": 1}
	if getattr(scope, "tenant", None):
		filters["tenant"] = scope.tenant
	if dated:
		filters["billing_date"] = ["between", [scope.from_date, scope.to_date]]
	rows = frappe.get_all("Rent Invoice", filters=filters, fields=["outstanding"])
	return flt(sum(flt(row.outstanding) for row in rows), 2)


def _sum_transactions(scope, types, dated):
	filters = {"docstatus": 1, "transaction_type": ["in", list(types)]}
	if scope.owner:
		filters["owner_user"] = scope.owner
	if scope.building:
		filters["building"] = scope.building
	if scope.flat:
		filters["flat"] = scope.flat
	if scope.area:
		filters["area"] = scope.area
	if getattr(scope, "tenant", None):
		filters["tenant"] = scope.tenant
	if dated:
		filters["posting_date"] = ["between", [scope.from_date, scope.to_date]]
	rows = frappe.get_all("Financial Transaction", filters=filters, fields=["amount"])
	return flt(sum(flt(row.amount) for row in rows), 2)


def _collection_split(scope):
	filters = {"docstatus": 1, "posting_date": ["between", [scope.from_date, scope.to_date]]}
	if scope.owner:
		filters["owner_user"] = scope.owner
	if getattr(scope, "tenant", None):
		filters["tenant"] = scope.tenant
	payments = frappe.get_all("Rent Payment", filters=filters, fields=["name", "amount", "owner_user"])
	allocated_total = 0.0
	advances = 0.0
	for payment in payments:
		rows = frappe.get_all(
			"Invoice Allocation",
			filters={"parent": payment.name, "parenttype": "Rent Payment"},
			fields=["rent_invoice", "allocated_amount"],
		)
		matched = []
		for row in rows:
			invoice = frappe.db.get_value(
				"Rent Invoice",
				row.rent_invoice,
				["owner_user", "building", "flat", "area"],
				as_dict=True,
			)
			if _invoice_in_scope(invoice, scope):
				matched.append(row)
		if scope.has_location and not matched:
			continue
		allocated_total += sum(flt(row.allocated_amount) for row in (matched if scope.has_location else rows))
		whole_payment_in_scope = not scope.has_location or (rows and len(matched) == len(rows))
		if whole_payment_in_scope:
			remainder = flt(payment.amount) - sum(flt(row.allocated_amount) for row in rows)
			if remainder > 0:
				advances += remainder
	return flt(allocated_total, 2), flt(advances, 2)


def _invoice_in_scope(invoice, scope):
	if not invoice:
		return False
	if scope.owner and invoice.owner_user != scope.owner:
		return False
	if scope.building and invoice.building != scope.building:
		return False
	if scope.flat and invoice.flat != scope.flat:
		return False
	if scope.area and invoice.area != scope.area:
		return False
	return True


def _user_rows(scope):
	profiles = frappe.get_all(
		"Property User Profile",
		fields=["user", "mobile_number", "enabled", "account_expiry"],
		order_by="mobile_number asc",
	)
	if scope.owner:
		profiles = [profile for profile in profiles if profile.user == scope.owner]
	elif scope.location_owner:
		profiles = [profile for profile in profiles if profile.user == scope.location_owner]
	full_names = {}
	if profiles:
		for row in frappe.get_all(
			"User",
			filters={"name": ["in", [profile.user for profile in profiles]]},
			fields=["name", "full_name"],
		):
			full_names[row.name] = row.full_name
	today_date = getdate(today())
	rows = []
	for profile in profiles:
		child = frappe._dict(scope)
		child.owner = profile.user
		metrics = _metrics(child)
		expiry = getdate(profile.account_expiry) if profile.account_expiry else None
		rows.append(
			{
				"user": profile.user,
				"full_name": full_names.get(profile.user) or profile.user,
				"mobile_number": profile.mobile_number,
				"enabled": cint(profile.enabled),
				"expired": bool(expiry and expiry < today_date),
				"buildings": metrics["occupancy"]["buildings"],
				"beds": metrics["occupancy"]["beds"],
				"beds_occupied": metrics["occupancy"]["beds_occupied"],
				"monthly_fixed_rent": metrics["money"]["monthly_fixed_rent"],
				"recognized_rental_revenue": metrics["money"]["recognized_rental_revenue"],
				"rent_collected": metrics["money"]["rent_collected"],
				"outstanding_open": metrics["money"]["outstanding_open"],
				"held_deposits": metrics["money"]["held_deposits"],
				"expenses": metrics["money"]["expenses"],
				"operating_profit": metrics["money"]["operating_profit"],
			}
		)
	return rows


def _hierarchy(scope):
	buildings = _building_rows(scope)
	flats = frappe.get_all(
		"Flat",
		filters=_flat_filters(scope),
		fields=["name", "flat_number", "building", "status"],
		order_by="flat_number asc",
	)
	areas = frappe.get_all(
		"Area",
		filters=_area_filters(scope),
		fields=["name", "area_name", "flat", "building", "status", "area_type"],
		order_by="area_name asc",
	)
	beds = frappe.get_all(
		"Bed",
		filters=_bed_filters(scope),
		fields=[
			"name",
			"bed_number",
			"area",
			"flat",
			"building",
			"occupancy_status",
			"status",
			"monthly_rent",
			"current_tenant",
			"current_allocation",
		],
		order_by="bed_number asc",
	)
	tenant_ids = [bed.current_tenant for bed in beds if bed.current_tenant]
	tenant_names = _names("Tenant", tenant_ids, "tenant_name")
	areas_by_flat = {}
	for area in areas:
		areas_by_flat.setdefault(area.flat, []).append(area)
	beds_by_area = {}
	for bed in beds:
		beds_by_area.setdefault(bed.area, []).append(bed)
	flats_by_building = {}
	for flat in flats:
		flats_by_building.setdefault(flat.building, []).append(flat)

	tree = []
	for building in buildings:
		flat_rows = []
		for flat in flats_by_building.get(building.name, []):
			area_rows = []
			for area in areas_by_flat.get(flat.name, []):
				bed_rows = []
				for bed in beds_by_area.get(area.name, []):
					bed_rows.append(
						{
							"doctype": "Bed",
							"name": bed.name,
							"label": bed.bed_number,
							"occupancy_status": bed.occupancy_status,
							"status": bed.status,
							"monthly_rent": flt(bed.monthly_rent),
							"current_tenant": bed.current_tenant,
							"current_tenant_name": tenant_names.get(bed.current_tenant),
							"current_allocation": bed.current_allocation,
						}
					)
				area_rows.append(
					{
						"doctype": "Area",
						"name": area.name,
						"label": area.area_name,
						"area_type": area.area_type,
						"status": area.status,
						"beds": bed_rows,
					}
				)
			flat_rows.append(
				{
					"doctype": "Flat",
					"name": flat.name,
					"label": flat.flat_number,
					"status": flat.status,
					"areas": area_rows,
				}
			)
		tree.append(
			{
				"doctype": "Building",
				"name": building.name,
				"label": building.building_name,
				"building_code": building.building_code,
				"status": building.status,
				"flats": flat_rows,
			}
		)
	return tree


def _payments(scope):
	filters = {"posting_date": ["between", [scope.from_date, scope.to_date]]}
	if scope.owner:
		filters["owner_user"] = scope.owner
	rows, truncated = _fetch_limited(
		"Rent Payment",
		filters,
		["name", "posting_date", "tenant", "amount", "docstatus", "payment_mode"],
		"posting_date desc",
	)
	if not scope.has_location:
		_attach_tenant_names(rows)
		return {"rows": _stringify_dates(rows), "truncated": truncated}

	visible = []
	for payment in rows:
		allocations = frappe.get_all(
			"Invoice Allocation",
			filters={"parent": payment.name, "parenttype": "Rent Payment"},
			fields=["rent_invoice"],
		)
		keep = False
		for allocation in allocations:
			invoice = frappe.db.get_value(
				"Rent Invoice",
				allocation.rent_invoice,
				["owner_user", "building", "flat", "area"],
				as_dict=True,
			)
			if _invoice_in_scope(invoice, scope):
				keep = True
				break
		if keep:
			visible.append(payment)
	_attach_tenant_names(visible)
	return {"rows": _stringify_dates(visible), "truncated": truncated}


def _deposit_transactions(scope):
	filters = {"posting_date": ["between", [scope.from_date, scope.to_date]]}
	if scope.owner:
		filters["owner_user"] = scope.owner
	rows, truncated = _fetch_limited(
		"Deposit Transaction",
		filters,
		["name", "tenant_deposit", "transaction_type", "posting_date", "amount", "docstatus"],
		"posting_date desc",
	)
	if scope.has_location and rows:
		deposit_names = [row.tenant_deposit for row in rows]
		deposits = {
			row.name: row
			for row in frappe.get_all(
				"Tenant Deposit",
				filters={"name": ["in", deposit_names]},
				fields=["name", "building", "flat", "area", "owner_user"],
			)
		}
		kept = []
		for row in rows:
			deposit = deposits.get(row.tenant_deposit)
			if not deposit:
				continue
			if scope.owner and deposit.owner_user != scope.owner:
				continue
			if scope.building and deposit.building != scope.building:
				continue
			if scope.flat and deposit.flat != scope.flat:
				continue
			if scope.area and deposit.area != scope.area:
				continue
			kept.append(row)
		rows = kept
	return {"rows": _stringify_dates(rows), "truncated": truncated}


def _limited_docs(doctype, filters, fields, order_by):
	rows, truncated = _fetch_limited(doctype, filters, fields, order_by)
	if "tenant" in fields:
		_attach_tenant_names(rows)
	return {"rows": _stringify_dates(rows), "truncated": truncated}


def _fetch_limited(doctype, filters, fields, order_by):
	rows = frappe.get_all(
		doctype,
		filters=filters,
		fields=fields,
		order_by=order_by,
		limit_page_length=LIST_LIMIT + 1,
	)
	truncated = len(rows) > LIST_LIMIT
	return rows[:LIST_LIMIT], truncated


def _attach_tenant_names(rows):
	names = _names("Tenant", [row.get("tenant") for row in rows if row.get("tenant")], "tenant_name")
	for row in rows:
		if row.get("tenant"):
			row["tenant_name"] = names.get(row.tenant)


def _names(doctype, ids, fieldname):
	ids = [name for name in ids if name]
	if not ids:
		return {}
	rows = frappe.get_all(doctype, filters={"name": ["in", list(set(ids))]}, fields=["name", fieldname])
	return {row.name: row.get(fieldname) for row in rows}


def _stringify_dates(rows):
	prepared = []
	for row in rows:
		item = {}
		for key, value in row.items():
			if hasattr(value, "isoformat") and not isinstance(value, str):
				item[key] = value.isoformat()
			else:
				item[key] = value
		prepared.append(item)
	return prepared


def _building_rows(scope):
	return frappe.get_all(
		"Building",
		filters=_building_filters(scope),
		fields=["name", "building_name", "building_code", "status", "owner_user"],
		order_by="building_name asc",
	)


def _building_filters(scope):
	filters = {}
	if scope.owner:
		filters["owner_user"] = scope.owner
	if scope.building:
		filters["name"] = scope.building
	elif scope.flat:
		filters["name"] = frappe.db.get_value("Flat", scope.flat, "building")
	elif scope.area:
		filters["name"] = frappe.db.get_value("Area", scope.area, "building")
	return filters


def _flat_filters(scope):
	filters = {}
	if scope.owner:
		filters["owner_user"] = scope.owner
	if scope.flat:
		filters["name"] = scope.flat
	elif scope.area:
		filters["name"] = frappe.db.get_value("Area", scope.area, "flat")
	elif scope.building:
		filters["building"] = scope.building
	return filters


def _area_filters(scope):
	filters = {}
	if scope.owner:
		filters["owner_user"] = scope.owner
	if scope.area:
		filters["name"] = scope.area
	elif scope.flat:
		filters["flat"] = scope.flat
	elif scope.building:
		filters["building"] = scope.building
	return filters


def _bed_filters(scope):
	return _location_filters(scope)


def _location_filters(scope):
	filters = {}
	if scope.owner:
		filters["owner_user"] = scope.owner
	if scope.building:
		filters["building"] = scope.building
	if scope.flat:
		filters["flat"] = scope.flat
	if scope.area:
		filters["area"] = scope.area
	return filters


def _scope_payload(scope):
	return {
		"owner_user": scope.owner,
		"building": scope.building,
		"flat": scope.flat,
		"area": scope.area,
		"from_date": str(scope.from_date),
		"to_date": str(scope.to_date),
		"period_is_default": bool(scope.period_is_default),
		"privileged": bool(scope.privileged),
	}


def _clean(value):
	if value is None:
		return None
	text = str(value).strip()
	return text or None
