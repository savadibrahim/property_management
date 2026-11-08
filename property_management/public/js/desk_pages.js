frappe.provide("property_management.desk");

property_management.desk.pages = {};

property_management.desk.mount = function (page, mode) {
	const state = {
		mode,
		page,
		blocked: false,
		filters: {
			owner_user: "",
			building: "",
			flat: "",
			area: "",
			from_date: "",
			to_date: "",
		},
		accounts: [],
		options: { buildings: [], flats: [], areas: [] },
		overview: null,
		operations: null,
	};
	property_management.desk.pages[mode] = state;
	state.root = $('<div class="pm-desk"></div>').appendTo(page.main);

	if (mode === "super-admin" && !property_management.desk.is_privileged()) {
		state.blocked = true;
		state.root.append(
			property_management.desk.banner(
				__("Super Admin Panel is limited to the Property Super Admin role."),
				"pm-error"
			)
		);
		return;
	}
	if (
		mode === "user-report" &&
		!property_management.desk.is_privileged() &&
		!property_management.desk.is_property_user()
	) {
		state.blocked = true;
		state.root.append(
			property_management.desk.banner(__("User Report is limited to property accounts."), "pm-error")
		);
		return;
	}
	if (property_management.desk.must_change_password()) {
		state.blocked = true;
		state.root.append(
			property_management.desk.banner(
				__("Change the temporary password before using this page.") +
					' <a href="/property-password">' +
					__("Set a new password") +
					"</a>",
				"pm-banner"
			)
		);
		return;
	}

	state.root.append(property_management.desk.lead(mode));
	state.filters_el = $('<div class="pm-filters"></div>').appendTo(state.root);
	state.status_el = $('<div class="pm-status"></div>').appendTo(state.root);
	state.kpis_el = $('<div class="pm-kpis"></div>').appendTo(state.root);
	if (mode === "super-admin") {
		state.accounts_el = $('<div class="pm-accounts"></div>').appendTo(state.root);
		state.users_el = $('<div class="pm-users"></div>').appendTo(state.root);
	}
	if (mode === "user-report") {
		state.nav_el = $('<div class="pm-nav"></div>').appendTo(state.root);
		state.ops_el = $('<div class="pm-ops"></div>').appendTo(state.root);
		property_management.desk.render_nav(state);
	}
	state.measures_el = $('<div class="pm-measures"></div>').appendTo(state.root);
	state.root.on("submit", "[data-pm-create]", (event) => {
		event.preventDefault();
		property_management.desk.create_user(state);
	});
	state.root.on("click", "[data-pm-action]", (event) => {
		event.preventDefault();
		property_management.desk.on_action(state, event.currentTarget);
	});
	state.root.on("change", "[data-pm-filter]", () => {
		property_management.desk.read_filters(state);
		property_management.desk.load(state);
	});
	property_management.desk.load(state);
};

property_management.desk.refresh = function (mode) {
	const state = property_management.desk.pages[mode];
	if (state && !state.blocked) {
		property_management.desk.load(state);
	}
};

property_management.desk.load = function (state) {
	state.request_id = (state.request_id || 0) + 1;
	const request_id = state.request_id;
	state.status_el.html(
		'<p class="pm-note">' + __("Loading figures from the database…") + "</p>"
	);
	const args = property_management.desk.filter_args(state);
	const accounts_call = property_management.desk.is_privileged()
		? property_management.desk.call("property_management.desk.list_property_accounts")
		: Promise.resolve([]);
	const operations_call =
		state.mode === "user-report"
			? property_management.desk.call("property_management.desk.get_operations", args)
			: Promise.resolve(null);
	Promise.all([
		property_management.desk.call("property_management.desk.get_filter_options", args),
		property_management.desk.call("property_management.desk.get_overview", args),
		accounts_call,
		operations_call,
	])
		.then((results) => {
			if (state.request_id !== request_id) {
				return;
			}
			state.options = results[0] || { buildings: [], flats: [], areas: [] };
			state.overview = results[1] || null;
			state.accounts = results[2] || [];
			state.operations = results[3];
			if (state.overview && state.overview.scope && !state.filters.from_date) {
				state.filters.from_date = state.overview.scope.from_date;
				state.filters.to_date = state.overview.scope.to_date;
			}
			state.status_el.empty();
			property_management.desk.render_filters(state);
			property_management.desk.render_kpis(state);
			if (state.mode === "super-admin") {
				property_management.desk.render_accounts(state);
				property_management.desk.render_users(state);
			}
			if (state.mode === "user-report") {
				property_management.desk.render_operations(state);
			}
			property_management.desk.render_measures(state);
		})
		.catch((error) => {
			if (state.request_id !== request_id) {
				return;
			}
			state.kpis_el.empty();
			state.status_el.html(
				'<div class="pm-error">' +
					property_management.desk.esc(property_management.desk.error_text(error)) +
					"</div>"
			);
		});
};

property_management.desk.call = function (method, args) {
	return frappe
		.call({
			method,
			args: args || {},
		})
		.then((response) => response.message);
};

