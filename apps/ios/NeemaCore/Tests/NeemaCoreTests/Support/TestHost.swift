import Foundation
import XCTest
@testable import NeemaCore

/// Runs `body` on the main actor from wherever the caller is — a fake route
/// handler on the cooperative pool included — and waits for it (Android's
/// Unconfined dispatcher made such calls synchronous).
func onMainSync(_ body: @escaping @MainActor () -> Void) {
    if Thread.isMainThread { MainActor.assumeIsolated { body() } } else { DispatchQueue.main.sync { MainActor.assumeIsolated { body() } } }
}

/// A mutable box a route handler can share with its test.
final class Ref<T>: @unchecked Sendable {
    private let lock = NSLock()
    private var v: T
    init(_ v: T) { self.v = v }
    var value: T {
        get { lock.sync { v } }
        set { lock.sync { v = newValue } }
    }
}

/// Lets every queued hop run (the inbox's work is asynchronous tasks on the
/// main actor; the fake answers in-process, so a handful of turns settles it).
func drain() async {
    for _ in 0..<3 {
        for _ in 0..<25 { await Task.yield() }
        try? await Task.sleep(nanoseconds: 12_000_000)
    }
}

extension HTTPRequest {
    /// One decoded query parameter (`cursor`, `tab`, `before`…).
    func param(_ name: String) -> String? {
        for pair in (url.query ?? "").split(separator: "&") {
            let kv = pair.split(separator: "=", maxSplits: 1, omittingEmptySubsequences: false)
            guard String(kv[0]) == name else { continue }
            let raw = kv.count > 1 ? String(kv[1]) : ""
            return raw.replacingOccurrences(of: "+", with: " ").removingPercentEncoding ?? raw
        }
        return nil
    }
}

extension FakeNeema.Call {
    /// One decoded query parameter of a recorded call.
    func param(_ name: String) -> String? { params[name] }
}

/// `base` (a JSON array as text) with `extra` rows appended.
func withRows(_ base: String, _ extra: [String]) -> String {
    var t = base.trimmingCharacters(in: .whitespacesAndNewlines)
    if t.hasSuffix("]") { t.removeLast() }
    return t + extra.map { "," + $0 }.joined() + "]"
}

func json(_ text: String) -> [String: JSONValue] { JSONValue.parse(text)?.objectValue ?? [:] }

/// A signed-in shell for the inbox (Android's `dashboard(...)` + `testContainer`):
/// the fake API, a session for Moses, the app "in the foreground", a fake
/// socket, every delay on one virtual clock, and the toasts recorded.
final class TestHost: InboxHost, CustomerHost, OrdersHost, CatalogHost, DealsHost, @unchecked Sendable {
    /// A burst of 403s costs one re-read of who this agent is (the shell's `FORBIDDEN_WINDOW_MS`).
    static let FORBIDDEN_WINDOW_MS: Int64 = 1_000

    let fake: FakeNeema
    let clock: VirtualClock
    let sessionStore: SessionStore
    let auth: AuthRepository
    let http: NeemaHTTP
    let api: NeemaApi
    let sockets = FakeSocketFactory()
    let socket: LiveSocket
    let foreground = Watched<Bool>(true)
    let sessionExpired = Watched<Bool>(false)
    let inboxRefresh = Signal<Void>(buffer: 4)
    let inboxSummary = Watched<InboxSummary?>(nil)
    let openConvKey = Watched<String?>(nil)
    let composerPrefill = Watched<ComposerPrefill?>(nil)
    let snapshots: SnapshotCache
    private let lock = NSLock()
    private var _toasts: [Toast] = []
    private var _calls: [(waId: String, name: String?, convId: String?)] = []
    var callOutcome: CallOutcome = .placed
    private var subs: [Subscription] = []
    // CustomerHost / OrdersHost
    let orders = Watched<[Order]>([])
    /// The dashboard's orders feed (Android's DashboardViewModel orders poll), when the test asks for one.
    let feed: OrdersFeed?
    // CatalogHost
    let catalog = Watched<[CatalogItem]>([])
    let catalogFeed: CatalogFeed?
    private var forbiddenRefresh: Coalescer?
    private var _accessRereads = 0
    /// How often a 403 made this host re-read /admin/me and the team list.
    var accessRereads: Int { lock.sync { _accessRereads } }
    let callChannels = Watched<CallChannels?>(nil)
    var canManageSettings = true
    var messengerOutcome: CallOutcome = .placed
    private var _messengerCalls: [(psid: String, name: String?, convId: String?)] = []
    var placedMessengerCalls: [(psid: String, name: String?, convId: String?)] { lock.sync { _messengerCalls } }
    /// Replaces the permission request (the call manager's) when a test must shape its answer.
    var permissionRequest: ((String, String?, String) async throws -> PermissionRequestResponse)?

