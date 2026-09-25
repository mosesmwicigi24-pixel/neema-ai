package ke.co.bethanyhouse.neema.reports

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
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
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The three screens' ViewModels against the fake backend: which endpoints
 * they call with which parameters, and what each does when a call fails.
 * (Paparazzi supplies a real Android Context; nothing is rendered.)
 */
@OptIn(ExperimentalCoroutinesApi::class)
class AreaViewModelTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private val toasts = mutableListOf<Toast>()

    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun fake(empty: Boolean = false) = FakeNeema.withFixtures().also {
        if (empty) ReportsFixtures.installEmpty(it) else ReportsFixtures.install(it)
    }

    private fun dash(f: FakeNeema): DashboardViewModel =
        dashboard(paparazzi.context, f).also { d -> scope.launch { d.toasts.collect { toasts += it } } }

    private fun FakeNeema.gets(path: String) = calls.filter { it.method == "GET" && it.path == path }

    // ── Reports ─────────────────────────────────────────────────────────────

    @Test fun reports_fetchesEveryConversation_unpaged() {
        val f = fake()
        val vm = ReportsViewModel(dash(f))
        assertEquals(9, vm.allConvs.value?.size)
        // No limit/cursor/tab: the legacy full array the API keeps for Reports.
        assertEquals(listOf<String?>(null), f.gets("/admin/conversations").map { it.query })
        assertTrue(toasts.none { it.type == ToastType.Error })
    }

    @Test fun reports_loadFailure_showsEmptyNotLoading_andToasts() {
        val f = fake()
        f.on("GET", "/admin/conversations", code = 500, body = """{"detail":"boom"}""")
        val vm = ReportsViewModel(dash(f))
        assertEquals(emptyList<Any>(), vm.allConvs.value)
        assertEquals("Could not load conversations for this report.", toasts.single { it.type == ToastType.Error }.message)
    }

    @Test fun reports_refreshFailure_keepsTheRowsAlreadyShown() {
        val f = fake()
        val vm = ReportsViewModel(dash(f))
        f.on("GET", "/admin/conversations", code = 503, body = "{}")
        vm.refresh()
        assertEquals(9, vm.allConvs.value?.size)
        assertFalse(vm.refreshing.value)
        assertEquals(1, toasts.count { it.type == ToastType.Error })
        // Refresh also re-reads the orders and agents the report is built from.
        assertTrue(f.gets("/admin/orders").size >= 2)
        assertTrue(f.gets("/admin/agents").size >= 2)
    }

    // ── Analytics ───────────────────────────────────────────────────────────

    @Test fun overview_loadsStatsAttributionAndHumanThreads() {
        val f = fake()
        val vm = OverviewViewModel(dash(f))
        assertEquals(128, vm.stats.value?.openConversations)
        assertFalse(vm.statsLoading.value)
        assertEquals(3, vm.attrib.value?.sources?.size)
        assertEquals(listOf("r1", "r5", "r6"), vm.humanRows.value?.map { it.id })
        // The human tab, 10 rows — exactly the web's conversationsApi.page({ tab: "human", limit: 10 }).
        val pages = f.gets("/admin/conversations").map { it.query }
        assertEquals(listOf<String?>("limit=10&tab=human"), pages)
        assertEquals(emptyList<Any>(), vm.fallbackConvs.value)
    }

    @Test fun overview_statsFailure_fallsBackToTheInboxFirstPage() {
        val f = fake()
        f.on("GET", "/admin/stats", code = 500, body = "{}")
        val vm = OverviewViewModel(dash(f))
        assertNull(vm.stats.value)
        assertFalse(vm.statsLoading.value) // skeletons give way to the fallback figures
        assertEquals(9, vm.fallbackConvs.value.size)
        assertTrue(f.gets("/admin/conversations").any { it.query == "limit=50" })
        // Attribution and intercepts still load on their own.
        assertNotNull(vm.attrib.value)
        assertEquals(3, vm.humanRows.value?.size)
    }

    @Test fun overview_attributionFailure_hidesThePanel() {
        val f = fake()
        f.on("GET", "/admin/attribution", code = 500, body = "{}")
        val vm = OverviewViewModel(dash(f))
        assertNull(vm.attrib.value)
        assertNotNull(vm.stats.value)
    }

    @Test fun overview_refreshFailure_keepsTheFiguresOnScreen() {
        val f = fake()
        val vm = OverviewViewModel(dash(f))
        f.on("GET", "/admin/stats", code = 500, body = "{}")
        f.on("GET", "/admin/attribution", code = 500, body = "{}")
        vm.refresh()
        assertEquals(128, vm.stats.value?.openConversations)
        assertNotNull(vm.attrib.value)
        assertFalse(vm.refreshing.value)
        assertFalse(f.gets("/admin/conversations").any { it.query == "limit=50" })
    }

    // ── Catalog ─────────────────────────────────────────────────────────────

    @Test fun catalog_loadsTheAudit_andNeverWrites() {
        val f = fake()
        val d = dash(f)
        val vm = CatalogViewModel(d)
        assertEquals(3, vm.audit.value?.currencyGaps?.size)
        assertEquals(6, d.catalog.value.size)
        assertEquals(listOf<String?>(null), f.gets("/admin/catalog").map { it.query })
        // Read-only, like the web: the hub is the single source of truth.
        assertTrue(f.calls.none { it.method != "GET" && it.path.startsWith("/admin/catalog") })
    }

    @Test fun catalog_auditFailure_staysHidden_silently() {
        val f = fake()
        f.on("GET", "/admin/catalog/audit", code = 500, body = "{}")
        val vm = CatalogViewModel(dash(f))
        assertNull(vm.audit.value)
        assertTrue(toasts.isEmpty())
    }
}
