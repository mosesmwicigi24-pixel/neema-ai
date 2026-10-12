import Foundation
import XCTest
@testable import NeemaCore

/// Every path the client builds is one the server serves. The server's
/// table (`ServerRoutes`, generated from the routers' decorators and
/// main.py's prefixes) is matched against every `http.get/post/put/patch/
/// delete`, `http.raw` and `http.multipart` call in NeemaCore's sources,
/// read at test time — so a renamed handler, a wrong method or a typo in a
/// path fails here on Linux, before the macOS job. Android has no such
/// check; its `ApiContractTest` covers the shapes, this covers the routes.
final class RouteCoverageTests: XCTestCase {
    struct Call: Hashable {
        let method: String
        let path: String
        let file: String
    }

    /// Tests/NeemaCoreTests/RouteCoverageTests.swift → Sources/NeemaCore.
    private static var sourcesDir: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources").appendingPathComponent("NeemaCore")
    }

    /// A Swift path literal as the server would see it: every `\(…)` (balanced)
    /// is a path parameter, a `\(…)` glued to the end of a segment is the query
    /// string the caller built, and anything after `?` is a query.
    static func normalise(_ literal: String) -> String {
        var out = ""
        var i = literal.startIndex
        while i < literal.endIndex {
            if literal[i] == "\\", literal.index(after: i) < literal.endIndex, literal[literal.index(after: i)] == "(" {
                var depth = 0
                var j = literal.index(after: i)
                while j < literal.endIndex {
                    if literal[j] == "(" { depth += 1 }
                    if literal[j] == ")" { depth -= 1; if depth == 0 { break } }
                    j = literal.index(after: j)
                }
                out += "{p}"
                i = j < literal.endIndex ? literal.index(after: j) : j
            } else {
                out.append(literal[i])
                i = literal.index(after: i)
            }
        }
        if let q = out.firstIndex(of: "?") { out = String(out[..<q]) }
        // "…/messages\(query)" — the interpolation is the query, not a segment.
        if out.hasSuffix("{p}"), !out.hasSuffix("/{p}") { out = String(out.dropLast(3)) }
        return out
    }

    /// Every (method, path) the sources under `dir` call.
    static func clientCalls(in dir: URL) throws -> Set<Call> {
        let fm = FileManager.default
        guard let e = fm.enumerator(at: dir, includingPropertiesForKeys: nil) else { return [] }
        let verb = try NSRegularExpression(pattern: #"http\.(get|post|put|patch|delete)\s*\(\s*"([^"]+)""#)
        let raw = try NSRegularExpression(pattern: #"http\.raw\(\s*"([A-Z]+)"\s*,\s*"([^"]+)""#)
        let multipart = try NSRegularExpression(pattern: #"http\.multipart\(\s*"([^"]+)""#)
        var out = Set<Call>()
        for case let url as URL in e where url.pathExtension == "swift" {
            let src = try String(contentsOf: url)
            let range = NSRange(src.startIndex..., in: src)
            func group(_ m: NSTextCheckingResult, _ i: Int) -> String { Range(m.range(at: i), in: src).map { String(src[$0]) } ?? "" }
            for m in verb.matches(in: src, range: range) {
                out.insert(Call(method: group(m, 1).uppercased(), path: normalise(group(m, 2)), file: url.lastPathComponent))
            }
            for m in raw.matches(in: src, range: range) {
                out.insert(Call(method: group(m, 1), path: normalise(group(m, 2)), file: url.lastPathComponent))
            }
            for m in multipart.matches(in: src, range: range) {
                out.insert(Call(method: "POST", path: normalise(group(m, 1)), file: url.lastPathComponent))
            }
        }
        return out
    }

    /// Whether the server serves `method` `/api<path>`: `{param}` segments match anything but a slash.
    static func served(_ method: String, _ path: String) -> Bool {
        let want = "/api" + path.replacingOccurrences(of: "{p}", with: "X")
        return ServerRoutes.all.contains { r in r.method == method && want.range(of: pattern(for: r.path), options: .regularExpression) != nil }
    }

    /// "/api/admin/agents/{agent_id}" → "^/api/admin/agents/[^/]+$" (the literal pieces escaped).
    static func pattern(for route: String) -> String {
        var out = "^"
        for (i, piece) in route.components(separatedBy: "{").enumerated() {
            if i == 0 {
                out += NSRegularExpression.escapedPattern(for: piece)
            } else {
                let rest = piece.split(separator: "}", maxSplits: 1, omittingEmptySubsequences: false)
                out += "[^/]+" + NSRegularExpression.escapedPattern(for: rest.count > 1 ? String(rest[1]) : "")
            }
        }
        return out + "$"
    }

    private func calls() throws -> Set<Call> {
        let dir = Self.sourcesDir
        guard FileManager.default.fileExists(atPath: dir.path) else { throw XCTSkip("NeemaCore's sources are not beside the tests here") }
        return try Self.clientCalls(in: dir)
    }

    func testNormalisation() {
        XCTAssertEqual(Self.normalise("/admin/conversations/\\(enc(id))/messages\\(q)"), "/admin/conversations/{p}/messages")
        XCTAssertEqual(Self.normalise("/admin/customers/\\(enc(waId))/merge_suggestions\\(query(channel))"), "/admin/customers/{p}/merge_suggestions")
        XCTAssertEqual(Self.normalise("/admin/calls/\\(enc(callId))/terminate"), "/admin/calls/{p}/terminate")
        XCTAssertEqual(Self.normalise("/admin/client-crashes?limit=\\(limit)"), "/admin/client-crashes")
        XCTAssertEqual(Self.normalise("/admin/me"), "/admin/me")
        XCTAssertTrue(Self.served("GET", "/admin/conversations/{p}/messages"))
        XCTAssertTrue(Self.served("PUT", "/admin/settings/offer"))
        XCTAssertFalse(Self.served("PATCH", "/admin/settings/offer"), "the offer is PUT, never PATCH")
        XCTAssertFalse(Self.served("GET", "/admin/no-such-route"))
    }

    func testEveryClientCallIsServed() throws {
        let all = try calls()
        let missing = all.filter { !Self.served($0.method, $0.path) }.sorted { $0.path < $1.path }
        XCTAssertTrue(missing.isEmpty, "not served by apps/api/app: " + missing.map { "\($0.method) \($0.path) (\($0.file))" }.joined(separator: ", "))
        // The Android app calls 81 endpoints (docs/ios/PARITY_MATRIX.md §23); the core must still reach every one.
        let distinct = Set(all.map { "\($0.method) \($0.path)" })
        XCTAssertGreaterThanOrEqual(distinct.count, 81, "\(distinct.count) distinct calls")
    }

    /// The client's calls, by handler file — a readable list in the test log for the cycle records.
    func testListsTheCallsByFile() throws {
        let all = try calls()
        let byFile = Dictionary(grouping: all, by: { $0.file }).mapValues { $0.count }
        XCTAssertFalse(byFile.isEmpty)
        let distinct = Set(all.map { "\($0.method) \($0.path)" })
        print("RouteCoverage: \(distinct.count) distinct client calls (\(all.count) sites across \(byFile.count) files); \(ServerRoutes.all.count) server routes")
    }
}
