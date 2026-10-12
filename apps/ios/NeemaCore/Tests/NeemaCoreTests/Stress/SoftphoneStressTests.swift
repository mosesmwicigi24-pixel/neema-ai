import XCTest
@testable import NeemaCore

/// Round 8 (Android `SoftphoneStressTest`) — the softphone under socket
/// bursts, and every media resource released on every way a call ends:
/// hang-up, decline, a failed answer, the media dropping, the caller giving
/// up, and signing out mid-call.
@MainActor
final class SoftphoneStressTests: XCTestCase {
    private var rigs: [CallRig] = []

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs = []
        AppClock.reset()
    }

    private func rig(api: FakeCallApi = FakeCallApi(), wrap: ((FakeCallApi) -> CallApi)? = nil) async -> CallRig {
        let r = CallRig(api: api, wrap: wrap)
        rigs.append(r)
        await r.settle()
        return r
    }

    /// Nothing of a call is left running: no peer open, no recording, no ring, no call audio.
    private func assertReleased(_ r: CallRig, _ why: String, file: StaticString = #filePath, line: UInt = #line) async {
        await r.settle()
        XCTAssertTrue(r.media.peers.allSatisfy { $0.closed }, "\(why): every peer closed", file: file, line: line)
        XCTAssertTrue(r.media.recordings.allSatisfy { $0.stopped }, "\(why): every recording stopped", file: file, line: line)
        XCTAssertFalse(r.ringer.ringing, "\(why): not ringing", file: file, line: line)
        XCTAssertFalse(r.ringer.showing, "\(why): no call notification", file: file, line: line)
        XCTAssertFalse(r.audio.inCall, "\(why): call audio left", file: file, line: line)
        XCTAssertFalse(r.audio.micService, "\(why): mic service down", file: file, line: line)
    }

    private func answerAndConnect(_ r: CallRig, _ id: String = "wacid.1") async {
        let recordings = r.media.recordings.count
        r.ring(id)
        await r.settle()
        r.calls.answer()
        await r.settle()
        r.media.peer.onEvent(.connected)
        await r.settle()
        XCTAssertEqual(.inCall, r.state.phase)
        XCTAssertEqual(recordings + 1, r.media.recordings.count, "recording while live")
    }

    func testABurstOfTwoHundredFramesRingsOnceAndEndsCleanly() async {
        let r = await rig()
        for _ in 0..<200 { r.frame(("type", "incoming_call"), ("call_id", "wacid.1"), ("from", "254712345678")) }
        for i in 0..<200 { r.frame(("type", "incoming_call"), ("call_id", "wacid.other\(i)"), ("from", "2547000\(i)")) }
        await r.settle()
        XCTAssertEqual(.ringing, r.state.phase)
        XCTAssertEqual("wacid.1", r.state.callId)
        XCTAssertEqual(1, r.ringer.ringStarts, "rang once")
        r.frame(("type", "call_ended"), ("call_id", "wacid.1"))
        await r.settle()
        XCTAssertEqual(.ended, r.state.phase)
        await assertReleased(r, "call_ended")
    }

    func testRememberedEndedCallsStayBoundedOverALongShift() async {
        let r = await rig()
        for i in 0..<1_000 {
            r.frame(("type", "call_ended"), ("call_id", "wacid.done\(i)"))
            if i % 100 == 0 { await r.settle() }
        }
        await r.settle()
        XCTAssertLessThanOrEqual(r.calls.endedCount, CallManager.ENDED_MAX, "remembered \(r.calls.endedCount) ended calls")
        // The newest are the ones kept: a late ring for one of them is still refused.
        r.frame(("type", "incoming_call"), ("call_id", "wacid.done999"), ("from", "254700000000"))
        await r.settle()
        XCTAssertEqual(.idle, r.state.phase)
    }

    /// A `CallApi` whose list() hangs until the test lets it through, counting how many are on the wire at once.
    private final class SlowList: CallApi, @unchecked Sendable {
        let inner: FakeCallApi
        let gate = Deferred<Void>()
        private let lock = NSLock()
        private var _inFlight = 0
        private(set) var maxInFlight = 0
        private(set) var lists = 0
        init(_ inner: FakeCallApi) { self.inner = inner }
        func list() async throws -> [Call] {
            lock.sync { lists += 1; _inFlight += 1; maxInFlight = max(maxInFlight, _inFlight) }
            defer { lock.sync { _inFlight -= 1 } }
            try await gate.value()
            return []
        }
        func get(_ callId: String) async throws -> Call { try await inner.get(callId) }
        func iceConfig() async throws -> IceConfig { try await inner.iceConfig() }
        func offer(_ callId: String) async throws -> CallOffer { try await inner.offer(callId) }
        func answer(_ callId: String, sdp: String) async throws -> CallSdpResponse { try await inner.answer(callId, sdp: sdp) }
        func terminate(_ callId: String) async throws { try await inner.terminate(callId) }
        func callback(_ callId: String) async throws { try await inner.callback(callId) }
        func connect(to: String, sdp: String, name: String?) async throws -> String { try await inner.connect(to: to, sdp: sdp, name: name) }
        func permission(_ waId: String) async throws -> CallPermission { try await inner.permission(waId) }
        func channels() async throws -> CallChannels { try await inner.channels() }
        func connectMessenger(psid: String, sdp: String, name: String?) async throws -> CallSdpResponse { try await inner.connectMessenger(psid: psid, sdp: sdp, name: name) }
        func messengerPermission(_ psid: String) async throws -> CallPermission { try await inner.messengerPermission(psid) }
        func requestMessengerPermission(_ psid: String) async throws -> PermissionRequestResponse { try await inner.requestMessengerPermission(psid) }
        func requestPermission(to: String, name: String?) async throws -> PermissionRequestResponse { try await inner.requestPermission(to: to, name: name) }
        func uploadRecording(_ callId: String, file: UploadFile) async throws { try await inner.uploadRecording(callId, file: file) }
    }

    func testPollsNeverOverlapOnASlowNetwork() async {
        var slow: SlowList!
        let r = await rig(wrap: { inner in slow = SlowList(inner); return slow })
        // The 12 s tick, a reconnect and a return to the app all while the first poll hangs.
        await r.advance(CallManager.IDLE_POLL_MS + 1)
        r.connected.value = false; await r.settle(); r.connected.value = true; await r.settle()
        r.foreground.value = false; await r.settle(); r.foreground.value = true; await r.settle()
        let calls = r.calls
        Task { await calls.pollOnce() }
        await r.settle()
        XCTAssertEqual(1, slow.maxInFlight, "only one poll on the wire")
        _ = slow.gate.complete(())
        await r.settle()
        XCTAssertEqual(1, slow.maxInFlight)
        XCTAssertLessThanOrEqual(slow.lists, 2, "the piled-up asks are one more poll, not four (\(slow.lists))")
    }

    // ── Every way a call ends releases the peer, the recording, the ring and the audio ──

    func testHangUpReleasesEverything() async {
        let r = await rig()
        await answerAndConnect(r)
        r.calls.hangup()
        await assertReleased(r, "hang-up")
    }

    func testDeclineReleasesEverything() async {
        let r = await rig()
        r.ring()
        await r.settle()
        XCTAssertTrue(r.ringer.ringing)
        r.calls.hangup()   // the card's Decline
        await assertReleased(r, "decline")
    }

    func testAFailedAnswerReleasesEverything() async {
        let r = await rig()
        r.api.answerError = apiError(500, "POST", "/admin/calls/wacid.1/answer")
        r.ring()
        await r.settle()
        r.calls.answer()
        await r.settle()
        await r.advance(5_000)
        XCTAssertTrue(r.state.phase == .ended || r.state.phase == .idle, "\(r.state.phase)")
        await assertReleased(r, "answer failed")
    }

    func testTheMediaDroppingReleasesEverything() async {
        let r = await rig()
        await answerAndConnect(r)
        r.media.peer.onEvent(.ended)
        await assertReleased(r, "peer failed")
    }

    func testANetworkBlipThatNeverRecoversReleasesEverything() async {
        let r = await rig()
        await answerAndConnect(r)
        r.media.peer.onEvent(.interrupted)
        await r.settle()
        await r.advance(CallManager.ICE_GRACE_MS + 1)
        await assertReleased(r, "ICE never recovered")
    }

    func testTheCallerGivingUpWhileRingingReleasesEverything() async {
        let r = await rig()
        r.ring()
        await r.settle()
        await r.advance(CallManager.RING_TIMEOUT_MS + 1)
        XCTAssertEqual(.ended, r.state.phase)
        await assertReleased(r, "ring timeout")
    }

    /// `AppModel.logout()` hangs the call up: nothing may outlive the session.
    func testSigningOutMidCallReleasesEverything() async {
        let r = await rig()
        await answerAndConnect(r)
        r.calls.hangup()   // what logout() calls
        await r.advance(8_001)
        XCTAssertEqual(.idle, r.state.phase)
        await assertReleased(r, "sign-out")
        XCTAssertEqual(["wacid.1"], r.api.uploads.map { $0.callId }, "the recording still reached the server")
    }

    func testTenCallsInARowLeaveNothingBehind() async {
        let r = await rig()
        for i in 0..<10 {
            await answerAndConnect(r, "wacid.row\(i)")
            r.calls.hangup()
            await r.settle()
            await r.advance(8_100)
            XCTAssertEqual(.idle, r.state.phase, "call \(i)")
        }
        await assertReleased(r, "ten calls")
        XCTAssertEqual(10, r.media.peers.count)
        XCTAssertEqual(10, r.media.recordings.count)
    }
}
