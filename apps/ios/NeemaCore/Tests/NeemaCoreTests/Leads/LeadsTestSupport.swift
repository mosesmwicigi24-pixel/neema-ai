import Foundation
import XCTest
@testable import NeemaCore

/// What every leads suite shares: the fake backend with the sales fixtures and a signed-in host on one virtual clock.
@MainActor
class LeadsTestCase: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var vms: [LeadsViewModel] = []

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        SalesFixtures.install(fake)
        host = TestHost(fake: fake)
    }

    override func tearDown() async throws {
        for v in vms { v.close() }
        vms = []
        host.logout()
        AppClock.reset()
        try await super.tearDown()
    }

    /// A leads screen, settled after its first load (a five-hundred-lead answer takes a moment to decode).
    func vm() async -> LeadsViewModel {
        let v = LeadsViewModel(host: host, sleep: host.clock.sleeper)
        vms.append(v)
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.loading }
        await drain()
        return v
    }

    func lead(_ vm: LeadsViewModel, _ id: String) -> Lead { vm.ui.leads.first { $0.id == id }! }
    func gets() -> Int { fake.callsTo("GET", "/admin/leads").count }
    var errors: [String] { host.errors.map { $0.message } }
    func lastToast() -> Toast? { host.toasts.last }
    func advance(_ ms: Int64) async { await host.clock.advance(by: ms); await drain() }

    /// The server's board with lead `id` changed by `edit` (a JSON-text rewrite of its row).
    func boardWith(_ id: String, _ edit: (String) -> String) -> String {
        SalesFixtures.leadsJson(SalesFixtures.leads.map { $0.contains("\"id\":\"\(id)\"") ? edit($0) : $0 })
    }

    var leadsApi: LeadsApi { LeadsApi(http: host.api.http) }
}
