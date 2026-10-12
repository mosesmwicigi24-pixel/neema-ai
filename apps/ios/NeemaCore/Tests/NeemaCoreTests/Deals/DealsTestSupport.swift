import Foundation
import XCTest
@testable import NeemaCore

/// What every deals suite shares: the fake backend with the sales fixtures and a signed-in host on one virtual clock.
@MainActor
class DealsTestCase: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var vms: [DealsViewModel] = []

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

    /// A deals screen, settled after its first load.
    func vm() async -> DealsViewModel {
        let v = DealsViewModel(host: host, sleep: host.clock.sleeper)
        vms.append(v)
        await drain()
        return v
    }

    func gets(_ path: String) -> [String?] { fake.callsTo("GET", path).map { $0.query } }
    var errors: [String] { host.errors.map { $0.message } }
    func lastToast() -> Toast? { host.toasts.last }
    func advance(_ ms: Int64) async { await host.clock.advance(by: ms); await drain() }
    func ids(_ list: [PlannedAction]?) -> [String] { (list ?? []).map { $0.id } }

}

/// The id in `/admin/actions/{id}/approve`.
func actionIdOf(_ r: HTTPRequest) -> String {
    let parts = r.path.split(separator: "/")
    return String(parts[parts.count - 2])
}

/// What crm.py's queue does on the server (Android `DealsNetworkTest`'s server):
/// pending ids, the messages that actually went, 409 once resolved.
final class QueueServer: @unchecked Sendable {
    let fake: FakeNeema
    private let lock = NSLock()
    private var _pending: Set<String> = ["x1", "x2"]
    private var _sent: [String] = []
    var pending: Set<String> { get { lock.sync { _pending } } set { lock.sync { _pending = newValue } } }
    var sent: [String] { lock.sync { _sent } }

    init(_ fake: FakeNeema) { self.fake = fake }

    func queueJson() -> String {
        let all = JSONValue.parse(SalesFixtures.actions)?.objectValue?["actions"]?.arrayValue ?? []
        let keep = pending
        return JSONValue.object(["actions": .array(all.filter { keep.contains($0.objectValue?["id"]?.stringValue ?? "") })]).text
    }

    /// What crm.py approve_action does: 409 once resolved, else send and mark sent.
    func approve(_ id: String) -> (Int, String) {
        lock.sync {
            if !_pending.contains(id) { return (409, #"{"detail":"Action is sent"}"#) }
            _sent.append(id); _pending.remove(id)
            return (200, #"{"ok":true,"sent":"Hello 🙏"}"#)
        }
    }

    func veto(_ id: String) { lock.sync { _ = _pending.remove(id) } }

    func install() {
        fake.on("GET", "/admin/actions") { [self] _, _ in (200, self.queueJson()) }
        fake.on("POST", "/admin/actions/([^/]+)/approve") { [self] r, _ in self.approve(actionIdOf(r)) }
        fake.on("POST", "/admin/actions/([^/]+)/veto") { [self] r, _ in self.veto(actionIdOf(r)); return (200, #"{"ok":true}"#) }
    }
}
