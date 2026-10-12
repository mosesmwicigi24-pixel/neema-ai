import Foundation
import XCTest
@testable import NeemaCore

/// "The app closes when I call a customer on WhatsApp": every step of placing
/// and answering a call — on WhatsApp and on Messenger — is made to fail with
/// the kind of error a device's audio stack or WebRTC's native side throws.
/// The call must end on the card, the audio and peer must be let go, nothing
/// may escape to the caller's task, and the very next call must go through.
/// Android `calls/CallResilienceTest.kt`.
@MainActor
final class CallResilienceTests: XCTestCase {
    /// Where a fault can be injected.
    enum Step: CaseIterable { case createPeer, addMic, createOffer, createAnswer, setLocal, setRemote, startRecording }

    /// A native-side failure, as the audio HAL or WebRTC's native side throws it.
    nonisolated static func nativeBoom(_ step: Step) -> Error { DeviceCallError("native failure at \(step)") }

    /// `FakeMedia` with one-shot faults: each armed step throws once, then works again.
    final class FlakyMedia: CallMedia, @unchecked Sendable {
        let inner = FakeMedia()
        var faults: [Step: Error] = [:]
        var peers: [FlakyPeer] = []
        var peer: FlakyPeer { peers.last! }
        func arm(_ step: Step, _ e: Error? = nil) { faults[step] = e ?? CallResilienceTests.nativeBoom(step) }
        func fire(_ step: Step) throws { if let e = faults.removeValue(forKey: step) { throw e } }
        func createPeer(config: IceConfig, onEvent: @escaping @Sendable (PeerEvent) -> Void) throws -> CallPeer {
            try fire(.createPeer)
            let p = FlakyPeer(inner: try inner.createPeer(config: config, onEvent: onEvent) as! FakePeer, media: self)
            peers.append(p)
            return p
        }
        func startRecording(micMuted: Bool) throws -> CallRecording? { try fire(.startRecording); return try inner.startRecording(micMuted: micMuted) }
    }

    final class FlakyPeer: CallPeer, @unchecked Sendable {
        let inner: FakePeer
        private let m: FlakyMedia
        init(inner: FakePeer, media: FlakyMedia) { self.inner = inner; self.m = media }
        func addMic(enabled: Bool) throws { try m.fire(.addMic); try inner.addMic(enabled: enabled) }
        var hasMic: Bool { inner.hasMic }
        func setMicEnabled(_ enabled: Bool) { inner.setMicEnabled(enabled) }
        func createOffer() async throws -> String { try m.fire(.createOffer); return try await inner.createOffer() }
        func createAnswer() async throws -> String { try m.fire(.createAnswer); return try await inner.createAnswer() }
        func setLocal(_ type: SdpType, _ sdp: String) async throws { try m.fire(.setLocal); try await inner.setLocal(type, sdp) }
        func setRemote(_ type: SdpType, _ sdp: String) async throws { try m.fire(.setRemote); try await inner.setRemote(type, sdp) }
        func awaitGathering() async throws { try await inner.awaitGathering() }
        var localSdp: String? { inner.localSdp }
        func close() { inner.close() }
    }

    /// `FakeCallApi` whose connect can throw any error (a broken transport, not a server answer).
    final class ThrowingApi: CallApi, @unchecked Sendable {
        let inner: FakeCallApi
        var connectFault: Error?
        init(_ inner: FakeCallApi) { self.inner = inner }
        func list() async throws -> [Call] { try await inner.list() }
        func get(_ callId: String) async throws -> Call { try await inner.get(callId) }
        func iceConfig() async throws -> IceConfig { try await inner.iceConfig() }
        func offer(_ callId: String) async throws -> CallOffer { try await inner.offer(callId) }
        func answer(_ callId: String, sdp: String) async throws -> CallSdpResponse { try await inner.answer(callId, sdp: sdp) }
        func terminate(_ callId: String) async throws { try await inner.terminate(callId) }
        func callback(_ callId: String) async throws { try await inner.callback(callId) }
        func connect(to: String, sdp: String, name: String?) async throws -> String {
            if let f = connectFault { connectFault = nil; throw f }
            return try await inner.connect(to: to, sdp: sdp, name: name)
        }
        func permission(_ waId: String) async throws -> CallPermission { try await inner.permission(waId) }
        func channels() async throws -> CallChannels { try await inner.channels() }
        func connectMessenger(psid: String, sdp: String, name: String?) async throws -> CallSdpResponse { try await inner.connectMessenger(psid: psid, sdp: sdp, name: name) }
        func messengerPermission(_ psid: String) async throws -> CallPermission { try await inner.messengerPermission(psid) }
        func requestMessengerPermission(_ psid: String) async throws -> PermissionRequestResponse { try await inner.requestMessengerPermission(psid) }
        func requestPermission(to: String, name: String?) async throws -> PermissionRequestResponse { try await inner.requestPermission(to: to, name: name) }
        func uploadRecording(_ callId: String, file: UploadFile) async throws { try await inner.uploadRecording(callId, file: file) }
    }

