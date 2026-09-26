package ke.co.bethanyhouse.neema.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
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
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 8 — the dashboard under a busy shop: alert storms coalesce into one
 * refetch, polls never stack and sleep in the background, and the signed-in
 * agent's screen store outlives the activity's content but not the agent.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DashboardStressTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)

    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    private fun live(fake: FakeNeema = FakeNeema.withFixtures()): Triple<DashboardViewModel, FakeSocketFactory, FakeNeema> {
        val ws = FakeSocketFactory()
        val dash = dashboard(paparazzi.context, fake, appDispatcher = Dispatchers.Unconfined, wsFactory = ws)
        dash.container.foreground.value = true
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

    @Test
    fun twoHundredInboxAlertsInABurstCostOneInboxRefetch() {
        val (dash, ws) = live()
        val refreshes = dash.inboxRefreshes()
        repeat(200) { i -> ws.last.frame("""{"event":"notification","type":"new_conversation","title":"New chat $i","body":"hi","wa_id":"2547$i"}""") }
        advance(799)
        assertEquals("the web's 800 ms wait", 0, refreshes())
        advance(2)
        assertEquals(1, refreshes())
        advance(10_000)
        assertEquals("and never again for the same burst", 1, refreshes())
        assertEquals("the bell stays bounded", 60, dash.container.notifications.items.value.size)
    }

    @Test
    fun anAlertAfterTheRefetchSchedulesAnotherSoNothingIsMissed() {
        val (dash, ws) = live()
        val refreshes = dash.inboxRefreshes()
        ws.last.frame("""{"event":"notification","type":"intercept","title":"a","body":"b","conversationId":"c1"}""")
        advance(801)
        ws.last.frame("""{"event":"notification","type":"intercept","title":"c","body":"d","conversationId":"c2"}""")
        advance(801)
        assertEquals(2, refreshes())
    }

    @Test
    fun twoHundredOrderAlertsCostOneOrdersFetch() {
        val (_, ws, fake) = live()
        val before = fake.callsTo("GET", "/admin/orders").size
        repeat(200) { i -> ws.last.frame("""{"event":"notification","type":"order_update","title":"Order paid","body":"BH-$i"}""") }
        advance(801)
        assertEquals(before + 1, fake.callsTo("GET", "/admin/orders").size)
    }

    @Test
    fun aBurstOfSocketFramesThatAreNotAlertsDoesNothingToTheDashboard() {
        val (dash, ws, fake) = live()
        val refreshes = dash.inboxRefreshes()
        val calls = fake.calls.size
        var emissions = 0
        CoroutineScope(main).launch { dash.orders.collect { emissions++ } }
        val base = emissions
        repeat(200) { i -> ws.last.frame("""{"type":"new_message","conversationId":"c${i % 9}","sender":"user","text":"m$i"}""") }
        advance(5_000)
        assertEquals(0, refreshes())
        assertEquals("no requests", calls, fake.calls.size)
        assertEquals("no list re-emissions", base, emissions)
    }

    @Test
    fun pollsSleepInTheBackgroundAndCatchUpOnceOnReturn() {
        val (dash, _, fake) = live()
        fun orders() = fake.callsTo("GET", "/admin/orders").size
        val start = orders()
        dash.container.foreground.value = false
        advance(30 * 60_000L) // half an hour in a pocket
        assertEquals("nothing polls in the background", start, orders())
        dash.container.foreground.value = true
        assertEquals("one fetch on return", start + 1, orders())
        advance(89_000)
        assertEquals(start + 1, orders())
        advance(2_000)
        assertEquals("then the 90 s rhythm", start + 2, orders())
    }

    @Test
    fun manyTokenRefreshesAndReturnsNeverStackPolls() {
        val (dash, _, fake) = live()
        fun orders() = fake.callsTo("GET", "/admin/orders").size
        val s = dash.session.value!!
        // A token refresh saves a new Session for the same agent 50 times.
        repeat(50) { dash.container.sessionStore.save(s.copy(accessToken = fakeJwt())) }
        val afterRefreshes = orders()
        advance(91_000)
        assertEquals("one poller, one tick", afterRefreshes + 1, orders())
        advance(90_000)
        assertEquals(afterRefreshes + 2, orders())
    }

    private class Probe : ViewModel() {
        var cleared = false
        override fun onCleared() { cleared = true }
    }

    private fun probeIn(store: androidx.lifecycle.ViewModelStore): Probe =
        ViewModelProvider(store, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <T : ViewModel> create(modelClass: Class<T>): T = Probe() as T
        })[Probe::class.java]

    @Test
    fun theAgentsScreenStoreSurvivesRecompositionButNotTheAgent() {
        val dash = dashboard(paparazzi.context)
        val id = dash.session.value!!.agentId
        val store = dash.viewModelStoreFor(id)
        val probe = probeIn(store)
        assertSame("the same agent gets the same store back (activity content recreated)", store, dash.viewModelStoreFor(id))
        assertTrue(!probe.cleared)

        val other = dash.viewModelStoreFor("someone-else")
        assertNotSame(store, other)
        assertTrue("another agent's store starts clean; the old one is cleared", probe.cleared)

        val p2 = probeIn(other)
        dash.logout()
        assertTrue("sign-out clears the screens' ViewModels", p2.cleared)
    }
}
