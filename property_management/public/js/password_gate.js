// Desk redirect. The server gate in before_request is what actually blocks the session.
// frappe.ready is a website helper and is not defined on the desk, so run directly.
(function () {
	if (window.frappe && frappe.boot && frappe.boot.property_management) {
		const gate = frappe.boot.property_management;
		if (gate.must_change_password && !window.location.pathname.startsWith("/property-password")) {
			window.location.replace("/property-password");
		}
	}
})();

(function () {
	const OWNED_DOCTYPES = [
		"Building",
		"Flat",
		"Area",
		"Bed",
		"Tenant",
		"Bed Allocation",
		"Cash Bank Account",
		"Financial Transaction",
		"Rent Invoice",
		"Rent Payment",
		"Tenant Deposit",
		"Deposit Transaction",
		"Property Expense",
		"Monthly Revenue",
		"Rent Billing Log",
	];

	function is_privileged_user() {
		const roles = frappe.user_roles || [];
		return (
			frappe.session.user === "Administrator" ||
			roles.includes("Property Super Admin") ||
			roles.includes("System Manager")
		);
	}

	function pin_owner_user_default(doctype) {
		if (is_privileged_user() || !OWNED_DOCTYPES.includes(doctype)) {
			return;
		}
		if (!frappe.meta || !frappe.meta.get_docfield) {
			return;
		}
		const df = frappe.meta.get_docfield(doctype, "owner_user");
		if (!df) {
			return;
		}
		// Match the field default so a new form shows this user and link validation keeps it.
		df.default = frappe.session.user;
		df.__default_value = frappe.session.user;
		df.read_only = 1;
	}

	function install_owner_prefill() {
		if (!frappe.model || frappe.model._property_owner_prefill) {
			return;
		}
		frappe.model._property_owner_prefill = true;

		const original_get_new_doc = frappe.model.get_new_doc;
		frappe.model.get_new_doc = function (doctype) {
			pin_owner_user_default(doctype);
			const doc = original_get_new_doc.apply(this, arguments);
			if (
				doc &&
				!is_privileged_user() &&
				OWNED_DOCTYPES.includes(doctype) &&
				doc.owner_user !== frappe.session.user
			) {
				doc.owner_user = frappe.session.user;
			}
			return doc;
		};

		const original_with_doctype = frappe.model.with_doctype;
		frappe.model.with_doctype = function (doctype, callback, async) {
			const user_callback = typeof callback === "function" ? callback : null;
			const result = original_with_doctype.call(
				this,
				doctype,
				user_callback
					? function () {
							pin_owner_user_default(doctype);
							return user_callback.apply(this, arguments);
						}
					: null,
				async
			);
			if (result && typeof result.then === "function") {
				return result.then((value) => {
					pin_owner_user_default(doctype);
					return value;
				});
			}
			pin_owner_user_default(doctype);
			return result;
		};
	}

	function remember_owner_name(user) {
		if (!user || !frappe.utils || !frappe.user_info) {
			return;
		}
		const known = frappe.utils.get_link_title("User", user);
		if (known && known !== user) {
			return;
		}
		const info = frappe.user_info(user);
		if (info && info.fullname && info.fullname !== user) {
			frappe.utils.add_link_title("User", user, info.fullname);
		}
	}

	function show_owner_name(frm) {
		if (!frm || !frm.doc || !frm.fields_dict || !frm.fields_dict.owner_user) {
			return;
		}
		remember_owner_name(frm.doc.owner_user);
		const control = frm.fields_dict.owner_user;
		if (typeof control.set_disp_area === "function") {
			control.set_disp_area(frm.doc.owner_user);
		}
		const shows_title = control.is_title_link && control.is_title_link();
		if (shows_title && typeof control.set_link_title === "function") {
			control.set_link_title(frm.doc.owner_user);
		}
	}

	function scope_owner_user_field(frm) {
		if (!frm || !frm.fields_dict || !frm.fields_dict.owner_user) {
			return;
		}
		show_owner_name(frm);
		if (is_privileged_user()) {
			return;
		}
		const current_user = frappe.session.user;
		pin_owner_user_default(frm.doctype);
		frm.set_query("owner_user", () => ({
			filters: { name: current_user },
		}));
		if (frm.is_new() && frm.doc.owner_user !== current_user) {
			frm.set_value("owner_user", current_user);
		}
		frm.set_df_property("owner_user", "read_only", 1);
	}

	install_owner_prefill();
	$(document).on("form-load", (_event, frm) => {
		if (!frm || is_privileged_user() || !OWNED_DOCTYPES.includes(frm.doctype) || !frm.is_new()) {
			return;
		}
		pin_owner_user_default(frm.doctype);
		if (frm.doc.owner_user !== frappe.session.user) {
			frm.doc.owner_user = frappe.session.user;
		}
	});

	if (frappe.ui && frappe.ui.form && frappe.ui.form.on) {
		OWNED_DOCTYPES.forEach((doctype) => {
			frappe.ui.form.on(doctype, {
				setup(frm) {
					scope_owner_user_field(frm);
				},
				onload(frm) {
					scope_owner_user_field(frm);
				},
				refresh(frm) {
					scope_owner_user_field(frm);
				},
			});
		});
	}

	frappe.listview_settings = frappe.listview_settings || {};
	OWNED_DOCTYPES.forEach((doctype) => {
		const existing = frappe.listview_settings[doctype] || {};
		const previous_onload = existing.onload;
		existing.onload = function (listview) {
			if (typeof previous_onload === "function") {
				previous_onload.call(this, listview);
			}
			if (
				!is_privileged_user() &&
				listview &&
				listview.page &&
				listview.page.fields_dict &&
				listview.page.fields_dict.owner_user
			) {
				const owner_filter = listview.page.fields_dict.owner_user;
				owner_filter.get_query = () => ({
					filters: { name: frappe.session.user },
				});
			}
		};
		frappe.listview_settings[doctype] = existing;
	});
})();

