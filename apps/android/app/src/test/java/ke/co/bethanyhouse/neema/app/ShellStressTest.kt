package ke.co.bethanyhouse.neema.app

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.net.ErrorText
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fakeJwt
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestCoroutineScheduler
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

/**
 * Round 5 — the dashboard's shared state under a bad network: a server
 * outage never opens the session-expired prompt, re-authenticating keeps
 * everything, a different agent starts clean, and answers that land after
 * sign-out (or after the agent changed) are dropped.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ShellStressTest {
    // Only for a Context (layoutlib); nothing is rendered here.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)

    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    @Test
    fun anOutageDuringRefreshNeverOpensTheSessionExpiredPrompt() {
        val fake = FakeNeema.withFixtures()
        fake.on("GET", "/admin/agents", code = 401, body = """{"detail":"Token expired"}""")
        fake.on("POST", "/agent-auth/refresh", code = 503, body = "<html>Service Unavailable</html>")
        val dash = dashboard(paparazzi.context, fake)
        assertFalse(dash.sessionExpired.value)
        assertTrue(dash.session.value != null)

        fake.offline = true
        dash.refetchAgents(); dash.refetchOrders()
        assertFalse("offline is not signed out", dash.sessionExpired.value)
    }

    @Test
    fun manyParallel401sOpenOnePrompt() {
        val fake = FakeNeema.withFixtures()
        fake.on("GET", "/admin/[a-z]+", code = 401, body = """{"detail":"Could not validate credentials"}""")
        fake.on("POST", "/agent-auth/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val dash = dashboard(paparazzi.context, fake)
        var opened = 0
        val job = kotlinx.coroutines.CoroutineScope(main).launchCount(dash) { opened++ }
        dash.refetchAgents(); dash.refetchOrders(); dash.refetchCatalog(); dash.refetchMe()
        assertTrue(dash.sessionExpired.value)
        assertEquals("one prompt, however many requests failed", 1, opened)
        assertEquals("the server is asked once", 1, fake.callsTo("POST", "/agent-auth/refresh").size)
        job.cancel()
    }

    private fun kotlinx.coroutines.CoroutineScope.launchCount(dash: DashboardViewModel, onOpen: () -> Unit) =
        launch { dash.sessionExpired.collect { if (it) onOpen() } }

    @Test
    fun reAuthenticatingAsTheSameAgentKeepsWhereTheyWere() {
        val fake = FakeNeema.withFixtures()
        val dash = dashboard(paparazzi.context, fake)
        dash.navigate(ViewId.Orders)
        dash.callsFocusKey.value = "254712345678"
        val me = dash.me.value
        dash.sessionExpired.value = true
        // The prompt signs in again: a new token for the same agent.
        dash.container.sessionStore.save(dash.session.value!!.copy(accessToken = fakeJwt(Fixtures.ME_ID, 7200), refreshToken = "r-new"))
        dash.onReauthenticated()
        assertFalse(dash.sessionExpired.value)
        assertEquals(ViewId.Orders, dash.view.value)
        assertEquals("254712345678", dash.callsFocusKey.value)
        assertEquals(me, dash.me.value)
    }

    @Test
    fun aTokenRefreshDoesNotRestartEveryPoll() {
        val fake = FakeNeema.withFixtures()
        val dash = dashboard(paparazzi.context, fake)
        val before = fake.calls.size
        dash.container.sessionStore.save(dash.session.value!!.copy(accessToken = fakeJwt(Fixtures.ME_ID, 7200)))
        dash.container.auth.updateProfile("Moses M.", "moses@bethanyhouse.co.ke")
        assertEquals("a new token for the same agent refetches nothing", before, fake.calls.size)
    }

    @Test
    fun anotherAgentSigningInStartsClean() {
        val fake = FakeNeema.withFixtures()
        val dash = dashboard(paparazzi.context, fake)
        dash.navigate(ViewId.Orders)
        dash.openConvKey.value = "254712345678"
        dash.inboxSummary.value = ke.co.bethanyhouse.neema.core.model.InboxSummary()
        assertTrue(dash.orders.value.isNotEmpty())

        // Grace signs in on this phone without a sign-out step in between.
        fake.on("GET", "/admin/orders", body = "[]")
        dash.container.sessionStore.save(
            dash.session.value!!.copy(accessToken = fakeJwt(Fixtures.AGENT2_ID), agentId = Fixtures.AGENT2_ID, email = "grace@bethanyhouse.co.ke"),
        )
        assertEquals(ViewId.Conversations, dash.view.value)
        assertNull(dash.openConvKey.value)
        assertNull(dash.inboxSummary.value)
        assertTrue("Moses's orders are gone; Grace's (none) are shown", dash.orders.value.isEmpty())
    }

    @Test
    fun anAnswerThatLandsAfterSignOutIsDropped() {
        val fake = FakeNeema.withFixtures()
        val dash = dashboard(paparazzi.context, fake)
        val hold = fake.hang("GET", "/admin/orders")
        dash.refetchOrders()
        assertEquals(1, hold.waiting)
        dash.logout()
        hold.release()
        advance(1)
        assertTrue("no orders for a signed-out app", dash.orders.value.isEmpty())
    }

    @Test
    fun signingOutMidPollCancelsItQuietly() {
        val fake = FakeNeema.withFixtures()
        val dash = dashboard(paparazzi.context, fake)
        val hold = fake.hang("GET", "/admin/(orders|agents|catalog)")
        dash.container.foreground.value = false; dash.container.foreground.value = true   // polls refetch on return
        assertTrue(hold.waiting > 0)
        dash.logout()
        assertEquals("the polls' held requests were abandoned", 0, hold.waiting)
        hold.release()
        assertTrue(dash.orders.value.isEmpty() && dash.agents.value.isEmpty())
    }

    @Test
    fun errorTextCoversOfflineAndTimeouts() {
        val dash = dashboard(paparazzi.context)
        val fake = FakeNeema()
        assertEquals(ErrorText.TIMED_OUT, dash.errorText(ke.co.bethanyhouse.neema.core.net.ApiException(0, "GET", "/x", "timed out after 30s")))
        assertEquals(ErrorText.OFFLINE, dash.errorText(ke.co.bethanyhouse.neema.core.net.ApiException(0, "GET", "/x", "Connection reset")))
        assertTrue(fake.calls.isEmpty())
    }

    @Test
    fun theOnlineFlagIsTheContainers() {
        val dash = dashboard(paparazzi.context)
        assertTrue(dash.online.value)
        dash.container.online.value = false
        assertFalse(dash.online.value)
    }
}
