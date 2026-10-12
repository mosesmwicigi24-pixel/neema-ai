import Foundation

/// An ordered cookie jar — just enough of RFC 6265 for NextAuth.
public struct CookieJar: Equatable {
    public private(set) var order: [String] = []
    public private(set) var values: [String: String] = [:]

    public init() {}

    public subscript(key: String) -> String? {
        get { values[key] }
        set {
            if let v = newValue {
                if values[key] == nil { order.append(key) }
                values[key] = v
            } else {
                values[key] = nil
                order.removeAll { $0 == key }
            }
        }
    }

    public var isEmpty: Bool { order.isEmpty }
    public var entries: [(String, String)] { order.map { ($0, values[$0] ?? "") } }

    /// Apply Set-Cookie headers: a new value replaces, an empty value or Max-Age=0 deletes.
    public mutating func merge(setCookies: [String]) {
        for c in setCookies {
            let kv = c.split(separator: ";", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init)?.trimmingCharacters(in: .whitespaces) ?? ""
            guard let eq = kv.firstIndex(of: "=") else {
                let k = kv.trimmingCharacters(in: .whitespaces)
                if !k.isEmpty { self[k] = nil }
                continue
            }
            let k = String(kv[..<eq]).trimmingCharacters(in: .whitespaces)
            if k.isEmpty { continue }
            let v = String(kv[kv.index(after: eq)...])
            let attrs = (c.firstIndex(of: ";").map { String(c[c.index(after: $0)...]) } ?? "").lowercased()
            var expired = false
            if let r = attrs.range(of: #"max-age=\s*(-?\d+)"#, options: .regularExpression) {
                let num = attrs[r].split(separator: "=")[1].trimmingCharacters(in: .whitespaces)
                if let n = Int64(num), n <= 0 { expired = true }
            }
            if v.isEmpty || expired { self[k] = nil } else { self[k] = v }
        }
    }

    public static func parse(header: String) -> CookieJar {
        var jar = CookieJar()
        for part in header.split(separator: ";") {
            let t = part.trimmingCharacters(in: .whitespaces)
            guard let eq = t.firstIndex(of: "=") else { continue }
            jar[String(t[..<eq])] = String(t[t.index(after: eq)...])
        }
        return jar
    }

    public var header: String { entries.map { "\($0.0)=\($0.1)" }.joined(separator: "; ") }

    /// The session cookie under any of its names — `next-auth.session-token`,
    /// `__Secure-next-auth.session-token` on https — including the `.0`,
    /// `.1` chunks v4 splits a large token into.
    public var sessionCookies: CookieJar {
        var out = CookieJar()
        for (k, v) in entries where k.hasSuffix("next-auth.session-token") || k.range(of: #"next-auth\.session-token\.\d+$"#, options: .regularExpression) != nil {
            out[k] = v
        }
        return out
    }
}

/// Sign-in and silent refresh.
///
/// The web signs in through NextAuth, whose server calls FastAPI's
/// `POST /api/auth/login` (routers/auth.py `login`) internally. Which process
/// answers `/api/auth/…` on the public origin depends on the proxy: the repo's
/// nginx.conf sends every `/api/` path to FastAPI, while a deployment that
/// serves the web first hands `/api/auth/` to NextAuth. So the app tries, in
/// order:
///
///  1. `POST /api/agent-auth/login` — the same FastAPI auth router, mounted a
///     second time under a path NextAuth never claims (main.py);
///  2. `POST /api/auth/login` — FastAPI's original mount, for a server that
///     predates (1) behind a proxy that routes `/api/` to FastAPI;
///  3. NextAuth v4's credentials flow — `GET /api/auth/csrf` → `POST
///     /api/auth/callback/credentials` → `GET /api/auth/session`, whose session
///     carries `accessToken`. That route keeps no refresh token, no role and no
///     superuser flag: the role comes from `/admin/me` once signed in.
///
/// FastAPI answers `{access_token, refresh_token, token_type, agent_id, role,
/// is_superuser}`; a wrong password is 401 `{"detail":"Invalid credentials"}`,
/// a malformed body 422.
public final class AuthRepository: TokenProvider {
    /// FastAPI's auth router mounts, newest first (main.py).
    public static let DIRECT_PREFIXES = ["agent-auth", "auth"]
    static let UNAVAILABLE_COOLDOWN_MS: Int64 = 30_000

