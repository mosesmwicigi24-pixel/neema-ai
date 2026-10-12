import Foundation

/// The shell as the Analytics screen sees it: the dashboard's orders, team
/// and catalogue (the cards' fallbacks and the feed), the socket, the API and the toasts.
public protocol OverviewHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var socketConnected: Watched<Bool> { get }
    var socketEvents: Signal<JSONValue> { get }
    var orders: Watched<[Order]> { get }
    var agents: Watched<[Agent]> { get }
    var catalog: Watched<[CatalogItem]> { get }
    var api: NeemaApi { get }
    /// Refetch and return when it has landed; throws on failure.
    func refreshOrders() async throws
    func refreshAgents() async throws
    func refreshCatalog() async throws
    func toast(_ message: String, _ type: ToastType)
}

/// OverviewView's state, in one watched value.
public struct OverviewUi: Equatable, Sendable {
    /// The server's headline counts (GET /admin/stats); nil until read, or when every read failed.
    public var stats: Stats? = nil
    public var statsLoading = true
    /// Why the server's headline counts couldn't be read, while the cards show
    /// the phone's own estimate instead; nil once they arrive.
    public var statsError: String? = nil
    public var attrib: Attribution? = nil
    /// The latest human-held threads (server-side "human" tab, 10 rows).
    public var humanRows: [Conversation]? = nil
    /// The web falls back to the inbox's loaded rows when /stats fails. The
    /// phone has no such rows here, so it fetches the inbox's first page —
    /// only when stats could not be loaded.
    public var fallbackConvs: [Conversation] = []
    public var refreshing = false
    public init() {}
}

/// State for the Analytics (overview) screen (Android `OverviewViewModel`).
/// Headline counts come from the server (GET /admin/stats, counted by the
/// database); attribution from GET /admin/attribution; human-held threads
/// from the inbox's "human" tab — the web's OverviewView does exactly these
/// three calls and polls stats and intercepts every 30 s while visible.
@MainActor
public final class OverviewViewModel {
    /// OverviewView's interval.
    nonisolated public static let POLL_MS: Int64 = 30_000
    /// Notifications after which a headline figure has moved.
    nonisolated public static let RELOAD_ON: Set<String> = [
        "order_update", "new_conversation", "human_transfer", "media_escalation",
        "intercept", "transfer", "system", "take_back", "hub_event",
    ]

    public let host: OverviewHost
    public let state = Watched<OverviewUi>(OverviewUi())
    /// OverviewView loads on mount and re-reads stats and intercepts every 30 s
    /// while the tab is visible. Here: only while this screen is on display and
    /// the app in front; every return to it (or to the app) and every socket
    /// reconnect reloads all three quietly — no spinner, figures kept on failure.
    public private(set) var life: ScreenLife!
    /// A live event moved a headline figure: re-read stats and intercepts (800 ms, coalesced).
    private var onEvent: Coalescer!
    private var jobs: [UUID: Job] = [:]
    private var subs: [Subscription] = []
    private var closed = false
    /// Held while a stats + intercepts read is in flight.
    private var liveBusy = false

    public init(host: OverviewHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        life = ScreenLife(foreground: host.foreground, connected: host.socketConnected, pollMs: Self.POLL_MS, sleep: sleep,
                          poll: { [weak self] in await self?.loadLive() }, catchUp: { [weak self] in await self?.catchUp() })
        onEvent = Coalescer(windowMs: Coalescer.EVENT_WINDOW_MS, sleep: sleep) { [weak self] in await self?.loadLive() }
        launch { [weak self] in _ = await self?.loadAll() }
        // Notifications that change the open / human / AI / order counts: the
        // web refetches only its orders list on `order_update` and leaves the
        // figures to the 30 s poll; here they follow at once while on display
        // (off-screen, the next visit reloads anyway). A thread changing hands
        // (intercept / release / transfer) moves the human and AI counts and
        // the "Human intercepts" feed.
        subs.append(host.socketEvents.observe { [weak self] e in
            let alert = e.str("event") == "notification" && Self.RELOAD_ON.contains(e.str("type") ?? "")
            let handsChanged = e.str("type") == "intercept_changed"
            guard alert || handsChanged else { return }
            onMain { [weak self] in self?.figuresMoved() }
        })
        // The dashboard's orders poll found a change (the pending badge moved):
        // keep the order figures in step with it.
        var primed = false
        subs.append(host.orders.observe { [weak self] _ in
            if !primed { primed = true; return }
            onMain { [weak self] in self?.figuresMoved() }
        })
    }

