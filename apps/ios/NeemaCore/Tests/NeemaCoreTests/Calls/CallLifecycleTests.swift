import Foundation
import XCTest
@testable import NeemaCore

/// The softphone through what a phone does to an app: a main thread held
/// back while the screen is off (the timer must still read the true length),
/// a call that ends while the app is in the background, sign-out in the
/// middle of a call, and a process killed mid-call (its raw audio swept, its
/// finished recordings still uploaded by the next process).
/// Android `calls/CallLifecycleTest.kt` (the console's lifecycle tests live
/// with the calls console; the recorder's own sweep is the platform layer's).
@MainActor
final class CallLifecycleTests: XCTestCase {
    private var rigs: [CallRig] = []

    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
    }

    private func rig(outboxDir: URL? = nil) async -> CallRig {
        let r = CallRig(outboxDir: outboxDir)
        rigs.append(r)
        await r.settle()
        return r
    }
    private func live(_ r: CallRig) async -> FakePeer {
        r.ring(); r.calls.answer(); await r.settle(); r.media.peer.onEvent(.connected); await r.settle()
        return r.media.peer
    }

    // ── The timer ────────────────────────────────────────────────────────
    func testTheTimerReadsTheClockNotACountOfTicks() async {
        let r = await rig()
        _ = await live(r)
        await r.advance(5_001)
        XCTAssertEqual(r.state.seconds, 5)
        // The screen goes off and the main thread sleeps for a minute: no tick runs.
        r.slept += 60_000
        await r.advance(1_000)
        XCTAssertEqual(r.state.seconds, 66, "the first tick after waking reads the true length")
    }

    func testBackOnScreenTheTimerIsTrueAtOnce() async {
        let r = await rig()
        _ = await live(r)
        await r.advance(2_001)
        r.foreground.value = false; await r.settle()
        r.slept += 90_000
        r.foreground.value = true; await r.settle()
        XCTAssertEqual(r.state.seconds, 92)
    }

    func testTheTimerKeepsGoingThroughAReconnectAndStartsAfreshNextCall() async {
        let r = await rig()
        let p = await live(r)
        await r.advance(3_001)
        p.onEvent(.interrupted); await r.settle()
        await r.advance(2_000)
        p.onEvent(.connected); await r.settle()
        await r.advance(1_000)
        XCTAssertEqual(r.state.seconds, 6)
        r.calls.hangup(); await r.settle()
        XCTAssertNil(r.calls.liveSinceForTest)
        await r.advance(1_500)
        await r.advance(15_000)
        _ = await live(r)
        await r.advance(1_001)
        XCTAssertEqual(r.state.seconds, 1, "a new call's timer starts from zero")
    }

    // ── Background ───────────────────────────────────────────────────────
    func testACallThatEndsInTheBackgroundIsOverWhenTheAgentComesBack() async {
        let r = await rig()
        _ = await live(r)
        r.foreground.value = false; await r.settle()
        r.frame(("type", "call_ended"), ("call_id", "wacid.1"))
        XCTAssertEqual(r.state.phase, .ended)
        await r.advance(1_100)
        r.foreground.value = true; await r.settle()
        XCTAssertFalse(r.state.live, "not a stale live card")
        XCTAssertFalse(r.audio.inCall)
    }

    func testARingThatStopsInTheBackgroundTakesItsNotificationWithIt() async {
        let r = await rig()
        r.foreground.value = false; await r.settle()
        r.ring()
        XCTAssertTrue(r.ringer.showing)
        r.frame(("type", "call_ended"), ("call_id", "wacid.1"))
        XCTAssertFalse(r.ringer.showing)
        XCTAssertFalse(r.ringer.ringing)
    }

    // ── Sign-out ─────────────────────────────────────────────────────────
    func testSignOutWaitsForTheTerminateBeforeTheSessionGoes() async {
        let r = await rig()
        _ = await live(r)
        let terminated = Ref<Bool?>(nil)
        let done = Task { await r.calls.endForSignOut(); terminated.value = r.api.log.contains("terminate wacid.1") }
        await r.settle()
        XCTAssertEqual(terminated.value, true, "the terminate went out before endForSignOut returned")
        _ = await done.value
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertNil(r.state.callId)
        XCTAssertFalse(r.audio.inCall)
    }

    func testSignOutGivesUpOnASlowTerminateAfterTheBound() async {
        let r = await rig()
        _ = await live(r)
        r.api.terminateGate = Deferred<Void>()   // the server never answers
        let t0 = r.clock.now
        let finished = Ref(false)
        let done = Task { await r.calls.endForSignOut(); finished.value = true }
        await r.advance(CallManager.SIGN_OUT_TERMINATE_MS - 1)
        XCTAssertFalse(finished.value, "waits for the server a while")
        await r.advance(2)
        XCTAssertTrue(finished.value, "…but sign-out is never held up for long")
        XCTAssertTrue(r.clock.now - t0 <= CallManager.SIGN_OUT_TERMINATE_MS + 1)
        XCTAssertEqual(r.state.phase, .idle)
        _ = await done.value
    }

    func testSignOutWhileRingingLetsTheCallRingOnForColleagues() async {
        let r = await rig()
        r.ring()
        await r.calls.endForSignOut(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertFalse(r.logged("terminate"), "not declined for everyone")
        XCTAssertFalse(r.ringer.ringing)
        XCTAssertFalse(r.ringer.showing)
        // And it doesn't ring again on this phone from a lagging poll.
        r.api.calls = [Call(id: "k", callId: "wacid.1", waId: "254712345678", direction: "inbound", status: "ringing", startedAt: r.at(0))]
        await r.calls.pollOnce(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testSignOutWithNoCallIsANoOp() async {
        let r = await rig()
        await r.calls.endForSignOut(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertFalse(r.logged("terminate"))
    }

    // ── Process death ────────────────────────────────────────────────────
    func testANewProcessSweepsRawAudioAndStillUploadsTheOutbox() async {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("rec-outbox-\(UUID().uuidString)")
        let first = await rig(outboxDir: dir)
        await eventually { first.media.sweeps == 1 }
        XCTAssertEqual(first.media.sweeps, 1, "swept once at start-up")
        first.api.uploadErrors.append(ApiError(status: 0, method: "POST", path: "/admin/calls/wacid.1/recording", body: "Failed to connect"))
        _ = await live(first)
        await first.advance(3_000)
        first.calls.hangup(); await first.settle()
        await eventually { first.count("recording") == 1 }
        XCTAssertEqual(first.outboxFiles.count, 1, "kept for later")

        // The process dies; a new one starts on the same files.
        first.stop()
        let second = await rig(outboxDir: dir)
        await eventually { second.api.uploads.count == 1 }
        XCTAssertEqual(second.api.uploads.map { $0.callId }, ["wacid.1"])
        XCTAssertEqual(second.outboxFiles.count, 0)
    }
}