    // What sign-in says, for people.
    public static let INVALID = "Invalid email or password. Please try again."
    public static let UNAVAILABLE = "Sign-in is unavailable right now. Please try again shortly."
    public static let TOO_MANY = "Too many sign-in attempts. Please wait a minute and try again."
    public static let OFFLINE = "Can't reach Neema. Check your internet connection and try again."
    public static let TIMED_OUT = "Neema is taking too long to answer. Check your connection and try again."

    private let store: SessionStore
    private let base: String
    private let transport: HTTPTransport
    /// Pause between refresh attempts (attempt × this), as lib/auth.ts doRefresh().
    private let backoffMs: Int64
    private let sleep: Sleeper
    private let refreshLock = AsyncLock()
    private let state = NSLock()
    private var lastRejected: String?
    /// The access token whose refresh the server refused — asking again is pointless.
    private var refusedFor: String?
    /// Until when proactive refreshes are skipped after the auth server failed to answer.
    private var unavailableUntil: Int64 = 0

    public init(store: SessionStore, base: String = NeemaConfig.baseUrl, transport: HTTPTransport,
                backoffMs: Int64 = 500, sleep: @escaping Sleeper = realSleep) {
        self.store = store
        self.base = base
        self.transport = transport
        self.backoffMs = backoffMs
        self.sleep = sleep
    }

    /// Every failure is an `AuthError` whose message is meant for people:
    /// a wrong password, the server failing, too many attempts, no network,
    /// or a timeout each say which.
    public func login(email: String, password: String) async throws -> Session {
        do {
            for prefix in Self.DIRECT_PREFIXES {
                do {
                    let s = try await directLogin(prefix: prefix, email: email, password: password)
                    store.save(s)
                    return s
                } catch is RouteMissing {
                    // Wrong password is final; only "route not there" falls through.
                    continue
                }
            }
            let s = try await nextAuthLogin(email: email, password: password)
            store.save(s)
            return s
        } catch let e as RefreshUnavailable {
            if e.timedOut { throw AuthError(Self.TIMED_OUT) }
            if e.status == 0 { throw AuthError(Self.OFFLINE) }
            if e.status == 429 { throw AuthError(Self.TOO_MANY) }
            throw AuthError(Self.UNAVAILABLE)
        }
    }

    /// Run one auth call. No answer at all (offline, refused, dropped, timed
    /// out) becomes `RefreshUnavailable` with status 0, so callers can tell it
    /// from the server refusing.
    private func exec(_ req: HTTPRequest) async throws -> HTTPResponse {
        var r = req
        r.followRedirects = false
        r.timeout = NeemaConfig.callTimeout
        do { return try await transport.send(r) }
        catch let e as TransportError {
            switch e {
            case .timedOut: throw RefreshUnavailable(status: 0, timedOut: true, message: "timed out")
            case .network(let m): throw RefreshUnavailable(status: 0, timedOut: false, message: m.isEmpty ? "network error" : m)
            case .cancelled: if Task.isCancelled { throw CancellationError() } else { throw RefreshUnavailable(status: 0, timedOut: false, message: "cancelled") }
            }
        }
    }

    private func jsonPost(_ url: String, _ object: JSONValue) -> HTTPRequest {
        HTTPRequest(method: "POST", url: URL(string: url)!, headers: ["Content-Type": "application/json", "Accept": "application/json"], body: .json(object.text))
    }

    /// The server is up but can't serve this now: a 5xx, a 429, a 408. Never a verdict on the session.
    private func transient(_ code: Int) -> Bool { code >= 500 || code == 429 || code == 408 }

    public func logout() { store.clear() }

    // ── Direct FastAPI ──────────────────────────────────────────────────────

    /// This path isn't FastAPI's auth router (not deployed, or another app answers it).
    private struct RouteMissing: Error {}

    /// FastAPI's own "no such route" (`{"detail":"Not Found"}` 404 /
    /// `{"detail":"Method Not Allowed"}` 405) or any page that isn't JSON (a
    /// proxy error page, NextAuth's plain-text 400). A 404 whose detail is
    /// anything else — "Agent not found" from `refresh` — is a real answer.
    private func routeMissing(_ code: Int, _ text: String) -> Bool {
        if !text.drop(while: { $0.isWhitespace }).hasPrefix("{") { return true }
        if code != 404 && code != 405 { return false }
        let detail = JSONValue.parse(text)?["detail"]?.content
        return detail == nil || detail == "Not Found" || detail == "Method Not Allowed"
    }

