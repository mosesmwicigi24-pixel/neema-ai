package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallRecorder
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.orders.MainDispatcherRule
import ke.co.bethanyhouse.neema.orders.processDeath
import ke.co.bethanyhouse.neema.orders.ToastLog
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.File
import java.nio.file.Files
import java.time.Instant

/**
 * Round 9 — the softphone through what a phone does to an app: a main thread
 * held back while the screen is off (the timer must still read the true
 * length), a call that ends while the app is in the background, sign-out in
 * the middle of a call, and a process killed mid-call (its raw audio swept,
 * its finished recordings still uploaded by the next process).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallLifecycleTest {
    private val base = Instant.parse("2026-09-25T10:00:00Z").toEpochMilli()

    private inner class Rig(val scope: TestScope, val outboxDir: File = Files.createTempDirectory("rec-outbox").toFile()) {
        val api = FakeCallApi()
        val media = SweepingMedia()
        val ringer = FakeRinger()
        val audio = FakeAudio()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 64)
        val foreground = MutableStateFlow(true)
        val connected = MutableStateFlow(true)
        var signedIn = true
        /** Wall-clock time that passed with the main thread asleep (no ticks ran). */
        var slept = 0L
        private val d = StandardTestDispatcher(scope.testScheduler)
        fun manager() = CallManager(
            api = api, events = frames, connected = connected, scope = scope.backgroundScope, foreground = foreground,
            signedInFn = { signedIn }, media = media, ringer = ringer, audio = audio,
            micGranted = { true }, main = d, io = d, now = { base + scope.testScheduler.currentTime + slept },
            outboxDir = outboxDir,
        ).also { it.start() }
        val calls = manager()
        val state get() = calls.state.value

        fun frame(vararg kv: Pair<String, String>) {
            frames.tryEmit(JsonObject(kv.associate { it.first to JsonPrimitive(it.second) }))
            scope.runCurrent()
        }
        fun ring(id: String = "wacid.1") = frame("type" to "incoming_call", "call_id" to id, "from" to "254712345678", "name" to "Fr. Peter Kamau")
        fun settle() = scope.runCurrent()
        fun live(): FakePeer { ring(); calls.answer(); settle(); media.peer.onEvent(PeerEvent.Connected); settle(); return media.peer }
    }

    private fun rig(block: suspend TestScope.(Rig) -> Unit) = runTest { val r = Rig(this); r.settle(); block(r) }

    // ── The timer ────────────────────────────────────────────────────────────
    @Test fun theTimerReadsTheClockNotACountOfTicks() = rig { r ->
        r.live()
        advanceTimeBy(5_001); runCurrent()
        assertEquals(5, r.state.seconds)
        // The screen goes off and the main thread sleeps for a minute: no tick runs.
        r.slept += 60_000
        advanceTimeBy(1_000); runCurrent()
        assertEquals("the first tick after waking reads the true length", 66, r.state.seconds)
    }

    @Test fun backOnScreenTheTimerIsTrueAtOnce() = rig { r ->
        r.live()
        advanceTimeBy(2_001); runCurrent()
        r.foreground.value = false; r.settle()
        r.slept += 90_000
        r.foreground.value = true; r.settle()
        assertEquals(92, r.state.seconds)
    }

    @Test fun theTimerKeepsGoingThroughAReconnectAndStartsAfreshNextCall() = rig { r ->
        val p = r.live()
        advanceTimeBy(3_001); runCurrent()
        p.onEvent(PeerEvent.Interrupted); r.settle()
        advanceTimeBy(2_000); runCurrent()
        p.onEvent(PeerEvent.Connected); r.settle()
        advanceTimeBy(1_000); runCurrent()
        assertEquals(6, r.state.seconds)
        r.calls.hangup(); r.settle()
        advanceTimeBy(1_500); runCurrent()
        assertNull(r.calls.liveSinceForTest)
        advanceTimeBy(15_000); runCurrent()
        r.live()
        advanceTimeBy(1_001); runCurrent()
        assertEquals("a new call's timer starts from zero", 1, r.state.seconds)
    }

    // ── Background ───────────────────────────────────────────────────────────
    @Test fun aCallThatEndsInTheBackgroundIsOverWhenTheAgentComesBack() = rig { r ->
        r.live()
        r.foreground.value = false; r.settle()
        r.frame("type" to "call_ended", "call_id" to "wacid.1")
        assertEquals(CallPhase.Ended, r.state.phase)
        advanceTimeBy(1_100); runCurrent()
        r.foreground.value = true; r.settle()
        assertEquals("not a stale live card", CallPhase.Idle, r.state.phase)
        assertFalse(r.audio.inCall)
    }

    @Test fun aRingThatStopsInTheBackgroundTakesItsNotificationWithIt() = rig { r ->
        r.foreground.value = false; r.settle()
        r.ring()
        assertTrue(r.ringer.showing)
        r.frame("type" to "call_ended", "call_id" to "wacid.1")
        assertFalse(r.ringer.showing)
        assertFalse(r.ringer.ringing)
    }

    // ── Sign-out ─────────────────────────────────────────────────────────────
    @Test fun signOutWaitsForTheTerminateBeforeTheSessionGoes() = rig { r ->
        r.live()
        var terminated = false
        val done = async { r.calls.endForSignOut(); terminated = "terminate wacid.1" in r.api.log }
        r.settle()
        assertTrue(done.isCompleted)
        assertTrue("the terminate went out before endForSignOut returned", terminated)
        assertEquals(CallPhase.Idle, r.state.phase)
        assertNull(r.state.callId)
        assertFalse(r.audio.inCall)
    }

    @Test fun signOutGivesUpOnASlowTerminateAfterTheBound() = rig { r ->
        r.live()
        r.api.terminateGate = kotlinx.coroutines.CompletableDeferred()   // the server never answers
        val t0 = testScheduler.currentTime
        val done = async { r.calls.endForSignOut() }
        advanceTimeBy(CallManager.SIGN_OUT_TERMINATE_MS - 1); runCurrent()
        assertFalse("waits for the server a while", done.isCompleted)
        advanceTimeBy(2); runCurrent()
        assertTrue("…but sign-out is never held up for long", done.isCompleted)
        assertTrue(testScheduler.currentTime - t0 <= CallManager.SIGN_OUT_TERMINATE_MS + 1)
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun signOutWhileRingingLetsTheCallRingOnForColleagues() = rig { r ->
        r.ring()
        r.calls.endForSignOut(); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
        assertFalse("not declined for everyone", r.api.log.any { it.startsWith("terminate") })
        assertFalse(r.ringer.ringing)
        assertFalse(r.ringer.showing)
        // And it doesn't ring again on this phone from a lagging poll.
        r.api.calls = listOf(ke.co.bethanyhouse.neema.core.model.Call(id = "k", callId = "wacid.1", waId = "254712345678", status = "ringing", direction = "inbound",
            startedAt = Instant.ofEpochMilli(base + testScheduler.currentTime).toString()))
        r.calls.pollOnce(); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
    }

    @Test fun signOutWithNoCallIsANoOp() = rig { r ->
        r.calls.endForSignOut(); r.settle()
        assertEquals(CallPhase.Idle, r.state.phase)
        assertTrue(r.api.log.none { it.startsWith("terminate") })
    }

    // ── Process death ────────────────────────────────────────────────────────
    @Test fun aNewProcessSweepsRawAudioAndStillUploadsTheOutbox() = runTest {
        val dir = Files.createTempDirectory("rec-outbox").toFile()
        val first = Rig(this, dir); first.settle()
        assertEquals("swept once at start-up", 1, first.media.sweeps)
        first.api.uploadErrors += ApiException(0, "POST", "/admin/calls/wacid.1/recording", "Failed to connect")
        first.live()
        advanceTimeBy(3_000); runCurrent()
        first.calls.hangup(); first.settle()
        assertEquals("kept for later", 1, dir.listFiles()!!.size)

        // The process dies; a new one starts on the same files.
        val second = Rig(this, dir); second.settle()
        assertEquals(listOf("wacid.1"), second.api.uploads.map { it.first })
        assertEquals(0, dir.listFiles()!!.size)
    }

    @Test fun recorderLeftoversAreSweptButNothingElse() {
        val dir = Files.createTempDirectory("rec-cache").toFile()
        val left = listOf("call_mic_123.pcm", "call_remote_123.pcm", "call_456.m4a").map { File(dir, it).apply { writeText("x") } }
        val keep = listOf("image_1.jpg", "call_notes.txt", "call_mic_x.pcm").map { File(dir, it).apply { writeText("x") } }
        assertEquals(3, CallRecorder.sweepLeftovers(dir))
        assertTrue(left.none { it.exists() })
        assertTrue(keep.all { it.exists() })
    }
}

