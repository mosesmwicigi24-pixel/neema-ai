package ke.co.bethanyhouse.neema.reports

import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.reports.DOWN_TEXT
import ke.co.bethanyhouse.neema.feature.reports.OFFLINE_TEXT
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.feature.reports.TIMEOUT_TEXT
import ke.co.bethanyhouse.neema.feature.reports.exportFailureText
import ke.co.bethanyhouse.neema.feature.reports.friendlyError
import ke.co.bethanyhouse.neema.feature.reports.writeReportCsv
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.NetStressFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.io.File

/**
 * Reports, Analytics and Catalog on a bad phone network: the huge
 * conversation download timing out or dropping halfway, partial failures on
 * the Analytics screen, the catalogue and its audit failing, and a CSV export
 * with nowhere to go.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InsightsNetworkTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private val toasts = mutableListOf<Toast>()

    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun fake() = FakeNeema.withFixtures().also(ReportsFixtures::install)
    private fun dash(f: FakeNeema): DashboardViewModel =
        dashboard(paparazzi.context, f).also { d -> scope.launch { d.toasts.collect { toasts += it } } }
    private fun errors() = toasts.filter { it.type == ToastType.Error }.map { it.message }

    /** Only the Reports download (no `limit`) behaves as [handler]; the inbox pages still answer. */
    private fun FakeNeema.fullList(handler: () -> Pair<Int, String>) {
        val paged = """{"items":[],"next_cursor":null}"""
        on("GET", "/admin/conversations") { r, _ -> if (r.url.queryParameter("limit") == null) handler() else 200 to paged }
    }

    // ── Reports: the ~13 MB download ────────────────────────────────────────

    @Test fun reports_downloadTimesOut_saysSo_withRetry_thenRetryLoads() {
        val f = fake()
        var fail = true
        val real = "[" + ReportsFixtures.conversations.joinToString(",") + "]"
        f.fullList { if (fail) throw java.net.SocketTimeoutException("timeout") else 200 to real }
        val vm = ReportsViewModel(dash(f))
        assertNull("no zeros", vm.allConvs.value)
        assertEquals(
            "The download timed out — this report needs every conversation, a large download. Try again on a stronger connection.",
            vm.loadError.value,
        )
        fail = false
        vm.retry()
        assertEquals(9, vm.allConvs.value?.size)
        assertNull(vm.loadError.value)
    }

    @Test fun reports_downloadCutOffHalfway_saysSo() {
        val f = fake()
        val all = "[" + ReportsFixtures.conversations.joinToString(",") + "]"
        // The connection died mid-body: what arrived is half a JSON array.
        f.fullList { 200 to all.take(all.length / 2) }
        val vm = ReportsViewModel(dash(f))
        assertNull(vm.allConvs.value)
        assertEquals("The download arrived incomplete — try again on a stronger connection.", vm.loadError.value)
    }

    @Test fun reports_captivePortalPage_isNotReadAsZeroConversations() {
        val f = fake()
        f.fullList { 200 to "<html><body>Log in to Safaricom Wi-Fi</body></html>" }
        val vm = ReportsViewModel(dash(f))
        assertNull(vm.allConvs.value)
        assertTrue(vm.loadError.value!!.isNotBlank())
    }

    @Test fun reports_offline_andEveryServerStatus_getPlainWords() {
        for ((setup, want) in listOf<Pair<(FakeNeema) -> Unit, String>>(
            { f: FakeNeema -> f.fullList { throw java.net.ConnectException("Failed to connect to neema.test") } } to OFFLINE_TEXT,
            { f: FakeNeema -> f.fullList { 502 to NetStressFixtures.HTML_502 } } to DOWN_TEXT,
            { f: FakeNeema -> f.fullList { 429 to "" } } to "Too many requests — wait a moment, then try again.",
            { f: FakeNeema -> f.fullList { 403 to """{"detail":"Not enough permissions"}""" } } to "Not enough permissions",
        )) {
            val f = fake().also(setup)
            val vm = ReportsViewModel(dash(f))
            assertEquals(want, vm.loadError.value)
            assertFalse(vm.loadError.value!!.contains("<"))
        }
    }

    @Test fun reports_refreshFailing_keepsTheReport_andToasts() {
        val f = fake()
        val vm = ReportsViewModel(dash(f))
        f.fullList { throw java.net.SocketTimeoutException("timeout") }
        vm.refresh()
        assertEquals(9, vm.allConvs.value?.size)
        assertEquals(listOf("Could not load conversations for this report."), errors())
        assertFalse(vm.refreshing.value)
    }

    @Test fun reports_impatientRefreshes_downloadOnce() {
        val f = fake()
        val vm = ReportsViewModel(dash(f))
        var downloads = 0
        val real = "[" + ReportsFixtures.conversations.joinToString(",") + "]"
        f.fullList {
            downloads++
            vm.refresh(); vm.retry()   // pulls and taps while the first is on the wire
            200 to real
        }
        vm.refresh()
        assertEquals(1, downloads)
    }

    @Test fun reports_leavingMidDownload_noToast() {
        val f = fake()
        val store = ViewModelStore()
        val d = dash(f)
        val vm = ViewModelProvider(store, viewModelFactory { initializer { ReportsViewModel(d) } })[ReportsViewModel::class.java]
        f.fullList { store.clear(); 500 to "Internal Server Error" }
        vm.refresh()
        assertTrue(errors().isEmpty())
    }

    @Test fun reports_theDownloadUsesTheLongClient() {
        // The 30 s ceiling would cut the full list short on a phone link.
        val d = dash(fake())
        assertTrue(d.api.http.uploadClient.callTimeoutMillis >= 10 * 60 * 1000)
    }

    // ── CSV export with nowhere to write or send ─────────────────────────────

    @Test fun export_noStorage_saysWhatToDo() {
        val blocker = File.createTempFile("not-a-dir", ".tmp").apply { deleteOnExit() }
        val err = runCatching { writeReportCsv(File(blocker, "reports"), emptyList(), ReportRange.D30) }.exceptionOrNull()!!
        assertEquals("Couldn't save the report file — free up some storage on this phone and try again.", exportFailureText(err))
    }

    @Test fun export_noShareTarget_saysWhatToInstall() {
        assertEquals(
            "No app on this phone can receive the CSV — install Gmail, Drive or a file manager, then export again.",
            exportFailureText(android.content.ActivityNotFoundException()),
        )
    }

    @Test fun export_writesTheFile() {
        val dir = kotlin.io.path.createTempDirectory("reports").toFile()
        val file = writeReportCsv(File(dir, "reports"), emptyList(), ReportRange.D7)
        assertEquals("neema-report-7d.csv", file.name)
        assertEquals("Date,Customer,Amount,Status\n", file.readText())
    }

    // ── Analytics: partial failures ──────────────────────────────────────────

    @Test fun overview_statsDown_otherPanelsStillLoad_andTheCardsSayTheyAreAnEstimate() {
        val f = fake()
        NetStressFixtures.html(f, "GET", "/admin/stats", 502)
        val vm = OverviewViewModel(dash(f))
        assertNull(vm.stats.value)
        assertEquals(DOWN_TEXT, vm.statsError.value)
        assertTrue("attribution loaded on its own", vm.attrib.value != null)
        assertTrue("the intercept feed loaded on its own", vm.humanRows.value != null)
        assertFalse(vm.statsLoading.value)
        // Retry once the server is back: the notice goes.
        f.on("GET", "/admin/stats", body = ReportsFixtures.stats)
        vm.refresh()
        assertTrue(vm.stats.value != null)
        assertNull(vm.statsError.value)
    }

    @Test fun overview_attributionAndInterceptsDown_statsStillShow() {
        val f = fake()
        NetStressFixtures.timeout(f, "GET", "/admin/attribution")
        f.on("GET", "/admin/conversations") { _, _ -> throw java.net.SocketTimeoutException("timeout") }
        val vm = OverviewViewModel(dash(f))
        assertTrue(vm.stats.value != null)
        assertNull(vm.statsError.value)
        assertNull(vm.attrib.value)
        assertTrue(errors().isEmpty())
    }

    @Test fun overview_pollFailing_keepsTheFigures_quietly() {
        val f = fake()
        val vm = OverviewViewModel(dash(f))
        val before = vm.stats.value
        NetStressFixtures.offline(f, "GET", "/admin/stats")
        vm.life.catchUpNow()
        assertEquals(before, vm.stats.value)
        assertNull(vm.statsError.value)
    }

    @Test fun overview_pullToRefreshFailing_keepsTheFigures_andSaysSo() {
        val f = fake()
        val vm = OverviewViewModel(dash(f))
        NetStressFixtures.offline(f, "GET", "/admin/stats")
        vm.refresh()
        assertTrue(vm.stats.value != null)
        assertEquals(listOf("Couldn't refresh the figures. $OFFLINE_TEXT"), errors())
        assertFalse(vm.refreshing.value)
    }

    @Test fun overview_garbledStats_noCrash() {
        val f = fake()
        f.on("GET", "/admin/stats", body = """{"open_conversations": "lots", "channel_breakdown": 3""")
        val vm = OverviewViewModel(dash(f))
        assertNull(vm.stats.value)
        assertEquals("The server sent an answer the app couldn't read — try again.", vm.statsError.value)
    }

    // ── Catalog ──────────────────────────────────────────────────────────────

    @Test fun catalog_auditFailing_staysHidden_catalogueUnaffected() {
        val f = fake()
        f.on("GET", "/admin/catalog/audit", code = 500, body = "Internal Server Error")
        val d = dash(f)
        val vm = CatalogViewModel(d)
        assertNull(vm.audit.value)
        assertTrue(d.catalog.value.isNotEmpty())
        assertNull(vm.catalogError.value)
        assertTrue(errors().isEmpty())
    }

    @Test fun catalog_auditRefreshFailing_keepsTheBannerAlreadyShown() {
        val f = fake()
        val vm = CatalogViewModel(dash(f))
        val shown = vm.audit.value
        NetStressFixtures.timeout(f, "GET", "/admin/catalog/audit")
        vm.refresh()
        assertEquals(shown, vm.audit.value)
    }

    @Test fun catalog_neverLoaded_screenAsks_andSaysWhyInsteadOfNoItems() {
        val f = fake()
        NetStressFixtures.offline(f, "GET", "/admin/catalog")
        val d = dash(f)
        val vm = CatalogViewModel(d)
        assertTrue(d.catalog.value.isEmpty())
        assertEquals(OFFLINE_TEXT, vm.catalogError.value)
        f.on("GET", "/admin/catalog", body = ReportsFixtures.catalog)
        vm.retry()
        assertTrue(d.catalog.value.isNotEmpty())
        assertNull(vm.catalogError.value)
    }

    @Test fun catalog_pullToRefreshFailing_keepsTheProducts_andSaysSo() {
        val f = fake()
        val d = dash(f)
        val vm = CatalogViewModel(d)
        val n = d.catalog.value.size
        NetStressFixtures.html(f, "GET", "/admin/catalog", 503)
        vm.refresh()
        assertEquals(n, d.catalog.value.size)
        assertEquals(listOf("Couldn't refresh the catalogue. $DOWN_TEXT"), errors())
    }

    // ── The words themselves ─────────────────────────────────────────────────

    @Test fun friendlyError_neverShowsMarkupOrStockText() {
        fun e(code: Int, body: String) = ApiException(code, "GET", "/x", body)
        assertEquals(TIMEOUT_TEXT, friendlyError(e(0, "timed out after 30s")))
        assertEquals(OFFLINE_TEXT, friendlyError(e(0, "Unable to resolve host \"neema.test\"")))
        assertEquals("The connection dropped before the answer arrived — try again.", friendlyError(e(0, "unexpected end of stream")))
        assertEquals("fallback", friendlyError(e(500, """{"detail":"Internal Server Error"}"""), "fallback"))
        assertEquals("That no longer exists — someone else may have removed it.", friendlyError(e(404, """{"detail":"Not Found"}""")))
        assertEquals("That no longer exists — someone else may have removed it.", friendlyError(e(404, """{"detail":"Order not found"}""")))
        assertEquals("You don't have permission to do that.", friendlyError(e(403, "<html>Forbidden</html>")))
        assertEquals("Admin only", friendlyError(e(403, """{"detail":"Admin only"}""")))
        assertEquals("That changed on the server meanwhile — showing the latest.", friendlyError(e(409, "")))
        assertEquals("fallback", friendlyError(e(418, "x".repeat(500)), "fallback"))
    }
}
