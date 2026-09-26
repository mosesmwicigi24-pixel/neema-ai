package ke.co.bethanyhouse.neema.reports

import androidx.compose.runtime.CompositionLocalProvider
import ke.co.bethanyhouse.neema.feature.agents.AgentsScreen
import ke.co.bethanyhouse.neema.feature.agents.LocalTeamPreview
import ke.co.bethanyhouse.neema.feature.agents.TeamPreview
import ke.co.bethanyhouse.neema.feature.catalog.CatalogScreen
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportTab
import ke.co.bethanyhouse.neema.feature.reports.ReportsScreen
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.team.AreaShots
import ke.co.bethanyhouse.neema.team.Devices
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.InsightsStressFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import org.junit.After
import org.junit.Before
import org.junit.Test

/**
 * Round 8: the busy shop on screen — Reports over 10,000 conversations and
 * 200 agents, a 2,000-product catalogue, a 200-agent team in 50 roles. Lists
 * are lazy, so each frame composes only what is visible; these prove the
 * pages still read well at that size (counts, long tables, scrolled grids).
 */
class InsightsStressScreenshotTest : AreaShots() {
    // "Last seen 25m ago" must not tick over to 26m when this class runs minutes into the suite.
    @Before fun zone() { ReportsFixtures.pinTimeZone(); ke.co.bethanyhouse.neema.core.util.AppClock.pinTo(ReportsFixtures.NOW) }
    @After fun unzone() = ReportsFixtures.restoreTimeZone()

    private fun busy() = dash(FakeNeema.withFixtures().also { InsightsStressFixtures.install(it) })

    // ── Reports ──────────────────────────────────────────────────────────────
    private fun reports(tab: ReportTab, range: ReportRange = ReportRange.D30, device: app.cash.paparazzi.DeviceConfig = Devices.PHONE, dark: Boolean = false) {
        val d = busy()
        val vm = ReportsViewModel(d, ReportsFixtures.clock).apply { this.tab.value = tab; this.range.value = range }
        shot(device, dark) { ReportsScreen(d, vm) }
    }

    @Test fun reportsOverview10k() = reports(ReportTab.Overview, ReportRange.D90)
    @Test fun reportsOverview10kTabletDark() = reports(ReportTab.Overview, ReportRange.D90, Devices.TABLET, dark = true)
    @Test fun reportsAgents200() = reports(ReportTab.Agents, ReportRange.D90)
    @Test fun reportsAgents200Tablet() = reports(ReportTab.Agents, ReportRange.D90, Devices.TABLET)
    @Test fun reportsConversations10kSmallXlFont() = reports(ReportTab.Conversations, device = Devices.SMALL_XL_FONT)

    // ── Catalog ──────────────────────────────────────────────────────────────
    private fun catalog(device: app.cash.paparazzi.DeviceConfig = Devices.PHONE, dark: Boolean = false, search: String = "") {
        val d = busy()
        val vm = CatalogViewModel(d).apply { this.search.value = search }
        shot(device, dark) { CatalogScreen(d, vm) }
    }

    @Test fun catalog2000() = catalog()
    @Test fun catalog2000TabletDark() = catalog(Devices.TABLET, dark = true)
    @Test fun catalog2000Search() = catalog(search = "product 19")

    // ── Team ─────────────────────────────────────────────────────────────────
    private fun team(preview: TeamPreview = TeamPreview(), device: app.cash.paparazzi.DeviceConfig = Devices.PHONE, dark: Boolean = false) {
        val d = busy()
        shot(device, dark) { CompositionLocalProvider(LocalTeamPreview provides preview) { AgentsScreen(d) } }
    }

    @Test fun team200() = team()
    @Test fun team200ScrolledTablet() = team(TeamPreview(scrollItem = 40), Devices.TABLET)
    @Test fun roles50Dark() = team(TeamPreview(tab = "roles", scrollItem = 20), dark = true)
    @Test fun assignRoleWith50Roles() = team(TeamPreview(dialog = "assign:${InsightsStressFixtures.agentId(1)}"))
}
