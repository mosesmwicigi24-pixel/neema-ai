package ke.co.bethanyhouse.neema.reports

import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import com.android.resources.ScreenOrientation
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.feature.catalog.CatalogScreen
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewScreen
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportTab
import ke.co.bethanyhouse.neema.feature.reports.ReportsScreen
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.PageSlice
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
 * Round 7's device matrix for Analytics, Reports and Catalog: a 360dp phone at
 * font scale 1.3, a Pixel 5 at 2.0 (accessibility), a ~600dp foldable, tablet
 * portrait and landscape, light and dark — all on the "busy shop" data
 * (seven-digit KES, long Swahili/emoji names, 40+ orders) that squeezes
 * stat cards, charts and product cards hardest.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AnalyticsDeviceMatrixTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_5)

    @Before fun setUp() { ReportsFixtures.pinTimeZone(); Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain(); ReportsFixtures.restoreTimeZone() }

    private enum class Screen { Overview, Reports, ReportsOrders, Catalog }

    private fun shot(device: DeviceConfig, screen: Screen, dark: Boolean = false, page: Int = 0, step: Int = 780) {
        paparazzi.unsafeUpdateConfig(device)
        val f = FakeNeema.withFixtures().also(ReportsFixtures::installBig)
        val dash = dashboard(paparazzi.context, f)
        val body: @Composable (DashboardViewModel) -> Unit = when (screen) {
            Screen.Overview -> { d -> OverviewScreen(d, OverviewViewModel(d), ReportsFixtures.clock) }
            Screen.Reports -> { d -> ReportsScreen(d, ReportsViewModel(d, ReportsFixtures.clock).apply { range.value = ReportRange.D30 }) }
            Screen.ReportsOrders -> { d -> ReportsScreen(d, ReportsViewModel(d, ReportsFixtures.clock).apply { tab.value = ReportTab.Orders }) }
            Screen.Catalog -> { d -> CatalogScreen(d, CatalogViewModel(d)) }
        }
        paparazzi.snapshot { AppFrame(dark) { PageSlice(page, totalHeight = 6000.dp, step = step.dp) { body(dash) } } }
    }

    // ── Analytics (Overview) ──────────────────────────────────────────────
    @Test fun overviewSmallFont13() = shot(SMALL_13, Screen.Overview)
    @Test fun overviewSmallFont13Page2() = shot(SMALL_13, Screen.Overview, page = 1, step = 560)
    @Test fun overviewSmallDark() = shot(SMALL, Screen.Overview, dark = true)
    @Test fun overviewFont20() = shot(PIXEL5_20, Screen.Overview)
    @Test fun overviewFont20Page2() = shot(PIXEL5_20, Screen.Overview, page = 1)
    @Test fun overviewFont20Page3() = shot(PIXEL5_20, Screen.Overview, page = 2)
    @Test fun overviewFont20Page4() = shot(PIXEL5_20, Screen.Overview, page = 3)
    @Test fun overviewFont20Page5() = shot(PIXEL5_20, Screen.Overview, page = 4)
    @Test fun overviewFont20Page6() = shot(PIXEL5_20, Screen.Overview, page = 5)
    @Test fun overviewFold() = shot(FOLD, Screen.Overview)
    @Test fun overviewTabletPortrait() = shot(TABLET_PORTRAIT, Screen.Overview)
    @Test fun overviewTabletLandscapeDark() = shot(TABLET_LANDSCAPE, Screen.Overview, dark = true)
    @Test fun overviewTabletFont20() = shot(TABLET_LANDSCAPE_20, Screen.Overview)

    // ── Reports ───────────────────────────────────────────────────────────
    @Test fun reportsSmallFont13() = shot(SMALL_13, Screen.Reports)
    @Test fun reportsSmallDark() = shot(SMALL, Screen.Reports, dark = true)
    @Test fun reportsFont20() = shot(PIXEL5_20, Screen.Reports)
    @Test fun reportsFont20Page2() = shot(PIXEL5_20, Screen.Reports, page = 1)
    @Test fun reportsOrdersFont20() = shot(PIXEL5_20, Screen.ReportsOrders)
    @Test fun reportsFold() = shot(FOLD, Screen.Reports)
    @Test fun reportsTabletPortrait() = shot(TABLET_PORTRAIT, Screen.Reports)
    @Test fun reportsTabletLandscapeDark() = shot(TABLET_LANDSCAPE, Screen.Reports, dark = true)
    @Test fun reportsTabletOrdersFont20() = shot(TABLET_LANDSCAPE_20, Screen.ReportsOrders)

    // ── Catalog ───────────────────────────────────────────────────────────
    @Test fun catalogSmallFont13() = shot(SMALL_13, Screen.Catalog)
    @Test fun catalogSmallFont13Page2() = shot(SMALL_13, Screen.Catalog, page = 1, step = 560)
    @Test fun catalogSmallDark() = shot(SMALL, Screen.Catalog, dark = true, page = 1, step = 560)
    @Test fun catalogFont20() = shot(PIXEL5_20, Screen.Catalog)
    @Test fun catalogFont20Page2() = shot(PIXEL5_20, Screen.Catalog, page = 1)
    @Test fun catalogFont20Page3() = shot(PIXEL5_20, Screen.Catalog, page = 2)
    @Test fun catalogFold() = shot(FOLD, Screen.Catalog)
    @Test fun catalogTabletPortrait() = shot(TABLET_PORTRAIT, Screen.Catalog)
    @Test fun catalogTabletLandscapeDark() = shot(TABLET_LANDSCAPE, Screen.Catalog, dark = true)

    private companion object {
        /** A 360dp-wide phone. */
        val SMALL = DeviceConfig.NEXUS_5
        val SMALL_13 = DeviceConfig.NEXUS_5.copy(fontScale = 1.3f)
        val PIXEL5_20 = DeviceConfig.PIXEL_5.copy(fontScale = 2.0f)
        /** An unfolded book-style foldable: ~600dp wide at the Pixel 5's density. */
        val FOLD = DeviceConfig.PIXEL_5.copy(screenWidth = 1650, screenHeight = 2200)
        val TABLET_LANDSCAPE = DeviceConfig.PIXEL_C
        val TABLET_LANDSCAPE_20 = DeviceConfig.PIXEL_C.copy(fontScale = 2.0f)
        val TABLET_PORTRAIT = DeviceConfig.PIXEL_C.copy(
            screenWidth = DeviceConfig.PIXEL_C.screenHeight, screenHeight = DeviceConfig.PIXEL_C.screenWidth,
            orientation = ScreenOrientation.PORTRAIT,
        )
    }
}
