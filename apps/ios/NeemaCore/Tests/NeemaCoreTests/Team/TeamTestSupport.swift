import Foundation
import XCTest
@testable import NeemaCore

/// What every team suite shares: the fake backend with the team fixtures
/// (handlers that validate like the real ones) and a signed-in admin host.
@MainActor
class TeamTestCase: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var vms: [TeamViewModel] = []
    /// The fake's call log and the host's toasts from the moment the model was settled.
    private var callBase = 0
    private var toastBase = 0
    var done = 0
    lazy var onDone: () -> Void = { [weak self] in self?.done += 1 }

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        TeamFixtures.install(fake)
        host = TestHost(fake: fake)
        // The dashboard's team list and the signed-in agent's row, as `dashboard()` reads them at sign-in.
        _ = try? await host.refreshAgents()
        host.refetchMe()
        await drain()
        _ = await eventually(timeout: 5) { self.host.me.value != nil }
    }

    override func tearDown() async throws {
        for v in vms { v.close() }
        vms = []
        host.logout()
        AppClock.reset()
        try await super.tearDown()
    }

    /// A team screen, settled after its roles read; the call log and the toasts count from here.
    func vm(_ h: TestHost? = nil) async -> TeamViewModel {
        let on = h ?? host!
        let v = TeamViewModel(host: on, sleep: on.clock.sleeper)
        vms.append(v)
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.rolesLoading }
        await drain()
        callBase = fake.calls.count
        toastBase = on.toasts.count
        return v
    }

    /// Lets a write and what follows it (refetches, toasts) land.
    func settled(_ v: TeamViewModel) async {
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.saving }
        await drain()
        await settle(ms: 20)
    }

    func agent(_ id: String) -> Agent { host.agents.value.first { $0.id == id }! }
    var since: [FakeNeema.Call] { Array(fake.calls.dropFirst(callBase)) }
    func writes() -> [FakeNeema.Call] { since.filter { $0.method != "GET" } }
    func writesTo(_ method: String, _ pathPattern: String) -> Int {
        since.filter { $0.method == method && $0.path.range(of: "^\(pathPattern)$", options: .regularExpression) != nil }.count
    }
    func called(_ method: String, _ path: String) -> Bool { since.contains { $0.method == method && $0.path == path } }
    func fail(_ method: String, _ path: String, _ code: Int, _ body: String) { fake.on(method, path, code: code, body: body) }
    /// A FastAPI `{"detail": …}` answer.
    func status(_ method: String, _ path: String, _ code: Int, _ detail: String) {
        fake.on(method, path, code: code, body: "{\"detail\":\(JSONValue.string(detail).text)}")
    }
    var toasts: [Toast] { Array(host.toasts.dropFirst(toastBase)) }
    func lastToast() -> Toast? { host.toasts.last }
    func json(_ c: FakeNeema.Call) -> JSONValue? { JSONValue.parse(c.body ?? "") }
    func el(_ s: String) -> JSONValue? { JSONValue.parse(s) }

    /// The team list the server would answer after `change`.
    func agentsWith(_ change: (inout [[String: JSONValue]]) -> Void) -> String {
        var rows = JSONValue.parse(TeamFixtures.agents)?.arrayValue?.compactMap { $0.objectValue } ?? []
        change(&rows)
        return JSONValue.array(rows.map { .object($0) }).text
    }
}
