import Foundation

/// The dashboard's orders list (the orders part of Android's
/// `DashboardViewModel`): one GET /admin/orders on the wire at a time — the
/// 90 s poll, a reconnect's catch-up, an `order_update` alert, re-auth and a
/// pull-to-refresh that meet share a read (a caller arriving mid-read gets the
/// next one, so its answer never predates its reason to ask). Painted from
/// this agent's last snapshot at sign-in; kept per agent.
public final class OrdersFeed: @unchecked Sendable {
    /// The web's `usePolling(fetchOrders, 90_000)`.
    public static let POLL_MS: Int64 = 90_000
    /// Orders fetched this recently need no catch-up on reconnect.
    public static let CATCH_UP_FRESH_MS: Int64 = 5_000
    public static let SNAPSHOT_KEY = "orders"

    /// Every order the dashboard knows (the customer panel and the badge read it too).
    public let orders: Watched<[Order]>
    private let api: NeemaApi
    private let foreground: Watched<Bool>
    private let snapshots: SnapshotCache
    private let sleep: Sleeper
    private let clock: @Sendable () -> Int64
    private let lock = NSLock()
    private var read: SingleFlight<Void>!
    private var kick: Coalescer!
    private var subs: [Subscription] = []
    private var pollTask: Task<Void, Never>?
    private var agentId: String?
    /// When orders last arrived (a poll that just ran makes a catch-up redundant).
    private var lastFetch: Int64 = 0

    public init(api: NeemaApi, foreground: Watched<Bool>, socketEvents: Signal<JSONValue>, reconnected: Signal<Void>,
                snapshots: SnapshotCache, orders: Watched<[Order]> = Watched<[Order]>([]), sleep: @escaping Sleeper = realSleep,
                clock: @escaping @Sendable () -> Int64 = { AppClock.now() }) {
        self.api = api
        self.foreground = foreground
        self.snapshots = snapshots
        self.orders = orders
        self.sleep = sleep
        self.clock = clock
        read = SingleFlight { [weak self] in try await self?.fetchNow() }
        // One GET /admin/orders per burst of order alerts: the web's
        // setTimeout(refetch, 800) per event, coalesced.
        kick = Coalescer(windowMs: Coalescer.EVENT_WINDOW_MS, sleep: sleep) { [weak self] in try await self?.refreshOrders() }
        subs.append(socketEvents.observe { [weak self] e in
            guard e.str("event") == "notification", e.str("type") == "order_update" else { return }
            self?.kick.kick()
        })
        // Frames sent while the socket was down are gone for good: catch up on
        // what it would have said — unless a fetch just ran.
        subs.append(reconnected.observe { [weak self] _ in
            guard let self = self, self.signedIn else { return }
            if self.clock() - self.lock.sync({ self.lastFetch }) > Self.CATCH_UP_FRESH_MS { self.refetchOrders() }
        })
    }

    public var signedIn: Bool { lock.sync { agentId != nil } }

    /// A read of the list is on the wire.
    public var reading: Bool { read.inFlight }

    /// The nav badge: orders still pending.
    public var pendingOrders: Int { orders.value.reduce(0) { $0 + ($1.status == "pending" ? 1 : 0) } }

    /// Sign-in, keyed by who (a token refresh for the same agent changes
    /// nothing): paint at once from the agent's last snapshot, then poll every
    /// 90 s while the app is in front — a return refetches at once.
    public func start(agentId id: String) {
        let previous: String? = lock.sync { let p = agentId; agentId = id; lastFetch = 0; return p }
        if previous == id { return }
        if previous != nil {
            // Someone else signed in without a sign-out in between: nothing of theirs stays.
            read.cancel()
            orders.value = []
        }
        if let cached: [Order] = snapshots.read(id, Self.SNAPSHOT_KEY) { orders.value = cached }
        startPolling()
    }

    /// Sign-out: the polls, the read on the wire and the list go.
    public func stop() {
        lock.sync { agentId = nil; lastFetch = 0 }
        stopPolling()
        read.cancel()
        kick.cancel()
        orders.value = []
    }

    /// Refetch and return when the list has landed; throws on failure (pull-to-refresh spinners, reconcile reads).
    public func refreshOrders() async throws { try await read.run() }

    /// Refetch in the background; a failure keeps what is on screen.
    public func refetchOrders() { Task { [weak self] in _ = try? await self?.refreshOrders() } }

    private func fetchNow() async throws {
        guard let who: String = lock.sync({ agentId }) else { throw CancellationError() }
        let list = try await api.orders.list()
        try Task.checkCancellation()
        // Only the agent who asked gets the answer painted.
        guard lock.sync({ agentId == who }) else { return }
        lock.sync { lastFetch = clock() }
        orders.value = list
        snapshots.write(who, Self.SNAPSHOT_KEY, list)
    }

    private func startPolling() {
        stopPolling()
        let every = Self.POLL_MS, sleep = self.sleep, fg = foreground
        let t = Task { [weak self] in
            while !Task.isCancelled {
                guard let self = self else { return }
                await quietly { try await self.refreshOrders() }
                // Wait out the interval — unless the app leaves and comes back
                // meanwhile, which refetches at once.
                let returned = await Self.leftAndCameBack(fg, within: every, sleep: sleep)
                if Task.isCancelled { return }
                if !returned && !fg.value { await await_(fg, equals: true) }
            }
        }
        lock.sync { pollTask = t }
    }

    /// `withTimeoutOrNull(ms) { fg.first { !it }; fg.first { it } }`: true when the
    /// app left and came back before `ms` passed.
    static func leftAndCameBack(_ fg: Watched<Bool>, within ms: Int64, sleep: @escaping Sleeper) async -> Bool {
        await withTaskGroup(of: Bool.self) { group in
            group.addTask { _ = try? await sleep(ms); return false }
            group.addTask {
                await await_(fg, equals: false)
                if Task.isCancelled { return false }
                await await_(fg, equals: true)
                return !Task.isCancelled
            }
            let first = await group.next() ?? false
            group.cancelAll()
            return first
        }
    }

    private func stopPolling() {
        let t: Task<Void, Never>? = lock.sync { let p = pollTask; pollTask = nil; return p }
        t?.cancel()
    }

    public func close() {
        stop()
        lock.sync { subs.forEach { $0.cancel() }; subs = [] }
    }

    deinit { close() }
}
