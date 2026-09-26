package ke.co.bethanyhouse.neema.freshness

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.feature.agents.AgentsViewModel
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.reports.Coalescer
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.feature.reports.ScreenLife
import ke.co.bethanyhouse.neema.feature.settings.SettingsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * How every non-inbox screen stays fresh (round 4): the web views' polls, run
 * only while the screen is on display and the app in front; a reload on each
 * return to the screen (the web view's remount), to the app, and after the
 * live socket reconnects; and the live notifications that move a screen's
 * figures. Time is virtual: [advance] moves the polls along.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ScreenFreshnessTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6) // a layoutlib Context only

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)
    private val scopes = mutableListOf<CoroutineScope>()

    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() { scopes.forEach { it.cancel() }; Dispatchers.resetMain() }

    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private val ws = FakeSocketFactory()

    /** A signed-in dashboard with its live socket open and the notification centre listening. */
    private fun live(): DashboardViewModel {
        val dash = dashboard(paparazzi.context, fake, appDispatcher = Dispatchers.Unconfined, wsFactory = ws)
        dash.container.notifications.start(dash.container.foreground)
        dash.container.socket.connect(Fixtures.ME_ID)
        ws.last.open()
        return dash
    }

    private fun toasts(dash: DashboardViewModel): List<Toast> {
        val all = mutableListOf<Toast>()
        CoroutineScope(main).also { scopes += it }.launch { dash.toasts.collect { all += it } }
        return all
    }

    /** The socket drops (frames are lost from here) and comes back. */
    private fun dropAndReconnect(dash: DashboardViewModel) {
        ws.last.fail()
        dash.container.socket.nudge()
        ws.last.open()
    }

    private fun notify(type: String, title: String = "Neema", body: String = "") =
        ws.last.frame("""{"event":"notification","type":"$type","title":"$title","body":"$body"}""")

    private fun gets(path: String) = fake.callsTo("GET", path).size
    private fun gets(path: String, query: String) = fake.callsTo("GET", path).count { it.query == query }

    // ── Deals: 60 s poll, only on display ───────────────────────────────────

    @Test
    fun dealsPollsEveryMinuteOnlyWhileOnDisplay() {
        val dash = live()
        val vm = DealsViewModel(dash)
        assertEquals("mount-time load", 1, gets("/admin/actions"))

        advance(60_001)
        assertEquals("the 60 s poll", 2, gets("/admin/actions"))

        // Off to another screen: the interval stops, as the web view's does when it unmounts.
        vm.life.shown.value = false
        advance(10 * 60_000)
        assertEquals(2, gets("/admin/actions"))

        // Back to Deals: one reload (the remount), then the minute poll again.
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(3, gets("/admin/actions"))
        advance(60_001)
        assertEquals(4, gets("/admin/actions"))
    }

    @Test
    fun dealsPausesInTheBackgroundAndCatchesUpOnReturn() {
        val dash = live()
        DealsViewModel(dash)
        dash.container.foreground.value = false
        advance(30 * 60_000)
        assertEquals("nothing while the app is in the background", 1, gets("/admin/actions"))

        dash.container.foreground.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals("the return reloads at once, not a minute later", 2, gets("/admin/actions"))
    }

    @Test
    fun aPlannedActionReloadsTheQueueOnceForABurst() {
        val dash = live()
        DealsViewModel(dash)
        // actions.py `_notify`: a follow-up moved into the approval queue — three at once.
        repeat(3) { notify("planned_action", "⏳ Follow-up needs your approval", "outside the 24h messaging window") }
        advance(ScreenLife.EVENT_WINDOW_MS - 1)
        assertEquals("the web's 800 ms", 1, gets("/admin/actions"))
        advance(2)
        assertEquals("one reload for the burst", 2, gets("/admin/actions"))
        assertEquals(2, gets("/admin/deals", "status=open"))
    }

    @Test
    fun aHubEventReloadsTheBoardButOtherNotificationsDoNot() {
        val dash = live()
        DealsViewModel(dash)
        notify("new_conversation"); notify("standup"); notify("selfcheck")
        advance(1_000)
        assertEquals(1, gets("/admin/deals", "status=open"))
        // hub_events: an order.paid closes the conversation's open deal as won.
        notify("hub_event", "🎉 Order paid")
        advance(ScreenLife.EVENT_WINDOW_MS + 1)
        assertEquals(2, gets("/admin/deals", "status=open"))
        assertEquals(2, gets("/admin/deals", "status=won"))
    }

    @Test
    fun aPlannedActionOffScreenWaitsForTheNextVisit() {
        val dash = live()
        val vm = DealsViewModel(dash)
        vm.life.shown.value = false
        notify("planned_action")
        advance(5_000)
        assertEquals(1, gets("/admin/actions"))
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(2, gets("/admin/actions"))
    }

    @Test
    fun dealsCatchesUpAfterTheSocketReconnects() {
        val dash = live()
        DealsViewModel(dash)
        dropAndReconnect(dash)
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(2, gets("/admin/actions"))
    }

    @Test
    fun aReturnAndAReconnectTogetherCostOneReload() {
        val dash = live()
        DealsViewModel(dash)
        dash.container.foreground.value = false
        dash.container.foreground.value = true
        dropAndReconnect(dash)
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(2, gets("/admin/actions"))
    }

    // ── Analytics: 30 s poll, live figures ──────────────────────────────────

    @Test
    fun overviewPollsStatsAndInterceptsEveryThirtySecondsOnDisplay() {
        val dash = live()
        val vm = OverviewViewModel(dash)
        assertEquals(1, gets("/admin/stats"))
        assertEquals(1, gets("/admin/attribution"))
        advance(30_001)
        assertEquals(2, gets("/admin/stats"))
        assertEquals(2, fake.callsTo("GET", "/admin/conversations").count { it.query.orEmpty().contains("tab=human") })
        assertEquals("attribution is a mount-time read", 1, gets("/admin/attribution"))

        vm.life.shown.value = false
        advance(5 * 60_000)
        assertEquals("no polling off-screen", 2, gets("/admin/stats"))

        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(3, gets("/admin/stats"))
        assertEquals(2, gets("/admin/attribution"))
    }

    @Test
    fun overviewCatchUpKeepsTheFiguresUpWithoutASpinner() {
        val dash = live()
        val vm = OverviewViewModel(dash)
        val before = vm.stats.value!!
        fake.on("GET", "/admin/stats", code = 502, body = "{}")
        vm.life.shown.value = false
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(before, vm.stats.value)
        assertEquals(false, vm.statsLoading.value)
    }

    @Test
    fun anInterceptChangeOrAnInterceptAlertMovesTheFigures() {
        val dash = live()
        OverviewViewModel(dash)
        ws.last.frame("""{"type":"intercept_changed","conversationId":"c1","mode":"human","eventKind":"intercept"}""")
        ws.last.frame("""{"type":"intercept_changed","conversationId":"c2","mode":"ai","eventKind":"release"}""")
        notify("intercept", "🙋 Grace picked up")
        advance(ScreenLife.EVENT_WINDOW_MS + 1)
        assertEquals("one refetch for the three", 2, gets("/admin/stats"))
        // A plain message moves nothing on this screen.
        ws.last.frame("""{"type":"new_message","conversationId":"c1","sender":"user","text":"hi"}""")
        advance(5_000)
        assertEquals(2, gets("/admin/stats"))
    }

    // ── order_update: Orders, the Analytics figures, the pending badge ─────

    @Test
    fun anOrderUpdateRefreshesOrdersTheBadgeAndTheFigures() {
        val dash = live()
        OverviewViewModel(dash)
        fun badge() = dash.navItems().first { it.id == ViewId.Orders }.badge
        val pendingBefore = badge()
        val statsBefore = gets("/admin/stats")

        // A new pending order lands server-side.
        val newRow = Fixtures.orderRow("o9", "254700000009", "[]", "1500.0", "pending", "whatsapp", 1)
        fake.on("GET", "/admin/orders", body = SalesFixtures.ordersJson(listOf(newRow) + SalesFixtures.orders))
        notify("order_update", "Order placed", "254700000009")
        advance(ScreenLife.EVENT_WINDOW_MS + 1)

        assertEquals(pendingBefore + 1, badge())
        assertTrue(dash.orders.value.any { it.id == "o9" })
        assertTrue("the Analytics figures follow", gets("/admin/stats") > statsBefore)
    }

    @Test
    fun theOrdersPollFindingAChangeRefreshesTheFigures() {
        val dash = live()
        OverviewViewModel(dash)
        val newRow = Fixtures.orderRow("o9", "254700000009", "[]", "1500.0", "pending", "whatsapp", 1)
        fake.on("GET", "/admin/orders", body = SalesFixtures.ordersJson(listOf(newRow) + SalesFixtures.orders))
        advance(90_001) // the dashboard's orders poll
        advance(ScreenLife.EVENT_WINDOW_MS + 1)
        // 30 s polls x3 plus the one the orders change asked for.
        assertEquals(1 + 3 + 1, gets("/admin/stats"))
    }

    @Test
    fun ordersRereadOnReturnAndAfterAReconnect() {
        val dash = live()
        val vm = OrdersViewModel(dash)
        val start = gets("/admin/orders")

        vm.life.shown.value = false
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(start + 1, gets("/admin/orders"))

        dropAndReconnect(dash)
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(start + 2, gets("/admin/orders"))

        // The dashboard's poll owns the foreground return: no second fetch from the screen.
        dash.container.foreground.value = false
        dash.container.foreground.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(start + 3, gets("/admin/orders"))
    }

    @Test
    fun aReconnectOffScreenFetchesNothing() {
        val dash = live()
        val vm = OrdersViewModel(dash)
        vm.life.shown.value = false
        val start = gets("/admin/orders")
        dropAndReconnect(dash)
        advance(5_000)
        assertEquals(start, gets("/admin/orders"))
    }

    // ── Screens the web loads once per visit ────────────────────────────────

    @Test
    fun leadsRereadOnReturnQuietly() {
        val dash = live()
        val toasts = toasts(dash)
        val vm = LeadsViewModel(dash)
        val shown = vm.leads.value
        assertTrue(shown.isNotEmpty())
        fake.on("GET", "/admin/leads", code = 500, body = """{"detail":"boom"}""")
        vm.life.shown.value = false
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(2, gets("/admin/leads"))
        assertEquals("a failed background re-read keeps the board", shown, vm.leads.value)
        assertTrue("and says nothing", toasts.isEmpty())
        assertEquals(false, vm.loading.value)
    }

    @Test
    fun leadsRereadWhenTheAppComesBack() {
        val dash = live()
        LeadsViewModel(dash)
        dash.container.foreground.value = false
        advance(60 * 60_000)
        assertEquals(1, gets("/admin/leads"))
        dash.container.foreground.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(2, gets("/admin/leads"))
    }

    @Test
    fun reportsDownloadOncePerVisitNeverOnATimer() {
        val dash = live()
        val vm = ReportsViewModel(dash)
        fun full() = fake.callsTo("GET", "/admin/conversations").count { it.query == null }
        assertEquals(1, full())
        advance(30 * 60_000)
        dash.container.foreground.value = false
        dash.container.foreground.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals("no poll, no reload on returning to the app", 1, full())
        vm.life.shown.value = false
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals("the next visit re-reads it", 2, full())
    }

    @Test
    fun catalogRereadsTheAuditAndTheCatalogueOnReturn() {
        val dash = live()
        val vm = CatalogViewModel(dash)
        val catalogBefore = gets("/admin/catalog")
        vm.life.shown.value = false
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(2, gets("/admin/catalog/audit"))
        assertEquals(catalogBefore + 1, gets("/admin/catalog"))
    }

    @Test
    fun theTeamIsFreshEachTimeItOpens() {
        val dash = live()
        val vm = AgentsViewModel(dash)
        val agentsBefore = gets("/admin/agents")
        val offlineBefore = dash.agents.value.count { !it.isAvailable }
        // A colleague went offline meanwhile.
        fake.on("GET", "/admin/agents", body = Fixtures.agents.replaceFirst("\"is_available\":true", "\"is_available\":false"))
        vm.life.shown.value = false
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals(agentsBefore + 1, gets("/admin/agents"))
        assertEquals(2, gets("/admin/roles"))
        assertEquals("the availability change shows", offlineBefore + 1, dash.agents.value.count { !it.isAvailable })
    }

    @Test
    fun theTeamPullToRefreshWaitsForTheList() {
        val dash = live()
        val vm = AgentsViewModel(dash)
        val before = gets("/admin/agents")
        vm.refresh()
        assertEquals(before + 1, gets("/admin/agents"))
        assertEquals(false, vm.refreshing.value)
    }

    @Test
    fun settingsRereadsOnReturnButKeepsUnsavedTyping() {
        val dash = live()
        val vm = SettingsViewModel(dash)
        vm.setDirectives("Half-written standing order")
        fake.on("GET", "/admin/settings/translation", body = """{"enabled":false,"default":false,"spend_30d_usd":0,"calls_30d":0}""")
        vm.life.shown.value = false
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals("Half-written standing order", vm.directives.value)
        assertEquals(1, gets("/admin/settings/directives"))
        assertEquals(false, vm.translation.value!!.enabled)
        assertEquals("the untouched offer is re-read", 2, gets("/admin/settings/offer"))
        assertEquals(2, gets("/admin/settings/pipeline-stages"))
    }

    @Test
    fun settingsRereadsUntouchedStandingOrders() {
        val dash = live()
        val vm = SettingsViewModel(dash)
        fake.on("GET", "/admin/settings/directives", body = """{"directives":"New orders from a colleague","max_chars":2000}""")
        vm.life.shown.value = false
        vm.life.shown.value = true
        advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        assertEquals("New orders from a colleague", vm.directives.value)
    }

    // ── The helpers ────────────────────────────────────────────────────────

    @Test
    fun aCoalescerFoldsABurstIntoOneRun() {
        val scope = CoroutineScope(main).also { scopes += it }
        var runs = 0
        val c = Coalescer(scope, 800) { runs++ }
        repeat(10) { c.kick() }
        advance(801)
        assertEquals(1, runs)
        c.kick()
        advance(801)
        assertEquals(2, runs)
    }
}
