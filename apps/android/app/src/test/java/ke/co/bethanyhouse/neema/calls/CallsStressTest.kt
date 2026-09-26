package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.feature.calls.rowKeys
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesStressFixtures
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.time.Instant

/**
 * Round 8 — the call log at a thousand rows under a busy socket: bursts of
 * call frames, polling that pauses off-screen and never stacks, and the
 * row keys a lazy list needs.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallsLogStressTest {
    @get:Rule val paparazzi = Paparazzi()

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)
    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()
    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    private val fake = FakeNeema.withFixtures().also { SalesStressFixtures.install(it) }
    private val ws = FakeSocketFactory()

    private fun live(): CallsViewModel {
        val dash = dashboard(paparazzi.context, fake, appDispatcher = main, wsFactory = ws)
        dash.container.socket.connect(Fixtures.ME_ID)
        ws.last.open()
        return CallsViewModel(dash)
    }

    private val loads get() = fake.callsTo("GET", "/admin/calls").size

    @Test fun aThousandCallsLoadWithUniqueStableKeys() {
        val vm = live()
        val rows = vm.calls.value!!
        assertEquals(1_000, rows.size)
        val keys = rowKeys(rows)
        assertEquals(1_000, keys.toSet().size)
        assertEquals("keys follow the row, not its position", rowKeys(rows.drop(1)), keys.drop(1))
    }

    @Test fun duplicateRowsStillGetDistinctKeys() {
        val c = Call(id = "k1", callId = "wacid.1")
        val keys = rowKeys(listOf(c, c, Call(id = "", callId = "wacid.2"), c))
        assertEquals(listOf("k1", "k1#2", "wacid.2", "k1#3"), keys)
        val many = (0 until 5_000).map { Call(id = "k${it % 2_500}", callId = "w$it") }
        repeat(3) { rowKeys(many) }
        val t = System.nanoTime()
        val k = rowKeys(many)
        val ms = (System.nanoTime() - t) / 1e6
        assertEquals(5_000, k.toSet().size)
        assertTrue("5,000 keys in ${ms}ms (budget 200)", ms < 200)
    }

    @Test fun twoHundredCallFramesInABurstAreOneReload() {
        live()
        val before = loads
        repeat(200) { i ->
            val type = if (i % 2 == 0) "incoming_call" else "call_ended"
            ws.last.frame("""{"type":"$type","call_id":"wacid.B$i","from":"2547${i.toString().padStart(8, '0')}","status":"COMPLETED"}""")
        }
        advance(CallsViewModel.FRAME_RELOAD_MS)
        assertEquals("one reload for the whole burst", before + 1, loads)
        advance(60_000 - CallsViewModel.FRAME_RELOAD_MS - 1)
        assertEquals("and nothing queued behind it", before + 1, loads)
    }

    @Test fun offScreenTheLogNeitherPollsNorReloadsOnFramesAndCatchesUpOnReturn() {
        val vm = live()
        val before = loads
        vm.life.shown.value = false
        repeat(50) { ws.last.frame("""{"type":"incoming_call","call_id":"wacid.X$it","from":"254700000000"}""") }
        advance(5 * 60_000)
        assertEquals("another screen is showing: no ticks, no frame reloads", before, loads)
        vm.life.shown.value = true
        assertEquals("back on the log: one catch-up read", before + 1, loads)
        advance(60_000)
        assertEquals(before + 2, loads)
    }

    @Test fun aSlowLogReadIsNeverStackedByTicksFramesAndPulls() {
        val vm = live()
        val before = loads
        val hold = fake.hang("GET", "/admin/calls")
        vm.refresh()
        advance(60_000)                     // the fallback tick
        ws.last.frame("""{"type":"call_ended","call_id":"wacid.S1","status":"COMPLETED"}""")
        advance(CallsViewModel.FRAME_RELOAD_MS)
        vm.load()
        assertEquals("one read on the wire", 1, hold.waiting)
        hold.release()
        assertEquals("the slow read, then one that follows it — not four", before + 2, loads)
        assertFalse(vm.refreshing.value)
        assertEquals(1_000, vm.calls.value!!.size)
    }
}

/**
 * Round 8 — the softphone under socket bursts, and every media resource
 * released on every way a call ends: hang-up, decline, a failed answer, the
 * media dropping, the caller giving up, and signing out mid-call.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class SoftphoneStressTest {
    private val base = Instant.parse("2026-09-25T10:00:00Z").toEpochMilli()

    private inner class Rig(val scope: TestScope, api: FakeCallApi = FakeCallApi()) {
        val api = api
        val media = FakeMedia()
        val ringer = FakeRinger()
        val audio = FakeAudio()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 4_096)
        val foreground = MutableStateFlow(true)
        val connected = MutableStateFlow(true)
        private val d = StandardTestDispatcher(scope.testScheduler)
        val calls = CallManager(
            api = api, events = frames, connected = connected, scope = scope.backgroundScope, foreground = foreground,
            signedInFn = { true }, media = media, ringer = ringer, audio = audio,
            micGranted = { true }, main = d, io = d, now = { base + scope.testScheduler.currentTime },
        ).also { it.start() }
        val state get() = calls.state.value

        fun frame(vararg kv: Pair<String, String>) {
            frames.tryEmit(JsonObject(kv.associate { it.first to JsonPrimitive(it.second) }))
        }
        fun settle() = scope.runCurrent()

        /** Nothing of a call is left running: no peer open, no recording, no ring, no call audio. */
        fun assertReleased(why: String) {
            settle()
            assertTrue("$why: every peer closed", media.peers.all { it.closed })
            assertTrue("$why: every recording stopped", media.recordings.all { it.stopped })
            assertFalse("$why: not ringing", ringer.ringing)
            assertFalse("$why: no call notification", ringer.showing)
            assertFalse("$why: call audio left", audio.inCall)
            assertFalse("$why: mic service down", audio.micService)
        }
    }

    private fun rig(block: suspend TestScope.(Rig) -> Unit) = runTest { val r = Rig(this); r.settle(); block(r) }

    private fun Rig.answerAndConnect(id: String = "wacid.1") {
        val recordings = media.recordings.size
        frame("type" to "incoming_call", "call_id" to id, "from" to "254712345678", "name" to "Fr. Peter Kamau")
        settle()
        calls.answer(); settle()
        media.peer.onEvent(PeerEvent.Connected); settle()
        assertEquals(CallPhase.InCall, state.phase)
        assertEquals("recording while live", recordings + 1, media.recordings.size)
    }

    @Test fun aBurstOfTwoHundredFramesRingsOnceAndEndsCleanly() = rig { r ->
        repeat(200) { r.frame("type" to "incoming_call", "call_id" to "wacid.1", "from" to "254712345678") }
        repeat(200) { i -> r.frame("type" to "incoming_call", "call_id" to "wacid.other$i", "from" to "2547000$i") }
        r.settle()
        assertEquals(CallPhase.Ringing, r.state.phase)
        assertEquals("wacid.1", r.state.callId)
        assertEquals("rang once", 1, r.ringer.ringStarts)
        r.frame("type" to "call_ended", "call_id" to "wacid.1")
        r.settle()
        assertEquals(CallPhase.Ended, r.state.phase)
        r.assertReleased("call_ended")
    }

    @Test fun rememberedEndedCallsStayBoundedOverALongShift() = rig { r ->
        repeat(1_000) { i -> r.frame("type" to "call_ended", "call_id" to "wacid.done$i"); if (i % 100 == 0) r.settle() }
        r.settle()
        assertTrue("remembered ${r.calls.endedCount} ended calls", r.calls.endedCount <= CallManager.ENDED_MAX)
        // The newest are the ones kept: a late ring for one of them is still refused.
        r.frame("type" to "incoming_call", "call_id" to "wacid.done999", "from" to "254700000000")
        r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun pollsNeverOverlapOnASlowNetwork() = rig { r ->
        val gate = CompletableDeferred<Unit>()
        var inFlight = 0
        var maxInFlight = 0
        var lists = 0
        val slow = object : ke.co.bethanyhouse.neema.feature.calls.CallApi by r.api {
            override suspend fun list(): List<Call> {
                lists++; inFlight++; maxInFlight = maxOf(maxInFlight, inFlight)
                try { gate.await() } finally { inFlight-- }
                return emptyList()
            }
        }
        val calls = CallManager(
            api = slow, events = MutableSharedFlow(), connected = r.connected, scope = backgroundScope, foreground = r.foreground,
            signedInFn = { true }, media = FakeMedia(), ringer = FakeRinger(), audio = FakeAudio(),
            micGranted = { true }, main = StandardTestDispatcher(testScheduler), io = StandardTestDispatcher(testScheduler),
            now = { base + testScheduler.currentTime },
        ).also { it.start() }
        runCurrent()
        // The 12s tick, a reconnect and a return to the app all while the first poll hangs.
        testScheduler.advanceTimeBy(CallManager.IDLE_POLL_MS + 1); runCurrent()
        r.connected.value = false; runCurrent(); r.connected.value = true; runCurrent()
        r.foreground.value = false; runCurrent(); r.foreground.value = true; runCurrent()
        launch { calls.pollOnce() }; runCurrent()
        assertEquals("only one poll on the wire", 1, maxInFlight)
        gate.complete(Unit); runCurrent()
        assertEquals(1, maxInFlight)
        assertTrue("the piled-up asks are one more poll, not four ($lists)", lists <= 2)
    }

    // ── Every way a call ends releases the peer, the recording, the ring and the audio ──

    @Test fun hangUpReleasesEverything() = rig { r ->
        r.answerAndConnect()
        r.calls.hangup()
        r.assertReleased("hang-up")
    }

    @Test fun declineReleasesEverything() = rig { r ->
        r.frame("type" to "incoming_call", "call_id" to "wacid.1", "from" to "254712345678")
        r.settle()
        assertTrue(r.ringer.ringing)
        r.calls.hangup() // the card's Decline
        r.assertReleased("decline")
    }

    @Test fun aFailedAnswerReleasesEverything() = rig { r ->
        r.api.answerError = ke.co.bethanyhouse.neema.core.net.ApiException(500, "POST", "/admin/calls/wacid.1/answer", "{}")
        r.frame("type" to "incoming_call", "call_id" to "wacid.1", "from" to "254712345678")
        r.settle()
        r.calls.answer(); r.settle()
        testScheduler.advanceTimeBy(5_000); r.settle()
        assertTrue(r.state.phase == CallPhase.Ended || r.state.phase == CallPhase.Idle)
        r.assertReleased("answer failed")
    }

    @Test fun theMediaDroppingReleasesEverything() = rig { r ->
        r.answerAndConnect()
        r.media.peer.onEvent(PeerEvent.Ended); r.settle()
        r.assertReleased("peer failed")
    }

    @Test fun aNetworkBlipThatNeverRecoversReleasesEverything() = rig { r ->
        r.answerAndConnect()
        r.media.peer.onEvent(PeerEvent.Interrupted); r.settle()
        testScheduler.advanceTimeBy(CallManager.ICE_GRACE_MS + 1); r.settle()
        r.assertReleased("ICE never recovered")
    }

    @Test fun theCallerGivingUpWhileRingingReleasesEverything() = rig { r ->
        r.frame("type" to "incoming_call", "call_id" to "wacid.1", "from" to "254712345678")
        r.settle()
        testScheduler.advanceTimeBy(CallManager.RING_TIMEOUT_MS + 1); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
        r.assertReleased("ring timeout")
    }

    /** DashboardViewModel.logout() hangs the call up: nothing may outlive the session. */
    @Test fun signingOutMidCallReleasesEverything() = rig { r ->
        r.answerAndConnect()
        r.calls.hangup() // what logout() calls
        testScheduler.advanceTimeBy(2_000); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
        r.assertReleased("sign-out")
        assertEquals("the recording still reached the server", listOf("wacid.1"), r.api.uploads.map { it.first })
    }

    @Test fun tenCallsInARowLeaveNothingBehind() = rig { r ->
        repeat(10) { i ->
            r.answerAndConnect("wacid.row$i")
            r.calls.hangup(); r.settle()
            testScheduler.advanceTimeBy(1_100); r.settle()
            assertEquals(CallPhase.Idle, r.state.phase)
        }
        r.assertReleased("ten calls")
        assertEquals(10, r.media.peers.size)
        assertEquals(10, r.media.recordings.size)
    }
}
