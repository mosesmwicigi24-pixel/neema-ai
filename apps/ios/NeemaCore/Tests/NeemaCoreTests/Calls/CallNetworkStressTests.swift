import Foundation
import XCTest
@testable import NeemaCore

/// The softphone on a bad phone network: every call step (ice-config, offer,
/// answer, connect, terminate, callback, the recording upload, the poll) when
/// the network drops, the server is slow or the answer never comes back, plus
/// impatient taps. Failures are what NeemaHTTP really throws: status 0 with
/// "timed out after 30s" for a timeout, status 0 with the transport's text
/// when there is no connection. Android `calls/CallNetworkStressTest.kt`.
@MainActor
final class CallNetworkStressTests: XCTestCase {
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
    private func timeout(_ method: String, _ path: String) -> ApiError { timeoutError(method, path) }
    private func offline(_ method: String, _ path: String) -> ApiError { ApiError(status: 0, method: method, path: path, body: "Failed to connect to neema.bethanyhouse.co.ke/41.90.1.2:443") }
    /// Ring, answer and connect: a live call.
    private func live(_ r: CallRig) async -> FakePeer {
        r.ring(); r.calls.answer(); await r.settle(); r.media.peer.onEvent(.connected); await r.settle()
        return r.media.peer
    }

    // ── The network drops mid-call ───────────────────────────────────────
    func testAShortBlipRecoversAndTheCallGoesOn() async {
        let r = await rig()
        let p = await live(r)
        p.onEvent(.interrupted); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall, "still in the call")
        XCTAssertTrue(r.state.reconnecting)
        XCTAssertFalse(p.closed)
        await r.advance(4_000)
        p.onEvent(.connected); await r.settle()
        XCTAssertFalse(r.state.reconnecting)
        await r.advance(CallManager.ICE_GRACE_MS * 3)
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(Int64(r.state.seconds), (4_000 + CallManager.ICE_GRACE_MS * 3) / 1000, "the timer kept running through the blip")
        XCTAssertEqual(r.count("terminate"), 0)
    }

    func testADropThatNeverRecoversEndsAfterTheGraceAndTellsTheServer() async {
        let r = await rig()
        let p = await live(r)
        p.onEvent(.interrupted); await r.settle()
        await r.advance(CallManager.ICE_GRACE_MS - 1)
        XCTAssertEqual(r.state.phase, .inCall)
        await r.advance(2)
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .connectionLost)
        // Dropped the moment it connected: the grace spent waiting is not call time (the web's bug a).
        XCTAssertEqual(r.state.statusText(), "Call dropped — the connection was lost", "the connected time, not the grace")
        XCTAssertFalse(r.state.reconnecting)
        XCTAssertTrue(p.closed)
        XCTAssertEqual(r.count("terminate wacid.1"), 1)
        await eventually { r.api.uploads.count == 1 }
        XCTAssertEqual(r.api.uploads.count, 1, "the recording is still uploaded")
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended, "Call again is owed: the wrap-up stays")
        XCTAssertEqual(r.state.wrapActions().first, .callAgain)
    }

    func testIceFailingWhileReconnectingEndsAtOnce() async {
        let r = await rig()
        let p = await live(r)
        p.onEvent(.interrupted); await r.settle()
        p.onEvent(.ended); await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .connectionLost)
        // Hung up behind it (never a silent line on their side), once: the grace timer is gone with the call.
        await r.advance(CallManager.ICE_GRACE_MS + 1)
        XCTAssertEqual(r.count("terminate"), 1)
    }

    func testHangingUpWhileReconnectingEndsCleanly() async {
        let r = await rig()
        let p = await live(r)
        p.onEvent(.interrupted); await r.settle()
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .completed, "a plain hang-up, not a lost connection")
        await r.advance(CallManager.ICE_GRACE_MS + 1)
        XCTAssertEqual(r.count("terminate"), 1, "one terminate: the grace timer died with the call")
    }

    // ── Terminate failing ────────────────────────────────────────────────
    func testHangupEndsTheCallHereEvenWhenTheServerIsUnreachable() async {
        let r = await rig()
        _ = await live(r)
        for _ in 0..<5 { r.api.terminateErrors.append(offline("POST", "/admin/calls/wacid.1/terminate")) }
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.phase, .ended, "ended on this phone at once")
        XCTAssertFalse(r.audio.inCall)
        XCTAssertTrue(r.media.peer.closed)
        XCTAssertEqual(r.count("terminate"), 1)
        await r.advance(2_001)
        XCTAssertEqual(r.count("terminate"), 2, "retried")
        await r.advance(5_001)
        XCTAssertEqual(r.count("terminate"), 3)
        await r.advance(60_000)
        XCTAssertEqual(r.count("terminate"), 3, "bounded: three tries")
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testTerminateRetryStopsOnceItGetsThrough() async {
        let r = await rig()
        _ = await live(r)
        r.api.terminateErrors.append(timeout("POST", "/admin/calls/wacid.1/terminate"))
        r.calls.hangup(); await r.settle()
        await r.advance(60_000)
        XCTAssertEqual(r.count("terminate"), 2)
    }

    func testRapidHangupTapsTerminateOnce() async {
        let r = await rig()
        _ = await live(r)
        for _ in 0..<4 { r.calls.hangup() }
        await r.settle()
        XCTAssertEqual(r.count("terminate"), 1)
        await r.advance(8_001)
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testDeclineFromTheNotificationRetriesTheTerminateToo() async {
        let r = await rig()
        r.api.terminateErrors.append(offline("POST", "/admin/calls/wacid.8/terminate"))
        r.calls.handleAction("decline", id: "wacid.8"); await r.settle()
        await r.advance(2_001)
        XCTAssertEqual(r.count("terminate wacid.8"), 2)
    }

    // ── Callback ─────────────────────────────────────────────────────────
    func testCallbackSaysSavedOnlyOnceTheServerSaidSo() async {
        let r = await rig()
        r.api.callbackGate = Deferred<Void>()
        r.ring()
        r.calls.callback(); await r.settle()
        XCTAssertTrue(r.state.busy, "waiting on the server, buttons disabled")
        XCTAssertFalse(r.ringer.ringing, "ringing stopped at once")
        XCTAssertEqual(r.state.phase, .ringing)
        // Impatient taps: none of them sends anything.
        r.calls.callback(); r.calls.hangup(); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.count("callback"), 1)
        XCTAssertEqual(r.count("terminate") + r.count("offer") + r.count("ice-config"), 0)
        // The poll sees the row already marked: the card still ends with the note.
        r.api.calls = [Call(id: "k", callId: "wacid.1", waId: "254712345678", status: "callback", startedAt: r.at(5_000))]
        await r.calls.pollOnce(); await r.settle()
        XCTAssertTrue(r.state.busy)
        r.api.callbackGate!.complete(()); await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.statusText(), CallManager.CALLBACK_SAVED)
        XCTAssertFalse(r.state.busy)
    }

    func testCallbackOfflineSaysSoAndKeepsTrying() async {
        let r = await rig()
        r.api.callbackErrors.append(offline("POST", "/admin/calls/wacid.1/callback"))
        r.ring()
        r.calls.callback(); await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .callback(saved: .retrying))
        XCTAssertEqual(r.state.statusText(), CallManager.CALLBACK_RETRYING)
        await r.advance(2_001)
        XCTAssertEqual(r.count("callback wacid.1"), 2, "retried in the background")
        await r.advance(60_000)
        XCTAssertEqual(r.count("callback wacid.1"), 2, "and stops once it got through")
    }

    func testCallbackRefusedSaysItWasNotSaved() async {
        let r = await rig()
        r.api.callbackErrors.append(apiError(401, "POST", "/admin/calls/wacid.1/callback", "Session expired"))
        r.ring()
        r.calls.callback(); await r.settle()
        XCTAssertEqual(r.state.outcome, .callback(saved: .notSaved))
        XCTAssertNil(r.state.outcome?.autoCloseMs, "not saved: the wrap-up stays")
        await r.advance(60_000)
        XCTAssertEqual(r.count("callback"), 1)
    }

    // ── Answer ───────────────────────────────────────────────────────────
    func testRapidAnswerTapsAnswerOnce() async {
        let r = await rig()
        r.ring()
        for _ in 0..<5 { r.calls.answer() }
        await r.settle()
        XCTAssertEqual(r.count("offer"), 1)
        XCTAssertEqual(r.count("answer"), 1)
        XCTAssertEqual(r.media.peers.count, 1)
    }

    func testAnswerThenDeclineAtOnceNeverAnswers() async {
        let r = await rig()
        r.ring()
        r.calls.answer(); r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.count("answer"), 0)
        XCTAssertEqual(r.count("terminate wacid.1"), 1)
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertNil(r.state.error)
    }

    func testAnswerTimedOutButTheCallConnectedIsKept() async {
        let r = await rig()
        r.api.answerError = timeout("POST", "/admin/calls/wacid.1/answer")
        r.ring(); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting, "no failure shown while it may have worked")
        XCTAssertNil(r.state.error)
        await r.advance(3_000)
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        await r.advance(20_000)
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertNil(r.state.error)
        XCTAssertEqual(r.count("terminate"), 0, "the live call is never terminated")
    }

    func testAnswerTimedOutAndNothingConnectedFailsWithTheReason() async {
        let r = await rig()
        r.api.answerError = timeout("POST", "/admin/calls/wacid.1/answer")
        r.ring(); r.calls.answer(); await r.settle()
        await r.advance(CallManager.ANSWER_CONFIRM_MS + 1)
        // Our answer left, its reply and the audio never came: hung up, and said plainly (web bug b).
        XCTAssertEqual(r.state.error, CallManager.ANSWER_DROPPED)
        await r.advance(1_801)
        XCTAssertEqual(r.count("terminate wacid.1"), 1)
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .failed(reason: CallManager.ANSWER_DROPPED))
        XCTAssertEqual(r.state.statusText(), "The connection dropped while answering — call them back")
    }

    func testAnswerWhileOfflineSaysSoAndKeepsRinging() async {
        let r = await rig()
        r.api.iceError = offline("GET", "/admin/calls/ice-config")
        r.ring(); r.calls.answer(); await r.settle()
        // Nothing reached the server: the call still rings and Answer stays live.
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.state.error, CallManager.ANSWER_NO_CONNECTION)
        XCTAssertTrue(r.ringer.ringing)
        XCTAssertEqual(r.count("terminate"), 0)
        // Back online: one more tap answers it.
        r.api.iceError = nil
        r.calls.answer(); await r.settle()
        XCTAssertTrue(r.api.log.contains("answer wacid.1"))
        XCTAssertNil(r.state.error)
        XCTAssertEqual(r.state.phase, .connecting)
    }

    func testAnswerAfterTheCallerHungUpSaysTheCallEnded() async {
        let r = await rig()
        r.api.offerError = apiError(404, "GET", "/admin/calls/wacid.1/offer", #"{"detail":"call offer expired or not found"}"#)
        r.ring(); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .missed(note: CallManager.CALL_GONE))
        XCTAssertEqual(r.state.statusText(), "Missed call")
        XCTAssertEqual(r.state.outcomeNote(), CallManager.CALL_GONE)
        await r.advance(1_801)
        XCTAssertEqual(r.count("terminate"), 0, "nothing to terminate: the caller is gone")
    }

    func testAnAnswerErrorAfterTheMediaConnectedDoesNotHangUp() async {
        let r = await rig()
        // A 502 from Meta's accept, yet the media came up while the copy showed.
        r.api.answerError = apiError(502, "POST", "/admin/calls/wacid.1/answer", #"{"detail":"accept failed: boom"}"#)
        r.ring(); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.error, "Couldn't connect the call")
        r.media.peer.onEvent(.connected); await r.settle()
        await r.advance(1_801)
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertNil(r.state.error)
        XCTAssertEqual(r.count("terminate"), 0)
    }

    // ── Outbound ─────────────────────────────────────────────────────────
    func testConnectTimedOutButMetaPlacedTheCallIsAdopted() async {
        let r = await rig()
        r.api.connectError = timeout("POST", "/admin/calls/connect")
        r.api.calls = [
            Call(id: "old", callId: "wacid.old", waId: "254712345678", direction: "outbound", status: "ringing", startedAt: r.at(10 * 60_000)),
            Call(id: "k", callId: "wacid.placed", waId: "254712345678", direction: "outbound", status: "ringing", startedAt: r.at(1_000)),
        ]
        let res = Task { await r.calls.initiateCall(to: "+254712345678", name: "Fr. Peter Kamau") }
        await r.settle()
        let rv = await res.value
        XCTAssertTrue(rv.isSuccess, "not a failure: the call is ringing them")
        XCTAssertEqual(r.state.callId, "wacid.placed")
        XCTAssertNil(r.state.error)
        r.frame(("type", "outbound_answer"), ("call_id", "wacid.placed"), ("sdp", "v=0 their-answer"))
        await r.settle()
        XCTAssertTrue(r.media.peer.ops.contains("setRemote(Answer,v=0 their-answer)"))
    }

    func testConnectTimedOutWithNoPlacedCallSaysItCouldNotConfirm() async {
        let r = await rig()
        r.api.connectError = timeout("POST", "/admin/calls/connect")
        let res = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle()
        await r.advance(CallManager.PLACED_LOOKUP_GAP_MS + 1)
        let rv = await res.value
        XCTAssertEqual(rv.failureMessage, CallManager.UNCONFIRMED_CALL)
        XCTAssertEqual(r.count("list"), 2, "looked twice")
        XCTAssertFalse(CallManager.UNCONFIRMED_CALL.lowercased().contains("permission"), "never mistaken for the permission prompt")
        XCTAssertEqual(r.state.outcome, .failed(reason: CallManager.UNCONFIRMED_CALL))
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended, "the agent checks before trying again: it stays")
    }

    func testPlacingACallOfflineSaysSo() async {
        let r = await rig()
        r.api.iceError = offline("GET", "/admin/calls/ice-config")
        let res = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle()
        let rv = await res.value
        XCTAssertEqual(rv.failureMessage, CallManager.OUTBOUND_OFFLINE)
        XCTAssertEqual(r.state.outcome, .failed(reason: CallManager.OUTBOUND_OFFLINE))
        XCTAssertEqual(r.state.wrapActions().first, .tryAgain)
        XCTAssertEqual(r.count("connect"), 0)
    }

    func testRapidCallTapsPlaceOneCall() async {
        let r = await rig()
        let a = Task { await r.calls.initiateCall(to: "254712345678") }
        let b = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle()
        let av = await a.value, bv = await b.value
        XCTAssertTrue(av.isSuccess)
        XCTAssertEqual(bv.failureMessage, "Already in a call")
        XCTAssertEqual(r.count("connect"), 1)
    }

    func testErrorCopyForEveryFailure() {
        XCTAssertEqual(CallManager.answerError(timeout("GET", "/admin/calls/x/offer")), CallManager.ANSWER_SLOW)
        XCTAssertEqual(CallManager.answerError(offline("GET", "/admin/calls/ice-config")), CallManager.ANSWER_OFFLINE)
        XCTAssertEqual(CallManager.answerError(apiError(401, "GET", "/admin/calls/ice-config", "Session expired")), CallManager.SESSION_EXPIRED)
        XCTAssertEqual(CallManager.answerError(apiError(502, "GET", "/admin/calls/x/offer", "<html>Bad gateway</html>")), "Couldn't connect the call")
        XCTAssertEqual(CallManager.outboundError(timeout("GET", "/admin/calls/ice-config")), CallManager.OUTBOUND_SLOW)
        XCTAssertEqual(CallManager.outboundError(offline("POST", "/admin/calls/connect")), CallManager.OUTBOUND_OFFLINE)
        XCTAssertEqual(CallManager.outboundError(apiError(503, "POST", "/admin/calls/connect", "<html>503</html>")), "Couldn't place the call")
        for m in [CallManager.OUTBOUND_SLOW, CallManager.OUTBOUND_OFFLINE, CallManager.SESSION_EXPIRED, CallManager.MIC_BLOCKED] {
            XCTAssertFalse(m.lowercased().contains("permission"), m)
        }
    }

    // ── A call arriving while offline, and a flaky poll ──────────────────
    func testACallThatRangWhileOfflineRingsOnReconnect() async {
        let r = await rig()
        r.connected.value = false; await r.settle()
        r.api.listError = offline("GET", "/admin/calls")
        await r.advance(CallManager.IDLE_POLL_MS * 2 + 1)
        XCTAssertEqual(r.state.phase, .idle, "poll errors are silent")
        r.api.listError = nil
        r.api.calls = [Call(id: "k", callId: "wacid.5", waId: "254712345678", status: "ringing", startedAt: r.at(8_000))]
        r.connected.value = true; await r.settle()
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.state.callId, "wacid.5")
    }

    func testAFailingPollNeverTearsDownARingingCall() async {
        let r = await rig()
        r.ring()
        r.api.listError = apiError(502, "GET", "/admin/calls", "<html><body>Bad Gateway</body></html>")
        await r.advance(CallManager.RING_POLL_MS * 4 + 1)
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertTrue(r.ringer.ringing)
    }

    // ── Recording upload ─────────────────────────────────────────────────
    func testARecordingThatFailsToUploadIsKeptAndSentOnReconnect() async {
        let r = await rig()
        r.api.uploadErrors.append(offline("POST", "/admin/calls/wacid.1/recording"))
        _ = await live(r)
        r.calls.hangup(); await r.settle()
        await eventually { r.count("recording") == 1 }
        XCTAssertTrue(r.api.uploads.isEmpty)
        XCTAssertEqual(r.outboxFiles.count, 1, "kept on disk")
        XCTAssertEqual(r.media.recordings.count, 1)
        XCTAssertFalse(r.media.recordings[0].exists, "moved out of the cache")
        r.connected.value = false; await r.settle()
        r.connected.value = true; await r.settle()
        await eventually { r.api.uploads.count == 1 }
        XCTAssertEqual(r.api.uploads.count, 1)
        XCTAssertEqual(r.api.uploads[0].callId, "wacid.1")
        XCTAssertEqual(r.api.uploads[0].filename, "wacid.1.m4a")
        XCTAssertEqual(r.api.uploads[0].bytes, 48_000)
        XCTAssertEqual(r.outboxFiles.count, 0, "deleted once the server has it")
    }

    func testARecordingLeftByAnEarlierSessionIsSentAtStart() async {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("rec-outbox-\(UUID().uuidString)")
        let first = await rig(outboxDir: dir)
        first.api.uploadErrors.append(timeout("POST", "/admin/calls/wacid.1/recording"))
        _ = await live(first); first.calls.hangup(); await first.settle()
        await eventually { first.count("recording") == 1 }
        XCTAssertEqual(first.outboxFiles.count, 1)
        // The app is killed and started again.
        first.stop()
        let second = await rig(outboxDir: dir)
        await eventually { second.api.uploads.count == 1 }
        XCTAssertEqual(second.api.uploads.first?.callId, "wacid.1")
        XCTAssertEqual(second.outboxFiles.count, 0)
    }

    func testARecordingTheServerRefusesIsDroppedNotRetried() async {
        let r = await rig()
        r.api.uploadErrors.append(apiError(403, "POST", "/admin/calls/wacid.1/recording", #"{"detail":"Call recording is disabled."}"#))
        _ = await live(r); r.calls.hangup(); await r.settle()
        await eventually { r.count("recording") == 1 }
        XCTAssertEqual(r.outboxFiles.count, 0)
        r.foreground.value = false; await r.settle(); r.foreground.value = true; await r.settle()
        XCTAssertEqual(r.count("recording"), 1)
    }

    func testUploadsWaitForSignIn() async {
        let r = await rig()
        r.api.uploadErrors.append(apiError(401, "POST", "/admin/calls/wacid.1/recording", "Session expired"))
        _ = await live(r); r.calls.hangup(); await r.settle()
        await eventually { r.count("recording") == 1 }
        XCTAssertEqual(r.outboxFiles.count, 1, "kept for after sign-in")
        r.signedIn = false
        r.connected.value = false; await r.settle(); r.connected.value = true; await r.settle()
        XCTAssertEqual(r.count("recording"), 1)
        r.signedIn = true
        r.foreground.value = false; await r.settle(); r.foreground.value = true; await r.settle()
        await eventually { r.api.uploads.count == 1 }
        XCTAssertEqual(r.api.uploads.count, 1)
    }

    // ── The outbox itself ────────────────────────────────────────────────
    private func tempRecording(_ bytes: Int = 3_000) -> URL {
        let f = FileManager.default.temporaryDirectory.appendingPathComponent("call-\(UUID().uuidString).m4a")
        try? Data(count: bytes).write(to: f)
        return f
    }

    func testOutboxIsBoundedByCountAndAge() {
        let t = Ref<Int64>(CallRig.BASE)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("rec-outbox-\(UUID().uuidString)")
        let box = RecordingOutbox(dir: dir) { t.value }
        for i in 0..<(RecordingOutbox.MAX_FILES + 3) {
            t.value += 1_000
            XCTAssertTrue(box.put("wacid.\(i)==", file: tempRecording()))
        }
        XCTAssertEqual(box.pending().count, RecordingOutbox.MAX_FILES)
        XCTAssertEqual(box.pending().first?.callId, "wacid.3==", "the oldest went first")
        t.value += RecordingOutbox.MAX_AGE_MS + 1
        box.prune()
        XCTAssertTrue(box.pending().isEmpty)
    }

    func testOutboxSendsOldestFirstAndStopsAtATransientFailure() async throws {
        let t = Ref<Int64>(CallRig.BASE)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("rec-outbox-\(UUID().uuidString)")
        let box = RecordingOutbox(dir: dir) { t.value }
        for id in ["a", "b", "c"] { t.value += 1; box.put(id, file: tempRecording()) }
        let sent = Ref<[String]>([])
        let n = try await box.drain { id, _ in
            if id == "b" { throw apiError(503, "POST", "/admin/calls/b/recording", "<html>down</html>") }
            sent.mutate { $0.append(id) }
        }
        XCTAssertEqual(n, 1)
        XCTAssertEqual(sent.value, ["a"])
        XCTAssertEqual(box.pending().map { $0.callId }, ["b", "c"])
        _ = try await box.drain { id, _ in sent.mutate { $0.append(id) } }
        XCTAssertEqual(sent.value, ["a", "b", "c"])
        XCTAssertTrue(box.pending().isEmpty)
    }
}
