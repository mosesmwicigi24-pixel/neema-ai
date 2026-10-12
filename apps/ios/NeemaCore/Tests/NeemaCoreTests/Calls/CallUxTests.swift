import Foundation
import XCTest
@testable import NeemaCore

/// docs/CALLING_UX.md on Linux: the phases and their words, every outcome of
/// the wrap-up and whether it closes by itself, several agents on one call (a
/// colleague's answer by frame, by 409, by a re-read after the phone was
/// offline), the call-permission flow (never sent by itself), cancelling, no
/// answer, the second caller, audio routes that follow headsets, and the live
/// row updates that tell the card where the customer's chat is.
/// Android `calls/CallUxTest.kt`.
@MainActor
final class CallUxTests: XCTestCase {
    private var rigs: [CallRig] = []
    private let james = "254733444555"
    private let buds = AudioRoute(.bluetooth, name: "Jabra Talk 25")
    private let wired = AudioRoute(.wired)

    override func setUp() async throws {
        AppClock.pin(to: Date(timeIntervalSince1970: TimeInterval(CallRig.BASE) / 1000))
    }

    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
        AppClock.reset()
    }

    private func rig(me: String? = "agent-me") async -> CallRig {
        let r = CallRig(start: false)
        r.agentId = me
        r.calls.start()
        rigs.append(r)
        await r.settle()
        return r
    }

    private func live(_ r: CallRig, _ id: String = "wacid.1") async -> FakePeer {
        ring(r, id); r.calls.answer(); await r.settle(); r.media.peer.onEvent(.connected); await r.settle()
        return r.media.peer
    }
    private func ring(_ r: CallRig, _ id: String = "wacid.1", from: String = "254712345678", name: String = "Fr. Peter Kamau") {
        r.raw(#"{"type":"incoming_call","call_id":"\#(id)","from":"\#(from)","name":"\#(name)","at":"1","conversation_id":null}"#)
    }
    private func placeCall(_ r: CallRig, to: String = "254733444555", name: String = "Deacon James Mwangi") async -> Result<Void, Error> {
        let t = Task { await r.calls.initiateCall(to: to, name: name) }
        await r.settle()
        return await t.value
    }
    private func endFrame(_ r: CallRig, _ outcome: String) {
        r.raw(#"{"type":"call_ended","call_id":"\#(r.state.callId ?? "")","outcome":"\#(outcome)"}"#)
    }
    private func meta(status: String = "unknown", canCall: Bool? = nil, canRequest: Bool? = true, streak: Int = 0, at: String? = nil,
                      permanent: Bool = false, expires: String? = nil, revoked: Bool = false, left: Int? = nil) -> CallPermission {
        CallPermission(waId: james, status: status, expiresAt: expires, permanent: permanent, metaStatus: canCall == false ? "no_permission" : "temporary",
                       canCall: canCall, canRequest: canRequest, requestAvailableAt: at, callsLeftToday: left, revoked: revoked,
                       unansweredStreak: streak, source: "meta")
    }
    private func inHours(_ h: Int) -> String { Fmt.iso(AppClock.now() + Int64(h) * 3_600_000 - 1_000) }

    // ── The words (§3) ───────────────────────────────────────────────────
    func testEveryPhaseSaysItsOwnWords() {
        let s = CallUiState(from: "254712345678", name: "Fr. Peter Kamau")
        func with(_ p: CallPhase, seconds: Int = 0, reconnecting: Bool = false) -> String {
            var c = s; c.phase = p; c.seconds = seconds; c.reconnecting = reconnecting; return c.statusText()
        }
        XCTAssertEqual(with(.ringing), "Incoming…")
        XCTAssertEqual(with(.placing), "Calling…")
        XCTAssertEqual(with(.ringingOut), "Ringing…")
        XCTAssertEqual(with(.connecting), "Connecting…")
        XCTAssertEqual(with(.inCall, seconds: 252), "04:12")
        XCTAssertEqual(with(.inCall, seconds: 252, reconnecting: true), "Reconnecting…", "the timer never shows while nothing flows")
        func ended(_ o: CallOutcome, _ secs: Int = 0) -> String { var c = s; c.phase = .ended; c.outcome = o; c.seconds = secs; return c.statusText() }
        XCTAssertEqual(ended(.completed, 252), "Call ended · 4:12")
        XCTAssertEqual(ended(.answeredElsewhere(agent: "Ann Wanjiru")), "Answered by Ann")
        XCTAssertEqual(ended(.declined()), "Call declined")
        XCTAssertEqual(ended(.missed()), "Missed call")
        XCTAssertEqual(ended(.callback(saved: .saved)), "Saved to call back — find it under Calls")
        XCTAssertEqual(ended(.noAnswer), "No answer")
        XCTAssertEqual(ended(.cancelled), "Call cancelled")
        XCTAssertEqual(ended(.connectionLost, 133), "Call dropped · 2:13 — the connection was lost")
        XCTAssertEqual(ended(.failed(reason: "The customer's phone is off")), "The customer's phone is off")
        XCTAssertEqual(ended(.permissionNeeded), "Peter hasn't allowed WhatsApp calls yet")
        XCTAssertEqual(ended(.permissionRequested), "Call request sent — you'll be told when Peter taps Allow")
        XCTAssertEqual(ended(.micBlocked), "Microphone blocked — allow it in settings")
        XCTAssertEqual(CallUiState(phase: .ended, from: "254700000000", outcome: .permissionNeeded).statusText(),
                       "+254700000000 hasn't allowed WhatsApp calls yet", "no name: their number, as the web")
    }

    func testFirstNamesSkipTitles() {
        XCTAssertEqual(firstNameOf("Fr. Peter Kamau"), "Peter")
        XCTAssertEqual(firstNameOf("Grace"), "Grace")
        XCTAssertEqual(firstNameOf("  Rev.  Mary Achieng "), "Mary")
        XCTAssertNil(firstNameOf(nil)); XCTAssertNil(firstNameOf("  ")); XCTAssertNil(firstNameOf("+254712345678"))
    }

    func testNeutralWrapUpsCloseByThemselvesActionableOnesWait() {
        XCTAssertEqual(CallOutcome.completed.autoCloseMs, 8_000)
        XCTAssertEqual(CallOutcome.declined().autoCloseMs, 5_000)
        XCTAssertEqual(CallOutcome.permissionRequested.autoCloseMs, 6_000)
        XCTAssertEqual(CallOutcome.answeredElsewhere(agent: nil).autoCloseMs, 4_000)
        XCTAssertEqual(CallOutcome.cancelled.autoCloseMs, 2_000)
        for o in [CallOutcome.missed(), .noAnswer, .connectionLost, .failed(reason: "x"), .permissionNeeded, .micBlocked, .callback(saved: .notSaved)] {
            XCTAssertNil(o.autoCloseMs, "\(o) stays until the agent acts")
        }
    }

    func testWrapUpActionsFollowTheTable() {
        let s = CallUiState(phase: .ended, from: "254712345678", name: "Fr. Peter Kamau")
        func acts(_ o: CallOutcome, outbound: Bool = false) -> [WrapAction] { var c = s; c.outcome = o; c.outbound = outbound; return c.wrapActions() }
        XCTAssertEqual(acts(.completed), [.openChat, .callAgain, .done])
        XCTAssertEqual(acts(.answeredElsewhere(agent: "Ann")), [.done])
        XCTAssertEqual(acts(.declined()), [.message, .done])
        XCTAssertEqual(acts(.missed()), [.callBack, .message, .done])
        XCTAssertEqual(acts(.noAnswer, outbound: true), [.callAgain, .message, .done])
        XCTAssertEqual(acts(.connectionLost), [.callAgain, .openChat, .done])
        XCTAssertEqual(acts(.failed(reason: "x"), outbound: true), [.tryAgain, .message, .done])
        XCTAssertEqual(acts(.permissionNeeded, outbound: true), [.sendCallRequest, .message, .cancel])
        XCTAssertEqual(acts(.permissionRequested, outbound: true), [.message, .done])
        XCTAssertEqual(acts(.micBlocked), [.openSettings, .done])
        XCTAssertEqual(CallUiState(phase: .ended, outcome: .missed()).wrapActions(), [.done], "nobody to call or write to")
    }

    // ── Several agents, one call (§4) ────────────────────────────────────
    func testAColleaguesAnswerStopsThisPhoneAtOnce() async {
        let r = await rig()
        r.foreground.value = false; await r.settle()
        ring(r)
        XCTAssertTrue(r.ringer.ringing && r.ringer.showing)
        r.raw(#"{"type":"call_answered","call_id":"wacid.1","agent_id":"agent-ann","agent_name":"Ann Wanjiru","direction":"inbound"}"#)
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Ann Wanjiru"))
        XCTAssertEqual(r.state.statusText(), "Answered by Ann")
        XCTAssertFalse(r.ringer.ringing); XCTAssertFalse(r.ringer.showing)
        XCTAssertFalse(r.logged("terminate"), "Ann keeps her call")
        await r.advance(3_999)
        XCTAssertEqual(r.state.phase, .ended)
        await r.advance(2)
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testAColleaguesAnswerWhileThisPhoneIsAnsweringEndsItHereOnly() async {
        let r = await rig()
        r.media.gatherAtOnce = false
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting)
        // This agent's own answer echoed back changes nothing.
        r.raw(#"{"type":"call_answered","call_id":"wacid.1","agent_id":"agent-me","agent_name":"Moses","direction":"inbound"}"#)
        XCTAssertEqual(r.state.phase, .connecting)
        r.raw(#"{"type":"call_answered","call_id":"wacid.1","agent_id":"agent-ann","agent_name":"Ann","direction":"inbound"}"#)
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Ann"))
        XCTAssertTrue(r.media.peer.closed)
        XCTAssertFalse(r.logged("terminate"))
    }

    func testA409NamesTheWinner() async {
        let r = await rig()
        r.api.answerError = apiError(409, "POST", "/admin/calls/wacid.1/answer", #"{"detail":"call already answered by Ann Wanjiru"}"#)
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Ann Wanjiru"))
        XCTAssertEqual(r.state.statusText(), "Answered by Ann")
        XCTAssertFalse(r.logged("terminate"))
    }

    func testA410SaysTheCallAlreadyEnded() async {
        let r = await rig()
        r.api.answerError = apiError(410, "POST", "/admin/calls/wacid.1/answer", #"{"detail":"This call has already ended."}"#)
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.outcome, .missed(note: CallManager.CALL_GONE))
        XCTAssertEqual(r.state.statusText(), "Missed call")
        XCTAssertEqual(r.state.outcomeNote(), "This call has already ended", "the reason, under it (as the web)")
        XCTAssertEqual(r.state.wrapActions().first, .callBack)
        XCTAssertFalse(r.logged("terminate"))
    }

    func testCallEndedOutcomesMapToTheWrapUp() async {
        let r = await rig()
        var n = 0
        func endWith(_ outcome: String, _ setup: () async -> Void) async -> CallOutcome? {
            await setup()
            r.raw(#"{"type":"call_ended","call_id":"\#(r.state.callId ?? "")","outcome":"\#(outcome)","status":"COMPLETED","duration":42,"agent_id":"agent-ann","agent_name":"Ann Wanjiru"}"#)
            let o = r.state.outcome
            r.calls.dismiss(); await r.settle()
            await r.advance(13_000)
            return o
        }
        func ringFresh() { ring(r, "wacid.r\(n)"); n += 1 }
        func place() async { r.api.connectId = "wacid.o\(n)"; n += 1; _ = Task { await r.calls.initiateCall(to: "254733444555") }; await r.settle() }
        var o = await endWith("missed") { ringFresh() }
        XCTAssertEqual(o, .missed())
        o = await endWith("declined") { ringFresh() }
        XCTAssertEqual(o, .declined(agent: "Ann Wanjiru"))
        o = await endWith("callback") { ringFresh() }
        XCTAssertEqual(o, .callback(saved: .saved, agent: "Ann Wanjiru"))
        o = await endWith("completed") { ringFresh() }
        XCTAssertEqual(o, .answeredElsewhere(agent: "Ann Wanjiru"), "completed while it rang here: someone else took it")
        o = await endWith("completed") { _ = await live(r, "wacid.r\(n)"); n += 1 }
        XCTAssertEqual(o, .completed)
        o = await endWith("no_answer") { await place() }
        XCTAssertEqual(o, .noAnswer)
        o = await endWith("failed") { await place() }
        XCTAssertEqual(o, .failed(reason: CallManager.CALL_NOT_CONNECTED))
    }

    func testACallThatEndedWhileOfflineShowsItsRealOutcomeOnReconnect() async {
        let r = await rig()
        ring(r)
        r.connected.value = false; await r.settle()
        // Offline: Ann answered; no frame reached this phone.
        r.api.calls = [Call(id: "k1", callId: "wacid.1", waId: "254712345678", status: "answered", agentName: "Ann Wanjiru", startedAt: r.at(5_000))]
        // The log read fails on the way back (a flaky network): the call's own row still tells.
        r.api.listError = apiError(502, "GET", "/admin/calls", "<html>502</html>")
        r.connected.value = true; await r.settle()
        XCTAssertTrue(r.api.log.contains("get wacid.1"), "re-read its own row")
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Ann Wanjiru"))
        XCTAssertFalse(r.ringer.ringing)
    }

    func testAnOutboundCallThatRangOutWhileOfflineSaysNoAnswer() async {
        let r = await rig()
        let p = await placeCall(r)
        XCTAssertTrue(p.isSuccess)
        r.foreground.value = false; await r.settle()
        r.api.listError = apiError(0, "GET", "/admin/calls", "Failed to connect")
        r.api.calls = [Call(id: "k9", callId: "wacid.out1", direction: "outbound", status: "no_answer", startedAt: r.at(60_000))]
        r.foreground.value = true; await r.settle()
        XCTAssertEqual(r.state.outcome, .noAnswer)
        XCTAssertTrue(r.media.peer.closed)
    }

    func testALiveCallThatEndedWhileTheAppWasAwayIsCorrectedOnReturn() async {
        let r = await rig()
        _ = await live(r)
        await r.advance(30_000)
        r.foreground.value = false; await r.settle()
        r.api.calls = [Call(id: "k1", callId: "wacid.1", waId: "254712345678", status: "completed", duration: 31, startedAt: r.at(40_000))]
        r.foreground.value = true; await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .completed)
        XCTAssertTrue(r.media.peer.closed)
        XCTAssertFalse(r.logged("terminate"), "the server already ended it")
    }

    func testAReSyncOfACallStillGoingChangesNothing() async {
        let r = await rig()
        _ = await live(r)
        r.api.calls = [Call(id: "k1", callId: "wacid.1", status: "answered", agentId: "agent-me", startedAt: r.at(5_000))]
        r.connected.value = false; await r.settle(); r.connected.value = true; await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        // A row the server lost (404) changes nothing either.
        r.api.calls = []
        r.foreground.value = false; await r.settle(); r.foreground.value = true; await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
    }

    // ── Outbound: placing, ringing, cancel, no answer, failures ──────────
    func testPlacingThenRingingThenConnectingThenLive() async {
        let r = await rig()
        r.api.connectGate = Deferred<Void>()
        let placed = Task { await r.calls.initiateCall(to: "254733444555", name: "Deacon James Mwangi") }
        await r.settle()
        XCTAssertEqual(r.state.phase, .placing)
        XCTAssertEqual(r.state.statusText(), "Calling…")
        XCTAssertTrue(r.audio.inCall, "call audio from the start (the ringback)")
        r.api.connectGate!.complete(()); await r.settle()
        let pv = await placed.value
        XCTAssertTrue(pv.isSuccess)
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut)
        // The customer picked up: call_answered for our own call.
        r.raw(#"{"type":"call_answered","call_id":"wacid.out1","agent_id":"agent-me","agent_name":"Moses","direction":"outbound"}"#)
        XCTAssertEqual(r.state.phase, .connecting)
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
    }

    func testCancellingWhilePlacingOrRingingSaysCancelled() async {
        let r = await rig()
        r.media.gatherAtOnce = false
        let a = Task { await r.calls.initiateCall(to: "254733444555") }
        await r.settle()
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.outcome, .cancelled)
        await r.advance(2_600)
        let av = await a.value
        XCTAssertTrue(av.isSuccess)
        XCTAssertEqual(r.state.phase, .idle, "closes by itself")
        XCTAssertFalse(r.logged("connect") || r.logged("terminate"))

        r.media.gatherAtOnce = true
        let p = await placeCall(r)
        XCTAssertTrue(p.isSuccess)
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.outcome, .cancelled)
        XCTAssertTrue(r.api.log.contains("terminate wacid.out1"), "their phone stops ringing")
    }

    func testNoAnswerStaysWithCallAgain() async {
        let r = await rig()
        let p = await placeCall(r)
        XCTAssertTrue(p.isSuccess)
        r.raw(#"{"type":"call_ended","call_id":"wacid.out1","outcome":"no_answer","status":"REJECTED","duration":null,"direction":"outbound"}"#)
        XCTAssertEqual(r.state.outcome, .noAnswer)
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended)
        r.api.connectId = "wacid.out2"
        r.calls.redial(); await r.settle()
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut, "Call again places it again")
        XCTAssertEqual(r.state.callId, "wacid.out2")
        XCTAssertEqual(r.state.name, "Deacon James Mwangi")
        XCTAssertEqual(r.api.log.filter { $0.hasPrefix("connect") }.count, 2)
    }

    func testAConnectRefusalSaysTheServersReason() async {
        let r = await rig()
        r.api.connectError = apiError(502, "POST", "/admin/calls/connect", #"{"detail":"call failed: the customer's phone is switched off"}"#)
        let res = await placeCall(r)
        XCTAssertEqual(res.failureMessage, "Couldn't place the call")
        XCTAssertEqual(r.state.outcome, .failed(reason: "The customer's phone is switched off"))
        // An HTML error page is never shown as a reason.
        r.api.connectError = apiError(502, "POST", "/admin/calls/connect", "<html><body>502 Bad Gateway</body></html>")
        _ = await placeCall(r)
        XCTAssertEqual(r.state.outcome, .failed(reason: "Couldn't place the call"))
    }

    // ── Call permission: asked only on the agent's tap ───────────────────
    func testPermissionAlreadyRequestedSaysSo() async {
        let r = await rig()
        r.api.connectError = apiError(409, "POST", "/admin/calls/connect", #"{"detail":"This customer hasn't allowed calls yet."}"#)
        r.api.permissionStatus = "requested"
        _ = await placeCall(r)
        XCTAssertTrue(r.api.log.contains("permission 254733444555"))
        XCTAssertEqual(r.state.outcome, .permissionRequested)
        XCTAssertEqual(r.state.statusText(), "Call request sent — you'll be told when James taps Allow")
        XCTAssertFalse(r.logged("request-permission"))
    }

    func testSendCallRequestThenTheCustomerAllowsCalls() async {
        let r = await rig()
        r.api.connectError = apiError(409, "POST", "/admin/calls/connect", #"{"detail":"no permission"}"#)
        _ = await placeCall(r)
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        // Offline the first time: said on the card, still offered.
        r.api.permissionError = apiError(0, "POST", "/admin/calls/request-permission", "Failed to connect to neema")
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        XCTAssertEqual(r.state.error, "No connection — the call request wasn't sent")
        XCTAssertFalse(r.state.busy)
        r.api.permissionError = nil
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.api.log.filter { $0 == "request-permission 254733444555" }.count, 2)
        XCTAssertEqual(r.state.outcome, .permissionRequested)
        XCTAssertNil(r.state.error)
        // Another customer allowing calls isn't news for this phone.
        r.raw(#"{"type":"call_permission","wa_id":"254700000001","status":"granted","expires_at":null,"permanent":false}"#)
        XCTAssertNil(r.calls.permissionGranted.value)
        r.raw(#"{"type":"call_permission","wa_id":"254733444555","status":"granted","expires_at":"2026-10-03T10:00:00+00:00","permanent":false}"#)
        XCTAssertEqual(r.calls.permissionGranted.value, PermissionGrant(waId: "254733444555", name: "Deacon James Mwangi"))
        XCTAssertEqual(r.state.phase, .idle, "the banner replaces the stale wrap-up")
        // "Call now".
        r.api.connectError = nil
        r.calls.callGranted(); await r.settle()
        XCTAssertNil(r.calls.permissionGranted.value)
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut)
        XCTAssertEqual(r.state.from, "254733444555")
    }

    // ── The second caller ────────────────────────────────────────────────
    func testASecondCallerIsABannerThatCanBeDeclinedOrKeptForLater() async {
        let r = await rig()
        _ = await live(r)
        ring(r, "wacid.2", from: "254799999999", name: "Sr. Agnes Wairimu")
        XCTAssertEqual(r.state.waiting, WaitingCall(callId: "wacid.2", from: "254799999999", name: "Sr. Agnes Wairimu"))
        XCTAssertEqual(r.state.callId, "wacid.1")
        r.calls.declineWaiting(); await r.settle()
        XCTAssertNil(r.state.waiting)
        XCTAssertTrue(r.api.log.contains("terminate wacid.2"))
        XCTAssertEqual(r.state.phase, .inCall)

        ring(r, "wacid.3", from: "254788888888", name: "Bro. Kevin Ouma")
        r.calls.callbackWaiting(); await r.settle()
        XCTAssertTrue(r.api.log.contains("callback wacid.3"))
        XCTAssertNil(r.state.waiting)

        ring(r, "wacid.4", from: "254777777777", name: "Mrs. Faith Chebet")
        // They gave up: the banner goes with them.
        r.raw(#"{"type":"call_ended","call_id":"wacid.4","outcome":"missed"}"#)
        XCTAssertNil(r.state.waiting)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.outcome, .completed, "nobody waits: the wrap-up of this call stays")
    }

    func testEndAndAnswerTakesTheSecondCaller() async {
        let r = await rig()
        _ = await live(r)
        ring(r, "wacid.2", from: "254799999999", name: "Sr. Agnes Wairimu")
        r.calls.endAndAnswer(); await r.settle()
        XCTAssertTrue(r.api.log.contains("terminate wacid.1"))
        XCTAssertTrue(r.api.log.contains("answer wacid.2"))
        XCTAssertEqual(r.state.callId, "wacid.2")
        XCTAssertEqual(r.state.phase, .connecting)
    }

    func testANewRingReplacesTheWrapUpAtOnce() async {
        let r = await rig()
        ring(r); endFrame(r, "missed")
        XCTAssertEqual(r.state.outcome, .missed())
        ring(r, "wacid.2", from: "254799999999", name: "Sr. Agnes Wairimu")
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.state.name, "Sr. Agnes Wairimu")
        XCTAssertNil(r.state.outcome)
    }

    // ── Audio routes follow headsets (§ build brief 3) ───────────────────
    func testAConnectedHeadsetTakesTheCallFromTheStart() async {
        let r = await rig()
        r.audio.plug(buds); await r.settle()
        _ = await live(r)
        XCTAssertEqual(r.state.route, buds)
        XCTAssertEqual(r.audio.route, buds)
        XCTAssertTrue(r.state.routeChoice)
    }

    func testHeadsetsComeAndGoMidCallWithoutEverBlastingTheSpeaker() async {
        let r = await rig()
        _ = await live(r)
        XCTAssertEqual(r.audio.route, .earpiece)
        r.audio.plug(wired); await r.settle()
        XCTAssertEqual(r.audio.route, wired, "plugged in: the call follows it")
        r.audio.unplug(wired); await r.settle()
        XCTAssertEqual(r.audio.route, .earpiece, "unplugged: back to the earpiece, never the speaker")
        r.audio.plug(buds); await r.settle()
        XCTAssertEqual(r.state.route, buds)
        r.audio.plug(wired); await r.settle()
        XCTAssertEqual(r.state.route, wired)
        r.audio.unplug(wired); await r.settle()
        XCTAssertEqual(r.state.route, buds, "the other headset is still there")
        // The agent chose the speaker; a headset that goes (not in use) changes nothing.
        r.calls.selectRoute(.speaker)
        r.audio.unplug(buds); await r.settle()
        XCTAssertEqual(r.audio.route, .speaker)
        r.calls.toggleSpeaker()
        XCTAssertEqual(r.audio.route, .earpiece)
    }

    func testATabletWithoutAnEarpieceUsesItsSpeaker() async {
        let r = await rig()
        r.audio.routes.value = [.speaker]; await r.settle()
        _ = await live(r)
        XCTAssertEqual(r.audio.route, .speaker)
        r.audio.plug(wired); await r.settle()
        XCTAssertEqual(r.audio.route, wired)
        r.audio.unplug(wired); await r.settle()
        XCTAssertEqual(r.audio.route, .speaker)
    }

    func testTheSpeakerToggleReturnsToTheHeadset() async {
        let r = await rig()
        r.audio.plug(buds); await r.settle()
        _ = await live(r)
        r.calls.toggleSpeaker()
        XCTAssertEqual(r.audio.route, .speaker)
        r.calls.toggleSpeaker()
        XCTAssertEqual(r.audio.route, buds)
        r.calls.selectRoute(AudioRoute(.wired))
        XCTAssertEqual(r.audio.route, buds, "not plugged in: ignored")
    }

    // ── The call card's other actions ────────────────────────────────────
    func testARowUpdateTellsTheCardWhereTheChatIs() async {
        let r = await rig()
        ring(r, name: "")
        r.raw(#"{"type":"call_update","call":{"call_id":"wacid.1","wa_id":"254712345678","name":"Fr. Peter Kamau","person_id":"p1","conversation_id":"c1","status":"ringing","unknown_key":[1,2]}}"#)
        XCTAssertEqual(r.state.conversationId, "c1")
        XCTAssertEqual(r.state.personId, "p1")
        XCTAssertEqual(r.state.name, "Fr. Peter Kamau")
        XCTAssertEqual(r.state.phase, .ringing)
        // A broken row is ignored.
        r.raw(#"{"type":"call_update","call":"nope"}"#)
        XCTAssertEqual(r.state.phase, .ringing)
    }

    func testOpenChatMinimisesALiveCallAndClosesAWrapUp() async {
        let r = await rig()
        _ = await live(r)
        XCTAssertEqual(r.calls.openChat(), "254712345678")
        XCTAssertTrue(r.state.minimised)
        XCTAssertEqual(r.state.phase, .inCall, "still on the call")
        r.calls.expand()
        XCTAssertFalse(r.state.minimised)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.calls.openChat(), "254712345678")
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testTheOngoingNotificationsEndHangsUp() async {
        let r = await rig()
        _ = await live(r)
        r.calls.minimise()
        r.calls.handleAction("end", id: nil); await r.settle()
        XCTAssertEqual(r.state.outcome, .completed)
        XCTAssertTrue(r.api.log.contains("terminate wacid.1"))
        XCTAssertTrue(r.state.minimised, "the minimised bar shows the wrap-up")
    }

    func testRecordingShowsOnlyWhileItRunsThenSaysWhatHappensNext() async {
        let r = await rig()
        r.api.ice.transcribe = true; r.api.ice.autoTranscribe = true
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertFalse(r.state.recording, "not yet connected")
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertTrue(r.state.recording)
        r.calls.hangup(); await r.settle()
        XCTAssertFalse(r.state.recording)
        XCTAssertEqual(r.state.recordingNote, CallManager.RECORDING_SAVED_AUTO)
        // Recording switched off on the server: nothing is said.
        await r.advance(13_000)
        r.api.ice.record = false
        _ = await live(r, "wacid.2")
        XCTAssertFalse(r.state.recording)
        r.calls.hangup(); await r.settle()
        XCTAssertNil(r.state.recordingNote)
    }

    // ── 2026-09-27 platform refresh (CALLING_UX.md §2.1) ─────────────────
    func testPermissionTruthSkipsTheDoomedConnect() async {
        let r = await rig()
        r.api.permission = meta(canCall: false)
        let res = await placeCall(r)
        XCTAssertTrue(r.api.log.contains("permission \(james)"))
        XCTAssertFalse(r.logged("connect"), "no connect Meta would refuse")
        XCTAssertTrue(r.media.peers.isEmpty, "no peer, no microphone")
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        XCTAssertEqual((res.failure as? CallError)?.shown, true)
        XCTAssertEqual(r.state.wrapActions(), [.sendCallRequest, .message, .cancel])
        // Asked already (and still waiting): the card says that instead.
        await r.advance(10_000)
        r.calls.dismiss()
        r.api.permission = meta(status: "requested", canCall: false, canRequest: false)
        _ = await placeCall(r)
        XCTAssertEqual(r.state.outcome, .permissionRequested)
        XCTAssertFalse(r.logged("connect"))
    }

    func testASlowOrFailedPermissionReadNeverHoldsTheCallUp() async {
        let r = await rig()
        r.api.permissionGate = Deferred<Void>()
        let placed = Task { await r.calls.initiateCall(to: james, name: "Deacon James Mwangi") }
        await r.settle()
        XCTAssertEqual(r.state.phase, .placing, "Calling… at once")
        XCTAssertFalse(r.logged("connect"))
        await r.advance(CallManager.PERMISSION_READ_MS + 1)
        let pv = await placed.value
        XCTAssertTrue(pv.isSuccess)
        XCTAssertTrue(r.api.log.contains("connect \(james)"), "placed as before")
        XCTAssertNil(r.state.permission)
        // A read that fails outright: placed as before too.
        r.calls.hangup(); await r.settle(); await r.advance(3_000)
        r.api.permissionGate = nil
        r.api.permissionReadError = apiError(502, "GET", "/admin/calls/permission")
        r.api.connectId = "wacid.out2"
        let p2 = await placeCall(r, to: james)
        XCTAssertTrue(p2.isSuccess)
        XCTAssertEqual(r.api.log.filter { $0 == "connect \(james)" }.count, 2)
    }

    func testCallingSaysRingingOnlyWhenMetaSaysItRings() async {
        let r = await rig()
        let p = await placeCall(r)
        XCTAssertTrue(p.isSuccess)
        XCTAssertEqual(r.state.statusText(), "Calling…")
        r.raw(#"{"type":"call_status","call_id":"wacid.other","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .placing, "someone else's call")
        r.raw(#"{"type":"call_status","call_id":"wacid.out1","status":"accepted"}"#)
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"wacid.out1","status":"ringing"}"#)
        XCTAssertEqual(r.state.statusText(), "Ringing…")
        // The customer picks up straight from "Calling…" too (no ringing frame ever came).
        r.calls.hangup(); await r.settle(); await r.advance(3_000)
        r.api.connectId = "wacid.out2"
        _ = await placeCall(r)
        r.raw(#"{"type":"call_answered","call_id":"wacid.out2","agent_id":"agent-me","agent_name":"Moses","direction":"outbound"}"#)
        XCTAssertEqual(r.state.phase, .connecting)
        // A ringing frame that beat connect's reply is applied once the id is known.
        r.calls.hangup(); await r.settle(); await r.advance(3_000)
        r.api.connectId = "wacid.out3"
        r.api.connectGate = Deferred<Void>()
        let placed = Task { await r.calls.initiateCall(to: james, name: "Deacon James Mwangi") }
        await r.settle()
        r.raw(#"{"type":"call_status","call_id":"wacid.out3","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .placing)
        r.api.connectGate!.complete(()); await r.settle()
        let pv = await placed.value
        XCTAssertTrue(pv.isSuccess)
        XCTAssertEqual(r.state.phase, .ringingOut)
    }

    func testADeclinedCallSaysSoWithMessageAndDone() async {
        let r = await rig()
        _ = await placeCall(r)
        r.raw(#"{"type":"call_ended","call_id":"wacid.out1","outcome":"rejected","status":"REJECTED","direction":"outbound"}"#)
        XCTAssertEqual(r.state.outcome, .rejected)
        XCTAssertEqual(r.state.statusText(), "James declined the call")
        XCTAssertEqual(r.state.wrapActions(), [.message, .done])
        XCTAssertNil(CallOutcome.rejected.autoCloseMs, "the agent decides: it stays")
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "outbound", status: "rejected")).label, "Declined by customer")
        // A no_answer corrected to rejected a moment later: the latest word wins.
        r.calls.dismiss()
        r.api.connectId = "wacid.out2"
        _ = await placeCall(r)
        r.raw(#"{"type":"call_ended","call_id":"wacid.out2","outcome":"no_answer","direction":"outbound"}"#)
        XCTAssertEqual(r.state.outcome, .noAnswer)
        r.raw(#"{"type":"call_ended","call_id":"wacid.out2","outcome":"rejected","direction":"outbound"}"#)
        XCTAssertEqual(r.state.outcome, .rejected)
    }

    func testUnansweredStreakCautionsButNeverBlocks() async {
        let r = await rig()
        r.api.permission = meta(status: "granted", canCall: true, streak: 3)
        let p = await placeCall(r)
        XCTAssertTrue(p.isSuccess)
        XCTAssertTrue(r.api.log.contains("connect \(james)"), "never blocking")
        XCTAssertEqual(r.state.callCaution(), "James missed your last 3 calls — WhatsApp removes call permission after 4 in a row. Consider a message first.")
        r.raw(#"{"type":"call_status","call_id":"wacid.out1","status":"ringing"}"#)
        XCTAssertNotNil(r.state.callCaution())
        r.raw(#"{"type":"call_answered","call_id":"wacid.out1","agent_id":"agent-me","direction":"outbound"}"#)
        XCTAssertNil(r.state.callCaution(), "only before it goes through")
        XCTAssertNil(CallUiState(phase: .placing, outbound: true, permission: meta(streak: 1)).callCaution())
        // WhatsApp's revoke-after-4 rule: never warned about on a Messenger call.
        XCTAssertNil(CallUiState(phase: .placing, channel: "messenger", outbound: true, permission: meta(streak: 3)).callCaution())
    }

    func testTemplateRequiredOffersSettingsToAdminsOnly() async {
        let r = await rig()
        r.calls.canManageSettings = { true }
        r.api.permission = meta(canCall: false)
        _ = await placeCall(r)
        let detail = "James hasn't messaged in 24 hours — WhatsApp only allows a call request by template then. An admin can create it in Settings → WhatsApp calling."
        r.api.permissionError = refusal(409, "/admin/calls/request-permission", detail, "template_required", "admin", extra: #","route":"template""#)
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.state.error, detail)
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        XCTAssertEqual(r.state.wrapActions(), [.callingSettings, .message, .cancel])
        // Asking again can't work: a second tap sends nothing.
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.api.log.filter { $0.hasPrefix("request-permission") }.count, 1)
        // Not an admin: no Settings button.
        var agent = r.state
        let ref = r.state.refusal!
        agent.refusal = CallRefusal(code: ref.code, action: ref.action, detail: ref.detail, adminCanFix: false)
        XCTAssertEqual(agent.wrapActions(), [.message, .cancel])
    }

    func testTheRequestLimitSaysWhenTheyCanAskAgain() async {
        let r = await rig()
        r.api.permission = meta(canCall: false)
        _ = await placeCall(r)
        r.api.permissionError = refusal(409, "/admin/calls/request-permission",
                                        "You've asked this customer recently — WhatsApp allows 1 request a day and 2 a week.", "138009", "wait",
                                        extra: ",\"request_available_at\":\"\(inHours(5))\"")
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertNil(r.state.error)
        XCTAssertEqual(r.state.sendRequestBlocked(), "You can ask again in 5 h")
        XCTAssertTrue(r.state.outcomeNote()!.contains("You can ask again in 5 h"))
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.api.log.filter { $0.hasPrefix("request-permission") }.count, 1, "the button waits")
        // Known before anyone taps: Meta's can_request=false.
        let known = CallUiState(phase: .ended, from: james, outcome: .permissionNeeded, permission: meta(canCall: false, canRequest: false, at: inHours(3)))
        XCTAssertEqual(known.sendRequestBlocked(), "You can ask again in 3 h")
    }

    func testAlreadyPermittedOffersCallNow() async {
        let r = await rig()
        r.api.permission = meta(canCall: false)
        _ = await placeCall(r)
        r.api.requestResponse = PermissionRequestResponse(permission: CallPermission(waId: james, status: "granted", permanent: true), alreadyPermitted: true)
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.state.outcome, .alreadyAllowed)
        XCTAssertEqual(r.state.statusText(), "James already allows calls — call now")
        XCTAssertEqual(r.state.wrapActions(), [.callNow, .message, .done])
        r.api.permission = nil
        r.calls.callNow(); await r.settle()
        XCTAssertTrue(r.api.log.contains("connect \(james)"))
    }

    func testEveryServerActionMapsToTheWrapUp() async {
        let r = await rig()
        func fail(_ code: String, _ action: String, _ detail: String) async {
            r.calls.dismiss()
            r.api.connectError = refusal(502, "/admin/calls/connect", "call failed: \(detail)", code, action)
            _ = Task { await r.calls.initiateCall(to: james, name: "Deacon James Mwangi") }
            await r.settle()
        }
        await fail("190", "admin", "WhatsApp access token expired — an admin must renew it")
        XCTAssertEqual(r.state.outcome, .failed(reason: "WhatsApp access token expired — an admin must renew it", action: "admin"))
        XCTAssertEqual(r.state.wrapActions(), [.message, .done])
        XCTAssertEqual(r.state.outcomeNote(), CallManager.ADMIN_MUST_ACT)
        await fail("meta_unavailable", "retry", "WhatsApp isn't answering right now — try again.")
        XCTAssertEqual(r.state.wrapActions(), [.tryAgain, .message, .done])
        XCTAssertNil(r.state.outcomeNote())
        await fail("rate_limited", "wait", "WhatsApp is rate-limiting us — try again in a minute.")
        XCTAssertEqual(r.state.wrapActions(), [.message, .done])
        XCTAssertEqual(r.state.outcomeNote(), CallManager.WAIT_A_MOMENT)
        await fail("138000", "none", "This customer can't take WhatsApp calls.")
        XCTAssertEqual(r.state.wrapActions(), [.message, .done])
        XCTAssertEqual(r.state.outcomeNote(), CallManager.MESSAGE_INSTEAD)
        await fail("138006", "request_permission", "This customer hasn't allowed calls yet.")
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        XCTAssertEqual(r.state.wrapActions().first, .sendCallRequest)
    }

    func testStructuredRefusalsReadTheirCodeActionAndFields() {
        let e = refusal(409, "/admin/calls/request-permission", "x", "138009", "wait", extra: #","request_available_at":"2026-09-28T10:00:00+00:00""#)
        XCTAssertEqual(e.code, "138009"); XCTAssertEqual(e.action, "wait"); XCTAssertEqual(e.detail, "x")
        XCTAssertEqual(e.field("request_available_at"), "2026-09-28T10:00:00+00:00")
        // The header alone (a body without `code`), and an older body with neither.
        XCTAssertEqual(ApiError(status: 502, method: "POST", path: "/p", body: #"{"detail":"call failed: x"}"#, reasonHeader: "190").code, "190")
        let old = apiError(409, "POST", "/p", #"{"detail":"no permission"}"#)
        XCTAssertNil(old.code); XCTAssertNil(old.action); XCTAssertEqual(old.detail, "no permission")
        XCTAssertNil(apiError(502, "POST", "/p", "<html>bad gateway</html>").code)
    }

    func testThePermissionIsSaidHonestly() {
        let now = AppClock.now()
        func lines(_ p: CallPermission) -> [String] { permissionLines(p, first: "James", now: now) }
        XCTAssertEqual(lines(meta(status: "granted", canCall: true, permanent: true)), ["Allowed permanently"])
        XCTAssertEqual(lines(meta(status: "granted", canCall: true, expires: "2026-10-03T10:00:00+00:00")), ["Allowed until 3 Oct 2026"])
        var requested = meta(status: "requested", canCall: false, canRequest: false)
        requested.at = Fmt.iso(now - 2 * 3_600_000)
        XCTAssertEqual(lines(requested), ["Request sent 2h ago — waiting for James"])
        XCTAssertEqual(lines(meta(status: "denied", canCall: false)), ["James declined calls"])
        XCTAssertEqual(lines(meta(status: "denied", canCall: false, revoked: true)), ["Permission revoked after unanswered calls"])
        XCTAssertEqual(lines(meta(status: "denied", canCall: false, canRequest: false, at: inHours(5))), ["James declined calls", "You can ask again in 5 h"])
        XCTAssertEqual(lines(meta(status: "granted", canCall: true, permanent: true, left: 3)), ["Allowed permanently", "Calls left today: 3"], "only when Meta gave it")
        XCTAssertTrue(lines(meta()).isEmpty)
    }

    func testAPermissionFrameUpdatesTheCardHonestly() async {
        let r = await rig()
        r.api.permission = meta(canCall: false)
        _ = await placeCall(r)
        r.raw(#"{"type":"call_permission","wa_id":"\#(james)","status":"denied","revoked":true,"reason":"automatic"}"#)
        XCTAssertTrue(r.state.permission!.revoked)
        XCTAssertTrue(r.state.outcomeNote()!.hasPrefix("Permission revoked after unanswered calls"))
    }

    func testVoicemailShowsOnTheRowAndThePill() throws {
        let row = try NeemaJSON.decode(Call.self, from: #"{"call_id":"wacid.9","wa_id":"\#(james)","direction":"inbound","status":"missed","has_voicemail":true}"#)
        XCTAssertTrue(row.hasVoicemail)
        XCTAssertEqual(threadCallLabel("Missed call", row), "Missed call · voicemail")
        XCTAssertEqual(threadCallLabel("", row), "Missed · voicemail")
        var plain = row; plain.hasVoicemail = false
        XCTAssertEqual(threadCallLabel("Missed call", plain), "Missed call")
        XCTAssertFalse(try NeemaJSON.decode(Call.self, from: #"{"call_id":"x","status":"missed"}"#).hasVoicemail, "an older row")
    }

    func testWhatsAppsOwnTranscriptionIsSaidHonestly() async {
        let r = await rig()
        r.api.ice.record = false; r.api.ice.metaTranscription = true
        _ = await live(r)
        XCTAssertTrue(r.state.metaTranscription, "the card says WhatsApp records it")
        await r.advance(5_000)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.recordingNote, CallManager.META_SUMMARY)
        // Recorded here as well: the usual note, with the summary promised.
        await r.advance(13_000)
        r.api.ice.record = true; r.api.ice.metaTranscription = true
        _ = await live(r, "wacid.2")
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.recordingNote, CallManager.RECORDING_SAVED_AUTO)
    }

    func testTwoSpeakerTranscriptsSplitIntoTurns() {
        let turns = transcriptTurns("Agent: Hello, Bethany House.\n\ncustomer:  Hi, I need a cassock size 54 please.")?.map { "\($0.speaker)|\($0.text)" }
        XCTAssertEqual(turns, ["Agent|Hello, Bethany House.", "Customer|Hi, I need a cassock size 54 please."])
        XCTAssertNil(transcriptTurns("Hello there, this is a transcript."), "plain text stays plain")
        XCTAssertNil(transcriptTurns("Agent: Good afternoon.\nCaller: Hello, Father Peter here."), "another labelling stays plain")
    }

    func testACallingRestrictionRaisesTheBanner() async {
        let r = await rig()
        XCTAssertNil(r.calls.restriction.value)
        r.raw(#"{"type":"calling_restricted","event":"restricted","reasons":["LOW_PICKUP_RATE"],"at":"2026-09-27T09:00:00Z"}"#)
        XCTAssertEqual(r.calls.restriction.value, CallingRestriction(reasons: ["LOW_PICKUP_RATE"], at: "2026-09-27T09:00:00Z"))
        XCTAssertEqual(restrictionText(r.calls.restriction.value!), "Low pickup rate. Calls you place may fail until it lifts (up to 7 days).")
        r.calls.dismissRestriction()
        XCTAssertNil(r.calls.restriction.value)
    }

    // ── The contract's words (§2.1) and a Messenger call's (§2.0) ────────
    func testTheWordsMatchTheContractAndTheWeb() {
        let james = CallUiState(from: "254733444555", name: "Deacon James Mwangi", outbound: true)
        XCTAssertEqual(callRowWords(Call(callId: "x", direction: "outbound", status: "rejected")).label, "Declined by customer")
        var declined = james; declined.phase = .ended; declined.outcome = .rejected; declined.conversationId = "conv-james"
        XCTAssertEqual(declined.statusText(), "James declined the call")
        XCTAssertEqual(declined.wrapActions(), [.message, .done])
        var ringing = james; ringing.phase = .ringingOut; ringing.permission = CallPermission(status: "granted", unansweredStreak: 3)
        XCTAssertEqual(ringing.callCaution(), "James missed your last 3 calls — WhatsApp removes call permission after 4 in a row. Consider a message first.")
        XCTAssertEqual(CallManager.META_SUMMARY, "Recorded by WhatsApp — summary in a minute")
        // Messenger: never a PSID, the app named, the permission words its own.
        let m = CallUiState(from: "7788990011", channel: "messenger")
        XCTAssertEqual(m.who, "Messenger caller")
        XCTAssertEqual(m.app, "Messenger")
        XCTAssertNil(m.number)
        var needed = m; needed.phase = .ended; needed.outcome = .permissionNeeded
        XCTAssertEqual(needed.statusText(), "This customer hasn't allowed Messenger calls yet")
        var rejected = m; rejected.phase = .ended; rejected.outcome = .rejected; rejected.outbound = true
        XCTAssertEqual(rejected.statusText(), "The customer declined the call")
        var grace = needed; grace.name = "Grace Wanjiku"
        XCTAssertEqual(grace.statusText(), "Grace hasn't allowed Messenger calls yet")
        XCTAssertEqual(WaitingCall(callId: "c_1", from: "7788990011", name: nil, channel: "messenger").who, "Messenger caller")
        XCTAssertEqual(WaitingCall(callId: "w_1", from: "254712345678", name: nil).who, "+254712345678")
        XCTAssertEqual(permissionLines(CallPermission(status: "granted"), first: "James", now: AppClock.now()).first, "Allowed calls")
        XCTAssertEqual(permissionLines(CallPermission(status: "unknown", metaStatus: "no_permission"), first: "James", now: AppClock.now()).first,
                       "James hasn't allowed calls yet")
    }
}
