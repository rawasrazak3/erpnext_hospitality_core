/* Front Desk Console (/app/front-desk-console) — the hotel's home screen.
 *
 * This page is where staff land, so it has two jobs: show the shift's work
 * (arrivals, departures, occupancy) and be the way to reach everything else. The
 * layout follows that order — search, primary actions, numbers, the two work
 * queues, then a full directory for the long tail.
 *
 * Conventions that matter here:
 *   - Styling lives in front_desk_console.css and uses Frappe's design tokens, so
 *     the page follows the active theme. Nothing is injected into document.head.
 *   - Every destination is a real <a href="/app/...">. Frappe's router intercepts
 *     the click for SPA navigation, and ctrl/cmd-click still opens a new tab —
 *     which an onclick="frappe.set_route(...)" handler silently breaks.
 *   - Guest names are guest-supplied text rendered into HTML, so everything
 *     interpolated goes through esc().
 */

/* Frappe evaluates page scripts by appending a <script> to <head>, so every
 * top-level declaration here would land on window — where a generic name like
 * `panel` or `esc` collides with another page's, and a re-eval throws on the
 * duplicate `const`. Everything therefore lives inside this IIFE; only the
 * frappe.pages[...] handlers, which are property assignments, escape it. */
(function () {

	frappe.pages["front-desk-console"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Front Desk"),
			single_column: true,
		});

		wrapper.fdc = new FrontDeskConsole(page, wrapper);
	};

	frappe.pages["front-desk-console"].on_page_show = function (wrapper) {
		// Coming back from a check-in leaves the numbers stale, so re-pull on return.
		if (wrapper.fdc) wrapper.fdc.refresh();
	};

	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	/* Primary actions. `count` names a key from the backend's nav block; `tone`
	 * decides whether that badge reads as urgent. Anything the user cannot open is
	 * dropped in filter_permitted() rather than shown as a dead tile. */
	const PRIMARY_ACTIONS = [
		{
			label: __("Hotel CRM"),
			hint: __("Enquiries & follow-ups"),
			route: "/app/hotel-crm",
			page: "hotel-crm",
			count: "enquiries_due",
			tone: "is-alert",
			icon: `<path d="M3 5.5A2.5 2.5 0 0 1 5.5 3h2A1.5 1.5 0 0 1 9 4.5v2A1.5 1.5 0 0 1 7.5 8H7a10 10 0 0 0 6 6v-.5A1.5 1.5 0 0 1 14.5 12h2a1.5 1.5 0 0 1 1.5 1.5v2a2.5 2.5 0 0 1-2.5 2.5A12.5 12.5 0 0 1 3 5.5z"></path><path d="M14 3h7v7"></path><path d="M14 10l7-7"></path>`,
		},
		{
			label: __("Hotel POS"),
			hint: __("Charge & check in"),
			route: "/app/hotel-pos",
			page: "hotel-pos",
			icon: `<circle cx="9" cy="21" r="1"></circle><circle cx="20" cy="21" r="1"></circle><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"></path>`,
		},
		{
			label: __("Tape Chart"),
			hint: __("Rooms by night"),
			route: "/app/tape-chart",
			page: "tape-chart",
			icon: `<rect x="3" y="4" width="18" height="18" rx="2"></rect><path d="M16 2v4M8 2v4M3 10h18"></path>`,
		},
		{
			label: __("Availability"),
			hint: __("What can I sell?"),
			route: "/app/availability-tool",
			page: "availability-tool",
			icon: `<path d="M2 4v16M2 8h18a2 2 0 0 1 2 2v10M2 17h20M6 8v9"></path>`,
		},
		{
			label: __("Housekeeping"),
			hint: __("Room status"),
			route: "/app/housekeeping-view",
			page: "housekeeping-view",
			count: "rooms_dirty",
			tone: "is-warn",
			icon: `<path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>`,
		},
		{
			label: __("Guest 360"),
			hint: __("History & folio"),
			route: "/app/guest-360",
			page: "guest-360",
			icon: `<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle>`,
		},
	];

	/* The full directory. Grouped the way a hotel is actually organised, so people
	 * look in the section that matches the job they are doing. */
	const DIRECTORY = [
		{
			title: __("Sales & CRM"),
			items: [
				{ label: __("Hotel CRM Console"), route: "/app/hotel-crm", page: "hotel-crm", count: "enquiries_due" },
				{ label: __("Enquiries"), route: "/app/hotel-enquiry", doctype: "Hotel Enquiry", count: "enquiries_open" },
				{ label: __("Bookings"), route: "/app/hotel-booking", doctype: "Hotel Booking", count: "bookings_due" },
				{ label: __("Call Log"), route: "/app/crm-call-log", doctype: "CRM Call Log", count: "calls_unlinked" },
				{ label: __("Enquiry Conversion"), route: "/app/query-report/Enquiry Conversion", report: "Enquiry Conversion", doctype: "Hotel Enquiry" },
				{ label: __("Call Activity"), route: "/app/query-report/Call Activity", report: "Call Activity", doctype: "CRM Call Log" },
			],
		},
		{
			title: __("Front Desk"),
			items: [
				{ label: __("Reservations"), route: "/app/hotel-reservation", doctype: "Hotel Reservation" },
				{ label: __("Guests"), route: "/app/guest", doctype: "Guest" },
				{ label: __("Group Bookings"), route: "/app/hotel-group-booking", doctype: "Hotel Group Booking" },
				{ label: __("Daily Arrivals"), route: "/app/query-report/Daily Arrivals", report: "Daily Arrivals", doctype: "Hotel Reservation" },
				{ label: __("Daily Departures"), route: "/app/query-report/Daily Departures", report: "Daily Departures", doctype: "Hotel Reservation" },
				{ label: __("House List"), route: "/app/query-report/House List", report: "House List", doctype: "Hotel Reservation" },
			],
		},
		{
			title: __("Rooms & Upkeep"),
			items: [
				{ label: __("Rooms"), route: "/app/hotel-room", doctype: "Hotel Room" },
				{ label: __("Room Types"), route: "/app/hotel-room-type", doctype: "Hotel Room Type" },
				{ label: __("Rate Plans"), route: "/app/room-rate-plan", doctype: "Room Rate Plan" },
				{ label: __("Maintenance"), route: "/app/hotel-maintenance-request", doctype: "Hotel Maintenance Request", count: "maintenance_open" },
				{ label: __("Room Availability"), route: "/app/query-report/Room Availability Report", report: "Room Availability Report", doctype: "Hotel Room" },
				{ label: __("Lost & Found"), route: "/app/lost-and-found-item", doctype: "Lost and Found Item" },
			],
		},
		{
			title: __("Money & Reports"),
			items: [
				{ label: __("Guest Folios"), route: "/app/guest-folio", doctype: "Guest Folio" },
				{ label: __("Payment Entry"), route: "/app/payment-entry", doctype: "Payment Entry" },
				{ label: __("Expenses"), route: "/app/hospitality-expense", doctype: "Hospitality Expense" },
				{ label: __("Daily Payments"), route: "/app/query-report/Daily Payment Collection", report: "Daily Payment Collection", doctype: "Payment Entry" },
				{ label: __("Room Sales"), route: "/app/query-report/Room Only Sales", report: "Room Only Sales", doctype: "Hotel Reservation" },
				{ label: __("Advance Liability"), route: "/app/query-report/Advance Liability Register", report: "Advance Liability Register", doctype: "Hotel Booking" },
			],
		},
	];

	const DIRECTORY_OPEN_KEY = "fdc:directory_open";

	class FrontDeskConsole {
		constructor(page, wrapper) {
			this.page = page;
			this.wrapper = wrapper;
			this.$container = $(wrapper).find(".layout-main-section");
			this.nav = {};
			this.search_seq = 0;
			this.selected_result = -1;

			this.setup_controls();
			this.render_shell();
			this.bind_events();
			this.refresh();
			this.start_auto_refresh();
		}

		setup_controls() {
			this.page.add_field({
				fieldname: "console_date",
				label: __("Date"),
				fieldtype: "Date",
				default: frappe.datetime.now_date(),
				change: () => this.refresh(),
			});

			this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");

			// The desk's own "New" affordance: a walk-in is the most common thing a
			// front desk creates, and it should not require finding the list view first.
			if (frappe.model.can_create("Hotel Reservation")) {
				this.page.set_primary_action(
					__("New Reservation"),
					() => frappe.new_doc("Hotel Reservation"),
					"add"
				);
			}
		}

		/* Only offer what the user can actually open. A Hotel Sales Agent has no read
		 * on Hotel Room, and a tile that throws a permission error on click is worse
		 * than no tile. */
		filter_permitted(items) {
			return items.filter((item) => {
				// frappe.boot.page_info only contains pages this user is allowed to open,
				// so it is the same answer the server would give on navigation.
				if (item.page && frappe.boot.page_info && !frappe.boot.page_info[item.page]) {
					return false;
				}
				// A report is reachable only if its ref_doctype is, which is what the
				// doctype key carries for report entries.
				if (item.doctype) return frappe.model.can_read(item.doctype);
				return true;
			});
		}

		render_shell() {
			const hour = new Date().getHours();
			const greeting =
				hour < 12 ? __("Good morning") : hour < 17 ? __("Good afternoon") : __("Good evening");
			const first_name = frappe.boot.user.first_name || "";

			this.$container.html(`
				<div class="fdc">
					<div class="fdc-hero">
						<div>
							<div class="fdc-greeting">${esc(greeting)}${first_name ? ", " + esc(first_name) : ""}</div>
							<div class="fdc-subgreeting" data-fdc="date-line"></div>
						</div>
						<div class="fdc-search-wrap" data-fdc="search-wrap">
							<span class="fdc-search-icon">${svg('<circle cx="11" cy="11" r="7"></circle><path d="M21 21l-4.3-4.3"></path>', 16)}</span>
							<input type="text" class="fdc-search-input" data-fdc="search"
								placeholder="${__("Search guest, room, booking or phone…")}"
								autocomplete="off" spellcheck="false"
								aria-label="${__("Search guests, reservations, bookings and enquiries")}">
							<span class="fdc-search-kbd">/</span>
							<div class="fdc-results" data-fdc="results" hidden></div>
						</div>
					</div>

					<div class="fdc-actions" data-fdc="actions"></div>

					<div class="fdc-stats">
						${stat_card("arrive", __("Arrivals Pending"), "arr", __("Yet to check in"))}
						${stat_card("depart", __("Departures Due"), "dep", __("Yet to check out"))}
						${stat_card(
							"house",
							__("In House"),
							"house",
							'<span data-fdc="occ-text"></span><div class="fdc-meter"><div class="fdc-meter-fill" data-fdc="occ-bar" style="width:0%"></div></div>'
						)}
						${stat_card("free", __("Available"), "free", __("Sellable tonight"))}
					</div>

					<div class="fdc-lists">
						${panel(
							"arrivals",
							__("Arrivals"),
							'<circle cx="12" cy="12" r="9"></circle><path d="M8 12l3 3 5-6"></path>'
						)}
						${panel(
							"departures",
							__("Departures"),
							'<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><path d="M16 17l5-5-5-5"></path><path d="M21 12H9"></path>'
						)}
					</div>

					<div class="fdc-directory" data-fdc="directory">
						<button class="fdc-directory-head" data-fdc="directory-toggle" aria-expanded="false">
							<span class="fdc-directory-title">${__("All areas")}</span>
							<span class="fdc-directory-chevron">${svg('<path d="M6 9l6 6 6-6"></path>', 16)}</span>
						</button>
						<div class="fdc-directory-body" data-fdc="directory-body"></div>
					</div>

					<div class="fdc-updated" data-fdc="updated"></div>
				</div>
			`);

			this.$container.css("padding-bottom", "0");
			this.render_actions();
			this.render_directory();
			this.restore_directory_state();
		}

		render_actions() {
			const html = this.filter_permitted(PRIMARY_ACTIONS)
				.map(
					(a) => `
					<a class="fdc-action" href="${a.route}" data-count="${esc(a.count || "")}" data-tone="${esc(a.tone || "")}">
						<span class="fdc-action-icon">${svg(a.icon, 20)}</span>
						<span class="fdc-action-label">${esc(a.label)}</span>
						<span class="fdc-action-hint">${esc(a.hint)}</span>
					</a>`
				)
				.join("");
			this.$container.find('[data-fdc="actions"]').html(html);
		}

		render_directory() {
			const html = DIRECTORY.map((group) => {
				const items = this.filter_permitted(group.items);
				if (!items.length) return "";
				const links = items
					.map(
						(i) => `
						<a class="fdc-link" href="${i.route}">
							<span>${esc(i.label)}</span>
							<span class="fdc-link-count" data-count="${esc(i.count || "")}"></span>
						</a>`
					)
					.join("");
				return `<div><div class="fdc-group-title">${esc(group.title)}</div>${links}</div>`;
			}).join("");
			this.$container.find('[data-fdc="directory-body"]').html(html);
		}

		restore_directory_state() {
			let open = false;
			try {
				open = localStorage.getItem(DIRECTORY_OPEN_KEY) === "1";
			} catch (e) {
				// Private windows and blocked site data throw on access; default to closed.
			}
			this.toggle_directory(open, false);
		}

		toggle_directory(open, persist = true) {
			this.$container.find('[data-fdc="directory"]').toggleClass("is-open", open);
			this.$container.find('[data-fdc="directory-toggle"]').attr("aria-expanded", String(open));
			if (!persist) return;
			try {
				localStorage.setItem(DIRECTORY_OPEN_KEY, open ? "1" : "0");
			} catch (e) {
				// Nothing to do — the panel still works, it just will not be remembered.
			}
		}

		bind_events() {
			const $c = this.$container;

			$c.on("click", '[data-fdc="directory-toggle"]', () => {
				const open = !$c.find('[data-fdc="directory"]').hasClass("is-open");
				this.toggle_directory(open);
			});

			const $search = $c.find('[data-fdc="search"]');
			$search.on(
				"input",
				frappe.utils.debounce(() => this.run_search($search.val()), 220)
			);
			$search.on("focus", () => $c.find('[data-fdc="search-wrap"]').addClass("is-active"));
			$search.on("blur", () => {
				$c.find('[data-fdc="search-wrap"]').removeClass("is-active");
				// Delayed so a click on a result lands before the list is torn down.
				setTimeout(() => this.hide_results(), 180);
			});
			$search.on("keydown", (e) => this.on_search_key(e));
			$c.on("mousedown", '[data-fdc="results"]', (e) => e.preventDefault());

			// "/" is the desk-wide convention for jump-to-search.
			this.key_handler = (e) => {
				if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
				const tag = (e.target.tagName || "").toLowerCase();
				if (tag === "input" || tag === "textarea" || e.target.isContentEditable) return;
				if (!$(this.wrapper).is(":visible")) return;
				e.preventDefault();
				$search.trigger("focus").select();
			};
			$(document).on("keydown.fdc", this.key_handler);

			// Frappe caches desk pages rather than destroying them, so there is no
			// teardown hook to hang destroy() on. Both the timer and the "/" handler
			// check visibility instead, and destroy() stays for explicit cleanup.
		}

		on_search_key(e) {
			const $results = this.$container.find('[data-fdc="results"]');
			const $items = $results.find(".fdc-result");

			if (e.key === "Escape") {
				this.hide_results();
				$(e.currentTarget).val("").trigger("blur");
				return;
			}
			if (!$items.length) return;

			if (e.key === "ArrowDown" || e.key === "ArrowUp") {
				e.preventDefault();
				const dir = e.key === "ArrowDown" ? 1 : -1;
				this.selected_result =
					this.selected_result < 0
						? dir === 1
							? 0
							: $items.length - 1
						: (this.selected_result + dir + $items.length) % $items.length;
				$items.removeClass("is-selected");
				const $sel = $items.eq(this.selected_result).addClass("is-selected");
				$sel[0].scrollIntoView({ block: "nearest" });
			} else if (e.key === "Enter") {
				e.preventDefault();
				const idx = this.selected_result >= 0 ? this.selected_result : 0;
				const href = $items.eq(idx).attr("href");
				if (href) {
					this.hide_results();
					frappe.set_route(href);
				}
			}
		}

		run_search(query) {
			query = (query || "").trim();
			if (query.length < 2) {
				this.hide_results();
				return;
			}

			// Responses can land out of order; only the newest query may paint.
			const seq = ++this.search_seq;
			frappe
				.xcall(
					"hospitality_core.hospitality_core.page.front_desk_console.front_desk_console.search",
					{ query }
				)
				.then((rows) => {
					if (seq !== this.search_seq) return;
					this.render_results(rows || []);
				})
				.catch(() => {
					if (seq === this.search_seq) this.hide_results();
				});
		}

		render_results(rows) {
			const $results = this.$container.find('[data-fdc="results"]');
			this.selected_result = -1;

			if (!rows.length) {
				$results.html(`<div class="fdc-result-empty">${__("Nothing found")}</div>`);
			} else {
				$results.html(
					rows
						.map(
							(r) => `
							<a class="fdc-result" href="/app/${frappe.router.slug(r.doctype)}/${encodeURIComponent(r.name)}">
								<span class="fdc-result-main">
									<span class="fdc-result-title">${esc(r.title)}</span>
									<span class="fdc-result-sub">${esc([r.name, r.subtitle, r.status].filter(Boolean).join(" · "))}</span>
								</span>
								<span class="fdc-result-type">${esc(__(r.doctype))}</span>
							</a>`
						)
						.join("")
				);
			}
			$results.prop("hidden", false);
		}

		hide_results() {
			this.$container.find('[data-fdc="results"]').prop("hidden", true).empty();
			this.selected_result = -1;
		}

		refresh() {
			const date = this.page.fields_dict.console_date.get_value();
			return frappe
				.xcall(
					"hospitality_core.hospitality_core.page.front_desk_console.front_desk_console.get_console_data",
					{ target_date: date }
				)
				.then((data) => {
					if (!data) return;
					this.nav = data.nav || {};
					this.render_date_line(date);
					this.render_stats(data.stats, date);
					this.render_counts();
					this.render_list("arrivals", data.arrivals, date);
					this.render_list("departures", data.departures, date);
					this.$container
						.find('[data-fdc="updated"]')
						.text(__("Updated {0}", [frappe.datetime.now_time()]));
				});
		}

		set_stat_links(date) {
			const res = frappe.model.can_read("Hotel Reservation");
			const list = (params) =>
				res ? "/app/hotel-reservation?" + new URLSearchParams(params).toString() : null;

			const targets = {
				arr: list({ status: "Reserved", arrival_date: date }),
				dep: list({ status: "Checked In", departure_date: date }),
				house: list({ status: "Checked In" }),
				free: "/app/tape-chart",
			};

			Object.entries(targets).forEach(([key, href]) => {
				const $el = this.$container.find(`[data-fdc="stat-${key}"]`);
				// No destination the user may open: keep the number, drop the affordance.
				if (href) $el.attr("href", href).css("cursor", "");
				else $el.removeAttr("href").css("cursor", "default");
			});
		}

		render_date_line(date) {
			const is_today = date === frappe.datetime.now_date();
			const label = frappe.datetime.str_to_user(date);
			this.$container
				.find('[data-fdc="date-line"]')
				.text(is_today ? __("Today, {0}", [label]) : __("Showing {0}", [label]));
		}

		render_stats(stats, date) {
			const $c = this.$container;
			this.set_stat_links(date);
			$c.find('[data-fdc="val-arr"]').text(stats.arrivals_pending);
			$c.find('[data-fdc="val-dep"]').text(stats.departures_pending);
			$c.find('[data-fdc="val-house"]').text(stats.in_house);
			$c.find('[data-fdc="val-free"]').text(stats.available);
			$c.find('[data-fdc="occ-text"]').text(
				__("{0}% of {1} rooms", [stats.occupancy_pct, stats.total_rooms])
			);
			$c.find('[data-fdc="occ-bar"]').css("width", Math.min(100, stats.occupancy_pct) + "%");
		}

		/* Paint every element that asked for a nav count, wherever it lives. A count of
		 * zero renders as nothing at all — a row of zeros teaches people to ignore the
		 * badges, and then the one that matters gets ignored too. */
		render_counts() {
			this.$container.find(".fdc-action[data-count]").each((_, el) => {
				const $el = $(el);
				const key = $el.attr("data-count");
				$el.find(".fdc-badge").remove();
				if (!this.nav[key]) return;
				const tone = $el.attr("data-tone") || "";
				$el.append(`<span class="fdc-badge ${tone}">${esc(this.count_label(key))}</span>`);
			});

			this.$container.find(".fdc-link-count[data-count]").each((_, el) => {
				const $el = $(el);
				const key = $el.attr("data-count");
				$el.text(this.nav[key] ? this.count_label(key) : "");
			});
		}

		/* A capped count must not claim to be exact: the backend sends the cap it used
		 * alongside the number, and hitting it renders as "99+". */
		count_label(key) {
			const value = this.nav[key];
			const cap = this.nav[key + "_cap"];
			return cap && value >= cap ? `${cap}+` : String(value);
		}

		render_list(kind, rows, date) {
			const is_arrivals = kind === "arrivals";
			const $body = this.$container.find(`[data-fdc="body-${kind}"]`);
			this.$container.find(`[data-fdc="count-${kind}"]`).text(rows.length);

			if (!rows.length) {
				$body.html(`
					<div class="fdc-empty">
						${svg('<circle cx="12" cy="12" r="9"></circle><path d="M8 12h8"></path>', 28)}
						<div>${is_arrivals ? __("No arrivals for this date") : __("No departures for this date")}</div>
					</div>`);
				return;
			}

			$body.html(rows.map((r) => this.row_html(r, is_arrivals, date)).join(""));
		}

		row_html(r, is_arrivals, date) {
			const href = `/app/hotel-reservation/${encodeURIComponent(r.name)}`;
			const time = is_arrivals ? r.arrival_time : r.departure_time;
			const meta = [r.room || __("Unassigned"), r.room_type, time ? time.substring(0, 5) : null]
				.filter(Boolean)
				.join(" · ");

			let pill = "";
			if (is_arrivals) {
				if (r.status === "Checked In" || r.status === "Checked Out") {
					pill = `<span class="fdc-pill is-done">${__("Arrived")}</span>`;
				} else if (r.status === "Reserved") {
					const late = frappe.datetime.get_diff(frappe.datetime.now_date(), date) > 0;
					pill = late
						? `<span class="fdc-pill is-late">${__("No Show")}</span>`
						: `<span class="fdc-pill is-pending">${__("Expected")}</span>`;
				}
			} else {
				if (r.status === "Checked Out") {
					pill = `<span class="fdc-pill is-done">${__("Departed")}</span>`;
				} else if (r.status === "Checked In") {
					const late = frappe.datetime.get_diff(frappe.datetime.now_date(), date) > 0;
					pill = late
						? `<span class="fdc-pill is-late">${__("Overstay")}</span>`
						: `<span class="fdc-pill is-pending">${__("Due out")}</span>`;
				}
				// Money owed is the one thing that must not be missed at checkout.
				if (r.status === "Checked In" && flt_gt_zero(r.folio_balance)) {
					pill =
						`<span class="fdc-pill is-due">${esc(format_currency_short(r.folio_balance))}</span>` +
						pill;
				}
			}

			return `
				<div class="fdc-row">
					<div class="fdc-row-main">
						<a class="fdc-row-name" href="${href}">${esc(r.guest_name || r.name)}</a>
						<div class="fdc-row-meta">${esc(meta)}</div>
					</div>
					<div class="fdc-row-side">${pill}</div>
				</div>`;
		}

		start_auto_refresh() {
			// The console sits open on a desk all shift. Refresh quietly, but never
			// against a hidden tab — that is just load with nobody looking at it.
			this.timer = setInterval(() => {
				if (document.hidden) return;
				if (!$(this.wrapper).is(":visible")) return;
				this.refresh();
			}, 60000);
		}

		destroy() {
			clearInterval(this.timer);
			$(document).off("keydown.fdc", this.key_handler);
		}
	}

	/* ----------------------------------------------------------------- small helpers */

	function svg(paths, size) {
		return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"
			stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
			stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
	}

	/* A number nobody can act on is decoration. Each card is an anchor whose href is
	 * set per-refresh in render_stats(), so clicking "Arrivals Pending" lands on
	 * exactly those reservations for exactly the date on screen. */
	function stat_card(tone, label, key, sub) {
		return `
			<a class="fdc-stat tone-${tone}" data-fdc="stat-${key}" href="#">
				<div class="fdc-stat-label">${esc(label)}</div>
				<div class="fdc-stat-value" data-fdc="val-${key}">–</div>
				<div class="fdc-stat-sub">${sub}</div>
			</a>`;
	}

	function panel(kind, title, icon) {
		return `
			<div class="fdc-panel">
				<div class="fdc-panel-head">
					<span class="fdc-panel-title">${svg(icon, 15)} ${esc(title)}</span>
					<span class="fdc-panel-count" data-fdc="count-${kind}">0</span>
				</div>
				<div class="fdc-panel-body" data-fdc="body-${kind}">
					<div class="fdc-empty">${__("Loading…")}</div>
				</div>
			</div>`;
	}

	function flt_gt_zero(value) {
		return flt(value) > 0.005;
	}

	function format_currency_short(value) {
		return format_currency(flt(value), frappe.defaults.get_default("currency"));
	}

})();
