import Foundation
import XCTest
@testable import NeemaCore

/// Round 9 core carry-overs: Coalescer, SingleFlight in core (and its cancel), grapheme initials (Android `CoreRound9Test`).
final class CoreRound9Tests: XCTestCase {

    // ── Coalescer ─────────────────────────────────────────────────────────

    func testKicksDuringASlowRunLeaveExactlyOneRunBehindIt() async {
        let clock = VirtualClock()
        let runs = Watched<Int>(0)
        let gate = AsyncLock()
        await gate.acquire()
        let c = Coalescer(windowMs: 800, sleep: clock.sleeper) {
            runs.value += 1
            if runs.value == 1 { await gate.withLock {} }
        }
        c.kick()
        await clock.advance(by: 801)
        _ = await eventually { runs.value == 1 }
        XCTAssertEqual(1, runs.value)
        // The first run is stuck on a slow network; kicks keep arriving for 10 s.
        for _ in 0..<50 { c.kick(); await clock.advance(by: 200) }
        gate.release()
        await clock.advance(by: 60_000)
        await settle()
        XCTAssertEqual(2, runs.value, "one run for the whole backlog, not one per window")
        // And the Coalescer is ready for the next burst.
        c.kick()
        await clock.advance(by: 801)
        _ = await eventually { runs.value == 3 }
        XCTAssertEqual(3, runs.value)
    }

    func testABurstBeforeTheWindowEndsIsOneRun() async {
        let clock = VirtualClock()
        let runs = Watched<Int>(0)
        let c = Coalescer(windowMs: 800, sleep: clock.sleeper) { runs.value += 1 }
        for _ in 0..<20 { c.kick() }
        await clock.advance(by: 801)
        _ = await eventually { runs.value == 1 }
        XCTAssertEqual(1, runs.value)
    }

    func testAFailingRunDoesNotWedgeIt() async {
        let clock = VirtualClock()
        let runs = Watched<Int>(0)
        let c = Coalescer(windowMs: 100, sleep: clock.sleeper) {
            runs.value += 1
            throw PlainError("offline")
        }
        c.kick(); await clock.advance(by: 101)
        _ = await eventually { runs.value == 1 }
        c.kick(); await clock.advance(by: 101)
        _ = await eventually { runs.value == 2 }
        XCTAssertEqual(2, runs.value)
    }

    // ── SingleFlight lives in core (the feature/orders forward was deleted in round 10) ─

    func testSingleFlightIsReachableFromCore() async throws {
        let n = Watched<Int>(0)
        let a: SingleFlight<Int> = SingleFlight { n.value += 1; return n.value }
        let got = try await a.run()
        XCTAssertEqual(1, got)
    }

    // ── Initials by grapheme ──────────────────────────────────────────────

    func testInitialsKeepEmojiWhole() {
        XCTAssertEqual("M🌸", Fmt.initials("Mama 🌸 Njeri"))
        XCTAssertEqual("🌸M", Fmt.initials("🌸 Mama"))
        XCTAssertEqual("👩🏽‍💻D", Fmt.initials("👩🏽‍💻 Dev"))
        XCTAssertEqual("❤️J", Fmt.initials("❤️ Jane"))
        XCTAssertEqual("🇰🇪K", Fmt.initials("🇰🇪 Kenya"))
    }

    func testInitialsKeepCombiningMarksAndStayAsBefore() {
        XCTAssertEqual("E\u{301}N", Fmt.initials("e\u{301}lodie njeri"), "the accent stays on its letter")
        XCTAssertEqual("FP", Fmt.initials("Fr. Peter Kamau"))
        XCTAssertEqual("MM", Fmt.initials("moses mwicigi"))
        XCTAssertEqual("G", Fmt.initials("Grace"))
        XCTAssertEqual("?", Fmt.initials(nil))
        XCTAssertEqual("?", Fmt.initials("  "))
    }

    // ── SingleFlight.cancel(): sign-out abandons the read on the wire ──

    func testCancelAbandonsTheReadAndTheQueuedOneThenStartsAfresh() async throws {
        let started = Watched<Int>(0)
        let gate = AsyncLock()
        await gate.acquire()
        let flight = SingleFlight<Int> {
            started.value += 1
            if started.value == 1 {
                await gate.withLock {}
                try Task.checkCancellation()
            }
            return started.value
        }
        let first = Task { try await flight.run() }
        _ = await eventually { started.value == 1 }
        let second = Task { try await flight.run() }
        await settle()
        XCTAssertTrue(flight.inFlight)
        flight.cancel()
        XCTAssertFalse(flight.inFlight)
        gate.release()
        do { _ = try await first.value; XCTFail("the read on the wire was abandoned") } catch { XCTAssertTrue(error is CancellationError, "\(error)") }
        do { _ = try await second.value; XCTFail("the queued read was abandoned") } catch { XCTAssertTrue(error is CancellationError, "\(error)") }
        XCTAssertEqual(1, started.value, "the queued read never started")
        let fresh = try await flight.run()
        XCTAssertEqual(2, fresh)
    }
}
