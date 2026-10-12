import Foundation

/// The shell as the catalog screen sees it: the shared catalogue feed, the API and the toasts.
public protocol CatalogHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var catalog: Watched<[CatalogItem]> { get }
    var api: NeemaApi { get }
    /// Refetch the catalogue and return when it has landed; throws on failure.
    func refreshCatalog() async throws
    func toast(_ message: String, _ type: ToastType)
}

/// The catalog screen's own state (the list is the host's).
public struct CatalogUi: Equatable, Sendable {
    public var filter = "all"
    public var search = ""
    public var audit: PriceAudit? = nil
    public var auditOpen = false
    public var refreshing = false
    /// Why the catalogue couldn't be read, when this screen asked and failed;
    /// nil once it arrives. With nothing to show the screen says this (and
    /// offers Retry) instead of "No items found", which would be untrue.
    public var catalogError: String? = nil
    public init() {}
}

/// Catalog state (Android `CatalogViewModel`). The list itself is the host's
/// shared, polled catalogue; this holds the filters and the price audit. Like
/// the web view it is READ-ONLY: products, prices and stock live in the hub,
/// the single source of truth — nothing is written from here.
@MainActor
public final class CatalogViewModel {
    public let host: CatalogHost
    public let state = Watched<CatalogUi>(CatalogUi())
    /// The catalogue itself is the host's 5-minute poll (paused in the
    /// background, refetched on return). The price audit is CatalogView's
    /// mount-time read: each return to this screen reads it again, as a
    /// remount of the web view does, and the catalogue with it.
    public private(set) var life: ScreenLife!
    private var jobs: [UUID: Job] = [:]
    private var subs: [Subscription] = []
    private var closed = false
    public var uiAttached = false
    /// The catalogue indexed once per poll (not once per keystroke).
    private var index: CatalogIndex
    private var indexStale = false

    public init(host: CatalogHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        index = CatalogIndex(host.catalog.value)
        life = ScreenLife(foreground: host.foreground, catchUpOnForeground: false, sleep: sleep) { [weak self] in
            guard let self = self else { return }
            async let audit: Void = self.loadAudit()
            async let catalog: Error? = self.loadCatalog()
            _ = await (audit, catalog)
        }
        launch { [weak self] in await self?.loadAudit() }
        // The host read the catalogue at sign-in; if that failed (a phone
        // offline at start) the list is empty until its 5-minute poll — ask now.
        if host.catalog.value.isEmpty { launch { [weak self] in _ = await self?.loadCatalog() } }
        var first = true
        subs.append(host.catalog.observe { [weak self] list in
            if first { first = false; return }
            onMain {
                guard let self = self else { return }
                self.indexStale = true
                // Any successful read (the host's poll included) clears the notice.
                if !list.isEmpty { self.mut { $0.catalogError = nil } }
            }
        })
    }

    public var ui: CatalogUi { state.value }

    private func mut(_ f: (inout CatalogUi) -> Void) {
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

    /// The grid's contents: filtered from the index, which follows the host's list.
    public var view: CatalogView {
        if indexStale { index = CatalogIndex(host.catalog.value); indexStale = false }
        return index.view(filter: ui.filter, search: ui.search)
    }

    public func setFilter(_ f: String) { mut { $0.filter = f } }
    public func setSearch(_ q: String) { mut { $0.search = q } }
    public func setAuditOpen(_ open: Bool) { mut { $0.auditOpen = open } }
    public func toggleAudit() { mut { $0.auditOpen.toggle() } }

    // ── The app reclaimed: the search, the category and the audit's open state come back ──

    public func saveUi() -> [String: JSONValue] {
        ["filter": .string(ui.filter), "search": .string(ui.search), "audit": .bool(ui.auditOpen)]
    }

    public func restoreUi(_ saved: [String: JSONValue]) {
        mut { s in
            if let f = saved["filter"]?.stringValue { s.filter = f }
            if let q = saved["search"]?.stringValue { s.search = q }
            if let a = saved["audit"] { s.auditOpen = a.boolValue ?? (a.content == "true") }
        }
    }

    @discardableResult
    public func restoreIfFresh(_ saved: [String: JSONValue]?) -> Bool {
        if uiAttached { return false }
        uiAttached = true
        guard let s = saved else { return false }
        restoreUi(s)
        return true
    }

    // ── Reads ────────────────────────────────────────────────────────────────

    /// The empty state's Retry.
    public func retry() { refresh() }

    /// The shared catalogue, remembering why it failed; answers the failure.
    private func loadCatalog() async -> Error? {
        do {
            try await host.refreshCatalog()
            if closed { return nil }
            mut { $0.catalogError = nil }
            return nil
        } catch {
            if closed || SalesErrors.isCancellation(error) { return nil }
            mut { $0.catalogError = FriendlyErrors.text(of: error, fallback: "The server couldn't send the catalogue just now.") }
            return error
        }
    }

    /// GET /admin/catalog/audit (admin.py `catalog_price_audit`). A failed
    /// audit just stays hidden, as on the web; a failed refresh keeps the
    /// banner already shown.
    private func loadAudit() async {
        if let a = try? await host.api.catalog.audit(), !closed { mut { $0.audit = a } }
    }

    /// Pull-to-refresh: the audit and the shared catalogue, the spinner lasting until both have landed (or failed).
    public func refresh() {
        if ui.refreshing { return }
        // Raised at once (not inside the task): a second pull before the task starts is ignored too.
        mut { $0.refreshing = true }
        launch { [weak self] in
            guard let self = self else { return }
            async let audit: Void = self.loadAudit()
            async let catalog: Error? = self.loadCatalog()
            let (_, failed) = await (audit, catalog)
            if self.closed { return }
            // With products on screen they stay; the pull just says it didn't reach the hub.
            if let f = failed, !self.host.catalog.value.isEmpty {
                self.host.toast("Couldn't refresh the catalogue. \(FriendlyErrors.text(of: f))", .error)
            }
            self.mut { $0.refreshing = false }
        }
    }

    public func close() {
        if closed { return }
        closed = true
        life.close()
        subs.forEach { $0.cancel() }
        subs = []
        for j in jobs.values { j.cancel() }
        jobs = [:]
    }
}
