import XCTest
@testable import NeemaCore

/// What every customer-panel suite shares: the fake backend with the CRM
/// fixtures, a signed-in host on one virtual clock, and the small helpers
/// Android's suites use (calls, lastBody, advance).
@MainActor
class CustomerTestCase: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var vms: [CustomerViewModel] = []

    override func setUp() async throws {
        try await super.setUp()
        StageCache.stages = nil
        fake = CustomerFixtures.withFixtures()
        host = TestHost(fake: fake)
    }

    override func tearDown() async throws {
        for v in vms { v.close() }
        vms = []
        StageCache.stages = nil
        try await super.tearDown()
    }

    /// A signed-in host with another role (the panel's stage editor follows the server's rule).
    func signIn(role: String, superuser: Bool) {
        host = TestHost(fake: fake, role: role, superuser: superuser)
        host.canManageSettings = superuser || role == "admin"
    }

    /// A panel for `convId` (or `conv`), settled after its first loads.
    func vm(_ convId: String = "c1", conv: Conversation? = nil, fetch: ((String, String?) async throws -> CustomerProfile)? = nil) async -> CustomerViewModel {
        let v = CustomerViewModel(host: host, conversation: conv ?? CustomerFixtures.conversation(convId), fetchProfile: fetch, sleep: host.clock.sleeper)
        vms.append(v)
        await drain()
        return v
    }

    func calls(_ method: String, _ path: String) -> [FakeNeema.Call] { fake.callsTo(method, path) }
    func lastBody(_ method: String, _ path: String) -> [String: JSONValue] { json(calls(method, path).last?.body ?? "{}") }
    var toasts: [Toast] { host.toasts }
    func lastToast() -> Toast? { host.toasts.last }
    func errors() -> [Toast] { host.toasts.filter { $0.type == .error } }

    /// Lets the coalesced reload leave (virtual time), then settles.
    func advance(_ ms: Int64 = CustomerViewModel.RELOAD_COALESCE_MS + 1) async {
        await host.clock.advance(by: ms)
        await drain()
    }

    func peterWith(_ from: String, _ to: String) -> String {
        let s = CustomerFixtures.peter.replacingOccurrences(of: from, with: to)
        precondition(s != CustomerFixtures.peter, "the fixture never contained \(from)")
        return s
    }

    var peterPath: String { "/admin/customers/\(CustomerFixtures.PETER)" }
}
