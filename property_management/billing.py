"""Calendar-month rent billing.

Each Monthly Revenue schedule raises its invoice on the day of its start date.
A shorter month uses the last day. Property Settings still controls proration and
how many days after that date the invoice is due. The daily scheduler generates
one invoice per occupied month and catches up missed months. It does not change
invoices that were already submitted.
"""

import calendar
from datetime import date

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

from property_management.permissions import is_privileged, is_property_user


def generate_due_rent_invoices(as_of=None, monthly_revenue=None, manual=False, owner=None):
	"""Create missing rent invoices for occupied months whose start day has arrived."""
	as_of = getdate(as_of) if as_of else getdate(today())
	created = skipped = failed = 0
	invoices = []
	for schedule_name in _schedules_to_scan(monthly_revenue, manual=manual, owner=owner):
		outcome = _generate_for_schedule(schedule_name, as_of, log_skips=bool(monthly_revenue or manual))
		created += outcome["created"]
		skipped += outcome["skipped"]
		failed += outcome["failed"]
		invoices.extend(outcome["invoices"])
	return {"created": created, "skipped": skipped, "failed": failed, "invoices": invoices}


@frappe.whitelist()
def generate_rent_invoices(as_of=None, monthly_revenue=None):
	"""Manual run for the signed-in owner, or every schedule for a Property Super Admin."""
	_require_billing_user()
	if monthly_revenue:
		# get_doc enforces owner isolation for a Property User.
		frappe.get_doc("Monthly Revenue", monthly_revenue)
	return generate_due_rent_invoices(as_of=as_of, monthly_revenue=monthly_revenue, manual=True)


@frappe.whitelist()
def revise_rent(monthly_revenue, effective_from, monthly_rent, remarks=None):
	"""Append an effective-dated rent. Submitted invoices are left as they were."""
	_require_billing_user()
	doc = frappe.get_doc("Monthly Revenue", monthly_revenue)
	doc.check_permission("write")
	effective_from = getdate(effective_from)
	amount = flt(monthly_rent)
	if amount <= 0:
		frappe.throw(_("Monthly rent must be greater than zero."))
	if any(getdate(row.effective_from) == effective_from for row in doc.revisions):
		frappe.throw(_("A rent revision already starts on {0}.").format(effective_from))
	doc.append(
		"revisions",
		{"effective_from": effective_from, "monthly_rent": amount, "remarks": remarks},
	)
	doc.save()
	return {"name": doc.name, "effective_from": str(effective_from), "monthly_rent": amount}


def sync_monthly_revenue(allocation):
	"""Open a schedule for an active allocation, and stop it on the vacating date.

	Stopping does not delete invoices or change outstanding amounts.
	"""
	if not allocation or not allocation.get("name"):
		return
	existing = frappe.db.get_value("Monthly Revenue", {"bed_allocation": allocation.name}, "name")
	if allocation.allocation_status == "Vacated":
		if existing:
			frappe.db.set_value(
				"Monthly Revenue",
				existing,
				{"end_date": allocation.vacating_date, "status": "Stopped"},
				update_modified=True,
			)
		return
	if allocation.allocation_status != "Active" or not cint(allocation.generate_rent):
		return
	if existing:
		return
	start = allocation.billing_start_date or allocation.allocation_date
	doc = frappe.new_doc("Monthly Revenue")
	doc.bed_allocation = allocation.name
	doc.owner_user = allocation.owner_user
	doc.frequency = "Monthly"
	doc.status = "Active"
	doc.start_date = getdate(start) if start else getdate(today())
	doc.append(
		"revisions",
		{
			"effective_from": doc.start_date,
			"monthly_rent": flt(allocation.monthly_rent),
		},
	)
	doc.insert()


def _require_billing_user():
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("You need to be logged in to generate rent."), frappe.PermissionError)
	if is_privileged(user) or is_property_user(user):
		return
	frappe.throw(_("You are not allowed to generate rent."), frappe.PermissionError)


def _schedules_to_scan(monthly_revenue, manual, owner=None):
	if monthly_revenue:
		return [monthly_revenue]
	filters = {}
	if owner:
		filters["owner_user"] = owner
	elif manual and not is_privileged():
		filters["owner_user"] = frappe.session.user
	return frappe.get_all("Monthly Revenue", filters=filters, pluck="name")


def _generate_for_schedule(schedule_name, as_of, log_skips):
	created = skipped = failed = 0
	invoices = []
	schedule = frappe.get_doc("Monthly Revenue", schedule_name)
	allocation = frappe.db.get_value(
		"Bed Allocation",
		schedule.bed_allocation,
		["name", "allocation_status", "generate_rent", "vacating_date", "owner_user"],
		as_dict=True,
	)
	reason = _skip_reason(schedule, allocation)
	if reason:
		if log_skips:
			_log(schedule, None, "Skipped", reason)
			skipped += 1
		return {"created": 0, "skipped": skipped, "failed": 0, "invoices": []}

	for period in _due_periods(schedule, allocation, as_of):
		billing_key = f"{schedule.bed_allocation}-{period['billing_month']}"
		if frappe.db.exists("Rent Invoice", {"billing_key": billing_key, "docstatus": ["!=", 2]}):
			skipped += 1
			if log_skips and not _log_exists(schedule.name, period["billing_month"], "Success"):
				_log(schedule, period["billing_month"], "Skipped", _("Invoice already exists."))
			continue
		savepoint = "rentbill" + frappe.generate_hash(length=8)
		try:
			frappe.db.savepoint(savepoint)
			invoice = _create_invoice(schedule, period)
			_log(schedule, period["billing_month"], "Success", _("Rent invoice {0}.").format(invoice), invoice)
			created += 1
			invoices.append(invoice)
		except Exception as exc:
			frappe.db.rollback(save_point=savepoint)
			if _is_duplicate(exc) or frappe.db.exists("Rent Invoice", {"billing_key": billing_key}):
				skipped += 1
				if log_skips:
					_log(schedule, period["billing_month"], "Skipped", _("Invoice already exists."))
				continue
			failed += 1
			_log(schedule, period["billing_month"], "Failed", frappe.get_traceback() or str(exc))
	return {"created": created, "skipped": skipped, "failed": failed, "invoices": invoices}


