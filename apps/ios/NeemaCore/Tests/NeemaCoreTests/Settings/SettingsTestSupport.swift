import Foundation
import XCTest
@testable import NeemaCore

/// What every settings suite shares: the fake backend with crm.py's settings
/// routes (handlers that validate like the real ones) and a signed-in admin
/// host (Android `AreaTest` + `TeamFixtures.settings`).
@MainActor
class SettingsTestCase: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var hosts: [TestHost] = []
    var vms: [SettingsViewModel] = []
    /// The fake's call log and the host's toasts from the moment the model was settled.
    private var callBase = 0
    private var toastBase = 0

    /// What the fake answers on top of the base fixtures.
    func install(_ f: FakeNeema) { TeamFixtures.settings(f) }

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        install(fake)
        host = TestHost(fake: fake)
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

    /// A settings screen's model, settled after its four reads; the call log and the toasts count from here.
    func vm(_ h: TestHost? = nil) async -> SettingsViewModel {
        let v = await fresh(h)
        mark()
        return v
    }

    /// A fresh model whose reads have landed, counters untouched (the app restarted).
    func fresh(_ h: TestHost? = nil) async -> SettingsViewModel {
        let on = h ?? host!
        let v = SettingsViewModel(host: on, sleep: on.clock.sleeper)
        vms.append(v)
        await settled(v)
        return v
    }

    /// Count calls and toasts from now.
    func mark() {
        callBase = fake.calls.count
        toastBase = host.toasts.count
    }

    /// Lets a read or a write and what follows it (re-reads, toasts) land.
    func settled(_ v: SettingsViewModel) async {
        await drain()
        _ = await eventually(timeout: 10) { !v.busy }
        await drain()
        await settle(ms: 20)
    }

    var since: [FakeNeema.Call] { Array(fake.calls.dropFirst(callBase)) }
    func writes() -> [FakeNeema.Call] { since.filter { $0.method != "GET" } }
    func puts(_ path: String) -> Int { since.filter { $0.method == "PUT" && $0.path == "/admin/settings/\(path)" }.count }
    func called(_ method: String, _ path: String) -> Bool { since.contains { $0.method == method && $0.path == path } }
    /// A FastAPI `{"detail": …}` refusal (Android `AreaTest.fail`: 403 "Admin only" by default).
    func fail(_ method: String, _ path: String, _ code: Int = 403, _ detail: String = "Admin only") {
        fake.on(method, path, code: code, body: "{\"detail\":\(JSONValue.string(detail).text)}")
    }
    var toasts: [Toast] { Array(host.toasts.dropFirst(toastBase)) }
    func lastToast() -> Toast? { host.toasts.last }
    func json(_ c: FakeNeema.Call) -> JSONValue? { JSONValue.parse(c.body ?? "") }
    func el(_ s: String) -> JSONValue? { JSONValue.parse(s) }
    /// The campaign a PUT /admin/settings/offer carried.
    func sentCampaign(_ c: FakeNeema.Call) -> [String: JSONValue]? { json(c)?["campaign"]?.objectValue }
}
