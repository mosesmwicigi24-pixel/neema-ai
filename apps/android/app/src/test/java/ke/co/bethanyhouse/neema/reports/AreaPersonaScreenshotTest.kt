package ke.co.bethanyhouse.neema.reports

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.catalog.CatalogScreen
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewScreen
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.reports.ReportsScreen
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.AreaPersonaFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.AreaPersonaFixtures.Persona
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The area's screens for the contrasting personas: each must look exactly
 * like the admin's (the web gates nothing inside these views), and a
 * server 403 reads in plain words.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AreaPersonaScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    @Before fun setUp() { ReportsFixtures.pinTimeZone(); Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain(); ReportsFixtures.restoreTimeZone() }

    private fun fake(p: Persona, configure: (FakeNeema) -> Unit = {}) = FakeNeema.withFixtures().also {
        ReportsFixtures.install(it); AreaPersonaFixtures.install(it, p); configure(it)
    }

    /** Reports for the override persona: view_reports without export_reports — Export CSV still there. */
    @Test fun reportsOverrideNoExportPermission() {
        val p = Persona.Override
        val dash = dashboard(paparazzi.context, fake(p), role = p.role, superuser = p.superuser)
        paparazzi.snapshot { AppFrame { ReportsScreen(dash, ReportsViewModel(dash), ReportsFixtures.clock) } }
    }

    /** A 403 on the full list: the web's words plus why, with Retry. */
    @Test fun reportsForbidden() {
        val p = Persona.Admin
        val f = fake(p) { it.on("GET", "/admin/conversations", code = 403, body = """{"detail":"Forbidden"}""") }
        val dash = dashboard(paparazzi.context, f, role = p.role, superuser = p.superuser)
        paparazzi.snapshot { AppFrame { ReportsScreen(dash, ReportsViewModel(dash), ReportsFixtures.clock) } }
    }

    /** Analytics for a legacy readonly agent (view_analytics by fallback): every section, attribution included. */
    @Test fun overviewLegacyReadonly() {
        val p = Persona.LegacyReadonly
        val dash = dashboard(paparazzi.context, fake(p), role = p.role, superuser = p.superuser)
        paparazzi.snapshot { AppFrame { OverviewScreen(dash, OverviewViewModel(dash), ReportsFixtures.clock) } }
    }

    /** Catalog for an agent WITH manage_catalog (override): still read-only, audit banner shown. */
    @Test fun catalogManageCatalogStillReadOnlyDark() {
        val p = Persona.Override
        val dash = dashboard(paparazzi.context, fake(p), role = p.role, superuser = p.superuser)
        paparazzi.snapshot { AppFrame(dark = true) { CatalogScreen(dash, CatalogViewModel(dash)) } }
    }

    /** Catalog for a legacy agent (view_catalog by fallback) on a tablet. */
    @Test fun catalogLegacyAgentTablet() {
        paparazzi.unsafeUpdateConfig(DeviceConfig.PIXEL_C)
        val p = Persona.LegacyAgent
        val dash = dashboard(paparazzi.context, fake(p), role = p.role, superuser = p.superuser)
        paparazzi.snapshot { AppFrame { CatalogScreen(dash, CatalogViewModel(dash)) } }
    }
}
