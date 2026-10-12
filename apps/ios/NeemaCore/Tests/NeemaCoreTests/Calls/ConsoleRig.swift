import Foundation
import XCTest
@testable import NeemaCore

/// The calls console over the fake backend (Android's `dashboard(context, fake)` + `CallsViewModel(dash)`).
@MainActor
final class ConsoleRig {
    let fake: FakeNeema
    let host: TestHost
    let vm: CallsViewModel
    init(fake: FakeNeema, live: Bool = false) {
        self.fake = fake
        host = TestHost(fake: fake)
        if live { host.connectLive() }
        vm = CallsViewModel(host: host, sleep: host.clock.sleeper)
    }
    /// The first read of the log has landed (or failed).
    func loaded() async { _ = await eventually(timeout: 5) { self.vm.calls.value != nil && !self.vm.busy } }
    var loads: Int { fake.callsTo("GET", "/admin/calls").count }
    func advance(_ ms: Int64) async { await host.clock.advance(by: ms); await drain() }
    func frame(_ json: String) { host.sockets.last.frame(json) }
    func stop() { vm.close(); host.logout() }
}

/// `FakeNeema.withFixtures()` with the call log, and the two POST handlers the console uses (as routers/admin.py answers them).
func callsFake() -> FakeNeema {
    let f = Fixtures.withFixtures()
    CallsFixtures.install(f)
    f.on("POST", "/admin/calls/[^/]+/follow-up-done", body: #"{"ok":true}"#)
    f.on("POST", "/admin/calls/[^/]+/transcribe") { req, _ in
        let id = req.path.split(separator: "/").map(String.init)[2]
        return (200, "{\"ok\":true,\"call_id\":\"\(id)\",\"status\":\"pending\"}")
    }
    return f
}
