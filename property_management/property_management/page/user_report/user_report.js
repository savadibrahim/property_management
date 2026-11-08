frappe.pages["user-report"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("User Report"),
		single_column: true,
	});
	frappe.require("/assets/property_management/js/desk_pages.js?v=20261108c").then(() => {
		property_management.desk.mount(page, "user-report");
	});
};

frappe.pages["user-report"].on_page_show = function () {
	if (window.property_management && property_management.desk && property_management.desk.refresh) {
		property_management.desk.refresh("user-report");
	}
};
