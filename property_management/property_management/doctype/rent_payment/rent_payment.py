import frappe
from frappe import _
from frappe.utils import flt, getdate

from property_management.finance import (
	allow_reversal_transaction_link,
	apply_invoice_allocation,
	post_financial_transaction,
)
from property_management.hierarchy import OwnedDocument, apply_owner, require_readable


class RentPayment(OwnedDocument):
	def validate(self):
		apply_owner(self)
		require_readable("Tenant", self.tenant)
		tenant_owner = frappe.db.get_value("Tenant", self.tenant, "owner_user")
		if tenant_owner != self.owner_user:
			frappe.throw(_("That tenant belongs to another user."), frappe.PermissionError)
		if flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero."))
		if self.posting_date:
			self.posting_date = getdate(self.posting_date)
		if self.name and not self.payment_number:
			self.payment_number = self.name
		self._require_cash_account()
		if self.docstatus == 0:
			self._validate_allocations()

	def before_submit(self):
		self._validate_allocations()
		if not self.payment_number:
			self.payment_number = self.name

	def on_submit(self):
		for row in self.allocations:
			apply_invoice_allocation(row.rent_invoice, row.allocated_amount)
			invoice = frappe.db.get_value(
				"Rent Invoice",
				row.rent_invoice,
				["tenant", "building", "flat", "area", "bed", "owner_user"],
				as_dict=True,
			)
			post_financial_transaction(
				transaction_type="Rent Received",
				amount=row.allocated_amount,
				owner_user=self.owner_user,
				posting_date=self.posting_date,
				tenant=self.tenant,
				building=invoice.building,
				flat=invoice.flat,
				area=invoice.area,
				bed=invoice.bed,
				reference_doctype=self.doctype,
				reference_name=self.name,
				payment_mode=self.payment_mode,
				payment_reference=self.payment_reference,
				cash_bank_account=self.cash_bank_account,
				remarks=_("Rent payment {0} against {1}").format(self.name, row.rent_invoice),
			)

	def on_cancel(self):
		"""Restore invoice balances and append Payment Reversal rows. The receipt rows stay."""
		allow_reversal_transaction_link(self)
		for row in self.allocations:
			apply_invoice_allocation(row.rent_invoice, -flt(row.allocated_amount))
			invoice = frappe.db.get_value(
				"Rent Invoice",
				row.rent_invoice,
				["building", "flat", "area", "bed"],
				as_dict=True,
			)
			post_financial_transaction(
				transaction_type="Payment Reversal",
				amount=-flt(row.allocated_amount),
				owner_user=self.owner_user,
				posting_date=self.posting_date,
				tenant=self.tenant,
				building=invoice.building,
				flat=invoice.flat,
				area=invoice.area,
				bed=invoice.bed,
				reference_doctype=self.doctype,
				reference_name=self.name,
				payment_mode=self.payment_mode,
				payment_reference=self.payment_reference,
				cash_bank_account=self.cash_bank_account,
				remarks=_("Reversal of rent payment {0} against {1}").format(self.name, row.rent_invoice),
			)

	def on_trash(self):
		if self.docstatus == 1:
			frappe.throw(_("A submitted rent payment cannot be deleted."))

	def _require_cash_account(self):
		if self.payment_mode in ("Cash", "Bank Transfer") and not self.cash_bank_account:
			frappe.throw(_("Cash/Bank Account is required for this payment mode."))
		if not self.cash_bank_account:
			return
		require_readable("Cash Bank Account", self.cash_bank_account)
		account_owner, account_type, status = frappe.db.get_value(
			"Cash Bank Account", self.cash_bank_account, ["owner_user", "account_type", "status"]
		)
		if account_owner != self.owner_user:
			frappe.throw(_("That cash or bank account belongs to another user."), frappe.PermissionError)
		if status != "Active":
			frappe.throw(_("Cash/Bank Account {0} is not active.").format(self.cash_bank_account))
		if self.payment_mode == "Cash" and account_type != "Cash":
			frappe.throw(_("Choose a Cash account for a cash payment."))
		if self.payment_mode == "Bank Transfer" and account_type != "Bank":
			frappe.throw(_("Choose a Bank account for a bank transfer."))

	def _validate_allocations(self):
		if not self.allocations:
			frappe.throw(_("Allocate this payment to at least one rent invoice."))
		seen = set()
		total = 0.0
		for row in self.allocations:
			if row.rent_invoice in seen:
				frappe.throw(_("Invoice {0} is allocated more than once.").format(row.rent_invoice))
			seen.add(row.rent_invoice)
			if flt(row.allocated_amount) <= 0:
				frappe.throw(_("Allocated amount must be greater than zero."))
			require_readable("Rent Invoice", row.rent_invoice)
			invoice = frappe.db.get_value(
				"Rent Invoice",
				row.rent_invoice,
				["tenant", "owner_user", "docstatus", "outstanding", "status"],
				as_dict=True,
			)
			if not invoice or invoice.docstatus != 1 or invoice.status == "Cancelled":
				frappe.throw(_("Rent Invoice {0} is not an open submitted invoice.").format(row.rent_invoice))
			if invoice.owner_user != self.owner_user:
				frappe.throw(_("Rent Invoice {0} belongs to another user.").format(row.rent_invoice), frappe.PermissionError)
			if invoice.tenant != self.tenant:
				frappe.throw(_("Rent Invoice {0} is for a different tenant.").format(row.rent_invoice))
			if flt(row.allocated_amount) > flt(invoice.outstanding):
				frappe.throw(
					_("Cannot allocate {0} to {1}. Outstanding is {2}.").format(
						row.allocated_amount, row.rent_invoice, invoice.outstanding
					)
				)
			total += flt(row.allocated_amount)
		if abs(total - flt(self.amount)) > 0.0001:
			frappe.throw(
				_("Allocated amounts must equal the payment amount. Over-allocation and unallocated cash are not allowed.")
			)


@frappe.whitelist()
def open_invoices(tenant):
	"""Open rent invoices for this tenant, oldest first, with the amount still due."""
	if not tenant:
		frappe.throw(_("Choose a tenant first."))
	require_readable("Tenant", tenant)
	return frappe.get_all(
		"Rent Invoice",
		filters={
			"tenant": tenant,
			"docstatus": 1,
			"status": ["in", ["Unpaid", "Partly Paid"]],
			"outstanding": [">", 0],
		},
		fields=["name", "invoice_number", "billing_month", "outstanding"],
		order_by="billing_date asc, creation asc",
		limit=500,
	)
