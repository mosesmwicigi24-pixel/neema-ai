import Foundation
import XCTest
@testable import NeemaCore

/// What every analytics suite shares: the fake backend with the reports
/// fixtures (pinned to Friday 25 Sep 2026, Nairobi) and a signed-in host on one virtual clock.
@MainActor
class OverviewTestCase: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var vms: [OverviewViewModel] = []
    var hosts: [TestHost] = []

    override func setUp() async throws {
        try await super.setUp()
        ReportsFixtures.pinTimeZone()
        fake = Fixtures.withFixtures()
        ReportsFixtures.install(fake)
        host = TestHost(fake: fake)
        hosts.append(host)
    }

    override func tearDown() async throws {
        for v in vms { v.close() }
        vms = []
        for h in hosts { h.logout() }
        hosts = []
        ReportsFixtures.restoreTimeZone()
        try await super.tearDown()
    }

    /// An analytics screen on `h` (the shared host by default), settled after its mount-time reads.
    func vm(_ h: TestHost? = nil) async -> OverviewViewModel {
        let on = h ?? host!
        let v = OverviewViewModel(host: on, sleep: on.clock.sleeper)
        vms.append(v)
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.statsLoading }
        await drain()
        return v
    }

    func gets(_ path: String) -> [String?] { fake.callsTo("GET", path).map { $0.query } }
    func reads(_ path: String) -> Int { fake.callsTo("GET", path).count }
    /// Reads of the inbox's human tab (the intercepts feed).
    func humanReads() -> Int { fake.callsTo("GET", "/admin/conversations").filter { ($0.query ?? "").contains("tab=human") }.count }
    func advance(_ ms: Int64) async { await host.clock.advance(by: ms); await drain() }
    var errors: [String] { host.errors.map { $0.message } }
}
