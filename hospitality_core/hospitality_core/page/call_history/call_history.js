/* Call History (/app/call-history) — who has been ringing us, and who owes them a call back.
 *
 * The screen is organised around a caller, not a call. The left pane is one row per
 * number with its whole history behind it; the right pane opens that number: the totals,
 * who they already are to the hotel, and every call underneath. A desk clerk should be
 * able to answer "how many times has this person tried us, and did anyone call back"
 * without opening a report or typing a filter.
 *
 * Conventions follow front_desk_console.js:
 *   - Styling lives in call_history.css on Frappe's design tokens, so the page follows
 *     the active theme. Nothing is injected into document.head.
 *   - Everything interpolated into HTML goes through esc(); contact names come off a
 *     guest's handset and are not ours to trust.
 *   - Everything lives inside an IIFE, because Frappe evaluates page scripts by
 *     appending a <script> to <head> and every top-level const would land on window.
 */
(function () {

	frappe.pages["call-history"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Call History"),
			single_column: true,
		});

		wrapper.chp = new CallHistory(page, wrapper);
	};

	frappe.pages["call-history"].on_page_show = function (wrapper) {
		// Calls land while the page sits open on the desk; coming back should not show
		// the queue as it was an hour ago.
		if (wrapper.chp) wrapper.chp.refresh();
	};

	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));

	const svg = (paths, size) =>
		`<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none"
			stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
			stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;

	const ICONS = {
		search: '<circle cx="11" cy="11" r="7"></circle><path d="M21 21l-4.3-4.3"></path>',
		empty: '<circle cx="12" cy="12" r="9"></circle><path d="M8 12h8"></path>',
	};

	/* The four questions the desk actually asks of the call log. Each carries a count
	 * from the server, so a tab never offers a queue that turns out to be empty. */
	const TABS = [
		{ key: "all", label: __("All callers") },
		{ key: "followup", label: __("Needs follow-up"), tone: "is-warn" },
		{ key: "missed", label: __("Never connected"), tone: "is-alert" },
		{ key: "today", label: __("Today") },
	];

	const METHOD = "hospitality_core.hospitality_core.page.call_history.call_history.";

	class CallHistory {
		constructor(page, wrapper) {
			this.page = page;
			this.wrapper = wrapper;
			this.$container = $(wrapper).find(".layout-main-section");

			this.view = "all";
			this.sort = "recent";
			this.search = "";
			this.start = 0;
			this.rows = [];
			this.selected = null;
			this.load_seq = 0;
			this.detail_seq = 0;

			this.page.set_secondary_action(__("Refresh"), () => this.refresh(), "refresh");

			this.render_shell();
			this.bind_events();

			// CRM Call Log carries its own permissions, and on many sites the desk roles do
			// not have them. Asking the server anyway answers with a red PermissionError
			// dialog, which tells the clerk nothing they can act on.
			if (!frappe.model.can_read("CRM Call Log")) {
				this.render_no_access();
				return;
			}

			this.load();
			this.start_auto_refresh();
		}

		// ------------------------------------------------------------------- shell
		render_shell() {
			this.$container.html(`
				<div class="chp">
					<div class="chp-stats" data-chp="stats"></div>

					<div class="chp-body">
						<div class="chp-pane chp-list">
							<div class="chp-list-head">
								<div class="chp-search">
									<span class="chp-search-icon">${svg(ICONS.search, 15)}</span>
									<input type="text" class="chp-search-input" data-chp="search"
										placeholder="${__("Search number or name…")}"
										autocomplete="off" spellcheck="false"
										aria-label="${__("Search callers by number or name")}">
								</div>
								<div class="chp-tabs" data-chp="tabs" role="tablist"></div>
								<div class="chp-sortline">
									<span data-chp="list-count"></span>
									<button class="chp-sort" data-chp="sort"></button>
								</div>
							</div>
							<div class="chp-scroll" data-chp="numbers"></div>
							<div class="chp-more" data-chp="more" hidden>
								<button class="btn btn-xs btn-default" data-chp="load-more">
									${__("Load more")}
								</button>
							</div>
						</div>

						<div class="chp-pane chp-detail" data-chp="detail"></div>
					</div>
				</div>
			`);
			this.$container.css("padding-bottom", "0");
			this.render_sort();
			this.render_detail(null);
		}

		bind_events() {
			const $c = this.$container;

			$c.on("click", "[data-chp-tab]", (e) => {
				this.view = $(e.currentTarget).attr("data-chp-tab");
				this.load();
			});

			$c.on("click", '[data-chp="sort"]', () => {
				this.sort = this.sort === "recent" ? "calls" : "recent";
				this.render_sort();
				this.load();
			});

			$c.on("click", '[data-chp="load-more"]', () => this.load({ append: true }));

			// A whole row is the target, not a link inside it: the pane is a queue being
			// worked through, and a 3px link is a poor thing to hit between calls.
			$c.on("click", "[data-chp-key]", (e) => {
				this.select($(e.currentTarget).attr("data-chp-key"));
			});

			// The rows carry role="button" and a tab stop, so they have to answer the keys
			// a button answers.
			$c.on("keydown", "[data-chp-key], [data-chp-call]", (e) => {
				if (e.key !== "Enter" && e.key !== " ") return;
				e.preventDefault();
				$(e.currentTarget).trigger("click");
			});

			$c.on("click", "[data-chp-call]", (e) => {
				$(e.currentTarget).closest(".chp-call").toggleClass("is-open");
			});

			$c.on("click", '[data-chp="create-enquiry"]', () => this.create_enquiry());
			$c.on("click", '[data-chp="follow-up"]', () => this.follow_up_dialog());

			const $search = $c.find('[data-chp="search"]');
			$search.on(
				"input",
				frappe.utils.debounce(() => {
					this.search = $search.val().trim();
					this.load();
				}, 250)
			);
			$search.on("keydown", (e) => {
				if (e.key !== "Escape") return;
				$search.val("");
				this.search = "";
				this.load();
			});

			// "/" jumps to search, the same as the Front Desk console.
			this.key_handler = (e) => {
				if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
				const tag = (e.target.tagName || "").toLowerCase();
				if (tag === "input" || tag === "textarea" || e.target.isContentEditable) return;
				if (!$(this.wrapper).is(":visible")) return;
				e.preventDefault();
				$search.trigger("focus").select();
			};
			$(document).on("keydown.chp", this.key_handler);
		}

		// -------------------------------------------------------------------- load
		load(opts) {
			opts = opts || {};
			this.start = opts.append ? this.rows.length : 0;
			if (!opts.append) this.$container.find('[data-chp="numbers"]').html(this.loading_rows());

			// Responses can land out of order once someone is typing; only the newest
			// request may paint.
			const seq = ++this.load_seq;
			return frappe
				.xcall(METHOD + "get_overview", {
					view: this.view,
					search: this.search,
					sort: this.sort,
					start: this.start,
				})
				.then((data) => {
					if (seq !== this.load_seq || !data) return;
					this.rows = opts.append ? this.rows.concat(data.numbers) : data.numbers;
					this.render_stats(data.totals);
					this.render_tabs(data.tabs);
					this.render_numbers(data);

					// Something is always open, so the right pane is never a blank slab —
					// but a refresh must not move the desk off the caller being worked.
					if (!this.selected && this.rows.length) this.select(this.rows[0].number_key);
					else this.mark_selected();
				})
				.catch(() => {
					if (seq !== this.load_seq) return;
					this.$container
						.find('[data-chp="numbers"]')
						.html(this.empty(__("Could not load call history")));
				});
		}

		refresh() {
			// Keeps the open caller and the tab; only the data underneath is re-read.
			const keep = this.selected;
			return this.load().then(() => {
				if (keep) this.select(keep, { quiet: true });
			});
		}

		start_auto_refresh() {
			this.timer = setInterval(() => {
				if (document.hidden) return;
				if (!$(this.wrapper).is(":visible")) return;
				// Not while someone is mid-search: the list would jump under them.
				if (this.$container.find('[data-chp="search"]').is(":focus")) return;
				this.refresh();
			}, 60000);
		}

		/* Frappe caches desk pages rather than destroying them, so there is no teardown
		 * hook to hang this on. The timer and the "/" handler both check visibility
		 * instead; this stays for explicit cleanup. */
		destroy() {
			clearInterval(this.timer);
			$(document).off("keydown.chp", this.key_handler);
		}

		// ------------------------------------------------------------------ header
		render_stats(t) {
			t = t || {};
			const cards = [
				{ label: __("Calls"), value: cint(t.calls), sub: __("in this list") },
				{ label: __("Callers"), value: cint(t.numbers), sub: __("distinct numbers") },
				{
					label: __("Connected"),
					value: cint(t.connected),
					sub: this.talk_time(t.talk_seconds),
					tone: "ok",
				},
				{
					label: __("Unanswered"),
					value: cint(t.missed),
					sub: __("calls that never connected"),
					tone: "warn",
				},
				{
					label: __("No enquiry yet"),
					value: cint(t.no_enquiry),
					sub: __("callers to follow up"),
					tone: "alert",
				},
			];

			this.$container.find('[data-chp="stats"]').html(
				cards
					.map(
						(c) => `
						<div class="chp-stat tone-${c.tone || "plain"}">
							<div class="chp-stat-label">${esc(c.label)}</div>
							<div class="chp-stat-value">${esc(c.value)}</div>
							<div class="chp-stat-sub">${esc(c.sub)}</div>
						</div>`
					)
					.join("")
			);
		}

		render_tabs(counts) {
			counts = counts || {};
			this.$container.find('[data-chp="tabs"]').html(
				TABS.map((t) => {
					const n = cint(counts[t.key]);
					return `<button class="chp-tab ${this.view === t.key ? "is-active" : ""}"
							data-chp-tab="${t.key}" role="tab"
							aria-selected="${this.view === t.key}">
						<span>${esc(t.label)}</span>
						${n ? `<span class="chp-tab-count ${t.tone || ""}">${n}</span>` : ""}
					</button>`;
				}).join("")
			);
		}

		render_sort() {
			this.$container
				.find('[data-chp="sort"]')
				.text(this.sort === "recent" ? __("Most recent") : __("Most calls"));
		}

		// ------------------------------------------------------------- number list
		render_numbers(data) {
			const $body = this.$container.find('[data-chp="numbers"]');
			const $count = this.$container.find('[data-chp="list-count"]');

			$count.text(
				this.search
					? __("{0} matching", [cint(data.totals && data.totals.numbers)])
					: __("{0} callers", [cint(data.totals && data.totals.numbers)])
			);

			if (!this.rows.length) {
				$body.html(
					this.empty(
						this.search ? __("No caller matches that") : __("No calls in this view")
					)
				);
				this.$container.find('[data-chp="more"]').prop("hidden", true);
				return;
			}

			$body.html(this.rows.map((r) => this.number_row(r)).join(""));
			this.$container.find('[data-chp="more"]').prop("hidden", !data.has_more);
			this.mark_selected();
		}

		number_row(r) {
			const name = r.contact_name || r.enquiry_guest || "";
			const missed = cint(r.missed);
			const calls = cint(r.calls);

			// One badge, not three: the row has to be readable at a glance down a queue.
			let badge = "";
			if (cint(r.no_enquiry)) {
				badge = `<span class="chp-badge is-warn">${__("No enquiry")}</span>`;
			} else if (r.enquiry_status) {
				badge = `<span class="chp-badge">${esc(r.enquiry_status)}</span>`;
			}

			const meta = [
				__("{0} calls", [calls]),
				missed ? __("{0} missed", [missed]) : "",
				cint(r.connected) ? __("{0} connected", [cint(r.connected)]) : "",
			]
				.filter(Boolean)
				.join(" · ");

			return `
				<div class="chp-row" data-chp-key="${esc(r.number_key)}" role="button" tabindex="0">
					<div class="chp-row-dot ${this.tone(r.last_status, r.last_type)}"
						title="${esc(this.call_label(r.last_type, r.last_status))}">
						${r.last_type === "Outgoing" ? "&uarr;" : "&darr;"}
					</div>
					<div class="chp-row-main">
						<div class="chp-row-top">
							<span class="chp-row-name">${esc(name || r.number || r.number_key)}</span>
							<span class="chp-row-when" title="${esc(r.last_time || "")}">
								${esc(this.when(r.last_time))}
							</span>
						</div>
						<div class="chp-row-sub">
							${name ? `<span class="chp-row-num">${esc(r.number || r.number_key)}</span>` : ""}
							<span>${esc(meta)}</span>
						</div>
					</div>
					<div class="chp-row-side">
						<span class="chp-row-calls" title="${__("Calls from this number")}">${calls}</span>
						${badge}
					</div>
				</div>`;
		}

		mark_selected() {
			this.$container.find(".chp-row").removeClass("is-selected");
			if (!this.selected) return;
			this.$container
				.find(`.chp-row[data-chp-key="${CSS.escape(this.selected)}"]`)
				.addClass("is-selected");
		}

		// ------------------------------------------------------------------ detail
		select(key, opts) {
			if (!key) return Promise.resolve();
			opts = opts || {};
			this.selected = key;
			this.mark_selected();
			if (!opts.quiet) {
				this.$container.find('[data-chp="detail"]').html(this.detail_loading());
			}

			const seq = ++this.detail_seq;
			return frappe
				.xcall(METHOD + "get_number", { number_key: key })
				.then((data) => {
					if (seq !== this.detail_seq) return;
					this.detail = data;
					this.render_detail(data);
				})
				.catch(() => {
					if (seq !== this.detail_seq) return;
					this.$container
						.find('[data-chp="detail"]')
						.html(this.empty(__("Could not load this caller")));
				});
		}

		render_detail(d) {
			const $pane = this.$container.find('[data-chp="detail"]');

			if (!d || !d.summary) {
				$pane.html(
					this.empty(
						__("Choose a caller"),
						__("Their calls, their enquiry and the follow-up actions appear here.")
					)
				);
				return;
			}

			const s = d.summary;
			const name = d.contact_name || (d.enquiry && d.enquiry.guest_name) || "";
			const dial = String(d.number || d.number_key).replace(/[^\d+]/g, "");
			const digits = dial.replace(/\D/g, "");

			$pane.html(`
				<div class="chp-detail-head">
					<div>
						<div class="chp-detail-name">${esc(name || d.number || d.number_key)}</div>
						<div class="chp-detail-num">${esc(d.number || d.number_key)}${
							name ? "" : ` · ${__("Unknown caller")}`
						}</div>
					</div>
					<div class="chp-detail-actions">
						<a class="btn btn-xs btn-default" href="tel:${esc(dial)}">${__("Call")}</a>
						<a class="btn btn-xs btn-default" target="_blank" rel="noopener"
							href="https://wa.me/${esc(digits)}">${__("WhatsApp")}</a>
					</div>
				</div>

				<div class="chp-scroll">
					<div class="chp-figures">
						${figure(__("Total calls"), cint(s.calls))}
						${figure(__("Incoming"), cint(s.incoming))}
						${figure(__("Outgoing"), cint(s.outgoing))}
						${figure(__("Connected"), cint(s.connected), "ok")}
						${figure(__("Unanswered"), cint(s.missed), "warn")}
						${figure(__("Talk time"), this.talk_duration(s.talk_seconds))}
					</div>

					<div class="chp-since">${esc(
						__("First call {0} · last call {1}", [
							this.when(s.first_time),
							this.when(s.last_time),
						])
					)}</div>

					${this.follow_up_card(d)}
					${this.guest_card(d.guest)}

					<div class="chp-section-title">
						${__("Call log")}
						<span class="chp-chip">${cint(s.calls)}</span>
					</div>
					${this.calls_html(d)}
				</div>
			`);
		}

		/* The point of the page: what happens next for this caller. An unknown number
		 * gets one button that turns it into an enquiry; a known one gets the enquiry
		 * and the follow-up it is waiting for. */
		follow_up_card(d) {
			const e = d.enquiry;

			if (!e) {
				const can = frappe.model.can_create("Hotel Enquiry");
				return `
					<div class="chp-card is-warn">
						<div class="chp-card-main">
							<div class="chp-card-title">${__("Nobody has followed this caller up")}</div>
							<div class="chp-card-sub">${__(
								"No enquiry exists for this number."
							)}</div>
						</div>
						${
							can
								? `<button class="btn btn-xs btn-primary" data-chp="create-enquiry">
									${__("Create Enquiry")}</button>`
								: ""
						}
					</div>`;
			}

			const due =
				e.next_follow_up && e.next_follow_up <= frappe.datetime.now_datetime()
					? `<span class="chp-badge is-warn">${__("Follow-up due")}</span>`
					: e.next_follow_up
					? `<span class="chp-badge">${__("Due {0}", [this.when(e.next_follow_up)])}</span>`
					: "";

			const stay =
				e.check_in_date && e.check_out_date
					? `${frappe.datetime.str_to_user(e.check_in_date)} → ${frappe.datetime.str_to_user(
							e.check_out_date
					  )}`
					: __("No dates yet");

			return `
				<div class="chp-card">
					<div class="chp-card-main">
						<div class="chp-card-title">
							<a href="/app/hotel-enquiry/${encodeURIComponent(e.name)}">${esc(
				e.guest_name || e.name
			)}</a>
							<span class="chp-badge">${esc(e.status || "")}</span>
							${due}
						</div>
						<div class="chp-card-sub">${esc(
							[e.name, stay, e.enquiry_owner].filter(Boolean).join(" · ")
						)}</div>
					</div>
					${
						frappe.model.can_write("Hotel Enquiry")
							? `<button class="btn btn-xs btn-default" data-chp="follow-up">
								${__("Log Follow-up")}</button>`
							: ""
					}
				</div>`;
		}

		guest_card(g) {
			if (!g) return "";
			return `
				<div class="chp-card">
					<div class="chp-card-main">
						<div class="chp-card-title">
							<a href="/app/guest/${encodeURIComponent(g.name)}">${esc(g.full_name || g.name)}</a>
							<span class="chp-badge">${__("Guest")}</span>
						</div>
						<div class="chp-card-sub">${esc(
							[g.guest_type, g.mobile_no, g.email_id].filter(Boolean).join(" · ")
						)}</div>
					</div>
				</div>`;
		}

		/* Every call for this number, newest first. A row opens to show the rest of what
		 * the handset reported — which of our lines it came through, the agent, the
		 * recording — so the common case stays one line per call. */
		calls_html(d) {
			const calls = d.calls || [];
			if (!calls.length) return this.empty(__("No calls logged"));

			const rows = calls
				.map((c) => {
					const detail = [
						[__("Line"), [c.line, c.line_label].filter(Boolean).join(" · ")],
						[__("Agent"), c.agent],
						[__("Channel"), c.channel],
						[__("Started"), c.start_time ? frappe.datetime.str_to_user(c.start_time) : ""],
						[__("Ended"), c.end_time ? frappe.datetime.str_to_user(c.end_time) : ""],
						[__("Contact name"), c.contact_name],
						[__("Call ID"), c.name],
					]
						.filter((pair) => pair[1])
						.map(
							(pair) =>
								`<div class="chp-kv"><span>${esc(pair[0])}</span><span>${esc(
									pair[1]
								)}</span></div>`
						)
						.join("");

					const recording = c.recording_url
						? `<a class="chp-kv-link" href="${esc(c.recording_url)}" target="_blank"
								rel="noopener">${__("Open recording")}</a>`
						: "";

					const enquiry = c.enquiry
						? `<a class="chp-kv-link" href="/app/hotel-enquiry/${encodeURIComponent(
								c.enquiry
						  )}">${esc(c.enquiry)}</a>`
						: "";

					return `
						<div class="chp-call">
							<div class="chp-call-line" data-chp-call="${esc(c.name)}" role="button" tabindex="0">
								<span class="chp-row-dot ${this.tone(c.status, c.type)}">${
						c.type === "Outgoing" ? "&uarr;" : "&darr;"
					}</span>
								<span class="chp-call-what">${esc(this.call_label(c.type, c.status))}</span>
								<span class="chp-call-dur">${esc(this.duration(c.duration, c.status))}</span>
								<span class="chp-call-when" title="${esc(c.start_time || "")}">${esc(
						this.when(c.start_time)
					)}</span>
							</div>
							<div class="chp-call-detail">
								${detail}
								${recording || enquiry ? `<div class="chp-kv-links">${recording}${enquiry}</div>` : ""}
							</div>
						</div>`;
				})
				.join("");

			const note = d.truncated
				? `<div class="chp-note">${__("Showing the most recent {0} calls.", [
						calls.length,
				  ])}</div>`
				: "";

			return `<div class="chp-calls">${rows}</div>${note}`;
		}

		// ----------------------------------------------------------------- actions
		create_enquiry() {
			const d = this.detail;
			const last = d && d.calls && d.calls[0];
			if (!last) return;

			frappe.call({
				method: "hospitality_core.hospitality_core.api.telephony.create_enquiry_from_call",
				args: { call_log: last.name, guest_name: d.contact_name || undefined },
				freeze: true,
				freeze_message: __("Creating enquiry…"),
				callback: (r) => {
					if (!r.message) return;
					frappe.show_alert({ message: __("Enquiry {0} created", [r.message]), indicator: "green" });
					this.select(this.selected, { quiet: true });
					this.load();
				},
			});
		}

		follow_up_dialog() {
			const e = this.detail && this.detail.enquiry;
			if (!e) return;
			const last = this.detail.calls && this.detail.calls[0];

			const dlg = new frappe.ui.Dialog({
				title: __("Log Follow-up"),
				fields: [
					{
						fieldname: "outcome",
						label: __("Outcome"),
						fieldtype: "Select",
						reqd: 1,
						options: ["Connected", "No Answer", "Callback Requested", "Quoted", "Not Interested"],
						default: "Connected",
					},
					{ fieldname: "remarks", label: __("Remarks"), fieldtype: "Small Text" },
					{ fieldname: "next_follow_up", label: __("Next Follow-up"), fieldtype: "Datetime" },
				],
				primary_action_label: __("Log"),
				primary_action: (values) => {
					frappe.call({
						method:
							"hospitality_core.hospitality_core.doctype.hotel_enquiry.hotel_enquiry.log_follow_up",
						// The call this follow-up answers, so the enquiry's history says
						// which ring was returned rather than just "somebody rang back".
						args: Object.assign(
							{ enquiry: e.name, call_log: last ? last.name : undefined },
							values
						),
						callback: () => {
							dlg.hide();
							frappe.show_alert({ message: __("Follow-up logged"), indicator: "green" });
							this.select(this.selected, { quiet: true });
							this.load();
						},
					});
				},
			});
			dlg.show();
		}

		// ----------------------------------------------------------------- helpers
		/* Missed reads first: a call that never connected is the one that needs doing
		 * something about, whichever direction it went. */
		tone(status, type) {
			if (status && status !== "Completed") return "is-missed";
			return type === "Outgoing" ? "is-out" : "is-in";
		}

		call_label(type, status) {
			const dir = type === "Outgoing" ? __("Outgoing") : __("Incoming");
			return status && status !== "Completed" ? `${dir} · ${status}` : dir;
		}

		duration(seconds, status) {
			// An unanswered call's "duration" is how long it rang, which is not talk
			// time and should not be shown as though it were.
			if (status && status !== "Completed") return "—";
			const s = cint(seconds);
			if (!s) return "—";
			const m = Math.floor(s / 60);
			return m ? `${m}m ${s % 60}s` : `${s}s`;
		}

		/* Bare figure for a column that is already labelled "Talk time"; the sentence
		 * form below is for the stat cards, where the number stands on its own. */
		talk_duration(seconds) {
			const s = cint(seconds);
			if (!s) return "—";
			const h = Math.floor(s / 3600);
			const m = Math.round((s % 3600) / 60);
			if (h) return `${h}h ${m}m`;
			return m ? `${m}m` : `${s}s`;
		}

		talk_time(seconds) {
			const s = cint(seconds);
			if (!s) return __("no talk time");
			return __("{0} talk time", [this.talk_duration(s)]);
		}

		when(dt) {
			if (!dt) return "—";
			return frappe.datetime.prettyDate ? frappe.datetime.prettyDate(dt, true) : dt;
		}

		render_no_access() {
			this.$container.find('[data-chp="stats"]').empty();
			this.$container.find(".chp-body").html(
				`<div class="chp-pane chp-detail">${this.empty(
					__("You cannot read call logs"),
					__("Ask an administrator for read access to CRM Call Log.")
				)}</div>`
			);
		}

		empty(title, sub) {
			return `
				<div class="chp-empty">
					${svg(ICONS.empty, 26)}
					<div class="chp-empty-title">${esc(title)}</div>
					${sub ? `<div class="chp-empty-sub">${esc(sub)}</div>` : ""}
				</div>`;
		}

		loading_rows() {
			return new Array(6)
				.fill('<div class="chp-row is-loading"><div class="chp-skeleton"></div></div>')
				.join("");
		}

		detail_loading() {
			return `<div class="chp-scroll"><div class="chp-figures">${new Array(6)
				.fill('<div class="chp-figure is-loading"><div class="chp-skeleton"></div></div>')
				.join("")}</div></div>`;
		}
	}

	function figure(label, value, tone) {
		return `
			<div class="chp-figure tone-${tone || "plain"}">
				<div class="chp-figure-value">${esc(value)}</div>
				<div class="chp-figure-label">${esc(label)}</div>
			</div>`;
	}

})();