def _skip_reason(schedule, allocation):
	if not allocation:
		return _("Bed allocation was not found.")
	if schedule.frequency != "Monthly":
		return _("Only monthly billing is generated.")
	if allocation.allocation_status == "Active" and cint(allocation.generate_rent):
		return None
	if allocation.allocation_status == "Vacated" and (schedule.end_date or allocation.vacating_date):
		return None
	if allocation.allocation_status == "Active":
		return _("Rent generation is turned off.")
	return _("Allocation is not active.")


def _due_periods(schedule, allocation, as_of):
	settings = _billing_settings()
	start = getdate(schedule.start_date)
	end = getdate(schedule.end_date or allocation.vacating_date) if (schedule.end_date or allocation.vacating_date) else None
	if end and end < start:
		return
	month = start.replace(day=1)
	last_month = (end or as_of).replace(day=1)
	while month <= last_month:
		period = _period(month, start, end, as_of, settings, schedule)
		if period:
			yield period
		month = _next_month(month)


def _period(month, start, end, as_of, settings, schedule):
	month_start = month
	month_end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
	occupied_start = max(month_start, start)
	occupied_end = min(month_end, end) if end else month_end
	if occupied_start > occupied_end:
		return None
	# The schedule start date sets the day. 31 January bills on 28 or 29 February.
	billing_day = min(start.day, month_end.day)
	billing_date = date(month.year, month.month, billing_day)
	if as_of < max(billing_date, occupied_start):
		return None
	days_in_month = month_end.day
	occupied_days = (occupied_end - occupied_start).days + 1
	rate = _rent_on(schedule, occupied_start)
	if settings.prorate and occupied_days < days_in_month:
		amount = flt(rate * occupied_days / days_in_month, 2)
	else:
		amount = flt(rate, 2)
	anchor = max(billing_date, occupied_start)
	return {
		"billing_month": f"{month.year:04d}-{month.month:02d}",
		"billing_date": billing_date,
		"due_date": add_days(anchor, settings.due_days),
		"rent_amount": amount,
		"occupied_start": occupied_start,
	}


def _rent_on(schedule, day):
	chosen = None
	for row in schedule.revisions or []:
		if not row.effective_from:
			continue
		if getdate(row.effective_from) <= day and (chosen is None or getdate(row.effective_from) >= getdate(chosen.effective_from)):
			chosen = row
	return flt(chosen.monthly_rent) if chosen else 0


def _create_invoice(schedule, period):
	if flt(period["rent_amount"]) <= 0:
		frappe.throw(_("Monthly rent for {0} is not greater than zero.").format(period["billing_month"]))
	invoice = frappe.new_doc("Rent Invoice")
	invoice.bed_allocation = schedule.bed_allocation
	invoice.owner_user = schedule.owner_user
	invoice.billing_month = period["billing_month"]
	invoice.billing_date = period["billing_date"]
	invoice.due_date = period["due_date"]
	invoice.rent_amount = period["rent_amount"]
	invoice.insert()
	invoice.submit()
	return invoice.name


def _billing_settings():
	settings = frappe.get_single("Property Settings")
	due = settings.due_days_after_billing
	due_days = 7 if due is None or due == "" else cint(due)
	if due_days < 0:
		due_days = 7
	return frappe._dict(
		prorate=cint(settings.prorate_partial_months) if settings.prorate_partial_months is not None else 1,
		due_days=due_days,
	)


def _log(schedule, billing_month, outcome, message, rent_invoice=None):
	if outcome == "Skipped" and _log_exists(schedule.name, billing_month, "Skipped"):
		return
	row = frappe.new_doc("Rent Billing Log")
	row.monthly_revenue = schedule.name
	row.bed_allocation = schedule.bed_allocation
	row.owner_user = schedule.owner_user
	row.billing_month = billing_month
	row.outcome = outcome
	row.message = (message or "")[:1400]
	row.rent_invoice = rent_invoice
	row.insert(ignore_permissions=True)


def _log_exists(schedule_name, billing_month, outcome):
	return frappe.db.exists(
		"Rent Billing Log",
		{"monthly_revenue": schedule_name, "billing_month": billing_month, "outcome": outcome},
	)


def _is_duplicate(exc):
	return exc.__class__.__name__ in {"DuplicateEntryError", "UniqueValidationError"}


def _next_month(month):
	if month.month == 12:
		return date(month.year + 1, 1, 1)
	return date(month.year, month.month + 1, 1)
