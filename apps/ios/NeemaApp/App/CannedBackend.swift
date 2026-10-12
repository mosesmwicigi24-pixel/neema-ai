import Foundation
import NeemaCore

/// A backend made of recorded answers: the screenshot gallery's fixture set
/// (`NeemaAppTests/Gallery/fixtures.json`, written by NeemaCore's
/// `GalleryFixtureExportTests`), served by method and path — the exact query
/// first, else the same path. Sign-in is answered as FastAPI's auth router
/// would for the fixtures' agent (any email; the password is `neema`). Anything
/// else gets FastAPI's own 404, so a missing fixture shows as an error state
/// rather than a hang.
///
/// Two users: the gallery (`ScreenGalleryTests`, in-process) and the UI tests
/// (`NeemaAppUITests`), which launch the app with `-neema-canned` and drive it
/// as a person would — `CannedBackend.container()` builds the app on this
/// transport, an in-memory session store and no sockets.
final class CannedTransport: HTTPTransport, @unchecked Sendable {
    struct Canned {
        let method: String
        let path: String
        let query: String
        let status: Int
        let body: String
    }

    struct Agent {
        let id: String
        let email: String
        let name: String
        let role: String
        let isSuperuser: Bool
    }

    /// The password the canned sign-in accepts.
    static let PASSWORD = "neema"

    let agent: Agent
    let pinnedMillis: Int64
    private let canned: [Canned]
    private let lock = NSLock()
    private var last = Date.distantPast
    private(set) var unmatched: [String] = []

    init(json: Data) throws {
        guard let doc = JSONValue.parse(String(decoding: json, as: UTF8.self))?.objectValue,
              let a = doc["agent"]?.objectValue, let list = doc["responses"]?.arrayValue else {
            throw NSError(domain: "Gallery", code: 1, userInfo: [NSLocalizedDescriptionKey: "fixtures.json is not the exporter's shape"])
        }
        agent = Agent(id: a["id"]?.stringValue ?? "", email: a["email"]?.stringValue ?? "", name: a["name"]?.stringValue ?? "",
                      role: a["role"]?.stringValue ?? "agent", isSuperuser: a["isSuperuser"]?.boolValue ?? false)
        pinnedMillis = Int64(doc["pinnedMillis"]?.doubleValue ?? 0)
        canned = list.compactMap { v in
            guard let o = v.objectValue, let m = o["method"]?.stringValue, let p = o["path"]?.stringValue else { return nil }
            return Canned(method: m, path: p, query: o["query"]?.stringValue ?? "", status: Int(o["status"]?.doubleValue ?? 200), body: o["body"]?.stringValue ?? "")
        }
    }

    /// The fixtures bundled with a test target.
    static func bundled(for cls: AnyClass) throws -> CannedTransport {
        guard let url = Bundle(for: cls).url(forResource: "fixtures", withExtension: "json") else {
            throw NSError(domain: "Gallery", code: 2, userInfo: [NSLocalizedDescriptionKey: "fixtures.json is not in the test bundle"])
        }
        return try CannedTransport(json: try Data(contentsOf: url))
    }

    /// The fixtures bundled with the app (project.yml copies the same file in).
    static func bundledWithApp() throws -> CannedTransport {
        guard let url = Bundle.main.url(forResource: "fixtures", withExtension: "json") else {
            throw NSError(domain: "Gallery", code: 3, userInfo: [NSLocalizedDescriptionKey: "fixtures.json is not in the app bundle"])
        }
        return try CannedTransport(json: try Data(contentsOf: url))
    }