    private func directLogin(prefix: String, email: String, password: String) async throws -> Session {
        let r = try await exec(jsonPost("\(base)/api/\(prefix)/login", ["email": .string(email), "password": .string(password)]))
        let text = r.text
        // Too many attempts, or a gateway with nothing behind it: final,
        // whatever page came with it — NextAuth would only relay the same.
        if r.status == 429 { throw AuthError(Self.TOO_MANY) }
        if (502...504).contains(r.status) { throw AuthError(Self.UNAVAILABLE) }
        if routeMissing(r.status, text) { throw RouteMissing() }
        if r.status == 401 || r.status == 422 { throw AuthError(Self.INVALID) }
        // A 5xx here is the API itself failing — NextAuth would only relay the same failure.
        if !r.isSuccessful { throw AuthError(Self.UNAVAILABLE) }
        guard let o = JSONValue.parse(text)?.objectValue else { throw RouteMissing() }
        if o["access_token"]?.content == nil { throw RouteMissing() }
        return try sessionFromTokens(o, email: email, mode: "direct", cookie: nil)
    }

    /// `POST …/refresh {refresh_token}` → a new pair. Nil when the server
    /// refused it (401 "Invalid refresh token", 404 "Agent not found") or no
    /// auth router answered. Throws `RefreshUnavailable` when it could not be
    /// asked: no answer, or a 5xx / 429 (even as a proxy's HTML page).
    private func directRefresh(_ refresh: String) async throws -> Session? {
        for prefix in Self.DIRECT_PREFIXES {
            let r = try await exec(jsonPost("\(base)/api/\(prefix)/refresh", ["refresh_token": .string(refresh)]))
            let text = r.text
            if transient(r.status) { throw RefreshUnavailable(status: r.status, timedOut: false, message: "auth server answered \(r.status)") }
            if routeMissing(r.status, text) { continue }
            if !r.isSuccessful { return nil }
            // A 2xx that isn't JSON (a captive portal's page) proves nothing about the session.
            guard let o = JSONValue.parse(text)?.objectValue else { throw RefreshUnavailable(status: 0, timedOut: false, message: "unreadable refresh answer") }
            if o["access_token"]?.content == nil { return nil }
            let cur = store.current
            var s = try sessionFromTokens(o, email: cur?.email ?? "", mode: "direct", cookie: nil)
            s.name = cur?.name ?? ""
            s.email = cur?.email ?? ""
            return s
        }
        // This session came from one of these routes, so neither answering as
        // FastAPI is a network in the way (a captive portal's page or
        // redirect), not a refused session.
        throw RefreshUnavailable(status: 0, timedOut: false, message: "no auth route answered")
    }

    private func sessionFromTokens(_ o: [String: JSONValue], email: String, mode: String, cookie: String?) throws -> Session {
        guard let access = o["access_token"]?.content else { throw AuthError(Self.UNAVAILABLE) }
        return Session(
            accessToken: access,
            refreshToken: o["refresh_token"]?.content,
            agentId: o["agent_id"]?.content ?? Self.jwtSub(access) ?? "",
            email: email,
            name: email,
            role: o["role"]?.content ?? "agent",
            isSuperuser: Self.bool(o["is_superuser"]) ?? false,
            mode: mode,
            nextAuthCookie: cookie
        )
    }

    // ── NextAuth bridge ─────────────────────────────────────────────────────

    private func nextAuthLogin(email: String, password: String) async throws -> Session {
        var jar = CookieJar()
        let csrfRes = try await exec(HTTPRequest(method: "GET", url: URL(string: "\(base)/api/auth/csrf")!))
        jar.merge(setCookies: csrfRes.setCookies)
        if csrfRes.status == 429 { throw AuthError(Self.TOO_MANY) }
        if !csrfRes.isSuccessful { throw AuthError(Self.UNAVAILABLE) }
        guard let csrf = JSONValue.parse(csrfRes.text)?["csrfToken"]?.content else { throw AuthError(Self.UNAVAILABLE) }
        // What next-auth/react signIn("credentials", {redirect:false}) posts.
        let form = HTTPBody.form([
            ("csrfToken", csrf), ("email", email), ("password", password),
            ("json", "true"), ("callbackUrl", "\(base)/dashboard"),
        ])
        let cb = try await exec(HTTPRequest(method: "POST", url: URL(string: "\(base)/api/auth/callback/credentials")!,
                                            headers: ["Cookie": jar.header], body: form))
        jar.merge(setCookies: cb.setCookies)
        // The web app itself failing (NextAuth's authorize() threw on a
        // FastAPI outage) is not a wrong password.
        if cb.status == 429 { throw AuthError(Self.TOO_MANY) }
        if cb.status >= 500 { throw AuthError(Self.UNAVAILABLE) }
        // v4 answers {url} (json=true) or a 302; a failed authorize() points
        // at …/error?error=CredentialsSignin, a stale csrf at …?csrf=true.
        let loc = (cb.header("Location") ?? "") + cb.text
        if loc.contains("error=") { throw AuthError(Self.INVALID) }
        if loc.contains("csrf=true") { throw AuthError(Self.UNAVAILABLE) }
        let session = jar.sessionCookies
        if session.isEmpty { throw AuthError(Self.INVALID) }
        // Signed in, but the session endpoint is failing: say so, not "wrong password".
        do {
            guard let s = try await nextAuthSession(cookie: session.header, email: email) else { throw AuthError(Self.INVALID) }
            return s
        } catch let e as RefreshUnavailable {
            if e.status == 0 { throw e }
            throw AuthError(e.status == 429 ? Self.TOO_MANY : Self.UNAVAILABLE)
        }
    }

