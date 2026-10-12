import Foundation

/// The shell as the Reports screen sees it: the dashboard's orders and team
/// (the report is built from them too), the API and the toasts.
public protocol ReportsHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var orders: Watched<[Order]> { get }
    var agents: Watched<[Agent]> { get }
    var api: NeemaApi { get }
    /// Refetch and return when it has landed; throws on failure.
    func refreshOrders() async throws
    func refreshAgents() async throws
    func toast(_ message: String, _ type: ToastType)
}

/// ReportsView's state, in one watched value.
public struct ReportsUi: Equatable, Sendable {
    /// nil while loading — never show zeros that look like real figures.
    public var allConvs: [Conversation]? = nil
    public var refreshing = false
    /// Why the last download failed, in plain words; nil once one succeeds.
    /// With no list yet the screen shows it with a Retry button instead of a
    /// report of zeros (the web falls back to an empty list, so a failed
    /// download there reads "0 conversations" as if it were true).
    public var loadError: String? = nil
    public var tab: ReportTab = .overview
    public var range: ReportRange = .d30
    public var customFrom: LocalDay? = nil
    public var customTo: LocalDay? = nil
    /// The phone's date. The web recomputes "now" on every render; here the
    /// report is rebuilt when its inputs change, so the date is one of them:
    /// re-read at each local midnight while the app is in front, and at once
    /// on coming back to it — a report left open overnight rolls its "last 7
    /// days" window and its per-day bars over to the new day.
    public var today: LocalDay
    /// The report for the chosen range, built off the main thread; nil until
    /// the first one is ready (the screen shows its loading state, never zeros).
    public var report: Report? = nil
    /// A CSV is being written: a second tap doesn't start another.
    public var exporting = false
    /// The CSV the share sheet should open with, until the screen has opened
    /// it (`exportShown`). Held here rather than passed to a callback so an
    /// export that finishes while the phone rotates, or while the app is in
    /// the background, still reaches the share sheet.
    public var readyExport: ReadyExport? = nil
    /// The app was closed by the system while a CSV was being written: nothing
    /// reached the share sheet. The screen tells the agent once.
    public var exportInterrupted = false
    public init(today: LocalDay) { self.today = today }
}

/// Reports aggregate a date range over EVERY conversation, so — like the web —
/// this screen fetches the full (un-paged) list itself, only while it is open.
/// Computing from the inbox's loaded rows would report on one page.
///
/// The list runs to ~14,000 rows, so nothing is aggregated on the screen's
/// thread: each row's timestamp is parsed once when the list lands, and the
/// report for the chosen range is built off the main actor; changing the
/// range keeps the last report on screen until the new one is ready
/// (Android `ReportsViewModel`).
@MainActor
public final class ReportsViewModel {
    /// What the agent is told when the app was closed mid-export.
    nonisolated public static let EXPORT_INTERRUPTED = "iOS closed Neema while the CSV was being prepared — tap Export CSV again."

    public let host: ReportsHost
    public let state: Watched<ReportsUi>
    /// ReportsView fetches the full list on mount — once per visit, never on a
    /// timer (it is ~13 MB). This model outlives the screen, so each return to
    /// it re-reads the list once (joining a download already in flight), the
    /// report keeping its figures until the new list lands. No poll, and no
    /// reload on returning to the app: the web doesn't either.
    public private(set) var life: ScreenLife!
    private let sleep: Sleeper
    private var jobs: [UUID: Job] = [:]
    private var subs: [Subscription] = []
    private var closed = false
    public var uiAttached = false
    /// Every conversation with its date parsed once (not once per range change).
    private var datedConvs: [Dated<Conversation>]? = nil
    private var datedOrders: [Dated<Order>] = []
    /// The download in flight: a pull-to-refresh joins it rather than starting a second full list.
    private var fetchTask: Task<Void, Never>?
    private var fetching = false
    private var buildTask: Task<Void, Never>?
    private var buildGen = 0
    /// How many reports have been built (a rebuild only when an input changed).
    public private(set) var builds = 0
    private var midnight: Job?

    private var zone: TimeZone { Fmt.timeZone }

