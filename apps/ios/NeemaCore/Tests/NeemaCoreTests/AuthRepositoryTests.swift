import XCTest
@testable import NeemaCore

/// Sign-in and silent refresh (lib/auth.ts + the NextAuth route) against a
/// fake that plays both FastAPI's `/api/agent-auth` routes and NextAuth's
/// csrf → callback → session flow.
final class AuthRepositoryTests: XCTestCase {
    private var fake: FakeNeema!
    private var store: SessionStore!
    private var memory: MemoryStore!
    private var auth: AuthRepository!

    override func setUp() {
        AppClock.pin(to: PINNED)
        fake = FakeNeema()
        memory = MemoryStore()
        store = SessionStore(store: memory)
        auth = AuthRepository(store: store, base: "https://neema.test", transport: fake, backoffMs: 0)
    }

    override func tearDown() { AppClock.reset() }

    private func tokens(_ access: String, refresh: String = "r-1", role: String = "admin", superuser: Bool = true) -> String {
        #"{"access_token":"\#(access)","refresh_token":"\#(refresh)","token_type":"bearer","agent_id":"a1","role":"\#(role)","is_superuser":\#(superuser)}"#
    }

    private func direct(_ access: String = fakeJwt("a1", expiresInSec: 3600)) -> Session {
        Session(accessToken: access, refreshToken: "r-1", agentId: "a1", email: "moses@bethanyhouse.co.ke",
                name: "Moses Mwicigi", role: "admin", isSuperuser: true, mode: "direct")
    }