property_management.desk.filter_args = function (state) {
	return {
		owner_user: state.filters.owner_user || undefined,
		building: state.filters.building || undefined,
		flat: state.filters.flat || undefined,
		area: state.filters.area || undefined,
		from_date: state.filters.from_date || undefined,
		to_date: state.filters.to_date || undefined,
	};
};

property_management.desk.read_filters = function (state) {
	state.filters_el.find("[data-pm-filter]").each(function () {
		state.filters[this.dataset.pmFilter] = this.value || "";
	});
	const building = state.options.buildings.find((row) => row.name === state.filters.building);
	if (state.filters.building && !building) {
		state.filters.building = "";
		state.filters.flat = "";
		state.filters.area = "";
	}
	const flat = state.options.flats.find((row) => row.name === state.filters.flat);
	if (state.filters.flat && (!flat || (state.filters.building && flat.building !== state.filters.building))) {
		state.filters.flat = "";
		state.filters.area = "";
	}
	const area = state.options.areas.find((row) => row.name === state.filters.area);
	if (state.filters.area && (!area || (state.filters.flat && area.flat !== state.filters.flat))) {
		state.filters.area = "";
	}
};

property_management.desk.render_filters = function (state) {
	const privileged = state.overview && state.overview.scope && state.overview.scope.privileged;
	const user_options = ['<option value="">' + __("All property users") + "</option>"];
	(state.accounts || []).forEach((account) => {
		user_options.push(
			'<option value="' +
				property_management.desk.esc(account.user) +
				'">' +
				property_management.desk.esc(account.full_name + " · " + account.mobile_number) +
				"</option>"
		);
	});
	const building_options = ['<option value="">' + __("All buildings") + "</option>"].concat(
		(state.options.buildings || []).map(
			(row) =>
				'<option value="' +
				property_management.desk.esc(row.name) +
				'">' +
				property_management.desk.esc(row.building_name) +
				"</option>"
		)
	);
	const flat_options = ['<option value="">' + __("All flats") + "</option>"].concat(
		(state.options.flats || []).map(
			(row) =>
				'<option value="' +
				property_management.desk.esc(row.name) +
				'">' +
				property_management.desk.esc(row.flat_number) +
				"</option>"
		)
	);
	const area_options = ['<option value="">' + __("All areas") + "</option>"].concat(
		(state.options.areas || []).map(
			(row) =>
				'<option value="' +
				property_management.desk.esc(row.name) +
				'">' +
				property_management.desk.esc(row.area_name) +
				"</option>"
		)
	);
	const html = [];
	if (privileged) {
		html.push(property_management.desk.select_field("owner_user", __("Property user"), user_options.join("")));
	}
	html.push(property_management.desk.select_field("building", __("Building"), building_options.join("")));
	html.push(property_management.desk.select_field("flat", __("Flat"), flat_options.join("")));
	html.push(property_management.desk.select_field("area", __("Area"), area_options.join("")));
	html.push(
		'<label>' +
			__("From") +
			'<input type="date" data-pm-filter="from_date" value="' +
			property_management.desk.esc(state.filters.from_date) +
			'"></label>'
	);
	html.push(
		'<label>' +
			__("To") +
			'<input type="date" data-pm-filter="to_date" value="' +
			property_management.desk.esc(state.filters.to_date) +
			'"></label>'
	);
	html.push(
		'<div class="pm-actions"><button type="button" class="btn btn-primary btn-sm" data-pm-action="apply">' +
			__("Apply") +
			'</button><button type="button" class="btn btn-default btn-sm" data-pm-action="reset-filters">' +
			__("This month") +
			"</button></div>"
	);
	state.filters_el.html(html.join(""));
	state.filters_el.find("[data-pm-filter]").each(function () {
		if (state.filters[this.dataset.pmFilter]) {
			this.value = state.filters[this.dataset.pmFilter];
		}
	});
};

property_management.desk.select_field = function (name, label, options) {
	return (
		"<label>" +
		property_management.desk.esc(label) +
		'<select data-pm-filter="' +
		name +
		'">' +
		options +
		"</select></label>"
	);
};

