package ke.co.bethanyhouse.neema.reports

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.catalog.CatalogIndex
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.catalog.filterCatalog
import ke.co.bethanyhouse.neema.feature.catalog.gridRows
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.overview.activityFeed
import ke.co.bethanyhouse.neema.feature.overview.sevenDayRevenue
import ke.co.bethanyhouse.neema.feature.overview.topProducts
import ke.co.bethanyhouse.neema.feature.reports.Report
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportTab
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.feature.reports.ScreenLife
import ke.co.bethanyhouse.neema.feature.reports.buildReport
import ke.co.bethanyhouse.neema.feature.reports.reportCsv
import ke.co.bethanyhouse.neema.feature.reports.reportAt
import ke.co.bethanyhouse.neema.feature.reports.tableFor
import ke.co.bethanyhouse.neema.feature.reports.uniqueKeys
import ke.co.bethanyhouse.neema.feature.reports.writeReportCsv
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InsightsStressFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.TextStyle
import java.util.Locale

/**
 * Round 8 — Reports, Analytics, Catalog and Team under a real shop's load:
 * 10,000 conversations, 1,000 orders, 200 agents in 50 roles, a 2,000-product
 * catalogue and 200 socket frames in a burst. Asserts the figures stay exact
 * (against a straightforward re-implementation of the web's maths), that the
 * heavy work is bounded in time and in requests, and that nothing stacks.
 * Time bounds are generous (JVM, cold-ish) so they only catch an O(n²) slip.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InsightsStressTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6) // a layoutlib Context only

    private val scheduler = TestCoroutineScheduler()

    @Before fun setUp() { ReportsFixtures.pinTimeZone(); Dispatchers.setMain(UnconfinedTestDispatcher(scheduler)) }
    @After fun tearDown() { Dispatchers.resetMain(); ReportsFixtures.restoreTimeZone() }

    private val NOW = ReportsFixtures.NOW.toEpochMilli()
    private val NAIROBI = ReportsFixtures.NAIROBI

    private val convs = InsightsStressFixtures.conversations()
    private val orders = InsightsStressFixtures.orders()
    private val agents = InsightsStressFixtures.agents()

    private fun ms(block: () -> Unit): Long { val t = System.nanoTime(); block(); return (System.nanoTime() - t) / 1_000_000 }

    // ── The web's maths, written the obvious way (the pre-round-8 algorithm) ──

    private fun naive(
        all: List<Conversation>, orders: List<Order>, agents: List<Agent>, range: ReportRange,
        cf: LocalDate?, ct: LocalDate?, now: Long, zone: ZoneId,
    ): Report {
        val day = 86_400_000L
        val (from, to) = when {
            range == ReportRange.D7 -> now - 7 * day to now
            range == ReportRange.D90 -> now - 90 * day to now
            range == ReportRange.Custom && cf != null && ct != null ->
                cf.atStartOfDay(zone).toInstant().toEpochMilli() to ct.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli() - 1
            else -> now - 30 * day to now
        }
        fun inRange(iso: String?) = Fmt.millis(iso)?.let { it in from..to } ?: false
        fun localDay(iso: String?) = Fmt.millis(iso)?.let { Instant.ofEpochMilli(it).atZone(zone).toLocalDate() }
        val c = all.filter { inRange(it.reportAt()) }
        val o = orders.filter { inRange(it.createdAt) }
        val n = minOf(when (range) { ReportRange.D7 -> 7; ReportRange.D30 -> 14; else -> 30 }, 14)
        val toDay = Instant.ofEpochMilli(to).atZone(zone).toLocalDate()
        val days = (0 until n).map { toDay.minusDays((n - 1 - it).toLong()) }
        val cd = c.groupingBy { localDay(it.reportAt()) }.eachCount()
        val od = o.groupBy { localDay(it.createdAt) }
        fun wk(d: LocalDate) = d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH)
        val stats = agents.map { a ->
            val mine = c.filter { it.assignedAgentId == a.id }
            val wa = mine.mapNotNull { it.waId }.toSet()
            ke.co.bethanyhouse.neema.feature.reports.AgentStat(a, mine.size, o.filter { it.waId.isNotEmpty() && it.waId in wa }.sumOf { it.total })
        }.sortedByDescending { it.handled }
        return Report(
            c, o, o.filter { it.status != "cancelled" }.sumOf { it.total },
            c.count { it.interceptMode == "human" }, c.count { it.interceptMode == "ai" },
            o.count { it.status == "pending" }, o.count { it.status == "confirmed" },
            o.count { it.status == "delivered" }, o.count { it.status == "cancelled" },
            days.map { ke.co.bethanyhouse.neema.feature.reports.BarPoint(wk(it), (cd[it] ?: 0).toDouble()) },
            days.map { d -> ke.co.bethanyhouse.neema.feature.reports.BarPoint(wk(d), od[d].orEmpty().sumOf { it.total }) },
            stats,
        )
    }

    private fun assertSame(expected: Report, actual: Report) {
        assertEquals(expected.convs.map { it.id }, actual.convs.map { it.id })
        assertEquals(expected.orders.map { it.id }, actual.orders.map { it.id })
        assertEquals(expected.revenue, actual.revenue, 0.0)
        assertEquals(
            listOf(expected.humanConvs, expected.aiConvs, expected.pending, expected.confirmed, expected.delivered, expected.cancelled),
            listOf(actual.humanConvs, actual.aiConvs, actual.pending, actual.confirmed, actual.delivered, actual.cancelled),
        )
        assertEquals(expected.convByDay, actual.convByDay)
        assertEquals(expected.orderByDay, actual.orderByDay)
        assertEquals(expected.agentStats.map { Triple(it.agent.id, it.handled, it.revenue) }, actual.agentStats.map { Triple(it.agent.id, it.handled, it.revenue) })
    }

    // ── Reports: aggregation ────────────────────────────────────────────────

    @Test
    fun tenThousandConversationsReportExactlyWhatTheWebWouldForEveryRange() {
        val cases = listOf(
            Triple(ReportRange.D7, null, null), Triple(ReportRange.D30, null, null), Triple(ReportRange.D90, null, null),
            Triple(ReportRange.Custom, LocalDate.of(2026, 6, 1), LocalDate.of(2026, 9, 25)),
            Triple(ReportRange.Custom, LocalDate.of(2026, 9, 25), LocalDate.of(2026, 9, 25)),
        )
        for ((range, f, t) in cases) {
            val want = naive(convs, orders, agents, range, f, t, NOW, NAIROBI)
            val got = buildReport(convs, orders, agents, range, f, t, NOW, NAIROBI)
            assertSame(want, got)
        }
        // The load is real: most agents hold threads, the 90-day report spans thousands.
        val r90 = buildReport(convs, orders, agents, ReportRange.D90, null, null, NOW, NAIROBI)
        assertTrue(r90.convs.size > 7_000)
        assertTrue(r90.agentStats.count { it.handled > 0 } > 150)
    }

    @Test
    fun buildingTheReportForTenThousandRowsIsFast() {
        repeat(2) { buildReport(convs, orders, agents, ReportRange.D90, null, null, NOW, NAIROBI) } // warm up
        val t = ms { buildReport(convs, orders, agents, ReportRange.D90, null, null, NOW, NAIROBI) }
        // The pre-round-8 per-agent scan (200 agents x 10k threads x 1k orders) plus
        // re-parsing every date for every figure took seconds; now it is a few passes.
        assertTrue("report over 10k conversations took ${t}ms", t < 500)
    }

    // ── Reports: the ViewModel ──────────────────────────────────────────────

    private fun stressDash(fake: FakeNeema = FakeNeema.withFixtures().also { InsightsStressFixtures.install(it) }): DashboardViewModel =
        dashboard(paparazzi.context, fake)

    @Test
    fun theViewModelDownloadsTheFullListOnceAndBuildsTheReportOffTheScreen() {
        val fake = FakeNeema.withFixtures().also { InsightsStressFixtures.install(it) }
        val dash = stressDash(fake)
        dash.refetchAgents()
        val vm = ReportsViewModel(dash, ReportsFixtures.clock)
        assertEquals("one full-list download", 1, fake.callsTo("GET", "/admin/conversations").count { it.query == null })
        val r = vm.report.value
        assertNotNull(r); r!!
        assertEquals(10_000, vm.allConvs.value!!.size)
        assertEquals(1_000, dash.orders.value.size)
        assertEquals(200, dash.agents.value.size)
        // The same numbers the pure function gives for the loaded lists.
        assertSame(buildReport(vm.allConvs.value!!, dash.orders.value, dash.agents.value, ReportRange.D30, null, null, NOW, NAIROBI), r)

        // A range change rebuilds from the parsed rows — no second download.
        vm.range.value = ReportRange.D90
        assertTrue(vm.report.value!!.convs.size > r.convs.size)
        vm.range.value = ReportRange.D7
        assertTrue(vm.report.value!!.convs.size < r.convs.size)
        assertEquals(1, fake.callsTo("GET", "/admin/conversations").count { it.query == null })
    }

    @Test
    fun theAgentsTableKeepsEveryAgentWithUniqueKeysAndIndexedNames() {
        val r = buildReport(convs, orders, agents, ReportRange.D90, null, null, NOW, NAIROBI)
        val agentsTable = tableFor(ReportTab.Agents, r, agents, NOW)!!
        assertEquals(200, agentsTable.rows.size)
        assertEquals(200, agentsTable.keys.toSet().size)
        val convTable = tableFor(ReportTab.Conversations, r, agents, NOW)!!
        assertEquals("the web's first 50", 50, convTable.rows.size)
        assertEquals(50, convTable.keys.toSet().size)
        assertEquals(20, tableFor(ReportTab.Orders, r, agents, NOW)!!.rows.size)
        // Building all three tables for a 10k report is cheap enough to do per tab switch.
        val t = ms { repeat(20) { ReportTab.entries.forEach { tab -> tableFor(tab, r, agents, NOW) } } }
        assertTrue("tables took ${t}ms", t < 500)
    }

    @Test
    fun duplicateIdsNeverCollideAsLazyKeys() {
        assertEquals(listOf("a", "b", "a#2", "c", "b#4"), uniqueKeys(listOf("a", "b", "a", "c", "b")))
        val many = uniqueKeys(List(5_000) { "same" })
        assertEquals(5_000, many.toSet().size)
    }

    // ── Reports: CSV export ─────────────────────────────────────────────────

    @Test
    fun tenThousandOrdersExportStreamedToAFileMatchingTheCsv() {
        val big = InsightsStressFixtures.orders(10_000)
        val dir = File(System.getProperty("java.io.tmpdir"), "neema-stress-${System.nanoTime()}")
        try {
            var file: File? = null
            val t = ms { file = writeReportCsv(dir, big, ReportRange.D90) }
            assertTrue("export of 10k rows took ${t}ms", t < 3_000)
            val lines = file!!.readLines()
            assertEquals(10_001, lines.size)
            assertEquals("Date,Customer,Amount,Status", lines.first())
            assertEquals(reportCsv(big), file!!.readText())
            assertFalse("no half-written file is left behind", File(dir, "${file!!.name}.part").exists())
        } finally { dir.deleteRecursively() }
    }

    @Test
    fun theExportWritesOnTheIoPathAndHandsTheFileBack() {
        val dash = stressDash()
        val vm = ReportsViewModel(dash, ReportsFixtures.clock).apply { range.value = ReportRange.D90 }
        val dir = File(System.getProperty("java.io.tmpdir"), "neema-stress-${System.nanoTime()}")
        try {
            val got = mutableListOf<Pair<File, ReportRange>>()
            vm.exportCsv(dir) { f, r -> got += f to r }
            assertEquals(1, got.size)
            assertEquals(ReportRange.D90, got[0].second)
            assertEquals(vm.report.value!!.orders.size + 1, got[0].first.readLines().size)
            assertFalse("the button is free again", vm.exporting.value)
        } finally { dir.deleteRecursively() }
    }

    // ── Analytics ───────────────────────────────────────────────────────────

    @Test
    fun analyticsDerivationsOverFiveThousandOrdersAreExactAndFast() {
        val many = InsightsStressFixtures.orders(5_000)
        val human = convs.filter { it.interceptMode == "human" }
        val today = LocalDate.of(2026, 9, 25)
        repeat(2) { activityFeed(many, human, agents); sevenDayRevenue(many, today, NAIROBI); topProducts(many) }
        val t = ms { activityFeed(many, human, agents); sevenDayRevenue(many, today, NAIROBI); topProducts(many) }
        assertTrue("analytics derivations took ${t}ms", t < 300)
        // The newest four orders and three intercepts, newest first, as the web picks them.
        val feed = activityFeed(many, human, agents)
        assertEquals(7, feed.size)
        val newestOrders = many.sortedByDescending { Fmt.millis(it.createdAt) }.take(4).map { "order-${it.id}" }
        assertEquals(newestOrders, feed.filter { it.id.startsWith("order-") }.map { it.id })
        val times = feed.map { Fmt.millis(it.at)!! }
        assertEquals(times.sortedDescending(), times)
    }

    @Test
    fun theThirtySecondPollNeverStacksAndStopsInTheBackground() {
        val ws = FakeSocketFactory()
        val fake = FakeNeema.withFixtures().also(ReportsFixtures::install)
        val dash = dashboard(paparazzi.context, fake, appDispatcher = Dispatchers.Unconfined, wsFactory = ws)
        dash.container.notifications.start(dash.container.foreground)
        dash.container.socket.connect(Fixtures.ME_ID)
        ws.last.open()
        dash.container.foreground.value = true
        val vm = OverviewViewModel(dash)
        fun stats() = fake.callsTo("GET", "/admin/stats").size
        fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }
        assertEquals(1, stats())

        // Ten minutes on screen: exactly one read per 30 s tick.
        advance(10 * 60_000 + 1)
        assertEquals(1 + 20, stats())

        // A burst of 200 frames (intercepts and alerts) is ONE refetch, not 200.
        repeat(100) { i ->
            ws.last.frame("""{"type":"intercept_changed","conversationId":"c$i","mode":"human","eventKind":"intercept"}""")
            ws.last.frame("""{"event":"notification","type":"intercept","title":"Picked up $i","body":""}""")
        }
        advance(ScreenLife.EVENT_WINDOW_MS + 1)
        assertEquals(1 + 20 + 1, stats())

        // The app goes to the background: nothing polls, however long.
        dash.container.foreground.value = false
        advance(30 * 60_000)
        assertEquals(1 + 20 + 1, stats())

        // Back in front: one catch-up, then the 30 s rhythm again.
        dash.container.foreground.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(1 + 20 + 1 + 1, stats())
        advance(30_000)
        assertEquals(1 + 20 + 1 + 2, stats())
        vm.life.shown.value = false
    }

    // ── Catalog ─────────────────────────────────────────────────────────────

    private val products: List<CatalogItem> = InsightsStressFixtures.catalog()

    @Test
    fun theIndexedSearchAnswersExactlyTheWebFilterOverTwoThousandProducts() {
        val ix = CatalogIndex(products)
        for (filter in listOf("all", "Clergy Apparel", "General", "Communion Wine")) {
            for (q in listOf("", "product 1", "SKU-0199", "KITU", "alias33", "zzz", "wine", "1")) {
                assertEquals("$filter / $q", filterCatalog(products, filter, q).map { it.id }, ix.filter(filter, q).map { it.id })
            }
        }
        assertEquals(products.map { it.category }.filter { it.isNotEmpty() }.distinct(), ix.categories)
    }

    @Test
    fun typingIntoTheSearchOverTwoThousandProductsStaysFast() {
        val ix = CatalogIndex(products)
        val typed = "product 19 clergy"
        repeat(3) { typed.indices.forEach { ix.filter("all", typed.take(it + 1)) } }
        val t = ms { repeat(5) { typed.indices.forEach { ix.filter("all", typed.take(it + 1)) } } }
        // 85 keystrokes' worth of filtering over 2,000 products.
        assertTrue("search took ${t}ms", t < 400)
    }

    @Test
    fun theCatalogViewModelFiltersTheLiveCatalogue() {
        val dash = stressDash()
        val vm = CatalogViewModel(dash)
        assertEquals(2_000, vm.view.value.filtered.size)
        assertEquals(products.count { it.inStock }, vm.view.value.inStock)
        assertEquals(products.count { !it.inStock }, vm.view.value.outStock)
        vm.search.value = "sku-0019"
        assertEquals(filterCatalog(products, "all", "sku-0019").map { it.id }, vm.view.value.filtered.map { it.id })
        vm.filter.value = "Clergy Apparel"; vm.search.value = ""
        assertEquals(products.count { it.category == "Clergy Apparel" }, vm.view.value.filtered.size)
    }

    @Test
    fun gridRowKeysAreUniqueAndStableAcrossAPoll() {
        val grid = gridRows(products, 3)
        assertEquals(667, grid.rows.size)
        assertEquals(grid.rows.size, grid.keys.toSet().size)
        // One product's stock changes on the next poll: every row keeps its key.
        val polled = products.mapIndexed { i, p -> if (i == 700) p.copy(inStock = !p.inStock) else p }
        assertEquals(grid.keys, gridRows(polled, 3).keys)
        // A hub row and a local row sharing an id still get distinct keys.
        val dup = listOf(products[0], products[0].copy(name = "local twin")) + products.drop(1).take(4)
        val g = gridRows(dup, 1)
        assertEquals(g.rows.size, g.keys.toSet().size)
    }
}