    public init(host: ReportsHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        self.sleep = sleep
        state = Watched(ReportsUi(today: LocalDay.today(zone: Fmt.timeZone)))
        life = ScreenLife(foreground: host.foreground, catchUpOnForeground: false, sleep: sleep, catchUp: { [weak self] in await self?.joinLoad() })
        datedOrders = ReportsRules.datedOrders(host.orders.value)
        _ = load()
        var firstOrders = true
        subs.append(host.orders.observe { [weak self] list in
            if firstOrders { firstOrders = false; return }
            onMain { [weak self] in
                guard let self = self, !self.closed else { return }
                self.datedOrders = ReportsRules.datedOrders(list)
                self.rebuild()
            }
        })
        var firstAgents = true
        subs.append(host.agents.observe { [weak self] _ in
            if firstAgents { firstAgents = false; return }
            onMain { [weak self] in self?.rebuild() }
        })
        // The midnight roll-over (see `today`): checked at the next local
        // midnight, and at least hourly so a changed clock or time zone is
        // caught; nothing ticks while the app is in the background.
        subs.append(host.foreground.observe { [weak self] fg in
            onMain { [weak self] in
                guard let self = self, !self.closed else { return }
                if fg { self.startMidnightTicker() } else { self.midnight?.cancel(); self.midnight = nil }
            }
        })
    }

    public var ui: ReportsUi { state.value }

