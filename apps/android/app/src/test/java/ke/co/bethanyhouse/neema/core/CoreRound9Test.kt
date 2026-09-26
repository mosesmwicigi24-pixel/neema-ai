package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.calls.FakeAudio
import ke.co.bethanyhouse.neema.calls.FakeCallApi
import ke.co.bethanyhouse.neema.calls.FakeMedia
import ke.co.bethanyhouse.neema.calls.FakeRinger
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.util.Coalescer
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.util.SingleFlight
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Round 9 core carry-overs: Coalescer, SingleFlight in core, grapheme initials, the hang-up job. */
@OptIn(ExperimentalCoroutinesApi::class)
class CoreRound9Test {

    // ── Coalescer ─────────────────────────────────────────────────────────

    @Test fun kicksDuringASlowRunLeaveExactlyOneRunBehindIt() = runTest {
        var runs = 0
        val gate = CompletableDeferred<Unit>()
        val c = Coalescer(backgroundScope, 800) { runs++; if (runs == 1) gate.await() }
        c.kick()
        advanceTimeBy(801); runCurrent()
        assertEquals(1, runs)
        // The first run is stuck on a slow network; kicks keep arriving for 10 s.
        repeat(50) { c.kick(); advanceTimeBy(200); runCurrent() }
        gate.complete(Unit)
        advanceTimeBy(60_000); runCurrent()
        assertEquals("one run for the whole backlog, not one per window", 2, runs)
        // And the Coalescer is ready for the next burst.
        c.kick(); advanceTimeBy(801); runCurrent()
        assertEquals(3, runs)
    }

    @Test fun aBurstBeforeTheWindowEndsIsOneRun() = runTest {
        var runs = 0
        val c = Coalescer(backgroundScope, 800) { runs++ }
        repeat(20) { c.kick() }
        advanceTimeBy(801); runCurrent()
        assertEquals(1, runs)
    }

    @Test fun aFailingRunDoesNotWedgeIt() = runTest {
        var runs = 0
        val c = Coalescer(backgroundScope, 100) { runs++; error("offline") }
        c.kick(); advanceTimeBy(101); runCurrent()
        c.kick(); advanceTimeBy(101); runCurrent()
        assertEquals(2, runs)
    }

    // ── SingleFlight now lives in core (feature/orders keeps a typealias) ─

    @Test fun singleFlightIsReachableFromBothPackages() = runTest {
        var n = 0
        val a: SingleFlight<Int> = ke.co.bethanyhouse.neema.feature.orders.SingleFlight(backgroundScope) { ++n }
        assertEquals(1, a.run())
    }

    // ── Initials by grapheme ──────────────────────────────────────────────

    @Test fun initialsKeepEmojiWhole() {
        assertEquals("M🌸", Fmt.initials("Mama 🌸 Njeri"))
        assertEquals("🌸M", Fmt.initials("🌸 Mama"))
        assertEquals("👩🏽‍💻D", Fmt.initials("👩🏽‍💻 Dev"))
        assertEquals("❤️J", Fmt.initials("❤️ Jane"))
        assertEquals("🇰🇪K", Fmt.initials("🇰🇪 Kenya"))
    }

    @Test fun initialsKeepCombiningMarksAndStayAsBefore() {
        assertEquals("the accent stays on its letter", "E\u0301N", Fmt.initials("e\u0301lodie njeri"))
        assertEquals("FP", Fmt.initials("Fr. Peter Kamau"))
        assertEquals("MM", Fmt.initials("moses mwicigi"))
        assertEquals("G", Fmt.initials("Grace"))
        assertEquals("?", Fmt.initials(null))
        assertEquals("?", Fmt.initials("  "))
    }

    // ── CallManager.hangup(): a job sign-out can wait on ──────────────────

    @Test fun hangUpsJobEndsOnlyOnceTheServerHasBeenTold() = runTest {
        val api = FakeCallApi()
        val frames = MutableSharedFlow<JsonObject>(extraBufferCapacity = 8)
        val d = StandardTestDispatcher(testScheduler)
        val calls = CallManager(
            api = api, events = frames, connected = MutableStateFlow(true), scope = backgroundScope,
            foreground = MutableStateFlow(true), signedInFn = { true }, media = FakeMedia(), ringer = FakeRinger(), audio = FakeAudio(),
            micGranted = { true }, main = d, io = d, now = { testScheduler.currentTime },
        ).also { it.start() }
        runCurrent()
        frames.tryEmit(JsonObject(mapOf("type" to JsonPrimitive("incoming_call"), "call_id" to JsonPrimitive("wacid.7"), "from" to JsonPrimitive("254712345678"))))
        runCurrent()
        assertEquals(CallPhase.Ringing, calls.state.value.phase)
        // The first terminate meets a dead network; the retry (2 s later) gets through.
        api.terminateErrors += ApiException(0, "POST", "/admin/calls/wacid.7/terminate", "")
        val job = calls.hangup()
        runCurrent()
        assertEquals("the card ends at once", CallPhase.Ended, calls.state.value.phase)
        assertFalse("but the job waits for the server", job.isCompleted)
        advanceTimeBy(2_001); runCurrent()
        assertEquals(2, api.log.count { it == "terminate wacid.7" })
        assertTrue(job.isCompleted)
        // Idle: nothing to end, the job is done at once.
        val idle = calls.hangup()
        advanceTimeBy(5_000); runCurrent()
        assertTrue(idle.isCompleted)
    }
}
