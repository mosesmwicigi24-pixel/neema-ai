import Foundation

/// Implemented by the auth layer; the HTTP client never touches storage directly.
public protocol TokenProvider: AnyObject {
    /// A token good for at least a few minutes, refreshing first if needed.
    func validAccessToken() async throws -> String?
    /// Refresh now regardless of expiry; nil when the server refused (the
    /// session is gone). Throws `RefreshUnavailable` when the auth server could
    /// not be asked — the session is not known to be gone. `validAccessToken`
    /// may throw it too, for a token already expired.
    func forceRefresh() async throws -> String?
    /// The server refused this token — never hand it out again as "still valid".
    func onRejected(_ token: String?)
}

/// Tests only: a hook `NeemaHTTP` awaits before each request, in the caller's
/// task. The fake backend uses it to delay a request or hold it until released.
public protocol RequestGate: AnyObject {
    /// `path` is the part after `/api`, without the query string.
    func beforeRequest(method: String, path: String) async throws
}

/// Where the app talks to; the Android twin is `BuildConfig.NEEMA_BASE_URL`.
public enum NeemaConfig {
    public static let baseUrl = "https://neema.bethanyhouse.co.ke"
    public static let callTimeout: TimeInterval = 30
    /// Media uploads (videos up to 150 MB are transcoded server-side) and whole AI turns.
    public static let uploadTimeout: TimeInterval = 600
}

/// The iOS twin of `lib/api.ts`'s `req()` and Android's `NeemaHttp`: JSON over
/// HTTPS against `${BASE}/api`, a bearer token on every call, a 30-second
/// ceiling so a dropped connection can never become a spinner that never
/// dies, and a single session-expired signal when the server stops accepting us.
///
/// Token handling lives in `TokenProvider` (the auth layer): it refreshes
/// proactively before expiry and once more on a 401 before giving up. Only
/// a refresh the server actually refused expires the session; one it could
/// not answer (offline, 5xx) fails this request and keeps the session.
public final class NeemaHTTP {
    public let baseUrl: String
    public var apiBase: String { baseUrl + "/api" }
    private let tokens: TokenProvider
    private let transport: HTTPTransport
    /// Tests only.
    public var gate: RequestGate?

    /// Fires when a request came back 401 and a refresh could not rescue it.
    public let sessionExpired = Signal<Void>(buffer: 1)
    /// Fires ("METHOD /path") when the server refused a signed-in request with
    /// 403: the agent's role or permissions may have changed since the app last
    /// read them, so the dashboard rereads /admin/me and the team list.
    /// GETs of those two are left out, so a refusal there can't loop.
    public let forbidden = Signal<String>(buffer: 8)

    public init(baseUrl: String = NeemaConfig.baseUrl, tokens: TokenProvider, transport: HTTPTransport) {
        self.baseUrl = baseUrl
        self.tokens = tokens
        self.transport = transport
    }

    /// The answer's text. Non-2xx throws `ApiError`; no answer is status 0.
    public func raw(_ method: String, _ path: String, body: HTTPBody? = nil, upload: Bool = false) async throws -> String {
        if let gate = gate {
            do { try await gate.beforeRequest(method: method, path: gatePath(path)) }
            catch let e as TransportError {
                if Task.isCancelled { throw CancellationError() }
                throw networkError(e, method, path, upload)
            }
        }
        let urlText = path.hasPrefix("http") ? path : apiBase + path
        guard let url = URL(string: urlText) else { throw ApiError(status: 0, method: method, path: path, body: "bad url") }
        let timeout = upload ? NeemaConfig.uploadTimeout : NeemaConfig.callTimeout

        func build(_ token: String?) -> HTTPRequest {
            var req = HTTPRequest(method: method, url: url, timeout: timeout)
            req.headers["Accept"] = "application/json"
            if let t = token { req.headers["Authorization"] = "Bearer " + t }
            if let b = body { req.body = b }
            else if method != "GET" && method != "DELETE" { req.body = .json("") }
            return req
        }

        let used = try await authStep(method, path) { try await self.tokens.validAccessToken() }
        var res = try await execute(build(used), method, path, upload)
        // FastAPI 0.115's HTTPBearer answers a request with NO token 403
        // "Not authenticated", not 401. That only happens once the token ran
        // out and could not be refreshed: the same dead session.
        if res.status == 401 || (res.status == 403 && used == nil) {
            tokens.onRejected(used)
            // One rescue attempt: the token may have expired between the
            // proactive check and the server's clock. Requests rejected
            // together share that one refresh (the auth layer serialises
            // it). A refresh the auth server could not answer is an
            // outage, not a signed-out agent: it fails this request only.
            let fresh = try await authStep(method, path) { try await self.tokens.forceRefresh() }
            if let f = fresh { res = try await execute(build(f), method, path, upload) }
            if fresh == nil || res.status == 401 {
                sessionExpired.emit()
                throw ApiError(status: 401, method: method, path: path, body: "Session expired")
            }
        }
        if !res.isSuccessful {
            // An error page can be anything (a proxy's multi-megabyte HTML dump): only its head is worth keeping.
            let text = String(decoding: res.body.prefix(MAX_ERROR_BODY), as: UTF8.self)
            if res.status == 403 && !isIdentityRead(method, path) { forbidden.emit("\(method) \(gatePath(path))") }
            throw ApiError(status: res.status, method: method, path: path, body: text,
                           retryAfterSeconds: retryAfter(res), reasonHeader: res.header("X-Neema-Reason"))
        }
        return res.text
    }