    private func mut(_ f: (inout ReportsUi) -> Void) {
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

    // ── The date ─────────────────────────────────────────────────────────────

    private func refreshToday() {
        let t = LocalDay.today(zone: zone)
        if t != ui.today {
            mut { $0.today = t }
            rebuild()
        }
    }

    private func startMidnightTicker() {
        midnight?.cancel()
        midnight = launch { [weak self] in
            guard let self = self else { return }
            while !self.closed && self.host.foreground.value {
                self.refreshToday()
                let now = AppClock.now()
                let next = LocalDay.of(millis: now, zone: self.zone).plusDays(1).startMillis(zone: self.zone)
                let wait = min(max(next - now + 1, 1), 3_600_000)
                do { try await self.sleep(wait) } catch { return }
            }
        }
    }

    // ── The download ─────────────────────────────────────────────────────────

    @discardableResult
    private func load() -> Task<Void, Never> {
        if fetching, let t = fetchTask { return t }
        fetching = true
        let t = Task { @MainActor [weak self] in
            guard let self = self else { return }
            await self.fetch()
            self.fetching = false
        }
        fetchTask = t
        return t
    }

    private func joinLoad() async { await load().value }

    private func fetch() async {
        do {
            let list = try await ReportsRules.fetchEveryConversation(host.api.http)
            if closed { return }
            let dated = await Task.detached(priority: .userInitiated) { ReportsRules.datedConversations(list) }.value
            if closed { return }
            datedConvs = dated
            mut { $0.allConvs = list; $0.loadError = nil }
            rebuild()
        } catch {
            if closed || SalesErrors.isCancellation(error) { return }
            // A refresh keeps the report already on screen and says so (the
            // web's toast); a first load shows the reason with a Retry button
            // — never a report of zeros.
            mut { $0.loadError = ReportsRules.loadErrorText(error) }
            if ui.allConvs != nil { host.toast("Could not load conversations for this report.", .error) }
        }
    }

    /// The error panel's Retry: back to the loading state, then download again.
    public func retry() {
        if fetching { return }
        mut { $0.loadError = nil }
        load()
    }

    /// Re-read the orders and agents the report is built from, and every conversation; the spinner lasts until all have landed.
    public func refresh() {
        if ui.refreshing { return }
        mut { $0.refreshing = true }
        launch { [weak self] in
            guard let self = self else { return }
            async let o: Void = quietly { try await self.host.refreshOrders() }
            async let a: Void = quietly { try await self.host.refreshAgents() }
            await self.joinLoad()
            _ = await (o, a)
            if self.closed { return }
            self.mut { $0.refreshing = false }
        }
    }

    // ── The report ───────────────────────────────────────────────────────────

    /// Rebuild the report for the inputs as they are now, off the main actor;
    /// an older build still running is dropped (the newest inputs win).
    private func rebuild() {
        guard let convs = datedConvs else { return }
        buildGen += 1
        let gen = buildGen
        let orders = datedOrders, agents = host.agents.value
        let range = ui.range, from = ui.customFrom, to = ui.customTo
        let now = AppClock.now(), zone = self.zone
        buildTask?.cancel()
        buildTask = Task.detached(priority: .userInitiated) { [weak self] in
            let r = ReportsRules.buildReportDated(convs, orders: orders, agents: agents, range: range, customFrom: from, customTo: to, now: now, zone: zone)
            if Task.isCancelled { return }
            await MainActor.run { [weak self] in
                guard let self = self, !self.closed, gen == self.buildGen else { return }
                self.builds += 1
                self.mut { $0.report = r }
            }
        }
    }

    public func setTab(_ t: ReportTab) { mut { $0.tab = t } }

    public func setRange(_ r: ReportRange) {
        if ui.range == r { return }
        mut { $0.range = r }
        rebuild()
    }

    public func setCustomFrom(_ d: LocalDay?) {
        if ui.customFrom == d { return }
        mut { $0.customFrom = d }
        rebuild()
    }

    public func setCustomTo(_ d: LocalDay?) {
        if ui.customTo == d { return }
        mut { $0.customTo = d }
        rebuild()
    }

    // ── CSV export ───────────────────────────────────────────────────────────

    /// Writes the report's orders as CSV into `dir` off the main actor (streamed
    /// row by row, never one giant string), then offers it as `readyExport`
    /// for the share sheet. A write failure is a toast; a tap while one is
    /// being written (or waiting to be shared) is ignored.
    public func exportCsv(dir: URL) {
        guard let r = ui.report else { return }
        if ui.exporting || ui.readyExport != nil { return }
        let range = ui.range
        mut { $0.exporting = true }
        launch { [weak self] in
            guard let self = self else { return }
            let orders = r.orders
            let result: Result<URL, Error> = await Task.detached(priority: .utility) {
                Result { try ReportsRules.writeReportCsv(dir: dir, orders: orders, range: range) }
            }.value
            if self.closed { return }
            self.mut { $0.exporting = false }
            switch result {
            case .success(let file): self.mut { $0.readyExport = ReadyExport(file: file, range: range) }
            case .failure(let e): self.host.toast(ReportsRules.exportFailureText(e), .error)
            }
        }
    }

    /// The screen opened the share sheet for `ready` (or failed to, and said so).
    public func exportShown(_ ready: ReadyExport) {
        if ui.readyExport == ready { mut { $0.readyExport = nil } }
    }

    /// The screen showed the `exportInterrupted` notice.
    public func interruptionShown() {
        if ui.exportInterrupted {
            mut { $0.exportInterrupted = false }
            host.toast(Self.EXPORT_INTERRUPTED, .warning)
        }
    }

    // ── The app reclaimed: tab, range and custom dates come back ─────────────

    /// What a restarted app should get back (plain JSON text, never a secret).
    public func saveUi() -> String {
        var o: [String: JSONValue] = ["tab": .string(ui.tab.rawValue), "range": .string(ui.range.rawValue)]
        if let f = ui.customFrom { o["from"] = .string(f.description) }
        if let t = ui.customTo { o["to"] = .string(t.description) }
        // A CSV being written (or not yet shared) is lost with the process: say so on return.
        if ui.exporting || ui.readyExport != nil { o["exporting"] = .bool(true) }
        return JSONValue.object(o).text
    }

    public func restoreUi(_ saved: String) {
        guard let o = JSONValue.parse(saved)?.objectValue else { return }
        mut { s in
            if let t = o["tab"]?.stringValue, let tab = ReportTab(rawValue: t) { s.tab = tab }
            if let r = o["range"]?.stringValue, let range = ReportRange(rawValue: r) { s.range = range }
            if let f = o["from"]?.stringValue, let d = LocalDay.parse(f) { s.customFrom = d }
            if let t = o["to"]?.stringValue, let d = LocalDay.parse(t) { s.customTo = d }
            if o["exporting"]?.boolValue == true { s.exportInterrupted = true }
        }
        rebuild()
    }

    @discardableResult
    public func restoreIfFresh(_ saved: String?) -> Bool {
        if uiAttached { return false }
        uiAttached = true
        guard let s = saved, !s.isEmpty else { return false }
        restoreUi(s)
        return true
    }

    public func close() {
        if closed { return }
        closed = true
        life.close()
        subs.forEach { $0.cancel() }
        subs = []
        midnight?.cancel()
        midnight = nil
        fetchTask?.cancel()
        buildTask?.cancel()
        for j in jobs.values { j.cancel() }
        jobs = [:]
    }
}