property_management.desk.render_kpis = function (state) {
	const overview = state.overview || {};
	const money = overview.money || {};
	const occupancy = overview.occupancy || {};
	const profit = Number(money.operating_profit || 0);
	const cards = [
		[__("Buildings"), occupancy.buildings],
		[__("Flats"), occupancy.flats],
		[__("Areas"), occupancy.areas],
		[__("Beds"), occupancy.beds],
		[__("Occupied"), occupancy.beds_occupied],
		[__("Vacant"), occupancy.beds_vacant],
		[__("Maintenance"), occupancy.beds_maintenance],
		[__("Occupancy"), property_management.desk.percent(occupancy.occupancy_rate)],
		[__("Monthly fixed rent"), property_management.desk.money(money.monthly_fixed_rent)],
		[__("Recognized rent"), property_management.desk.money(money.recognized_rental_revenue)],
		[__("Rent collected"), property_management.desk.money(money.rent_collected)],
		[__("Allocated receipts"), property_management.desk.money(money.allocated_receipts)],
		[__("Advances"), property_management.desk.money(money.advances)],
		[__("Outstanding in period"), property_management.desk.money(money.outstanding_in_period)],
		[__("All open receivables"), property_management.desk.money(money.outstanding_open)],
		[__("Held deposits"), property_management.desk.money(money.held_deposits)],
		[__("Deposit transferred"), property_management.desk.money(money.deposit_transferred_to_revenue)],
		[__("Expenses"), property_management.desk.money(money.expenses)],
	];
	const profit_class = profit < 0 ? " loss" : profit > 0 ? " profit" : "";
	const html = cards
		.map(
			(card) =>
				'<article class="pm-kpi"><span>' +
				property_management.desk.esc(card[0]) +
				"</span><strong>" +
				property_management.desk.esc(card[1] == null ? "0" : card[1]) +
				"</strong></article>"
		)
		.join("");
	state.kpis_el.html(
		html +
			'<article class="pm-kpi' +
			profit_class +
			'"><span>' +
			__("Operating profit") +
			"</span><strong>" +
			property_management.desk.esc(property_management.desk.money(profit)) +
			"</strong></article>"
	);
};

property_management.desk.render_accounts = function (state) {
	const rows = (state.accounts || [])
		.map((account) => {
			const badges = [];
			if (!account.enabled) {
				badges.push('<span class="pm-badge off">' + __("Deactivated") + "</span>");
			} else {
				badges.push('<span class="pm-badge">' + __("Enabled") + "</span>");
			}
			if (account.expired) {
				badges.push('<span class="pm-badge warn">' + __("Expired") + "</span>");
			}
			if (account.must_change_password) {
				badges.push('<span class="pm-badge warn">' + __("Must change password") + "</span>");
			}
			return (
				"<tr><td>" +
				property_management.desk.esc(account.full_name) +
				"</td><td>" +
				property_management.desk.esc(account.mobile_number) +
				"</td><td>" +
				property_management.desk.esc(account.account_expiry || "") +
				"</td><td>" +
				badges.join(" ") +
				'</td><td class="pm-actions">' +
				property_management.desk.button("reset-password", __("Reset password"), {
					user: account.user,
				}) +
				property_management.desk.button("set-expiry", __("Expiry"), {
					user: account.user,
					expiry: account.account_expiry || "",
				}) +
				property_management.desk.button("set-active", account.enabled ? __("Deactivate") : __("Activate"), {
					user: account.user,
					active: account.enabled ? "0" : "1",
				}) +
				property_management.desk.button("open-doc", __("Profile"), {
					doctype: "Property User Profile",
					name: account.user,
				}) +
				"</td></tr>"
			);
		})
		.join("");
	state.accounts_el.html(
		'<section class="pm-section"><h3>' +
			__("Property accounts") +
			"</h3><p class=\"pm-note\">" +
			__(
				"The mobile number is the username. The password is sent once to Frappe and is not shown again."
			) +
			'</p><form class="pm-create" data-pm-create autocomplete="off"><div class="pm-filters">' +
			"<label>" +
			__("Full name") +
			'<input name="full_name" required autocomplete="off"></label><label>' +
			__("Mobile number") +
			'<input name="mobile_number" inputmode="numeric" required autocomplete="off"></label><label>' +
			__("Temporary password") +
			'<input name="password" type="password" required autocomplete="new-password"></label><label>' +
			__("Confirm password") +
			'<input name="confirm_password" type="password" required autocomplete="new-password"></label><label>' +
			__("Account expiry") +
			'<input name="account_expiry" type="date" required></label><label class="pm-check"><input name="enabled" type="checkbox" checked> ' +
			__("Enabled") +
			"</label></div>" +
			'<div class="pm-actions"><button type="button" class="btn btn-primary btn-sm" data-pm-action="create-user">' +
			__("Create property user") +
			"</button></div></form>" +
			(rows
				? '<div class="pm-table-wrap"><table class="pm-table"><thead><tr><th>' +
					__("Name") +
					"</th><th>" +
					__("Username") +
					"</th><th>" +
					__("Expiry") +
					"</th><th>" +
					__("Status") +
					"</th><th>" +
					__("Actions") +
					"</th></tr></thead><tbody>" +
					rows +
					"</tbody></table></div>"
				: '<p class="pm-note">' + __("No property users yet.") + "</p>") +
			"</section>"
	);
};

