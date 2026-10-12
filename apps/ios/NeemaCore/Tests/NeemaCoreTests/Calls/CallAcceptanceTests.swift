import Foundation
import XCTest
@testable import NeemaCore

/// The owner's Final Acceptance Test (docs/CALLING_UX.md), scenario by
/// scenario, on the real `CallManager` with the fake API, frames, socket,
/// foreground, peer, ringer, audio and clock: the phase, the outcome, the
/// exact words the agent reads, the actions the card offers, what the ringer
/// and alert did, and every request that went to the server.
/// Android `calls/CallAcceptanceTest.kt` (the console scenarios 17, 19, 20
/// and 22 live with the calls console's tests).
@MainActor
final class CallAcceptanceTests: XCTestCase {
    private var rigs: [CallRig] = []
    private let peter = "254712345678"
    private let james = "254733444555"
    private let grace = "7788990011"

    override func tearDown() async throws {
        for r in rigs { r.stop() }
        rigs.removeAll()
        await drain()
    }

    private func rig() async -> CallRig {
        let r = CallRig(start: false)
        r.agentId = "agent-me"
        r.agentName = "Moses Mwicigi"
        r.calls.start()
        rigs.append(r)
        await r.settle()
        return r
    }

    private func err(_ status: Int, _ path: String, _ detail: String) -> ApiError { ApiError(status: status, method: "POST", path: path, body: "{\"detail\":\(jsonString(detail))}") }
    private func offline(_ path: String) -> ApiError { ApiError(status: 0, method: "GET", path: path, body: "Failed to connect to neema.bethanyhouse.co.ke") }
    private func timeout(_ path: String) -> ApiError { ApiError(status: 0, method: "POST", path: path, body: "timed out after 30s") }

    private func ring(_ r: CallRig, _ id: String = "wacid.1", from: String? = nil, name: String = "Fr. Peter Kamau", conv: String? = "conv-peter") {
        let f = from ?? peter
        let c = conv.map { "\"\($0)\"" } ?? "null"
        r.raw(#"{"type":"incoming_call","call_id":"\#(id)","from":"\#(f)","name":"\#(name)","at":"1","channel":"whatsapp","conversation_id":\#(c)}"#)
    }
    private func answered(_ r: CallRig, _ id: String, _ agentId: String, _ agent: String, direction: String = "inbound") {
        r.raw(#"{"type":"call_answered","call_id":"\#(id)","agent_id":"\#(agentId)","agent_name":"\#(agent)","direction":"\#(direction)"}"#)
    }
    private func ended(_ r: CallRig, _ id: String, _ outcome: String, agentId: String? = nil, agent: String? = nil, duration: Int? = nil) {
        let d = duration.map { "\($0)" } ?? "null"
        let aid = agentId.map { "\"\($0)\"" } ?? "null"
        let an = agent.map { "\"\($0)\"" } ?? "null"
        r.raw(#"{"type":"call_ended","call_id":"\#(id)","outcome":"\#(outcome)","status":"COMPLETED","duration":\#(d),"direction":"inbound","agent_id":\#(aid),"agent_name":\#(an)}"#)
    }
    /// Ring, answer, audio flowing.
    private func live(_ r: CallRig, _ id: String = "wacid.1") async -> FakePeer {
        ring(r, id); r.calls.answer(); await r.settle()
        r.media.peer.onEvent(.connected); await r.settle()
        return r.media.peer
    }
    private func place(_ r: CallRig, to: String? = nil, name: String = "Deacon James Mwangi") async -> Task<Result<Void, Error>, Never> {
        let t = Task { await r.calls.initiateCall(to: to ?? self.james, name: name) }
        await r.settle()
        return t
    }
    private func requests(_ r: CallRig) -> Set<String> { Set(r.api.log.filter { !$0.hasPrefix("list") }) }

    // ── 1. An incoming call, one agent ───────────────────────────────────
    func testS01IncomingCallOneAgent() async {
        let r = await rig()
        ring(r)
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.state.who, "Fr. Peter Kamau")
        XCTAssertEqual(r.words, "Incoming…")
        XCTAssertTrue(r.ringer.ringing, "the phone rings")
        XCTAssertTrue(r.ringer.posted.isEmpty, "on screen: the card is the alert, no notification")
        r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting)
        XCTAssertEqual(r.words, "Connecting…")
        XCTAssertFalse(r.ringer.ringing, "ringing stops the moment Answer is tapped")
        XCTAssertEqual(requests(r), ["ice-config", "offer wacid.1", "answer wacid.1"])
        XCTAssertEqual(r.api.lastAnswerSdp, "setLocal(Answer,v=0 our-answer)+candidates", "our answer carries the gathered candidates")
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(r.words, "00:00")
        XCTAssertTrue(r.state.recording, "● Recording only while a recording really runs")
        await r.advance(65_000)
        XCTAssertEqual(r.words, "01:05")
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.outcome, .completed)
        XCTAssertEqual(r.words, "Call ended · 1:05")
        XCTAssertEqual(r.state.wrapActions(), [.openChat, .callAgain, .done])
        XCTAssertEqual(r.count("terminate wacid.1"), 1)
        XCTAssertFalse(r.audio.inCall)
        await r.advance(8_001)
        XCTAssertEqual(r.state.phase, .idle, "a neutral wrap-up closes by itself")
    }

