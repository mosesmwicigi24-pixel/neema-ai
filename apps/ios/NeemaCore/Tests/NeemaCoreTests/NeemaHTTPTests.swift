import XCTest
@testable import NeemaCore

/// lib/api.ts req(): bearer auth, the 30 s ceiling, 401 handling and error mapping.
final class NeemaHTTPTests: XCTestCase {
    private final class Tokens: TokenProvider, @unchecked Sendable {
        var current: String?
        var refreshTo: String?
        var refreshes = 0
        var rejected: [String?] = []
        init(_ current: String?, _ refreshTo: String?) { self.current = current; self.refreshTo = refreshTo }
        func validAccessToken() async throws -> String? { current }
        func forceRefresh() async throws -> String? { refreshes += 1; if let r = refreshTo { current = r }; return refreshTo }
        func onRejected(_ token: String?) { rejected.append(token) }
    }

    private var fake: FakeNeema!
    private var tokens: Tokens!
    private var http: NeemaHTTP!

    override func setUp() {
        fake = FakeNeema()
        tokens = Tokens("tok-1", nil)
        http = NeemaHTTP(baseUrl: "https://neema.test", tokens: tokens, transport: fake)
        http.gate = fake
    }

    func testEveryCallCarriesTheBearerTokenUnderApi() async throws {
        fake.on("GET", "/admin/me", body: #"{"ok":true}"#)
        let _: OkResponse = try await http.get("/admin/me")
        let c = fake.calls[0]
        XCTAssertEqual(fake.calls.count, 1)
        XCTAssertEqual("/admin/me", c.path)
        XCTAssertEqual("Bearer tok-1", c.header("Authorization"))
        XCTAssertEqual("application/json", c.header("Accept"))
    }

    func testNoTokenMeansNoAuthorizationHeader() async throws {
        tokens.current = nil
        fake.on("GET", "/health", body: "{}")
        _ = try await http.raw("GET", "/health")
        XCTAssertNil(fake.calls[0].header("Authorization"))
    }

    func testBodilessPostsSendAnEmptyJsonBody() async throws {
        fake.on("POST", "/admin/actions/x/veto", body: "{}")
        fake.on("DELETE", "/admin/roles/r", body: #"{"ok":true}"#)
        _ = try await http.raw("POST", "/admin/actions/x/veto")
        let _: OkResponse = try await http.delete("/admin/roles/r")
        XCTAssertEqual("", fake.calls[0].body)
        XCTAssertNil(fake.calls[1].body)
    }

    func testBlankBodiesDecode() async throws {
        fake.on("PATCH", "/admin/catalog/1", body: "")
        let v: JSONValue = try await http.patch("/admin/catalog/1", JSONValue.object([:]))
        XCTAssertEqual(v, .null)
        let none: OkResponse? = try http.decode("")
        XCTAssertNil(none)
        let ok: OkResponse = try http.decode("")
        XCTAssertTrue(ok.ok)
        let list: [Agent] = try http.decode("   ")
        XCTAssertTrue(list.isEmpty)
    }

    func testA401IsRescuedByOneRefreshAndRetried() async throws {
        tokens.refreshTo = "tok-2"
        fake.on("GET", "/admin/agents") { req, _ in
            req.header("Authorization") == "Bearer tok-2" ? (200, "[]") : (401, #"{"detail":"Token expired"}"#)
        }
        let got1 = try await http.raw("GET", "/admin/agents")
        XCTAssertEqual("[]", got1)
        XCTAssertEqual(["tok-1"], tokens.rejected)
        XCTAssertEqual(1, tokens.refreshes)
        XCTAssertEqual(2, fake.calls.count)
    }

    func testA401ThatCannotBeRefreshedSignalsSessionExpired() async throws {
        var expired = 0
        let sub = http.sessionExpired.observe { expired += 1 }
        defer { sub.cancel() }
        fake.on("GET", "/admin/orders", code: 401, body: #"{"detail":"Not authenticated"}"#)
        let e = await expectApi { try await self.http.raw("GET", "/admin/orders") }
        XCTAssertEqual(401, e?.status)
        XCTAssertEqual("Session expired", e?.body)
        XCTAssertEqual(1, expired)
        XCTAssertEqual(1, fake.calls.count, "no retry without a fresh token")
    }

    func testASecond401AfterRefreshAlsoSignalsSessionExpired() async throws {
        tokens.refreshTo = "tok-2"
        var expired = 0
        let sub = http.sessionExpired.observe { expired += 1 }
        defer { sub.cancel() }
        fake.on("GET", "/admin/orders", code: 401, body: "{}")
        let e = await expectApi { try await self.http.raw("GET", "/admin/orders") }
        XCTAssertEqual(401, e?.status)
        XCTAssertEqual(1, expired)
        XCTAssertEqual(2, fake.calls.count)
    }

    /// FastAPI's HTTPBearer answers a request with NO token 403: the same dead session.
    func testA403WithoutATokenIsTheDeadSession() async throws {
        tokens.current = nil
        fake.on("GET", "/admin/orders", code: 403, body: #"{"detail":"Not authenticated"}"#)
        let e = await expectApi { try await self.http.raw("GET", "/admin/orders") }
        XCTAssertEqual(401, e?.status)
        XCTAssertEqual(1, tokens.refreshes)
    }

    func testA403WithATokenSignalsForbiddenExceptForIdentityReads() async throws {
        var seen: [String] = []
        let sub = http.forbidden.observe { seen.append($0) }
        defer { sub.cancel() }
        fake.on("POST", "/admin/agents", code: 403, body: #"{"detail":"Admins only"}"#)
        fake.on("GET", "/admin/me", code: 403, body: "{}")
        fake.on("GET", "/admin/agents", code: 403, body: "{}")
        _ = await expectApi { try await self.http.raw("POST", "/admin/agents?x=1") }
        _ = await expectApi { try await self.http.raw("GET", "/admin/me") }
        _ = await expectApi { try await self.http.raw("GET", "/admin/agents/") }
        XCTAssertEqual(["POST /admin/agents"], seen)
        XCTAssertEqual(0, tokens.refreshes)
    }

    func testServerErrorsCarryTheDetail() async {
        fake.on("POST", "/admin/agents", code: 422, body: #"{"detail":"Missing required fields: email"}"#)
        let e = await expectApi { try await self.http.raw("POST", "/admin/agents") }
        XCTAssertEqual(422, e?.status)
        XCTAssertEqual("Missing required fields: email", e?.detail)
        XCTAssertEqual("POST", e?.method)
        XCTAssertEqual("/admin/agents", e?.path)
        XCTAssertTrue(e!.message.hasPrefix("POST /admin/agents → 422"), e!.message)
    }

    func testStructuredOrNonJsonDetailsFallBackSensibly() async {
        fake.on("GET", "/a", code: 422, body: #"{"detail":[{"loc":["body","email"],"msg":"field required"}]}"#)
        fake.on("GET", "/b", code: 502, body: "<html>Bad Gateway</html>")
        let a = await expectApi { try await self.http.raw("GET", "/a") }
        XCTAssertTrue(a!.detail.contains("field required"))
        let b = await expectApi { try await self.http.raw("GET", "/b") }
        XCTAssertEqual("", b?.detail)
    }

    func testNetworkFailuresAreStatusZero() async {
        fake.drop("GET", "/down")
        fake.timeout("GET", "/slow")
        let down = await expectApi { try await self.http.raw("GET", "/down") }
        XCTAssertEqual(0, down?.status)
        XCTAssertEqual("Connection reset", down?.body)
        let slow = await expectApi { try await self.http.raw("GET", "/slow") }
        XCTAssertEqual(0, slow?.status)
        XCTAssertEqual("timed out after 30s", slow?.body)
    }

    func testAnUploadsTimeoutSaysTenMinutes() async {
        fake.timeout("POST", "/admin/x/recording")
        let e = await expectApi { try await self.http.raw("POST", "/admin/x/recording", body: .json("{}"), upload: true) }
        XCTAssertEqual("timed out after 10 min", e?.body)
        XCTAssertTrue(e!.timedOut)
    }

    func testRetryAfterAndReasonHeadersAreRead() async {
        fake.reply("POST", "/admin/calls/connect") { _, _ in
            FakeNeema.Reply(code: 429, body: "{}", headers: ["Retry-After": " 45 ", "X-Neema-Reason": "rate_limited"])
        }
        let e = await expectApi { try await self.http.raw("POST", "/admin/calls/connect") }
        XCTAssertEqual(45, e?.retryAfterSeconds)
        XCTAssertEqual("rate_limited", e?.code)
    }

    func testA404IsAnErrorNotASessionProblem() async {
        fake.on("GET", "/admin/orders/x", code: 404, body: #"{"detail":"Order not found"}"#)
        let e = await expectApi { try await self.http.raw("GET", "/admin/orders/x") }
        XCTAssertEqual(404, e?.status)
        XCTAssertEqual(0, tokens.refreshes)
        XCTAssertTrue(tokens.rejected.isEmpty)
    }

    func testAbsoluteUrlsAreUsedAsIs() async throws {
        fake.on("GET", "/media/x.jpg", body: "{}")
        _ = try await http.raw("GET", "https://neema.test/api/media/x.jpg")
        XCTAssertEqual("/media/x.jpg", fake.calls[0].path)
    }

    func testAMalformed2xxIsAReadableFailure() async {
        fake.on("GET", "/admin/me", body: "<html>captive portal</html>")
        let e = await expectApi { let a: Agent = try await self.http.get("/admin/me"); return a }
        XCTAssertEqual(true, e?.malformed)
        XCTAssertEqual(ErrorText.UNREADABLE, ErrorText.of(e!))
    }

    /// Calls' carry-over: api.calls.uploadRecording(id, UploadFile.of(file:)) survives a token refresh.
    func testAFileBackedRecordingIsResentWholeAfterA401() async throws {
        tokens.refreshTo = "tok-2"
        let f = FileManager.default.temporaryDirectory.appendingPathComponent("wacid-\(UUID().uuidString).m4a")
        try Data((0..<(64 * 1024)).map { UInt8($0 % 239) }).write(to: f)
        defer { try? FileManager.default.removeItem(at: f) }
        var sizes: [Int] = []
        fake.on("POST", "/admin/calls/wacid.9/recording") { req, body in
            sizes.append(body!.utf8.count)
            return req.header("Authorization") == "Bearer tok-2" ? (200, #"{"ok":true,"will_transcribe":false}"#) : (401, #"{"detail":"Token expired"}"#)
        }
        let api = NeemaApi(http: http)
        let res = try await api.calls.uploadRecording(callId: "wacid.9", file: UploadFile.of(file: f, filename: "wacid.9.m4a", mimeType: "audio/mp4"))
        XCTAssertEqual(false, res.willTranscribe)
        XCTAssertEqual(2, sizes.count, "sent twice (401, then the retry)")
        XCTAssertEqual(sizes[0], sizes[1], "the retry re-read the whole file")
        XCTAssertTrue(sizes[0] > 64 * 1024)
        XCTAssertTrue(fake.calls[0].body!.contains("filename=\"wacid.9.m4a\""))
        XCTAssertTrue(fake.calls[0].body!.contains("Content-Type: audio/mp4"))
    }

    func testAMissingRecordingFileIsANetworkStyleErrorNotACrash() async {
        let gone = URL(fileURLWithPath: "/nonexistent/neema/rec.m4a")
        fake.on("POST", "/admin/calls/x/recording", body: "{}")
        let api = NeemaApi(http: http)
        let e = await expectApi { try await api.calls.uploadRecording(callId: "x", file: UploadFile.of(file: gone, mimeType: "audio/mp4")) }
        XCTAssertEqual(0, e?.status)
    }

    func testARefreshOutageFailsOnlyThisRequest() async {
        final class Outage: TokenProvider {
            func validAccessToken() async throws -> String? { throw RefreshUnavailable(status: 503, timedOut: false, message: "auth server answered 503") }
            func forceRefresh() async throws -> String? { nil }
            func onRejected(_ token: String?) {}
        }
        let h = NeemaHTTP(baseUrl: "https://neema.test", tokens: Outage(), transport: fake)
        var expired = 0
        let sub = h.sessionExpired.observe { expired += 1 }
        defer { sub.cancel() }
        let e = await expectApi { try await h.raw("GET", "/admin/orders") }
        XCTAssertEqual(503, e?.status)
        XCTAssertEqual(0, expired)
        XCTAssertTrue(fake.calls.isEmpty)
    }

    func testCancellingTheCallerEndsAsCancelledNotAsANetworkError() async throws {
        let hold = fake.hang("GET", "/admin/slow")
        let task = Task { try await self.http.raw("GET", "/admin/slow") }
        await eventually { hold.caught == 1 }
        task.cancel()
        hold.drop()
        do { _ = try await task.value; XCTFail("expected cancellation") }
        catch is CancellationError { }
        catch { XCTFail("expected CancellationError, got \(error)") }
    }
}
