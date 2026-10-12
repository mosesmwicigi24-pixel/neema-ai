import Foundation
@testable import NeemaCore

/// A fake Neema API for tests: answers every request in-process from
/// registered routes, and records what was called so tests can assert on it.
/// Unmatched routes answer FastAPI's own 404 `{"detail":"Not Found"}` so a
/// missing fixture shows up as an error state rather than hanging.
/// The Swift twin of Android's `FakeNeema`.
final class FakeNeema: HTTPTransport, RequestGate, @unchecked Sendable {
    struct Call {
        let method: String
        let path: String
        let query: String?
        let body: String?
        let headers: [String: String]

        func header(_ name: String) -> String? { headers.first { $0.key.lowercased() == name.lowercased() }?.value }

        /// The decoded query string, e.g. `status=pending&wa_id=254…` → {status=pending, wa_id=254…}.
        var params: [String: String] {
            var out: [String: String] = [:]
            for pair in (query ?? "").split(separator: "&") where !pair.isEmpty {
                let kv = pair.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
                let k = String(kv[0]).removingPercentEncoding ?? String(kv[0])
                let v = kv.count > 1 ? (String(kv[1]).replacingOccurrences(of: "+", with: " ").removingPercentEncoding ?? String(kv[1])) : ""
                out[k] = v
            }
            return out
        }
    }

    /// A full answer: status, body and headers (Set-Cookie, Location…).
    struct Reply {
        var code: Int = 200
        var body: String = ""
        var headers: [String: String] = [:]
        var setCookies: [String] = []
    }

    private struct Route {
        let method: String
        let pattern: NSRegularExpression
        let handler: (HTTPRequest, String?) throws -> Reply
        func matches(_ m: String, _ p: String) -> Bool {
            method == m && pattern.firstMatch(in: p, range: NSRange(p.startIndex..., in: p)) != nil
        }
    }

    private enum FaultKind { case drop, timeout }
    private final class Fault {
        let method: String; let pattern: NSRegularExpression; var left: Int; let kind: FaultKind
        init(_ m: String, _ p: NSRegularExpression, _ left: Int, _ kind: FaultKind) { method = m; pattern = p; self.left = left; self.kind = kind }
        func matches(_ m: String, _ p: String) -> Bool {
            guard method == "*" || method == m, pattern.firstMatch(in: p, range: NSRange(p.startIndex..., in: p)) != nil, left > 0 else { return false }
            left -= 1
            return true
        }
    }
    private final class Slow {
        let method: String; let pattern: NSRegularExpression; let ms: Int64; var left: Int
        init(_ m: String, _ p: NSRegularExpression, _ ms: Int64, _ left: Int) { method = m; pattern = p; self.ms = ms; self.left = left }
        func matches(_ m: String, _ p: String) -> Bool {
            guard method == "*" || method == m, pattern.firstMatch(in: p, range: NSRange(p.startIndex..., in: p)) != nil, left > 0 else { return false }
            left -= 1
            return true
        }
    }

    /// Hold every matching request until the test decides: `release` lets
    /// them (and later ones) through to their routes, `drop` fails them.
    final class Hold: @unchecked Sendable {
        fileprivate let method: String
        fileprivate let pattern: NSRegularExpression
        private let lock = NSLock()
        private var verdict: TransportError?? = nil
        private var waiters: [(UUID, CheckedContinuation<Void, Error>)] = []
        private var cancelledEarly: Set<UUID> = []
        private(set) var caught = 0
        var waiting: Int { lock.sync { waiters.count } }

        fileprivate init(_ m: String, _ p: NSRegularExpression) { method = m; pattern = p }

        fileprivate func matches(_ m: String, _ p: String) -> Bool {
            lock.sync { verdict == nil } && (method == "*" || method == m) && pattern.firstMatch(in: p, range: NSRange(p.startIndex..., in: p)) != nil
        }