property_management.desk.render_users = function (state) {
	const users = (state.overview && state.overview.users) || [];
	const rows = users
		.map(
			(user) =>
				"<tr><td><button type=\"button\" class=\"btn btn-link btn-sm\" data-pm-action=\"filter-user\" data-user=\"" +
				property_management.desk.esc(user.user) +
				'">' +
				property_management.desk.esc(user.full_name) +
				"</button><div class=\"pm-note\">" +
				property_management.desk.esc(user.mobile_number) +
				"</div></td><td>" +
				property_management.desk.esc(user.buildings) +
				"</td><td>" +
				property_management.desk.esc(user.beds_occupied + " / " + user.beds) +
				"</td><td>" +
				property_management.desk.esc(property_management.desk.money(user.monthly_fixed_rent)) +
				"</td><td>" +
				property_management.desk.esc(property_management.desk.money(user.recognized_rental_revenue)) +
				"</td><td>" +
				property_management.desk.esc(property_management.desk.money(user.rent_collected)) +
				"</td><td>" +
				property_management.desk.esc(property_management.desk.money(user.outstanding_open)) +
				"</td><td>" +
				property_management.desk.esc(property_management.desk.money(user.held_deposits)) +
				"</td><td>" +
				property_management.desk.esc(property_management.desk.money(user.expenses)) +
				"</td><td>" +
				property_management.desk.esc(property_management.desk.money(user.operating_profit)) +
				"</td></tr>"
		)
		.join("");
	state.users_el.html(
		'<section class="pm-section"><div class="pm-section-head"><h3>' +
			__("User-wise overview") +
			"</h3>" +
			property_management.desk.button("open-page", __("Open User Report"), { page: "user-report" }) +
			"</div>" +
			(rows
				? '<div class="pm-table-wrap"><table class="pm-table"><thead><tr><th>' +
					__("User") +
					"</th><th>" +
					__("Buildings") +
					"</th><th>" +
					__("Occupied beds") +
					"</th><th>" +
					__("Fixed rent") +
					"</th><th>" +
					__("Recognized") +
					"</th><th>" +
					__("Collected") +
					"</th><th>" +
					__("Open receivables") +
					"</th><th>" +
					__("Held deposits") +
					"</th><th>" +
					__("Expenses") +
					"</th><th>" +
					__("Operating profit") +
					"</th></tr></thead><tbody>" +
					rows +
					"</tbody></table></div>"
				: '<p class="pm-note">' + __("No property users match this filter.") + "</p>") +
			"</section>"
	);
};

property_management.desk.render_nav = function (state) {
	const links = [
		["Building", __("Buildings")],
		["Flat", __("Flats")],
		["Area", __("Areas")],
		["Bed", __("Beds")],
		["Tenant", __("Tenants")],
		["Bed Allocation", __("Allocations")],
		["Monthly Revenue", __("Monthly revenue")],
		["Rent Invoice", __("Invoices")],
		["Rent Payment", __("Collections")],
		["Tenant Deposit", __("Deposits")],
		["Deposit Transaction", __("Deposit transactions")],
		["Property Expense", __("Expenses")],
		["Cash Bank Account", __("Cash and bank")],
		["Rent Billing Log", __("Billing log")],
	];
	state.nav_el.html(
		links
			.map((link) => property_management.desk.button("list", link[1], { doctype: link[0] }))
			.join("")
	);
};

property_management.desk.render_operations = function (state) {
	const ops = state.operations || {};
	const privileged = state.overview && state.overview.scope && state.overview.scope.privileged;
	const parts = [
		property_management.desk.hierarchy_section(ops.hierarchy || [], privileged),
		property_management.desk.allocation_section(ops.allocations),
		property_management.desk.schedule_section(ops.schedules, privileged),
		property_management.desk.table_section(
			__("Invoices in this period"),
			__("No rent invoices in this period."),
			ops.invoices,
			[__("Invoice"), __("Tenant"), __("Month"), __("Rent"), __("Paid"), __("Outstanding"), __("Status")],
			(row) => [
				property_management.desk.doc_link("Rent Invoice", row.name, row.name),
				property_management.desk.esc(row.tenant_name || row.tenant || ""),
				property_management.desk.esc(row.billing_month || ""),
				property_management.desk.money(row.rent_amount),
				property_management.desk.money(row.amount_paid),
				property_management.desk.money(row.outstanding),
				property_management.desk.esc(row.status || ""),
			]
		),
		property_management.desk.table_section(
			__("Collections in this period"),
			__("No rent payments in this period."),
			ops.payments,
			[__("Payment"), __("Date"), __("Tenant"), __("Amount"), __("Status")],
			(row) => [
				property_management.desk.doc_link("Rent Payment", row.name, row.name),
				property_management.desk.esc(row.posting_date || ""),
				property_management.desk.esc(row.tenant_name || row.tenant || ""),
				property_management.desk.money(row.amount),
				property_management.desk.docstatus(row.docstatus),
			],
			property_management.desk.button("new-doc", __("Record collection"), { doctype: "Rent Payment" })
		),
		property_management.desk.table_section(
			__("Deposits"),
			__("No deposits in this filter."),
			ops.deposits,
			[__("Deposit"), __("Tenant"), __("Balance"), __("Received"), __("Refunded"), __("Transferred"), __("Status")],
			(row) => [
				property_management.desk.doc_link("Tenant Deposit", row.name, row.name),
				property_management.desk.esc(row.tenant_name || row.tenant || ""),
				property_management.desk.money(row.balance),
				property_management.desk.money(row.total_received),
				property_management.desk.money(row.total_refunded),
				property_management.desk.money(row.total_transferred),
				property_management.desk.esc(row.status || ""),
			],
			property_management.desk.button("new-doc", __("New deposit"), { doctype: "Tenant Deposit" }) +
				property_management.desk.button("new-doc", __("Receipt"), {
					doctype: "Deposit Transaction",
					transaction_type: "Receipt",
				}) +
				property_management.desk.button("new-doc", __("Refund"), {
					doctype: "Deposit Transaction",
					transaction_type: "Refund",
				}) +
				property_management.desk.button("new-doc", __("Transfer to revenue"), {
					doctype: "Deposit Transaction",
					transaction_type: "Transfer to Revenue",
				})
		),
		property_management.desk.table_section(
			__("Deposit transactions in this period"),
			__("No deposit transactions in this period."),
			ops.deposit_transactions,
			[__("Transaction"), __("Type"), __("Date"), __("Amount")],
			(row) => [
				property_management.desk.doc_link("Deposit Transaction", row.name, row.name),
				property_management.desk.esc(row.transaction_type || ""),
				property_management.desk.esc(row.posting_date || ""),
				property_management.desk.money(row.amount),
			]
		),
		property_management.desk.table_section(
			__("Expenses in this period"),
			__("No expenses in this period."),
			ops.expenses,
			[__("Expense"), __("Date"), __("Category"), __("Amount"), __("Status")],
			(row) => [
				property_management.desk.doc_link("Property Expense", row.name, row.name),
				property_management.desk.esc(row.posting_date || ""),
				property_management.desk.esc(row.expense_category || ""),
				property_management.desk.money(row.amount),
				property_management.desk.esc(row.status || ""),
			],
			property_management.desk.button("new-doc", __("New expense"), { doctype: "Property Expense" })
		),
	];
	state.ops_el.html(parts.join(""));
};