    // ── 2. Several agents: a colleague answers ───────────────────────────
    func testS02ColleagueAnswersFirst() async {
        let r = await rig()
        ring(r)
        answered(r, "wacid.1", "agent-ann", "Ann Wanjiru")
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Ann Wanjiru"))
        XCTAssertEqual(r.words, "Answered by Ann")
        XCTAssertFalse(r.ringer.ringing, "ringing stopped")
        XCTAssertFalse(r.ringer.showing)
        XCTAssertEqual(r.count("answer"), 0, "no answer POST from this phone")
        XCTAssertEqual(r.count("terminate"), 0)
        XCTAssertEqual(r.state.wrapActions(), [.done])
        await r.advance(4_001)
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testS02AnsweredOnMyOtherDeviceSaysSo() async {
        let r = await rig()
        ring(r)
        answered(r, "wacid.1", "agent-me", "Moses Mwicigi")
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Moses Mwicigi", mine: true))
        XCTAssertEqual(r.words, "Answered on your other device")
        // A colleague's answer never says "your other device".
        ring(r, "wacid.2"); answered(r, "wacid.2", "agent-ann", "Ann Wanjiru")
        XCTAssertEqual(r.words, "Answered by Ann")
    }

    // ── 3. Decline ───────────────────────────────────────────────────────
    func testS03Decline() async {
        let r = await rig()
        ring(r)
        r.calls.hangup(); await r.settle()   // the Decline button ("Decline call")
        XCTAssertEqual(r.state.outcome, .declined())
        XCTAssertEqual(r.words, "Call declined")
        XCTAssertEqual(r.state.wrapActions(), [.message, .done])
        XCTAssertEqual(r.count("terminate wacid.1"), 1, "declined for the whole team")
        XCTAssertFalse(r.ringer.ringing)
        await r.advance(5_001)
        XCTAssertEqual(r.state.phase, .idle)
        // The still-"ringing" row must not ring it again.
        r.api.calls = [Call(id: "k1", callId: "wacid.1", waId: peter, status: "ringing", startedAt: r.at(8_000))]
        await r.calls.pollOnce(); await r.settle()
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testS03DeclineFromAColleagueSaysWho() async {
        let r = await rig()
        ring(r)
        ended(r, "wacid.1", "declined", agentId: "agent-ann", agent: "Ann Wanjiru")
        XCTAssertEqual(r.words, "Declined by Ann")
    }

    // ── 4. Missed ────────────────────────────────────────────────────────
    func testS04Missed() async {
        let r = await rig()
        ring(r)
        ended(r, "wacid.1", "missed")
        XCTAssertEqual(r.state.outcome, .missed())
        XCTAssertEqual(r.words, "Missed call")
        XCTAssertEqual(r.state.wrapActions(), [.callBack, .message, .done])
        XCTAssertFalse(r.ringer.ringing)
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended, "a call back is owed: the card waits")
        // Call back: straight out to them.
        r.calls.redial(); await r.settle()
        XCTAssertEqual(r.count("connect \(peter)"), 1)
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut)
        XCTAssertEqual(r.state.who, "Fr. Peter Kamau", "the same customer, the same name")
    }

    // ── 5. Outgoing ──────────────────────────────────────────────────────
    func testS05Outgoing() async {
        let r = await rig()
        r.api.connectGate = Deferred<Void>()
        let call = await place(r)
        XCTAssertEqual(r.state.phase, .placing)
        XCTAssertEqual(r.words, "Calling…")
        XCTAssertTrue(r.audio.inCall)
        XCTAssertFalse(r.audio.speakerOn, "never the loudspeaker by itself")
        r.api.connectGate!.complete(()); await r.settle()
        let cv = await call.value
        XCTAssertTrue(cv.isSuccess)
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut)
        XCTAssertEqual(r.words, "Ringing…")
        XCTAssertEqual(r.api.lastConnect?.to, james)
        XCTAssertEqual(r.api.lastConnect?.sdp, "setLocal(Offer,v=0 our-offer)+candidates")
        XCTAssertEqual(r.api.lastConnect?.name, "Deacon James Mwangi")
        r.raw(#"{"type":"outbound_answer","call_id":"wacid.out1","sdp":"v=0 their-answer"}"#)
        await r.settle()
        XCTAssertEqual(r.state.phase, .connecting)
        XCTAssertTrue(r.media.peer.ops.contains("setRemote(Answer,v=0 their-answer)"))
        r.media.peer.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(r.words, "00:00")
        XCTAssertFalse(r.ringer.ringStarts > 0, "an outbound call never rings this phone")
    }

