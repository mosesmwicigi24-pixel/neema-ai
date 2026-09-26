package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.util.AppClock

import ke.co.bethanyhouse.neema.app.NavItem
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.app.buildNavItems
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.isPhoneLike
import ke.co.bethanyhouse.neema.core.util.Fmt
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.util.TimeZone

/** Round 2: the edge paths of lib/utils.ts and the dashboard's nav. */
class CoreRound2Test {
    private var savedZone: TimeZone? = null

    @Before fun nairobi() { savedZone = TimeZone.getDefault(); TimeZone.setDefault(TimeZone.getTimeZone("Africa/Nairobi")) }
    @After fun restore() { TimeZone.setDefault(savedZone) }

    @Test
    fun datesUseEnKeShortMonthsWithSept() {
        // node: new Date(...).toLocaleDateString("en-KE", {day:"numeric", month:"short", year:"numeric"})
        assertEquals("5 Sept 2026", Fmt.date("2026-09-05T12:00:00Z"))
        assertEquals("25 Sept 2026", Fmt.date("2026-09-25T08:00:00+03:00"))
        assertEquals("5 Jan 2026", Fmt.date("2026-01-05T12:00:00Z"))
        assertEquals("31 Dec 2025", Fmt.date("2025-12-31T12:00:00Z"))
        assertEquals("5 May 2026", Fmt.date("2026-05-05T12:00:00Z"))
        assertEquals("5 Jun 2026", Fmt.date("2026-06-05T12:00:00Z"))
        // Every other month is the same three letters Java uses.
        val expected = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec")
        expected.forEachIndexed { i, m -> assertEquals("1 $m 2026", Fmt.date("2026-%02d-01T12:00:00Z".format(i + 1))) }
    }

    @Test
    fun dateTimeAndDayLabelShareTheWebMonths() {
        assertEquals("5 Sept 2026, 15:30", Fmt.dateTime("2026-09-05T12:30:00Z"))
        assertEquals("1 Sept 2025", Fmt.dayLabel("2025-09-01T12:00:00Z"))
        assertEquals("Today", Fmt.dayLabel(AppClock.instant().toString()))
    }

    @Test
    fun missingOrBrokenDatesReadAsADash() {
        assertEquals("—", Fmt.date(null))
        assertEquals("—", Fmt.date(""))
        assertEquals("—", Fmt.date("not a date"))
        assertEquals("—", Fmt.dateTime(null))
        assertEquals("", Fmt.time(null))
    }

    @Test
    fun websiteVisitorsGetThePersonGlyph() {
        assertEquals("Website visitor", Fmt.displayName(null, "web_3f9a1c"))
        assertTrue(isPhoneLike(Fmt.displayName(null, "web_3f9a1c")))
        assertTrue(isPhoneLike("website visitor"))
        assertTrue(isPhoneLike("web_3f9a1c"))
        // A real name that merely starts like it keeps its initials.
        assertFalse(isPhoneLike("Website Visitors Ltd"))
        assertFalse(isPhoneLike("Webster Ouma"))
    }

    @Test
    fun badgesArePassedThroughUncapped() {
        // Sidebar.tsx prints the count as is ("143"), never "99+".
        val items: List<NavItem> = buildNavItems({ true }, humanConvs = 143, pendingOrders = 0)
        assertEquals(143, items.first { it.id == ViewId.Conversations }.badge)
        assertEquals(0, items.first { it.id == ViewId.Orders }.badge)
    }

    @Test
    fun navOrderMatchesDesktopNavItems() {
        val all = buildNavItems({ true }, 0, 0).map { it.id }
        assertEquals(
            listOf(
                ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Reports, ViewId.Deals, ViewId.Leads,
                ViewId.Overview, ViewId.Catalog, ViewId.Agents, ViewId.Settings, ViewId.Profile,
            ),
            all,
        )
        // A legacy agent: view_leads and view_catalog, nothing admin.
        val agent = Perms.effective("agent", false, null)
        assertEquals(
            listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Deals, ViewId.Leads, ViewId.Catalog, ViewId.Profile),
            buildNavItems({ it in agent }, 0, 0).map { it.id },
        )
    }
}
