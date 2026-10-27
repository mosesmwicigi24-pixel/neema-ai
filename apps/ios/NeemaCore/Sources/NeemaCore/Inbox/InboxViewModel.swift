import Foundation

/// Runs `body` on the main actor: at once when already on the main thread
/// (tests, the app's own calls), else hopped there (socket readers, the
/// network monitor). Keeps the order of events as they arrive.
func onMain(_ body: @escaping @MainActor () -> Void) {
    if Thread.isMainThread { MainActor.assumeIsolated { body() } } else { Task { @MainActor in body() } }
}

/// A unit of work with kotlinx's `Job.isActive`: false once it has run or was cancelled.
@MainActor
public final class Job {
    private(set) var active = true
    private var task: Task<Void, Never>?
    init(_ body: @escaping @MainActor () async -> Void) {
        task = Task { [self] in
            await body()
            self.active = false
        }
    }
    public var isActive: Bool { active }
    public func cancel() { active = false; task?.cancel() }
}

/// The inbox screen's state: the paged conversation list (a port of
/// hooks/useInbox.ts), the open thread, its composer, and every conversation
/// action of ConversationsView.tsx — Android's `ConversationsViewModel`, one
/// rule for one rule.
///
/// useInbox's three rules hold here too: the cache holds every row ever
/// loaded while `InboxUi.orderIds` says what the current filter shows; a
/// refresh MERGES; and the newest request wins (sequence numbers).
@MainActor
public final class InboxViewModel {
    nonisolated public static let MB: Int64 = 1024 * 1024
    /// A burst of typing reaches disk this long after it stops.
    nonisolated public static let MEMORY_DEBOUNCE_MS: Int64 = 400
    /// Sends the app was killed during: looked for on the server at once, then again.
    nonisolated public static let RESTORE_CHECK_MS: [Int64] = [0, 2_000, 8_000]
    nonisolated public static let AUTH_HELD = "Your session expired — sign in again and it will send."
    /// After a send got no answer: re-read the thread at these intervals (the server may still be delivering it) before calling it failed.
    nonisolated public static let RECONCILE_DELAYS_MS: [Int64] = [2_000, 8_000, 20_000]
    /// A burst of frames becomes one list refetch this long after the first.
    nonisolated public static let SOCKET_REFRESH_MS: Int64 = 1_500
    nonisolated public static let CATCH_UP_WINDOW_MS: Int64 = 2_000
    /// New messages in the open thread re-check its messaging window this long after the first.
    nonisolated public static let WINDOW_REFRESH_MS: Int64 = 1_000
    /// Threads whose messages stay cached (the open one plus the most recently visited).
    nonisolated public static let MAX_CACHED_THREADS = 8
    /// Message-frame ids remembered for duplicate-delivery checks.
    nonisolated public static let SEEN_FRAMES = 512
    /// Calls frames that can change the open thread's call pills.
    nonisolated public static let CALL_FRAMES: Set<String> = ["incoming_call", "call_answered", "call_ended", "call_update"]
    nonisolated public static let CALL_REFRESH_MS: Int64 = 700
    /// Conversation frames that move a row or a badge.
    nonisolated public static let MOVING_FRAMES: Set<String> = ["new_message", "message", "intercept_changed", "history_cleared"]
    nonisolated public static let MAX_IMAGE = 5 * MB
    nonisolated public static let MAX_VIDEO = 150 * MB
    nonisolated public static let MAX_AUDIO = 16 * MB
    nonisolated public static let MAX_DOC = 18 * MB
    nonisolated public static let SENDABLE_IMAGES: Set<String> = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    nonisolated public static let LIST_POLL_MS: Int64 = 60_000
    nonisolated public static let THREAD_POLL_MS: Int64 = 20_000
    nonisolated public static let SEARCH_DEBOUNCE_MS: Int64 = 300
    nonisolated public static let QUIET_REFRESH_MS: Int64 = 2_000
    nonisolated public static let TRANSLATE_DEBOUNCE_MS: Int64 = 700
    nonisolated public static let ACTIVITY_REFRESH_MS: Int64 = 60_000

    public let host: InboxHost
    private var api: NeemaApi { host.api }
    public let inboxApi: InboxApi
    private let mediaAccess: MediaAccess
    private let sleep: Sleeper
    public var myId: String? { host.session.value?.agentId }

    public let inbox = Watched<InboxUi>(InboxUi())
    public let list = Watched<ListUi>(ListUi())
    public let thread = Watched<ThreadUi>(ThreadUi())
    public let composer = Watched<ComposerUi>(ComposerUi())
    public let dialogs = Watched<DialogUi>(DialogUi())
    /// Fires whenever `rows` may have changed (the list regroups lazily, on read).
    public let rowsChanged = Signal<Void>(buffer: 1)
    private var rowsCache: [RowGroup] = []
    private var rowsDirty = true

    /// The people the list shows, grouped and sorted (filteredConvs → groupedConvs).
    /// Computed on demand, once per change — a burst of frames never regroups 5,000 people per frame.
    public var rows: [RowGroup] {
        if rowsDirty {
            rowsCache = Inbox.groupRows(inbox.value, me: myId)
            rowsDirty = false
        }
        return rowsCache
    }

    // useInbox refs
    private var cursor: String? = nil
    private var pages = 0
    private var firstSeq = 0
    private var moreSeq = 0
    private var revealed: [String] = []
    private var watched: String? = nil
    private var seededFor: String? = nil
    private var quietJob: Job? = nil
    private var searchJob: Job? = nil
    private var socketRefreshJob: Job? = nil
    private var catchUpJob: Job? = nil
    /// Alive for a moment after each refresh() — a catch-up right then needn't repeat it.
    private var recentRefresh: Job? = nil
    private var txJob: Job? = nil
    private var draftJob: Job? = nil
    private var windowJob: Job? = nil
    private var activityJob: Job? = nil
    /// The page-one request in flight. A refresh for the SAME filters joins it and asks for
    /// one more run after it (`refreshAgain`) — never cancels it. Only a change of filters cancels.
    private var pageJob: Job? = nil
    private var pageKey: String? = nil
    private var pageSeq = 0
    private var refreshAgain = false
    /// The newest refresh whose badges were shown: an older, slower answer never overwrites them.
    private var summaryShown = 0
    /// One messaging-window re-check per burst of new messages.
    private var windowSoonJob: Job? = nil
    /// Each thread's load in flight: a poll or catch-up never stacks a second one on it.
    private var threadJobs: [String: Job] = [:]
    /// Threads opened most recently (last = newest): only these keep their messages cached.
    private var recentThreads: [String] = []
    /// Ids of message frames already handled: a duplicate delivery neither re-counts nor re-moves a row.
    private var seenFrames: [String] = []
    private var seenFrameSet: Set<String> = []
    /// Sends on their way, by bubble id, in the order they were made.
    private var outgoing: [String: Outgoing] = [:]
    private var outgoingOrder: [String] = []
    /// Each thread's composer while another thread is open: text, quote, files, draft.
    private var stash: [String: ComposerUi] = [:]
    /// The newest load of each thread: an older answer landing last never flips its flags.
    private var loadSeq: [String: Int] = [:]
    private var localSeq = 0
    /// Drafts generated for a thread the agent had left: shown when it is opened again.
    private var heldDrafts: [String: String] = [:]
    /// A deep link that failed for want of a connection: tried again on reconnect.
    private var retryOpenKey: String? = nil
    /// Half-written notes of threads the agent left (a deep link can switch threads under an open note).
    private var noteStash: [String: String] = [:]
    /// Whose `InboxMemory` this is (the agent signed in when it was read).
    private var memoryFor: String? = nil
    /// Nothing is written before the saved memory has been read back: it would overwrite it.
    private var memoryReady = false
    private var memoryJob: Job? = nil
    /// Threads whose files an expired session refused: they go again on sign-in.
    private var mediaAuthHeld: [String] = []
    private var reachJob: Job? = nil
    private var callRefreshJob: Job? = nil
    private var lastLiveStamp: Int64 = 0
    private var openingKey = false
    private var subs: [Subscription] = []
    private var jobs: [UUID: Job] = [:]
    private var closed = false
    private var wasFront: Bool
    private var wasExpired: Bool
    private var wasConnected: Bool
    private var lastListSig: (String, Bool)? = nil
    private var lastFilters: InboxQuery? = nil
    private var lastThreadSig: (String, Bool, [String])? = nil

    public init(host: InboxHost, media: MediaAccess = FileMediaAccess(), sleep: @escaping Sleeper = realSleep) {
        self.host = host
        self.inboxApi = InboxApi(http: host.api.http)
        self.mediaAccess = media
        self.sleep = sleep
        wasFront = host.foreground.value
        wasExpired = host.sessionExpired.value
        wasConnected = host.socketConnected.value
        start()
    }

    private func start() {
        // Seed from this agent's snapshot so the inbox paints instantly, then fetch.
        subs.append(host.session.observe { [weak self] s in onMain { guard let self = self else { return }; self.onSession(s); self.regroup() } })
        // What the agent is doing reaches disk shortly after each change, and at
        // once when the app goes to the background (where the system may kill it).
        subs.append(composer.observe { [weak self] _ in onMain { self?.saveSoon() } })
        subs.append(dialogs.observe { [weak self] _ in onMain { self?.saveSoon() } })
        subs.append(list.observe { [weak self] l in onMain {
            guard let self = self else { return }
            let sig = (l.search, l.showFilters)
            if let last = self.lastListSig, last == sig { return }
            self.lastListSig = sig
            self.saveSoon()
        } })
        subs.append(inbox.observe { [weak self] s in onMain {
            guard let self = self else { return }
            if self.lastFilters == s.filters { return }
            self.lastFilters = s.filters
            self.saveSoon()
        } })
        subs.append(thread.observe { [weak self] t in onMain {
            guard let self = self else { return }
            let sig = (t.activeId, t.threadOpen, self.outboxSig())
            if let last = self.lastThreadSig, last == sig { return }
            self.lastThreadSig = sig
            self.saveSoon()
        } })
        subs.append(host.foreground.observe { [weak self] v in onMain {
            guard let self = self else { return }
            let was = self.wasFront
            self.wasFront = v
            if !v { self.saveMemory() }
            // Frames sent while the app was away are gone: returning to the foreground catches up.
            if v && !was { self.catchUp() }
        } })
        // Sends refused with a 401 go the moment the agent signs back in (SessionExpiredDialog).
        subs.append(host.sessionExpired.observe { [weak self] v in onMain {
            guard let self = self else { return }
            let was = self.wasExpired
            self.wasExpired = v
            if was && !v && self.host.session.value != nil { self.resendHeld() }
        } })
        // …and every reconnect catches up too.
        subs.append(host.socketConnected.observe { [weak self] v in onMain {
            guard let self = self else { return }
            let was = self.wasConnected
            self.wasConnected = v
            if v && !was { self.catchUp() }
        } })
        subs.append(host.inboxRefresh.observe { [weak self] _ in onMain { self?.refresh() } })
        subs.append(host.socketEvents.observe { [weak self] e in onMain { self?.onSocket(e) } })
        // Deep links from other views / the hub: consume host.openConvKey.
        subs.append(host.openConvKey.observe { [weak self] _ in onMain { self?.checkOpenKey() } })
        // Words another view asked for in the open thread's composer (never sent by themselves).
        subs.append(host.composerPrefill.observe { [weak self] _ in onMain { self?.checkPrefill() } })
        // Poll (push events are the primary signal) while foregrounded. A tick
        // that falls while backgrounded waits for the return — where catchUp()
        // has already refetched — and skips, so coming back is one request.
        launch { [weak self] in
            while let self = self, !Task.isCancelled {
                do { try await self.sleep(Self.LIST_POLL_MS) } catch { return }
                if !self.host.foreground.value { await await_(self.host.foreground, equals: true); continue }
                self.refresh()
            }
        }
        // The open thread: poll as the socket's fallback every 20 s, as the web does (skip while backgrounded).
        launch { [weak self] in
            while let self = self, !Task.isCancelled {
                do { try await self.sleep(Self.THREAD_POLL_MS) } catch { return }
                let id = self.thread.value.activeId
                if !id.isEmpty && self.host.foreground.value { self.loadMessages(id, silent: true) }
            }
        }
    }

