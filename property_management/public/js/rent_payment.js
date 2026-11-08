frappe.ui.form.on("Rent Payment", {
	refresh(frm) {
		frm.set_query("rent_invoice", "allocations", () => {
			if (!frm.doc.tenant) {
				return { filters: { name: ["=", ""] } };
			}
			return {
				filters: {
					tenant: frm.doc.tenant,
					docstatus: 1,
					status: ["in", ["Unpaid", "Partly Paid"]],
				},
			};
		});
		if (frm.doc.docstatus !== 0) {
			return;
		}
		frm.add_custom_button(__("Open Invoice"), () => fill_open_invoices(frm));
	},
});

frappe.ui.form.on("Invoice Allocation", {
	rent_invoice(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.rent_invoice) {
			frappe.model.set_value(cdt, cdn, "allocated_amount", 0);
			return;
		}
		frappe.db.get_value("Rent Invoice", row.rent_invoice, "outstanding").then((response) => {
			const outstanding = flt((response.message || {}).outstanding);
			frappe.model.set_value(cdt, cdn, "allocated_amount", outstanding);
			if (!flt(frm.doc.amount)) {
				frm.set_value("amount", allocation_total(frm));
			}
		});
	},
});

function fill_open_invoices(frm) {
	if (!frm.doc.tenant) {
		frappe.msgprint(__("Choose a tenant first."));
		return;
	}
	frappe.call({
		method: "property_management.property_management.doctype.rent_payment.rent_payment.open_invoices",
		args: { tenant: frm.doc.tenant },
		callback(response) {
			const invoices = response.message || [];
			if (!invoices.length) {
				frappe.msgprint(__("This tenant has no open invoice."));
				return;
			}
			frm.clear_table("allocations");
			invoices.forEach((invoice) => {
				const row = frm.add_child("allocations");
				row.rent_invoice = invoice.name;
				row.allocated_amount = flt(invoice.outstanding);
			});
			// Allocations have to add up to the payment, so an empty amount follows the invoices.
			if (!flt(frm.doc.amount)) {
				frm.set_value("amount", allocation_total(frm));
			}
			frm.refresh_field("allocations");
		},
	});
}

function allocation_total(frm) {
	return (frm.doc.allocations || []).reduce((total, row) => total + flt(row.allocated_amount), 0);
}
