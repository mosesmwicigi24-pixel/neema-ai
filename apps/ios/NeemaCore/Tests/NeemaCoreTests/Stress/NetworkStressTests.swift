import XCTest
@testable import NeemaCore

/// Round 5 (Android `NetworkStressTest`) — a Nairobi phone network against
/// the real NeemaHTTP and AuthRepository: parallel 401s, refreshes that time
/// out or hit an outage, 429s, offline vs timeout, empty / HTML / huge
/// bodies, and sign-in when things are half broken. The rule throughout:
/// only the server refusing the session signs anyone out; an outage is an
/// error message.
final class NetworkStressTests: XCTestCase {
    private var fake: FakeNeema!
    private var clock: VirtualClock!
    private var store: SessionStore!
    private var auth: AuthRepository!
    private var http: NeemaHTTP!

    override func setUp() { fresh() }

    private func fresh() {
        fake = FakeNeema()
        clock = VirtualClock()
        fake.sleep = clock.sleeper
        store = SessionStore(store: MemoryStore())
        auth = AuthRepository(store: store, base: "https://neema.test", transport: fake, backoffMs: 0, sleep: clock.sleeper)
        http = NeemaHTTP(baseUrl: "https://neema.test", tokens: auth, transport: fake)
        http.gate = fake
    }

    @discardableResult
    private func session(_ access: String = fakeJwt("a1", expiresInSec: 3600)) -> Session {
        let s = Session(accessToken: access, refreshToken: "r-1", agentId: "a1", email: "moses@bethanyhouse.co.ke",
                        name: "Moses Mwicigi", role: "admin", isSuperuser: true, mode: "direct")
        store.save(s)
        return s
    }

    private func tokens(_ access: String) -> String {
        #"{"access_token":"\#(access)","refresh_token":"r-2","token_type":"bearer","agent_id":"a1","role":"admin","is_superuser":true}"#
    }

    private func expectApi(_ block: () async throws -> Void) async -> ApiError {
        do { try await block() } catch let e as ApiError { return e } catch { XCTFail("expected ApiError, got \(error)") }
        XCTFail("expected ApiError")
        return ApiError(status: -1, method: "", path: "", body: "")
    }

    /// Counts session-expired signals while `block` runs.
    private func expirations(_ block: () async -> Void) async -> Int {
        let n = Ref(0)
        let sub = http.sessionExpired.observe { n.mutate { $0 += 1 } }
        await block()
        sub.cancel()
        return n.value
    }

    private func refreshCalls() -> Int { fake.callsTo("POST", "/agent-auth/refresh").count }

    // ── 401s and the shared refresh ─────────────────────────────────────────

