import Foundation

/// The shell as the orders screen sees it (Android's `DashboardViewModel` for
/// `OrdersViewModel`): the orders feed, the API and the toasts.
public protocol OrdersHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var socketConnected: Watched<Bool> { get }
    /// The dashboard's polled list — the screen's own state is the filter, search, page and open order.
    var orders: Watched<[Order]> { get }
    var api: NeemaApi { get }
    /// Refetch the list and return when it has landed; throws on failure.
    func refreshOrders() async throws
    /// Refetch in the background; a failure keeps what is on screen.
    func refetchOrders()
    func toast(_ message: String, _ type: ToastType)
}

/// Where a list was scrolled: its first visible row and the offset into it.
public struct ScrollPos: Equatable, Sendable, Codable {
    public var index: Int
    public var offset: Int
    public init(_ index: Int = 0, _ offset: Int = 0) { self.index = index; self.offset = offset }
}

/// OrdersView's local state, in one watched value.
public struct OrdersUi: Equatable, Sendable {
    /// "all" or one of `OrderUi.ORDER_STATUSES`.
    public var filter = "all"
    public var search = ""
    public var page = 1
    /// The open order's id — the sheet re-reads the live row so a refetch shows through.
    public var selectedId: String? = nil
    /// The row whose status change is on the wire.
    public var updating: String? = nil
    public var refreshing = false
    /// True only while the very first fetch is in flight with nothing cached —
    /// otherwise an empty list on first paint would claim "No orders found".
    public var initialLoading = true
    /// Why the last read of the list failed (nil when it worked). With orders
    /// on screen it is a banner over them; with none it replaces "No orders
    /// found", which would be a lie. The dashboard's poller keeps trying, and
    /// any good answer clears it.
    public var loadError: String? = nil
    /// A scroll restored after the app was reclaimed, applied by the screen once the orders are in.
    public var pendingScroll: ScrollPos? = nil
    public init() {}
}

/// OrdersView's state and actions (Android `feature/orders/OrdersViewModel`).
/// The orders themselves are the host's polled list; this holds the filter,
/// search, page, the open order, which row is mid-update and why the last
/// read failed.
@MainActor
public final class OrdersViewModel {
    nonisolated public static let PAGE_SIZE = 15

    public let host: OrdersHost
    public let state: Watched<OrdersUi>
    /// The list is the host's 90 s poll, which already pauses in the
    /// background and refetches on return. On top of that, while this screen
    /// is on display: coming back to it re-reads the orders, and so does the
    /// live socket reconnecting — an `order_update` sent while it was down is
    /// lost, and the pending badge must not wait 90 s to catch up.
    public private(set) var life: ScreenLife!
    /// This screen's reads of the list, one on the wire at a time: a pull, a
    /// Retry, a catch-up on return and the settle after a status change that
    /// pile up on a slow network share one round trip instead of stacking.
    private var reads: SingleFlight<Bool>!
    private var jobs: [UUID: Job] = [:]
    private var subs: [Subscription] = []
    private var closed = false
    /// The screen has drawn this model: a state saved before it must not replay over what was typed since.
    public var uiAttached = false
    /// The list's scroll (first visible row, its offset), kept current by the screen.
    public var scroll = ScrollPos()

    public init(host: OrdersHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        var ui = OrdersUi()
        ui.initialLoading = host.orders.value.isEmpty
        state = Watched(ui)
        reads = SingleFlight { [weak self] () async throws -> Bool in
            guard let self = self else { return false }
            return await self.readOnce()
        }
        life = ScreenLife(foreground: host.foreground, connected: host.socketConnected, catchUpOnForeground: false, sleep: sleep) { [weak self] in
            guard let self = self else { return }
            _ = await self.awaitRefetch()
        }
        if host.orders.value.isEmpty {
            launch { [weak self] in
                guard let self = self else { return }
                _ = await self.awaitRefetch()
                self.mut { $0.initialLoading = false }
            }
        }
        // A good read from anywhere (the host's own poll included) clears the error.
        var first = true
        subs.append(host.orders.observe { [weak self] _ in
            if first { first = false; return }
            onMain { self?.mut { $0.loadError = nil } }
        })
    }

    public var ui: OrdersUi { state.value }

    private func mut(_ f: (inout OrdersUi) -> Void) {
        var s = state.value
        f(&s)
        state.update(s)
    }

    @discardableResult
    private func launch(_ body: @escaping @MainActor () async -> Void) -> Job? {
        if closed { return nil }
        let id = UUID()
        let job = Job { [weak self] in
            await body()
            self?.jobs[id] = nil
        }
        jobs[id] = job
        return job
    }

    public func setFilter(_ f: String) { mut { $0.filter = f; $0.page = 1 } }
    /// Tapping the active status card clears it (the web's toggle).
    public func toggleFilter(_ f: String) { setFilter(ui.filter == f ? "all" : f) }
    public func setSearch(_ q: String) { mut { $0.search = q; $0.page = 1 } }
    public func setPage(_ p: Int) { mut { $0.page = p } }
    public func select(_ order: Order?) { mut { $0.selectedId = order?.id } }
    public func select(id: String?) { mut { $0.selectedId = id } }

    /// Whether the list has been read at least once (so an open order missing from it is really gone).
    public var loaded: Bool { !host.orders.value.isEmpty || (!ui.initialLoading && ui.loadError == nil) }

    /// The open order's live row, if it is still in the list.
    public var selected: Order? { ui.selectedId.flatMap { id in host.orders.value.first { $0.id == id } } }

