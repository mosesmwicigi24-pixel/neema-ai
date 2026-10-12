import Foundation
import NeemaCore

/// The backend the screenshot gallery renders against: the answers
/// `GalleryFixtureExportTests` recorded from the core's fixtures, served by
/// method and path (the exact query first, else the same path). Anything
/// else gets FastAPI's own 404, so a missing fixture shows as an error state
/// in the screenshot rather than a hang.
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

    /// The fixtures bundled with the test target.
    static func bundled(for cls: AnyClass) throws -> CannedTransport {
        guard let url = Bundle(for: cls).url(forResource: "fixtures", withExtension: "json") else {
            throw NSError(domain: "Gallery", code: 2, userInfo: [NSLocalizedDescriptionKey: "fixtures.json is not in the test bundle"])
        }
        return try CannedTransport(json: try Data(contentsOf: url))
    }

    /// When the app last asked for anything: the gallery waits for a quiet moment before it renders.
    var lastRequest: Date { lock.sync { last } }

    func send(_ request: HTTPRequest) async throws -> HTTPResponse {
        lock.sync { last = Date() }
        var path = request.url.path
        if path.hasPrefix("/api/") { path = String(path.dropFirst(4)) }
        let query = request.url.query ?? ""
        let hits = canned.filter { $0.method == request.method && $0.path == path }
        guard let hit = hits.first(where: { $0.query == query }) ?? hits.first else {
            lock.sync { unmatched.append("\(request.method) \(path)\(query.isEmpty ? "" : "?\(query)")") }
            return HTTPResponse(status: 404, headers: ["x-gallery": "no fixture"], body: Data(#"{"detail":"Not Found"}"#.utf8))
        }
        return HTTPResponse(status: hit.status, headers: ["content-type": "application/json"], body: Data(hit.body.utf8))
    }
}