    private func isIdentityRead(_ method: String, _ path: String) -> Bool {
        guard method == "GET" else { return false }
        var p = gatePath(path)
        while p.hasSuffix("/") { p.removeLast() }
        return p == "/admin/me" || p == "/admin/agents"
    }

    func gatePath(_ path: String) -> String {
        var p = path
        if p.hasPrefix("http") {
            if let r = p.range(of: "://") { p = String(p[r.upperBound...]) }
            if let slash = p.firstIndex(of: "/") { p = String(p[slash...]) } else { p = "/" }
            if p.hasPrefix("/api") { p = String(p.dropFirst(4)) }
        }
        if let q = p.firstIndex(of: "?") { p = String(p[..<q]) }
        return p
    }

    private func authStep<T>(_ method: String, _ path: String, _ step: () async throws -> T) async throws -> T {
        do { return try await step() }
        catch let e as RefreshUnavailable {
            throw ApiError(status: e.status, method: method, path: path, body: e.timedOut ? "timed out after 30s" : e.message, cause: e)
        }
    }

    private func execute(_ req: HTTPRequest, _ method: String, _ path: String, _ upload: Bool) async throws -> HTTPResponse {
        do { return try await transport.send(req) }
        catch let e as TransportError {
            // Cancelled by its task (the screen that asked went away, a newer
            // search replaced this one): ends as cancelled, never as a
            // "network error" a screen might show. A ceiling that passed is a
            // slow server, which the screen must hear about.
            if case .cancelled = e, Task.isCancelled { throw CancellationError() }
            throw networkError(e, method, path, upload)
        }
    }

    private func networkError(_ e: TransportError, _ method: String, _ path: String, _ upload: Bool) -> ApiError {
        switch e {
        case .timedOut: return ApiError(status: 0, method: method, path: path, body: upload ? "timed out after 10 min" : "timed out after 30s", cause: e)
        case .network(let m): return ApiError(status: 0, method: method, path: path, body: m.isEmpty ? "network error" : m, cause: e)
        case .cancelled: return ApiError(status: 0, method: method, path: path, body: "cancelled", cause: e)
        }
    }

    /// `Retry-After: <seconds>` (the HTTP-date form is rare enough to ignore).
    private func retryAfter(_ r: HTTPResponse) -> Int64? {
        guard let v = r.header("Retry-After")?.trimmingCharacters(in: .whitespaces), let n = Int64(v) else { return nil }
        return min(max(n, 0), 3600)
    }

    // ── Typed helpers ───────────────────────────────────────────────────────

    public func get<T: Decodable>(_ path: String) async throws -> T { try decode(try await raw("GET", path)) }
    public func delete<T: Decodable>(_ path: String) async throws -> T { try decode(try await raw("DELETE", path)) }
    public func post<B: Encodable, T: Decodable>(_ path: String, _ body: B) async throws -> T {
        try decode(try await raw("POST", path, body: try encode(body)))
    }
    public func patch<B: Encodable, T: Decodable>(_ path: String, _ body: B) async throws -> T {
        try decode(try await raw("PATCH", path, body: try encode(body)))
    }
    public func put<B: Encodable, T: Decodable>(_ path: String, _ body: B) async throws -> T {
        try decode(try await raw("PUT", path, body: try encode(body)))
    }
    public func multipart<T: Decodable>(_ path: String, _ parts: MultipartBody) async throws -> T {
        try decode(try await raw("POST", path, body: .multipart(parts), upload: true))
    }

    public func encode<B: Encodable>(_ body: B) throws -> HTTPBody {
        .json(try NeemaJSON.encoder.encode(body))
    }

    /// Reads an answer as `T`. A 2xx that isn't what was asked for (a captive
    /// portal's page, a cut-off answer, a shape the app doesn't know) is a
    /// readable failure, not a crash. An empty 2xx (a 204, or a handler that
    /// returned None) is a success: read it as nil, else as an empty object /
    /// list, never as a failure.
    public func decode<T: Decodable>(_ text: String) throws -> T {
        if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            do { return try NeemaJSON.decode(T.self, from: text) }
            catch {
                throw ApiError(status: 200, method: "", path: "(response)", body: String(text.prefix(MAX_ERROR_BODY)), malformed: true, cause: error)
            }
        }
        if let v = try? NeemaJSON.decode(T.self, from: "null") { return v }
        if let v = try? NeemaJSON.decode(T.self, from: "{}") { return v }
        return try NeemaJSON.decode(T.self, from: "[]")
    }
}
