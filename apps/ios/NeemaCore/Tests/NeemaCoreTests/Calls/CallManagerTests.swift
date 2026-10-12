import Foundation
import XCTest
@testable import NeemaCore

/// The softphone's rules (lib/callContext.tsx) on Linux: phases, the 12 s
/// re-ring cooldown, the 2.5 s / 12 s poll cadence, every WebSocket frame, the
/// error copy, the mic prompt, recording upload, and the alert actions.
/// Android `calls/CallManagerTest.kt`, one test for one test.
@MainActor
final class CallManagerTests: XCTestCase {
    private let wacid = "wacid.HBgMMjU0NzEyMzQ1Njc4FQIAEhggQUFBQTFCMkMzRDRFNUY2QTdCOEM5RDBFMUYyHBgMMjU0NzAwMDAwMDAwFQIAAA=="

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

    // ── Ringing ──────────────────────────────────────────────────────────
    func testIncomingFrameRingsWithCallerAndRingtone() async {
        let r = await rig()
        r.ring()
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.state.callId, "wacid.1")
        XCTAssertEqual(r.state.from, "254712345678")
        XCTAssertEqual(r.state.name, "Fr. Peter Kamau")
        XCTAssertTrue(r.ringer.ringing)
        XCTAssertTrue(r.ringer.posted.isEmpty, "foreground: the card is the alert")
    }

    func testIncomingFrameWithoutCallIdIsIgnored() async {
        let r = await rig()
        r.frame(("type", "incoming_call"), ("from", "254700000000"))
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testSecondCallWhileRingingDoesNotReplaceTheFirst() async {
        let r = await rig()
        r.ring("wacid.1")
        r.ring("wacid.2", from: "254799999999", name: "Someone Else")
        XCTAssertEqual(r.state.callId, "wacid.1")
    }

    func testBackgroundRingPostsTheNotificationAndForegroundDropsIt() async {
        let r = await rig()
        r.foreground.value = false; await r.settle()
        r.ring(name: nil)
        XCTAssertEqual(r.ringer.posted.count, 1)
        XCTAssertEqual(r.ringer.posted[0].callId, "wacid.1")
        XCTAssertEqual(r.ringer.posted[0].who, "+254712345678")
        XCTAssertEqual(r.ringer.posted[0].from, "254712345678")
        r.foreground.value = true; await r.settle()
        XCTAssertFalse(r.ringer.showing)
        r.foreground.value = false; await r.settle()
        XCTAssertTrue(r.ringer.showing, "backgrounded again while still ringing")
    }

    // ── Decline / callback / cooldown ────────────────────────────────────
    func testDeclineTerminatesShowsEndedThenIdleAndStartsTheCooldown() async {
        let r = await rig()
        r.ring()
        r.calls.hangup(); await r.settle()
        XCTAssertTrue(r.api.log.contains("terminate wacid.1"))
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .declined())
        XCTAssertEqual(r.state.statusText(), "Call declined")
        XCTAssertFalse(r.ringer.ringing)
        // A neutral wrap-up closes by itself.
        await r.advance(4_999)
        XCTAssertEqual(r.state.phase, .ended)
        await r.advance(2)
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertNil(r.state.callId)
        // Still "ringing" server-side: the same call must not re-ring within 12 s…
        r.ring()
        XCTAssertEqual(r.state.phase, .idle)
        // …but a genuine retry after the cooldown does.
        await r.advance(11_000)
        r.ring()
        XCTAssertEqual(r.state.phase, .ringing)
    }

    func testCooldownIsPerCall() async {
        let r = await rig()
        r.ring("wacid.1"); r.calls.hangup(); await r.settle()
        await r.advance(1_100)
        r.ring("wacid.2")
        XCTAssertEqual(r.state.phase, .ringing)
    }

    func testCallbackPostsAndShowsTheNoteForLonger() async {
        let r = await rig()
        r.ring()
        r.calls.callback(); await r.settle()
        XCTAssertTrue(r.api.log.contains("callback wacid.1"))
        XCTAssertFalse(r.api.log.contains("terminate wacid.1"))
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.statusText(), "Saved to call back — find it under Calls")
        await r.advance(3_900)
        XCTAssertEqual(r.state.phase, .ended)
        await r.advance(200)
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testHangupWhenIdleOrAlreadyEndedDoesNothing() async {
        let r = await rig()
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
        r.ring()
        r.calls.hangup(); await r.settle()
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.api.log.filter { $0 == "terminate wacid.1" }.count, 1)
    }

    // ── WebSocket call_ended ─────────────────────────────────────────────
    func testCallEndedFrameForThisCallEndsIt() async {
        let r = await rig()
        r.ring()
        r.frame(("type", "call_ended"), ("call_id", "other"))
        XCTAssertEqual(r.state.phase, .ringing)
        r.frame(("type", "call_ended"), ("call_id", "wacid.1"))
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertFalse(r.ringer.ringing)
        // An older frame without an outcome, for a call that was ringing: the caller gave up.
        XCTAssertEqual(r.state.outcome, .missed())
        XCTAssertEqual(r.state.wrapActions(), [.callBack, .message, .done])
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended, "the team owes them a call: the wrap-up waits for the agent")
        r.calls.dismiss(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertFalse(r.logged("terminate"), "the caller hung up: nothing to terminate")
    }

    // ── Poll fallback ────────────────────────────────────────────────────
    func testPollCadenceIs12sIdleAnd2500msWhileRinging() async {
        let r = await rig()
        await r.advance(11_999)
        XCTAssertEqual(r.listCount(), 0)
        await r.advance(2)
        XCTAssertEqual(r.listCount(), 1)
        await r.advance(5_000)
        r.ring()
        // The 12 s wait already running is dropped: the next poll is 2.5 s after the ring.
        await r.advance(2_499)
        XCTAssertEqual(r.listCount(), 1)
        await r.advance(2)
        XCTAssertEqual(r.listCount(), 2)
        await r.advance(2_500)
        XCTAssertEqual(r.listCount(), 3)
        // Back to idle: 12 s again.
        r.calls.hangup(); await r.settle(); await r.advance(1_001)
        let n = r.listCount()
        await r.advance(10_000)
        XCTAssertEqual(r.listCount(), n)
    }

    func testPollCatchesAFreshRingingCallOnly() async {
        let r = await rig()
        r.api.calls = [
            Call(id: "k0", callId: "old", waId: "254700000001", status: "ringing", startedAt: r.at(120_000)),
            Call(id: "k1", callId: "done", waId: "254700000002", status: "missed", startedAt: r.at(5_000)),
        ]
        await r.calls.pollOnce(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle, "older than 90 s / not ringing: ignored")
        r.api.calls.append(Call(id: "k2", callId: "fresh", waId: "254711111111", name: "Rev. Mary Achieng", status: "ringing", startedAt: r.at(30_000)))
        await r.calls.pollOnce(); await r.settle()
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.state.callId, "fresh")
        XCTAssertEqual(r.state.from, "254711111111")
        XCTAssertEqual(r.state.name, "Rev. Mary Achieng")
    }

    func testPollWhileRingingTearsDownWhenTheCallerHungUp() async {
        let r = await rig()
        r.ring()
        r.api.calls = [Call(id: "k1", callId: "wacid.1", status: "ringing", startedAt: r.at(3_000))]
        await r.calls.pollOnce(); await r.settle()
        XCTAssertEqual(r.state.phase, .ringing)
        r.api.calls = [Call(id: "k1", callId: "wacid.1", status: "missed", startedAt: r.at(3_000))]
        await r.calls.pollOnce(); await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .missed())
        XCTAssertFalse(r.ringer.ringing)
        XCTAssertFalse(r.logged("terminate"))
    }

    func testPollSkipsWhenSignedOutAndSurvivesErrors() async {
        let r = await rig()
        r.signedIn = false
        await r.calls.pollOnce()
        XCTAssertFalse(r.api.log.contains("list"))
        r.signedIn = true
        r.api.listError = apiError(500, "GET", "/admin/calls")
        await r.calls.pollOnce()
        XCTAssertEqual(r.state.phase, .idle)
    }

    // ── Answer ───────────────────────────────────────────────────────────
    func testAnswerBuildsTheWebRtcAnswerAndGoesLive() async {
        let r = await rig()
        r.ring()
        r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting)
        XCTAssertFalse(r.ringer.ringing)
        XCTAssertTrue(r.api.log.contains("ice-config") && r.api.log.contains("offer wacid.1"))
        let p = r.media.peer
        XCTAssertEqual(p.ops, ["addMic(true)", "setRemote(Offer,v=0 caller-offer)", "createAnswer", "setLocal(Answer,v=0 our-answer)"])
        XCTAssertEqual(r.api.lastAnswerSdp, "setLocal(Answer,v=0 our-answer)+candidates", "the gathered SDP is sent")
        XCTAssertTrue(r.audio.inCall, "in-call audio + mic service")
        p.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(r.media.recordings.count, 1, "recording starts once live")
        await r.advance(3_001)
        XCTAssertEqual(r.state.seconds, 3)
    }

    func testAnswerWaitsAtMost2500msForIceGathering() async {
        let r = await rig()
        r.media.gatherAtOnce = false
        r.ring()
        r.calls.answer(); await r.settle()
        XCTAssertFalse(r.logged("answer"))
        await r.advance(2_501)
        XCTAssertTrue(r.api.log.contains("answer wacid.1"))
    }

    func testAnswerFailureShowsCopyThenHangsUp() async {
        let r = await rig()
        r.api.offerError = apiError(503, "GET", "/admin/calls/wacid.1/offer", #"{"detail":"calling unavailable"}"#)
        r.ring()
        r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.error, "Couldn't connect the call")
        XCTAssertEqual(r.state.phase, .connecting)
        await r.advance(1_801)
        XCTAssertTrue(r.api.log.contains("terminate wacid.1"))
        XCTAssertEqual(r.state.phase, .ended)
    }

    func testAnswerAlreadyTakenBySomeoneElse() async {
        let r = await rig()
        r.api.answerError = apiError(409, "POST", "/admin/calls/wacid.1/answer", #"{"detail":"call already answered"}"#)
        r.ring()
        r.calls.answer(); await r.settle()
        // Said at once, on the wrap-up: no error to read and wait out.
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: nil))
        XCTAssertEqual(r.state.statusText(), "Answered by a colleague")
        await r.advance(1_801)
        // The colleague who won the call keeps it: no terminate from this device.
        XCTAssertFalse(r.logged("terminate"))
        XCTAssertTrue(r.media.peer.closed)
    }

    func testAnswerAsksForTheMicAndProceedsWhenAllowed() async {
        let r = await rig()
        r.mic = false
        r.ring()
        r.calls.answer(); await r.settle()
        XCTAssertTrue(r.calls.micRequest.value)
        XCTAssertTrue(r.media.peer.ops.isEmpty)
        r.mic = true
        r.calls.onMicResult(true); await r.settle()
        XCTAssertFalse(r.calls.micRequest.value)
        XCTAssertTrue(r.api.log.contains("answer wacid.1"))
        XCTAssertNil(r.state.error)
    }

    // ── The microphone's live signal (only once the mic was allowed) ─────
    func testMicServiceStartsOnlyOnceTheMicIsAllowed() async {
        let r = await rig()
        r.mic = false
        r.ring()
        r.calls.answer(); await r.settle()
        XCTAssertTrue(r.audio.inCall, "audio routed while connecting")
        XCTAssertFalse(r.audio.micService, "no mic-live signal while the prompt is up")
        r.mic = true
        r.calls.onMicResult(true); await r.settle()
        XCTAssertTrue(r.audio.micService)
        XCTAssertEqual(r.audio.micLives, 1)
        r.media.peer.onEvent(.connected); await r.settle()
        r.calls.hangup(); await r.settle()
        XCTAssertFalse(r.audio.micService || r.audio.inCall, "back to plain after the call")
    }

    func testMicRefusedNeverStartsTheMicService() async {
        let r = await rig()
        r.mic = false
        r.ring(); r.calls.answer(); await r.settle()
        r.calls.onMicResult(false); await r.settle()
        await r.advance(1_801)
        XCTAssertEqual(r.audio.micLives, 0)
        // Outbound, refused too.
        await r.advance(1_001)
        let b = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle(); r.calls.onMicResult(false); await r.settle()
        let v1 = await b.value
        XCTAssertEqual(v1.failureMessage, CallManager.MIC_BLOCKED)
        XCTAssertEqual(r.audio.micLives, 0)
        XCTAssertFalse(r.audio.micService)
    }

    func testOutboundStartsTheMicServiceWithTheMic() async {
        let r = await rig()
        let a = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle()
        let v2 = await a.value
        XCTAssertTrue(v2.isSuccess)
        XCTAssertEqual(r.audio.micLives, 1)
        XCTAssertTrue(r.media.peer.hasMic)
    }

    func testAnswerWithMicRefusedSaysMicrophoneBlocked() async {
        let r = await rig()
        r.mic = false
        r.ring()
        r.calls.answer(); await r.settle()
        r.calls.onMicResult(false); await r.settle()
        XCTAssertEqual(r.state.outcome, .micBlocked)
        XCTAssertEqual(r.state.statusText(), "Microphone blocked — allow it in settings")
        XCTAssertEqual(r.state.wrapActions(), [.openSettings, .done])
        XCTAssertFalse(r.logged("answer"))
        await r.advance(60_000)
        // Nothing was answered: a colleague can still take it — declining would end it for everyone.
        XCTAssertFalse(r.logged("terminate"))
        XCTAssertEqual(r.state.phase, .ended, "sticky: the agent has something to fix")
    }

    func testUnansweredMicPromptTimesOutAsBlocked() async {
        let r = await rig()
        r.mic = false
        r.ring()
        r.calls.answer(); await r.settle()
        await r.advance(CallManager.MIC_PROMPT_TIMEOUT_MS + 1)
        XCTAssertEqual(r.state.outcome, .micBlocked)
        XCTAssertFalse(r.calls.micRequest.value)
    }

    func testHangingUpDuringTheMicPromptCancelsItQuietly() async {
        let r = await rig()
        r.mic = false
        r.ring()
        r.calls.answer(); await r.settle()
        r.calls.hangup(); await r.settle()
        XCTAssertFalse(r.calls.micRequest.value)
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertNil(r.state.error)
    }

    func testPeerDisconnectEndsTheCall() async {
        let r = await rig()
        r.ring(); r.calls.answer(); await r.settle()
        let p = r.media.peer
        p.onEvent(.connected); await r.settle()
        p.onEvent(.ended); await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .completed)
        XCTAssertTrue(p.closed)
        XCTAssertFalse(r.audio.inCall)
        await r.advance(8_001)
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testEventsFromAClosedPeerAreIgnored() async {
        let r = await rig()
        r.ring(); r.calls.answer(); await r.settle()
        let old = r.media.peer
        r.calls.hangup(); await r.settle()
        await r.advance(1_001)
        r.ring("wacid.2")
        old.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .ringing)
    }

    // ── Mute / speaker / recording ───────────────────────────────────────
    func testMuteNeedsTheMicThenTogglesTrackAndRecording() async {
        let r = await rig()
        r.ring()
        r.calls.toggleMute()
        XCTAssertFalse(r.state.muted, "no local stream yet")
        r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        r.calls.toggleMute()
        XCTAssertTrue(r.state.muted)
        XCTAssertEqual(r.media.peer.micEnabled, false)
        XCTAssertEqual(r.media.recordings.count, 1)
        XCTAssertTrue(r.media.recordings[0].micMuted)
        r.calls.toggleMute()
        XCTAssertFalse(r.state.muted)
        XCTAssertEqual(r.media.peer.micEnabled, true)
    }

    func testSpeakerRoutesAudio() async {
        let r = await rig()
        r.calls.toggleSpeaker()
        XCTAssertTrue(r.state.speaker && r.audio.speakerOn)
        r.calls.toggleSpeaker()
        XCTAssertFalse(r.state.speaker || r.audio.speakerOn)
    }

    func testRecordingUploadsOnHangup() async {
        let r = await rig()
        r.ring(); r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.media.recordings.count, 1)
        let rec = r.media.recordings[0]
        XCTAssertTrue(rec.stopped)
        await eventually { !r.api.uploads.isEmpty }
        XCTAssertEqual(r.api.uploads.count, 1)
        let u = r.api.uploads[0]
        XCTAssertEqual(u.callId, "wacid.1")
        XCTAssertEqual(u.filename, "wacid.1.m4a")
        XCTAssertEqual(u.mime, "audio/mp4")
        XCTAssertEqual(u.bytes, 48_000, "the whole recording, streamed from disk")
        XCTAssertEqual(r.api.lastUploadStreamed, true, "one upload path: core api.calls.uploadRecording(UploadFile.of(file))")
        XCTAssertFalse(rec.exists, "temp file removed")
    }

    func testTinyRecordingsAreSkippedAndTheKillSwitchIsHonoured() async {
        let r = await rig()
        r.media.recordingBytes = 1_500
        r.ring(); r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        r.calls.hangup(); await r.settle()
        XCTAssertTrue(r.api.uploads.isEmpty)
        await r.advance(1_001)
        r.api.ice = IceConfig(record: false)
        r.ring("wacid.2"); r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.media.recordings.count, 1, "record:false → no second recording")
    }

    // ── Outbound ─────────────────────────────────────────────────────────
    func testOutboundCallPlacesTheOfferAndConnectsOnTheAnswerFrame() async {
        let r = await rig()
        let res = Task { await r.calls.initiateCall(to: "+254712345678", name: "Fr. Peter Kamau") }
        await r.settle()
        let v3 = await res.value
        XCTAssertTrue(v3.isSuccess)
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut, "Meta is ringing them")
        XCTAssertEqual(r.state.statusText(), "Ringing…")
        XCTAssertTrue(r.state.outbound)
        XCTAssertEqual(r.state.from, "254712345678")
        XCTAssertEqual(r.state.callId, "wacid.out1")
        let c = r.api.lastConnect!
        XCTAssertEqual(c.to, "+254712345678")
        XCTAssertEqual(c.sdp, "setLocal(Offer,v=0 our-offer)+candidates")
        XCTAssertEqual(c.name, "Fr. Peter Kamau")
        r.frame(("type", "outbound_answer"), ("call_id", "someone-else"), ("sdp", "x"))
        XCTAssertFalse(r.media.peer.ops.contains { $0.hasPrefix("setRemote") })
        r.frame(("type", "outbound_answer"), ("call_id", "wacid.out1"), ("sdp", "v=0 their-answer"))
        await r.settle()
        XCTAssertTrue(r.media.peer.ops.contains("setRemote(Answer,v=0 their-answer)"))
        XCTAssertEqual(r.state.phase, .connecting)
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
    }

    func testOutboundBlankNameIsNotSent() async {
        let r = await rig()
        let res = Task { await r.calls.initiateCall(to: "254712345678", name: "") }
        await r.settle(); _ = await res.value
        XCTAssertNil(r.api.lastConnect!.name)
    }

    func testOutboundWithoutCustomerPermissionSaysSoAndResets() async {
        let r = await rig()
        r.api.connectError = apiError(409, "POST", "/admin/calls/connect", #"{"detail":"This customer hasn't granted call permission yet."}"#)
        let res = Task { await r.calls.initiateCall(to: "254712345678", name: "Fr. Peter Kamau") }
        await r.settle()
        let result = await res.value
        XCTAssertEqual(result.failureMessage, CallManager.NO_CALL_PERMISSION)
        XCTAssertEqual((result.failure as? CallError)?.shown, true, "the card says it: callers don't toast it again")
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        XCTAssertEqual(r.state.statusText(), "Peter hasn't allowed WhatsApp calls yet")
        XCTAssertEqual(r.state.wrapActions().first, .sendCallRequest)
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended, "sticky until the agent decides")
        XCTAssertTrue(r.media.peer.closed)
        XCTAssertFalse(r.logged("request-permission"), "never asked by itself: it messages the customer")
        // The "permission" → requestPermission path: digits only.
        let v4 = await r.calls.requestPermission(to: "+254 712 345 678")
        XCTAssertTrue(v4.isSuccess)
        XCTAssertTrue(r.api.log.contains("request-permission 254712345678"))
    }

    func testRequestPermissionFailureIsReported() async {
        let r = await rig()
        r.api.permissionError = apiError(502, "POST", "/admin/calls/request-permission")
        let v5 = await r.calls.requestPermission(to: "254712345678")
        XCTAssertTrue(v5.isFailure)
    }

    func testOutboundOtherFailuresAndMicRefusal() async {
        let r = await rig()
        r.api.connectError = apiError(502, "POST", "/admin/calls/connect", #"{"detail":"call failed"}"#)
        let a = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle()
        let v6 = await a.value
        XCTAssertEqual(v6.failureMessage, "Couldn't place the call")
        await r.advance(2_201)

        r.api.connectError = nil
        r.mic = false
        let b = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle()
        r.calls.onMicResult(false); await r.settle()
        let msg = (await b.value).failureMessage ?? ""
        XCTAssertEqual(msg, CallManager.MIC_BLOCKED)
        XCTAssertFalse(msg.lowercased().contains("permission"), "not the customer's permission")
        XCTAssertFalse(r.api.log.filter { $0.hasPrefix("connect") }.count > 1)
    }

    func testOutboundWhileBusyIsRefused() async {
        let r = await rig()
        r.ring()
        let res = Task { await r.calls.initiateCall(to: "254700000000") }
        await r.settle()
        let v7 = await res.value
        XCTAssertEqual(v7.failureMessage, "Already in a call")
        XCTAssertEqual(r.state.callId, "wacid.1")
    }

    func testHangingUpAPendingOutboundCallNeverTerminatesPending() async {
        let r = await rig()
        r.media.gatherAtOnce = false
        let res = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle()
        r.calls.hangup(); await r.settle()
        await r.advance(2_600)
        let v8 = await res.value
        XCTAssertTrue(v8.isSuccess)
        XCTAssertFalse(r.logged("terminate") || r.logged("connect"))
    }

    func testHangingUpWhileMetaPlacesTheCallTerminatesIt() async {
        let r = await rig()
        r.api.connectGate = Deferred<Void>()
        let res = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle()
        r.calls.hangup(); await r.settle()
        r.api.connectGate!.complete(()); await r.settle()
        let v9 = await res.value
        XCTAssertTrue(v9.isSuccess)
        XCTAssertTrue(r.api.log.contains("terminate wacid.out1"))
    }

    func testOutboundErrorResetDoesNotWipeALaterCall() async {
        let r = await rig()
        r.api.connectError = apiError(502, "POST", "/admin/calls/connect")
        let a = Task { await r.calls.initiateCall(to: "254712345678") }
        await r.settle(); _ = await a.value
        r.calls.hangup(); await r.settle()             // dismiss the error early
        await r.advance(1_001)
        r.ring("wacid.9")
        await r.advance(1_500)                         // past the old 2.2 s reset
        XCTAssertEqual(r.state.phase, .ringing)
    }

    // ── Alert actions ────────────────────────────────────────────────────
    func testNotificationAnswerAndDecline() async {
        let r = await rig()
        r.ring()
        r.calls.handleAction("answer", id: "wacid.other"); await r.settle()
        XCTAssertEqual(r.state.phase, .ringing, "a stale alert's action is ignored")
        r.calls.handleAction("answer", id: "wacid.1"); await r.settle()
        XCTAssertTrue(r.api.log.contains("answer wacid.1"))
        r.calls.hangup(); await r.settle(); await r.advance(1_001)
        await r.advance(12_000)
        r.ring("wacid.2")
        r.calls.handleAction("decline", id: "wacid.2"); await r.settle()
        XCTAssertTrue(r.api.log.contains("terminate wacid.2"))
        XCTAssertEqual(r.state.phase, .ended)
    }

    func testNotificationActionsAfterAProcessRestart() async {
        let r = await rig()
        r.api.calls = [Call(id: "k1", callId: "wacid.7", waId: "254712345678", status: "ringing", startedAt: r.at(10_000))]
        r.calls.handleAction("answer", id: "wacid.7"); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting, "found by polling, then answered")
        XCTAssertTrue(r.api.log.contains("answer wacid.7"))
        r.calls.hangup(); await r.settle(); await r.advance(1_001)
        r.calls.handleAction("decline", id: "wacid.8"); await r.settle()
        XCTAssertTrue(r.api.log.contains("terminate wacid.8"))
        XCTAssertFalse(r.state.live)
    }

    func testErrorMapping() {
        let e409 = apiError(409, "POST", "/admin/calls/connect")
        XCTAssertEqual(CallManager.outboundError(e409), CallManager.NO_CALL_PERMISSION)
        XCTAssertEqual(CallManager.outboundError(apiError(502, "POST", "/x")), "Couldn't place the call")
        XCTAssertEqual(CallManager.outboundError(PlainError("sdp")), "Couldn't place the call")
        XCTAssertEqual(CallManager.answerError(e409), "Couldn't connect the call")
    }

    // ── WebSocket frames, byte for byte as the webhook publishes them ────
    func testRealIncomingCallFrameRings() async {
        let r = await rig()
        // _handle_calls, event == "connect" with an offer: `at` is Meta's string
        // timestamp, `name` null when the contacts block had no profile.
        r.raw(#"{"type": "incoming_call", "call_id": "\#(wacid)", "from": "254712345678", "name": null, "at": "1790330413"}"#)
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.state.callId, wacid)
        XCTAssertEqual(r.state.from, "254712345678")
        XCTAssertNil(r.state.name)
    }

    func testRealOutboundAnswerFrameAppliesTheCustomersSdp() async {
        let r = await rig()
        r.api.connectId = wacid
        let placed = Task { await r.calls.initiateCall(to: "+254712345678", name: "Fr. Peter Kamau") }
        await r.settle()
        let v10 = await placed.value
        XCTAssertTrue(v10.isSuccess)
        // event == "connect" with sdp_type == "answer" → outbound_answer {call_id, sdp}.
        r.raw(#"{"type": "outbound_answer", "call_id": "\#(wacid)", "sdp": "v=0\r\na=setup:passive\r\n"}"#)
        await r.settle()
        XCTAssertTrue(r.media.peer.ops.contains("setRemote(Answer,v=0\r\na=setup:passive\r\n)"))
        // Another agent's outbound call is not ours.
        r.raw(#"{"type": "outbound_answer", "call_id": "wacid.other", "sdp": "v=0"}"#)
        await r.settle()
        XCTAssertEqual(r.media.peer.ops.filter { $0.hasPrefix("setRemote") }.count, 1)
    }

    func testRealCallEndedFrameEndsTheCall() async {
        let r = await rig()
        r.raw(#"{"type": "incoming_call", "call_id": "\#(wacid)", "from": "254712345678", "name": "Fr. Peter Kamau", "at": "1790330413"}"#)
        // event == "terminate": status is Meta's (e.g. "COMPLETED"), duration an int or null.
        r.raw(#"{"type": "call_ended", "call_id": "\#(wacid)", "status": "COMPLETED", "duration": 42}"#)
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertFalse(r.ringer.ringing)
    }

    func testUnrelatedFramesOnTheSharedSocketAreIgnored() async {
        let r = await rig()
        // websocket.py relays every ws:channel:* to every client.
        r.raw(#"{"type": "new_message", "conversation_id": "c1", "call_id": 5}"#)
        r.raw(#"{"type": "incoming_call", "from": "254712345678"}"#)   // no call_id
        XCTAssertEqual(r.state.phase, .idle)
    }

    // ── Round 4: missed frames, stale signals, calls that overlap ────────
    func testSocketReconnectPollsAtOnce() async {
        let r = await rig()
        r.connected.value = false; await r.settle()
        r.api.calls = [Call(id: "k1", callId: "wacid.9", waId: "254712345678", status: "ringing", startedAt: r.at(4_000))]
        await r.advance(3_000)
        XCTAssertEqual(r.state.phase, .idle)
        r.connected.value = true; await r.settle()
        XCTAssertEqual(r.state.phase, .ringing, "caught up on reconnect, not on the next 12 s tick")
        XCTAssertEqual(r.state.callId, "wacid.9")
    }

    func testComingBackToTheForegroundPollsAtOnce() async {
        let r = await rig()
        r.foreground.value = false; await r.settle()
        let before = r.listCount()
        r.foreground.value = true; await r.settle()
        XCTAssertEqual(r.listCount(), before + 1)
        // Signed out: nothing is fetched.
        r.signedIn = false
        r.foreground.value = false; await r.settle(); r.foreground.value = true; await r.settle()
        r.connected.value = false; await r.settle(); r.connected.value = true; await r.settle()
        XCTAssertEqual(r.listCount(), before + 1)
    }

    func testAColleaguesOutboundCallNeverRingsThisPhone() async {
        let r = await rig()
        // calls_connect logs the outbound call as status "ringing" too.
        r.api.calls = [Call(id: "k1", callId: "wacid.out", waId: "254733444555", direction: "outbound", status: "ringing", startedAt: r.at(2_000))]
        await r.calls.pollOnce(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertEqual(r.ringer.ringStarts, 0)
    }

    func testCallEndedForACallNeverSeenIsHarmlessAndBlocksALateRing() async {
        let r = await rig()
        r.raw(#"{"type": "call_ended", "call_id": "wacid.ghost", "status": "COMPLETED", "duration": null}"#)
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertTrue(r.api.log.isEmpty && r.ringer.ringStarts == 0, "no request, no ringtone")
        // The incoming_call frame arrives after its own end (out of order).
        r.ring("wacid.ghost")
        XCTAssertEqual(r.state.phase, .idle)
        // A lagging "ringing" row for it doesn't ring either.
        r.api.calls = [Call(id: "k1", callId: "wacid.ghost", waId: "254712345678", status: "ringing", startedAt: r.at(3_000))]
        await r.calls.pollOnce(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
        // Other calls are unaffected.
        r.ring("wacid.2")
        XCTAssertEqual(r.state.phase, .ringing)
    }

    func testDuplicatedAndBurstFramesRingOnce() async {
        let r = await rig()
        r.ring(); r.ring(); r.ring()
        XCTAssertEqual(r.ringer.ringStarts, 1)
        r.frame(("type", "call_ended"), ("call_id", "wacid.1"))
        r.frame(("type", "call_ended"), ("call_id", "wacid.1"))
        XCTAssertEqual(r.state.phase, .ended)
        await r.advance(1_001)
        r.ring()   // a duplicate that arrives after the end
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.ringer.ringStarts, 1)
    }

    func testCallEndedWhileConnectingEndsTheCall() async {
        let r = await rig()
        r.ring(); r.media.gatherAtOnce = false
        r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting)
        r.frame(("type", "call_ended"), ("call_id", "wacid.1"))
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertTrue(r.media.peer.closed)
        XCTAssertFalse(r.audio.inCall)
    }

    func testASecondCallDuringALiveCallIsIgnoredThenRingsWhenItEnds() async {
        let r = await rig()
        r.ring("wacid.1"); r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        r.api.calls = [Call(id: "k2", callId: "wacid.2", waId: "254799999999", name: "Sr. Agnes Wairimu", status: "ringing", startedAt: r.at(1_000))]
        let polls = r.listCount()
        r.ring("wacid.2", from: "254799999999", name: "Sr. Agnes Wairimu")
        // No take-over: the live call carries on, no ringtone over it — a banner says who waits.
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(r.state.callId, "wacid.1")
        XCTAssertEqual(r.state.waiting, WaitingCall(callId: "wacid.2", from: "254799999999", name: "Sr. Agnes Wairimu"))
        XCTAssertEqual(r.ringer.ringStarts, 1)
        XCTAssertTrue(r.ringer.posted.isEmpty)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.listCount(), polls + 1, "looked for again the moment the phone is free")
        XCTAssertEqual(r.state.phase, .ringing, "and rung at once — the wrap-up gives way")
        XCTAssertEqual(r.state.callId, "wacid.2")
        XCTAssertEqual(r.state.name, "Sr. Agnes Wairimu")
    }

    func testASecondCallThatGaveUpDuringTheLiveCallDoesNotRing() async {
        let r = await rig()
        r.ring("wacid.1"); r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        r.ring("wacid.2")
        r.api.calls = [Call(id: "k2", callId: "wacid.2", status: "missed", startedAt: r.at(20_000))]
        r.calls.hangup(); await r.settle(); await r.advance(1_001)
        XCTAssertEqual(r.state.outcome, .completed, "the wrap-up of the call that ended stays")
        XCTAssertEqual(r.state.callId, "wacid.1")
    }

    func testRingingGivesUpAfterTwoMinutesWhenEveryEndSignalWasLost() async {
        let r = await rig()
        r.api.listError = apiError(503, "GET", "/admin/calls")   // polls fail too
        r.ring()
        await r.advance(119_000)
        XCTAssertEqual(r.state.phase, .ringing)
        await r.advance(1_001)
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .missed())
        XCTAssertFalse(r.ringer.ringing); XCTAssertFalse(r.ringer.showing)
        XCTAssertFalse(r.logged("terminate"), "nothing to terminate: the caller is long gone")
        r.ring()
        XCTAssertEqual(r.ringer.ringStarts, 1, "cooldown: a replayed frame doesn't re-ring it")
    }

    func testTheRingTimeoutDoesNotTouchAnAnsweredCall() async {
        let r = await rig()
        r.ring(); r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        await r.advance(125_000)
        XCTAssertEqual(r.state.phase, .inCall)
    }

    // ── Round 10: an answer that beats connect's reply ───────────────────
    func testAnOutboundAnswerThatArrivesBeforeConnectRepliesIsStillApplied() async {
        let r = await rig()
        let gate = Deferred<Void>()
        r.api.connectGate = gate
        let placed = Task { await r.calls.initiateCall(to: "254712345678", name: "Fr. Peter Kamau") }
        await r.settle()
        // Meta rang them and they picked up before our POST came back.
        r.frame(("type", "outbound_answer"), ("call_id", "wacid.out1"), ("sdp", "v=0 their-answer"))
        XCTAssertFalse(r.media.peer.ops.contains { $0.hasPrefix("setRemote") })
        gate.complete(()); await r.settle()
        let v11 = await placed.value
        XCTAssertTrue(v11.isSuccess)
        XCTAssertTrue(r.media.peer.ops.contains("setRemote(Answer,v=0 their-answer)"))
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
    }

    func testAnEarlyAnswerForAnotherCallIsNotAppliedToOurs() async {
        let r = await rig()
        let gate = Deferred<Void>()
        r.api.connectGate = gate
        let placed = Task { await r.calls.initiateCall(to: "254712345678", name: nil) }
        await r.settle()
        r.frame(("type", "outbound_answer"), ("call_id", "wacid.colleague"), ("sdp", "v=0 not-ours"))
        gate.complete(()); await r.settle()
        let v12 = await placed.value
        XCTAssertTrue(v12.isSuccess)
        XCTAssertFalse(r.media.peer.ops.contains { $0.hasPrefix("setRemote") })
    }

    func testSignOutMidCallTerminatesTheLiveCallOnly() async {
        let r = await rig()
        r.ring(); r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        await r.calls.endForSignOut()
        XCTAssertEqual(r.state.phase, .idle)
        XCTAssertTrue(r.api.log.contains("terminate wacid.1"))
        r.ring("wacid.2")
        await r.calls.endForSignOut()
        XCTAssertFalse(r.api.log.contains("terminate wacid.2"), "a ringing call is let go, not declined")
    }
}
