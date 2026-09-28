package ke.co.bethanyhouse.neema.tablet

import ke.co.bethanyhouse.neema.core.ui.Adaptive
import ke.co.bethanyhouse.neema.core.ui.NavMode
import ke.co.bethanyhouse.neema.core.ui.SideMode
import ke.co.bethanyhouse.neema.core.ui.fitWidths
import ke.co.bethanyhouse.neema.core.ui.inboxPanes
import ke.co.bethanyhouse.neema.core.ui.navModeFor
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Tab S9 Ultra's windows, as numbers: what navigation each gets and how
 * the inbox shares the room. The content width is the window minus the
 * navigation — 208dp docked (270 at 130% text), 60dp rail, 0 drawer.
 */
class TabletLayoutTest {
    private fun content(window: Int, fontScale: Float = 1f) = when (navModeFor(window)) {
        NavMode.Drawer -> window
        NavMode.Rail -> window - 60
        NavMode.Docked -> window - (208 * fontScale.coerceIn(1f, 1.3f)).toInt()
    }

    // 1. On its side, default zoom: everything docked, the thread readable.
    @Test fun fullLandscape() {
        assertEquals(NavMode.Docked, navModeFor(1480))
        val p = inboxPanes(content(1480))
        assertTrue(p.twoPane)
        assertEquals(SideMode.Docked, p.customer)
        assertTrue("thread ${p.threadWidth}", p.threadWidth >= Adaptive.THREAD_MIN)
        assertTrue(p.listWidth in 320..400)
    }

    // 2. One zoom step up (1393 × 870): still three panes, still a readable thread.
    @Test fun zoomedLandscape() {
        val p = inboxPanes(content(1393))
        assertTrue(p.twoPane)
        assertEquals(SideMode.Docked, p.customer)
        assertTrue("thread ${p.threadWidth}", p.threadWidth >= Adaptive.THREAD_MIN)
    }

    // 3. Upright: the rail, two panes, the customer slides over a roomy thread.
    @Test fun portrait() {
        assertEquals(NavMode.Rail, navModeFor(924))
        val p = inboxPanes(content(924))
        assertTrue(p.twoPane)
        assertEquals(SideMode.Overlay, p.customer)
        assertTrue("thread ${p.threadWidth}", p.roomyThread)
    }

    // 4. Split screen 50/50: one pane at a time, the rail stays.
    @Test fun halfSplit() {
        assertEquals(NavMode.Rail, navModeFor(736))
        assertFalse(inboxPanes(content(736)).twoPane)
    }

    // 5. The ⅔ side: two panes, customer on demand.
    @Test fun twoThirds() {
        val p = inboxPanes(content(980))
        assertTrue(p.twoPane)
        assertEquals(SideMode.Overlay, p.customer)
        assertTrue(p.threadWidth >= Adaptive.THREAD_MIN)
    }

    // 6. The ⅓ side: the phone layout (drawer, one pane).
    @Test fun oneThird() {
        assertEquals(NavMode.Drawer, navModeFor(488))
        assertFalse(inboxPanes(content(488)).twoPane)
    }

    // 7. Upright split (top or bottom half): as wide as portrait, so two panes.
    @Test fun portraitSplit() = assertTrue(inboxPanes(content(924)).twoPane)

    // 8. The pop-up window: one pane, the rail.
    @Test fun popup() {
        assertEquals(NavMode.Rail, navModeFor(640))
        assertFalse(inboxPanes(content(640)).twoPane)
    }

    // 9. DeX on a 1920-wide monitor: everything docked, the activity log opens beside.
    @Test fun dexMonitor() {
        val p = inboxPanes(content(1920))
        assertEquals(SideMode.Docked, p.customer)
        assertTrue(p.activityDocks)
        assertTrue(p.threadWidth - p.activityWidth >= Adaptive.THREAD_MIN)
    }

    // 10. 130% text widens the docked sidebar: the thread still keeps its room.
    @Test fun largeTextLandscape() {
        val p = inboxPanes(content(1480, 1.3f))
        assertTrue(p.twoPane)
        assertTrue("thread ${p.threadWidth}", p.threadWidth >= Adaptive.THREAD_MIN)
    }

    // 11. Every width from 720 to 2560: a two-pane thread is never squeezed,
    // and a docked side pane never pushes it under the minimum.
    @Test fun sweepNeverSqueezesTheThread() {
        for (w in Adaptive.TWO_PANE_MIN..2560) {
            val p = inboxPanes(w)
            assertTrue("$w two-pane", p.twoPane)
            assertTrue("$w thread ${p.threadWidth}", p.threadWidth >= Adaptive.THREAD_MIN)
            if (p.activityDocks) assertTrue("$w activity", p.threadWidth - p.activityWidth >= Adaptive.THREAD_MIN)
            assertTrue("$w fits", p.listWidth + p.threadWidth + (if (p.customer == SideMode.Docked) p.customerWidth + 33 else 0) <= w)
        }
    }