property_management.desk.hierarchy_section = function (tree) {
	const body = tree.length
		? '<div class="pm-tree">' + tree.map(property_management.desk.building_node).join("") + "</div>"
		: '<p class="pm-note">' + __("No buildings yet.") + "</p>";
	return (
		'<section class="pm-section"><div class="pm-section-head"><h3>' +
		__("Buildings, flats, areas, and beds") +
		"</h3>" +
		property_management.desk.button("new-doc", __("Add building"), { doctype: "Building" }) +
		property_management.desk.button("new-doc", __("Add tenant"), { doctype: "Tenant" }) +
		"</div>" +
		body +
		"</section>"
	);
};

property_management.desk.building_node = function (building) {
	const flats = (building.flats || []).map(property_management.desk.flat_node).join("");
	return (
		'<article class="pm-building"><div class="pm-row"><strong>' +
		property_management.desk.doc_link("Building", building.name, building.label) +
		"</strong> <span class=\"pm-note\">" +
		property_management.desk.esc(building.status || "") +
		"</span> " +
		property_management.desk.button("new-doc", __("Add flat"), {
			doctype: "Flat",
			building: building.name,
		}) +
		"</div>" +
		(flats || '<p class="pm-note">' + __("No flats in this building.") + "</p>") +
		"</article>"
	);
};

property_management.desk.flat_node = function (flat) {
	const areas = (flat.areas || []).map(property_management.desk.area_node).join("");
	return (
		'<article class="pm-flat"><div class="pm-row">' +
		property_management.desk.doc_link("Flat", flat.name, flat.label) +
		" <span class=\"pm-note\">" +
		property_management.desk.esc(flat.status || "") +
		"</span> " +
		property_management.desk.button("new-doc", __("Add area"), {
			doctype: "Area",
			flat: flat.name,
		}) +
		"</div>" +
		(areas || '<p class="pm-note">' + __("No areas in this flat.") + "</p>") +
		"</article>"
	);
};

property_management.desk.area_node = function (area) {
	const beds = (area.beds || [])
		.map((bed) => {
			const who = bed.current_tenant
				? property_management.desk.doc_link(
						"Tenant",
						bed.current_tenant,
						bed.current_tenant_name || bed.current_tenant
					)
				: __("No tenant");
			return (
				"<li>" +
				property_management.desk.doc_link("Bed", bed.name, bed.label) +
				" · " +
				property_management.desk.esc(bed.occupancy_status || "") +
				" · " +
				who +
				" " +
				(bed.current_allocation
					? property_management.desk.button("open-doc", __("Allocation"), {
							doctype: "Bed Allocation",
							name: bed.current_allocation,
						})
					: property_management.desk.button("new-doc", __("Allocate"), {
							doctype: "Bed Allocation",
							bed: bed.name,
							tenant: bed.current_tenant || "",
						})) +
				"</li>"
			);
		})
		.join("");
	return (
		'<article class="pm-area"><div class="pm-row">' +
		property_management.desk.doc_link("Area", area.name, area.label) +
		" <span class=\"pm-note\">" +
		property_management.desk.esc(area.area_type || "") +
		"</span> " +
		property_management.desk.button("new-doc", __("Add bed"), { doctype: "Bed", area: area.name }) +
		"</div><ul>" +
		(beds || "<li>" + __("No beds in this area.") + "</li>") +
		"</ul></article>"
	);
};

