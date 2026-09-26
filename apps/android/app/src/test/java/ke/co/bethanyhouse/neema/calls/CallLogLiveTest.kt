package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The Calls console's log stays live (components/views/CallsView.tsx): a
 * reload 500ms after `incoming_call` / `call_ended`, a 60s fallback tick
 * that pauses in the background, and — beyond the web — an immediate
 * catch-up when the socket reconnects or the app returns to the foreground.
 * Driven through the real LiveSocket on a fake WebSocket.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallLogLiveTest {
    @get:Rule val paparazzi = Paparazzi()

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)
    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()
    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    private class Live(val dash: DashboardViewModel, val ws: FakeSocketFactory, val fake: FakeNeema, val vm: CallsViewModel) {
        val loads get() = fake.callsTo("GET", "/admin/calls").size
    }

    private fun live(): Live {
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install)
        val ws = FakeSocketFactory()
        val dash = dashboard(paparazzi.context, fake, appDispatcher = main, wsFactory = ws)
        dash.container.socket.connect(Fixtures.ME_ID)
        ws.last.open()
        return Live(dash, ws, fake, CallsViewModel(dash))
    }

    private val newRing = CallsFixtures.row(
        "5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b99", "wacid.NEW", "254799999999", "Sr. Agnes Wairimu", "inbound", "ringing",
        null, null, CallsFixtures.pyIso(0), null, "none", false,
    )

    @Test fun incomingCallAddsTheRowHalfASecondLater() {
        val l = live()
        assertEquals(7, l.vm.calls.value!!.size)
        val loads = l.loads
        l.fake.on("GET", "/admin/calls", body = "[" + newRing + "," + CallsFixtures.calls.removePrefix("["))
        l.ws.last.frame("""{"type": "incoming_call", "call_id": "wacid.NEW", "from": "254799999999", "name": "Sr. Agnes Wairimu", "at": "1790330413"}""")
        advance(499)
        assertEquals(loads, l.loads)
        advance(1)
        assertEquals(loads + 1, l.loads)
        assertEquals("wacid.NEW", l.vm.calls.value!!.first().callId)
        assertEquals("ringing", l.vm.calls.value!!.first().status)
    }

    @Test fun callEndedUpdatesTheRow() {
        val l = live()
        val loads = l.loads
        l.ws.last.frame("""{"type": "call_ended", "call_id": "${CallsFixtures.C2}", "status": "COMPLETED", "duration": null}""")
        advance(500)
        assertEquals(loads + 1, l.loads)
    }

    @Test fun aBurstOfFramesIsOneReloadNotAStorm() {
        val l = live()
        val loads = l.loads
        repeat(3) { l.ws.last.frame("""{"type": "incoming_call", "call_id": "wacid.NEW", "from": "254799999999", "name": null, "at": "1"}""") }
        l.ws.last.frame("""{"type": "call_ended", "call_id": "wacid.NEW", "status": "COMPLETED", "duration": null}""")
        l.ws.last.frame("""{"type": "call_ended", "call_id": "wacid.OTHER", "status": "COMPLETED", "duration": null}""")
        advance(500)
        assertEquals(loads + 1, l.loads)
        // A frame after that reload schedules the next one.
        l.ws.last.frame("""{"type": "call_ended", "call_id": "wacid.NEW", "status": "COMPLETED", "duration": null}""")
        advance(500)
        assertEquals(loads + 2, l.loads)
    }

    @Test fun framesThatAreNotCallLogEventsLoadNothing() {
        val l = live()
        val loads = l.loads
        l.ws.last.frame("""{"type": "outbound_answer", "call_id": "wacid.OUT", "sdp": "v=0"}""")
        l.ws.last.frame("""{"type": "new_message", "conversationId": "c1", "sender": "user", "text": "hi"}""")
        l.ws.last.frame("""{"event": "notification", "type": "intercept", "title": "t", "body": "b", "conversationId": "c1"}""")
        advance(1_000)
        assertEquals(loads, l.loads)
    }

    @Test fun aReconnectCatchesUpWhatTheDroppedSocketMissed() {
        val l = live()
        val loads = l.loads
        l.ws.last.fail()
        advance(2_000)          // LiveSocket retries after 2s
        assertEquals(loads, l.loads)
        l.ws.last.open()
        assertEquals("reloaded on reconnect, without waiting for the 60s tick", loads + 1, l.loads)
    }

    @Test fun theFallbackTickPausesInTheBackgroundAndReturningReloadsAtOnce() {
        val l = live()
        val loads = l.loads
        advance(60_000)
        assertEquals(loads + 1, l.loads)
        l.dash.container.foreground.value = false
        advance(180_000)
        assertEquals("no ticks in the background", loads + 1, l.loads)
        l.dash.container.foreground.value = true
        assertEquals(loads + 2, l.loads)
        advance(59_000)
        assertEquals("the clock restarts on return: no double load", loads + 2, l.loads)
        advance(1_000)
        assertEquals(loads + 3, l.loads)
    }
}