    /// The signed-in model is going away (sign-out, the screen's owner cleared).
    /// Signed out: the agent's work leaves with them — the next person on a
    /// shared phone must find nothing. Otherwise (the app finishing) it stays.
    public func close() {
        if closed { return }
        closed = true
        if host.session.value == nil { writeMemory(InboxMemory()) } else if memoryReady { writeMemory(buildMemory()) }
        subs.forEach { $0.cancel() }
        subs = []
        for j in jobs.values { j.cancel() }
        jobs = [:]
        for j in [quietJob, searchJob, socketRefreshJob, catchUpJob, recentRefresh, txJob, draftJob, windowJob, activityJob, pageJob, windowSoonJob, memoryJob, reachJob, callRefreshJob] { j?.cancel() }
        threadJobs.values.forEach { $0.cancel() }
        threadJobs = [:]
    }

    /// `viewModelScope.launch`: a unit of work that `close()` cancels.
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

    private func toast(_ message: String, _ type: ToastType = .success) { host.toast(message, type) }

    // ── State helpers ──

    private func mutInbox(_ f: (inout InboxUi) -> Void) {
        var v = inbox.value
        f(&v)
        inbox.value = v
        regroup()
        checkOpenKey()
    }
    private func mutList(_ f: (inout ListUi) -> Void) { var v = list.value; f(&v); list.update(v) }
    private func mutThread(_ f: (inout ThreadUi) -> Void) { var v = thread.value; f(&v); thread.value = v; checkPrefill() }
    private func mutComposer(_ f: (inout ComposerUi) -> Void) { var v = composer.value; f(&v); composer.update(v) }
    private func mutDialogs(_ f: (inout DialogUi) -> Void) { var v = dialogs.value; f(&v); dialogs.update(v) }

    private func regroup() {
        rowsDirty = true
        rowsChanged.emit()
    }

    private func onSession(_ s: Session?) {
        guard let id = s?.agentId else { return }
        if seededFor == id { return }
        seededFor = id
        memoryFor = id
        let snap: ConversationPage? = host.snapshots.readText(id, Inbox.SNAP_KEY).flatMap { JSONValue.parse($0) }.flatMap { Inbox.page(of: $0) }
        let mem: InboxMemory? = host.snapshots.read(id, Inbox.MEMORY_KEY)
        // The filters come back first, so the first request is already the right list.
        if let m = mem { restoreFilters(m) }
        if Inbox.filterKey(of: inbox.value.filters) == Inbox.DEFAULT_KEY { seed(snap) }
        refresh()
        if let m = mem { restoreWork(m) }
        memoryReady = true
    }

    // ═══════════════════════════ The paged list (useInbox) ═══════════════════════════

    private func seed(_ snap: ConversationPage?) {
        guard let snap = snap, !snap.items.isEmpty else { return }
        let rows = snap.items.map(Inbox.normalized)
        upsert(rows)
        mutInbox { s in
            if s.orderIds.isEmpty {
                s.orderKey = Inbox.DEFAULT_KEY
                s.orderIds = rows.map { $0.id }
                s.hasMore = snap.nextCursor != nil
            }
        }
        cursor = snap.nextCursor
        pages = 1
    }

    private func upsert(_ rows: [Conversation]) {
        if rows.isEmpty { return }
        mutInbox { s in for r in rows { s.cache[r.id] = Inbox.normalized(r) } }
    }

    /// Page one + badges.
    public func refresh() {
        if host.session.value == nil { return }
        firstSeq += 1
        let seq = firstSeq
        recentRefresh?.cancel()
        recentRefresh = Job { [sleep] in try? await sleep(Self.CATCH_UP_WINDOW_MS) }
        let f = inbox.value.filters
        let key = Inbox.filterKey(of: f)
        if inbox.value.orderKey != key || inbox.value.orderIds.isEmpty {
            mutInbox { $0.loading = true; $0.loadError = false; $0.errorText = nil }
        }
        launch { [weak self] in
            guard let self = self else { return }
            guard let s = try? await self.api.conversations.summary() else { return } // on failure the badges keep their last value
            if seq > self.summaryShown {
                self.summaryShown = seq
                self.mutInbox { $0.summary = s }
                self.host.inboxSummary.value = s
            }
        }
        if let p = pageJob, p.isActive, pageKey == key { refreshAgain = true; return }
        pageJob?.cancel()
        refreshAgain = false
        pageKey = key
        pageSeq += 1
        let pseq = pageSeq
        var job: Job? = nil
        job = launch { [weak self] in
            guard let self = self else { return }
            var finished = false
            defer {
                // Finished (answered or failed, not cancelled) with refreshes asked for meanwhile: one more.
                if finished, self.pageJob === job, self.refreshAgain {
                    self.refreshAgain = false
                    self.launch { [weak self] in self?.refresh() }
                }
            }
            let res: ConversationPage
            do {
                res = try await self.inboxApi.page(f, limit: Inbox.PAGE)
            } catch is CancellationError {
                return
            } catch {
                finished = true
                // Only the live filter's own failure counts; a superseded one says nothing.
                // The rows already on screen stay; the list says why it couldn't refresh.
                if pseq == self.pageSeq {
                    self.mutInbox { s in
                        let live = key == Inbox.filterKey(of: s.filters)
                        s.loading = false
                        s.loadError = live
                        if live { s.errorText = NetErrors.listErrorText(error) }
                    }
                }
                return
            }
            finished = true
            // Superseded by a newer refresh, or the filters moved on.
            if pseq != self.pageSeq || key != Inbox.filterKey(of: self.inbox.value.filters) { return }
            self.upsert(res.items)
            let fresh = res.items.map { $0.id }
            let top = Set(fresh)
            let o = self.inbox.value
            if o.orderKey != key || self.pages <= 1 {
                // Only page one was loaded (or a snapshot, maybe days old): REPLACE
                // it and take the fresh cursor. A "load more" in flight was paging
                // from the OLD cursor — cancel it so it can't leave a gap.
                self.cursor = res.nextCursor
                self.pages = 1
                self.moreSeq += 1
                let revealed = self.revealed
                self.mutInbox { s in
                    s.hasMore = res.nextCursor != nil
                    s.loadingMore = false
                    s.orderKey = key
                    s.orderIds = fresh + revealed.filter { !top.contains($0) }
                }
            } else {
                // Scrolled further this session: page one on top, the rest kept below.
                self.mutInbox { s in
                    s.orderKey = key
                    s.orderIds = fresh + s.orderIds.filter { !top.contains($0) }
                }
            }
            self.mutInbox { s in s.freshLoaded = true; s.loading = false; s.loadError = false; s.errorText = nil; s.moreError = false }
            if key == Inbox.DEFAULT_KEY, let raw = res.raw {
                self.host.snapshots.writeText(self.myId, Inbox.SNAP_KEY, raw.text)
            }
            // The open thread stays fresh even when it is not on page one.
            if let w = self.watched, !top.contains(w) {
                if let one = try? await self.inboxApi.get(id: w), pseq == self.pageSeq { self.upsert([one]) }
            }
        }
        pageJob = job
    }

    /// The next page of people. Scrolling calls it on its own; after a failure
    /// only an explicit Retry (`force`) or a successful refresh pages again.
    public func loadMore(force: Bool = false) {
        guard let c = cursor else { return }
        if inbox.value.loadingMore || host.session.value == nil { return }
        if inbox.value.moreError && !force { return }
        moreSeq += 1
        let seq = moreSeq
        let f = inbox.value.filters
        let key = Inbox.filterKey(of: f)
        mutInbox { $0.loadingMore = true; $0.moreError = false }
        launch { [weak self] in
            guard let self = self else { return }
            defer { if seq == self.moreSeq { self.mutInbox { $0.loadingMore = false } } }
            do {
                let res = try await self.inboxApi.page(f, limit: Inbox.PAGE, cursor: c)
                if seq != self.moreSeq || key != Inbox.filterKey(of: self.inbox.value.filters) { return }
                self.upsert(res.items)
                if self.inbox.value.orderKey != key { return }
                // Dedup by set, inside the update so a live frame that moved a row meanwhile is kept.
                self.mutInbox { s in
                    var have = Set(s.orderIds)
                    s.orderIds += res.items.map { $0.id }.filter { have.insert($0).inserted }
                    s.hasMore = res.nextCursor != nil
                }
                self.cursor = res.nextCursor
                self.pages += 1
            } catch is CancellationError {
                return
            } catch {
                if seq == self.moreSeq { self.mutInbox { $0.moreError = true } }
            }
        }
    }

    /// New filters start their own list; the cache (and the open thread) stays.
    private func setFilters(_ t: (InboxQuery) -> InboxQuery) {
        let prev = inbox.value.filters
        let next = t(prev)
        if next == prev { return }
        mutInbox { $0.filters = next }
        let key = Inbox.filterKey(of: next)
        if inbox.value.orderKey != key {
            cursor = nil; pages = 0; revealed = []
            mutInbox { s in
                s.hasMore = false; s.orderKey = key; s.orderIds = []
                s.loadError = false; s.errorText = nil; s.moreError = false
            }
        }
        refresh()
    }

    // Changing what the list shows clears the picks: a selection you can no
    // longer see is one you can't check before releasing it.
    private func clearPicks() { mutList { $0.selected = [] } }

    public func setTab(_ tab: String) { clearPicks(); setFilters { var f = $0; f.tab = tab; return f } }
    public func setChannel(_ ch: String) { clearPicks(); setFilters { var f = $0; f.channel = ch; return f } }
    public func setMode(_ m: String) { setFilters { var f = $0; f.mode = m; return f } }
    public func setTag(_ tag: String?) { clearPicks(); setFilters { var f = $0; f.tag = tag; return f } }
    public func toggleFilters() { mutList { $0.showFilters.toggle() } }

    /// Search waits for a pause in typing so every keystroke is not a query.
    public func setSearch(_ q: String) {
        mutList { $0.search = q; $0.selected = [] }
        searchJob?.cancel()
        searchJob = Job { [weak self, sleep] in
            do { try await sleep(Self.SEARCH_DEBOUNCE_MS) } catch { return }
            self?.setFilters { var f = $0; f.q = q; return f }
        }
    }

    /// Optimistic local edit to cached rows; a quiet refresh follows.
    public func patchRows(_ t: (Conversation) -> Conversation) {
        mutInbox { s in s.cache = s.cache.mapValues(t) }
        quietRefresh()
    }

    /// `patchRows` for one row: no pass over the whole (5,000-row) cache.
    private func patchRow(_ id: String, _ t: (Conversation) -> Conversation) {
        mutInbox { s in if let c = s.cache[id] { s.cache[id] = t(c) } }
        quietRefresh()
    }

    private func quietRefresh() {
        quietJob?.cancel()
        quietJob = Job { [weak self, sleep] in
            do { try await sleep(Self.QUIET_REFRESH_MS) } catch { return }
            self?.refresh()
        }
    }

    /// Add rows to the cache AND the visible list — a thread opened by a deep link.
    private func reveal(_ rows: [Conversation]) {
        upsert(rows)
        for r in rows where !revealed.contains(r.id) { revealed.append(r.id) }
        mutInbox { s in
            var have = Set(s.orderIds)
            s.orderIds += rows.map { $0.id }.filter { have.insert($0).inserted }
        }
    }

    public func renameCustomer(waId: String, newName: String) {
        patchRows { c in
            guard c.waId == waId else { return c }
            var n = c; n.name = newName; return n
        }
    }

    // ═══════════════════════════ Bulk selection ═══════════════════════════

    public func enterSelect(_ key: String? = nil) { mutList { $0.selectMode = true; $0.selected = key.map { [$0] } ?? [] } }
    public func exitSelect() { mutList { $0.selectMode = false; $0.selected = [] } }
    public func toggleRow(_ key: String) { mutList { s in if s.selected.contains(key) { s.selected.remove(key) } else { s.selected.insert(key) } } }
    public func selectAllOrClear() {
        let all = Set(rows.map { $0.key })
        mutList { s in s.selected = (s.selected.count == all.count && !all.isEmpty) ? [] : all }
    }

