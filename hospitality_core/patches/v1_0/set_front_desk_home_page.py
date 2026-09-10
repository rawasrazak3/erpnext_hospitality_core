"""Land desk users on the Front Desk Console instead of a workspace.

Frappe resolves the desk landing screen in `frappe.boot.add_home_page`: it reads the
`desktop:home_page` default and, if that names a Page the user may read, boots into it.
The value was 'workspace', which is not a Page at all, so the lookup raised and the
boot fell back to the workspace list.

Set as a global default rather than per user, so new staff get it too. It stays a
default, so an individual user (or the site) can still override it later without this
patch fighting them — patches run once.
"""

import frappe

HOME_PAGE = "front-desk-console"


def execute():
	if not frappe.db.exists("Page", HOME_PAGE):
		return

	frappe.db.set_default("desktop:home_page", HOME_PAGE)

	# A user pinned to a default workspace never reaches the home page at all
	# (auth.set_user_info redirects straight to /app/<workspace>), which would make
	# this change look like it silently did nothing for exactly those users.
	pinned = frappe.get_all(
		"User",
		filters={"default_workspace": ["is", "set"], "user_type": "System User"},
		pluck="name",
	)
	if pinned:
		frappe.logger().info(
			f"set_front_desk_home_page: {len(pinned)} user(s) pinned to a default "
			f"workspace will still land there: {', '.join(pinned)}"
		)

	frappe.db.commit()