        fileprivate func await_() async throws {
            lock.sync { caught += 1 }
            let id = UUID()
            try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
                    lock.sync {
                        if cancelledEarly.remove(id) != nil { c.resume(throwing: CancellationError()); return }
                        if let v = verdict {
                            if let e = v { c.resume(throwing: e) } else { c.resume() }
                        } else {
                            waiters.append((id, c))
                        }
                    }
                }
            } onCancel: {
                let c: CheckedContinuation<Void, Error>? = lock.sync {
                    if let i = waiters.firstIndex(where: { $0.0 == id }) { return waiters.remove(at: i).1 }
                    cancelledEarly.insert(id)
                    return nil
                }
                c?.resume(throwing: CancellationError())
            }
        }

        private func settle(_ e: TransportError?) {
            let ws: [CheckedContinuation<Void, Error>] = lock.sync {
                verdict = .some(e)
                let w = waiters.map { $0.1 }
                waiters = []
                return w
            }
            for w in ws { if let e = e { w.resume(throwing: e) } else { w.resume() } }
        }

        /// Let held (and later) requests through to their routes.
        func release() { settle(nil) }
        /// Fail held (and later) requests with a dropped connection.
        func drop() { settle(.network("Connection reset")) }
    }

    private let lock = NSLock()
    private var routes: [Route] = []
    private var faults: [Fault] = []
    private var slows: [Slow] = []
    private var holds: [Hold] = []
    private(set) var calls: [Call] = []
    /// No network at all: every request fails as a phone with no signal does.
    var offline = false
    /// The clock that drives `delay` (a test's virtual clock).
    var sleep: Sleeper = realSleep

    private func regex(_ path: String) -> NSRegularExpression { try! NSRegularExpression(pattern: "^\(path)$") }

    /// Register a route; later registrations win. `path` is a regex over the path after `/api`.
    func on(_ method: String, _ path: String, code: Int = 200, body: String = "{}") {
        on(method, path) { _, _ in (code, body) }
    }

    func on(_ method: String, _ path: String, _ handler: @escaping (HTTPRequest, String?) throws -> (Int, String)) {
        lock.sync {
            // A fresh answer for exactly this route heals any fault injected on it.
            faults.removeAll { $0.method == method && $0.pattern.pattern == "^\(path)$" }
            routes.insert(Route(method: method, pattern: regex(path), handler: { r, b in
                let (c, t) = try handler(r, b)
                return Reply(code: c, body: t)
            }), at: 0)
        }
    }

    /// Register a route that also answers with headers (cookies, redirects).
    func reply(_ method: String, _ path: String, _ handler: @escaping (HTTPRequest, String?) throws -> Reply) {
        lock.sync { routes.insert(Route(method: method, pattern: regex(path), handler: handler), at: 0) }
    }

    /// Every recorded call to `method` `path` (exact path).
    func callsTo(_ method: String, _ path: String) -> [Call] { lock.sync { calls.filter { $0.method == method && $0.path == path } } }
    func called(_ method: String, _ pathPrefix: String) -> Bool { lock.sync { calls.contains { $0.method == method && $0.path.hasPrefix(pathPrefix) } } }

    // ── Network faults ──────────────────────────────────────────────────────

    /// The connection drops before an answer: NeemaHTTP reports status 0.
    func drop(_ method: String, _ path: String, times: Int = Int.max) { lock.sync { faults.insert(Fault(method, regex(path), times, .drop), at: 0) } }
    /// The request times out — NeemaHTTP's "timed out after 30s".
    func timeout(_ method: String, _ path: String, times: Int = Int.max) { lock.sync { faults.insert(Fault(method, regex(path), times, .timeout), at: 0) } }
    /// Answer only after `ms` (on the injected clock): a slow server.
    func delay(_ method: String, _ path: String, ms: Int64, times: Int = Int.max) { lock.sync { slows.insert(Slow(method, regex(path), ms, times), at: 0) } }
    func hang(_ method: String, _ path: String) -> Hold { let h = Hold(method, regex(path)); lock.sync { holds.insert(h, at: 0) }; return h }
    /// Remove every fault, delay and hold (held requests are released).
    func heal() {
        let hs: [Hold] = lock.sync {
            offline = false
            faults.removeAll(); slows.removeAll()
            let h = holds; holds.removeAll(); return h
        }
        hs.forEach { $0.release() }
    }

    func beforeRequest(method: String, path: String) async throws {
        if let s = lock.sync({ slows.first { $0.matches(method, path) } }) { try await sleep(s.ms) }
        if let h = lock.sync({ holds.first { $0.matches(method, path) } }) { try await h.await_() }
    }

    private func bodyText(_ body: HTTPBody?) throws -> String? {
        switch body {
        case .none: return nil
        case .data(let d, _): return String(decoding: d, as: UTF8.self)
        case .file(let u, _): return String(decoding: try Data(contentsOf: u), as: UTF8.self)
        case .multipart(let m): return String(decoding: try m.encoded(), as: UTF8.self)
        }
    }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        let path = request.path
        let body = try bodyText(request.body)
        let call = Call(method: request.method, path: path, query: request.url.query, body: body, headers: request.headers)
        lock.sync { calls.append(call) }
        if lock.sync({ offline }) { throw TransportError.network("Unable to resolve host \"\(request.url.host ?? "")\": No address associated with hostname") }
        if let f = lock.sync({ faults.first { $0.matches(request.method, path) } }) {
            switch f.kind {
            case .drop: throw TransportError.network("Connection reset")
            case .timeout: throw TransportError.timedOut
            }
        }
        guard let route = lock.sync({ routes.first { $0.matches(request.method, path) } }) else {
            return HTTPResponse(status: 404, headers: ["X-Fake": "no fixture for \(request.method) \(path)"], text: #"{"detail":"Not Found"}"#)
        }
        let reply = try route.handler(request, body)
        return HTTPResponse(status: reply.code, headers: reply.headers, setCookies: reply.setCookies, text: reply.body)
    }
}
