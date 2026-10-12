import Foundation
import XCTest
@testable import NeemaCore

/// What every profile suite shares: the fake backend with the team fixtures
/// (handlers that validate like the real ones) and a signed-in host whose
/// /me and team rows have landed (Android `AreaTest` + `TeamFixtures`).
@MainActor
class ProfileTestCase: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var hosts: [TestHost] = []
    var vms: [ProfileViewModel] = []
    /// The fake's call log and the host's toasts from the moment the model was settled.
    private var callBase = 0
    private var toastBase = 0
    var done = 0
    lazy var onDone: () -> Void = { [weak self] in self?.done += 1 }

    /// What the fake answers on top of the base fixtures: the whole team install, or its writes only.
    func install(_ f: FakeNeema) { TeamFixtures.install(f) }

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        install(fake)
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
        for h in hosts { h.logout() }
        hosts = []
        AppClock.reset()
        try await super.tearDown()
    }

    /// A profile screen's model, settled; the call log and the toasts count from here.
    func vm(_ h: TestHost? = nil) async -> ProfileViewModel {
        let on = h ?? host!
        let v = ProfileViewModel(host: on)
        vms.append(v)
        await drain()
        _ = await eventually(timeout: 5) { !v.ui.refreshing }
        await drain()
        callBase = fake.calls.count
        toastBase = on.toasts.count
        return v
    }

    /// Lets a write and what follows it (refetches, toasts) land.
    func settled(_ v: ProfileViewModel) async {
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.saving && !v.settingAvailable && !v.ui.refreshing }
        await drain()
        await settle(ms: 20)
    }

    /// The signed-in agent as the screen finds them: /me, else the team row.
    func me() -> Agent { host.me.value ?? host.agents.value.first { $0.id == host.session.value?.agentId }! }
    var since: [FakeNeema.Call] { Array(fake.calls.dropFirst(callBase)) }
    func writes() -> [FakeNeema.Call] { since.filter { $0.method != "GET" } }
    func patches() -> Int { since.filter { $0.method == "PATCH" && $0.path == "/admin/me" }.count }
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
    /// "PATCH /admin/me" for the one write a test expects.
    func route(_ c: FakeNeema.Call) -> String { "\(c.method) \(c.path)" }
}