    // ── 6. Permission required → request → granted → Call now ────────────
    func testS06PermissionRequiredThenGranted() async {
        let r = await rig()
        r.api.connectError = err(409, "/admin/calls/connect", "No call permission")
        _ = await (await place(r)).value
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        XCTAssertEqual(r.words, "James hasn't allowed WhatsApp calls yet")
        XCTAssertEqual(r.state.outcomeNote(), CallManager.PERMISSION_EXPLAINED)
        XCTAssertEqual(r.state.wrapActions(), [.sendCallRequest, .message, .cancel])
        XCTAssertEqual(r.count("request-permission"), 0, "the request messages the customer: never sent by itself")
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.count("request-permission \(james)"), 1)
        XCTAssertEqual(r.state.outcome, .permissionRequested)
        XCTAssertEqual(r.words, "Call request sent — you'll be told when James taps Allow")
        XCTAssertEqual(r.state.wrapActions(), [.message, .done])
        // They tap Allow.
        r.raw(#"{"type":"call_permission","wa_id":"\#(james)","status":"granted","expires_at":null,"permanent":false}"#)
        XCTAssertEqual(r.calls.permissionGranted.value, PermissionGrant(waId: james, name: "Deacon James Mwangi"))
        XCTAssertEqual(r.state.phase, .idle, "the banner replaces the wrap-up")
        r.api.connectError = nil
        r.calls.callGranted(); await r.settle()
        XCTAssertNil(r.calls.permissionGranted.value)
        XCTAssertEqual(r.count("connect \(james)"), 2)
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut)
    }

    func testS06AlreadyRequestedSaysSoAtOnce() async {
        let r = await rig()
        r.api.connectError = err(409, "/admin/calls/connect", "No call permission")
        r.api.permissionStatus = "requested"
        _ = await (await place(r)).value
        XCTAssertEqual(r.state.outcome, .permissionRequested)
        XCTAssertEqual(r.count("request-permission"), 0)
    }

    // ── 7. Customer unavailable ──────────────────────────────────────────
    func testS07CustomerUnavailable() async {
        let r = await rig()
        r.api.connectError = err(502, "/admin/calls/connect", "call failed: The customer's phone is switched off")
        _ = await (await place(r)).value
        XCTAssertEqual(r.state.outcome, .failed(reason: "The customer's phone is switched off"))
        XCTAssertEqual(r.words, "The customer's phone is switched off")
        XCTAssertEqual(r.state.wrapActions(), [.tryAgain, .message, .done])
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertFalse(r.audio.inCall)
        XCTAssertTrue(r.media.peer.closed)
    }

    // ── 8. Answered while another agent is answering ─────────────────────
    func testS08Answer409SaysWhoTookIt() async {
        let r = await rig()
        r.api.answerError = err(409, "/admin/calls/wacid.1/answer", "call already answered by Ann Wanjiru")
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Ann Wanjiru"))
        XCTAssertEqual(r.words, "Answered by Ann")
        XCTAssertEqual(r.count("terminate"), 0, "the colleague's live call is never cut off")
        XCTAssertTrue(r.media.peer.closed)
    }

    func testS08Answer409NamingMeIsMyOtherDevice() async {
        let r = await rig()
        r.api.answerError = err(409, "/admin/calls/wacid.1/answer", "call already answered by Moses Mwicigi")
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.words, "Answered on your other device")
    }

    func testS08Decline409SaysAnsweredNotDeclined() async {
        let r = await rig()
        r.api.terminateErrors.append(err(409, "/admin/calls/wacid.1/terminate", "call already answered by Ann Wanjiru"))
        ring(r)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.words, "Answered by Ann")
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Ann Wanjiru"))
        XCTAssertEqual(r.count("terminate"), 1, "the refusal is final: no retry")
        await r.advance(4_001)
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testS08Callback409SaysAnsweredNotSaved() async {
        let r = await rig()
        r.api.callbackErrors.append(err(409, "/admin/calls/wacid.1/callback", "call already answered by Ann Wanjiru"))
        ring(r)
        r.calls.callback(); await r.settle()
        XCTAssertEqual(r.words, "Answered by Ann")
        XCTAssertEqual(r.count("callback wacid.1"), 1)
    }

    func testS08EndWhileConnectingBeforeTheAnswerWasAcceptedIsADecline() async {
        let r = await rig()
        r.api.answerGate = Deferred<Void>()   // the server hasn't accepted our answer yet
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting)
        XCTAssertEqual(r.count("answer wacid.1"), 1)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.outcome, .declined())
        XCTAssertEqual(r.words, "Call declined")
        XCTAssertEqual(r.count("terminate wacid.1"), 1)
        // Once accepted, End ends a call.
        r.api.answerGate = nil
        await r.advance(13_000)
        ring(r, "wacid.2"); r.calls.answer(); await r.settle()
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.outcome, .completed)
    }

    // ── 9. Network loss before answering ─────────────────────────────────
    func testS09NoConnectionKeepsItRingingAndAnswerRetries() async {
        let r = await rig()
        r.api.iceError = offline("/admin/calls/ice-config")
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.words, "Incoming…")
        XCTAssertEqual(r.state.error, "No connection — can't answer yet")
        XCTAssertTrue(r.ringer.ringing, "still ringing")
        XCTAssertEqual(r.count("answer"), 0)
        r.api.iceError = nil
        r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting)
        XCTAssertNil(r.state.error)
        XCTAssertEqual(r.count("answer wacid.1"), 1)
    }

    func testS09AnswerLostInFlightEndsAndHangsUpNeverRingsAgain() async {
        let r = await rig()
        r.api.answerError = timeout("/admin/calls/wacid.1/answer")
        ring(r); r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting)
        await r.advance(CallManager.ANSWER_CONFIRM_MS + 1)
        await r.advance(1_801)
        XCTAssertEqual(r.state.outcome, .failed(reason: CallManager.ANSWER_DROPPED))
        XCTAssertEqual(r.words, "The connection dropped while answering — call them back")
        XCTAssertEqual(r.count("terminate wacid.1"), 1, "nobody left on a silent line")
        XCTAssertEqual(r.ringer.ringStarts, 1, "never rang again")
        XCTAssertEqual(r.state.wrapActions(), [.callBack, .message, .done])
    }

    // ── 10. Network loss during a call ───────────────────────────────────
    func testS10ReconnectingIsHonest() async {
        let r = await rig()
        let p = await live(r)
        await r.advance(30_000)
        XCTAssertEqual(r.words, "00:30")
        p.onEvent(.interrupted); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertTrue(r.state.reconnecting)
        XCTAssertEqual(r.words, "Reconnecting…", "the timer never shows while nothing flows")
        await r.advance(5_000)
        XCTAssertEqual(r.words, "Reconnecting…")
        XCTAssertEqual(r.count("terminate"), 0)
    }

    // ── 11. Reconnection ─────────────────────────────────────────────────
    func testS11MediaRecoversWithinTheGrace() async {
        let r = await rig()
        let p = await live(r)
        await r.advance(20_000)
        p.onEvent(.interrupted); await r.settle()
        await r.advance(CallManager.ICE_GRACE_MS - 1_000)
        p.onEvent(.connected); await r.settle()
        XCTAssertFalse(r.state.reconnecting)
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(r.words, "00:29")
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .inCall, "the grace timer is gone: the call goes on")
        XCTAssertEqual(r.count("terminate"), 0)
    }

    func testS11SocketReconnectRereadsTheCallAndTakesTheServersWord() async {
        let r = await rig()
        _ = await live(r)
        await r.advance(40_000)
        r.connected.value = false; await r.settle()
        // Only the call's own row answers (the log read fails): GET /calls/{id} alone corrects it.
        r.api.listError = offline("/admin/calls")
        // The customer hung up while this phone couldn't hear.
        r.api.calls = [Call(id: "k1", callId: "wacid.1", waId: peter, status: "completed", duration: 42, agentId: "agent-me", startedAt: r.at(60_000))]
        r.connected.value = true; await r.settle()
        XCTAssertTrue(r.api.log.contains("get wacid.1"), "GET /calls/{id}")
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.state.outcome, .completed)
    }

    func testS11RingingCallThatEndedOfflineShowsItsRealOutcome() async {
        let r = await rig()
        ring(r)
        r.connected.value = false; await r.settle()
        r.api.listError = offline("/admin/calls")
        r.api.calls = [Call(id: "k1", callId: "wacid.1", waId: peter, status: "missed", startedAt: r.at(30_000))]
        r.connected.value = true; await r.settle()
        XCTAssertEqual(r.words, "Missed call")
        XCTAssertTrue(r.api.log.contains("get wacid.1"))
        XCTAssertFalse(r.ringer.ringing)
    }

    // ── 12. Bluetooth / headset switching ────────────────────────────────
    func testS12HeadsetsComeAndGoNeverTheSpeaker() async {
        let r = await rig()
        let buds = AudioRoute(.bluetooth, name: "Pixel Buds")
        let wired = AudioRoute(.wired)
        r.audio.plug(buds); await r.settle()
        XCTAssertTrue(r.state.routeChoice, "a headset: Audio opens a list")
        _ = await live(r)
        XCTAssertEqual(r.audio.route, buds, "a call starts on the connected headset")
        r.audio.plug(wired); await r.settle()
        XCTAssertEqual(r.audio.route, wired, "a headset plugged in mid-call takes it")
        r.calls.selectRoute(buds); await r.settle()
        XCTAssertEqual(r.audio.route, buds)
        XCTAssertEqual(r.state.route, buds)
        r.audio.unplug(buds); await r.settle()
        XCTAssertEqual(r.audio.route, wired, "the route in use gone: the other headset")
        r.audio.unplug(wired); await r.settle()
        XCTAssertEqual(r.audio.route, .earpiece, "…then the earpiece, never the loudspeaker")
        XCTAssertFalse(r.audio.speakerOn)
        XCTAssertFalse(r.state.routeChoice)
        r.calls.toggleSpeaker(); await r.settle()
        XCTAssertTrue(r.audio.speakerOn)
        r.calls.toggleSpeaker(); await r.settle()
        XCTAssertEqual(r.audio.route, .earpiece)
    }

    // ── 13. Background / locked phone ────────────────────────────────────
    func testS13LockedPhoneNotificationAnswersInOneTap() async {
        let r = await rig()
        r.foreground.value = false; await r.settle()
        ring(r)
        XCTAssertEqual(r.ringer.posted.count, 1)
        XCTAssertEqual(r.ringer.posted[0].callId, "wacid.1"); XCTAssertEqual(r.ringer.posted[0].who, "Fr. Peter Kamau"); XCTAssertEqual(r.ringer.posted[0].from, peter)
        XCTAssertTrue(r.ringer.showing)
        XCTAssertTrue(r.ringer.ringing)
        r.calls.handleAction("answer", id: "wacid.1"); await r.settle()
        XCTAssertEqual(r.state.phase, .connecting, "one tap: straight to Connecting on the full card")
        XCTAssertFalse(r.state.minimised)
        XCTAssertFalse(r.ringer.showing)
        XCTAssertFalse(r.ringer.ringing)
        XCTAssertEqual(r.count("answer wacid.1"), 1)
    }

    func testS13LockedPhoneNotificationDeclines() async {
        let r = await rig()
        r.foreground.value = false; await r.settle()
        ring(r, "wacid.7", name: "Grace Achieng")
        XCTAssertEqual(r.ringer.posted.count, 1)
        XCTAssertEqual(r.ringer.posted[0].who, "Grace Achieng")
        r.calls.handleAction("decline", id: "wacid.7"); await r.settle()
        XCTAssertEqual(r.state.outcome, .declined())
        XCTAssertEqual(r.count("terminate wacid.7"), 1)
        XCTAssertFalse(r.ringer.showing)
        // Back on screen: nothing posted again.
        r.foreground.value = true; await r.settle()
        XCTAssertEqual(r.ringer.posted.count, 1)
    }

    // ── 14. Cancellation ─────────────────────────────────────────────────
    func testS14HangingUpOurCallBeforeTheyAnswer() async {
        let r = await rig()
        r.api.connectGate = Deferred<Void>()
        let call = await place(r)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.outcome, .cancelled)
        XCTAssertEqual(r.words, "Call cancelled")
        XCTAssertEqual(r.state.wrapActions(), [.done])
        // Meta placed it after all: it is hung up, their phone doesn't keep ringing.
        r.api.connectGate!.complete(()); await r.settle()
        _ = await call.value
        XCTAssertEqual(r.count("terminate wacid.out1"), 1)
        await r.advance(2_001)
        XCTAssertEqual(r.state.phase, .idle)
    }

    func testS14CancelWhileItRingsThem() async {
        let r = await rig()
        _ = await (await place(r)).value
        // "Calling…" turns "Ringing…" only when Meta says their phone rings.
        XCTAssertEqual(r.state.phase, .placing)
        r.raw(#"{"type":"call_status","call_id":"\#(r.api.connectId)","status":"ringing"}"#)
        XCTAssertEqual(r.state.phase, .ringingOut)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.words, "Call cancelled")
        XCTAssertEqual(r.count("terminate wacid.out1"), 1)
    }

    func testS14TheyDontPickUp() async {
        let r = await rig()
        _ = await (await place(r)).value
        ended(r, "wacid.out1", "no_answer")
        XCTAssertEqual(r.words, "No answer")
        XCTAssertEqual(r.state.wrapActions(), [.callAgain, .message, .done])
    }

    // ── 15. Call dropped ─────────────────────────────────────────────────
    func testS15DroppedCallSaysTheConnectedTime() async {
        let r = await rig()
        let p = await live(r)
        await r.advance(133_000)
        p.onEvent(.interrupted); await r.settle()
        await r.advance(CallManager.ICE_GRACE_MS + 1)
        XCTAssertEqual(r.state.outcome, .connectionLost)
        XCTAssertEqual(r.words, "Call dropped · 2:13 — the connection was lost", "the grace is not call time")
        XCTAssertEqual(r.count("terminate wacid.1"), 1)
        XCTAssertEqual(r.state.wrapActions(), [.callAgain, .openChat, .done])
        XCTAssertFalse(r.audio.inCall)
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended, "a call back is owed: the card waits")
    }

    func testS15AudioThatNeverArrivedIsNotACallDropped() async {
        let r = await rig()
        ring(r); r.calls.answer(); await r.settle()
        await r.advance(CallManager.CONNECT_GUARD_MS + 1)
        XCTAssertEqual(r.words, "The call audio couldn't connect", "never stuck on Connecting…")
        XCTAssertEqual(r.count("terminate wacid.1"), 1)
    }

    // ── 16. Recording enabled / disabled ─────────────────────────────────
    func testS16RecordingOn() async {
        let r = await rig()
        _ = await live(r)
        XCTAssertTrue(r.state.recording)
        XCTAssertEqual(r.media.recordings.count, 1)
        await r.advance(20_000)
        r.calls.hangup(); await r.settle()
        XCTAssertFalse(r.state.recording)
        XCTAssertTrue(r.media.recordings[0].stopped)
        XCTAssertEqual(r.state.recordingNote, "Recording saved")
        await eventually { !r.api.uploads.isEmpty }
        XCTAssertEqual(r.api.uploads.map { $0.callId }, ["wacid.1"])
    }

    func testS16RecordingOff() async {
        let r = await rig()
        r.api.ice = IceConfig(record: false)
        _ = await live(r)
        XCTAssertFalse(r.state.recording, "no ● Recording when nothing records")
        XCTAssertTrue(r.media.recordings.isEmpty)
        r.calls.hangup(); await r.settle()
        XCTAssertNil(r.state.recordingNote)
        XCTAssertEqual(r.count("recording"), 0)
    }

    // ── 17. Completed with transcription ─────────────────────────────────
    func testS17CompletedWithTranscription() async {
        let r = await rig()
        r.api.ice = IceConfig(record: true, transcribe: true, autoTranscribe: true)
        _ = await live(r)
        await r.advance(252_000)
        r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.words, "Call ended · 4:12")
        XCTAssertEqual(r.state.recordingNote, "Recording saved — summary in a minute")
        await eventually { !r.api.uploads.isEmpty }
        XCTAssertEqual(r.api.uploads.map { $0.callId }, ["wacid.1"])
        await r.advance(7_999)
        XCTAssertEqual(r.state.phase, .ended, "long enough to read the recording line")
    }

    // ── 18. Without transcription ────────────────────────────────────────
    func testS18WithoutTranscription() async {
        let r = await rig()
        r.api.ice = IceConfig(record: true, transcribe: true, autoTranscribe: false)
        _ = await live(r); r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.recordingNote, "Recording saved — Transcribe from Calls")
        await r.advance(13_000)
        r.api.ice = IceConfig(record: true, transcribe: false)
        _ = await live(r, "wacid.2"); r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.state.recordingNote, "Recording saved")
    }

    // ── 20. Back into the conversation ───────────────────────────────────
    func testS20OpenChatFromALiveCallMinimisesIt() async {
        let r = await rig()
        _ = await live(r)
        XCTAssertEqual(r.calls.openChat(), peter, "Chat opens the customer's WhatsApp conversation")
        XCTAssertTrue(r.state.minimised)
        XCTAssertEqual(r.state.phase, .inCall, "the call goes on in the bar")
        XCTAssertEqual(r.count("terminate"), 0)
        r.calls.expand()
        XCTAssertFalse(r.state.minimised)
    }

    func testS20OpenChatFromTheWrapUpClosesIt() async {
        let r = await rig()
        _ = await live(r); r.calls.hangup(); await r.settle()
        XCTAssertEqual(r.calls.openChat(), peter)
        XCTAssertEqual(r.state.phase, .idle)
    }

    // ── Around the scenarios ─────────────────────────────────────────────
    func testASecondCallerIsABannerNeverATakeOver() async {
        let r = await rig()
        _ = await live(r)
        ring(r, "wacid.2", from: "254722000111", name: "Grace Achieng")
        XCTAssertEqual(r.state.callId, "wacid.1")
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(r.state.waiting?.who, "Grace Achieng")
        XCTAssertEqual(r.ringer.ringStarts, 1, "the live call is not interrupted by a ring")
        r.calls.declineWaiting(); await r.settle()
        XCTAssertNil(r.state.waiting)
        XCTAssertEqual(r.count("terminate wacid.2"), 1)
        XCTAssertEqual(r.state.phase, .inCall)
    }

    func testANewRingReplacesAWrapUp() async {
        let r = await rig()
        ring(r); ended(r, "wacid.1", "missed")
        XCTAssertEqual(r.state.phase, .ended)
        ring(r, "wacid.3", name: "Grace Achieng")
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertEqual(r.state.callId, "wacid.3")
        XCTAssertEqual(r.state.who, "Grace Achieng")
        XCTAssertNil(r.state.outcome)
    }

    func testNameAndNumberNeverChangeMidCall() async {
        let r = await rig()
        _ = await live(r)
        let row = #"{"id":"k1","call_id":"wacid.1","wa_id":"254799999999","name":"Somebody Else","conversation_id":"conv-x","direction":"inbound","status":"answered","agent_id":"agent-me"}"#
        r.raw(#"{"type":"call_update","call":\#(row)}"#)
        XCTAssertEqual(r.state.who, "Fr. Peter Kamau")
        XCTAssertEqual(r.state.from, peter)
        XCTAssertEqual(r.state.phase, .inCall)
    }

    // ── 21. The 2026-09 refresh, end to end: permission truth → request → Allow → ringing → declined ──
    func testS21PermissionTruthThenRingingThenDeclined() async {
        let r = await rig()
        r.api.permission = CallPermission(waId: james, status: "unknown", metaStatus: "no_permission", canCall: false, canRequest: true, unansweredStreak: 0, source: "meta")
        _ = await (await place(r)).value
        XCTAssertEqual(r.words, "James hasn't allowed WhatsApp calls yet")
        XCTAssertEqual(r.count("connect"), 0, "no doomed connect")
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.state.outcome, .permissionRequested)
        r.raw(#"{"type":"call_permission","wa_id":"\#(james)","status":"granted","expires_at":null,"permanent":true}"#)
        XCTAssertNotNil(r.calls.permissionGranted.value)
        // Call now: Meta now says yes.
        r.api.permission = CallPermission(waId: james, status: "granted", permanent: true, metaStatus: "permanent", canCall: true, source: "meta")
        r.calls.callGranted(); await r.settle()
        XCTAssertEqual(r.count("connect \(james)"), 1)
        XCTAssertEqual(r.words, "Calling…")
        r.raw(#"{"type":"call_status","call_id":"wacid.out1","status":"ringing"}"#)
        XCTAssertEqual(r.words, "Ringing…")
        r.raw(#"{"type":"call_ended","call_id":"wacid.out1","outcome":"rejected","status":"REJECTED","direction":"outbound"}"#)
        XCTAssertEqual(r.words, "James declined the call")
        XCTAssertEqual(r.state.wrapActions(), [.message, .done])
        await r.advance(60_000)
        XCTAssertEqual(r.state.phase, .ended, "the agent decides what's next")
    }

    // ── Messenger (CALLING_UX.md §2.0): the web's M1–M5 ──────────────────
    private func ringMessenger(_ r: CallRig, _ id: String = "c_in1", name: String? = nil) {
        let n = name.map { "\"\($0)\"" } ?? "null"
        r.raw(#"{"type":"incoming_call","call_id":"\#(id)","from":"\#(grace)","external_id":"\#(grace)","name":\#(n),"at":"1","channel":"messenger"}"#)
    }
    private func placeMessenger(_ r: CallRig, name: String = "Grace Wanjiku") async -> Task<Result<Void, Error>, Never> {
        let t = Task { await r.calls.initiateCall(to: self.grace, name: name, conversationId: "conv-grace", channel: "messenger") }
        await r.settle()
        return t
    }
    private func mediaUpdate(_ r: CallRig, _ id: String, _ version: Int?, _ sdp: String?, type: String? = "offer") async {
        let v = version.map { "\($0)" } ?? "null"
        let t = type.map { "\"\($0)\"" } ?? "null"
        let s = sdp.map { "\"\($0)\"" } ?? "null"
        r.raw(#"{"type":"media_update","call_id":"\#(id)","channel":"messenger","version":\#(v),"sdp_type":\#(t),"sdp":\#(s)}"#)
        await r.settle()
    }

    // M1. A customer calls on Messenger: WE build the offer, Meta answers it.
    func testM1InboundMessengerCallSendsAnOfferAndAppliesMetasAnswer() async {
        let r = await rig()
        r.api.messengerCalls.insert("c_in1")
        r.api.messengerRenegotiation = .string("v=0 reneg")
        ringMessenger(r)
        XCTAssertEqual(r.state.phase, .ringing)
        XCTAssertTrue(r.state.messenger)
        XCTAssertEqual(r.state.who, "Messenger caller", "never a PSID on screen")
        XCTAssertNil(r.state.number, "a PSID is no number")
        XCTAssertEqual(r.words, "Incoming…")
        // The name follows in a call_update, from the linked person.
        r.raw(#"{"type":"call_update","call":{"call_id":"c_in1","channel":"messenger","external_id":"\#(grace)","wa_id":null,"name":"Grace Wanjiku","direction":"inbound","status":"ringing","conversation_id":"conv-grace"}}"#)
        XCTAssertEqual(r.state.who, "Grace Wanjiku")
        XCTAssertEqual(r.state.chatKey, "conv-grace", "Open chat goes to the Messenger conversation")
        r.calls.answer(); await r.settle()
        XCTAssertEqual(requests(r), ["ice-config", "offer c_in1", "answer c_in1"])
        XCTAssertEqual(r.api.lastAnswerSdp, "setLocal(Offer,v=0 our-offer)+candidates", "our OFFER went to /answer")
        let p = r.media.peer
        XCTAssertEqual(p.ops, ["addMic(true)", "createOffer", "setLocal(Offer,v=0 our-offer)", "setRemote(Answer,v=0 meta-answer)",
                               "setRemote(Offer,v=0 reneg)", "createAnswer", "setLocal(Answer,v=0 our-answer)"])
        XCTAssertEqual(r.words, "Connecting…")
        p.onEvent(.connected); await r.settle()
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(r.words, "00:00")
    }

    func testM1bAnAcceptWithNoAnswerIsNeverASilentLine() async {
        let r = await rig()
        r.api.messengerCalls.insert("c_in1")
        r.api.messengerAnswer = nil
        ringMessenger(r, name: "Grace Wanjiku")
        r.calls.answer(); await r.settle()
        XCTAssertEqual(r.state.phase, .ended)
        XCTAssertEqual(r.words, CallManager.AUDIO_NOT_CONNECTED)
        XCTAssertEqual(r.count("terminate c_in1"), 1)
    }

    // M2. Several agents, two apps: the first answer wins, whatever the channel; a second caller is a banner.
    func testM2CrossChannelFirstAnswerWinsAndTheWaitingBanner() async {
        let r = await rig()
        r.api.messengerCalls.insert("c_in1")
        // A colleague takes the Messenger call first.
        ringMessenger(r, name: "Grace Wanjiku")
        answered(r, "c_in1", "agent-ann", "Ann Wanjiru")
        XCTAssertEqual(r.state.outcome, .answeredElsewhere(agent: "Ann Wanjiru"))
        XCTAssertEqual(r.words, "Answered by Ann")
        r.calls.dismiss(); await r.advance(13_000)
        // …or wins the lock a moment before this phone: 409 names them.
        r.api.messengerCalls.insert("c_in2")
        ringMessenger(r, "c_in2", name: "Grace Wanjiku")
        r.api.answerError = err(409, "/admin/calls/c_in2/answer", "call already answered by Ann Wanjiru")
        r.calls.answer(); await r.settle()
        XCTAssertEqual(r.words, "Answered by Ann")
        XCTAssertEqual(r.count("terminate c_in2"), 0, "their call is left alone")
        r.calls.dismiss(); r.api.answerError = nil; await r.advance(13_000)
        // On a WhatsApp call, a Messenger caller rings in: a banner, never a take-over.
        _ = await live(r, "wacid.9")
        r.api.messengerCalls.insert("c_in3")
        ringMessenger(r, "c_in3")
        XCTAssertEqual(r.state.phase, .inCall)
        let w = r.state.waiting!
        XCTAssertEqual(w.channel, "messenger")
        XCTAssertEqual(w.who, "Messenger caller")
        // End & answer: this call ends, theirs is answered — with our offer.
        r.calls.endAndAnswer(); await r.settle()
        XCTAssertEqual(r.count("terminate wacid.9"), 1)
        XCTAssertEqual(r.state.callId, "c_in3")
        XCTAssertTrue(r.state.messenger)
        XCTAssertEqual(r.count("answer c_in3"), 1)
        XCTAssertTrue(r.api.lastAnswerSdp!.hasPrefix("setLocal(Offer,"))
    }

    // M3. Calling a Messenger customer: with their permission, and without (calling_optin).
    func testM3OutboundMessengerWithPermissionStaysRingingUntilAnswered() async {
        let r = await rig()
        r.api.permission = CallPermission(waId: nil, status: "granted", canCall: true, source: "meta")
        let placed = await placeMessenger(r)
        let pv = await placed.value
        XCTAssertTrue(pv.isSuccess)
        let log = r.api.log.filter { !$0.hasPrefix("list") }
        XCTAssertEqual(Set(log), ["ice-config", "permission messenger \(grace)", "connect-messenger \(grace)"])
        XCTAssertEqual(log.last, "connect-messenger \(grace)", "connect with channel + psid, after the permission read")
        XCTAssertEqual(r.api.lastMessengerConnect?.psid, grace)
        XCTAssertTrue(r.api.lastMessengerConnect!.sdp.hasPrefix("setLocal(Offer,"), "our offer")
        XCTAssertEqual(r.state.callId, "c_msg.out1")
        XCTAssertEqual(r.words, "Calling…")
        XCTAssertEqual(r.media.peer.ops.first { $0.hasPrefix("setRemote") }, "setRemote(Answer,v=0 meta-answer)", "Meta's answer applied at once")
        r.raw(#"{"type":"call_status","call_id":"c_msg.out1","status":"ringing"}"#)
        XCTAssertEqual(r.words, "Ringing…")
        // The media path to Meta comes up before they pick up: not connected, no timer.
        r.media.peer.onEvent(.connected); await r.settle()
        await r.advance(5_000)
        XCTAssertEqual(r.state.phase, .ringingOut)
        XCTAssertEqual(r.words, "Ringing…")
        XCTAssertNil(r.calls.liveSinceForTest, "the timer never starts before call_answered")
        // They picked up: live at once (the media is already there).
        answered(r, "c_msg.out1", "agent-me", "Moses Mwicigi", direction: "outbound")
        XCTAssertEqual(r.state.phase, .inCall)
        XCTAssertEqual(r.words, "00:00")
        await r.advance(3_000)
        XCTAssertEqual(r.words, "00:03", "the call's length from the answer, not the media")
    }

    func testM3bOutboundMessengerWithoutPermissionSendsCallingOptin() async {
        let r = await rig()
        r.api.permission = CallPermission(waId: nil, status: "unknown", metaStatus: "no_permission", canCall: false, canRequest: true, source: "meta")
        _ = await (await placeMessenger(r)).value
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        XCTAssertEqual(r.words, "Grace hasn't allowed Messenger calls yet")
        XCTAssertTrue(r.state.outcomeNote()!.contains(CallManager.PERMISSION_EXPLAINED_MESSENGER))
        XCTAssertEqual(r.count("connect-messenger"), 0, "no doomed connect")
        XCTAssertEqual(r.state.wrapActions().first, .sendCallRequest)
        r.calls.sendCallRequest(); await r.settle()
        XCTAssertEqual(r.count("request-permission messenger \(grace)"), 1)
        XCTAssertEqual(r.count("request-permission \(grace)"), 0)
        XCTAssertEqual(r.state.outcome, .permissionRequested)
        // They tap Accept: matched by channel + external_id.
        r.raw(#"{"type":"call_permission","wa_id":null,"channel":"messenger","external_id":"\#(grace)","status":"granted","expires_at":"2026-10-03T10:00:00+00:00"}"#)
        XCTAssertEqual(r.calls.permissionGranted.value, PermissionGrant(waId: grace, name: "Grace Wanjiku", channel: "messenger"))
        XCTAssertEqual(r.state.phase, .idle, "the banner replaces the wrap-up")
        // A WhatsApp frame for the same digits is someone else's.
        r.calls.dismissGrant()
        r.api.permission = CallPermission(waId: nil, status: "granted", canCall: true, source: "meta")
        _ = await r.calls.requestPermission(to: grace, name: "Grace Wanjiku", channel: "messenger")
        r.raw(#"{"type":"call_permission","wa_id":"\#(grace)","status":"granted"}"#)
        XCTAssertNil(r.calls.permissionGranted.value)
    }

    func testM3cConnectRefusedForNoPermissionOffersTheRequest() async {
        let r = await rig()
        r.api.connectError = ApiError(status: 409, method: "POST", path: "/admin/calls/connect",
                                      body: #"{"detail":"This customer hasn't allowed Messenger calls yet.","code":"no_permission","action":"request_permission"}"#)
        _ = await (await placeMessenger(r)).value
        XCTAssertEqual(r.state.outcome, .permissionNeeded)
        XCTAssertEqual(r.words, "Grace hasn't allowed Messenger calls yet")
    }

    // M4. The switch is off: no Messenger button, the sheet says so, a refusal re-reads the channels.
    func testM4MessengerCallingOffIsSaidEverywhere() async throws {
        let r = await rig()
        XCTAssertEqual(r.api.channelsReads, 1, "read at start")
        XCTAssertFalse(r.calls.messengerCallsOn, "off until read, and off here")
        let conv = try NeemaJSON.decode(Conversation.self, from: #"{"id":"conv-grace","external_id":"\#(grace)","channel":"messenger","name":"Grace Wanjiku"}"#)
        let insta = try NeemaJSON.decode(Conversation.self, from: #"{"id":"conv-ig","external_id":"\#(grace)","channel":"instagram","name":"Grace Wanjiku"}"#)
        let on = CallChannels(messenger: ChannelCalling(inbound: true, outbound: true, sdp: "offer"))
        XCTAssertEqual(CustomerWords.callButtonFor(conv, channels: nil, phoneDigits: nil), .sheet(.messenger))
        XCTAssertEqual(CustomerWords.callButtonFor(conv, channels: CallChannels(), phoneDigits: "254711222333"), .sheet(.messenger))
        XCTAssertEqual(CustomerWords.callButtonFor(conv, channels: on, phoneDigits: nil), .onMessenger(psid: grace))
        XCTAssertEqual(CustomerWords.callButtonFor(insta, channels: on, phoneDigits: nil), .sheet(.instagram), "Instagram never calls")
        XCTAssertEqual(cantCallWhy("Messenger"), "Messenger calling isn't switched on for Neema yet.")
        XCTAssertEqual(cantCallWhy("Instagram"), "Instagram doesn't let businesses take calls.")
        // Switched on: the socket reconnect re-reads it.
        r.api.channels = on
        r.connected.value = false; await r.settle(); r.connected.value = true; await r.settle()
        XCTAssertEqual(r.api.channelsReads, 2)
        XCTAssertTrue(r.calls.messengerCallsOn)
        // …and off again between the read and the tap: the refusal says so and re-reads.
        r.api.channels = CallChannels()
        r.api.connectError = ApiError(status: 409, method: "POST", path: "/admin/calls/connect",
                                      body: #"{"detail":"Messenger calling is switched off — call them on WhatsApp instead.","code":"messenger_calling_off","action":"none"}"#)
        _ = await (await placeMessenger(r)).value
        await r.settle()
        XCTAssertEqual(r.words, "Messenger calling is switched off — call them on WhatsApp instead.")
        XCTAssertEqual(r.state.outcomeNote(), CallManager.MESSAGE_INSTEAD)
        XCTAssertFalse(r.state.wrapActions().contains(.tryAgain), "no Try again: it won't help")
        XCTAssertEqual(r.api.channelsReads, 3)
        XCTAssertFalse(r.calls.messengerCallsOn)
        // ice-config carries channels too.
        r.calls.dismiss()
        r.api.ice = IceConfig(record: true, channels: on)
        r.api.connectError = nil
        _ = await (await placeMessenger(r)).value
        XCTAssertTrue(r.calls.messengerCallsOn)
    }

    // M5. media_update: only the highest version, never another call's or an SDP-less one; held until the call is set up.
    func testM5MediaUpdatesApplyTheHighestVersionOnly() async {
        let r = await rig()
        r.api.permission = CallPermission(waId: nil, status: "granted", canCall: true, source: "meta")
        _ = await (await placeMessenger(r)).value
        let p = r.media.peer
        func offers() -> [String] { p.ops.filter { $0.hasPrefix("setRemote(Offer") } }
        await mediaUpdate(r, "c_msg.out1", 2, "v=0 v2")
        XCTAssertEqual(offers(), ["setRemote(Offer,v=0 v2)"])
        XCTAssertEqual(p.ops.last, "setLocal(Answer,v=0 our-answer)", "answered locally")
        await mediaUpdate(r, "c_msg.out1", 1, "v=0 v1")
        await mediaUpdate(r, "c_msg.out1", 2, "v=0 v2-again")
        XCTAssertEqual(offers(), ["setRemote(Offer,v=0 v2)"], "stale versions are never applied")
        await mediaUpdate(r, "c_other", 9, "v=0 other")
        await mediaUpdate(r, "c_msg.out1", 5, nil)
        await mediaUpdate(r, "c_msg.out1", 6, "v=0 an-answer", type: "answer")
        XCTAssertEqual(offers(), ["setRemote(Offer,v=0 v2)"], "other calls', SDP-less and non-offers are ignored")
        await mediaUpdate(r, "c_msg.out1", 3, "v=0 v3")
        XCTAssertEqual(offers(), ["setRemote(Offer,v=0 v2)", "setRemote(Offer,v=0 v3)"])
        XCTAssertEqual(r.count("answer"), 0, "nothing is sent back")
    }

    func testM5bAMediaUpdateBeforeSetupIsHeld() async {
        let r = await rig()
        // Our call: it arrives while connect is still out.
        r.api.permission = CallPermission(waId: nil, status: "granted", canCall: true, source: "meta")
        r.api.connectGate = Deferred<Void>()
        let placed = await placeMessenger(r)
        await mediaUpdate(r, "c_msg.out1", 1, "v=0 early1")
        await mediaUpdate(r, "c_msg.out1", 4, "v=0 early4")
        await mediaUpdate(r, "c_msg.out1", 2, "v=0 early2")
        XCTAssertFalse(r.media.peer.ops.contains { $0.hasPrefix("setRemote") })
        r.api.connectGate!.complete(()); await r.settle()
        _ = await placed.value
        await r.settle()
        XCTAssertEqual(r.media.peer.ops.filter { $0.hasPrefix("setRemote") }, ["setRemote(Answer,v=0 meta-answer)", "setRemote(Offer,v=0 early4)"],
                       "the answer first, then the highest held offer")
        r.calls.hangup(); await r.settle(); r.calls.dismiss(); await r.advance(13_000)
        // A customer's call: it arrives while it still rings here.
        r.api.messengerCalls.insert("c_in5")
        ringMessenger(r, "c_in5", name: "Grace Wanjiku")
        await mediaUpdate(r, "c_in5", 1, "v=0 ring-time")
        r.calls.answer(); await r.settle()
        XCTAssertEqual(r.media.peer.ops.filter { $0.hasPrefix("setRemote") }, ["setRemote(Answer,v=0 meta-answer)", "setRemote(Offer,v=0 ring-time)"])
    }
}
