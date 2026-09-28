package ke.co.bethanyhouse.neema.core.ui

/**
 * Large-screen layout rules, decided from the space a view really has (the
 * window, or the content beside the navigation) — never from the screen:
 * a Galaxy Tab S9 Ultra is 1480 × 924 dp, but in split screen the app gets
 * 736, a ⅓ split 488 and a pop-up window 640. Pure functions: every rule is
 * unit-tested at each of those sizes (TabletLayoutTest).
 */
object Adaptive {
    /** A thread never narrower than this beside other panes (~60 characters a line). */
    const val THREAD_MIN = 480

    /**
     * Below this content width the inbox is one pane at a time (list, then
     * thread): the 320dp list plus a [THREAD_MIN] thread need 801dp.
     */
    const val TWO_PANE_MIN = 801

    /** The docked sidebar only from here: narrower windows get the icon rail. */
    const val DOCKED_NAV_MIN = 1200
}

/** How the shell shows navigation in a window [windowWidthDp] wide. */
enum class NavMode { Drawer, Rail, Docked }

fun navModeFor(windowWidthDp: Int): NavMode = when {
    windowWidthDp < 600 -> NavMode.Drawer
    windowWidthDp < Adaptive.DOCKED_NAV_MIN -> NavMode.Rail
    else -> NavMode.Docked
}

/** A side pane: beside the main one, or sliding over it on demand. */
enum class SideMode { Docked, Overlay }

/**
 * The inbox's panes for a content area [contentWidthDp] wide (the window
 * minus the navigation).
 *
 * - One pane below [Adaptive.TWO_PANE_MIN] (a ⅓ split, a pop-up, a phone).
 * - The list takes ~30%, 300–400dp.
 * - The customer panel docks beside the thread only when the thread keeps
 *   [Adaptive.THREAD_MIN] (plus the activity rail); otherwise it slides over
 *   the thread from the end edge when asked for.
 * - The activity log opens beside the thread only when the thread would
 *   still keep [Adaptive.THREAD_MIN]; otherwise it slides over too.
 */
data class InboxPanes(
    val twoPane: Boolean,
    val listWidth: Int,
    val customer: SideMode,
    val customerWidth: Int,
    /** The activity log's collapsed rail sits beside the thread. */
    val activityRail: Boolean,
    /** Opening the activity log docks it at [activityWidth] (else it slides over). */
    val activityDocks: Boolean,
    val activityWidth: Int,
    /** The thread's width with every docked pane closed but the customer panel. */
    val threadWidth: Int,
) {
    /** The thread is roomy enough for its actions on one line beside the badges. */
    val roomyThread: Boolean get() = threadWidth >= 540
}

fun inboxPanes(contentWidthDp: Int): InboxPanes {
    val w = contentWidthDp.coerceAtLeast(0)
    val sheet = minOf(400, (w * 0.9f).toInt())
    if (w < Adaptive.TWO_PANE_MIN) {
        return InboxPanes(false, w, SideMode.Overlay, sheet, false, false, sheet, w)
    }
    val list = (w * 0.30f).toInt().coerceIn(320, 400)
    val afterList = w - list - 1
    val customerW = (w * 0.26f).toInt().coerceIn(300, 360)
    val rail = 32
    val docked = afterList - customerW - 1 - rail >= Adaptive.THREAD_MIN
    val thread = if (docked) afterList - customerW - 1 - rail else afterList
    val activityW = (w * 0.16f).toInt().coerceIn(196, 292)
    val activityDocks = docked && thread - activityW >= Adaptive.THREAD_MIN
    return InboxPanes(
        twoPane = true, listWidth = list,
        customer = if (docked) SideMode.Docked else SideMode.Overlay,
        customerWidth = if (docked) customerW else minOf(400, (afterList * 0.8f).toInt()),
        activityRail = docked, activityDocks = activityDocks, activityWidth = activityW,
        threadWidth = thread,
    )
}

/**
 * The width the current view has, in dp: the window minus the navigation
 * beside it. Provided by the shell (DashboardShell) — no measuring pass, so a
 * view's back handlers keep their order below the shell's overlays. A view
 * shown without the shell (tests, previews) falls back to the window width.
 */
val LocalContentWidthDp = androidx.compose.runtime.compositionLocalOf<Int?> { null }

@androidx.compose.runtime.Composable
fun contentWidthDp(): Int = LocalContentWidthDp.current ?: androidx.compose.ui.platform.LocalConfiguration.current.screenWidthDp