    func testManyParallel401sShareOneRefreshAndAllComplete() async throws {
        let old = session().accessToken
        let fresh = fakeJwt("a1", expiresInSec: 7200)
        let refreshes = Ref(0)
        fake.on("POST", "/agent-auth/refresh") { [tokens] _, _ in refreshes.mutate { $0 += 1 }; Thread.sleep(forTimeInterval: 0.03); return (200, tokens(fresh)) }
        fake.on("GET", "/admin/[a-z]+") { req, _ in
            req.headers["Authorization"] == "Bearer \(fresh)" ? (200, "{}") : (401, #"{"detail":"Token expired"}"#)
        }
        let paths = ["orders", "agents", "catalog", "me", "deals", "leads", "stats", "roles"]
        let http = self.http!
        let got = await withTaskGroup(of: String?.self) { group -> [String?] in
            for p in paths { group.addTask { try? await http.raw("GET", "/admin/\(p)") } }
            var out: [String?] = []
            for await r in group { out.append(r) }
            return out
        }
        XCTAssertTrue(got.allSatisfy { $0 == "{}" }, "\(got)")
        XCTAssertEqual(1, refreshes.value, "one refresh for the whole burst")
        XCTAssertEqual(fresh, store.current?.accessToken)
        XCTAssertNotEqual(old, fresh)
    }

    func testARefusedRefreshSignalsExpiryAndABurstAsksTheServerOnce() async {
        session()
        fake.on("GET", "/admin/[a-z]+", code: 401, body: #"{"detail":"Could not validate credentials"}"#)
        fake.on("POST", "/agent-auth/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let n = await expirations {
            for p in ["orders", "agents", "catalog", "me", "deals", "leads"] {
                let e = await expectApi { _ = try await http.raw("GET", "/admin/\(p)") }
                XCTAssertEqual(401, e.status)
            }
        }
        XCTAssertGreaterThanOrEqual(n, 1, "every failed request says so; the dialog is one state")
        XCTAssertEqual(1, refreshCalls(), "the verdict is remembered")
        XCTAssertNotNil(store.current, "the dialog re-authenticates over the same session")
    }

    func testARefreshThatTimesOutIsATimeoutNotASignOut() async {
        session()
        fake.on("GET", "/admin/orders", code: 401, body: #"{"detail":"Token expired"}"#)
        fake.timeout("POST", "/agent-auth/refresh")
        let n = await expirations {
            let e = await expectApi { _ = try await http.raw("GET", "/admin/orders") }
            XCTAssertEqual(0, e.status)
            XCTAssertTrue(e.timedOut)
            XCTAssertEqual(ErrorText.TIMED_OUT, ErrorText.of(e))
        }
        XCTAssertEqual(0, n, "no session-expired dialog")
        XCTAssertEqual(1, refreshCalls(), "a timeout is not retried (3 × 30 s would freeze every request)")
        XCTAssertNotNil(store.current)
    }

    func testARefreshDuringAnOutageKeepsTheSession() async {
        for (code, body) in [(500, #"{"detail":"Internal Server Error"}"#), (502, "<html><body>502 Bad Gateway</body></html>"), (503, ""), (429, "")] {
            fresh()
            session()
            fake.on("GET", "/admin/orders", code: 401, body: #"{"detail":"Token expired"}"#)
            fake.on("POST", "/agent-auth/refresh", code: code, body: body)
            fake.on("POST", "/auth/refresh", code: code, body: body)
            let n = await expirations {
                let e = await expectApi { _ = try await http.raw("GET", "/admin/orders") }
                XCTAssertEqual(code, e.status, "\(code)")
            }
            XCTAssertEqual(0, n, "\(code) must not sign anyone out")
            XCTAssertEqual(3, refreshCalls(), "\(code): three tries")
            XCTAssertNotNil(store.current)
        }
    }

    func testARefreshWhileOfflineOrBehindACaptivePortalKeepsTheSession() async {
        session()
        fake.on("GET", "/admin/orders", code: 401, body: #"{"detail":"Token expired"}"#)
        fake.drop("POST", "/agent-auth/refresh")
        var n = await expirations { let e = await expectApi { _ = try await http.raw("GET", "/admin/orders") }; XCTAssertEqual(0, e.status) }
        XCTAssertEqual(0, n)
        fake.heal()
        // A hotel wifi login page answers everything with its own HTML.
        fake.on("POST", "/(agent-)?auth/refresh", body: "<html><body>Sign in to NairobiFreeWiFi</body></html>")
        n = await expirations { let e = await expectApi { _ = try await http.raw("GET", "/admin/orders") }; XCTAssertEqual(0, e.status) }
        XCTAssertEqual(0, n)
        XCTAssertNotNil(store.current)
    }

    func testAnOutageDoesNotMakeEveryRequestWaitOutRefreshAttempts() async throws {
        // Inside the 5-minute buffer, so every request would try a proactive refresh.
        let expiring = session(fakeJwt("a1", expiresInSec: 120)).accessToken
        fake.on("POST", "/agent-auth/refresh", code: 503, body: "")
        fake.on("GET", "/admin/orders", body: "[]")
        for _ in 0..<5 { let r = try await http.raw("GET", "/admin/orders"); XCTAssertEqual("[]", r) }
        XCTAssertEqual(3, refreshCalls(), "one round of three, then a cool-down")
        XCTAssertTrue(fake.callsTo("GET", "/admin/orders").allSatisfy { $0.header("Authorization") == "Bearer \(expiring)" })
    }

    func testAnExpiredTokenDuringAnOutageFailsFastWithoutAPointlessRequest() async {
        session(fakeJwt("a1", expiresInSec: -10))
        fake.on("POST", "/agent-auth/refresh", code: 502, body: "<html>Bad Gateway</html>")
        fake.on("GET", "/admin/orders", body: "[]")
        let n = await expirations { let e = await expectApi { _ = try await http.raw("GET", "/admin/orders") }; XCTAssertEqual(502, e.status) }
        XCTAssertEqual(0, n)
        XCTAssertTrue(fake.callsTo("GET", "/admin/orders").isEmpty, "the API is not asked with a dead token")
    }

    // ── Statuses, bodies, network ───────────────────────────────────────────

    func testTooManyRequestsCarriesRetryAfter() async {
        session()
        fake.reply("POST", "/admin/conversations/c1/reply") { _, _ in
            FakeNeema.Reply(code: 429, body: #"{"detail":"Too Many Requests"}"#, headers: ["Retry-After": "12"])
        }
        let e = await expectApi { _ = try await http.raw("POST", "/admin/conversations/c1/reply") }
        XCTAssertEqual(429, e.status)
        XCTAssertEqual(12, e.retryAfterSeconds)
        XCTAssertTrue(ErrorText.of(e).contains("12"), ErrorText.of(e))
    }

    func testOfflineAndTimeoutReadDifferently() async {
        session()
        fake.offline = true
        let off = await expectApi { _ = try await http.raw("GET", "/admin/orders") }
        XCTAssertEqual(0, off.status); XCTAssertFalse(off.timedOut)
        XCTAssertEqual(ErrorText.OFFLINE, ErrorText.of(off))
        fake.offline = false
        fake.timeout("GET", "/admin/orders")
        let slow = await expectApi { _ = try await http.raw("GET", "/admin/orders") }
        XCTAssertEqual(0, slow.status); XCTAssertTrue(slow.timedOut)
        XCTAssertEqual(ErrorText.TIMED_OUT, ErrorText.of(slow))
    }

    func testADroppedConnectionRetriedSucceeds() async throws {
        session()
        fake.on("GET", "/admin/orders", body: "[]")
        fake.drop("GET", "/admin/orders", times: 1)
        let e = await expectApi { _ = try await http.raw("GET", "/admin/orders") }
        XCTAssertEqual(0, e.status)
        let r = try await http.raw("GET", "/admin/orders")
        XCTAssertEqual("[]", r)
    }

    func testEmptyHtmlAndCutOffBodiesNeverCrash() async throws {
        session()
        fake.on("GET", "/admin/empty", body: "")
        let empty: OkResponse? = try await http.get("/admin/empty")
        XCTAssertNil(empty)
        let obj: [String: String] = try await http.get("/admin/empty")
        XCTAssertEqual([:], obj)

        fake.on("GET", "/admin/portal", body: "<!doctype html><html><body>Log in to continue</body></html>")
        let portal = await expectApi { let _: OkResponse = try await http.get("/admin/portal") }
        XCTAssertTrue(portal.malformed)
        XCTAssertEqual(ErrorText.UNREADABLE, ErrorText.of(portal))

        fake.on("GET", "/admin/cut", body: #"[{"id":"o1","status":"pend"#)
        let cut = await expectApi { let _: [JSONValue] = try await http.get("/admin/cut") }
        XCTAssertTrue(cut.malformed)
    }

    func testAHugeErrorPageIsCappedAndNeverShown() async {
        session()
        let page = "<html><body>" + String(repeating: "x", count: 5_000_000) + "</body></html>"
        fake.on("GET", "/admin/orders", code: 502, body: page)
        let e = await expectApi { _ = try await http.raw("GET", "/admin/orders") }
        XCTAssertLessThanOrEqual(e.body.count, MAX_ERROR_BODY)
        XCTAssertEqual("", e.detail)
        XCTAssertEqual(ErrorText.DOWN, ErrorText.of(e))
        XCTAssertLessThan((e.errorDescription ?? "").count, 1_000)
    }

    // ── The fake's slow and hung server, on virtual time ────────────────────

    func testADelayedAnswerArrivesOnVirtualTime() async {
        session()
        fake.on("GET", "/admin/orders", body: "[]")
        fake.delay("GET", "/admin/orders", ms: 15_000)
        let http = self.http!
        let res = Task { try await http.raw("GET", "/admin/orders") }
        let done = Ref(false)
        Task { _ = try? await res.value; done.mutate { $0 = true } }
        await clock.advance(by: 14_000)
        XCTAssertFalse(done.value)
        XCTAssertTrue(fake.calls.isEmpty, "not sent until the delay is over")
        await clock.advance(by: 1_001)
        let r = try? await res.value
        XCTAssertEqual("[]", r)
    }

    func testAHungRequestWaitsForReleaseOrDrop() async {
        session()
        fake.on("POST", "/admin/orders/o1/status", body: #"{"ok":true}"#)
        let hold = fake.hang("POST", "/admin/orders/o1/status")
        let http = self.http!
        let first = Task { try await http.raw("POST", "/admin/orders/o1/status") }
        _ = await eventually { hold.waiting == 1 }
        await clock.advance(by: 600_000)
        XCTAssertEqual(1, hold.waiting)
        hold.release()
        let r1 = try? await first.value
        XCTAssertEqual(#"{"ok":true}"#, r1)

        let hold2 = fake.hang("POST", "/admin/orders/o1/status")
        let second = Task { try await http.raw("POST", "/admin/orders/o1/status") }
        _ = await eventually { hold2.waiting == 1 }
        hold2.drop()
        do { _ = try await second.value; XCTFail("expected a failure") } catch let e as ApiError { XCTAssertEqual(0, e.status) } catch { XCTFail("\(error)") }

        // Leaving mid-request: the caller is cancelled while held; the hold is abandoned.
        let before = fake.calls.count
        let hold3 = fake.hang("GET", "/admin/orders")
        let left = Task { try await http.raw("GET", "/admin/orders") }
        _ = await eventually { hold3.waiting == 1 }
        left.cancel()
        let r3 = await left.result
        if case .success = r3 { XCTFail("a cancelled request must not answer") }
        XCTAssertEqual(before, fake.calls.count, "nothing was sent")
    }

    // ── Sign-in when things are broken ──────────────────────────────────────

    private func loginError() async -> String {
        do { _ = try await auth.login(email: "moses@bethanyhouse.co.ke", password: "pw"); XCTFail("expected a refusal"); return "" }
        catch let e as AuthError { return e.message }
        catch { XCTFail("\(error)"); return "" }
    }

    func testLoginOfflineOrTimingOutSaysSo() async {
        fake.offline = true
        let off = await loginError()
        XCTAssertEqual(AuthRepository.OFFLINE, off)
        fake.offline = false
        fake.timeout("POST", "/agent-auth/login")
        let slow = await loginError()
        XCTAssertEqual(AuthRepository.TIMED_OUT, slow)
    }

    func testLoginAgainstAGatewayOutageOrRateLimitIsNotAWrongPassword() async {
        fake.on("POST", "/agent-auth/login", code: 503, body: "<html><body>503 Service Temporarily Unavailable</body></html>")
        let outage = await loginError()
        XCTAssertEqual(AuthRepository.UNAVAILABLE, outage)
        XCTAssertFalse(fake.called("GET", "/auth/csrf"), "an outage is final: no NextAuth detour")
        fake.on("POST", "/agent-auth/login", code: 429, body: "<html>Too Many Requests</html>")
        let limited = await loginError()
        XCTAssertEqual(AuthRepository.TOO_MANY, limited)
    }

    func testAHalfBrokenNextAuthIsUnavailableNotAWrongPassword() async {
        fake.on("POST", "/agent-auth/login", code: 404, body: #"{"detail":"Not Found"}"#)
        fake.on("POST", "/auth/login", code: 404, body: #"{"detail":"Not Found"}"#)
        fake.reply("GET", "/auth/csrf") { _, _ in FakeNeema.Reply(code: 200, body: #"{"csrfToken":"c"}"#) }
        // authorize() threw because FastAPI is down: NextAuth answers 500.
        fake.on("POST", "/auth/callback/credentials", code: 500, body: "Internal Server Error")
        let down = await loginError()
        XCTAssertEqual(AuthRepository.UNAVAILABLE, down)

        // Signed in, but the session endpoint is failing.
        fake.reply("POST", "/auth/callback/credentials") { _, _ in
            FakeNeema.Reply(code: 200, body: #"{"url":"https://neema.test/dashboard"}"#, setCookies: ["__Secure-next-auth.session-token=S; Path=/"])
        }
        fake.on("GET", "/auth/session", code: 502, body: "<html>Bad Gateway</html>")
        let gateway = await loginError()
        XCTAssertEqual(AuthRepository.UNAVAILABLE, gateway)

        // The session endpoint's connection drops.
        fake.drop("GET", "/auth/session")
        let dropped = await loginError()
        XCTAssertEqual(AuthRepository.OFFLINE, dropped)
        XCTAssertNil(store.current)
    }
}
