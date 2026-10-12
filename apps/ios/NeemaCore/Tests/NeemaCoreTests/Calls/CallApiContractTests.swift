import Foundation
import XCTest
@testable import NeemaCore

/// The softphone's API contract against what routers/admin.py's `/calls*`
/// handlers really send and accept: exact method, encoded path, query and body
/// for every request, and decoding of the real response shapes — including the
/// nulls, the legacy rows with missing keys, `+00:00` microsecond timestamps,
/// the two ICE `urls` shapes, and every error body the handlers raise.
/// Android `calls/CallApiContractTest.kt`.
@MainActor
final class CallApiContractTests: XCTestCase {
    private let C1 = CallsFixtures.C1
    private var hosts: [TestHost] = []

    override func setUp() async throws { AppClock.pin(to: PINNED) }
    override func tearDown() async throws {
        for h in hosts { h.logout() }
        hosts.removeAll()
        AppClock.reset()
    }

    private func rig() -> (FakeNeema, NeemaCallApi, NeemaApi) {
        let fake = Fixtures.withFixtures()
        CallsFixtures.install(fake)
        fake.on("GET", CallsFixtures.route(C1, "offer"), body: CallsFixtures.offer(C1))
        // calls_answer / terminate / callback → {"ok": True, "call_id": call_id}
        for s in ["answer", "terminate", "callback"] { fake.on("POST", CallsFixtures.route(C1, s), body: "{\"ok\":true,\"call_id\":\"\(C1)\"}") }
        // calls_connect → {"ok": True, "call_id": <Meta's new wacid>}
        fake.on("POST", "/admin/calls/connect", body: "{\"ok\":true,\"call_id\":\"\(CallsFixtures.wacid("T1VU"))\"}")
        // calls_request_permission → {"ok": True, "permission": {...}} (an older server: {"ok": True})
        fake.on("POST", "/admin/calls/request-permission", body: #"{"ok":true}"#)
        // calls_upload_recording → {"ok": True, "call_id": ..., "will_transcribe": auto}
        fake.on("POST", CallsFixtures.route(C1, "recording"), body: "{\"ok\":true,\"call_id\":\"\(C1)\",\"will_transcribe\":false}")
        let host = TestHost(fake: fake)
        hosts.append(host)
        return (fake, NeemaCallApi(host.api), host.api)
    }

    private func last(_ f: FakeNeema, _ m: String, _ p: String) -> FakeNeema.Call? { f.calls.last { $0.method == m && $0.path == p } }
    private func tempRecording(_ bytes: Int = 3000) -> URL {
        let f = FileManager.default.temporaryDirectory.appendingPathComponent("rec-\(UUID().uuidString).m4a")
        try? Data(repeating: 7, count: bytes).write(to: f)
        return f
    }
    /// The id on the wire: `==` percent-encoded.
    private var wire: String { C1.replacingOccurrences(of: "=", with: "%3D") }

    // ── Requests ─────────────────────────────────────────────────────────
    func testEveryRequestMatchesTheHandlers() async throws {
        let (fake, api, _) = rig()
        _ = try await api.list(); _ = try await api.iceConfig(); _ = try await api.offer(C1)
        _ = try await api.answer(C1, sdp: "v=0 answer"); try await api.terminate(C1); try await api.callback(C1)
        _ = try await api.connect(to: "254712345678", sdp: "v=0 our-offer", name: "Fr. Peter Kamau")
        _ = try await api.requestPermission(to: "254712345678", name: nil)
        try await api.uploadRecording(C1, file: UploadFile.of(file: tempRecording(), filename: "\(C1).m4a", mimeType: "audio/mp4"))

        // The wacid's `==` is percent-encoded on the wire, exactly as encodeURIComponent does.
        XCTAssertEqual(CallsFixtures.encoded(C1), wire)
        XCTAssertEqual(CallsFixtures.path(C1, "offer"), "/admin/calls/\(C1)/offer")

        // list_calls: GET, no `limit` (the web sends none; the handler defaults to 50).
        XCTAssertNil(last(fake, "GET", "/admin/calls")?.query)
        XCTAssertTrue(fake.calls.contains { $0.method == "GET" && $0.path == "/admin/calls/ice-config" && $0.query == nil })
        XCTAssertTrue(fake.calls.contains { $0.method == "GET" && $0.path == CallsFixtures.path(C1, "offer") })
        // calls_answer reads body["sdp"]; terminate/callback take no body (the web posts {}).
        XCTAssertEqual(last(fake, "POST", CallsFixtures.path(C1, "answer"))?.body, #"{"sdp":"v=0 answer"}"#)
        XCTAssertEqual(last(fake, "POST", CallsFixtures.path(C1, "terminate"))?.body, "{}")
        XCTAssertEqual(last(fake, "POST", CallsFixtures.path(C1, "callback"))?.body, "{}")
        // calls_connect reads to / sdp / name; calls_request_permission reads to.
        XCTAssertEqual(JSONValue.parse(last(fake, "POST", "/admin/calls/connect")?.body ?? ""),
                       JSONValue.parse(#"{"to":"254712345678","sdp":"v=0 our-offer","name":"Fr. Peter Kamau"}"#))
        XCTAssertEqual(JSONValue.parse(last(fake, "POST", "/admin/calls/request-permission")?.body ?? ""), JSONValue.parse(#"{"to":"254712345678"}"#))
        // calls_upload_recording: `file: UploadFile = File(...)`; the extension
        // comes from the file name (a wacid has dots — splitext still yields .m4a).
        let body = last(fake, "POST", CallsFixtures.path(C1, "recording"))?.body ?? ""
        XCTAssertTrue(body.contains("Content-Disposition: form-data; name=\"file\"; filename=\"\(C1).m4a\""), body.prefix(300).description)
        XCTAssertTrue(body.contains("Content-Type: audio/mp4") && body.count > 3000)
        XCTAssertEqual(String("\(C1).m4a".suffix(4)), ".m4a")
    }

    func testTheNewCallRoutesMatchTheHandlers() async throws {
        let (fake, api, raw) = rig()
        fake.on("GET", NSRegularExpression.escapedPattern(for: "/admin/calls/\(C1)"), body: CallsFixtures.row(
            CallsFixtures.K1, C1, "254712345678", "Fr. Peter Kamau", "inbound", "completed", 184, "Moses Mwicigi",
            CallsFixtures.pyIso(40), nil, "done", true))
        fake.on("GET", "/admin/calls/permission", body: #"{"wa_id":"254712345678","status":"requested","expires_at":null,"permanent":false}"#)
        fake.on("POST", "/admin/calls/request-permission",
                body: #"{"ok":true,"permission":{"wa_id":"254712345678","status":"requested","permanent":false,"expires_at":null,"at":"2026-09-26T10:00:00+00:00"}}"#)
        // get_call: GET /admin/calls/{call_id}, the id percent-encoded.
        let row = try await api.get(C1)
        XCTAssertEqual(row.callId, C1)
        XCTAssertTrue(fake.calls.contains { $0.method == "GET" && $0.path == "/admin/calls/\(C1)" })
        // calls_permission reads ?wa_id= (no +).
        let perm = try await api.permission("+254712345678")
        XCTAssertEqual(perm.status, "requested")
        XCTAssertEqual(last(fake, "GET", "/admin/calls/permission")?.query, "wa_id=254712345678")
        // calls_request_permission answers with the permission on file.
        let req = try await api.requestPermission(to: "254712345678", name: nil)
        XCTAssertEqual(req.permission?.status, "requested")
        // list_calls: one customer / the follow-ups, only when asked.
        _ = try await raw.calls.list(waId: "+254712345678", limit: 3)
        XCTAssertEqual(last(fake, "GET", "/admin/calls")?.query, "wa_id=254712345678&limit=3")
        _ = try await raw.calls.list(view: "follow_up")
        XCTAssertEqual(last(fake, "GET", "/admin/calls")?.query, "view=follow_up")
        // calls_follow_up_done: POST, no body fields.
        _ = try await raw.calls.followUpDone(callId: C1)
        XCTAssertEqual(last(fake, "POST", CallsFixtures.path(C1, "follow-up-done"))?.body, "{}")
    }

    func testTheNewRowShapeDecodesLeniently() throws {
        let rows = try NeemaJSON.decode([Call].self, from: CallsFixtures.calls)
        let peter = rows[0]
        XCTAssertEqual(peter.status, "completed")
        XCTAssertEqual(peter.conversationId, "c1")
        XCTAssertEqual(peter.channel, "whatsapp")
        XCTAssertNotNil(peter.answeredAt); XCTAssertNotNil(peter.endedAt)
        let i = peter.insights!
        XCTAssertEqual(i.nextAction, "Confirm Friday delivery to Nyeri")
        XCTAssertEqual(i.products, ["Clergy Shirt (Black 16\")"])
        XCTAssertTrue(i.followUpMessage!.hasPrefix("Hello Father Peter"))
        XCTAssertTrue(rows.first { $0.status == "missed" }!.followUpOpen, "missed rows owe a call")
        // Odd insights never sink the row: a string where a list goes, numbers, objects, junk.
        let odd = try NeemaJSON.decode(Call.self, from: #"{"call_id":"x","status":"completed","insights":{"products":"one shirt","objections":[3,{"name":"price"},null],"next_action":null,"follow_up_message":"","extra":{"a":1}},"new_key":true}"#)
        XCTAssertEqual(odd.insights!.products, ["one shirt"])
        XCTAssertEqual(odd.insights!.objections, ["3", "price"])
        XCTAssertNil(odd.insights!.nextAction); XCTAssertNil(odd.insights!.followUpMessage)
        XCTAssertNil(try NeemaJSON.decode(Call.self, from: #"{"call_id":"y","insights":"n/a"}"#).insights, "not an object")
        XCTAssertNil(try NeemaJSON.decode(Call.self, from: #"{"call_id":"z","insights":{}}"#).insights, "empty")
        // ice-config's transcription flags.
        let cfg = try NeemaJSON.decode(IceConfig.self, from: #"{"ice_servers":[],"record":true,"transcribe":true,"auto_transcribe":false}"#)
        XCTAssertEqual(cfg.transcribe, true); XCTAssertEqual(cfg.autoTranscribe, false)
    }

    func testConnectWithoutANameOmitsIt() async throws {
        let (fake, api, _) = rig()
        _ = try await api.connect(to: "254712345678", sdp: "sdp", name: nil)
        XCTAssertEqual(JSONValue.parse(fake.calls.last!.body ?? ""), JSONValue.parse(#"{"to":"254712345678","sdp":"sdp"}"#))
    }

    // ── Responses ────────────────────────────────────────────────────────
    func testTheCallLogDecodesAsTheHandlerBuildsIt() async throws {
        let (_, api, _) = rig()
        let rows = try await api.list()
        XCTAssertEqual(rows.count, 7)
        let first = rows[0]
        XCTAssertEqual(first.id, CallsFixtures.K1)
        XCTAssertEqual(first.callId, C1)
        XCTAssertEqual(first.duration, 184)
        XCTAssertEqual(first.transcriptStatus, "done")
        XCTAssertTrue(first.hasRecording)
        // started_at is isoformat(): "…T09:20:13.482915+00:00" — parsed, not dropped.
        XCTAssertTrue(first.startedAt!.hasSuffix("+00:00"))
        let t = Fmt.millis(first.startedAt)!
        XCTAssertTrue(abs(AppClock.now() - 40 * 60_000 - t) < 60_000)
        // The bare row calls_upload_recording creates: no wa_id, no name.
        let bare = rows.first { $0.callId == CallsFixtures.C6 }!
        XCTAssertNil(bare.waId); XCTAssertNil(bare.name)
    }

    func testLegacyAndNullHeavyRowsStillDecode() throws {
        // A row from before the transcript migration (keys missing), and one with
        // every nullable as null (started_at included — the handler allows it).
        let json = """
        [{"id":"a","call_id":"wacid.X","wa_id":"254700000001","name":null,"direction":"inbound","status":"missed","duration":null,"agent_name":null,"started_at":"2026-09-25T09:20:13.482915+00:00"},
         {"id":"b","call_id":"wacid.Y","wa_id":null,"name":null,"direction":"outbound","status":"ringing","duration":null,"agent_name":null,
          "started_at":null,"summary":null,"transcript_status":null,"has_recording":false}]
        """
        let rows = try NeemaJSON.decode([Call].self, from: json)
        XCTAssertEqual(rows.count, 2)
        XCTAssertFalse(rows[0].hasRecording)
        XCTAssertNil(rows[0].transcriptStatus)
        XCTAssertNil(rows[1].startedAt)
        XCTAssertNil(Fmt.millis(rows[1].startedAt))
        // A naive timestamp (no offset) is read as UTC.
        let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        XCTAssertEqual(Fmt.millis("2026-09-25T09:20:13.482915"), Int64(f.date(from: "2026-09-25T09:20:13.482Z")!.timeIntervalSince1970 * 1000))
    }

    func testIceConfigCarriesBothUrlShapesAndTheTurnCredentials() async throws {
        let (_, api, _) = rig()
        let cfg = try await api.iceConfig()
        XCTAssertEqual(cfg.record, true)
        XCTAssertEqual(iceSpecs(cfg), [
            IceSpec(["turn:turn.bethanyhouse.co.ke:3478"], "neema", "s3cret"),
            IceSpec(["stun:stun.l.google.com:19302"], "", ""),
            IceSpec(["turn:openrelay.metered.ca:80", "turn:openrelay.metered.ca:443", "turn:openrelay.metered.ca:443?transport=tcp"], "openrelayproject", "openrelayproject"),
        ])
    }

    func testIceConfigToleratesAMissingRecordFlagAndOddEntries() throws {
        // TURN_URL unset → only the STUN + openrelay; a username with an empty
        // credential (TURN_CREDENTIAL unset) and an entry with null urls.
        let cfg = try NeemaJSON.decode(IceConfig.self, from: #"{"ice_servers":[{"urls":"turn:t.example:3478","username":"u","credential":""},{"urls":null},{"urls":[]}]}"#)
        XCTAssertNil(cfg.record)   // CallManager records unless record == false
        XCTAssertEqual(iceSpecs(cfg), [IceSpec(["turn:t.example:3478"], "u", "")])
    }

    func testOfferWithNullsDecodes() throws {
        // calls_get_offer returns data.get("sdp") / data.get("from") — null when the webhook had none.
        let o = try NeemaJSON.decode(CallOffer.self, from: #"{"call_id":"\#(C1)","sdp":null,"from":null}"#)
        XCTAssertNil(o.sdp); XCTAssertNil(o.from); XCTAssertFalse(o.offerRequired)
        let real = try NeemaJSON.decode(CallOffer.self, from: CallsFixtures.offer(C1))
        XCTAssertTrue(real.sdp!.contains("a=setup:actpass") && real.sdp!.contains("\r\n"))
        // Messenger (§2.0): no offer — we build it.
        let m = try NeemaJSON.decode(CallOffer.self, from: #"{"call_id":"c_1","sdp":null,"channel":"messenger","offer_required":true,"from":"7788990011"}"#)
        XCTAssertTrue(m.offerRequired); XCTAssertEqual(m.channel, "messenger"); XCTAssertNil(m.sdp)
    }

    func testMessengerRoutesMatchTheHandlers() async throws {
        let (fake, api, _) = rig()
        fake.on("GET", "/admin/calls/channels", body: #"{"whatsapp":{"inbound":true,"outbound":true,"video":false,"sdp":"answer"},"messenger":{"inbound":true,"outbound":true,"video":false,"sdp":"offer"},"instagram":{"inbound":false,"outbound":false,"video":false}}"#)
        fake.on("GET", "/admin/calls/permission", body: #"{"wa_id":null,"channel":"messenger","external_id":"7788990011","status":"granted","expires_at":"2026-10-03T10:00:00+00:00","permanent":false,"can_call":true}"#)
        fake.on("POST", "/admin/calls/connect", body: #"{"ok":true,"call_id":"c_9","channel":"messenger","sdp":"v=0 meta","sdp_type":"answer","renegotiation":{"sdp_type":"offer","sdp":"v=0 reneg"}}"#)
        fake.on("POST", "/admin/calls/request-permission", body: #"{"ok":true,"route":"calling_optin","permission":{"wa_id":null,"channel":"messenger","external_id":"7788990011","status":"requested"}}"#)
        let ch = try await api.channels()
        XCTAssertTrue(ch.messenger.outbound && ch.messenger.inbound); XCTAssertEqual(ch.messenger.sdp, "offer"); XCTAssertFalse(ch.instagram.outbound)
        let p = try await api.messengerPermission("7788990011")
        XCTAssertEqual(p.status, "granted"); XCTAssertEqual(p.externalId, "7788990011"); XCTAssertNil(p.waId)
        XCTAssertEqual(last(fake, "GET", "/admin/calls/permission")?.query, "channel=messenger&psid=7788990011")
        let c = try await api.connectMessenger(psid: "7788990011", sdp: "v=0 our-offer", name: "Grace Wanjiku")
        XCTAssertEqual(c.callId, "c_9"); XCTAssertEqual(c.sdp, "v=0 meta"); XCTAssertEqual(c.renegotiationSdp, "v=0 reneg")
        XCTAssertEqual(JSONValue.parse(last(fake, "POST", "/admin/calls/connect")?.body ?? ""),
                       JSONValue.parse(#"{"channel":"messenger","psid":"7788990011","sdp":"v=0 our-offer","name":"Grace Wanjiku"}"#))
        let r = try await api.requestMessengerPermission("7788990011")
        XCTAssertEqual(r.route, "calling_optin")
        XCTAssertEqual(JSONValue.parse(last(fake, "POST", "/admin/calls/request-permission")?.body ?? ""), JSONValue.parse(#"{"channel":"messenger","psid":"7788990011"}"#))
        // The renegotiation as a plain string (the accept sample's shape) reads the same.
        let plain = try NeemaJSON.decode(CallSdpResponse.self, from: #"{"ok":true,"call_id":"c_9","sdp":"v=0 a","renegotiation":"v=0 r"}"#)
        XCTAssertEqual(plain.renegotiationSdp, "v=0 r")
        XCTAssertNil(try NeemaJSON.decode(CallSdpResponse.self, from: #"{"ok":true,"call_id":"c_9","renegotiation":null}"#).renegotiationSdp)
    }

    func testTranscriptDecodesEveryVariant() async throws {
        let (_, _, raw) = rig()
        let done = try await raw.calls.transcript(callId: C1)
        XCTAssertEqual(done.status, "done")
        XCTAssertEqual(done.language, "en")
        XCTAssertTrue(done.recordingUrl!.hasPrefix("https://") && done.recordingUrl!.hasSuffix(".m4a"))
        // A legacy row: transcript_status NULL → status null; the panel reads it as "".
        let legacy = try NeemaJSON.decode(CallTranscript.self, from: #"{"call_id":"\#(C1)","status":null,"transcript":null,"summary":null,"language":null,"has_recording":false,"recording_url":null}"#)
        XCTAssertEqual(legacy.status, "")
        XCTAssertNil(legacy.recordingUrl)
        // MEDIA_PUBLIC_URL unset: recording_url is the bare saved file name.
        let bare = try NeemaJSON.decode(CallTranscript.self, from: #"{"call_id":"\#(C1)","status":"recorded","transcript":null,"summary":null,"language":null,"has_recording":true,"recording_url":"call_0f3e.m4a"}"#)
        XCTAssertEqual(bare.recordingUrl, "call_0f3e.m4a")
    }

    // ── Errors ───────────────────────────────────────────────────────────
    func testConnectErrorsMapToTheWebCopy() async throws {
        let (fake, api, _) = rig()
        func fail(_ code: Int, _ detail: String) async -> Error {
            fake.on("POST", "/admin/calls/connect", code: code, body: "{\"detail\":\(jsonString(detail))}")
            do { _ = try await api.connect(to: "254712345678", sdp: "sdp", name: nil); return PlainError("no error") } catch { return error }
        }
        // calls_connect: Meta error 138006 → 409 with the permission detail.
        let e409 = await fail(409, "This customer hasn't allowed calls yet. Send them a call request — you can call as soon as they tap Allow.")
        XCTAssertEqual((e409 as? ApiError)?.status, 409)
        XCTAssertEqual(CallManager.outboundError(e409), CallManager.NO_CALL_PERMISSION)
        XCTAssertTrue((e409 as! ApiError).detail.hasPrefix("This customer hasn't allowed calls yet"))
        for (code, detail) in [(400, "A valid phone number is required."), (400, "sdp offer is required"),
                               (502, "call failed: WA call connect failed (500)"), (502, "Meta did not return a call id")] {
            let e = await fail(code, detail)
            XCTAssertEqual(CallManager.outboundError(e), "Couldn't place the call", detail)
        }
    }

    func testAnswerErrorsMapPerHandler() async throws {
        let (fake, api, _) = rig()
        func answerErr() async -> Error { do { _ = try await api.answer(C1, sdp: "sdp"); return PlainError() } catch { return error } }
        func offerErr() async -> Error { do { _ = try await api.offer(C1); return PlainError() } catch { return error } }
        fake.on("POST", CallsFixtures.route(C1, "answer"), code: 409, body: #"{"detail":"call already answered"}"#)
        let e1 = await answerErr()
        XCTAssertEqual(CallManager.answerError(e1), CallManager.TAKEN_ELSEWHERE)
        fake.on("POST", CallsFixtures.route(C1, "answer"), code: 502, body: #"{"detail":"accept failed: boom"}"#)
        let e2 = await answerErr()
        XCTAssertEqual(CallManager.answerError(e2), "Couldn't connect the call")
        fake.on("GET", CallsFixtures.route(C1, "offer"), code: 404, body: #"{"detail":"call offer expired or not found"}"#)
        let e3 = await offerErr()
        XCTAssertEqual(CallManager.answerError(e3), CallManager.CALL_GONE)
        fake.on("GET", CallsFixtures.route(C1, "offer"), code: 503, body: #"{"detail":"calling unavailable"}"#)
        let e4 = await offerErr()
        XCTAssertEqual(CallManager.answerError(e4), "Couldn't connect the call")
    }

    func testRecordingRefusalsSurfaceAsApiErrors() async throws {
        let (fake, api, _) = rig()
        for (code, detail) in [(403, "Call recording is disabled."), (413, "Recording too large — max 60 MB."), (400, "Empty recording.")] {
            fake.on("POST", CallsFixtures.route(C1, "recording"), code: code, body: "{\"detail\":\(jsonString(detail))}")
            var caught: Error?
            do { try await api.uploadRecording(C1, file: UploadFile.of(file: tempRecording(), filename: "\(C1).m4a", mimeType: "audio/mp4")) } catch { caught = error }
            let e = caught as? ApiError
            XCTAssertEqual(e?.status, code); XCTAssertEqual(e?.detail, detail)
        }
    }

    func testTranscriptNotFoundIsAnError() async throws {
        let (fake, _, raw) = rig()
        fake.on("GET", CallsFixtures.route(C1, "transcript"), code: 404, body: #"{"detail":"Call not found"}"#)
        var caught: Error?
        do { _ = try await raw.calls.transcript(callId: C1) } catch { caught = error }
        XCTAssertNotNil(caught); XCTAssertEqual((caught as? ApiError)?.status, 404)
    }
}
