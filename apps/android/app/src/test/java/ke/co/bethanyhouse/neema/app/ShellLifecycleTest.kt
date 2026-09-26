package ke.co.bethanyhouse.neema.app

import androidx.lifecycle.SavedStateHandle
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.testContainer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.awaitCancellation
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
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 9 (lifecycle and state) for the shell: the view and the way back
 * through the views survive the process being killed; a deep link that
 * arrived at the login screen survives it too and replays after sign-in;
 * system back walks the views and then leaves; sign-out ends a live call
 * with the token still in hand (bounded), then clears everything.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ShellLifecycleTest {
    // Only for a Context (layoutlib); nothing is rendered here.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)

    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    /** What Android writes to the saved-state Bundle, handed to the next process. */
    private fun SavedStateHandle.afterProcessDeath() = SavedStateHandle(keys().associateWith { get<Any?>(it) })

    private fun dash(handle: SavedStateHandle = SavedStateHandle(), fake: FakeNeema = FakeNeema.withFixtures()) =
        DashboardViewModel(testContainer(paparazzi.context, fake), handle)

    // ── Back through the views ─────────────────────────────────────────────

    @Test fun backWalksThePreviousViewsThenTheInboxThenLeaves() {
        val d = dash()
        assertFalse("the inbox with nowhere to go back to: the system leaves the app", d.canGoBack.value)
        d.navigate(ViewId.Orders)
        d.navigate(ViewId.Reports)
        assertTrue(d.canGoBack.value)
        assertTrue(d.back()); assertEquals(ViewId.Orders, d.view.value)
        assertTrue(d.back()); assertEquals(ViewId.Conversations, d.view.value)
        assertFalse(d.canGoBack.value)
        assertFalse(d.back())
        assertEquals(ViewId.Conversations, d.view.value)
    }

    @Test fun eachViewIsRememberedOnceSoBackNeverLoops() {
        val d = dash()
        // Inbox → Orders → Reports → Orders → Inbox → Orders
        listOf(ViewId.Orders, ViewId.Reports, ViewId.Orders, ViewId.Conversations, ViewId.Orders).forEach(d::navigate)
        val seen = mutableListOf<ViewId>()
        while (d.back()) seen += d.view.value
        assertEquals("then the inbox, and out", listOf(ViewId.Conversations, ViewId.Reports, ViewId.Conversations), seen)
    }

    @Test fun navigatingToTheSameViewIsNotAHistoryEntry() {
        val d = dash()
        d.navigate(ViewId.Orders); d.navigate(ViewId.Orders); d.navigate(ViewId.Orders)
        assertTrue(d.back()); assertEquals(ViewId.Conversations, d.view.value)
        assertFalse(d.back())
    }

    @Test fun aViewReachedWithoutHistoryStillGoesBackToTheInbox() {
        // A deep link straight into Calls (a cold start from a notification).
        val handle = SavedStateHandle(mapOf("shell.view" to "Calls", "shell.owner" to Fixtures.ME_ID))
        val d = dash(handle)
        assertEquals(ViewId.Calls, d.view.value)
        assertTrue(d.canGoBack.value)
        assertTrue(d.back()); assertEquals(ViewId.Conversations, d.view.value)
        assertFalse(d.back())
    }

    @Test fun crossViewRequestsAreHistoryEntriesToo() {
        val d = dash()
        d.navigate(ViewId.Orders)
        d.openConversationFor("254722000111")
        assertEquals(ViewId.Conversations, d.view.value)
        assertTrue("back from the chat opened out of Orders returns to Orders", d.back())
        assertEquals(ViewId.Orders, d.view.value)
        d.focusCalls("254722000111")
        assertTrue(d.back()); assertEquals(ViewId.Orders, d.view.value)
    }

    // ── Process death ──────────────────────────────────────────────────────

    @Test fun theViewAndItsHistorySurviveProcessDeath() {
        val handle = SavedStateHandle()
        val before = dash(handle)
        before.navigate(ViewId.Orders)
        before.navigate(ViewId.Deals)
        // The process dies in the background; Android restores the saved state into a new one.
        val after = dash(handle.afterProcessDeath())
        assertEquals("the first frame is already the right view", ViewId.Deals, after.view.value)
        assertTrue(after.canGoBack.value)
        assertTrue(after.back()); assertEquals(ViewId.Orders, after.view.value)
        assertTrue(after.back()); assertEquals(ViewId.Conversations, after.view.value)
        assertFalse(after.back())
    }

    @Test fun anotherAgentRestoredIntoTheSameTaskStartsOnTheInbox() {
        val handle = SavedStateHandle(
            mapOf("shell.view" to "Settings", "shell.history" to arrayListOf("Conversations", "Orders"), "shell.owner" to "agent-someone-else"),
        )
        val d = dash(handle)
        assertEquals(ViewId.Conversations, d.view.value)
        assertFalse(d.canGoBack.value)
        assertEquals(Fixtures.ME_ID, handle.get<String>("shell.owner"))
    }

    @Test fun unknownSavedViewNamesAreIgnored() {
        val d = dash(SavedStateHandle(mapOf("shell.view" to "Nope", "shell.history" to arrayListOf("Gone", "Orders"), "shell.owner" to Fixtures.ME_ID)))
        assertEquals(ViewId.Conversations, d.view.value)
        assertTrue(d.back()); assertEquals(ViewId.Orders, d.view.value)
    }

    @Test fun aDeepLinkThatArrivedSignedOutSurvivesProcessDeathAndReplaysAfterSignIn() {
        val fake = FakeNeema.withFixtures()
        val c1 = testContainer(paparazzi.context, fake)
        val session = c1.sessionStore.current!!
        c1.auth.logout()
        val handle = SavedStateHandle()
        val atLogin = DashboardViewModel(c1, handle)
        atLogin.applyDeepLink(DeepLink(open = "254722000111", ref = "BH-1042", view = null, caller = null))
        assertNull("nothing opens while signed out", atLogin.openConvKey.value)

        // Killed at the login screen; the agent comes back and signs in.
        val c2 = testContainer(paparazzi.context, fake)
        c2.auth.logout()
        val restored = DashboardViewModel(c2, handle.afterProcessDeath())
        assertNull(restored.openConvKey.value)
        c2.sessionStore.save(session)
        assertEquals("254722000111|BH-1042", restored.openConvKey.value)
        assertEquals(ViewId.Conversations, restored.view.value)
        // Replayed once: a later sign-in (after a sign-out) does not open it again.
        restored.openConvKey.value = null
        restored.logout()
        c2.sessionStore.save(session)
        assertNull(restored.openConvKey.value)
    }

    @Test fun aNotificationTapWhileSignedOutWaitsForSignIn() {
        val c = testContainer(paparazzi.context)
        val session = c.sessionStore.current!!
        c.auth.logout()
        val d = DashboardViewModel(c, SavedStateHandle())
        d.openFromNotification(convKey = null, view = "orders", notificationId = null)
        assertEquals(ViewId.Conversations, d.view.value)
        c.sessionStore.save(session)
        assertEquals(ViewId.Orders, d.view.value)
    }

    // ── Sign-out ───────────────────────────────────────────────────────────

    @Test fun signOutTellsTheServerTheCallIsOverBeforeTheTokenGoes() {
        val fake = FakeNeema.withFixtures()
        fake.on("POST", "/admin/calls/wacid.9/terminate", body = """{"ok":true}""")
        val hold = fake.hang("POST", "/admin/calls/wacid.9/terminate")
        val d = dash(fake = fake)
        // What CallManager.endForSignOut does for a live call: POST /terminate, awaited.
        d.endCall = { runCatching { d.container.api.calls.terminate("wacid.9") } }

        d.logout()
        assertNotNull("the token stays while the terminate is on its way", d.session.value)
        assertTrue(d.signingOut.value)
        hold.release()
        val terminate = fake.callsTo("POST", "/admin/calls/wacid.9/terminate").single()
        assertTrue(terminate.headers["Authorization"].orEmpty(), terminate.headers["Authorization"].orEmpty().startsWith("Bearer "))
        assertNull("then the agent is signed out", d.session.value)
        assertFalse(d.signingOut.value)
    }

    @Test fun signOutWaitsForTheCallOnlySoLong() {
        val d = dash()
        var ended = 0
        d.endCall = { ended++; awaitCancellation() }
        d.navigate(ViewId.Orders)
        d.logout()
        d.logout()   // a second tap while waiting changes nothing
        assertEquals(1, ended)
        advance(3_999)
        assertNotNull(d.session.value)
        advance(2)
        assertNull("4 s at most, then the sign-out goes ahead", d.session.value)
        assertEquals(ViewId.Conversations, d.view.value)
        assertFalse(d.canGoBack.value)
        assertFalse(d.signingOut.value)
    }

    @Test fun signOutWithNoCallIsImmediateAndForgetsTheAgent() {
        val d = dash()
        d.navigate(ViewId.Orders); d.navigate(ViewId.Reports)
        d.openConvKey.value = "254722000111"
        d.logout()
        assertNull(d.session.value)
        assertNull(d.me.value)
        assertTrue(d.orders.value.isEmpty())
        assertNull(d.openConvKey.value)
        assertEquals(ViewId.Conversations, d.view.value)
        assertFalse("the next agent can't walk back into the last one's views", d.canGoBack.value)
    }

    @Test fun aFailingHangUpDoesNotBlockSignOut() {
        val d = dash()
        d.endCall = { error("media already torn down") }
        d.logout()
        assertNull(d.session.value)
    }

    // ── Shell back ordering ────────────────────────────────────────────────

    @Test fun shellOverlaysCloseTopmostFirstThenLeaveBackToTheView() {
        assertEquals(ShellOverlay.Bell, shellBackTarget(bellPopupOpen = true, accountMenuOpen = true, drawerOpen = true))
        assertEquals(ShellOverlay.AccountMenu, shellBackTarget(bellPopupOpen = false, accountMenuOpen = true, drawerOpen = true))
        assertEquals(ShellOverlay.Drawer, shellBackTarget(bellPopupOpen = false, accountMenuOpen = false, drawerOpen = true))
        assertNull(shellBackTarget(bellPopupOpen = false, accountMenuOpen = false, drawerOpen = false))
    }

    // ── Orders: one read on the wire ───────────────────────────────────────

    @Test fun ordersRefetchesThatMeetShareOneRead() {
        val fake = FakeNeema.withFixtures()
        val d = dash(fake = fake)
        val before = fake.callsTo("GET", "/admin/orders").size
        val hold = fake.hang("GET", "/admin/orders")
        d.refetchOrders()          // on the wire (held)
        d.refetchOrders()          // queued behind it
        d.refetchOrders()          // shares the queued one
        d.onReauthenticated()      // and so does re-auth's
        hold.release()
        assertEquals("the held read, then ONE more — not four", before + 2, fake.callsTo("GET", "/admin/orders").size)
    }
}
