package ke.co.bethanyhouse.neema.app

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.auth.Session
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fakeJwt
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 4: the dashboard catching up after missed frames, deep links on cold
 * start / while running / while signed out, and notification taps.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DashboardRealtimeTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)

    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    // Starts at the real clock the first poll stamps with; tests move it by hand.
    private var now = ke.co.bethanyhouse.neema.core.util.AppClock.now()

    private fun live(fake: FakeNeema = FakeNeema.withFixtures()): Triple<DashboardViewModel, FakeSocketFactory, FakeNeema> {
        val ws = FakeSocketFactory()
        val dash = dashboard(paparazzi.context, fake, appDispatcher = Dispatchers.Unconfined, wsFactory = ws)
        dash.clock = { now }
        dash.container.notifications.start(dash.container.foreground)
        dash.container.socket.connect(Fixtures.ME_ID)
        ws.last.open()
        return Triple(dash, ws, fake)
    }

    private fun DashboardViewModel.inboxRefreshes(): () -> Int {
        var n = 0
        CoroutineScope(main).launch { inboxRefresh.collect { n++ } }
        return { n }
    }

    private fun session() = Session(
        accessToken = fakeJwt(), refreshToken = "refresh", agentId = Fixtures.ME_ID,
        email = "moses@bethanyhouse.co.ke", name = "Moses Mwicigi", role = "admin", isSuperuser = true, mode = "direct",
    )

    // ── Missed frames ───────────────────────────────────────────────────────

    @Test
    fun aReconnectCatchesUpTheInboxAndOrders() {
        val (dash, ws, fake) = live()
        val refreshes = dash.inboxRefreshes()
        fun orders() = fake.callsTo("GET", "/admin/orders").size
        val before = orders()
        now += 60_000

        ws.last.fail()          // the network drops; frames are lost from here
        advance(2_001)
        assertEquals("nothing until the socket is really back", 0, refreshes())
        ws.last.open()

        // The inbox catches itself up on reconnect (InboxLiveTest); the dashboard
        // must not ping it as well, or the list would be fetched twice.
        assertEquals(0, refreshes())
        assertEquals(before + 1, orders())
    }

    @Test
    fun theFirstConnectAfterSignInIsNotACatchUp() {
        val (dash, _, fake) = live()
        val refreshes = dash.inboxRefreshes()
        assertEquals(0, refreshes())
        assertEquals("only the poll's own first fetch", 1, fake.callsTo("GET", "/admin/orders").size)
    }

    @Test
    fun ordersJustFetchedAreNotFetchedAgainOnReconnect() {
        val (dash, ws, fake) = live()
        val refreshes = dash.inboxRefreshes()
        val before = fake.callsTo("GET", "/admin/orders").size
        now += 1_000 // the poll ran a second ago (e.g. the app just came to the front)
        ws.dropAndReconnect(::advance)
        assertEquals("the inbox catches itself up", 0, refreshes())
        assertEquals("no refetch storm", before, fake.callsTo("GET", "/admin/orders").size)
    }

    @Test
    fun comingBackWithoutLiveModeCatchesUpToo() {
        val (dash, ws, fake) = live()
        val refreshes = dash.inboxRefreshes()
        now += 600_000
        dash.container.socket.disconnect() // backgrounded, live mode off
        dash.container.socket.connect(Fixtures.ME_ID); ws.last.open()
        assertEquals("the inbox catches itself up", 0, refreshes())
        assertTrue(fake.callsTo("GET", "/admin/orders").size >= 2)
    }

    @Test
    fun aBurstOfAlertsRefreshesOncePerAlertAndNeverDuplicates() {
        val (dash, ws) = live()
        val refreshes = dash.inboxRefreshes()
        repeat(10) { i -> ws.last.frame("""{"event":"notification","type":"new_conversation","title":"New chat $i","body":"hi","wa_id":"2547$i"}""") }
        // The same frame twice (a double publish) is one alert.
        ws.last.frame("""{"event":"notification","type":"new_conversation","title":"New chat 9","body":"hi","wa_id":"25479"}""")
        advance(801)
        assertEquals(10, refreshes())
        assertEquals(10, dash.container.notifications.items.value.size)
    }

    // ── Deep links ──────────────────────────────────────────────────────────

    @Test
    fun aLinkThatArrivesSignedOutIsReplayedAfterSignIn() {
        val dash = dashboard(paparazzi.context)
        dash.logout()
        dash.applyDeepLink(DeepLink(open = "254712345678", ref = "BH-1042", view = null, caller = null))
        assertNull("nothing happens at the login screen", dash.openConvKey.value)
        assertEquals(ViewId.Conversations, dash.view.value)

        dash.container.sessionStore.save(session())
        assertEquals("254712345678|BH-1042", dash.openConvKey.value)
        assertEquals(ViewId.Conversations, dash.view.value)
    }

    @Test
    fun aCallsLinkSignedOutFocusesTheCallerAfterSignIn() {
        val dash = dashboard(paparazzi.context)
        dash.logout()
        dash.applyDeepLink(DeepLink.of(mapOf("view" to "calls", "caller" to "254722000111")::get))
        dash.container.sessionStore.save(session())
        assertEquals(ViewId.Calls, dash.view.value)
        assertEquals("254722000111", dash.callsFocusKey.value)
    }

    @Test
    fun theStashIsReplayedOnceAndTheNewestWins() {
        val dash = dashboard(paparazzi.context)
        dash.logout()
        dash.applyDeepLink(DeepLink(null, null, "orders", null))
        dash.applyDeepLink(DeepLink(null, null, "reports", null))
        dash.container.sessionStore.save(session())
        assertEquals(ViewId.Reports, dash.view.value)

        dash.navigate(ViewId.Deals)
        dash.container.sessionStore.save(session().copy(accessToken = fakeJwt())) // a token refresh
        assertEquals("not replayed again", ViewId.Deals, dash.view.value)
    }

    @Test
    fun signingOutDropsAStashedLink() {
        val dash = dashboard(paparazzi.context)
        dash.logout()
        dash.applyDeepLink(DeepLink(null, null, "orders", null))
        dash.logout()
        dash.container.sessionStore.save(session())
        assertEquals(ViewId.Conversations, dash.view.value)
    }

    @Test
    fun aLinkWhileRunningAppliesAtOnce() {
        val dash = dashboard(paparazzi.context)
        dash.applyDeepLink(DeepLink.of(mapOf("open" to "254700000000")::get))
        assertEquals("254700000000", dash.openConvKey.value)
        dash.applyDeepLink(DeepLink.of(mapOf("view" to "analytics")::get))
        assertEquals(ViewId.Overview, dash.view.value)
    }

    @Test
    fun anEmptyLinkChangesNothing() {
        val dash = dashboard(paparazzi.context)
        dash.navigate(ViewId.Orders)
        dash.applyDeepLink(DeepLink.of { null })
        dash.applyDeepLink(DeepLink(null, "BH-1", null, "x"))
        assertEquals(ViewId.Orders, dash.view.value)
    }

    // ── Notification taps ───────────────────────────────────────────────────

    @Test
    fun tappingAnAlertOpensItsThreadAndMarksItRead() {
        val (dash, ws) = live()
        ws.last.frame("""{"event":"notification","type":"intercept","title":"🤖 AI Escalation","body":"x","conversationId":"c-77"}""")
        val n = dash.container.notifications.items.value.single()
        dash.navigate(ViewId.Orders)
        dash.openFromNotification(convKey = "c-77", view = null, notificationId = n.id)
        assertEquals("c-77", dash.openConvKey.value)
        assertEquals(ViewId.Conversations, dash.view.value)
        assertTrue(dash.container.notifications.items.value.single().read)
    }

    @Test
    fun tappingAnOrderAlertOpensOrders() {
        val dash = dashboard(paparazzi.context)
        dash.openFromNotification(convKey = null, view = "orders", notificationId = null)
        assertEquals(ViewId.Orders, dash.view.value)
    }

    @Test
    fun aTapThatFindsTheAgentSignedOutWaitsForSignIn() {
        val dash = dashboard(paparazzi.context)
        dash.logout()
        dash.openFromNotification(convKey = "254711", view = null, notificationId = "gone")
        assertNull(dash.openConvKey.value)
        dash.container.sessionStore.save(session())
        assertEquals("254711", dash.openConvKey.value)
    }
}