    // ── The app reclaimed: the filter, search, page and the open order come back ──

    public func scrollRestored() { mut { $0.pendingScroll = nil } }

    /// What the scene keeps across a reclaim (JSON-safe values only).
    public func saveUi() -> [String: JSONValue] {
        // Not applied yet (the orders are still loading): that is still where the agent was.
        let at = ui.pendingScroll ?? scroll
        return [
            "filter": .string(ui.filter), "search": .string(ui.search), "page": .number(Double(ui.page)),
            "selected": ui.selectedId.map { .string($0) } ?? .null,
            "scrollIndex": .number(Double(at.index)), "scrollOffset": .number(Double(at.offset)),
        ]
    }

    public func restoreUi(_ saved: [String: JSONValue]) {
        mut { s in
            if let f = saved["filter"]?.stringValue, f == "all" || OrderUi.ORDER_STATUSES.contains(f) { s.filter = f }
            if let q = saved["search"]?.stringValue { s.search = q }
            if let p = saved["page"]?.lenientDouble { s.page = max(1, Int(p)) }
            s.selectedId = saved["selected"]?.stringValue
        }
        let index = max(0, Int(saved["scrollIndex"]?.lenientDouble ?? 0))
        let offset = max(0, Int(saved["scrollOffset"]?.lenientDouble ?? 0))
        if index > 0 || offset > 0 {
            scroll = ScrollPos(index, offset)
            mut { $0.pendingScroll = ScrollPos(index, offset) }
        }
    }

    /// The screen's first frame restores the scene's saved state — but only onto
    /// a model no frame has drawn yet: after a rotation the model is the same
    /// one the agent typed on since the save, and the stale copy must not win.
    @discardableResult
    public func restoreIfFresh(_ saved: [String: JSONValue]?) -> Bool {
        if uiAttached { return false }
        uiAttached = true
        guard let s = saved else { return false }
        restoreUi(s)
        return true
    }

    // ── Reads ────────────────────────────────────────────────────────────────

    public func refresh() {
        if ui.refreshing { return }
        launch { [weak self] in
            guard let self = self else { return }
            self.mut { $0.refreshing = true }
            _ = await self.awaitRefetch()
            self.mut { $0.refreshing = false }
        }
    }

    /// The error state's Retry: the first load again, with its spinner.
    public func retry() {
        if ui.initialLoading || ui.refreshing { return }
        launch { [weak self] in
            guard let self = self else { return }
            self.mut { $0.initialLoading = true }
            _ = await self.awaitRefetch()
            self.mut { $0.initialLoading = false }
        }
    }

    /// Refetch through the host and return when the round trip is over. A
    /// failure keeps the list as it was and says why; true when it worked.
    private func awaitRefetch() async -> Bool { (try? await reads.run()) ?? false }

    private func readOnce() async -> Bool {
        do {
            try await host.refreshOrders()
            if closed { return false }
            mut { $0.loadError = nil }
            return true
        } catch {
            if closed || SalesErrors.isCancellation(error) { return false }
            mut { $0.loadError = SalesErrors.failure(of: error).message() }
            return false
        }
    }

    // ── Status moves ─────────────────────────────────────────────────────────

    /// PATCH the order's status. The web toasts "Failed to update order" on any
    /// throw; on a phone network that is often a lie — the PATCH can land and
    /// its answer be lost — so a failure that may have happened is settled by
    /// re-reading the list: the order's real status decides what is said. A
    /// 404 means someone deleted it: the list is re-read (the row goes) and the
    /// sheet closes. On any other failure the sheet stays open for another tap.
    public func updateStatus(id: String, status: String) {
        if ui.updating != nil { return }
        mut { $0.updating = id }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.updating = nil } }
            do {
                _ = try await self.host.api.orders.updateStatus(id: id, status: status)
                if self.closed || Task.isCancelled { return }
                self.host.refetchOrders()
                if self.ui.selectedId == id { self.mut { $0.selectedId = nil } }
                self.host.toast("Order marked as \(status)", .success)
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                let f = SalesErrors.failure(of: error)
                switch f.kind {
                case .notFound:
                    self.host.toast("This order no longer exists — it may have been deleted", .error)
                    _ = await self.awaitRefetch()
                    if self.ui.selectedId == id { self.mut { $0.selectedId = nil } }
                case _ where f.mayHaveHappened:
                    let read = await self.awaitRefetch()
                    if self.closed { return }
                    let now = self.host.orders.value.first { $0.id == id }
                    if read && now?.status == status {
                        if self.ui.selectedId == id { self.mut { $0.selectedId = nil } }
                        self.host.toast("Order marked as \(status)", .success)
                    } else if read {
                        self.host.toast("Order not updated — \(SalesErrors.lowerFirst(f.message()))", .error)
                    } else {
                        self.host.toast("No answer from the server — the order may not have updated. Pull down to check.", .error)
                    }
                // The session-expired dialog says so; the sheet waits for a retry after sign-in.
                case .sessionExpired:
                    break
                default:
                    self.host.toast("Failed to update order — \(SalesErrors.lowerFirst(f.message()))", .error)
                }
            }
        }
    }

    /// The screen is gone for good (sign-out): stop listening and give up the work in flight.
    public func close() {
        if closed { return }
        closed = true
        life.close()
        subs.forEach { $0.cancel() }
        subs = []
        for j in jobs.values { j.cancel() }
        jobs = [:]
        reads.cancel()
    }
}
