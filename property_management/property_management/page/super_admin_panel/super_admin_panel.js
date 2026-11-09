frappe.pages["super-admin-panel"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Super Admin Panel"),
		single_column: true,
	});
	// The query must end in .js. frappe.require reads the extension from the query string.
	frappe.require("/assets/property_management/js/desk_pages.js?v=20261109b.js").then(() => {
		property_management.desk.mount(page, "super-admin");
	});
};

frappe.pages["super-admin-panel"].on_page_show = function () {
	if (window.property_management && property_management.desk && property_management.desk.refresh) {
		property_management.desk.refresh("super-admin");
	}
};