    // 12. Nav thresholds.
    @Test fun navThresholds() {
        assertEquals(NavMode.Drawer, navModeFor(599))
        assertEquals(NavMode.Rail, navModeFor(600))
        assertEquals(NavMode.Rail, navModeFor(1199))
        assertEquals(NavMode.Docked, navModeFor(1200))
    }

    // 14. A call docks beside the view on a Tab S9 Ultra on its side (and DeX),
    // covers the content on narrower windows, and is the top bar when minimised.
    @Test fun callDocking() {
        val live = ke.co.bethanyhouse.neema.feature.calls.CallPhase.InCall
        val ringing = ke.co.bethanyhouse.neema.feature.calls.CallPhase.Ringing
        val idle = ke.co.bethanyhouse.neema.feature.calls.CallPhase.Idle
        fun docks(phase: ke.co.bethanyhouse.neema.feature.calls.CallPhase, window: Int, min: Boolean = false) =
            ke.co.bethanyhouse.neema.feature.calls.callDocks(phase, min, content(window))
        assertTrue(docks(live, 1480))
        assertTrue(docks(ringing, 1393))
        assertTrue(docks(live, 1920))
        assertFalse("upright", docks(live, 924))
        assertFalse("split", docks(live, 736))
        assertFalse("phone", docks(live, 412))
        assertFalse("minimised", docks(live, 1480, min = true))
        assertFalse("idle", docks(idle, 1480))
        // Docked, the view beside keeps a two-pane inbox.
        assertTrue(inboxPanes(content(1480) - ke.co.bethanyhouse.neema.feature.calls.CALL_PANEL_WIDTH - 1).twoPane)
    }

    // 13. Filter tabs share a row: all visible when they fit, equal when they can be.
    @Test fun fitRowShares() {
        assertEquals(listOf(60, 60, 60), fitWidths(listOf(30, 40, 50), 180))
        assertEquals(listOf(40, 90, 50), fitWidths(listOf(30, 80, 40), 180))
        assertEquals(listOf(100, 100), fitWidths(listOf(100, 100), 150))
        assertEquals(emptyList<Int>(), fitWidths(emptyList(), 100))
    }
}

/** The Calls view's details pane through rotations, splits and filters. */
class CallsDetailsPickTest {
    private fun p(wide: Boolean, shown: List<String>, sel: String?, auto: String?) =
        ke.co.bethanyhouse.neema.feature.calls.detailsPick(wide, shown, sel, auto)

    @Test fun tabletOpensTheNewest() = assertEquals("a", p(true, listOf("a", "b"), null, null).select)
    @Test fun theAgentsPickStays() {
        val r = p(true, listOf("a", "b"), "b", "a")
        assertEquals("b", r.select); assertEquals(null, r.autoPicked)
    }
    @Test fun aFilteredAwayCallMovesToTheFirstShown() = assertEquals("c", p(true, listOf("c"), "a", null).select)
    @Test fun shrinkingDropsOnlyTheAppsPick() {
        assertEquals(null, p(false, listOf("a"), "a", "a").select)
        assertEquals("b", p(false, listOf("a", "b"), "b", null).select)
    }
    @Test fun anEmptyLogKeepsWhatIsOpen() = assertEquals("x", p(true, emptyList(), "x", null).select)
    @Test fun growingBackOpensTheNewestAgain() = assertEquals("a", p(true, listOf("a"), null, null).autoPicked)
}

/** Esc on the Book Cover Keyboard / DeX. */
class EscapeKeyTest {
    private val esc = android.view.KeyEvent.KEYCODE_ESCAPE
    @Test fun escClosesWhatIsOpen() = assertTrue(ke.co.bethanyhouse.neema.core.ui.escapeIsBack(esc, false, true))
    @Test fun escAtTheRootNeverLeavesTheApp() = assertFalse(ke.co.bethanyhouse.neema.core.ui.escapeIsBack(esc, false, false))
    @Test fun modifiedEscAndOtherKeysAreLeftAlone() {
        assertFalse(ke.co.bethanyhouse.neema.core.ui.escapeIsBack(esc, true, true))
        assertFalse(ke.co.bethanyhouse.neema.core.ui.escapeIsBack(android.view.KeyEvent.KEYCODE_ENTER, false, true))
    }
}