    /// How many conversations Release would act on — rows with Neema already cost nothing.
    public func selectedHeldIds() -> [String] {
        let sel = list.value.selected
        return rows.filter { sel.contains($0.key) }.flatMap { g in g.siblings.filter { $0.interceptMode == "human" }.map { $0.id } }
    }

    public func releaseSelected() {
        let ids = selectedHeldIds()
        if ids.isEmpty { toast("None of those are held by a human", .warning); return }
        if list.value.bulkBusy { return }
        mutList { $0.bulkBusy = true }
        launch { [weak self] in
            guard let self = self else { return }
            // Each release says whether it happened; one that got no answer is
            // asked about (a release is idempotent, and the row tells the truth).
            var failed: [Error] = []
            await withTaskGroup(of: (Int, Error?).self) { group in
                for (i, id) in ids.enumerated() {
                    group.addTask { @MainActor [weak self] in
                        guard let self = self else { return (i, nil) }
                        do { try await self.inboxApi.release(id: id); return (i, nil) } catch {
                            if error is CancellationError { return (i, nil) }
                            if NetErrors.conversationGone(error) { self.dropGone(id); return (i, nil) }
                            if NetErrors.fate(of: error) == .unknown {
                                if let row = try? await self.inboxApi.get(id: id), row.interceptMode == "ai" { self.upsert([row]); return (i, nil) }
                                return (i, error)
                            }
                            return (i, error)
                        }
                    }
                }
                var byIndex: [Int: Error] = [:]
                for await (i, e) in group { if let e = e { byIndex[i] = e } }
                failed = byIndex.keys.sorted().compactMap { byIndex[$0] }
            }
            if Task.isCancelled { return }
            let ok = ids.count - failed.count
            self.mutList { $0.bulkBusy = false }
            self.exitSelect()
            self.refresh()
            if let first = failed.first {
                self.toast("Released \(ok) — \(failed.count) failed. \(NetErrors.whyFailed(first, "Try again."))", .error)
            } else {
                self.toast("\(ok) conversation\(ok == 1 ? "" : "s") released back to Neema")
            }
        }
    }

    // ═══════════════════════════ Opening threads ═══════════════════════════

    public func activeConv() -> Conversation? { inbox.value.cache[thread.value.activeId] }

    public func select(_ id: String, openThread: Bool = true) {
        if let conv = inbox.value.cache[id], conv.unread > 0 {
            // Snapshot before clearing so the "N new" divider can be placed.
            mutThread { $0.unreadSnapshot[id] = conv.unread }
            patchRow(id) { var c = $0; c.unread = 0; return c }
        }
        let prev = thread.value.activeId
        let changed = prev != id
        // Each customer keeps their own composer: what was typed for one person
        // must never be sent to the next one opened. The same person's other
        // channels share it — a quote grabbed on WhatsApp can be answered on
        // their Facebook thread (as a text prefix), as on the web.
        if changed {
            let txMode = composer.value.txMode
            let samePerson = !prev.isEmpty && composerKey(prev) == composerKey(id)
            let next: ComposerUi
            if samePerson {
                next = composer.value
            } else {
                if !prev.isEmpty { stash[composerKey(prev)] = composer.value }
                next = stash.removeValue(forKey: composerKey(id)) ?? ComposerUi()
            }
            // A draft belongs to one thread, and one left behind may be stale (a
            // newer one may have been written meanwhile): only a draft the agent
            // opened or edited comes back with its own thread.
            let keepDraft = !samePerson && next.draftVisible && (next.draftExpanded || next.draftEditing)
            var c = next
            c.txMode = txMode; c.txPreview = nil; c.txBusy = false
            c.draftVisible = keepDraft
            c.draftExpanded = keepDraft && next.draftExpanded
            c.draftEditing = keepDraft && next.draftEditing
            c.draftText = keepDraft ? next.draftText : ""
            composer.value = c
            if let d = heldDrafts.removeValue(forKey: id) {
                mutComposer { $0.draftText = d; $0.draftVisible = true; $0.draftExpanded = true; $0.draftEditing = false }
            }
            // A thread's dialogs belong to it. A deep link or a notification tap can
            // switch threads under an open one: a transfer or a clear must never
            // retarget, and a half-written note waits with its own thread.
            let d = dialogs.value
            if !prev.isEmpty && d.note && !d.noteText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { noteStash[prev] = d.noteText }
            let note = noteStash.removeValue(forKey: id)
            mutDialogs { $0.transfer = false; $0.clearConfirm = false; $0.note = note != nil; $0.noteText = note ?? "" }
        }
        mutThread { t in
            t.activeId = id
            t.threadOpen = openThread || t.threadOpen
            if changed { t.window = nil; t.activity = [] }
        }
        watched = id
        keepRecent(id)
        loadMessages(id)
        if changed { onActiveChanged(id) }
    }

    /// Only the `MAX_CACHED_THREADS` threads opened most recently keep their
    /// messages in memory. A thread with a send still on its way is never
    /// dropped; one dropped reloads when reopened.
    private func keepRecent(_ id: String) {
        recentThreads.removeAll { $0 == id }
        recentThreads.append(id)
        let pending = Set(outgoing.values.map { $0.convId })
        while recentThreads.count > Self.MAX_CACHED_THREADS {
            guard let old = recentThreads.first(where: { $0 != id && !pending.contains($0) }) else { break }
            recentThreads.removeAll { $0 == old }
        }
        let keep = Set(recentThreads).union(pending)
        let drop = thread.value.messages.keys.filter { !keep.contains($0) }
        if drop.isEmpty { return }
        for d in drop { threadJobs[d] = nil; loadSeq[d] = nil }
        mutThread { t in for d in drop { t.messages[d] = nil; t.hasMore[d] = nil } }
    }

    public func closeThread() { mutThread { $0.threadOpen = false } }

    private func onActiveChanged(_ id: String) {
        // A human-held thread fetches the latest AI draft (pill only) unless the
        // agent's own open draft came back with the thread.
        draftJob?.cancel()
        if !composer.value.draftVisible { fetchLatestDraft(id) }
        refreshWindow()
        loadActivity()
        scheduleTranslate()
        loadReach(id)
    }

    /// The customer's captured phone and channels (the profile CustomerSidebar
    /// reads). A person already on WhatsApp needs no invite, so no fetch; a
    /// failure leaves the shortcut hidden rather than guessing.
    private func loadReach(_ id: String) {
        reachJob?.cancel()
        mutThread { $0.reach = nil }
        guard let conv = inbox.value.cache[id] else { return }
        let onWa = Inbox.realWhatsApp(conv) || (conv.personId != nil && inbox.value.cache.values.contains { $0.personId == conv.personId && Inbox.realWhatsApp($0) })
        if onWa { mutThread { $0.reach = Reach(convId: id, phone: Inbox.phoneDigits(conv), hasWhatsApp: true) }; return }
        guard let key = conv.waId ?? conv.externalId else { return }
        reachJob = Job { [weak self] in
            guard let self = self else { return }
            guard let p = try? await CrmApi(http: self.api.http).profile(key: key, channel: conv.channel.isEmpty ? nil : conv.channel) else { return }
            if self.thread.value.activeId != id { return }
            let hasWa = p.channels.contains { $0.channel == "whatsapp" && !Inbox.isWebVisitor($0.identifier) }
            self.mutThread { $0.reach = Reach(convId: id, phone: p.phone, hasWhatsApp: hasWa) }
        }
    }

    private func checkOpenKey() {
        guard let k = host.openConvKey.value, !openingKey else { return }
        openingKey = true
        defer { openingKey = false }
        tryOpenKey(k, inbox.value)
    }

    /// Open a conversation another view requested (Calls → "message in Neema", the hub).
    private func tryOpenKey(_ openKey: String, _ s: InboxUi) {
        // A pair computed before the key was consumed is stale.
        if host.openConvKey.value != openKey { return }
        // A deep link can land before the inbox has loaded — don't consume it against an empty list.
        if s.cache.isEmpty { return }
        let parts = openKey.split(separator: "|", omittingEmptySubsequences: false).map(String.init)
        let rawKey = parts[0]
        let refPart = parts.count > 1 && !parts[1].trimmingCharacters(in: .whitespaces).isEmpty ? parts[1] : nil
        let key = rawKey.hasPrefix("+") ? String(rawKey.dropFirst()) : rawKey
        let matches = s.cache.values.filter { $0.waId == key || $0.externalId == key || $0.waId == rawKey || $0.id == rawKey }
        let conv = matches.first { $0.channel == "whatsapp" } ?? matches.first
        if let conv = conv {
            select(conv.id)
        } else {
            // A cached snapshot may not contain a brand-new conversation — wait for the fresh list.
            if !s.freshLoaded { return }
            // Not directly keyed — the server walks order -> person -> identities.
            launch { [weak self] in
                guard let self = self else { return }
                let id: String?
                do {
                    id = try await self.api.conversations.resolve(key: key, ref: refPart)
                } catch is CancellationError {
                    return
                } catch {
                    // No connection: the link is kept and opened once we're back.
                    if NetErrors.status(of: error) == 0 {
                        self.retryOpenKey = openKey
                        self.toast("Couldn't open that chat — no connection. It will open when you're back online.", .error)
                    } else {
                        self.toast("Could not look up that chat.", .error)
                    }
                    return
                }
                guard let id = id else {
                    self.toast("No conversation yet — they haven't messaged. Use Invite to WhatsApp.", .warning)
                    return
                }
                if self.inbox.value.cache[id] == nil {
                    // Revealed, not just cached: the paged list would drop it on the next refresh.
                    if let row = try? await self.inboxApi.get(id: id) { self.reveal([row]) }
                }
                self.select(id)
            }
        }
        host.openConvKey.value = nil
    }

    private func checkPrefill() {
        guard let p = host.composerPrefill.value, p.convId == thread.value.activeId else { return }
        host.composerPrefill.value = nil
        useAsReply(p.text)
    }

    /// Jump to the same person's conversation on another channel.
    public func openIdentity(channel: String, externalId: String) {
        func matches(_ c: Conversation) -> Bool { c.channel == channel && (c.externalId == externalId || c.waId == externalId) }
        if let hit = inbox.value.cache.values.first(where: matches) { select(hit.id); return }
        // Paged: absence here is not absence. Ask for THAT channel and THAT id.
        launch { [weak self] in
            guard let self = self else { return }
            let items: [Conversation]
            do {
                items = try await self.inboxApi.page(InboxQuery(channel: channel, q: externalId), limit: 5).items
            } catch is CancellationError {
                return
            } catch {
                // A failed lookup is not an answer: never claim there is no conversation.
                self.toast("Couldn't open that conversation. \(NetErrors.whyFailed(error, "Try again."))", .error)
                return
            }
            if let hit = items.map(Inbox.normalized).first(where: matches) { self.reveal([hit]); self.select(hit.id) }
            else { self.toast("No conversation on that channel yet.", .warning) }
        }
    }

    // ═══════════════════════════ The thread ═══════════════════════════

    private func setMsgs(_ convId: String, _ t: ([ThreadMsg]) -> [ThreadMsg]) {
        let loaded = thread.value.messages[convId] != nil
        let before = thread.value.messages[convId]?.count ?? 0
        mutThread { s in s.messages[convId] = t(s.messages[convId] ?? []) }
        let after = thread.value.messages[convId]?.count ?? 0
        // An inbound reopens the messaging window: re-check it when messages arrive —
        // once per burst, and not for the first load of a thread, whose opening already asked.
        if convId == thread.value.activeId && after != before && loaded { scheduleWindowRefresh() }
    }

    private func scheduleWindowRefresh() {
        if let w = windowSoonJob, w.isActive { return }
        windowSoonJob = Job { [weak self, sleep] in
            do { try await sleep(Self.WINDOW_REFRESH_MS) } catch { return }
            self?.refreshWindow()
        }
    }

    /// The server's newest page for `convId`: merged in (a fresh open replaces,
    /// keeping only this device's own bubbles), then any send still on its way
    /// is settled against it.
    private func applyServer(_ convId: String, _ msgs: [ThreadMsg], replace: Bool = false) {
        setMsgs(convId) { cur in replace ? Inbox.mergeServer(cur.filter { $0.isLocal }, msgs) : Inbox.mergeServer(cur, msgs) }
        settle(convId, msgs)
    }

