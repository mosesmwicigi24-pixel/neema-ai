package ke.co.bethanyhouse.neema.reports

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.reports.EXPORT_INTERRUPTED
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportTab
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.File
import java.time.LocalDate

/**
 * Round 9 (lifecycle) for Reports, Catalog and Analytics: what survives
 * Android restarting the app, a CSV export caught by a rotation, the
 * background or a restart, and the Analytics poll across background trips.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InsightsLifecycleTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private val toasts = mutableListOf<Toast>()

    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun eager() = Dispatchers.setMain(UnconfinedTestDispatcher())
    private fun fake() = FakeNeema.withFixtures().also(ReportsFixtures::install)
    private fun dash(f: FakeNeema = fake()): DashboardViewModel =
        dashboard(paparazzi.context, f).also { d -> scope.launch { d.toasts.collect { toasts += it } } }

    // ── Reports ─────────────────────────────────────────────────────────────

    @Test fun reportChoicesSurviveARestart() {
        eager()
        val d = dash()
        val vm = ReportsViewModel(d, ReportsFixtures.clock).apply {
            tab.value = ReportTab.Agents
            range.value = ReportRange.Custom
            customFrom.value = LocalDate.of(2026, 9, 1)
            customTo.value = LocalDate.of(2026, 9, 20)
        }
        val fresh = ReportsViewModel(d, ReportsFixtures.clock).apply { restoreUi(vm.saveUi()) }
        assertEquals(ReportTab.Agents, fresh.tab.value)
        assertEquals(ReportRange.Custom, fresh.range.value)
        assertEquals(LocalDate.of(2026, 9, 1) to LocalDate.of(2026, 9, 20), fresh.customFrom.value to fresh.customTo.value)
        assertFalse("nothing was being exported", fresh.exportInterrupted.value)
        assertNotNull("the report is built for the restored range", fresh.report.value)
    }

    @Test fun aBrokenSavedStateLeavesTheDefaults() {
        eager()
        val fresh = ReportsViewModel(dash(), ReportsFixtures.clock).apply { restoreUi("""{"tab":"Nope","range":7,"from":"yesterday"}""") }
        assertEquals(ReportTab.Overview, fresh.tab.value)
        assertEquals(ReportRange.D30, fresh.range.value)
        assertNull(fresh.customFrom.value)
    }

    /**
     * The CSV finished while no screen was there to open the share sheet (the
     * phone was turning, or the app was in the background): it waits for the
     * next screen, and a second tap meanwhile doesn't write another.
     */
    @Test fun aFinishedExportWaitsForTheScreenToShareIt() {
        eager()
        val d = dash()
        val vm = ReportsViewModel(d, ReportsFixtures.clock)
        val dir = File(System.getProperty("java.io.tmpdir"), "neema-life-${System.nanoTime()}")
        try {
            vm.exportCsv(dir)
            val ready = vm.readyExport.value!!
            assertFalse(vm.exporting.value)
            vm.exportCsv(dir)
            assertEquals("a second tap waits for the first to be shared", ready, vm.readyExport.value)
            vm.exportShown(ready)
            assertNull(vm.readyExport.value)
            // Shared: the next tap exports again.
            vm.exportCsv(dir)
            assertNotNull(vm.readyExport.value)
        } finally { dir.deleteRecursively() }
    }

    /** Android closed the app mid-export: the agent is told once, on return, to export again. */
    @Test fun anExportCutOffByARestartIsReportedOnce() {
        eager()
        val d = dash()
        val vm = ReportsViewModel(d, ReportsFixtures.clock)
        val dir = File(System.getProperty("java.io.tmpdir"), "neema-life-${System.nanoTime()}")
        try {
            vm.exportCsv(dir)   // written, not yet shared when the process died
            val saved = vm.saveUi()
            val fresh = ReportsViewModel(d, ReportsFixtures.clock).apply { restoreUi(saved) }
            assertTrue(fresh.exportInterrupted.value)
            fresh.interruptionShown()
            fresh.interruptionShown()
            assertEquals(1, toasts.count { it.message == EXPORT_INTERRUPTED && it.type == ToastType.Warning })
            assertFalse(fresh.exportInterrupted.value)
            assertFalse("the new process has nothing to share", fresh.readyExport.value != null)
        } finally { dir.deleteRecursively() }
    }

    // ── Catalog ─────────────────────────────────────────────────────────────

    @Test fun catalogSearchAndCategorySurviveARestart() {
        eager()
        val d = dash()
        val vm = CatalogViewModel(d).apply { search.value = "cassock"; filter.value = "Clergy"; auditOpen.value = true }
        val fresh = CatalogViewModel(d).apply { restoreUi(vm.saveUi()) }
        assertEquals("cassock" to "Clergy", fresh.search.value to fresh.filter.value)
        assertTrue(fresh.auditOpen.value)
    }

    // ── Analytics: the 30 s poll across trips to the background ─────────────

    @Test fun analyticsPollPausesInTheBackgroundAndCatchesUpOnceOnReturn() {
        val sched = TestCoroutineScheduler()
        Dispatchers.setMain(StandardTestDispatcher(sched))
        val f = fake()
        val d = dashboard(paparazzi.context, f)
        val vm = OverviewViewModel(d)
        // The first load, and the one catch-up the dashboard's first orders read asks for.
        sched.advanceTimeBy(1_000); sched.runCurrent()
        fun stats() = f.calls.count { it.method == "GET" && it.path == "/admin/stats" }
        f.calls.clear()

        sched.advanceTimeBy(OverviewViewModel.POLL_MS + 1); sched.runCurrent()
        assertEquals("on screen: one read per 30 s", 1, stats())

        d.container.foreground.value = false
        sched.advanceTimeBy(10 * OverviewViewModel.POLL_MS); sched.runCurrent()
        assertEquals("in the background: nothing", 1, stats())

        d.container.foreground.value = true
        sched.advanceTimeBy(1_000); sched.runCurrent()
        assertEquals("back in front: one catch-up, not the ten missed polls", 2, stats())

        // Off-screen (another view) the poll stops too.
        vm.life.shown.value = false
        sched.advanceTimeBy(5 * OverviewViewModel.POLL_MS); sched.runCurrent()
        assertEquals(2, stats())
        vm.life.shown.value = true
        sched.advanceTimeBy(1_000); sched.runCurrent()
        assertEquals("a return to the screen reads the figures again", 3, stats())
    }
}
