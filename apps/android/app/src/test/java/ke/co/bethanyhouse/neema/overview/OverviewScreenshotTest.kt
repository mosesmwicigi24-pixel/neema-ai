package ke.co.bethanyhouse.neema.overview

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.overview.OverviewScreen
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.PageSlice
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** The Analytics dashboard: populated, stats-failed fallback, empty, loading; phone and tablet; light and dark. */
@OptIn(ExperimentalCoroutinesApi::class)
class OverviewScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    @Before fun setUp() { ReportsFixtures.pinTimeZone(); Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain(); ReportsFixtures.restoreTimeZone() }

    private fun shot(dark: Boolean = false, page: Int = 0, configure: (FakeNeema) -> Unit = {}) {
        val f = FakeNeema.withFixtures().also(ReportsFixtures::install).also(configure)
        val dash = dashboard(paparazzi.context, f)
        val vm = OverviewViewModel(dash)
        paparazzi.snapshot { AppFrame(dark) { PageSlice(page) { OverviewScreen(dash, vm, ReportsFixtures.clock) } } }
    }

    @Test fun phone() = shot()
    @Test fun phonePage2() = shot(page = 1)
    @Test fun phonePage3() = shot(page = 2)
    @Test fun phoneDark() = shot(dark = true)
    @Test fun phoneDarkPage2() = shot(dark = true, page = 1)
    @Test fun phoneDarkPage3() = shot(dark = true, page = 2)
    @Test fun statsFailed() = shot { it.on("GET", "/admin/stats", code = 500, body = "{}") }
    @Test fun empty() = shot { ReportsFixtures.installEmpty(it) }
    @Test fun emptyPage2() = shot(page = 1) { ReportsFixtures.installEmpty(it) }
    @Test fun emptyDark() = shot(dark = true) { ReportsFixtures.installEmpty(it) }

    @Test fun loading() {
        Dispatchers.setMain(StandardTestDispatcher())
        val dash = dashboard(paparazzi.context, FakeNeema.withFixtures().also(ReportsFixtures::install))
        val vm = OverviewViewModel(dash)
        paparazzi.snapshot { AppFrame { OverviewScreen(dash, vm, ReportsFixtures.clock) } }
    }

    @Test fun tablet() { paparazzi.unsafeUpdateConfig(TABLET); shot() }
    @Test fun tabletPage2() { paparazzi.unsafeUpdateConfig(TABLET); shot(page = 1) }
    @Test fun tabletDark() { paparazzi.unsafeUpdateConfig(TABLET); shot(dark = true) }

    private companion object {
        val TABLET = DeviceConfig.PIXEL_C
    }
}