    /// GET /api/auth/session with the session cookie. v4 answers `{}` when the
    /// cookie is gone, else `{user:{name?,email,image?,id}, expires,
    /// accessToken}` — and re-issues the session cookie (a new expiry, maybe
    /// split into `.0`/`.1` chunks), which is merged back in.
    private func nextAuthSession(cookie: String, email: String) async throws -> Session? {
        let r = try await exec(HTTPRequest(method: "GET", url: URL(string: "\(base)/api/auth/session")!, headers: ["Cookie": cookie]))
        if transient(r.status) { throw RefreshUnavailable(status: r.status, timedOut: false, message: "session endpoint answered \(r.status)") }
        if !r.isSuccessful { return nil }
        var jar = CookieJar.parse(header: cookie)
        jar.merge(setCookies: r.setCookies)
        let fresh = jar.sessionCookies.header
        let newCookie = fresh.isEmpty ? cookie : fresh
        let text = r.text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let o = JSONValue.parse(text.isEmpty ? "{}" : text)?.objectValue else { return nil }
        if o["error"]?.content != nil { return nil }
        guard let access = o["accessToken"]?.content else { return nil }
        let user = o["user"]?.objectValue
        return Session(
            accessToken: access,
            refreshToken: o["refreshToken"]?.content,
            agentId: user?["id"]?.content ?? Self.jwtSub(access) ?? "",
            email: user?["email"]?.content ?? email,
            name: user?["name"]?.content ?? email,
            role: o["role"]?.content ?? user?["role"]?.content ?? "agent",
            isSuperuser: Self.bool(user?["isSuperuser"]) ?? false,
            mode: "nextauth",
            nextAuthCookie: newCookie
        )
    }

    // ── TokenProvider ───────────────────────────────────────────────────────

    public func validAccessToken() async throws -> String? {
        guard let s = store.current else { return nil }
        let left = Self.jwtExp(s.accessToken) - AppClock.now() / 1000
        // Same 5-minute buffer the web's jwt() callback uses.
        if left > 300 { return s.accessToken }
        // The auth server just failed to answer: while the token still works,
        // don't make every request wait out another round of attempts.
        let cooldown: Int64 = state.sync { unavailableUntil }
        if left > 0 && AppClock.now() < cooldown { return s.accessToken }
        do {
            if let fresh = try await forceRefresh() { return fresh }
            return left > 0 ? s.accessToken : nil
        } catch let e as RefreshUnavailable {
            // Still unexpired: use it; the server is the judge. Expired: the
            // request would only bounce, so it fails as the outage it is.
            if left > 0 { return s.accessToken }
            throw e
        }
    }