/** [FakeMedia] that counts start-up sweeps. */
class SweepingMedia : ke.co.bethanyhouse.neema.feature.calls.CallMedia {
    private val inner = FakeMedia()
    var sweeps = 0
    val peer get() = inner.peer
    override fun createPeer(config: ke.co.bethanyhouse.neema.core.model.IceConfig, onEvent: (PeerEvent) -> Unit) = inner.createPeer(config, onEvent)
    override fun startRecording(micMuted: Boolean) = inner.startRecording(micMuted)
    override fun sweepLeftovers() { sweeps++ }
}

/** The Calls console's UI state across process death, and the caller deep link on a stale log. */
@OptIn(ExperimentalCoroutinesApi::class)
class CallsConsoleLifecycleTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi()

    private fun fake() = FakeNeema.withFixtures().also(CallsFixtures::install)

    @Test fun missedFilterAndOpenCallerSurviveProcessDeath() {
        val a = CallsViewModel(dashboard(paparazzi.context, fake()))
        a.missedOnly.value = true
        a.select(a.calls.value!!.first { it.id == CallsFixtures.K1 })
        // The new process: the log hasn't loaded when the screen restores.
        val f = fake()
        f.on("GET", "/admin/calls", code = 500, body = "{}")
        val b = CallsViewModel(dashboard(paparazzi.context, f))
        paparazzi.processDeath(a, b)
        assertTrue(b.missedOnly.value)
        assertNull("waits for its row", b.selected.value)
        f.on("GET", "/admin/calls", body = CallsFixtures.calls)
        b.refresh()
        assertEquals("opened once the log is read", CallsFixtures.K1, b.selected.value?.id)
    }

    @Test fun aCallerLinkOnAStaleLogReadsItAgainBeforeSayingThereAreNoCalls() {
        val f = fake()
        val dash = dashboard(paparazzi.context, f)
        val toasts = ToastLog(dash)
        val vm = CallsViewModel(dash)
        // A new caller rang after the log was read: the missed-call alert names them.
        val fresh = CallsFixtures.row("5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b99", "wacid.NEW", "254711000999", "Mama Wanjiku", "inbound", "missed",
            null, null, CallsFixtures.pyIso(1), null, "none", false)
        f.on("GET", "/admin/calls", body = "[" + fresh + "," + CallsFixtures.calls.removePrefix("["))
        dash.callsFocusKey.value = "254711000999"
        vm.consumeFocus("254711000999")
        assertEquals("wacid.NEW", vm.selected.value?.callId)
        assertTrue("no false 'no calls yet'", toasts.all.none { it.message.startsWith("No calls with this customer") })
        assertNull(dash.callsFocusKey.value)
        toasts.close()
    }

    @Test fun aCallerLinkWhenTheLogCantBeReadSaysNothingFalse() {
        val f = fake()
        val dash = dashboard(paparazzi.context, f)
        val toasts = ToastLog(dash)
        val vm = CallsViewModel(dash)
        f.on("GET", "/admin/calls", code = 503, body = "{}")
        dash.callsFocusKey.value = "254711000999"
        vm.consumeFocus("254711000999")
        assertNull(vm.selected.value)
        assertTrue(toasts.all.none { it.message.startsWith("No calls with this customer") })
        assertNull("consumed: the log's own error explains", dash.callsFocusKey.value)
        toasts.close()
    }

    @Test fun aCallerWithNoCallsStillGetsTheWebsWarningAfterAFreshRead() {
        val f = fake()
        val dash = dashboard(paparazzi.context, f)
        val toasts = ToastLog(dash)
        val vm = CallsViewModel(dash)
        val before = f.calls.count { it.method == "GET" && it.path == "/admin/calls" }
        dash.callsFocusKey.value = "254799999999"
        vm.consumeFocus("254799999999")
        assertEquals("read again first", before + 1, f.calls.count { it.method == "GET" && it.path == "/admin/calls" })
        assertTrue(toasts.all.any { it.message == "No calls with this customer yet — showing the full call log." })
        toasts.close()
    }
}