    public func loadMessages(_ convId: String, silent: Bool = false) {
        if convId.isEmpty { return }
        // A background re-read (the 20 s poll, a catch-up) while a load is already
        // on its way would fetch the same page twice: that answer covers it.
        if silent, let j = threadJobs[convId], j.isActive { return }
        let seq = (loadSeq[convId] ?? 0) + 1
        if !silent { loadSeq[convId] = seq; mutThread { $0.loading = true; $0.error = false; $0.errorText = nil } }
        threadJobs[convId] = Job { [weak self] in
            guard let self = self else { return }
            defer {
                if !silent && self.loadSeq[convId] == seq && self.thread.value.activeId == convId { self.mutThread { $0.loading = false } }
            }
            do {
                let msgs = try await self.inboxApi.messages(id: convId)
                self.applyServer(convId, msgs, replace: !silent)
                if !silent { self.mutThread { $0.hasMore[convId] = msgs.filter { !$0.isSystem }.count >= Inbox.THREAD_PAGE } }
            } catch is CancellationError {
                return
            } catch {
                if NetErrors.conversationGone(error) { self.dropGone(convId); return }
                // "No messages yet" over a failed fetch would read as an empty conversation.
                // Only this thread's newest open touches the spinner and error — and only while it is still the thread on screen.
                if !silent && self.loadSeq[convId] == seq && self.thread.value.activeId == convId {
                    self.mutThread { $0.error = true; $0.errorText = NetErrors.whyFailed(error, "Couldn't load this conversation.") }
                    self.toast("Failed to load messages", .error)
                }
            }
        }
    }