    public var ui: OverviewUi { state.value }

    private func mut(_ f: (inout OverviewUi) -> Void) {
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

    private func figuresMoved() {
        guard !closed, life.active else { return }
        onEvent.kick()
    }

    // ── Reads ────────────────────────────────────────────────────────────────

    /// The poll's pair: server stats and the human-held threads. Single-flight:
    /// the 30 s poll, an event and a return to the screen landing together
    /// cost one pair of requests — a caller arriving while one is in flight
    /// relies on it rather than stacking a second.
    private func loadLive() async {
        if liveBusy { return }
        liveBusy = true
        defer { liveBusy = false }
        async let s: Void = loadStatsQuietly()
        async let h: Void = loadHuman()
        _ = await (s, h)
    }

    /// A return to the screen: the mount-time three, without the first-load spinner.
    private func catchUp() async {
        async let l: Void = loadLive()
        async let a: Void = loadAttribution()
        _ = await (l, a)
    }

    /// The poll's stats read: a failure keeps the figures on screen (a 403 re-reads this agent's access in the HTTP layer).
    private func loadStatsQuietly() async {
        if let s = try? await host.api.stats.overview(), !closed { mut { $0.stats = s; $0.statsError = nil } }
    }

    /// Loads everything; answers why the headline figures failed, or nil.
    @discardableResult
    private func loadAll() async -> Error? {
        mut { $0.statsLoading = true }
        var failed: Error? = nil
        do {
            let s = try await host.api.stats.overview()
            if closed { return nil }
            mut { $0.stats = s; $0.statsError = nil }
        } catch {
            if closed || SalesErrors.isCancellation(error) { return nil }
            failed = error
        }
        if let e = failed, ui.stats == nil {
            // A failed pull-to-refresh keeps the figures already on screen
            // (like the web's 30 s poll); only a first load falls back — and,
            // unlike the web, says the cards are an estimate, and why.
            mut { $0.statsError = FriendlyErrors.text(of: e, fallback: "The server couldn't count them just now.") }
            await loadFallback()
        }
        if closed { return failed }
        mut { $0.statsLoading = false }
        await loadAttribution()
        await loadHuman()
        // The web's feed reads `humanRows ?? conversations`: with no human tab,
        // the intercepts come from the inbox's own rows.
        if !closed && ui.humanRows == nil && ui.fallbackConvs.isEmpty { await loadFallback() }
        return failed
    }

    /// A failed read stays hidden, as on the web (a 403 re-reads this agent's access).
    private func loadAttribution() async {
        if let a = try? await host.api.attribution(), !closed { mut { $0.attrib = a } }
    }

    private func loadFallback() async {
        if let p = try? await host.api.conversations.page(InboxQuery(), limit: 50), !closed { mut { $0.fallbackConvs = p.items } }
    }

    private func loadHuman() async {
        if let p = try? await host.api.conversations.page(InboxQuery(tab: "human"), limit: 10), !closed { mut { $0.humanRows = p.items } }
    }

    /// Pull-to-refresh (and the notice's Retry): the three calls, plus the
    /// orders, team and catalogue the fallbacks read — the spinner lasts until
    /// all land. A refresh that couldn't reach the server says so; the
    /// figures already on screen stay.
    public func refresh() {
        if ui.refreshing { return }
        mut { $0.refreshing = true }
        launch { [weak self] in
            guard let self = self else { return }
            async let o: Void = quietly { try await self.host.refreshOrders() }
            async let a: Void = quietly { try await self.host.refreshAgents() }
            async let c: Void = quietly { try await self.host.refreshCatalog() }
            let failed = await self.loadAll()
            _ = await (o, a, c)
            if self.closed { return }
            self.mut { $0.refreshing = false }
            if let e = failed, self.ui.stats != nil {
                self.host.toast("Couldn't refresh the figures. \(FriendlyErrors.text(of: e))", .error)
            }
        }
    }

    public func close() {
        if closed { return }
        closed = true
        life.close()
        onEvent.cancel()
        for s in subs { s.cancel() }
        subs = []
        for j in jobs.values { j.cancel() }
        jobs = [:]
    }
}
