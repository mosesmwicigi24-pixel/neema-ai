package ke.co.bethanyhouse.neema.team

import androidx.compose.runtime.CompositionLocalProvider
import app.cash.paparazzi.DeviceConfig
import ke.co.bethanyhouse.neema.feature.agents.AgentsScreen
import ke.co.bethanyhouse.neema.feature.agents.LocalTeamPreview
import ke.co.bethanyhouse.neema.feature.agents.TeamPreview
import ke.co.bethanyhouse.neema.feature.catalog.CatalogScreen
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewScreen
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.profile.ProfileScreen
import ke.co.bethanyhouse.neema.feature.reports.ReportsScreen
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.feature.settings.SettingsScreen
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.NetStressFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.After
import org.junit.Before
import org.junit.Test

/**
 * What each screen in the area shows when its load fails on a phone network:
 * a reason in plain words and a way to try again — never a blank, a spinner
 * that never ends, or zeros / "nothing here" that read as the truth.
 */
class NetworkErrorScreenshotTest : AreaShots() {
    @Before fun pin() = ReportsFixtures.pinTimeZone()
    @After fun unpin() = ReportsFixtures.restoreTimeZone()

    private fun reportsFake() = FakeNeema.withFixtures().also(ReportsFixtures::install)
    private fun teamFake() = FakeNeema.withFixtures().also(TeamFixtures::install)

    // ── Reports: the full download failed ───────────────────────────────────

    private fun reports(dark: Boolean = false, device: DeviceConfig = Devices.PHONE) {
        val f = reportsFake()
        f.on("GET", "/admin/conversations") { r, _ ->
            if (r.url.queryParameter("limit") == null) throw java.net.SocketTimeoutException("timeout") else 200 to """{"items":[],"next_cursor":null}"""
        }
        val d = dashboard(paparazzi.context, f)
        val vm = ReportsViewModel(d, ReportsFixtures.clock)
        shot(device, dark) { ReportsScreen(d, vm) }
    }

    @Test fun reportsTimedOut() = reports()
    @Test fun reportsTimedOutDark() = reports(dark = true)
    @Test fun reportsTimedOutTablet() = reports(device = Devices.TABLET)

    // ── Analytics: the server's counts failed, the rest loaded ───────────────

    private fun overview(dark: Boolean = false, device: DeviceConfig = Devices.PHONE) {
        val f = reportsFake()
        NetStressFixtures.html(f, "GET", "/admin/stats", 502)
        val d = dashboard(paparazzi.context, f)
        val vm = OverviewViewModel(d)
        shot(device, dark) { OverviewScreen(d, vm, ReportsFixtures.clock) }
    }

    @Test fun overviewStatsDown() = overview()
    @Test fun overviewStatsDownDark() = overview(dark = true)
    @Test fun overviewStatsDownTablet() = overview(device = Devices.TABLET)

    // ── Catalog: never loaded ────────────────────────────────────────────────

    private fun catalog(dark: Boolean = false) {
        val f = reportsFake()
        NetStressFixtures.offline(f, "GET", "/admin/catalog")
        val d = dashboard(paparazzi.context, f)
        val vm = CatalogViewModel(d)
        shot(dark = dark) { CatalogScreen(d, vm) }
    }

    @Test fun catalogOffline() = catalog()
    @Test fun catalogOfflineDark() = catalog(dark = true)

    // ── Team: nothing loaded ─────────────────────────────────────────────────

    private fun team(preview: TeamPreview, dark: Boolean = false) {
        val f = teamFake()
        NetStressFixtures.offline(f, "GET", "/admin/agents")
        NetStressFixtures.offline(f, "GET", "/admin/roles")
        val d = dashboard(paparazzi.context, f)
        shot(dark = dark) { CompositionLocalProvider(LocalTeamPreview provides preview) { AgentsScreen(d) } }
    }

    @Test fun teamOffline() = team(TeamPreview())
    @Test fun teamOfflineDark() = team(TeamPreview(), dark = true)
    @Test fun rolesOffline() = team(TeamPreview(tab = "roles"))

    // ── Profile: signed in offline ───────────────────────────────────────────

    private fun profile(dark: Boolean = false) {
        val f = teamFake()
        NetStressFixtures.offline(f, "GET", "/admin/me")
        NetStressFixtures.offline(f, "GET", "/admin/agents")
        val d = dashboard(paparazzi.context, f)
        shot(dark = dark) { ProfileScreen(d) }
    }

    @Test fun profileOffline() = profile()
    @Test fun profileOfflineDark() = profile(dark = true)

    // ── Settings: every live card failed ─────────────────────────────────────

    private fun settings(dark: Boolean = false, device: DeviceConfig = Devices.tallPhone(3200)) {
        val f = FakeNeema.withFixtures().also { TeamFixtures.settings(it) }
        NetStressFixtures.offline(f, "GET", "/admin/settings/directives")
        NetStressFixtures.timeout(f, "GET", "/admin/settings/translation")
        NetStressFixtures.html(f, "GET", "/admin/settings/offer", 502)
        NetStressFixtures.offline(f, "GET", "/admin/settings/pipeline-stages")
        val d = dash(f)
        shot(device, dark) { SettingsScreen(d) }
    }

    @Test fun settingsCardsFailed() = settings()
    @Test fun settingsCardsFailedDark() = settings(dark = true)
    @Test fun settingsCardsFailedTablet() = settings(device = Devices.TABLET)
}