property_management.desk.allocation_section = function (bundle) {
	return property_management.desk.table_section(
		__("Allocations"),
		__("No allocations in this filter."),
		bundle,
		[__("Allocation"), __("Tenant"), __("Bed"), __("Status"), __("Rent"), __("Deposit"), __("Vacating"), __("")],
		(row) => [
			property_management.desk.doc_link("Bed Allocation", row.name, row.name),
			property_management.desk.esc(row.tenant_name || row.tenant || ""),
			property_management.desk.doc_link("Bed", row.bed, row.bed),
			property_management.desk.esc(row.allocation_status || ""),
			property_management.desk.money(row.monthly_rent),
			property_management.desk.money(row.deposit_amount),
			property_management.desk.esc(row.vacating_date || ""),
			row.allocation_status === "Active"
				? property_management.desk.button("vacate", __("Vacate"), { name: row.name })
				: "",
		],
		property_management.desk.button("new-doc", __("New allocation"), { doctype: "Bed Allocation" })
	);
};

property_management.desk.schedule_section = function (bundle, privileged) {
	const extra =
		(privileged
			? ""
			: property_management.desk.button("generate-all", __("Generate due invoices"), {})) +
		property_management.desk.button("list", __("Billing log"), { doctype: "Rent Billing Log" });
	return property_management.desk.table_section(
		__("Monthly revenue"),
		__("No rent schedules in this filter."),
		bundle,
		[__("Schedule"), __("Tenant"), __("Status"), __("Rent"), __("Start"), __("End"), __("")],
		(row) => [
			property_management.desk.doc_link("Monthly Revenue", row.name, row.name),
			property_management.desk.esc(row.tenant_name || row.tenant || ""),
			property_management.desk.esc(row.status || ""),
			property_management.desk.money(row.monthly_rent),
			property_management.desk.esc(row.start_date || ""),
			property_management.desk.esc(row.end_date || ""),
			(row.status === "Active"
				? property_management.desk.button("generate-one", __("Generate due"), { name: row.name })
				: "") + property_management.desk.button("revise-rent", __("Revise rent"), { name: row.name }),
		],
		extra
	);
};

property_management.desk.table_section = function (title, empty, bundle, headings, cells, actions) {
	const rows = (bundle && bundle.rows) || [];
	const body = rows.length
		? '<div class="pm-table-wrap"><table class="pm-table"><thead><tr>' +
			headings.map((heading) => "<th>" + property_management.desk.esc(heading) + "</th>").join("") +
			"</tr></thead><tbody>" +
			rows
				.map((row) => "<tr>" + cells(row).map((cell) => "<td>" + (cell || "") + "</td>").join("") + "</tr>")
				.join("") +
			"</tbody></table></div>" +
			(bundle.truncated
				? '<p class="pm-note">' + __("Showing the first rows. Open the list for the rest.") + "</p>"
				: "")
		: '<p class="pm-note">' + property_management.desk.esc(empty) + "</p>";
	return (
		'<section class="pm-section"><div class="pm-section-head"><h3>' +
		property_management.desk.esc(title) +
		'</h3><div class="pm-actions">' +
		(actions || "") +
		"</div></div>" +
		body +
		"</section>"
	);
};

property_management.desk.render_measures = function (state) {
	const measures = (state.overview && state.overview.measures) || {};
	const items = Object.keys(measures)
		.map(
			(key) =>
				"<dt>" +
				property_management.desk.esc(key.replaceAll("_", " ")) +
				"</dt><dd>" +
				property_management.desk.esc(measures[key]) +
				"</dd>"
		)
		.join("");
	state.measures_el.html(
		"<details><summary>" +
			__("How these figures are calculated") +
			"</summary><dl>" +
			items +
			"</dl></details>"
	);
};

property_management.desk.on_action = function (state, button) {
	const action = button.dataset.pmAction;
	if (action === "apply") {
		property_management.desk.read_filters(state);
		property_management.desk.load(state);
		return;
	}
	if (action === "reset-filters") {
		state.filters.from_date = "";
		state.filters.to_date = "";
		property_management.desk.load(state);
		return;
	}
	if (action === "filter-user") {
		state.filters.owner_user = button.dataset.user || "";
		property_management.desk.load(state);
		return;
	}
	if (action === "open-page") {
		frappe.set_route(button.dataset.page);
		return;
	}
	if (action === "list") {
		frappe.set_route("List", button.dataset.doctype);
		return;
	}
	if (action === "open-doc") {
		frappe.set_route("Form", button.dataset.doctype, button.dataset.name);
		return;
	}
	if (action === "new-doc") {
		property_management.desk.open_new(state, button);
		return;
	}
	if (action === "create-user") {
		property_management.desk.create_user(state);
		return;
	}
	if (action === "reset-password") {
		property_management.desk.reset_password(state, button.dataset.user);
		return;
	}
	if (action === "set-expiry") {
		property_management.desk.set_expiry(state, button.dataset.user, button.dataset.expiry);
		return;
	}
	if (action === "set-active") {
		property_management.desk.set_active(state, button.dataset.user, button.dataset.active);
		return;
	}
	if (action === "vacate") {
		property_management.desk.vacate(state, button.dataset.name);
		return;
	}
	if (action === "generate-one") {
		property_management.desk.generate(state, button.dataset.name);
		return;
	}
	if (action === "generate-all") {
		property_management.desk.generate(state, null);
		return;
	}
	if (action === "revise-rent") {
		property_management.desk.revise(state, button.dataset.name);
	}
};