    /// Scrolling up past the loaded page fetches the previous page (via `before`).
    public func loadOlder() {
        let t = thread.value
        let convId = t.activeId
        if convId.isEmpty || t.olderLoading == convId || t.hasMore[convId] != true { return }
        guard let oldest = (t.messages[convId] ?? []).first(where: { !$0.isSystem && !$0.isLocal }), let before = oldest.createdAt else { return }
        mutThread { s in s.olderLoading = convId; if s.olderError == convId { s.olderError = "" } }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mutThread { s in if s.olderLoading == convId { s.olderLoading = "" } } }
            do {
                let older = try await self.inboxApi.messages(id: convId, before: before)
                self.mutThread { $0.hasMore[convId] = older.filter { !$0.isSystem }.count >= Inbox.THREAD_PAGE }
                if !older.isEmpty { self.setMsgs(convId) { Inbox.mergeThread($0, older) } }
            } catch is CancellationError {
                return
            } catch {
                // Scrolling at the very top changes nothing that would ask again: offer a tap.
                self.mutThread { $0.olderError = convId }
            }
        }
    }

    private func refreshWindow() {
        let id = thread.value.activeId
        if id.isEmpty { return }
        windowJob?.cancel()
        windowJob = Job { [weak self] in
            guard let self = self else { return }
            let w = try? await self.api.conversations.window(id: id)
            if Task.isCancelled { return }
            if self.thread.value.activeId == id { self.mutThread { $0.window = w } }
        }
    }

    /// The person-scoped journey ledger; refreshed each minute while the panel is open.
    private func loadActivity() {
        let id = thread.value.activeId
        if id.isEmpty { return }
        activityJob?.cancel()
        activityJob = Job { [weak self] in
            while let self = self, !Task.isCancelled {
                let ev = (try? await self.inboxApi.activity(id: id)) ?? []
                if Task.isCancelled || self.thread.value.activeId != id { return }
                self.mutThread { $0.activity = ev }
                if !self.thread.value.activityOpen { return }
                do { try await self.sleep(Self.ACTIVITY_REFRESH_MS) } catch { return }
                if !self.host.foreground.value { await await_(self.host.foreground, equals: true) }
            }
        }
    }

    public func setActivityOpen(_ open: Bool) {
        mutThread { $0.activityOpen = open }
        if open { loadActivity() }
    }

    /// Fetch an expired attachment back from Meta. Only the server's 404 means
    /// Meta no longer has it; a dropped connection or a busy server is "try
    /// again", never "gone for good".
    public func recoverMedia(_ messageId: String, onDone: @escaping @MainActor (Recovery) -> Void) {
        let convId = thread.value.activeId
        launch { [weak self] in
            guard let self = self else { return }
            let out: Recovery
            do {
                let url = try await self.api.conversations.recoverMedia(messageId: messageId).mediaUrl.trimmingCharacters(in: .whitespaces)
                out = url.isEmpty ? .gone : .found(url: url)
            } catch is CancellationError {
                return
            } catch {
                let st = NetErrors.status(of: error)
                out = (st == 404 || st == 422) ? .gone : .failed(why: NetErrors.whyFailed(error, "Couldn't fetch it — try again."))
            }
            if case .found(let url) = out {
                self.mutThread { $0.recovered[messageId] = url }
                if !convId.isEmpty { self.loadMessages(convId, silent: true) }
            }
            onDone(out)
        }
    }

    // ═══════════════════════════ Live events ═══════════════════════════

    /// Catch up on what the socket could not deliver: the list and badges, the
    /// open thread, and — for a human-held thread — a draft that may have been
    /// written meanwhile. A return to the foreground usually also reopens the
    /// socket a moment later; both land in one catch-up, and a list refresh
    /// that has only just run is not repeated.
    private func catchUp() {
        if host.session.value == nil { return }
        if let c = catchUpJob, c.isActive { return }
        // A deep link that failed offline opens now.
        if let k = retryOpenKey {
            retryOpenKey = nil
            if host.openConvKey.value == nil { host.openConvKey.value = k }
        }
        catchUpJob = Job { [weak self] in
            guard let self = self else { return }
            if !(self.recentRefresh?.isActive ?? false) { self.refresh() }
            let id = self.thread.value.activeId
            if !id.isEmpty {
                self.loadMessages(id, silent: true)
                if !self.composer.value.draftVisible { self.fetchLatestDraft(id) }
            }
            try? await self.sleep(Self.CATCH_UP_WINDOW_MS)
        }
    }

    /// The latest AI draft of a human-held thread, as a pill (never auto-expanded).
    private func fetchLatestDraft(_ id: String) {
        if inbox.value.cache[id]?.interceptMode != "human" { return }
        draftJob?.cancel()
        draftJob = Job { [weak self] in
            guard let self = self else { return }
            guard let d = try? await self.api.conversations.latestDraft(id: id), !d.trimmingCharacters(in: .whitespaces).isEmpty else { return }
            if Task.isCancelled { return }
            if self.thread.value.activeId == id && !self.composer.value.draftVisible { self.mutComposer { $0.draftText = d; $0.draftVisible = true } }
        }
    }

    /// Change `convId`'s composer — the live one when it is open, else the one it left behind.
    private func editComposer(_ convId: String, _ t: (inout ComposerUi) -> Void) {
        if convId.isEmpty { return }
        let active = thread.value.activeId
        let key = composerKey(convId)
        if !active.isEmpty && composerKey(active) == key { mutComposer(t) }
        else { var c = stash[key] ?? ComposerUi(); t(&c); stash[key] = c }
    }

    /// Whose composer a thread uses: the person's (all their channels share one), else the thread's own.
    private func composerKey(_ convId: String) -> String { inbox.value.cache[convId]?.personId.map { "p:\($0)" } ?? convId }

    /// Someone deleted the conversation (the server's 404): take it off the
    /// list, close it if open, and say so once.
    private func dropGone(_ convId: String) {
        guard let had = inbox.value.cache[convId] else { return }
        mutInbox { s in s.cache[convId] = nil; s.orderIds.removeAll { $0 == convId } }
        revealed.removeAll { $0 == convId }
        if had.personId == nil { stash[convId] = nil }
        noteStash[convId] = nil
        for (k, o) in outgoing where o.convId == convId { outgoing[k] = nil; outgoingOrder.removeAll { $0 == k } }
        if watched == convId { watched = nil }
        mutThread { t in
            let open = t.activeId == convId
            t.messages[convId] = nil
            if open {
                t.activeId = ""; t.threadOpen = false; t.error = false; t.loading = false; t.window = nil; t.activity = []
            }
        }
        if thread.value.activeId.isEmpty { mutComposer { c in c = ComposerUi(txMode: c.txMode) } }
        toast("\(Inbox.inboxName(had))'s conversation was deleted — it has been removed from your inbox.", .warning)
    }

    /// One refetch per burst: the first frame schedules it, frames arriving
    /// before it runs ride along.
    private func scheduleSocketRefresh() {
        if let j = socketRefreshJob, j.isActive { return }
        socketRefreshJob = Job { [weak self, sleep] in
            do { try await sleep(Self.SOCKET_REFRESH_MS) } catch { return }
            self?.refresh()
        }
    }

    private func onSocket(_ e: JSONValue) {
        let type = e.str("type")
        let convId = e.str("conversationId") ?? e.str("conversation_id")
        // Agent-level pings (`event: "notification"`) share type names with thread
        // events but carry a title/body, not a message — never paint them. The
        // shell refetches the inbox for the kinds that move it; an SMS arrival
        // (`new_message`) is the one it doesn't, so it counts here.
        if e.str("event") == "notification" {
            if type == "new_message" { scheduleSocketRefresh() }
            return
        }
        // A message frame delivered twice (a relay retry, a reconnect replay) is the
        // same message: it must not bump the row or count as unread a second time.
        if type == "new_message" || type == "message", let fid = e.str("id"), !fid.isEmpty {
            if !seenFrameSet.insert(fid).inserted { return }
            seenFrames.append(fid)
            if seenFrames.count > Self.SEEN_FRAMES { seenFrameSet.remove(seenFrames.removeFirst()) }
        }
        // A call with the open thread's customer rang, was answered, ended or got
        // its summary: its pill (and brief) must follow, as on the web.
        if let t = type, Self.CALL_FRAMES.contains(t) { onCallFrame(t, e); return }
        // Any thread moving means rows / badges moved: refetch shortly (coalesced).
        if let t = type, Self.MOVING_FRAMES.contains(t) { scheduleSocketRefresh() }
        guard let convId = convId else { return }
        // The row moves NOW; the refetch then confirms it (same values, no flicker).
        patchLive(convId, type, e)
        let active = thread.value.activeId
        if convId != active {
            // A cached thread that isn't open would reappear uncleared for a moment.
            if type == "history_cleared" && thread.value.messages[convId] != nil { setMsgs(convId) { _ in [] } }
            return
        }
        switch type {
        case "ai_draft_ready":
            mutComposer { $0.draftText = e.str("draft") ?? ""; $0.draftVisible = true; $0.draftExpanded = false; $0.draftEditing = false }
        // `message` is the older frame (web chat, ManyChat, TikTok, the Tier-2
        // agent's WhatsApp replies, channel sends). The web drops it and waits
        // for its 20 s poll; here it paints like `new_message`.
        case "new_message", "message":
            guard let msg = Inbox.wsMessage(of: e) else { return }
            setMsgs(active) { Inbox.appendWs($0, msg) }
        case "translations":
            guard let items = e["items"]?.arrayValue?.compactMap({ $0.objectValue }) else { return }
            var byId: [String: [String: JSONValue]] = [:]
            for it in items { byId[it["id"]?.content ?? ""] = it }
            let cur = thread.value.messages[active] ?? []
            if !cur.contains(where: { $0.translation == nil && byId[$0.id] != nil }) { return } // nothing to change: no re-render
            setMsgs(active) { existing in
                existing.map { x in
                    guard let t = byId[x.id], x.translation == nil else { return x }
                    var m = x
                    m.translation = t["text"]?.content
                    m.translatedFrom = t["lang"]?.content
                    return m
                }
            }
        case "intercept_changed":
            guard let evt = Inbox.systemEvent(fromWs: e) else { return }
            // One live pill per kind: a repeat fire is skipped.
            if (thread.value.messages[active] ?? []).contains(where: { $0.id.hasPrefix("live-evt-") && $0.eventKind == evt.eventKind }) { return }
            setMsgs(active) { $0 + [evt] }
        case "history_cleared":
            setMsgs(active) { _ in [] }
            toast("History cleared by \(e.str("clearedBy") ?? "an agent")")
        default:
            break
        }
    }

    /// A calls frame for the open thread's customer (their number, their person,
    /// or a call already in the thread): re-read the first page quietly — merged,
    /// so older pages, the scroll and the composer stay — to update the call pill
    /// and bring its summary in. A burst of frames is one read.
    private func onCallFrame(_ type: String, _ e: JSONValue) {
        let active = thread.value.activeId
        if active.isEmpty { return }
        let conv = inbox.value.cache[active]
        let row = e["call"]?.objectValue
        var wa: String? = type == "call_update" ? row?["wa_id"]?.content : (type == "incoming_call" ? e.str("from") : nil)
        if let w = wa, w.hasPrefix("+") { wa = String(w.dropFirst()) }
        let person = type == "call_update" ? row?["person_id"]?.content : e.str("person_id")
        let callId = e.str("call_id") ?? row?["call_id"]?.content
        var mine = false
        if let c = conv {
            if let w = wa, w == c.waId || (c.channel == "whatsapp" && w == c.externalId) { mine = true }
            if let p = person, p == c.personId { mine = true }
        }
        let known = callId != nil && (thread.value.messages[active] ?? []).contains { $0.call?.callId == callId }
        if !mine && !known { return }
        callRefreshJob?.cancel()
        callRefreshJob = Job { [weak self, sleep] in
            do { try await sleep(Self.CALL_REFRESH_MS) } catch { return }
            guard let self = self else { return }
            if self.thread.value.activeId == active { self.loadMessages(active, silent: true) }
        }
    }

    /// Two frames in the same millisecond must still sort by arrival: stamps only ever increase.
    private func liveStamp() -> String {
        lastLiveStamp = max(AppClock.now(), lastLiveStamp + 1)
        return Inbox.iso(ofMillis: lastLiveStamp)
    }

    /// Move the conversation's row the moment its frame lands, with the values
    /// the refetch will bring: a message sets the preview and time; an inbound
    /// one adds to `unread`, an outbound reply zeroes it; a mode change sets
    /// the mode and owner. A frame for a conversation not loaded yet leaves it
    /// to the refetch.
    private func patchLive(_ convId: String, _ type: String?, _ e: JSONValue) {
        guard let cur = inbox.value.cache[convId] else { return }
        var next = cur
        switch type {
        case "new_message", "message":
            guard let msg = Inbox.wsMessage(of: e) else { return }
            let text = msg.body.trimmingCharacters(in: .whitespacesAndNewlines)
            next.lastMessageAt = liveStamp()
            if !text.isEmpty { next.lastMessagePreview = String(text.prefix(100)) }
            next.unread = msg.inbound ? cur.unread + 1 : 0
        case "intercept_changed":
            guard let mode = e.str("mode") else { return } // an AI escalation carries no mode: the refetch says
            let released = mode == "ai"
            next.interceptMode = mode
            if released {
                next.assignedAgentId = nil
                next.assignedAgentName = nil
            } else {
                if e.objectValue?["assignedAgentId"] != nil { next.assignedAgentId = e.str("assignedAgentId") }
                next.assignedAgentName = e.str("assignedAgentName") ?? cur.assignedAgentName
            }
        case "history_cleared":
            next.lastMessagePreview = nil
            next.unread = 0
        default:
            return
        }
        if next == cur { return }
        mutInbox { s in
            // A thread just written to is on page one of an unsearched list; a
            // search waits for the server to say whether it still matches.
            let show = type != "intercept_changed" && type != "history_cleared" &&
                s.orderKey == Inbox.filterKey(of: s.filters) && s.filters.q.trimmingCharacters(in: .whitespaces).isEmpty && !s.orderIds.contains(convId)
            s.cache[convId] = next
            if show { s.orderIds.insert(convId, at: 0) }
        }
    }

    // ═══════════════════════════ Conversation actions ═══════════════════════════

    /// One control at a time per conversation; another thread's controls stay live.
    private func busy(_ id: String, _ kind: String, _ block: @escaping @MainActor () async -> Void) {
        if id.isEmpty || !thread.value.busyFor(id).isEmpty { return }
        mutThread { $0.busy[id] = kind }
        launch { [weak self] in
            defer { self?.mutThread { $0.busy[id] = nil } }
            await block()
        }
    }

    private func status(_ e: Error) -> Int { (e as? ApiError)?.status ?? 0 }

    // A 403 anywhere re-reads /admin/me and the team list on its own (NeemaHTTP →
    // the shell's onForbidden), so the inbox's role-based controls correct themselves.

    /// "Failed to pause. No connection — check your internet and try again." — the web's words, then why.
    private func failMsg(_ fail: String, _ e: Error, useDetail: Bool = false) -> String {
        let why = NetErrors.whyFailed(e, "", useDetail: useDetail)
        return why.isEmpty ? fail : "\(fail). \(why)"
    }

    /// An ownership change that got no answer: the server may have made it.
    /// These calls are idempotent, so the row is the truth — read it, show it,
    /// and report what actually happened.
    private func truthOf(_ id: String) async -> Conversation? {
        guard let row = try? await inboxApi.get(id: id) else { return nil }
        upsert([row])
        return row
    }

    /// Run one ownership control: success says `ok`; a conflict shows the
    /// current truth and `conflict`; no answer asks the server whether `done`
    /// holds before saying anything; a deleted conversation is removed.
    private func control(_ id: String, ok: String, fail: String, conflict: String?, done: (Conversation) -> Bool,
                         call: () async throws -> Void) async -> Bool {
        do {
            try await call()
        } catch is CancellationError {
            return false
        } catch {
            if NetErrors.conversationGone(error) { dropGone(id); return false }
            if status(error) == 409, let conflict = conflict {
                _ = await truthOf(id); refresh()
                toast(conflict, .error); return false
            }
            if NetErrors.fate(of: error) != .notSent {
                guard let row = await truthOf(id) else {
                    // Couldn't ask either: never call it failed when it may not have.
                    toast("Couldn't confirm that went through — no answer from the server. The inbox shows the latest as soon as you're back online.", .warning)
                    return false
                }
                if !done(row) { refresh(); toast(failMsg(fail, error), .error); return false }
                // It happened after all.
            } else {
                // A state conflict: show the current truth along with the reason.
                if status(error) == 409 { _ = await truthOf(id); refresh() }
                toast(failMsg(fail, error, useDetail: [400, 403, 409, 422].contains(status(error))), .error)
                return false
            }
        }
        refresh()
        toast(ok)
        return true
    }

    public func intercept(_ id: String) {
        busy(id, "intercept") { [weak self] in
            guard let self = self else { return }
            let me = self.myId
            _ = await self.control(id, ok: "Conversation claimed — you now control replies", fail: "Failed to claim conversation",
                                   conflict: "Already claimed by another agent",
                                   done: { $0.interceptMode == "human" && $0.assignedAgentId == me }) { try await self.inboxApi.intercept(id: id) }
        }
    }

    public func release(_ id: String) {
        busy(id, "release") { [weak self] in
            guard let self = self else { return }
            _ = await self.control(id, ok: "Conversation released back to Neema", fail: "Failed to release", conflict: nil,
                                   done: { $0.interceptMode == "ai" }) { try await self.inboxApi.release(id: id) }
        }
    }

    public func pause(_ id: String) {
        busy(id, "pause") { [weak self] in
            guard let self = self else { return }
            _ = await self.control(id, ok: "Paused — Neema holds all replies until you resume", fail: "Failed to pause",
                                   conflict: "Handled by another agent — they must pause it",
                                   done: { $0.interceptMode == "paused" }) { try await self.inboxApi.pause(id: id) }
        }
    }

    public func transfer(agentId: String, agentName: String?) {
        let id = thread.value.activeId
        if id.isEmpty { return }
        busy(id, "release") { [weak self] in
            guard let self = self else { return }
            let ok = await self.control(id, ok: "Transferred to \(agentName ?? "agent")", fail: "Failed to transfer", conflict: nil,
                                        done: { $0.assignedAgentId == agentId }) { try await self.inboxApi.transfer(id: id, agentId: agentId) }
            if ok { self.mutDialogs { $0.transfer = false } }
        }
    }

    public func showTransfer(_ v: Bool) { mutDialogs { $0.transfer = v } }
    public func showNote(_ v: Bool) { mutDialogs { $0.note = v } }
    public func setNoteText(_ v: String) { mutDialogs { $0.noteText = v } }
    public func showClear(_ v: Bool) { mutDialogs { $0.clearConfirm = v } }

    /// An internal note: the bubble shows at once and is confirmed like a reply.
    public func saveNote() {
        let convId = thread.value.activeId
        let text = dialogs.value.noteText.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty || convId.isEmpty { return }
        localSeq += 1
        let o = Outgoing(localId: "optimistic-note-\(AppClock.now())-\(localSeq)", convId: convId, kind: .note, text: text, known: knownIds(convId))
        putOutgoing(o)
        setMsgs(convId) { $0 + [ThreadMsg(id: o.localId, direction: "outbound", sender: "human_agent", text: text, createdAt: Inbox.nowIso(), isNote: true, sendState: "sending")] }
        mutDialogs { $0.note = false; $0.noteText = "" }
        launch { [weak self] in await self?.deliver(o.localId) }
    }

    public func clearHistory() {
        let convId = thread.value.activeId
        if convId.isEmpty { return }
        if dialogs.value.clearing { return }
        mutDialogs { $0.clearing = true }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mutDialogs { $0.clearing = false } }
            do {
                do {
                    _ = try await self.api.conversations.clearHistory(id: convId)
                } catch is CancellationError {
                    return
                } catch {
                    // No answer: a clear is idempotent — an empty thread says it happened.
                    if NetErrors.fate(of: error) == .notSent { throw error }
                    guard let msgs = try? await self.inboxApi.messages(id: convId), !msgs.contains(where: { !$0.isSystem }) else { throw error }
                }
                self.setMsgs(convId) { _ in [] }
                self.mutDialogs { $0.clearConfirm = false }
                self.refresh()
                self.toast("Chat history cleared")
            } catch is CancellationError {
                return
            } catch {
                if NetErrors.conversationGone(error) { self.mutDialogs { $0.clearConfirm = false }; self.dropGone(convId); return }
                // Refused: the 🗑️ was stale (this agent is no longer an admin) — close
                // the dialog; the core's 403 refetch then takes the button away too.
                if self.status(error) == 403 { self.mutDialogs { $0.clearConfirm = false } }
                self.toast(self.status(error) == 403 ? "You don't have permission to clear chat history" : self.failMsg("Failed to clear history", error), .error)
            }
        }
    }

    // ═══════════════════════════ Composer ═══════════════════════════

    /// The customer's detected language — free, from translations cached on inbound rows.
    public func threadLang() -> String? { Inbox.threadLang(of: thread.value) }

    public func txOn() -> Bool { Inbox.txOn(thread.value, composer.value) }

    public func toggleTx() {
        let id = thread.value.activeId
        if id.isEmpty { return }
        let on = txOn()
        mutComposer { $0.txMode[id] = !on }
        scheduleTranslate()
    }

    public func setReplyText(_ v: String) {
        mutComposer { $0.replyText = v }
        scheduleTranslate()
    }

    /// Live preview: pause typing → see what will be sent in the customer's
    /// language. Debounced; the send path reuses a matching preview so nothing
    /// is translated twice.
    private func scheduleTranslate() {
        txJob?.cancel()
        let id = thread.value.activeId
        let t = composer.value.replyText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !txOn() || id.isEmpty || t.count < 2 { mutComposer { $0.txPreview = nil; $0.txBusy = false }; return }
        txJob = Job { [weak self, sleep] in
            do { try await sleep(Self.TRANSLATE_DEBOUNCE_MS) } catch { return }
            guard let self = self else { return }
            self.mutComposer { $0.txBusy = true }
            defer { self.mutComposer { $0.txBusy = false } }
            do {
                let res = try await self.api.conversations.translateReply(id: id, text: t)
                if Task.isCancelled { return }
                let out = res.text.trimmingCharacters(in: .whitespacesAndNewlines)
                self.mutComposer { $0.txPreview = (!out.isEmpty && out != t) ? TxPreview(src: t, text: res.text, lang: res.lang) : nil }
            } catch is CancellationError {
                return
            } catch {
                self.mutComposer { $0.txPreview = nil } // fail open — English still sends
            }
        }
    }

    /// Start replying to a specific message (the Reply button or a swipe).
    public func beginReplyTo(_ msg: ThreadMsg) {
        if msg.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && msg.mediaUrl == nil { return }
        let text = String(msg.body.replacingOccurrences(of: #"^\[comment]\s*"#, with: "", options: .regularExpression).prefix(300))
        let q = Quoted(msgId: msg.id, sender: msg.sender, text: text, channel: activeConv()?.channel ?? "whatsapp",
                       mediaUrl: msg.mediaType == "image" ? msg.mediaUrl : nil, mediaType: msg.mediaType)
        mutComposer { $0.quoted = q }
    }

    public func clearQuote() { mutComposer { $0.quoted = nil } }

    /// Send the reply. The bubble shows at once ("sending…") and the box
    /// clears; the words are never lost after that:
    ///  - delivered → the server's row replaces the bubble;
    ///  - refused (the channel said no, a 4xx, no connection at all) → the
    ///    text goes back in the box, or — if the agent has moved on — the
    ///    bubble turns "Not sent" with Retry / Edit;
    ///  - no answer (a timeout, a dropped connection, a gateway error) → it
    ///    may have reached the customer: the bubble stays "sending…" while the
    ///    thread is re-read, and only a server that shows no such row turns it
    ///    "Not sent". A retry checks once more before sending again.
    public func sendReply() {
        let c = composer.value
        let convId = thread.value.activeId
        if c.replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || convId.isEmpty { return }
        let conv = activeConv()
        // Same channel → a native threaded reply. A quote from ANOTHER channel
        // can't be threaded, so it rides as a text prefix.
        let quoted = c.quoted
        let sameChannel = quoted != nil && quoted!.channel == (conv?.channel ?? "whatsapp")
        let replyToId = sameChannel ? quoted?.msgId : nil
        let prefix = (quoted != nil && !sameChannel) ? "↩ Re (\(Inbox.channelLabel(quoted!.channel))): \"\(quoted!.text.prefix(180))\"\n\n" : ""
        let text = prefix + c.replyText
        let wantTx = txOn()
        let preview = c.txPreview
        localSeq += 1
        let o = Outgoing(localId: "optimistic-\(AppClock.now())-\(localSeq)", convId: convId, kind: .reply, text: text, replyToId: replyToId,
                         typed: c.replyText, quoted: quoted, known: knownIds(convId))
        putOutgoing(o)
        setMsgs(convId) { l in
            var m = ThreadMsg(id: o.localId, direction: "outbound", sender: "human_agent", text: text, createdAt: Inbox.nowIso(), sendState: "sending")
            if let r = replyToId, let q = quoted { m.replyTo = QuotedRef(id: r, text: q.text, sender: q.sender, mediaType: q.mediaType, mediaUrl: q.mediaUrl) }
            return l + [m]
        }
        // The box is free at once: a second tap has nothing to send twice.
        txJob?.cancel()
        mutComposer { $0.replyText = ""; $0.quoted = nil; $0.txPreview = nil; $0.txBusy = false }
        launch { [weak self] in
            guard let self = self else { return }
            if wantTx {
                // Toggle ON → the customer receives their language; the English rides
                // along as the gray line. Any failure falls open to sending English.
                let src = text.trimmingCharacters(in: .whitespacesAndNewlines)
                var tx: (String, String?)? = nil
                if let p = preview, p.src == src { tx = (p.text, p.lang) }
                else if let r = try? await self.api.conversations.translateReply(id: convId, text: src) { tx = (r.text, r.lang) }
                if Task.isCancelled { return }
                if let (txt, lang) = tx, !txt.trimmingCharacters(in: .whitespaces).isEmpty, txt.trimmingCharacters(in: .whitespacesAndNewlines) != src {
                    if var cur = self.outgoing[o.localId] { cur.text = txt; cur.origText = src; cur.origLang = lang; self.outgoing[o.localId] = cur }
                    self.setMsgs(convId) { l in l.map { m in
                        guard m.id == o.localId else { return m }
                        var x = m; x.text = txt; x.translation = src; x.translatedFrom = lang; return x
                    } }
                }
            }
            await self.deliver(o.localId)
        }
    }

    /// The server rows a thread already shows: a send's own row is a NEW one.
    private func knownIds(_ convId: String) -> Set<String> {
        Set((thread.value.messages[convId] ?? []).filter { !$0.isLocal }.map { $0.id })
    }

    private func bubble(_ convId: String, _ localId: String, _ state: String?, _ error: String? = nil) {
        setMsgs(convId) { l in l.map { m in
            guard m.id == localId else { return m }
            var x = m; x.sendState = state; x.sendError = error; return x
        } }
    }

    private func dropBubble(_ convId: String, _ localId: String) { setMsgs(convId) { l in l.filter { $0.id != localId } } }

    private func whoOf(_ convId: String) -> String { inbox.value.cache[convId].map(Inbox.inboxName) ?? "this customer" }

    private func noun(_ k: OutKind) -> String {
        switch k { case .reply: return "Reply"; case .approve: return "Neema's draft"; case .note: return "Note" }
    }

    private func putOutgoing(_ o: Outgoing) {
        if outgoing[o.localId] == nil { outgoingOrder.append(o.localId) }
        outgoing[o.localId] = o
    }

    private func removeOutgoing(_ localId: String) {
        outgoing[localId] = nil
        outgoingOrder.removeAll { $0 == localId }
    }

    private var outgoingInOrder: [Outgoing] { outgoingOrder.compactMap { outgoing[$0] } }

    /// Post one send and decide what its answer means.
    private func deliver(_ localId: String) async {
        guard let o = outgoing[localId] else { return }
        var err: Error? = nil
        do {
            switch o.kind {
            case .reply: try await inboxApi.reply(id: o.convId, text: o.text, replyTo: o.replyToId, originalText: o.origText, originalLang: o.origLang, clientMsgId: o.localId)
            case .approve: _ = try await api.conversations.approveDraft(id: o.convId, text: o.text.isEmpty ? nil : o.text)
            case .note: _ = try await api.conversations.addNote(id: o.convId, text: o.text)
            }
        } catch is CancellationError {
            return
        } catch {
            err = error
        }
        if Task.isCancelled { return }
        if err == nil || NetErrors.fate(of: err!) == .done { await sent(o) }
        else if NetErrors.conversationGone(err!) { dropGone(o.convId) }
        // The session ran out: nothing left the phone. The words stay on their
        // bubble and go by themselves once the agent signs back in.
        else if NetErrors.status(of: err!) == 401 { holdForAuth(localId) }
        else if NetErrors.fate(of: err!) == .unknown { await reconcile(localId) }
        else { notSent(localId, err!) }
    }

    /// Delivered: the server's row replaces the bubble. A failed refetch is still a success.
    private func sent(_ o: Outgoing) async {
        removeOutgoing(o.localId)
        bubble(o.convId, o.localId, nil)
        switch o.kind {
        case .approve: toast("Neema's draft approved & sent")
        case .note: toast("Note saved")
        case .reply: break
        }
        if let msgs = try? await inboxApi.messages(id: o.convId) { applyServer(o.convId, msgs) }
        if Task.isCancelled { return }
        if o.kind != .note { refresh() }
    }

    /// The server refused it (or it never left the phone): nothing went out.
    /// The words go back where they were typed when that is safe — the thread
    /// is open and that box is empty — else the bubble says "Not sent".
    private func notSent(_ localId: String, _ e: Error) {
        guard let o = outgoing[localId] else { return }
        let active = thread.value.activeId == o.convId
        if status(e) == 409 { launch { [weak self] in guard let self = self else { return }; _ = await self.truthOf(o.convId); self.refresh() } }
        let why: String
        switch o.kind {
        case .reply: why = NetErrors.whyFailed(e, "Failed to send message", useDetail: true)
        case .approve: why = failMsg("Failed to approve draft", e)
        case .note: why = failMsg("Failed to save note", e)
        }
        var back = active && !o.retried
        if back {
            switch o.kind {
            case .reply: back = composer.value.replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            case .approve: back = !composer.value.draftVisible
            case .note: back = !dialogs.value.note
            }
        }
        if back {
            removeOutgoing(localId)
            dropBubble(o.convId, localId)
            restore(o)
        } else {
            markFailed(o, why)
        }
        toast(active ? why : "\(noun(o.kind)) to \(whoOf(o.convId)) not sent — \(why)", .error)
    }

    /// Put a send's words back where they were written.
    private func restore(_ o: Outgoing) {
        switch o.kind {
        case .reply:
            editComposer(o.convId) { c in
                c.replyText = c.replyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? o.typed : o.typed + "\n" + c.replyText
                c.quoted = c.quoted ?? o.quoted
            }
        case .approve:
            editComposer(o.convId) { c in c.draftVisible = true; c.draftExpanded = true; c.draftEditing = false; c.draftText = o.text }
        case .note:
            mutDialogs { d in d.note = true; if d.noteText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { d.noteText = o.text } }
        }
    }

    private func holdForAuth(_ localId: String) {
        guard var o = outgoing[localId] else { return }
        o.failed = true; o.authHeld = true
        outgoing[localId] = o
        bubble(o.convId, localId, "failed", Self.AUTH_HELD)
    }

    /// Signed back in: every send the expired session refused goes now, once.
    private func resendHeld() {
        let held = outgoingInOrder.filter { $0.authHeld }
        for var o in held {
            o.failed = false; o.authHeld = false
            outgoing[o.localId] = o
            bubble(o.convId, o.localId, "sending")
            let id = o.localId
            launch { [weak self] in await self?.deliver(id) }
        }
        // Files too — each tray exactly as the agent left it (captions, order).
        let trays = mediaAuthHeld
        mediaAuthHeld = []
        trays.forEach { sendMediaOf($0) }
    }

    private func markFailed(_ o: Outgoing, _ why: String) {
        var m = o; m.failed = true
        outgoing[o.localId] = m
        bubble(o.convId, o.localId, "failed", why)
    }

    /// No answer: re-read the thread a few times (the server may still be
    /// delivering) before deciding. Offline, the check waits for the next
    /// successful read (a poll, the catch-up on reconnect).
    private func reconcile(_ localId: String, delays: [Int64] = InboxViewModel.RECONCILE_DELAYS_MS) async {
        guard var start = outgoing[localId] else { return }
        start.checking = true; start.exhausted = false; start.failed = false
        outgoing[localId] = start
        let convId = start.convId
        for (i, wait) in delays.enumerated() {
            do { try await sleep(wait) } catch { return }
            guard var cur = outgoing[localId] else { return }
            if i == delays.count - 1 { cur.exhausted = true; outgoing[localId] = cur }
            guard let msgs = try? await inboxApi.messages(id: convId) else { continue }
            if Task.isCancelled { return }
            applyServer(convId, msgs)
            if outgoing[localId] == nil { return }
        }
    }

    /// Match sends still on their way against the server's rows: a NEW row
    /// with the same words (a note, a reply, a draft sent) confirms it; a
    /// checked send the server still hasn't got is "Not sent".
    private func settle(_ convId: String, _ msgs: [ThreadMsg]) {
        let mine = outgoingInOrder.filter { $0.convId == convId }
        if mine.isEmpty { return }
        var claimed = Set<String>()
        for o in mine {
            if let hit = msgs.first(where: { s in !o.known.contains(s.id) && !claimed.contains(s.id) && matches(o, s) }) {
                claimed.insert(hit.id)
                removeOutgoing(o.localId)
                dropBubble(convId, o.localId)
                // Checked and found: the same outcome a prompt answer would have had.
                if o.checking && !o.failed {
                    switch o.kind {
                    case .approve: toast("Neema's draft approved & sent")
                    case .note: toast("Note saved")
                    case .reply: break
                    }
                    if o.kind != .note { refresh() }
                }
            } else if o.checking && o.exhausted && !o.failed {
                markFailed(o, "Not delivered — the server never got it.")
                toast("\(noun(o.kind)) to \(whoOf(convId)) didn't go through — tap Retry on it to send again.", .error)
            }
        }
    }

    private func matches(_ o: Outgoing, _ s: ThreadMsg) -> Bool {
        if s.isSystem || s.inbound || s.isLocal { return false }
        let same = s.body.trimmingCharacters(in: .whitespacesAndNewlines) == o.text.trimmingCharacters(in: .whitespacesAndNewlines)
        switch o.kind {
        case .reply: return !s.isNote && s.sender == "human_agent" && same
        case .approve: return !s.isNote && s.sender == "ai" && (o.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || same)
        case .note: return s.isNote && same
        }
    }

    /// Retry a "Not sent" bubble. One whose first attempt got no answer is
    /// looked for on the server first — it may have gone after all — and is
    /// not sent again while the server can't be asked.
    public func retrySend(_ localId: String) {
        guard var o = outgoing[localId], o.failed else { return }
        o.failed = false; o.retried = true; o.authHeld = false
        outgoing[localId] = o
        bubble(o.convId, localId, "sending")
        let wasChecking = o.checking
        launch { [weak self] in
            guard let self = self else { return }
            if wasChecking {
                guard let msgs = try? await self.inboxApi.messages(id: o.convId) else {
                    if let cur = self.outgoing[localId] { self.markFailed(cur, "Still no connection — try again in a moment.") }
                    self.toast("Still can't reach the server — nothing was sent twice.", .error)
                    return
                }
                if Task.isCancelled { return }
                self.applyServer(o.convId, msgs)
                guard var cur = self.outgoing[localId] else { self.toast("It had already gone through — not sent twice."); return }
                cur.checking = false; cur.exhausted = false; cur.known.formUnion(msgs.map { $0.id })
                self.outgoing[localId] = cur
            }
            await self.deliver(localId)
        }
    }

    /// "Edit" on a "Not sent" bubble: the words go back to the box (or the note / draft) and the bubble goes.
    public func editFailed(_ localId: String) {
        guard let o = outgoing[localId], o.failed else { return }
        removeOutgoing(localId)
        dropBubble(o.convId, localId)
        restore(o)
    }

    // ── AI drafts ──
    public func expandDraft(_ v: Bool) { mutComposer { $0.draftExpanded = v } }
    public func toggleDraftEditing() { mutComposer { $0.draftEditing.toggle() } }
    public func setDraftText(_ v: String) { mutComposer { $0.draftText = v } }
    public func dismissDraft() { mutComposer { $0.draftVisible = false; $0.draftExpanded = false; $0.draftText = ""; $0.draftEditing = false } }
    public func draftToComposer() {
        mutComposer { c in c.replyText = c.draftText; c.draftVisible = false; c.draftExpanded = false; c.draftText = ""; c.draftEditing = false }
        scheduleTranslate()
    }

    /// Send the AI draft (as edited). Confirmed exactly like a typed reply.
    public func approveDraft() {
        let convId = thread.value.activeId
        if convId.isEmpty { return }
        // One approval in flight per thread: a double tap never sends the draft twice.
        if outgoing.values.contains(where: { $0.convId == convId && $0.kind == .approve && !$0.failed }) { return }
        let textToSend = composer.value.draftText
        localSeq += 1
        let o = Outgoing(localId: "optimistic-\(AppClock.now())-\(localSeq)", convId: convId, kind: .approve, text: textToSend, known: knownIds(convId))
        putOutgoing(o)
        setMsgs(convId) { $0 + [ThreadMsg(id: o.localId, direction: "outbound", sender: "ai", text: textToSend, createdAt: Inbox.nowIso(), sendState: "sending")] }
        dismissDraft()
        launch { [weak self] in await self?.deliver(o.localId) }
    }

    /// A fresh AI draft (a whole AI turn, on the long client). It lands on the
    /// thread that asked for it, even if the agent has moved on meanwhile.
    public func generateDraft() {
        let convId = thread.value.activeId
        if convId.isEmpty { return }
        if composer.value.generatingDraft { return }
        editComposer(convId) { $0.generatingDraft = true }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.editComposer(convId) { $0.generatingDraft = false } }
            do {
                let d = try await self.api.conversations.generateDraft(id: convId)
                if Task.isCancelled { return }
                if let d = d, !d.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    if self.thread.value.activeId == convId {
                        // The agent asked for it — open immediately.
                        self.mutComposer { $0.draftText = d; $0.draftVisible = true; $0.draftExpanded = true; $0.draftEditing = false }
                        self.toast("Draft generated")
                    } else {
                        // A draft belongs to its thread: it waits there, never in another's box.
                        self.heldDrafts[convId] = d
                        self.toast("Draft ready for \(self.whoOf(convId)) — open their chat to review it.")
                    }
                }
            } catch is CancellationError {
                return
            } catch {
                if NetErrors.conversationGone(error) { self.dropGone(convId); return }
                // A draft is read-only (nothing is sent or saved), so a lost answer
                // loses nothing: a timeout just means ask again.
                let slow = NetErrors.timedOut(error)
                let msg: String
                if NetErrors.status(of: error) == 502 { msg = "Failed to generate draft. Neema couldn't write one just now — try again." } // the model failing, not the network
                else if slow { msg = "Neema took too long to write a draft — nothing was sent. Try again." }
                else { msg = self.failMsg("Failed to generate draft", error) }
                self.toast(msg, slow ? .warning : .error)
            }
        }
    }

    // ═══════════════════════════ Attachments ═══════════════════════════

    private static func stem(_ name: String) -> String {
        guard let dot = name.lastIndex(of: ".") else { return name }
        return String(name[name.startIndex..<dot])
    }

    /// Per-type ceilings BEFORE upload (the server's own): images 5 MB — an
    /// oversized photo is downscaled and re-encoded like WhatsApp does, never
    /// rejected — videos 150 MB (transcoded server-side), audio 16 MB, documents 18 MB.
    public func addMedia(_ files: [URL]) {
        if files.isEmpty { return }
        launch { [weak self] in
            guard let self = self else { return }
            var refused: [String] = []
            var accepted: [PickedMedia] = []
            for uri in files {
                let (name0, size) = self.mediaAccess.meta(of: uri)
                var mime = self.mediaAccess.mimeType(of: uri) ?? Inbox.guessMime(name0)
                var name = name0
                let isVideo = mime.hasPrefix("video/") || name.range(of: #"\.(mov|hevc|mp4|m4v|3gp)$"#, options: [.regularExpression, .caseInsensitive]) != nil
                if isVideo && !mime.hasPrefix("video/") { mime = Inbox.guessMime(name) }
                let (limit, label): (Int64, String) = mime.hasPrefix("image/") ? (Self.MAX_IMAGE, "5 MB")
                    : isVideo ? (Self.MAX_VIDEO, "150 MB")
                    : mime.hasPrefix("audio/") ? (Self.MAX_AUDIO, "16 MB")
                    : (Self.MAX_DOC, "18 MB")
                var bytes: Data? = nil
                // HEIC and other formats WhatsApp won't take become JPEG too.
                let needsJpeg = mime.hasPrefix("image/") && !Self.SENDABLE_IMAGES.contains(mime)
                if (size > limit || needsJpeg) && mime.hasPrefix("image/") && mime != "image/gif" {
                    bytes = await self.mediaAccess.compressImage(at: uri)
                    if bytes != nil { mime = "image/jpeg"; name = Self.stem(name) + ".jpg" }
                }
                if Task.isCancelled { return }
                // upload-media refuses anything outside its ALLOWED_MIME with a 415; say so up front.
                if !Inbox.uploadable(mime: mime, name: name) { refused.append("\(name) can't be sent — unsupported file type"); continue }
                if bytes == nil && size > limit { refused.append("\(name) is too large (max \(label))"); continue }
                accepted.append(PickedMedia(id: "\(name)-\(size)-\(UUID().uuidString.lowercased().prefix(6))", file: uri, name: name, mime: mime,
                                            size: bytes.map { Int64($0.count) } ?? size, bytes: bytes))
            }
            refused.forEach { self.toast($0, .error) }
            if !accepted.isEmpty { self.mutComposer { $0.media += accepted } }
        }
    }

    /// A file already prepared (tests, a share-sheet item): straight into the tray.
    public func pickMedia(_ items: [PickedMedia]) { mutComposer { $0.media = items } }

    public func setMediaCaption(_ id: String, _ caption: String) {
        mutComposer { c in c.media = c.media.map { m in var x = m; if x.id == id { x.caption = caption }; return x } }
    }

    public func removeMedia(_ id: String) { mutComposer { c in c.media.removeAll { $0.id == id } } }
    public func clearMedia() { mutComposer { $0.media = [] } }
    public func dismissLostMedia() { mutComposer { $0.lostMedia = [] } }

    /// Send sequentially; each file carries its OWN caption (or none). A file
    /// that fails stays in the tray with its caption and the reason; one whose
    /// upload got no answer is looked for in the thread before it is called
    /// failed — and again before a retry uploads it a second time.
    public func sendMedia() { sendMediaOf(thread.value.activeId) }

    private func composerOf(_ convId: String) -> ComposerUi? {
        let active = thread.value.activeId
        return (!active.isEmpty && composerKey(active) == composerKey(convId)) ? composer.value : stash[composerKey(convId)]
    }

    private func sendMediaOf(_ convId: String) {
        guard let c = composerOf(convId) else { return }
        let items = c.media
        if items.isEmpty || convId.isEmpty || c.uploading { return }
        editComposer(convId) { c in c.uploading = true; c.media = c.media.map { m in var x = m; x.error = nil; return x } }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.editComposer(convId) { $0.uploading = false } }
            var sent: [ThreadMsg] = []
            var sentIds = Set<String>()
            var known = self.knownIds(convId)
            var failed = 0
            for item in items {
                // A file whose last attempt ended without an answer may be there already.
                if item.unconfirmed, let hit = await self.findUpload(convId, item, known) {
                    sent.append(hit); sentIds.insert(item.id); known.insert(hit.id); continue
                }
                if Task.isCancelled { return }
                do {
                    let m = try await self.inboxApi.upload(convId: convId, item: item)
                    if Task.isCancelled { return }
                    sent.append(m); sentIds.insert(item.id); known.insert(m.id)
                } catch is CancellationError {
                    return
                } catch {
                    if NetErrors.conversationGone(error) { self.dropGone(convId); return }
                    let unknown = NetErrors.fate(of: error) == .unknown
                    if unknown, let hit = await self.findUpload(convId, item, known) {
                        sent.append(hit); sentIds.insert(item.id); known.insert(hit.id); continue
                    }
                    if Task.isCancelled { return }
                    failed += 1
                    let expired = NetErrors.status(of: error) == 401
                    if expired && !self.mediaAuthHeld.contains(convId) { self.mediaAuthHeld.append(convId) }
                    let why = expired ? "your session expired — it sends once you sign in again" : Inbox.uploadError(of: error)
                    self.editComposer(convId) { c in c.media = c.media.map { m in
                        guard m.id == item.id else { return m }
                        var x = m; x.error = why; x.unconfirmed = unknown; return x
                    } }
                    // The SessionExpired dialog says it already; no toast over it.
                    if !expired { self.toast("\(item.name): \(why)", .error) }
                }
            }
            if !sent.isEmpty {
                self.setMsgs(convId) { Inbox.mergeThread($0, sent) }
                // Only what went out leaves the tray; a failed file waits for a retry.
                self.editComposer(convId) { c in c.media.removeAll { sentIds.contains($0.id) } }
                self.refresh()
                let msg = failed > 0 ? "Sent \(sent.count), \(failed) failed" : (sent.count > 1 ? "\(sent.count) files sent" : "Media sent")
                self.toast(msg, failed > 0 ? .error : .success)
            }
        }
    }

    /// The thread's new outbound file matching `item` (its kind and caption), if the server has it.
    private func findUpload(_ convId: String, _ item: PickedMedia, _ known: Set<String>) async -> ThreadMsg? {
        guard let msgs = try? await inboxApi.messages(id: convId) else { return nil }
        let ext = item.name.split(separator: ".").count > 1 ? String(item.name.split(separator: ".").last ?? "").lowercased() : ""
        let kind: String? = item.mime.hasPrefix("image/") ? "image"
            : (item.mime.hasPrefix("video/") || ["mov", "hevc", "mp4", "m4v"].contains(ext)) ? "video"
            : item.mime.hasPrefix("audio/") ? "audio" : nil
        let cap = item.caption.trimmingCharacters(in: .whitespacesAndNewlines)
        return msgs.first { s in
            guard !known.contains(s.id), !s.inbound, !s.isSystem, !s.isNote, s.sender == "human_agent", let mt = s.mediaType else { return false }
            let kindOk = kind == nil || mt == kind! || mt.hasPrefix("\(kind!)/")
            let capOk = cap.isEmpty || s.body.trimmingCharacters(in: .whitespacesAndNewlines) == cap || (s.mediaCaption ?? "").trimmingCharacters(in: .whitespacesAndNewlines) == cap
            return kindOk && capOk
        }
    }

    // ═══════════════════════════ Reach-out (Ask Neema, invite, call) ═══════════════════════════

    /// Read-only: a failure just says why, and the question stays in the box.
    public func askNeema(_ question: String) async -> String {
        do {
            return try await api.askNeema(convId: thread.value.activeId, question: question).answer
        } catch {
            let st = NetErrors.status(of: error)
            if NetErrors.conversationGone(error) { return "This conversation no longer exists." }
            if st == 0 && NetErrors.timedOut(error) { return "Neema took too long to answer — try again." }
            if st == 0 || st == 401 || st == 429 { return NetErrors.whyFailed(error, "") }
            return "Couldn't check right now — try again."
        }
    }

    /// Neema delivers the confirmed FACTS in her own voice; the thread stays in
    /// AI mode. This one reaches the customer, so a lost answer is checked: a
    /// NEW message from Neema in the thread means it went; otherwise the agent
    /// is told it may still be on its way — never "failed", which invites a
    /// second send.
    public func answerViaNeema(_ facts: String) async -> (Bool, String) {
        let convId = thread.value.activeId
        let known = knownIds(convId)
        do {
            return (true, "Neema sent: “\(try await api.answerViaNeema(convId: convId, facts: facts).sent)”")
        } catch {
            // Only to classify (the web tests its error message for "window"); never shown.
            let body = ((error as? ApiError)?.body ?? "").lowercased()
            let st = NetErrors.status(of: error)
            if NetErrors.fate(of: error) == .unknown {
                let hit = (try? await inboxApi.messages(id: convId))?.last { !known.contains($0.id) && !$0.inbound && !$0.isSystem && !$0.isNote && $0.sender == "ai" }
                if let hit = hit {
                    loadMessages(convId, silent: true)
                    return (true, "Neema sent: “\(hit.body)”")
                }
                return (false, "No answer from the server — Neema may still be sending it. Watch the thread before sending it again.")
            }
            if NetErrors.conversationGone(error) { return (false, "This conversation no longer exists.") }
            if status(error) == 409 || body.contains("window") { return (false, "Outside the messaging window — reply yourself when they next write.") }
            if st == 0 || st == 401 || st == 429 { return (false, NetErrors.whyFailed(error, "")) }
            return (false, "Couldn't send right now — try again.")
        }
    }

    public func invite(phone: String, name: String?) async -> InviteResult {
        do {
            _ = try await api.whatsappInvite(phone: phone, name: name)
            return .sent
        } catch {
            if NetErrors.fate(of: error) == .unknown {
                return .unknown(message: "No answer from the server — the invite may still go through. Check with the customer before sending another.")
            }
            return .refused
        }
    }

    /// Business-initiated WhatsApp call. The call screen carries every outcome;
    /// only a refusal the screen doesn't show ("Already in a call") is a toast.
    /// Only ever a real number: a web-chat visitor's `web_<hash>` key (or a Meta
    /// PSID) is not dialable, whatever digits it happens to contain.
    public func call(waId: String, name: String?) {
        if Inbox.isWebVisitor(waId) || waId.contains(where: { !($0.isASCII && $0.isNumber) }) || !(7...15).contains(waId.count) { return }
        let active = thread.value.activeId
        let convId: String? = inbox.value.cache[active]?.channel == "whatsapp" ? active : nil
        launch { [weak self] in
            guard let self = self else { return }
            let r = await self.host.placeCall(waId: waId, name: name, convId: convId)
            if case .failed(let m) = r { self.toast(m.trimmingCharacters(in: .whitespaces).isEmpty ? "Couldn't place the call" : m, .error) }
        }
    }

    /// "Use as reply" on a call's summary card: the AI's follow-up goes in the composer — never sent by itself.
    public func useAsReply(_ text: String) {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { return }
        mutComposer { c in
            let cur = c.replyText
            c.replyText = cur.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? t : trimEnd(cur) + "\n" + t
        }
    }

    // ═══════════════════════════ Surviving process death (InboxMemory) ═══════════════════════════

    /// Changes when a send starts, settles or fails: the outbox on disk follows.
    private func outboxSig() -> [String] { outgoingInOrder.map { "\($0.localId)|\($0.failed)|\($0.authHeld)|\($0.text)" } }

    private func buildMemory() -> InboxMemory {
        let t = thread.value
        let f = inbox.value.filters
        let l = list.value
        let d = dialogs.value
        let live = composer.value
        var composers: [String: SavedComposer] = [:]
        for (k, c) in stash { let s = c.saved(); if !s.isEmpty { composers[k] = s } }
        if !t.activeId.isEmpty {
            let key = composerKey(t.activeId)
            let saved = live.saved()
            if saved.isEmpty { composers[key] = nil } else { composers[key] = saved }
        }
        var notes = noteStash
        if !t.activeId.isEmpty && d.note && !d.noteText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { notes[t.activeId] = d.noteText }
        let outbox: [SavedOutgoing] = outgoingInOrder.compactMap { o in
            guard let b = t.messages[o.convId]?.first(where: { $0.id == o.localId }) else { return nil }
            var bubble = b; bubble.sendState = nil; bubble.sendError = nil
            return SavedOutgoing(localId: o.localId, convId: o.convId, kind: o.kind.rawValue, text: o.text, replyToId: o.replyToId,
                                 origText: o.origText, origLang: o.origLang, typed: o.typed, quoted: o.quoted, known: Array(o.known).sorted(),
                                 failed: o.failed, checking: o.checking, retried: o.retried, authHeld: o.authHeld, bubble: bubble, error: b.sendError)
        }
        var m = InboxMemory()
        m.activeId = t.activeId; m.threadOpen = t.threadOpen
        m.tab = f.tab; m.channel = f.channel; m.mode = f.mode; m.tag = f.tag; m.search = l.search; m.q = f.q; m.showFilters = l.showFilters
        m.composers = composers; m.txMode = live.txMode; m.notes = notes
        m.dialog = (d.transfer && !t.activeId.isEmpty) ? "transfer" : nil
        m.outbox = outbox
        return m
    }

    private func writeMemory(_ m: InboxMemory) {
        guard let id = memoryFor else { return }
        host.snapshots.write(id, Inbox.MEMORY_KEY, m)
    }

    /// Coalesced: a burst of keystrokes is one write.
    private func saveSoon() {
        if !memoryReady { return }
        memoryJob?.cancel()
        memoryJob = Job { [weak self, sleep] in
            do { try await sleep(Self.MEMORY_DEBOUNCE_MS) } catch { return }
            guard let self = self else { return }
            self.writeMemory(self.buildMemory())
        }
    }

    /// Now (the app is going to the background, where the system may kill it).
    public func saveMemory() {
        if !memoryReady { return }
        memoryJob?.cancel()
        writeMemory(buildMemory())
    }

    private func restoreFilters(_ m: InboxMemory) {
        // The search box as typed runs as the query (its pause may not have passed before the app died).
        var f = m.filters
        f.q = m.search
        mutList { $0.search = m.search; $0.showFilters = m.showFilters }
        if f != inbox.value.filters {
            mutInbox { s in s.filters = f; s.orderKey = Inbox.filterKey(of: f); s.orderIds = [] }
        }
    }

    private func restoreWork(_ m: InboxMemory) {
        // Anything that landed before the memory did (a camera photo delivered on restore) is kept.
        let early = composer.value.media
        for (k, c) in m.composers where stash[k] == nil { stash[k] = c.liveWithoutMedia() }
        mutComposer { c in c.txMode = m.txMode.merging(c.txMode) { _, live in live } }
        for (k, v) in m.notes where noteStash[k] == nil { noteStash[k] = v }
        restoreMedia(m.composers)
        for so in m.outbox { restoreSend(so) }
        let id = m.activeId
        if id.isEmpty { return }
        func open() {
            // A deep link that arrived meanwhile, or a thread the agent already opened, wins.
            if host.openConvKey.value != nil || !thread.value.activeId.isEmpty { return }
            select(id, openThread: m.threadOpen)
            if !early.isEmpty { mutComposer { c in c.media += early.filter { e in !c.media.contains { $0.id == e.id } } } }
            if m.dialog == "transfer" { showTransfer(true) }
        }
        if inbox.value.cache[id] != nil { open(); return }
        launch { [weak self] in
            guard let self = self else { return }
            // Gone, or offline: the list shows; the words wait in the stash.
            guard let row = try? await self.inboxApi.get(id: id) else { return }
            if Task.isCancelled { return }
            self.reveal([row])
            open()
        }
    }

    /// A send the app was killed during: shown again, and looked for on the server — never sent twice.
    private func restoreSend(_ so: SavedOutgoing) {
        guard let kind = OutKind(rawValue: so.kind) else { return }
        if outgoing[so.localId] != nil { return }
        let failed = so.failed || so.authHeld
        let o = Outgoing(localId: so.localId, convId: so.convId, kind: kind, text: so.text, replyToId: so.replyToId, origText: so.origText,
                         origLang: so.origLang, typed: so.typed, quoted: so.quoted, known: Set(so.known), checking: so.checking || !failed,
                         failed: failed, retried: so.retried)
        putOutgoing(o)
        let why = so.authHeld ? "Not sent — your session had expired. Tap Retry to send it." : (so.error ?? "Not sent")
        setMsgs(o.convId) { l in
            if l.contains(where: { $0.id == o.localId }) { return l }
            var b = so.bubble
            b.sendState = failed ? "failed" : "sending"
            b.sendError = failed ? why : nil
            return l + [b]
        }
        if !failed { launch { [weak self] in await self?.reconcile(o.localId, delays: Self.RESTORE_CHECK_MS) } }
    }

    /// Files picked before the app was killed come back only if the system still
    /// lets the app read them. The rest are named in the composer so they can be picked again.
    private func restoreMedia(_ composers: [String: SavedComposer]) {
        let withMedia = composers.filter { !$0.value.media.isEmpty }
        if withMedia.isEmpty { return }
        launch { [weak self] in
            guard let self = self else { return }
            for (key, c) in withMedia {
                var kept: [PickedMedia] = []
                var lost: [String] = []
                for sm in c.media {
                    let uri = URL(string: sm.uri)
                    let readable = uri.map { self.mediaAccess.readable($0) } ?? false
                    guard let u = uri, readable else { lost.append(sm.name); continue }
                    let bytes = sm.reencoded ? await self.mediaAccess.compressImage(at: u) : nil
                    if sm.reencoded && bytes == nil { lost.append(sm.name); continue }
                    kept.append(PickedMedia(id: "\(sm.name)-\(sm.size)-\(UUID().uuidString.lowercased().prefix(6))", file: u, name: sm.name, mime: sm.mime,
                                            size: bytes.map { Int64($0.count) } ?? sm.size, bytes: bytes, caption: sm.caption, error: sm.error, unconfirmed: sm.unconfirmed))
                }
                if Task.isCancelled { return }
                self.editComposerKey(key) { c in
                    c.media += kept
                    var l = c.lostMedia
                    for n in lost where !l.contains(n) { l.append(n) }
                    c.lostMedia = l
                }
            }
        }
    }

    private func editComposerKey(_ key: String, _ t: (inout ComposerUi) -> Void) {
        let active = thread.value.activeId
        if !active.isEmpty && composerKey(active) == key { mutComposer(t) }
        else { var c = stash[key] ?? ComposerUi(); t(&c); stash[key] = c }
    }
}

private func trimEnd(_ s: String) -> String {
    var out = Substring(s)
    while let l = out.last, l.isWhitespace || l.isNewline { out.removeLast() }
    return String(out)
}

extension Inbox {
    private static let stampFormatter: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    /// `Instant.ofEpochMilli(ms).toString()`.
    public static func iso(ofMillis ms: Int64) -> String {
        stampFormatter.string(from: Date(timeIntervalSince1970: TimeInterval(ms) / 1000))
    }
}