    /// An unsigned JWT the core reads `sub` and `exp` from — a year from now.
    static func token(for agentId: String) -> String {
        func b64(_ s: String) -> String {
            var out = Data(s.utf8).base64EncodedString().replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            while out.hasSuffix("=") { out.removeLast() }
            return out
        }
        let exp = AppClock.now() / 1000 + 365 * 24 * 3600
        return b64(#"{"alg":"HS256","typ":"JWT"}"#) + "." + b64(#"{"sub":"\#(agentId)","exp":\#(exp)}"#) + ".canned"
    }

    /// When the app last asked for anything: the gallery waits for a quiet moment before it renders.
    var lastRequest: Date { lock.sync { last } }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        lock.sync { last = Date() }
        var path = request.url.path
        if path.hasPrefix("/api/") { path = String(path.dropFirst(4)) }
        let query = request.url.query ?? ""
        if request.method == "POST", let auth = authAnswer(path: path, body: request.body) { return auth }
        let hits = canned.filter { $0.method == request.method && $0.path == path }
        guard let hit = hits.first(where: { $0.query == query }) ?? hits.first else {
            lock.sync { unmatched.append("\(request.method) \(path)\(query.isEmpty ? "" : "?\(query)")") }
            return HTTPResponse(status: 404, headers: ["x-gallery": "no fixture"], body: Data(#"{"detail":"Not Found"}"#.utf8))
        }
        return HTTPResponse(status: hit.status, headers: ["content-type": "application/json"], body: Data(hit.body.utf8))
    }

    /// FastAPI's auth router for the fixtures' agent: `/agent-auth/login` takes
    /// any email with the canned password (401 otherwise, as the server
    /// answers a wrong password); `/agent-auth/refresh` always mints a new pair.
    private func authAnswer(path: String, body: HTTPBody?) -> HTTPResponse? {
        guard path == "/agent-auth/login" || path == "/agent-auth/refresh" else { return nil }
        if path == "/agent-auth/login" {
            var text = ""
            if case .data(let d, _)? = body { text = String(decoding: d, as: UTF8.self) }
            let password = JSONValue.parse(text)?["password"]?.stringValue ?? ""
            if password != Self.PASSWORD {
                return HTTPResponse(status: 401, headers: ["content-type": "application/json"], body: Data(#"{"detail":"Invalid credentials"}"#.utf8))
            }
        }
        let pair = JSONValue.object([
            "access_token": .string(Self.token(for: agent.id)), "refresh_token": .string("canned-refresh"), "token_type": .string("bearer"),
            "agent_id": .string(agent.id), "role": .string(agent.role), "is_superuser": .bool(agent.isSuperuser),
        ])
        return HTTPResponse(status: 200, headers: ["content-type": "application/json"], body: (try? NeemaJSON.encoder.encode(pair)) ?? Data())
    }
}

/// No live feed: every socket the app opens is dead on arrival (the canned
/// backend has no server to push from).
final class DeadSockets: WebSocketFactory {
    final class Dead: WebSocketConnection {
        let url: URL
        init(_ u: URL) { url = u }
        func send(text: String) {}
        func close(code: Int, reason: String?) {}
        func cancel() {}
    }
    func newWebSocket(url: URL, events: WebSocketEvents) -> WebSocketConnection { Dead(url) }
}

enum CannedBackend {
    /// The launch argument the UI tests pass.
    static let ARGUMENT = "-neema-canned"

    static var requested: Bool { ProcessInfo.processInfo.arguments.contains(ARGUMENT) }

    /// The app on the canned backend, signed out, with nothing remembered
    /// between launches (an in-memory session store; the one-time notification
    /// ask already made, so no system prompt sits over the UI tests).
    @MainActor
    static func container() -> AppContainer? {
        guard requested, let transport = try? CannedTransport.bundledWithApp() else { return nil }
        return container(transport: transport)
    }

    /// The app on a recorded backend, in its own wiped preferences suite and
    /// snapshot folder: nothing of the real app's (or of an earlier run's: the
    /// gallery once left a thread open that the UI tests then restored)
    /// reaches it, and it leaves nothing behind.
    @MainActor
    static func container(transport: HTTPTransport) -> AppContainer {
        let suite = "ke.co.bethanyhouse.neema.canned"
        let defaults = UserDefaults(suiteName: suite) ?? .standard
        defaults.removePersistentDomain(forName: suite)
        defaults.set(true, forKey: AppModel.ASKED_NOTIFICATIONS)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("neema-canned-snapshots", isDirectory: true)
        try? FileManager.default.removeItem(at: dir)
        return AppContainer(baseUrl: "https://neema.test", store: MemoryStore(), transport: transport, socketFactory: DeadSockets(), watchNetwork: false,
                            defaults: defaults, snapshots: SnapshotCache(directory: dir))
    }
}