property_management.desk.open_new = function (state, button) {
	const privileged = state.overview && state.overview.scope && state.overview.scope.privileged;
	const values = {};
	if (privileged) {
		if (!state.filters.owner_user) {
			frappe.msgprint(__("Choose a property user before adding a record."));
			return;
		}
		values.owner_user = state.filters.owner_user;
	}
	["building", "flat", "area", "bed", "tenant", "transaction_type"].forEach((field) => {
		const value = button.dataset[field.replace(/_([a-z])/g, (_m, letter) => letter.toUpperCase())];
		if (value) {
			values[field] = value;
		}
	});
	if (state.filters.building && !values.building && button.dataset.doctype !== "Building") {
		values.building = state.filters.building;
	}
	frappe.model.with_doctype(button.dataset.doctype, () => {
		frappe.route_options = values;
		const doc = frappe.model.get_new_doc(button.dataset.doctype);
		frappe.set_route("Form", button.dataset.doctype, doc.name);
	});
};

property_management.desk.create_user = function (state) {
	const form = state.root.find("[data-pm-create]").get(0);
	if (!form) {
		return;
	}
	const full_name = form.full_name.value.trim();
	const mobile_number = form.mobile_number.value.trim();
	const password = form.password.value;
	const confirm_password = form.confirm_password.value;
	const account_expiry = form.account_expiry.value;
	const enabled = form.enabled.checked ? 1 : 0;
	if (!full_name || !mobile_number || !password || !account_expiry) {
		frappe.msgprint(__("Name, mobile number, password, and expiry are required."));
		return;
	}
	if (password !== confirm_password) {
		form.password.value = "";
		form.confirm_password.value = "";
		frappe.msgprint(__("The passwords do not match."));
		return;
	}
	frappe
		.call({
			method: "property_management.api.create_property_user",
			args: {
				full_name,
				mobile_number,
				password,
				account_expiry,
				enabled,
			},
		})
		.then((response) => {
			form.password.value = "";
			form.confirm_password.value = "";
			form.full_name.value = "";
			form.mobile_number.value = "";
			frappe.show_alert({
				message: __("Property user {0} can sign in with mobile {1}. They must change the password.", [
					response.message.full_name || full_name,
					response.message.username,
				]),
				indicator: "green",
			});
			property_management.desk.load(state);
		})
		.catch(() => {
			form.password.value = "";
			form.confirm_password.value = "";
		});
};

property_management.desk.reset_password = function (state, user) {
	frappe.prompt(
		[
			{
				fieldname: "new_password",
				fieldtype: "Password",
				label: __("Temporary password"),
				reqd: 1,
				description: __("This is not stored on the profile. The user must change it at the next login."),
			},
		],
		(values) => {
			frappe
				.call({
					method: "property_management.api.reset_property_user_password",
					args: { user, new_password: values.new_password },
				})
				.then(() => {
					frappe.show_alert({
						message: __("Temporary password set. It must be changed at the next login."),
						indicator: "green",
					});
					property_management.desk.load(state);
				});
		},
		__("Reset password"),
		__("Set password")
	);
};

property_management.desk.set_expiry = function (state, user, current) {
	frappe.prompt(
		[
			{
				fieldname: "account_expiry",
				fieldtype: "Date",
				label: __("Account expiry"),
				reqd: 1,
				default: current,
			},
		],
		(values) => {
			frappe
				.call({
					method: "property_management.api.set_account_expiry",
					args: { user, account_expiry: values.account_expiry },
				})
				.then(() => property_management.desk.load(state));
		},
		__("Account expiry"),
		__("Update")
	);
};

property_management.desk.set_active = function (state, user, active) {
	const enabling = String(active) === "1";
	frappe.confirm(
		enabling ? __("Activate this property user?") : __("Deactivate this property user?"),
		() => {
			frappe
				.call({
					method: "property_management.api.set_user_active",
					args: { user, active: enabling ? 1 : 0 },
				})
				.then(() => property_management.desk.load(state));
		}
	);
};