    private var rigs: [CallRig] = []
    private var throwing: ThrowingApi!
    private var media: FlakyMedia!

    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
    }

    private func rig() async -> CallRig {
        let fake = FakeCallApi()
        let t = ThrowingApi(fake)
        throwing = t
        media = FlakyMedia()
        let r = CallRig(api: fake, wrap: { _ in t }, media: media)
        rigs.append(r)
        await r.settle()
        return r
    }
    /// Let any wrap-up close itself, back to Idle.
    private func drainWrap(_ r: CallRig) async { await r.advance(60_000) }

    /// Place a call and return what initiateCall answered (it must never throw).
    private func place(_ r: CallRig, _ channel: String) async -> Result<Void, Error> {
        let to = channel == CallWords.MESSENGER ? "7788990011" : "+254712345678"
        let t = Task { await r.calls.initiateCall(to: to, name: "Fr. Peter Kamau", conversationId: "conv-1", channel: channel) }
        await r.settle()
        return await t.value
    }

    /// A clean call on `channel`, all the way to InCall, then hung up.
    private func cleanCall(_ r: CallRig, _ channel: String) async {
        let p = await place(r, channel)
        XCTAssertTrue(p.isSuccess, "the next call goes through")
        if channel == CallWords.WHATSAPP {
            r.frame(("type", "outbound_answer"), ("call_id", r.api.connectId), ("sdp", "v=0 their-answer"))
        } else {
            r.frame(("type", "call_answered"), ("call_id", r.api.messengerConnectId))
        }
        await r.settle()
        media.peer.inner.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertTrue(r.audio.inCall)
        r.calls.hangup(); await r.settle()
        await drainWrap(r)
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertFalse(r.audio.inCall)
    }

    private func assertFailedCleanly(_ r: CallRig, _ res: Result<Void, Error>, _ step: Step, line: UInt = #line) {
        let err = res.failure
        XCTAssertTrue(err is CallError, "\(step): initiateCall reports a failure", line: line)
        XCTAssertEqual((err as? CallError)?.shown, true, "\(step): the card already says it", line: line)
        XCTAssertEqual(r.state.phase, .ended, "\(step): ended on the card", line: line)
        XCTAssertTrue(r.state.outcome?.isFailed == true, "\(step): a failed call, not a crash (\(String(describing: r.state.outcome)))", line: line)
        XCTAssertFalse(r.audio.inCall, "\(step): the call audio is let go", line: line)
        XCTAssertFalse(r.audio.micService, "\(step): the mic service is let go", line: line)
        if let p = media.peers.last { XCTAssertTrue(p.inner.closed, "\(step): the peer is closed", line: line) }
    }

    // ── Cycle 6: outgoing WhatsApp, a native failure at every step ───────
    func testWhatsappOutboundSurvivesANativeFailureAtEveryStep() async {
        let r = await rig()
        for step in [Step.createPeer, .addMic, .createOffer, .setLocal] {
            media.arm(step)
            let res = await place(r, CallWords.WHATSAPP)
            assertFailedCleanly(r, res, step)
            XCTAssertEqual(res.failureMessage, CallManager.DEVICE_CALL_FAILED)
            await drainWrap(r)
            await cleanCall(r, CallWords.WHATSAPP)
        }
    }

    func testWhatsappOutboundSurvivesAnErrorFromTheServerCall() async {
        let r = await rig()
        // A device error out of the HTTP layer (a broken TLS provider).
        throwing.connectFault = DeviceCallError("response body")
        let res = await place(r, CallWords.WHATSAPP)
        assertFailedCleanly(r, res, .setLocal)
        XCTAssertEqual(res.failureMessage, CallManager.DEVICE_CALL_FAILED)
        await drainWrap(r)
        // …and a library that fails to initialise the first time WebRTC is touched.
        media.arm(.createPeer, DeviceCallError("webrtc init"))
        let res2 = await place(r, CallWords.WHATSAPP)
        assertFailedCleanly(r, res2, .createPeer)
        await drainWrap(r)
        await cleanCall(r, CallWords.WHATSAPP)
    }

    func testWhatsappAnswerThatThePeerRefusesEndsTheCallNotTheApp() async {
        let r = await rig()
        let p = await place(r, CallWords.WHATSAPP)
        XCTAssertTrue(p.isSuccess)
        media.arm(.setRemote)
        r.frame(("type", "outbound_answer"), ("call_id", r.api.connectId), ("sdp", "v=0 their-answer"))
        await drainWrap(r)
        XCTAssertFalse(r.audio.inCall)
        XCTAssertTrue(r.state.phase == .idle || r.state.phase == .ended)
        await drainWrap(r)
        await cleanCall(r, CallWords.WHATSAPP)
    }

    func testTenCallsInARowWithFailuresBetweenThem() async {
        let r = await rig()
        let steps = [Step.createPeer, .addMic, .createOffer, .setLocal]
        for i in 0..<10 {
            let channel = i % 2 == 0 ? CallWords.WHATSAPP : CallWords.MESSENGER
            media.arm(steps[i % steps.count])
            let res = await place(r, channel)
            assertFailedCleanly(r, res, steps[i % steps.count])
            await drainWrap(r)
            await cleanCall(r, channel)
        }
        XCTAssertTrue(media.peers.allSatisfy { $0.inner.closed }, "every peer made was closed")
    }

    // ── Cycle 7: answering an incoming call, a native failure at every step ──
    func testIncomingAnswerSurvivesANativeFailureAtEveryStep() async {
        let r = await rig()
        var n = 0
        for step in [Step.createPeer, .addMic, .setRemote, .createAnswer, .setLocal] {
            let id = "wacid.in\(n)"; n += 1
            r.frame(("type", "incoming_call"), ("call_id", id), ("from", "254712345678"), ("name", "Fr. Peter Kamau"))
            XCTAssertEqual(r.state.phase, .ringing, "\(step): rings")
            media.arm(step)
            r.calls.answer(); await r.settle()
            await drainWrap(r)
            XCTAssertFalse(r.audio.inCall, "\(step): the call audio is let go")
            XCTAssertFalse(r.audio.micService, "\(step): the mic service is let go")
            if let p = media.peers.last { XCTAssertTrue(p.inner.closed, "\(step): the peer is closed") }
            XCTAssertEqual(r.state.phase, .ended, "\(step): ended on the card")
            r.calls.dismiss(); await r.settle()
            XCTAssertEqual(r.state.phase, .idle, "\(step): back to idle")
        }
        // …and the next incoming call is answered and connects.
        r.frame(("type", "incoming_call"), ("call_id", "wacid.ok"), ("from", "254712345678"), ("name", "Fr. Peter Kamau"))
        r.calls.answer(); await r.settle()
        media.peer.inner.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
    }

    func testIncomingMessengerAnswerSurvivesANativeFailure() async {
        let r = await rig()
        r.api.messengerCalls.insert("c_msg.in1")
        r.frame(("type", "incoming_call"), ("call_id", "c_msg.in1"), ("from", "7788990011"), ("name", "Grace"), ("channel", CallWords.MESSENGER))
        media.arm(.createOffer)
        r.calls.answer(); await r.settle()
        await drainWrap(r)
        XCTAssertFalse(r.audio.inCall)
        XCTAssertEqual(r.state.phase, .ended)
        r.calls.dismiss(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
        r.api.messengerCalls.insert("c_msg.in2")
        r.frame(("type", "incoming_call"), ("call_id", "c_msg.in2"), ("from", "7788990011"), ("name", "Grace"), ("channel", CallWords.MESSENGER))
        r.calls.answer(); await r.settle()
        media.peer.inner.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
    }

    // ── Cycle 8: outgoing Messenger ──────────────────────────────────────
    func testMessengerOutboundHappyPath() async {
        let r = await rig()
        await cleanCall(r, CallWords.MESSENGER)
        XCTAssertEqual(r.api.lastMessengerConnect?.psid, "7788990011")
    }

    func testMessengerOutboundSurvivesANativeFailureAtEveryStep() async {
        let r = await rig()
        for step in [Step.createPeer, .addMic, .createOffer, .setLocal] {
            media.arm(step)
            let res = await place(r, CallWords.MESSENGER)
            assertFailedCleanly(r, res, step)
            await drainWrap(r)
            await cleanCall(r, CallWords.MESSENGER)
        }
    }

    func testMessengerAnswerThePeerRefusesDoesNotCrash() async {
        let r = await rig()
        media.arm(.setRemote)
        let res = await place(r, CallWords.MESSENGER)
        // Meta's answer was refused inside placeMessenger (logged): the call is placed, the card carries on.
        XCTAssertTrue(res.isSuccess || res.failure is CallError)
        r.calls.hangup(); await r.settle(); await drainWrap(r)
        XCTAssertFalse(r.audio.inCall)
        await cleanCall(r, CallWords.MESSENGER)
    }

    // ── Cycle 9: the agent's own taps ────────────────────────────────────
    func testDoubleTapIsAlreadyInACallNotACrash() async {
        let r = await rig()
        r.api.connectGate = Deferred<Void>()
        let a = Task { await r.calls.initiateCall(to: "254712345678", name: "Fr. Peter Kamau") }
        await r.settle()
        let b = Task { await r.calls.initiateCall(to: "254712345678", name: "Fr. Peter Kamau", channel: CallWords.MESSENGER) }
        await r.settle()
        let bv = await b.value
        XCTAssertEqual(bv.failureMessage, "Already in a call")
        r.api.connectGate!.complete(()); await r.settle()
        let av = await a.value
        XCTAssertTrue(av.isSuccess)
        XCTAssertEqual(media.peers.count, 1)
    }

    func testHangingUpWhilePlacingTerminatesAndTheNextCallWorks() async {
        let r = await rig()
        for channel in [CallWords.WHATSAPP, CallWords.MESSENGER] {
            r.api.connectGate = Deferred<Void>()
            let a = Task { await r.calls.initiateCall(to: channel == CallWords.MESSENGER ? "7788990011" : "254712345678", name: "Grace", channel: channel) }
            await r.settle()
            r.calls.hangup(); await r.settle()
            r.api.connectGate!.complete(()); await r.settle()
            let av = await a.value
            XCTAssertTrue(av.isSuccess, "\(channel): hung up before it was placed is not a failure")
            XCTAssertFalse(r.audio.inCall)
            r.api.connectGate = nil
            await drainWrap(r)
            await cleanCall(r, channel)
        }
    }

    func testMicDeniedOnEitherChannelSaysSoAndLetsGo() async {
        let r = await rig()
        for channel in [CallWords.WHATSAPP, CallWords.MESSENGER] {
            r.mic = false
            let res = Task { await r.calls.initiateCall(to: channel == CallWords.MESSENGER ? "7788990011" : "254712345678", name: "Grace", channel: channel) }
            await r.settle()
            r.calls.onMicResult(false); await r.settle()
            let rv = await res.value
            XCTAssertTrue(rv.isFailure)
            XCTAssertEqual(r.state.outcome, .micBlocked)
            XCTAssertFalse(r.audio.inCall)
            await drainWrap(r)
            r.mic = true
            await cleanCall(r, channel)
        }
    }

    func testRtcGuardSwallowsWhatANativeCallbackThrows() {
        var after = false
        rtcGuard("onIceCandidate") { throw CallResilienceTests.nativeBoom(.setLocal) }
        rtcGuard("onTrack") { throw PlainError("MediaStreamTrack has been disposed.") }
        rtcGuard("onConnectionChange") { after = true }
        XCTAssertTrue(after, "the guard runs the callback")
    }
}