    var session: Watched<Session?> { sessionStore.session }
    var socketConnected: Watched<Bool> { socket.connected }
    var socketEvents: Signal<JSONValue> { socket.events }
    var toasts: [Toast] { lock.sync { _toasts } }
    var errors: [Toast] { toasts.filter { $0.type == .error } }
    var placedCalls: [(waId: String, name: String?, convId: String?)] { lock.sync { _calls } }

    init(fake: FakeNeema, role: String = "admin", superuser: Bool = true, clock: VirtualClock = VirtualClock(),
         snapshots: SnapshotCache? = nil, signedIn: Bool = true, ordersFeed: Bool = false, catalogFeed: Bool = false) {
        self.fake = fake
        self.clock = clock
        fake.sleep = clock.sleeper
        sessionStore = SessionStore(store: MemoryStore())
        auth = AuthRepository(store: sessionStore, base: "https://neema.test", transport: fake, backoffMs: 0, sleep: clock.sleeper)
        http = NeemaHTTP(baseUrl: "https://neema.test", tokens: auth, transport: fake)
        http.gate = fake
        api = NeemaApi(http: http)
        let store = sessionStore
        socket = LiveSocket(factory: sockets, baseUrl: "https://neema.test", token: { store.current?.accessToken }, sleep: clock.sleeper)
        self.snapshots = snapshots ?? SnapshotCache.temporary()
        feed = ordersFeed ? OrdersFeed(api: api, foreground: foreground, socketEvents: socket.events, reconnected: socket.reconnected,
                                       snapshots: self.snapshots, orders: orders, sleep: clock.sleeper, clock: { clock.now }) : nil
        self.catalogFeed = catalogFeed ? CatalogFeed(api: api, foreground: foreground, snapshots: self.snapshots, catalog: catalog, sleep: clock.sleeper) : nil
        if signedIn {
            sessionStore.save(Session(accessToken: fakeJwt(), refreshToken: "refresh", agentId: Fixtures.ME_ID, email: "moses@bethanyhouse.co.ke",
                                      name: "Moses Mwicigi", role: role, isSuperuser: superuser, mode: "direct"))
        }
        subs.append(http.sessionExpired.observe { [weak self] _ in
            guard let self = self else { return }
            if self.session.value != nil { self.sessionExpired.value = true }
        })
        // A refusal re-reads who this agent is (the shell's onForbidden), coalesced over a short window.
        let api = self.api
        forbiddenRefresh = Coalescer(windowMs: Self.FORBIDDEN_WINDOW_MS, sleep: clock.sleeper) { [weak self] in
            self?.lock.sync { self?._accessRereads += 1 }
            _ = try? await api.profile.me()
            _ = try? await api.agents.list()
        }
        subs.append(http.forbidden.observe { [weak self] _ in self?.forbiddenRefresh?.kick() })
        if signedIn, let f = feed { f.start(agentId: Fixtures.ME_ID) }
        if signedIn, let f = self.catalogFeed { f.start(agentId: Fixtures.ME_ID) }
    }

    // CatalogHost
    func refreshCatalog() async throws {
        if let f = catalogFeed { try await f.refreshCatalog() } else { catalog.value = try await api.catalog.list() }
    }

    // OrdersHost
    func refreshOrders() async throws {
        if let f = feed { try await f.refreshOrders() } else { orders.value = try await api.orders.list() }
    }
    func refetchOrders() { Task { [weak self] in _ = try? await self?.refreshOrders() } }

    func toast(_ message: String, _ type: ToastType) { lock.sync { _toasts.append(Toast(message: message, type: type)) } }

    func placeCall(waId: String, name: String?, convId: String?) async -> CallOutcome {
        lock.sync { _calls.append((waId, name, convId)) }
        return callOutcome
    }

    func placeMessengerCall(psid: String, name: String?, convId: String?) async -> CallOutcome {
        lock.sync { _messengerCalls.append((psid, name, convId)) }
        return messengerOutcome
    }

    func requestCallPermission(to: String, name: String?, channel: String) async throws -> PermissionRequestResponse {
        if let p = permissionRequest { return try await p(to, name, channel) }
        return channel == CallWords.MESSENGER ? try await api.calls.requestMessengerPermission(psid: to) : try await api.calls.requestPermission(to: to, name: name)
    }

    /// `DashboardViewModel.openConversationFor`.
    func openConversationFor(_ key: String) { openConvKey.value = key }
    /// The SessionExpired dialog's sign-in succeeded.
    func onReauthenticated() { sessionExpired.value = false }
    func logout() {
        feed?.stop()
        catalogFeed?.stop()
        sessionStore.clear()
        sessionExpired.value = false
        inboxSummary.value = nil
        openConvKey.value = nil
        socket.signOut()
    }
    func refreshInbox() { inboxRefresh.emit() }
    /// The live socket, open.
    func connectLive() {
        socket.connect(Fixtures.ME_ID)
        sockets.last.open()
    }
}
