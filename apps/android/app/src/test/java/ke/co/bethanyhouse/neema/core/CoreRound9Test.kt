package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.util.Coalescer
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.util.SingleFlight
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Round 9 core carry-overs: Coalescer, SingleFlight in core (and its cancel), grapheme initials. */
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

    // ── SingleFlight lives in core (the feature/orders forward was deleted in round 10) ─

    @Test fun singleFlightIsReachableFromCore() = runTest {
        var n = 0
        val a: SingleFlight<Int> = SingleFlight(backgroundScope) { ++n }
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

    // ── SingleFlight.cancel(): sign-out abandons the read on the wire ──

    @Test fun cancelAbandonsTheReadAndTheQueuedOneThenStartsAfresh() = runTest {
        var started = 0
        val gate = CompletableDeferred<Int>()
        val flight = SingleFlight(backgroundScope) { started++; if (started == 1) gate.await() else started }
        val first = async { runCatching { flight.run() } }
        val second = async { runCatching { flight.run() } }
        runCurrent()
        assertTrue(flight.inFlight)
        flight.cancel()
        runCurrent()
        assertFalse(flight.inFlight)
        assertTrue(first.await().exceptionOrNull() is CancellationException)
        assertTrue(second.await().exceptionOrNull() is CancellationException)
        assertEquals("the queued read never started", 1, started)
        assertEquals(2, flight.run())
    }
}