    /// NextAuth v4 (the deployed app/api/auth/[...nextauth]/route.ts): csrf, credentials callback, session.
    private func installNextAuth(sessionAccess: String, wrongPassword: Bool = false) {
        fake.reply("GET", "/auth/csrf") { _, _ in
            FakeNeema.Reply(code: 200, body: #"{"csrfToken":"csrf-123"}"#, setCookies: ["__Host-next-auth.csrf-token=csrf-123%7Chash; Path=/; HttpOnly"])
        }
        fake.reply("POST", "/auth/callback/credentials") { _, _ in
            if wrongPassword { return FakeNeema.Reply(code: 200, body: #"{"url":"https://neema.test/api/auth/error?error=CredentialsSignin&provider=credentials"}"#) }
            return FakeNeema.Reply(code: 200, body: #"{"url":"https://neema.test/dashboard"}"#,
                                   setCookies: ["__Secure-next-auth.session-token=SESS-1; Path=/; HttpOnly; Secure"])
        }
        fake.reply("GET", "/auth/session") { req, _ in
            guard req.header("Cookie")?.contains("next-auth.session-token=SESS") == true else { return FakeNeema.Reply(code: 200, body: "{}") }
            return FakeNeema.Reply(
                code: 200,
                body: #"{"user":{"id":"a1","email":"moses@bethanyhouse.co.ke"},"accessToken":"\#(sessionAccess)","expires":"2099-01-01T00:00:00Z"}"#,
                setCookies: ["__Secure-next-auth.session-token=SESS-2; Path=/; HttpOnly; Secure"]
            )
        }
    }

    // ── Login ───────────────────────────────────────────────────────────────

    func testDirectLoginSavesTheFastApiSession() async throws {
        let access = fakeJwt("a1", expiresInSec: 3600)
        fake.on("POST", "/agent-auth/login", body: tokens(access))

        let s = try await auth.login(email: "moses@bethanyhouse.co.ke", password: "pw")

        XCTAssertEqual("direct", s.mode)
        XCTAssertEqual(access, s.accessToken)
        XCTAssertEqual("r-1", s.refreshToken)
        XCTAssertEqual("a1", s.agentId)
        XCTAssertEqual("admin", s.role)
        XCTAssertTrue(s.isSuperuser)
        XCTAssertEqual(s, store.current)
        let body = fake.callsTo("POST", "/agent-auth/login")[0].body!
        XCTAssertTrue(body.contains("\"email\":\"moses@bethanyhouse.co.ke\"") && body.contains("\"password\":\"pw\""), body)
        XCTAssertFalse(fake.called("GET", "/auth/csrf"), "never touches NextAuth when the direct route answers")
        XCTAssertEqual(access, memory.snapshot["access"])
    }

    func testWrongPasswordOnTheDirectRouteIsFinal() async {
        fake.on("POST", "/agent-auth/login", code: 401, body: #"{"detail":"Invalid credentials"}"#)
        let e = await expectAuth { try await self.auth.login(email: "moses@bethanyhouse.co.ke", password: "nope") }
        XCTAssertEqual("Invalid email or password. Please try again.", e?.message)
        XCTAssertNil(store.current)
        XCTAssertFalse(fake.called("GET", "/auth/csrf"), "a wrong password must not fall through to NextAuth")
    }

    func testInvalidEmailShapeIsAWrongPasswordToo() async {
        fake.on("POST", "/agent-auth/login", code: 422, body: #"{"detail":[{"msg":"value is not a valid email"}]}"#)
        let e = await expectAuth { try await self.auth.login(email: "nobody", password: "pw") }
        XCTAssertTrue(e!.message.hasPrefix("Invalid"))
    }

    func testMissingDirectRouteFallsBackToNextAuth() async throws {
        let access = fakeJwt("a1", expiresInSec: 3600)
        fake.on("POST", "/agent-auth/login", code: 404, body: #"{"detail":"Not Found"}"#)
        installNextAuth(sessionAccess: access)

        let s = try await auth.login(email: "moses@bethanyhouse.co.ke", password: "pw")

        XCTAssertEqual("nextauth", s.mode)
        XCTAssertEqual(access, s.accessToken)
        XCTAssertNil(s.refreshToken, "route.ts keeps no refresh token")
        XCTAssertEqual("a1", s.agentId)
        XCTAssertEqual("agent", s.role)
        XCTAssertEqual("__Secure-next-auth.session-token=SESS-2", s.nextAuthCookie, "the session call rotates the cookie")
        let cb = fake.callsTo("POST", "/auth/callback/credentials")[0]
        XCTAssertTrue(cb.body!.contains("csrfToken=csrf-123") && cb.body!.contains("email=moses%40bethanyhouse.co.ke"), cb.body!)
        XCTAssertTrue(cb.header("Cookie")!.contains("__Host-next-auth.csrf-token="))
        XCTAssertEqual(s, store.current)
    }

    func testAnHtmlPageFromTheDirectRouteAlsoFallsBack() async throws {
        fake.on("POST", "/agent-auth/login", body: "<!doctype html><html>Next.js</html>")
        installNextAuth(sessionAccess: fakeJwt("a1", expiresInSec: 3600))
        let got1 = try await auth.login(email: "moses@bethanyhouse.co.ke", password: "pw").mode
        XCTAssertEqual("nextauth", got1)
    }

    func testNextAuthWrongPassword() async {
        fake.on("POST", "/agent-auth/login", code: 405, body: "{}")
        installNextAuth(sessionAccess: fakeJwt("a1", expiresInSec: 3600), wrongPassword: true)
        let e = await expectAuth { try await self.auth.login(email: "moses@bethanyhouse.co.ke", password: "nope") }
        XCTAssertEqual("Invalid email or password. Please try again.", e?.message)
        XCTAssertNil(store.current)
    }

    func testLogoutForgetsTokensButRemembersWhoWasSignedIn() {
        store.save(direct())
        auth.logout()
        XCTAssertNil(store.current)
        XCTAssertEqual("moses@bethanyhouse.co.ke", store.lastEmail)
        XCTAssertNil(memory.snapshot["access"])
    }

    func testOfflineAndTimeoutsSpeakForThemselves() async {
        fake.offline = true
        var e = await expectAuth { try await self.auth.login(email: "m@b.co", password: "pw") }
        XCTAssertEqual(AuthRepository.OFFLINE, e?.message)
        fake.heal()
        fake.timeout("POST", "/agent-auth/login")
        e = await expectAuth { try await self.auth.login(email: "m@b.co", password: "pw") }
        XCTAssertEqual(AuthRepository.TIMED_OUT, e?.message)
        fake.heal()
        fake.on("POST", "/agent-auth/login", code: 429, body: "{}")
        e = await expectAuth { try await self.auth.login(email: "m@b.co", password: "pw") }
        XCTAssertEqual(AuthRepository.TOO_MANY, e?.message)
        fake.on("POST", "/agent-auth/login", code: 503, body: "<html>Service Unavailable</html>")
        e = await expectAuth { try await self.auth.login(email: "m@b.co", password: "pw") }
        XCTAssertEqual(AuthRepository.UNAVAILABLE, e?.message)
    }

    // ── Refresh ─────────────────────────────────────────────────────────────

    func testATokenWithTimeLeftIsUsedAsIs() async throws {
        let s = direct(fakeJwt("a1", expiresInSec: 3600))
        store.save(s)
        let got1 = try await auth.validAccessToken()
        XCTAssertEqual(s.accessToken, got1)
        XCTAssertFalse(fake.called("POST", "/agent-auth/refresh"))
    }

    func testATokenInsideTheFiveMinuteBufferIsRefreshedFirst() async throws {
        store.save(direct(fakeJwt("a1", expiresInSec: 120)))
        let fresh = fakeJwt("a1", expiresInSec: 3600)
        fake.on("POST", "/agent-auth/refresh", body: tokens(fresh, refresh: "r-2"))

        let got1 = try await auth.validAccessToken()
        XCTAssertEqual(fresh, got1)

        let body = fake.callsTo("POST", "/agent-auth/refresh")[0].body!
        XCTAssertTrue(body.contains("\"refresh_token\":\"r-1\""), body)
        let saved = store.current!
        XCTAssertEqual(fresh, saved.accessToken)
        XCTAssertEqual("r-2", saved.refreshToken)
        XCTAssertEqual("Moses Mwicigi", saved.name, "keeps the profile name")
        XCTAssertEqual("moses@bethanyhouse.co.ke", saved.email)
    }

    func testARefusedRefreshIsFinalAtOnce() async throws {
        let expiring = fakeJwt("a1", expiresInSec: 120)
        store.save(direct(expiring))
        fake.on("POST", "/agent-auth/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)

        let got1 = try await auth.forceRefresh()
        XCTAssertNil(got1)
        XCTAssertEqual(1, fake.callsTo("POST", "/agent-auth/refresh").count)
        // Still unexpired, so it is handed out until the server says otherwise.
        let got2 = try await auth.validAccessToken()
        XCTAssertEqual(expiring, got2)
        XCTAssertEqual(1, fake.callsTo("POST", "/agent-auth/refresh").count, "the refusal is remembered: no second ask")
    }

    func testAnExpiredTokenThatCannotBeRefreshedIsNotHandedOut() async throws {
        store.save(direct(fakeJwt("a1", expiresInSec: -60)))
        fake.on("POST", "/agent-auth/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let got1 = try await auth.validAccessToken()
        XCTAssertNil(got1)
    }

    func testAnExpiredTokenDuringAnOutageFailsAsTheOutageNotAsSignedOut() async {
        store.save(direct(fakeJwt("a1", expiresInSec: -60)))
        fake.on("POST", "/agent-auth/refresh", code: 500, body: "{}")
        do { _ = try await auth.validAccessToken(); XCTFail("expected RefreshUnavailable") }
        catch let e as RefreshUnavailable { XCTAssertEqual(500, e.status) }
        catch { XCTFail("\(error)") }
        XCTAssertEqual(3, fake.callsTo("POST", "/agent-auth/refresh").count, "three attempts while the server can't answer")
        XCTAssertNotNil(store.current, "the session stays")
    }

    func testATimeoutIsNotRetriedThreeTimes() async {
        store.save(direct(fakeJwt("a1", expiresInSec: -60)))
        fake.timeout("POST", "/agent-auth/refresh")
        fake.timeout("POST", "/auth/refresh")
        do { _ = try await auth.forceRefresh(); XCTFail() }
        catch let e as RefreshUnavailable { XCTAssertTrue(e.timedOut) }
        catch { XCTFail("\(error)") }
        XCTAssertEqual(1, fake.callsTo("POST", "/agent-auth/refresh").count)
    }

    func testARefreshThatSucceedsOnTheSecondTryIsUsed() async throws {
        store.save(direct(fakeJwt("a1", expiresInSec: 60)))
        let fresh = fakeJwt("a1", expiresInSec: 3600)
        var n = 0
        fake.on("POST", "/agent-auth/refresh") { _, _ in n += 1; return n == 1 ? (502, "bad gateway") : (200, self.tokens(fresh)) }
        let got1 = try await auth.forceRefresh()
        XCTAssertEqual(fresh, got1)
        XCTAssertEqual(2, n)
    }

    func testARejectedButUnexpiredTokenIsRefreshedAnyway() async throws {
        let revoked = fakeJwt("a1", expiresInSec: 3600)
        store.save(direct(revoked))
        let fresh = fakeJwt("a2", expiresInSec: 3600)
        fake.on("POST", "/agent-auth/refresh", body: tokens(fresh))

        auth.onRejected(revoked)
        let got1 = try await auth.forceRefresh()
        XCTAssertEqual(fresh, got1)
    }

    func testConcurrentCallersShareOneRefresh() async throws {
        store.save(direct(fakeJwt("a1", expiresInSec: 30)))
        let fresh = fakeJwt("a1", expiresInSec: 3600)
        fake.on("POST", "/agent-auth/refresh", body: tokens(fresh))

        let got: [String?] = try await withThrowingTaskGroup(of: String?.self) { group in
            for _ in 1...5 { group.addTask { try await self.auth.validAccessToken() } }
            var out: [String?] = []
            for try await t in group { out.append(t) }
            return out
        }

        XCTAssertTrue(got.allSatisfy { $0 == fresh })
        XCTAssertEqual(1, fake.callsTo("POST", "/agent-auth/refresh").count)
    }

    func testNextAuthSessionsRefreshThroughTheSessionEndpoint() async throws {
        let fresh = fakeJwt("a1", expiresInSec: 3600)
        installNextAuth(sessionAccess: fresh)
        var s = direct(fakeJwt("a1", expiresInSec: 60))
        s.refreshToken = nil; s.mode = "nextauth"; s.nextAuthCookie = "__Secure-next-auth.session-token=SESS-1"
        store.save(s)

        let got1 = try await auth.validAccessToken()
        XCTAssertEqual(fresh, got1)
        XCTAssertEqual("__Secure-next-auth.session-token=SESS-2", store.current!.nextAuthCookie)
        XCTAssertEqual("nextauth", store.current!.mode)
    }

    func testNextAuthHandingBackTheRefusedTokenIsNoRescue() async throws {
        let stale = fakeJwt("a1", expiresInSec: 3600)
        installNextAuth(sessionAccess: stale)
        var s = direct(stale)
        s.refreshToken = nil; s.mode = "nextauth"; s.nextAuthCookie = "__Secure-next-auth.session-token=SESS-1"
        store.save(s)

        auth.onRejected(stale)
        let got1 = try await auth.forceRefresh()
        XCTAssertNil(got1)
    }

    func testNoSessionMeansNoToken() async throws {
        let got1 = try await auth.validAccessToken()
        XCTAssertNil(got1)
        let got2 = try await auth.forceRefresh()
        XCTAssertNil(got2)
        XCTAssertTrue(fake.calls.isEmpty)
    }

    // ── The contract of routers/auth.py and NextAuth v4 ──────────────────────

    func testTheOriginalFastApiMountIsTriedBeforeNextAuth() async throws {
        let access = fakeJwt("a1", expiresInSec: 3600)
        fake.on("POST", "/agent-auth/login", code: 404, body: #"{"detail":"Not Found"}"#)
        fake.on("POST", "/auth/login", body: tokens(access, role: "agent", superuser: false))

        let s = try await auth.login(email: "grace@bethanyhouse.co.ke", password: "pw")

        XCTAssertEqual("direct", s.mode)
        XCTAssertEqual(access, s.accessToken)
        XCTAssertEqual("agent", s.role)
        XCTAssertFalse(s.isSuperuser)
        XCTAssertFalse(fake.called("GET", "/auth/csrf"))
    }

    func testAWrongPasswordOnTheOriginalMountIsFinalToo() async {
        fake.on("POST", "/agent-auth/login", code: 404, body: #"{"detail":"Not Found"}"#)
        fake.on("POST", "/auth/login", code: 401, body: #"{"detail":"Invalid credentials"}"#)
        let e = await expectAuth { try await self.auth.login(email: "g@b.co", password: "nope") }
        XCTAssertTrue(e!.message.hasPrefix("Invalid"))
        XCTAssertFalse(fake.called("GET", "/auth/csrf"))
    }

    func testNextAuthsPlainTextAnswerToALoginPostFallsThrough() async throws {
        fake.on("POST", "/agent-auth/login", code: 404, body: #"{"detail":"Not Found"}"#)
        fake.on("POST", "/auth/login", code: 400, body: "Error: This action with HTTP POST is not supported by NextAuth.js")
        installNextAuth(sessionAccess: fakeJwt("a1", expiresInSec: 3600))
        let got1 = try await auth.login(email: "moses@bethanyhouse.co.ke", password: "pw").mode
        XCTAssertEqual("nextauth", got1)
    }

    func testAServerErrorIsNotReportedAsAWrongPassword() async {
        fake.on("POST", "/agent-auth/login", code: 500, body: #"{"detail":"Internal Server Error"}"#)
        let e = await expectAuth { try await self.auth.login(email: "moses@bethanyhouse.co.ke", password: "pw") }
        XCTAssertEqual("Sign-in is unavailable right now. Please try again shortly.", e?.message)
        XCTAssertFalse(fake.called("GET", "/auth/csrf"), "NextAuth would only relay the same failure")
    }

    func testATokenResponseWithoutATokenIsNotASession() async throws {
        fake.on("POST", "/agent-auth/login", body: #"{"ok":true}"#)
        fake.on("POST", "/auth/login", body: #"{"ok":true}"#)
        installNextAuth(sessionAccess: fakeJwt("a1", expiresInSec: 3600))
        let got1 = try await auth.login(email: "moses@bethanyhouse.co.ke", password: "pw").mode
        XCTAssertEqual("nextauth", got1)
    }

    func testRefreshFallsBackToTheOriginalMount() async throws {
        store.save(direct(fakeJwt("a1", expiresInSec: 60)))
        let fresh = fakeJwt("a1", expiresInSec: 3600)
        fake.on("POST", "/agent-auth/refresh", code: 404, body: #"{"detail":"Not Found"}"#)
        fake.on("POST", "/auth/refresh", body: tokens(fresh, refresh: "r-9"))
        let got1 = try await auth.forceRefresh()
        XCTAssertEqual(fresh, got1)
        XCTAssertEqual("r-9", store.current!.refreshToken)
        XCTAssertTrue(fake.callsTo("POST", "/auth/refresh")[0].body!.contains("\"refresh_token\":\"r-1\""))
    }

    func testADeletedAgentsRefreshIsARealAnswer() async throws {
        store.save(direct(fakeJwt("a1", expiresInSec: 60)))
        fake.on("POST", "/agent-auth/refresh", code: 404, body: #"{"detail":"Agent not found"}"#)
        let got1 = try await auth.forceRefresh()
        XCTAssertNil(got1)
        XCTAssertFalse(fake.called("POST", "/auth/refresh"))
    }

    func testNoAuthRouteAnsweringIsAnOutageNotARefusal() async {
        store.save(direct(fakeJwt("a1", expiresInSec: -60)))
        fake.on("POST", "/agent-auth/refresh", body: "<html>captive portal</html>")
        fake.on("POST", "/auth/refresh", body: "<html>captive portal</html>")
        do { _ = try await auth.forceRefresh(); XCTFail() }
        catch let e as RefreshUnavailable { XCTAssertEqual(0, e.status) }
        catch { XCTFail("\(error)") }
        XCTAssertNotNil(store.current)
    }

    func testARefreshKeepsTheRoleTheServerNowReports() async throws {
        store.save(direct(fakeJwt("a1", expiresInSec: 60)))
        fake.on("POST", "/agent-auth/refresh", body: tokens(fakeJwt("a1", expiresInSec: 3600), role: "readonly", superuser: false))
        _ = try await auth.forceRefresh()
        XCTAssertEqual("readonly", store.current!.role)
        XCTAssertFalse(store.current!.isSuperuser)
    }

    func testChunkedNextAuthSessionCookiesAreAllSent() async throws {
        let access = fakeJwt("a1", expiresInSec: 3600)
        fake.on("POST", "/agent-auth/login", code: 404, body: #"{"detail":"Not Found"}"#)
        fake.reply("GET", "/auth/csrf") { _, _ in
            FakeNeema.Reply(code: 200, body: #"{"csrfToken":"c"}"#, setCookies: ["__Host-next-auth.csrf-token=c%7Ch; Path=/"])
        }
        fake.reply("POST", "/auth/callback/credentials") { _, _ in
            FakeNeema.Reply(code: 302, body: "", headers: ["Location": "https://neema.test/dashboard"], setCookies: [
                "__Secure-next-auth.session-token.0=PART-A; Path=/; HttpOnly; Secure",
                "__Secure-next-auth.session-token.1=PART-B; Path=/; HttpOnly; Secure",
                "__Secure-next-auth.callback-url=https%3A%2F%2Fneema.test; Path=/",
            ])
        }
        var seen = ""
        fake.reply("GET", "/auth/session") { req, _ in
            seen = req.header("Cookie") ?? ""
            return FakeNeema.Reply(code: 200, body: #"{"user":{"email":"moses@bethanyhouse.co.ke","id":"a1"},"expires":"2099-01-01T00:00:00.000Z","accessToken":"\#(access)"}"#,
                                   setCookies: [
                                    "__Secure-next-auth.session-token=WHOLE; Path=/; HttpOnly; Secure",
                                    "__Secure-next-auth.session-token.0=; Max-Age=0; Path=/",
                                    "__Secure-next-auth.session-token.1=; Max-Age=0; Path=/",
                                   ])
        }

        let s = try await auth.login(email: "moses@bethanyhouse.co.ke", password: "pw")

        XCTAssertEqual("__Secure-next-auth.session-token.0=PART-A; __Secure-next-auth.session-token.1=PART-B", seen)
        XCTAssertEqual("__Secure-next-auth.session-token=WHOLE", s.nextAuthCookie)
        XCTAssertEqual(access, s.accessToken)
        XCTAssertEqual("moses@bethanyhouse.co.ke", s.name, "route.ts sends no name: the email stands in")
    }

    func testAStaleCsrfIsNotAWrongPassword() async {
        fake.on("POST", "/agent-auth/login", code: 404, body: #"{"detail":"Not Found"}"#)
        installNextAuth(sessionAccess: fakeJwt("a1", expiresInSec: 3600))
        fake.reply("POST", "/auth/callback/credentials") { _, _ in FakeNeema.Reply(code: 200, body: #"{"url":"https://neema.test/api/auth/signin?csrf=true"}"#) }
        let e = await expectAuth { try await self.auth.login(email: "moses@bethanyhouse.co.ke", password: "pw") }
        XCTAssertEqual("Sign-in is unavailable right now. Please try again shortly.", e?.message)
    }

    func testANextAuthRefreshKeepsTheRoleFromAdminMe() async throws {
        let fresh = fakeJwt("a1", expiresInSec: 3600)
        installNextAuth(sessionAccess: fresh)
        var s = direct(fakeJwt("a1", expiresInSec: 60))
        s.refreshToken = nil; s.mode = "nextauth"; s.nextAuthCookie = "__Secure-next-auth.session-token=SESS-1"
        store.save(s)
        auth.updateProfile(name: "Moses Mwicigi", email: "moses@bethanyhouse.co.ke", role: "admin", isSuperuser: true)
        let got1 = try await auth.forceRefresh()
        XCTAssertEqual(fresh, got1)
        XCTAssertEqual("admin", store.current!.role, "the session payload has no role; /admin/me's stays")
        XCTAssertTrue(store.current!.isSuperuser)
    }

    func testUpdateProfileTakesRoleAndSuperuserWhenGiven() {
        var s = direct()
        s.role = "agent"; s.isSuperuser = false; s.mode = "nextauth"
        store.save(s)
        auth.updateProfile(name: "Moses M.", email: "m@b.co")
        XCTAssertEqual("agent", store.current!.role)
        auth.updateProfile(name: "Moses M.", email: "m@b.co", role: "admin", isSuperuser: true)
        XCTAssertEqual("admin", store.current!.role)
        XCTAssertTrue(store.current!.isSuperuser)
        XCTAssertEqual("Moses M.", store.current!.name)
    }

    func testJwtClaimsAreReadWithoutVerifying() {
        let t = fakeJwt("agent-9", expiresInSec: 100)
        XCTAssertEqual("agent-9", AuthRepository.jwtSub(t))
        XCTAssertNotEqual(0, AuthRepository.jwtExp(t))
        XCTAssertEqual(0, AuthRepository.jwtExp("not-a-jwt"))
        XCTAssertNil(AuthRepository.jwtSub("a.b.c"))
    }

    func testTheStoredSessionIsReadBackAtLaunch() {
        store.save(direct())
        let again = SessionStore(store: memory)
        XCTAssertEqual(store.current, again.current)
        XCTAssertEqual("moses@bethanyhouse.co.ke", again.lastEmail)
    }

    func testAnUnreadableStoreIsWipedNotACrash() {
        final class Broken: SecureStore {
            var wiped = false
            func string(_ key: String) throws -> String? { throw PlainError("keychain -25300") }
            func set(_ value: String?, for key: String) throws {}
            func removeAll() throws { wiped = true }
        }
        let b = Broken()
        var recorded: Error?
        SessionStore.onReadFailure = { recorded = $0 }
        defer { SessionStore.onReadFailure = nil }
        let s = SessionStore(store: b)
        XCTAssertNil(s.current)
        XCTAssertTrue(b.wiped)
        XCTAssertNotNil(recorded)
    }

    func testCookieJarRules() {
        var jar = CookieJar()
        jar.merge(setCookies: ["a=1; Path=/", "b=2; Max-Age=0", "c=3", "c=; Path=/", "=x"])
        XCTAssertEqual("a=1", jar.header)
        jar.merge(setCookies: ["a=9; Max-Age=-1"])
        XCTAssertTrue(jar.isEmpty)
        let parsed = CookieJar.parse(header: "x=1; next-auth.session-token=S; __Secure-next-auth.session-token.0=P0; junk")
        XCTAssertEqual("next-auth.session-token=S; __Secure-next-auth.session-token.0=P0", parsed.sessionCookies.header)
    }
}
