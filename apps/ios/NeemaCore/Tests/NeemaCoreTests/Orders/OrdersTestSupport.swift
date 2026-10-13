import Foundation
import XCTest
@testable import NeemaCore

/*
 * Network faults for the sales screens' tests, on top of FakeNeema (Android
 * `NetFaults.kt`). A handler that throws is exactly what the transport does on
 * a phone network: NeemaHTTP turns it into ApiError(status 0, …) as it would
 * the real thing.
 */
extension FakeNeema {
    /// Connection refused / no route: nothing reached the server.
    func failOffline(_ method: String, _ path: String) {
        on(method, path) { _, _ in throw TransportError.network("Failed to connect to neema.test/10.0.0.1:443") }
    }

    /// The 30 s ceiling hit. `serverDid` runs first: the server may well have done the work.
    func failTimeout(_ method: String, _ path: String, serverDid: @escaping (String?) -> Void = { _ in }) {
        on(method, path) { _, body in serverDid(body); throw TransportError.timedOut }
    }

    /// The connection dropped mid-answer after the server did the work.
    func failDropped(_ method: String, _ path: String, serverDid: @escaping (String?) -> Void = { _ in }) {
        on(method, path) { _, body in serverDid(body); throw TransportError.network("unexpected end of stream on https://neema.test/...") }
    }

    /// A proxy's HTML error page (nginx 502, Cloudflare 503…) — never to be shown raw.
    func htmlPage(_ method: String, _ path: String, code: Int) {
        on(method, path, code: code, body: "<html><head><title>\(code) Bad Gateway</title></head><body><center><h1>\(code) Bad Gateway</h1></center><hr><center>nginx</center></body></html>")
    }

    /// 401 on the first `times` calls, then `then`: an access token that expired mid-action.
    func expiredOnce(_ method: String, _ path: String, times: Int = 1, then: @escaping () -> (Int, String)) {
        let n = Ref(0)
        on(method, path) { _, _ in
            let i = n.value; n.value = i + 1
            return i < times ? (401, #"{"detail":"Token expired"}"#) : then()
        }
    }

    /// The bodies of every call to `method` `path`, as JSON objects.
    func bodies(_ method: String, _ path: String) -> [[String: JSONValue]] { callsTo(method, path).map { json($0.body ?? "{}") } }
}

/// What every orders suite shares: the fake backend with the sales fixtures,
/// a signed-in host whose orders feed has read the list once, and the small
/// helpers Android's suites use.
@MainActor
class OrdersTestCase: XCTestCase {
    /// A status change runs to its end: the PATCH and, when its answer was lost, the
    /// list re-read that settles what happened (`updating` clears last, in a defer).
    /// A slow CI runner can take longer than one drain for those two round trips.
    func finishUpdate(_ vm: OrdersViewModel) async {
        _ = await eventually { vm.ui.updating == nil }
        await drain()
    }

    var fake: FakeNeema!
    var host: TestHost!
    var hosts: [TestHost] = []
    var vms: [OrdersViewModel] = []

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        SalesFixtures.install(fake)
        host = await signedIn()
    }

    override func tearDown() async throws {
        for v in vms { v.close() }
        vms = []
        for h in hosts { h.logout() }
        hosts = []
        AppClock.reset()
        try await super.tearDown()
    }

    /// A signed-in host (Android's `dashboard(context, fake)`) with the orders feed started and its first read landed.
    func signedIn(role: String = "admin", superuser: Bool = true, snapshots: SnapshotCache? = nil) async -> TestHost {
        let h = TestHost(fake: fake, role: role, superuser: superuser, snapshots: snapshots, ordersFeed: true)
        hosts.append(h)
        // The feed's first read leaves on sign-in; a thousand-order answer takes a moment to decode.
        await drain()
        _ = await eventually(timeout: 10) { !(h.feed?.reading ?? false) }
        await drain()
        return h
    }

    /// An orders screen on `h` (the shared host by default), settled after its first load.
    func vm(_ h: TestHost? = nil) async -> OrdersViewModel {
        let on = h ?? host!
        let v = OrdersViewModel(host: on, sleep: on.clock.sleeper)
        vms.append(v)
        await drain()
        return v
    }

    func gets() -> Int { fake.callsTo("GET", "/admin/orders").count }
    var orders: [Order] { host.orders.value }
    func order(_ id: String) -> Order { orders.first { $0.id == id }! }
    var errors: [String] { host.errors.map { $0.message } }
    func lastToast() -> Toast? { host.toasts.last }
    func advance(_ ms: Int64) async { await host.clock.advance(by: ms); await drain() }

    /// The server's list with order `id` now in `status`.
    func listWith(_ id: String, _ status: String) -> String {
        SalesFixtures.ordersJson(SalesFixtures.orders.map { row in
            guard row.contains("\"id\":\"\(id)\"") else { return row }
            return row.replacingOccurrences(of: "\"status\":\"[a-z]+\"", with: "\"status\":\"\(status)\"", options: .regularExpression)
        })
    }
}