property_management.desk.vacate = function (state, name) {
	frappe.prompt(
		[
			{
				fieldname: "vacating_date",
				fieldtype: "Date",
				label: __("Vacating date"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
		],
		(values) => {
			frappe
				.call({
					method: "frappe.handler.run_doc_method",
					args: {
						method: "vacate",
						dt: "Bed Allocation",
						dn: name,
						args: { vacating_date: values.vacating_date },
					},
				})
				.then(() => property_management.desk.load(state));
		},
		__("Vacate bed"),
		__("Vacate")
	);
};

property_management.desk.generate = function (state, monthly_revenue) {
	const args = {};
	if (monthly_revenue) {
		args.monthly_revenue = monthly_revenue;
	}
	frappe
		.call({
			method: "property_management.billing.generate_rent_invoices",
			args,
		})
		.then((response) => {
			const result = response.message || {};
			frappe.msgprint({
				title: __("Rent billing"),
				message: __("Created {0}. Skipped {1}. Failed {2}. Failures stay in the billing log and can be run again.", [
					result.created || 0,
					result.skipped || 0,
					result.failed || 0,
				]),
			});
			property_management.desk.load(state);
		});
};

property_management.desk.revise = function (state, monthly_revenue) {
	frappe.prompt(
		[
			{
				fieldname: "effective_from",
				fieldtype: "Date",
				label: __("Effective from"),
				reqd: 1,
				default: frappe.datetime.get_today(),
			},
			{
				fieldname: "monthly_rent",
				fieldtype: "Currency",
				label: __("Monthly rent"),
				reqd: 1,
			},
			{
				fieldname: "remarks",
				fieldtype: "Small Text",
				label: __("Remarks"),
			},
		],
		(values) => {
			frappe
				.call({
					method: "property_management.billing.revise_rent",
					args: {
						monthly_revenue,
						effective_from: values.effective_from,
						monthly_rent: values.monthly_rent,
						remarks: values.remarks,
					},
				})
				.then(() => property_management.desk.load(state));
		},
		__("Revise rent"),
		__("Save revision")
	);
};

property_management.desk.button = function (action, label, data) {
	const attrs = Object.keys(data || {})
		.filter((key) => data[key] !== undefined && data[key] !== null && data[key] !== "")
		.map(
			(key) =>
				" data-" +
				key.replace(/_/g, "-") +
				'="' +
				property_management.desk.esc(data[key]) +
				'"'
		)
		.join("");
	return (
		'<button type="button" class="btn btn-default btn-sm" data-pm-action="' +
		action +
		'"' +
		attrs +
		">" +
		property_management.desk.esc(label) +
		"</button>"
	);
};

property_management.desk.doc_link = function (doctype, name, label) {
	if (!name) {
		return "";
	}
	return (
		'<button type="button" class="btn btn-link btn-sm" data-pm-action="open-doc" data-doctype="' +
		property_management.desk.esc(doctype) +
		'" data-name="' +
		property_management.desk.esc(name) +
		'">' +
		property_management.desk.esc(label || name) +
		"</button>"
	);
};

property_management.desk.docstatus = function (value) {
	if (Number(value) === 1) {
		return __("Submitted");
	}
	if (Number(value) === 2) {
		return __("Cancelled");
	}
	return __("Draft");
};

property_management.desk.lead = function (mode) {
	const text =
		mode === "super-admin"
			? __(
					"Create property logins, move expiry, and read occupancy and money for every account or one user."
				)
			: __(
					"Your buildings, tenants, rent schedules, collections, deposits, and expenses. Figures are read from the records, for the current month unless you change the dates."
				);
	return $("<p class=\"pm-lead\"></p>").text(text);
};

property_management.desk.banner = function (html, class_name) {
	return $('<div class="' + class_name + '"></div>').html(html);
};

property_management.desk.money = function (value) {
	const amount = Number(value || 0);
	if (typeof format_currency === "function") {
		try {
			return format_currency(amount);
		} catch (error) {
			return amount.toFixed(2);
		}
	}
	return amount.toFixed(2);
};

property_management.desk.percent = function (rate) {
	return (Number(rate || 0) * 100).toFixed(1) + "%";
};

property_management.desk.esc = function (value) {
	return frappe.utils.escape_html(value == null ? "" : String(value));
};

property_management.desk.error_text = function (error) {
	if (!error) {
		return __("The request failed.");
	}
	if (error._server_messages) {
		try {
			const messages = JSON.parse(error._server_messages).map((item) => {
				const parsed = JSON.parse(item);
				return parsed.message || "";
			});
			const text = messages.join(" ");
			if (text) {
				return $("<div>").html(text).text();
			}
		} catch (ignored) {
			return __("The request failed.");
		}
	}
	if (typeof error.message === "string" && error.message) {
		return error.message;
	}
	return __("The request failed.");
};

property_management.desk.is_privileged = function () {
	const roles = frappe.user_roles || [];
	return (
		frappe.session.user === "Administrator" ||
		roles.includes("Property Super Admin") ||
		roles.includes("System Manager")
	);
};

property_management.desk.is_property_user = function () {
	return (frappe.user_roles || []).includes("Property User");
};

property_management.desk.must_change_password = function () {
	const info = (frappe.boot && frappe.boot.property_management) || {};
	return !!info.must_change_password;
};
