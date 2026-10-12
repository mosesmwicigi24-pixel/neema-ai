import Foundation
import XCTest
@testable import NeemaCore

/// What every reports suite shares: the fake backend with the reports
/// fixtures (pinned to Friday 25 Sep 2026, Nairobi) and a signed-in host on one virtual clock.
@MainActor
class ReportsTestCase: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var vms: [ReportsViewModel] = []
    var hosts: [TestHost] = []
    private var dirs: [URL] = []

    static let NOW_MS = Int64(ReportsFixtures.NOW.timeIntervalSince1970 * 1000)
    static let NAIROBI = ReportsFixtures.NAIROBI

    override func setUp() async throws {
        try await super.setUp()
        ReportsFixtures.pinTimeZone()
        fake = Fixtures.withFixtures()
        ReportsFixtures.install(fake)
        host = TestHost(fake: fake)
        hosts.append(host)
        // The dashboard's lists the report is also built from (Android's `dashboard()` reads them at sign-in).
        _ = try? await host.refreshOrders()
        _ = try? await host.refreshAgents()
    }

    override func tearDown() async throws {
        for v in vms { v.close() }
        vms = []
        for h in hosts { h.logout() }
        hosts = []
        for d in dirs { try? FileManager.default.removeItem(at: d) }
        dirs = []
        ReportsFixtures.restoreTimeZone()
        try await super.tearDown()
    }

    /// A reports screen on `h` (the shared host by default), settled: the download landed (or failed) and the first report is built.
    func vm(_ h: TestHost? = nil) async -> ReportsViewModel {
        let on = h ?? host!
        let v = ReportsViewModel(host: on, sleep: on.clock.sleeper)
        vms.append(v)
        await landed(v)
        return v
    }

    /// Waits for `v`'s download and report (or its failure) to land.
    func landed(_ v: ReportsViewModel, timeout: TimeInterval = 30) async {
        await drain()
        _ = await eventually(timeout: timeout) { v.ui.allConvs != nil || v.ui.loadError != nil }
        if v.ui.allConvs != nil { _ = await eventually(timeout: timeout) { v.ui.report != nil } }
        await drain()
    }

    /// Only the Reports download (no `limit`) behaves as `handler`; the inbox pages still answer.
    func fullList(_ handler: @escaping () throws -> (Int, String)) {
        fake.on("GET", "/admin/conversations") { r, _ in
            if r.param("limit") == nil { return try handler() }
            return (200, #"{"items":[],"next_cursor":null}"#)
        }
    }

    var fullBody: String { "[" + ReportsFixtures.conversations.joined(separator: ",") + "]" }
    func gets(_ path: String) -> [String?] { fake.callsTo("GET", path).map { $0.query } }
    func reads(_ path: String) -> Int { fake.callsTo("GET", path).count }
    func downloads() -> Int { fake.callsTo("GET", "/admin/conversations").filter { $0.query == nil }.count }
    var errors: [String] { host.errors.map { $0.message } }
    func advance(_ ms: Int64) async { await host.clock.advance(by: ms); await drain() }

    /// A fresh directory for an export, removed after the test.
    func tempDir(_ name: String = "reports") -> URL {
        let d = FileManager.default.temporaryDirectory.appendingPathComponent("neema-\(name)-\(UUID().uuidString)")
        dirs.append(d)
        return d
    }

    func report(_ range: ReportRange, from: LocalDay? = nil, to: LocalDay? = nil,
                convs: [Conversation], orders: [Order], agents: [Agent]) -> Report {
        ReportsRules.buildReport(convs, orders: orders, agents: agents, range: range, customFrom: from, customTo: to, now: Self.NOW_MS, zone: Self.NAIROBI)
    }
}