    /// One refresh for everyone: callers queue on a lock, and whoever comes
    /// second finds the new token already stored. Up to three attempts
    /// (lib/auth.ts doRefresh) while the auth server can't answer; a refusal
    /// is final at once, and so is a timeout (three of those would hold every
    /// request for 90 s). A refusal is remembered for that token, so a burst of
    /// 401s after it asks the server once, not once each.
    public func forceRefresh() async throws -> String? {
        try await refreshLock.withLock {
            guard let s = store.current else { return nil }
            let (rejected, refused): (String?, String?) = state.sync { (lastRejected, refusedFor) }
            // Another caller may have refreshed while we waited for the lock.
            if Self.jwtExp(s.accessToken) - AppClock.now() / 1000 > 300 && s.accessToken != rejected { return s.accessToken }
            if s.accessToken == refused { return nil }
            var fresh: Session? = nil
            var outage: RefreshUnavailable? = nil
            for attempt in 1...3 {
                outage = nil
                do { fresh = try await refreshOnce(s) }
                catch let e as RefreshUnavailable { outage = e; fresh = nil }
                // NextAuth may hand back the very token the API just refused
                // (its session callback doesn't always refresh): that is no rescue.
                if let f = fresh, f.accessToken == s.accessToken,
                   s.accessToken == rejected || Self.jwtExp(s.accessToken) <= AppClock.now() / 1000 {
                    fresh = nil
                }
                let retry = fresh == nil && outage != nil && !(outage?.timedOut ?? false) && attempt < 3
                if !retry { break }
                if backoffMs > 0 { try await sleep(Int64(attempt) * backoffMs) }
            }
            guard let f = fresh else {
                if let o = outage {
                    state.sync { unavailableUntil = AppClock.now() + Self.UNAVAILABLE_COOLDOWN_MS }
                    throw o
                }
                state.sync { lastRejected = s.accessToken; refusedFor = s.accessToken }
                return nil
            }
            state.sync { unavailableUntil = 0 }
            var merged = f
            merged.name = s.name.trimmingCharacters(in: .whitespaces).isEmpty ? f.name : s.name
            merged.email = s.email.trimmingCharacters(in: .whitespaces).isEmpty ? f.email : s.email
            merged.nextAuthCookie = f.nextAuthCookie ?? s.nextAuthCookie
            merged.refreshToken = f.refreshToken ?? s.refreshToken
            // NextAuth's session carries no role: keep what /admin/me told us.
            merged.role = f.mode == "nextauth" ? s.role : f.role
            merged.isSuperuser = f.mode == "nextauth" ? s.isSuperuser : f.isSuperuser
            store.save(merged)
            return merged.accessToken
        }
    }

    /// One try through every refresh path this session has: FastAPI's
    /// refresh token, then NextAuth's session cookie. Nil when refused;
    /// `RefreshUnavailable` when none could give an answer either way.
    private func refreshOnce(_ s: Session) async throws -> Session? {
        var outage: RefreshUnavailable? = nil
        if let rt = s.refreshToken {
            do { if let r = try await directRefresh(rt) { return r } }
            catch let e as RefreshUnavailable { outage = outage ?? e }
        }
        if let c = s.nextAuthCookie {
            do { if let r = try await nextAuthSession(cookie: c, email: s.email) { return r } }
            catch let e as RefreshUnavailable { outage = outage ?? e }
        }
        if let o = outage { throw o }
        return nil
    }

    /// Called after a 401 so forceRefresh() doesn't trust an unexpired-but-revoked token.
    public func onRejected(_ token: String?) { state.sync { lastRejected = token } }

    /// The signed-in agent as `/admin/me` describes them. Name and email always;
    /// role and superuser too when given — a NextAuth sign-in carries neither,
    /// and an admin must not be shown an agent's app until the first refresh.
    public func updateProfile(name: String, email: String, role: String? = nil, isSuperuser: Bool? = nil) {
        guard let it = store.current else { return }
        var next = it
        next.name = name
        next.email = email
        if let r = role, !r.trimmingCharacters(in: .whitespaces).isEmpty { next.role = r }
        if let su = isSuperuser { next.isSuperuser = su }
        if next != it { store.save(next) }
    }

    // ── JWT (read, never verified) ──────────────────────────────────────────

    static func bool(_ v: JSONValue?) -> Bool? {
        guard let v = v else { return nil }
        switch v {
        case .bool(let b): return b
        case .string(let s): return s == "true" ? true : (s == "false" ? false : nil)
        default: return nil
        }
    }

    static func claims(_ jwt: String) -> [String: JSONValue]? {
        let parts = jwt.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count > 1 else { return nil }
        var b64 = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while b64.hasSuffix("=") { b64.removeLast() }
        while b64.count % 4 != 0 { b64 += "=" }
        guard let data = Data(base64Encoded: b64), let text = String(data: data, encoding: .utf8) else { return nil }
        return JSONValue.parse(text)?.objectValue
    }

    public static func jwtExp(_ jwt: String) -> Int64 {
        guard let e = claims(jwt)?["exp"] else { return 0 }
        if case .number(let d) = e { return Int64(d) }
        return Int64(e.content ?? "") ?? 0
    }

    public static func jwtSub(_ jwt: String) -> String? { claims(jwt)?["sub"]?.content }
}
