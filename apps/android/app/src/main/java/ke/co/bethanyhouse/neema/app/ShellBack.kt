package ke.co.bethanyhouse.neema.app

/**
 * What system back (and the predictive back gesture) closes at the shell's
 * level, topmost first:
 *
 * 1. the bell's popup on a tablet — drawn over everything, it swallows taps
 *    elsewhere, so nothing under it can have opened later;
 * 2. the account menu open inline in the sidebar (on the collapsed rail it
 *    is a focusable popup, which closes itself on back);
 * 3. the phone's navigation drawer;
 * 4. — then whatever the view has open (a dialog, a sheet, a thread, a
 *    detail pane, a search: each feature's own back handlers) —
 * 5. the previous view ([DashboardViewModel.back]), then the inbox, and only
 *    then out of the app.
 *
 * On a phone the bell is a bottom sheet, which is its own window and closes
 * itself on back before any of this is asked.
 *
 * 1–3 are one back handler that re-registers whenever the top overlay
 * changes, so it always sits above the views' handlers (registered earlier);
 * 5 is registered before any view is composed, so every view's handler sits
 * above it. The web has none of this: its overlays close on an outside click
 * or Escape, and the browser's back leaves the dashboard.
 */
enum class ShellOverlay { Bell, AccountMenu, Drawer }

/** The shell overlay system back closes now, or null to let the view (then the view history) have it. */
fun shellBackTarget(bellPopupOpen: Boolean, accountMenuOpen: Boolean, drawerOpen: Boolean): ShellOverlay? = when {
    bellPopupOpen -> ShellOverlay.Bell
    accountMenuOpen -> ShellOverlay.AccountMenu
    drawerOpen -> ShellOverlay.Drawer
    else -> null
}
