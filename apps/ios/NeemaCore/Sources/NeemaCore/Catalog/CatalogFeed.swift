import Foundation

/// The dashboard's catalogue (the catalog part of Android's
/// `DashboardViewModel`): the hub's products, read once at sign-in from this
/// agent's snapshot and then every five minutes while the app is in front —
/// one GET on the wire at a time, shared by the poll, a pull-to-refresh and
/// a return to the catalog screen.
public final class CatalogFeed: @unchecked Sendable {
    public static let POLL_MS: Int64 = 300_000
    public static let SNAPSHOT_KEY = "catalog"

    public let catalog: Watched<[CatalogItem]>
    private let api: NeemaApi
    private let foreground: Watched<Bool>
    private let snapshots: SnapshotCache
    private let sleep: Sleeper
    private let lock = NSLock()
    private var read: SingleFlight<Void>!
    private var pollTask: Task<Void, Never>?
    private var agentId: String?

    public init(api: NeemaApi, foreground: Watched<Bool>, snapshots: SnapshotCache,
                catalog: Watched<[CatalogItem]> = Watched<[CatalogItem]>([]), sleep: @escaping Sleeper = realSleep) {
        self.api = api
        self.foreground = foreground
        self.snapshots = snapshots
        self.catalog = catalog
        self.sleep = sleep
        read = SingleFlight { [weak self] in try await self?.fetchNow() }
    }

    public var signedIn: Bool { lock.sync { agentId != nil } }
    /// A read of the catalogue is on the wire.
    public var reading: Bool { read.inFlight }

    /// Sign-in, keyed by who: paint from the agent's last snapshot, then poll.
    public func start(agentId id: String) {
        let previous: String? = lock.sync { let p = agentId; agentId = id; return p }
        if previous == id { return }
        if previous != nil {
            read.cancel()
            catalog.value = []
        }
        if let cached: [CatalogItem] = snapshots.read(id, Self.SNAPSHOT_KEY) { catalog.value = cached }
        stopPolling()
        let t = Polling.loop(every: Self.POLL_MS, foreground: foreground, sleep: sleep) { [weak self] in
            guard let self = self else { return }
            await quietly { try await self.refreshCatalog() }
        }
        lock.sync { pollTask = t }
    }

    public func stop() {
        lock.sync { agentId = nil }
        stopPolling()
        read.cancel()
        catalog.value = []
    }

    /// Refetch and return when the list has landed; throws on failure.
    public func refreshCatalog() async throws { try await read.run() }

    /// Refetch in the background; a failure keeps what is on screen.
    public func refetchCatalog() { Task { [weak self] in _ = try? await self?.refreshCatalog() } }

    private func fetchNow() async throws {
        guard let who: String = lock.sync({ agentId }) else { throw CancellationError() }
        let list = try await api.catalog.list()
        try Task.checkCancellation()
        guard lock.sync({ agentId == who }) else { return }
        catalog.value = list
        snapshots.write(who, Self.SNAPSHOT_KEY, list)
    }

    private func stopPolling() {
        let t: Task<Void, Never>? = lock.sync { let p = pollTask; pollTask = nil; return p }
        t?.cancel()
    }

    deinit { stop() }
}
