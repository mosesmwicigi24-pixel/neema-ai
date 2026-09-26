package ke.co.bethanyhouse.neema.reports

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.catalog.CatalogScreen
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportTab
import ke.co.bethanyhouse.neema.feature.reports.ReportsScreen
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.team.Store
import ke.co.bethanyhouse.neema.team.beforeAndRestored
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.time.LocalDate

/**
 * Round 9: Reports and Catalog as the agent left them, then after Android
 * restarted the app (fresh ViewModels, only saved state to go on) — and,
 * for Reports, after a rotation (same ViewModel: its newer state wins over
 * the saved copy).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class RestoredInsightsScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    @Before fun setUp() { ReportsFixtures.pinTimeZone(); Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun tearDown() { Dispatchers.resetMain(); ReportsFixtures.restoreTimeZone() }

    private fun dash() = dashboard(paparazzi.context, FakeNeema.withFixtures().also(ReportsFixtures::install))

    /** Custom range + the Agents tab, then a restart: the fresh ViewModel builds the same report. */
    @Test fun reportAfterRestart() {
        val d = dash()
        val before = Store()
        before.put(ReportsViewModel(d, ReportsFixtures.clock)).apply {
            tab.value = ReportTab.Agents
            range.value = ReportRange.Custom
            customFrom.value = LocalDate.of(2026, 9, 20)
            customTo.value = LocalDate.of(2026, 9, 22)
        }
        val after = Store()
        val fresh = after.put(ReportsViewModel(d, ReportsFixtures.clock))
        paparazzi.beforeAndRestored(before, after) { ReportsScreen(d) }
        assertEquals(ReportTab.Agents, fresh.tab.value)
        assertEquals(ReportRange.Custom, fresh.range.value)
    }

    /** A rotation keeps the ViewModel: a tab picked after the state was saved is not rolled back to the saved one. */
    @Test fun reportAfterRotation() {
        val d = dash()
        val store = Store()
        val vm = store.put(ReportsViewModel(d, ReportsFixtures.clock)).apply { tab.value = ReportTab.Agents }
        paparazzi.beforeAndRestored(store, store, between = { vm.tab.value = ReportTab.Orders }) { ReportsScreen(d) }
        assertEquals(ReportTab.Orders, vm.tab.value)
    }

    /** A search, a category and an open product, then a restart: all three come back. */
    @Test fun catalogAfterRestart() {
        val d = dash().also { it.refetchCatalog() }
        val item = d.catalog.value.first { it.category.isNotEmpty() }
        val before = Store()
        before.put(CatalogViewModel(d)).apply { filter.value = item.category; search.value = item.name.take(4) }
        var initial: ke.co.bethanyhouse.neema.core.model.CatalogItem? = item
        val r = paparazzi.beforeAndRestored(before, Store(), between = { initial = null }) {
            CatalogScreen(d, initialDetail = initial)
        }
        // The product sheet is open again (its slide-up runs on frames this
        // render doesn't draw; CatalogScreenshotTest shows the sheet itself).
        assertEquals(item.id, r.restoredValue("catalog.product"))
    }
}
