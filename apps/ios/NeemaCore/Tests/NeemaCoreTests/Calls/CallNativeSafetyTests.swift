import Foundation
import XCTest
@testable import NeemaCore

/// The call ends while WebRTC is still working on it - the agent taps End as
/// the offer is made, the customer hangs up as the agent answers, the answer
/// frame lands a beat after the call was torn down. On a phone, touching the
/// PeerConnection after close() is a native crash (use after dispose) that no
/// catch can stop: the app closes. Here the fake peer records every such use;
/// there must be none.
/// Android `calls/CallNativeSafetyTest.kt`. Its JVM-only parts (a device
/// audio stack that throws from `enter`, uncaught-exception handlers per
/// thread, `CrashVault.contained`) have no iOS counterpart: `CallAudio.enter`
/// cannot throw, and WebRTC callbacks are contained by `rtcGuard`.
@MainActor
final class CallNativeSafetyTests: XCTestCase {
    private var rigs: [CallRig] = []

    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
    }

    private func rig() async -> CallRig {
        let r = CallRig()
        rigs.append(r)
        await r.settle()
        return r
    }
    /// Android's `drain()`: a minute of virtual time, every queued hop run.
    private func drainRig(_ r: CallRig) async { await r.advance(60_000) }
    private func assertNoNativeUseAfterClose(_ r: CallRig, file: StaticString = #filePath, line: UInt = #line) {
        for (i, p) in r.media.peers.enumerated() {
            XCTAssertTrue(p.usedAfterClose.isEmpty, "peer \(i) used after close: \(p.usedAfterClose)", file: file, line: line)
        }
    }

    func testAnswerFrameLandingJustAsTheCallEndsNeverTouchesTheClosedPeer() async {
        let r = await rig()
        let placed = Task { await r.calls.initiateCall(to: "254712345678", name: "Fr. Peter Kamau") }
        await r.settle()
        let v = await placed.value
        XCTAssertTrue(v.isSuccess)
        // Their phone picks up as the agent taps End: the answer is applied a beat later.
        r.frame(("type", "outbound_answer"), ("call_id", r.api.connectId), ("sdp", "v=0 their-answer"))
        r.calls.hangup()
        await r.settle(); await drainRig(r)
        XCTAssertTrue(r.media.peer.closed)
        assertNoNativeUseAfterClose(r)
    }

    func testHangingUpWhileTheOfferIsMadeNeverUsesTheClosedPeer() async {
        let r = await rig()
        for channel in [CallWords.WHATSAPP, CallWords.MESSENGER] {
            let gate = Deferred<Void>()
            r.media.sdpGate = gate               // WebRTC takes its time over the offer...
            r.api.lastConnect = nil; r.api.lastMessengerConnect = nil
            let placed = Task { await r.calls.initiateCall(to: channel == CallWords.MESSENGER ? "7788990011" : "254712345678", name: "Grace", channel: channel) }
            await r.settle()
            XCTAssertEqual(["addMic(true)", "createOffer"], r.media.peer.ops)
            r.calls.hangup(); await r.settle()   // ...the agent taps End meanwhile
            gate.complete(()); await r.settle()  // ...and the offer comes back
            r.media.sdpGate = nil
            let v = await placed.value
            XCTAssertTrue(v.isSuccess)
            XCTAssertFalse(r.media.peer.ops.contains { $0.hasPrefix("setLocal") }, "\(channel): the offer isn't applied to a closed peer")
            if channel == CallWords.MESSENGER { XCTAssertNil(r.api.lastMessengerConnect, "\(channel): nothing was placed") }
            else { XCTAssertNil(r.api.lastConnect, "\(channel): nothing was placed") }
            await drainRig(r)
            assertNoNativeUseAfterClose(r)
        }
    }

    func testCallerHangingUpMidAnswerNeverUsesTheClosedPeer() async {
        let r = await rig()
        // WhatsApp: setRemote -> createAnswer -> setLocal, each a wait; Messenger: createOffer -> setLocal.
        var n = 0
        for messenger in [false, true] {
            for stepsBeforeEnd in 0...2 {
                let id = messenger ? "c_msg.in\(n)" : "wacid.in\(n)"
                n += 1
                if messenger { r.api.messengerCalls.insert(id) }
                if messenger {
                    r.frame(("type", "incoming_call"), ("call_id", id), ("from", "254712345678"), ("name", "Fr. Peter Kamau"), ("channel", CallWords.MESSENGER))
                } else {
                    r.frame(("type", "incoming_call"), ("call_id", id), ("from", "254712345678"), ("name", "Fr. Peter Kamau"))
                }
                await r.settle()
                XCTAssertEqual(CallPhase.ringing, r.state.phase)
                let gate = Deferred<Void>()
                r.media.sdpGate = gate
                r.calls.answer(); await r.settle()
                let p = r.media.peer
                r.media.sdpGate = nil
                // The caller hangs up somewhere inside the SDP steps.
                for _ in 0..<stepsBeforeEnd { gate.complete(()); await r.settle() }
                r.frame(("type", "call_ended"), ("call_id", id)); await r.settle()
                if !gate.isDone { gate.complete(()) }
                await r.settle(); await drainRig(r)
                XCTAssertTrue(p.closed, "\(id): the peer was let go")
                assertNoNativeUseAfterClose(r)
                r.calls.dismiss(); await r.settle(); await drainRig(r)
            }
        }
    }

    /// The crash in the owner's video: "Calling...", then the app closes a
    /// second later. WebRTC's microphone thread asserts the recorder is
    /// recording - false when another app holds the mic or the audio mode is
    /// mid-switch. On iOS a native callback's throw is contained by `rtcGuard`,
    /// recorded as a non-fatal named "webrtc-<callback>", and the call is told
    /// through the audio-trouble signal.
    func testWebRtcsMicThreadAssertingIsContainedAndTheCardSaysSo() async {
        let told = Ref<[String]>([])
        CrashHooks.recordNonFatal = { _, `where` in told.mutate { $0.append(`where`) } }
        defer { CrashHooks.recordNonFatal = nil }
        let r = await rig()
        let placed = Task { await r.calls.initiateCall(to: "254712345678", name: "Grace") }
        await r.settle()
        let v = await placed.value
        XCTAssertTrue(v.isSuccess)
        for name in ["AudioRecordThread", "AudioTrackThread"] {
            rtcGuard(name) { throw PlainError("Expected condition to be true") }
        }
        XCTAssertEqual(["webrtc-AudioRecordThread", "webrtc-AudioTrackThread"], told.value, "WebRTC's audio callbacks: contained, and recorded")
        XCTAssertEqual(CallPhase.placing, r.state.phase, "the call is still up")
        r.trouble.emit(true); await r.settle()
        XCTAssertEqual(CallManager.MIC_UNAVAILABLE, r.state.error, "and the call is told")
    }

    func testAMicrophoneWebRtcCouldNotStartIsSaidOnTheCard() async {
        let r = await rig()
        r.trouble.emit(true); await r.settle()
        XCTAssertNil(r.state.error, "no call: nothing to say")
        let placed = Task { await r.calls.initiateCall(to: "254712345678", name: "Grace") }
        await r.settle()
        let v = await placed.value
        XCTAssertTrue(v.isSuccess)
        r.trouble.emit(true); await r.settle()
        XCTAssertEqual(CallManager.MIC_UNAVAILABLE, r.state.error)
        XCTAssertEqual(CallPhase.placing, r.state.phase, "the call stays up: the agent decides")
        r.frame(("type", "outbound_answer"), ("call_id", r.api.connectId), ("sdp", "v=0 their-answer")); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        r.trouble.emit(false); await r.settle()
        XCTAssertEqual(CallManager.SPEAKER_UNAVAILABLE, r.state.error)
    }
}
