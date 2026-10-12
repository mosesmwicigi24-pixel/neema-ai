import Foundation

/// What the calls console needs from the shell (Android's `DashboardViewModel` as the console sees it).
public protocol CallsHost: AnyObject {
    var api: NeemaApi { get }
    var foreground: Watched<Bool> { get }
    var socketConnected: Watched<Bool> { get }
    var socketEvents: Signal<JSONValue> { get }
    /// The softphone (process-wide): call back, and which channels can call.
    var calls: CallManager { get }
    /// `?view=calls&caller=<wa_id>` (a missed-call alert): consumed by the console once it opened the caller.
    var callsFocusKey: Watched<String?> { get }
    func toast(_ message: String, _ type: ToastType)
}

/// The expandable transcript + AI summary panel's state for the open call row.
public struct TranscriptUi: Equatable, Sendable {
    public var callId: String
    /// nil while the first load is in flight (or it failed: see `loadErr`) — the panel reads "Loading…".
    public var data: CallTranscript? = nil
    /// The transcript could not be fetched and there is nothing to show: the panel offers Retry.
    public var loadErr: String? = nil
    public var showFull: Bool = false
    public var busy: Bool = false
    public var err: String? = nil
    public init(callId: String) { self.callId = callId }
}

/// GET /admin/calls answers the newest 50 by default.
let CALL_LOG_PAGE = 50

/// `row` placed among `rows` (newest first) by its start time. Older than every
/// row held: appended while the log is shorter than a page (it holds every
/// call), else nil — it belongs to a page not shown and the next read has it.
func insertByTime(_ rows: [Call], _ row: Call, page: Int = CALL_LOG_PAGE) -> [Call]? {
    let t = Fmt.millis(row.startedAt)
    var at = -1
    if let t = t { at = rows.firstIndex { (Fmt.millis($0.startedAt) ?? Int64.min) <= t } ?? -1 }
    if at >= 0 { return Array(rows[0..<at]) + [row] + Array(rows[at...]) }
    if rows.count < page { return rows + [row] }
    return nil
}

/// Stable, unique keys for a lazy list of call rows: the row id (else the call id), a `#n` on repeats.
public func rowKeys(_ rows: [Call]) -> [String] {
    var seen: [String: Int] = [:]
    seen.reserveCapacity(rows.count * 2)
    return rows.map { c in
        let base = c.id.isEmpty ? c.callId : c.id
        let n = (seen[base] ?? 0) + 1
        seen[base] = n
        return n == 1 ? base : "\(base)#\(n)"
    }
}

/// State for the Calls view (components/views/CallsView.tsx, CALLING_UX.md §7):
/// the call log (polled every 60 s as a fallback, reloaded 500 ms after call WS
/// events — a burst coalesces into one reload — at once when the socket
/// reconnects or the app returns to the foreground, and a `call_update` row
/// merged in place without a read), the All / Follow-ups filter, the selected
/// call's details, and the open transcript panel (lazily fetched, polled every
/// 5 s while a transcription job runs). From a row: call back, and mark a
/// follow-up done. Android `feature/calls/CallsViewModel.kt`.
@MainActor
public final class CallsViewModel {
    /// The web's fallback interval (the socket frames are the real path).
    nonisolated public static let POLL_MS: Int64 = 60_000
    /// CallsView's `setTimeout(load, 500)` after a call frame.
    nonisolated public static let FRAME_RELOAD_MS: Int64 = 500
    nonisolated public static let TRANSCRIPT_POLL_MS: Int64 = 5_000

    public let host: CallsHost
    private let api: NeemaApi
    private let sleep: Sleeper

    /// nil = still loading (the web's `calls === null`).
    public let calls = Watched<[Call]?>(nil)
    public let refreshing = Watched<Bool>(false)
    /// Why the last load of the log failed (nil once one succeeds). The web
    /// shows "No calls yet" when offline; here the log says it couldn't load,
    /// keeps what it last had, and offers Retry.
    public let loadError = Watched<String?>(nil)
    /// The "Follow-ups" filter: only the missed / callback calls nobody has returned yet.
    public let followUpsOnly = Watched<Bool>(false)
    /// The app filter (CallsView.tsx chFilter): "all" | "whatsapp" | "messenger".
    public let channelFilter = Watched<String>("all")
    /// Which channels can call now (the softphone's read of GET /calls/channels).
    public var channels: Watched<CallChannels?> { host.calls.channels }
    /// Follow-ups being marked done (their button waits; a second tap sends nothing).
    public let doneBusy = Watched<Set<String>>([])
    /// Clicking a call opens the caller's full CRM panel right here.
    public let selected = Watched<Call?>(nil)
    public let transcript = Watched<TranscriptUi?>(nil)
    private var transcriptPoll: Job?
    /// The reload a burst of call frames coalesces into (the web schedules one per frame).
    private var frameReload: Job?
    private var reads: SingleFlight<Bool>!
    public private(set) var life: ScreenLife!
    private var subs: [Subscription] = []
    private var focusing: String?
    private var closed = false
    public var uiAttached = false
    /// A caller restored before the log has loaded: opened once the row is read.
    private var pendingSelect: String?

    /// A read of the log is on the wire (tests wait on it).
    public var busy: Bool { reads.inFlight }

    public init(host: CallsHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        self.api = host.api
        self.sleep = sleep
        // The log's reads, one on the wire at a time: the 60 s tick, a burst of
        // call frames, a reconnect, a return to the app, a pull and a Retry share
        // round trips on a slow network instead of stacking.
        reads = SingleFlight { [weak self] in
            guard let self = self else { return false }
            let r: Result<[Call], Error>
            do { r = .success(try await self.api.calls.list()) } catch { r = .failure(error) }
            await self.land(r)
            if case .success = r { return true }
            return false
        }
        let reads = self.reads!
        // CallsView's lifecycle: the fallback tick runs only while the log is on
        // display and the app in front; coming back to it (or to the app), or
        // the socket reconnecting, reloads at once.
        life = ScreenLife(foreground: host.foreground, connected: host.socketConnected, pollMs: Self.POLL_MS, catchUpWindowMs: 0, sleep: sleep,
                          poll: { _ = try await reads.run() }, catchUp: { _ = try await reads.run() })
        load()
        // Call frames reload the log 500 ms later (a burst is one reload) while
        // it is on display; off-screen, the next visit catches up anyway.
        subs.append(host.socketEvents.observe { [weak self] e in onMain { self?.onFrame(e) } })
    }

    private func onFrame(_ e: JSONValue) {
        let t = e.str("type")
        // A changed row arrives whole: merged in place, no read.
        if t == "call_update" { if let row = e["call"], row.objectValue != nil { mergeRow(row) }; return }
        if (t == "incoming_call" || t == "call_ended" || t == "call_answered") && life.active && frameReload?.isActive != true {
            frameReload = Job { [weak self] in
                guard let self = self else { return }
                do { try await self.sleep(Self.FRAME_RELOAD_MS) } catch { return }
                _ = try? await self.reads.run()
            }
        }
    }

    public func load() { Task { @MainActor [weak self] in _ = try? await self?.reads.run() } }

    /// A `call_update` row: replaces its row where it is; a row the log doesn't
    /// hold goes in at its place by time (the log is newest first). An update
    /// for a call older than everything shown is left for the next read.
    func mergeRow(_ raw: JSONValue) {
        guard let row = try? NeemaJSON.decode(Call.self, from: raw), !row.callId.isEmpty, let cur = calls.value else { return }
        if cur.contains(where: { $0.callId == row.callId }) { calls.value = cur.map { $0.callId == row.callId ? row : $0 } }
        else { calls.value = insertByTime(cur, row) ?? cur }
        if selected.value?.callId == row.callId { selected.value = row }
    }

    /// A call back goes out on the call's own app — Messenger only while it can
    /// call (the server's switch), WhatsApp whenever there is a number.
    public func canCallBack(_ c: Call) -> Bool {
        if channelOf(c.channel) == CallWords.MESSENGER { return !(c.externalId ?? "").isEmpty && channels.value?.messenger.outbound == true }
        return !(c.waId ?? "").isEmpty
    }

    /// "Mark follow-up done": off the Follow-ups list at once; put back, with the
    /// reason, if the server says no (a timeout may have landed — the next read
    /// shows the truth).
    public func markFollowUpDone(_ call: Call) {
        // The row as it is now (the caller may hold one from before an earlier tap).
        let c = calls.value?.first { $0.callId == call.callId } ?? call
        if !c.followUpOpen || doneBusy.value.contains(c.callId) { return }
        doneBusy.value.insert(c.callId)
        func set(_ open: Bool) {
            calls.value = calls.value?.map { var r = $0; if r.callId == c.callId { r.followUpOpen = open }; return r }
            if var s = selected.value, s.callId == c.callId { s.followUpOpen = open; selected.value = s }
        }
        set(false)
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            defer { self.doneBusy.value.remove(c.callId) }
            do { _ = try await self.api.calls.followUpDone(callId: c.callId) }
            catch is CancellationError { return }
            catch {
                if let a = error as? ApiError, a.status == 0, a.body.hasPrefix("timed out") { _ = try? await self.reads.run() }
                else {
                    set(true)
                    self.host.toast(self.actionErrorText(error, "mark the follow-up done"), .error)
                }
            }
        }
    }

    /// The row's call button / "Call back": a call to them now on the call's own app (the call screen says the rest).
    public func callBack(_ c: Call) {
        if !canCallBack(c) { return }
        let handle = callHandle(c)
        if handle.isEmpty { return }
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            let r = await self.host.calls.initiateCall(to: handle, name: c.name, conversationId: c.conversationId, channel: channelOf(c.channel))
            guard case .failure(let err) = r else { return }
            if (err as? CallError)?.shown == true { return }
            let m = ((err as? CallError)?.message ?? "").trimmingCharacters(in: .whitespaces)
            self.host.toast(m.isEmpty ? "Couldn't place the call" : m, .error)
        }
    }

    /// Pull-to-refresh / Retry: the spinner shows until the answer (or the failure) is in.
    public func refresh() {
        if refreshing.value { return }
        refreshing.value = true
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            _ = try? await self.reads.run()
            self.refreshing.value = false
        }
    }

    /// One answer lands (reads never overlap, so it is the newest). A failure
    /// never clears the rows already on screen; a first load that fails leaves
    /// an empty log with the reason and a Retry.
    private func land(_ r: Result<[Call], Error>) {
        switch r {
        case .success(let list):
            calls.value = list
            loadError.value = nil
            // The open caller follows the log: a restored one is found again, an open one shows its row as it is now.
            let want = (pendingSelect ?? selected.value?.id).flatMap { $0.isEmpty ? nil : $0 }
            if let want = want {
                pendingSelect = nil
                if let row = list.first(where: { $0.id == want }) { selected.value = row }
            }
        case .failure(let e):
            // The server never refuses the log by role today; if it ever does, the HTTP layer's 403 re-read runs.
            if calls.value == nil { calls.value = [] }
            loadError.value = callsErrorText(e)
        }
    }

    /// Deep-link focus (`?view=calls&caller=<wa_id>`, a missed-call alert):
    /// open the caller panel for that customer. The log on hand may be minutes
    /// old — the alert is usually about a call it doesn't hold yet — so when
    /// it has no call with them it is read again before saying so. A read that
    /// fails says nothing false ("no calls yet"): the log's own error shows.
    public func consumeFocus(_ key: String) {
        if focusing == key { return }
        let wa = key.hasPrefix("+") ? String(key.dropFirst()) : key
        func match(_ list: [Call]) -> Call? { list.sorted { ($0.startedAt ?? "") > ($1.startedAt ?? "") }.first { $0.waId == wa || $0.externalId == wa } }
        if let list = calls.value, let hit = match(list) { selected.value = hit; host.callsFocusKey.value = nil; return }
        focusing = key
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            defer { if self.focusing == key { self.focusing = nil } }
            let read = (try? await self.reads.run()) ?? false
            if self.host.callsFocusKey.value != key { return }   // another link came meanwhile
            let found = self.calls.value.flatMap(match)
            if let f = found { self.selected.value = f }
            else if read { self.host.toast("No calls with this customer yet — showing the full call log.", .warning) }
            self.host.callsFocusKey.value = nil
        }
    }

    public func select(_ c: Call?) { selected.value = c; pendingSelect = nil }

    // ── Process death: the Follow-ups filter and the open call come back ──
    public func saveUi() -> String {
        var o: [String: JSONValue] = ["followUps": .bool(followUpsOnly.value), "channel": .string(channelFilter.value)]
        if let s = selected.value?.id ?? pendingSelect { o["selected"] = .string(s) }
        return JSONValue.object(o).text
    }

    public func restoreUi(_ saved: String) {
        guard let o = JSONValue.parse(saved)?.objectValue else { return }
        if let f = o["followUps"]?.boolValue { followUpsOnly.value = f }
        if let c = o["channel"]?.stringValue, ["all", CallWords.WHATSAPP, CallWords.MESSENGER].contains(c) { channelFilter.value = c }
        guard let id = o["selected"]?.stringValue, !id.isEmpty else { return }
        if let row = calls.value?.first(where: { $0.id == id }) { selected.value = row } else { pendingSelect = id }
    }

    /// Restore once per model, the first time a screen attaches.
    @discardableResult
    public func restoreIfFresh(_ saved: String?) -> Bool {
        if uiAttached { return false }
        uiAttached = true
        guard let s = saved, !s.isEmpty else { return false }
        restoreUi(s)
        return true
    }

    // ── Transcript panel ─────────────────────────────────────────────────
    /// The panel's Retry after a failed first load.
    public func retryTranscript() {
        guard var cur = transcript.value else { return }
        cur.loadErr = nil
        transcript.value = cur
        loadTranscript(cur.callId)
    }

    public func toggleTranscript(_ callId: String) {
        if transcript.value?.callId == callId {
            transcriptPoll?.cancel(); transcriptPoll = nil; transcript.value = nil
            return
        }
        transcriptPoll?.cancel()
        transcript.value = TranscriptUi(callId: callId)
        loadTranscript(callId)
        transcriptPoll = Job { [weak self] in
            // A transcription job takes ~1-2 min — 5 s resolution is plenty, and
            // neither a backgrounded app nor another screen keeps polling for it.
            // Each fetch finishes before the next wait starts: polls never stack.
            while !Task.isCancelled {
                guard let self = self else { return }
                do { try await self.sleep(Self.TRANSCRIPT_POLL_MS) } catch { return }
                guard let cur = self.transcript.value, cur.callId == callId else { return }
                let st = cur.data?.status
                if (st == "pending" || st == "processing") && self.life.active { await self.fetchTranscript(callId) }
            }
        }
    }

    /// One fetch. A failure keeps what the panel already shows; with nothing
    /// to show yet it says why and offers Retry instead of "Loading…" forever.
    private func fetchTranscript(_ callId: String) async {
        let r: Result<CallTranscript, Error>
        do { r = .success(try await api.calls.transcript(callId: callId)) } catch { r = .failure(error) }
        guard var cur = transcript.value, cur.callId == callId else { return }
        switch r {
        case .success(let t): cur.data = t; cur.loadErr = nil
        case .failure(let e):
            if cur.data != nil { return }
            cur.loadErr = (e as? ApiError)?.status == 404 ? "This call is no longer in the log." : actionErrorText(e, "load the transcript")
        }
        transcript.value = cur
    }

    private func loadTranscript(_ callId: String) { Task { @MainActor [weak self] in await self?.fetchTranscript(callId) } }

    public func toggleFull() { if var t = transcript.value { t.showFull.toggle(); transcript.value = t } }

    public func runTranscribe() {
        guard var cur = transcript.value, !cur.busy else { return }   // one request at a time, however fast the taps
        let id = cur.callId
        cur.busy = true; cur.err = nil
        transcript.value = cur
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            defer { if var t = self.transcript.value, t.callId == id { t.busy = false; self.transcript.value = t } }
            do {
                _ = try await self.api.calls.transcribe(callId: id)
                await self.fetchTranscript(id)
            } catch is CancellationError {
                return
            } catch {
                if let a = error as? ApiError, a.status == 0 {
                    // No answer: the job may have started anyway. Show the truth.
                    await self.fetchTranscript(id)
                    let st = self.transcript.value.flatMap { $0.callId == id ? $0.data?.status : nil }
                    if st == "pending" || st == "processing" { return }
                }
                // routers/admin.py calls_transcribe raises 409 for two reasons; the
                // web shows the WHISPER copy for both, which misleads when the call
                // simply has no recording.
                let msg: String
                if let a = error as? ApiError, a.status == 409, a.detail.hasPrefix("No recording") { msg = "No recording was captured for this call." }
                else if let a = error as? ApiError, a.status == 409 { msg = "Turn on transcription on the server first (WHISPER_ENABLED)." }
                else if let a = error as? ApiError, a.status == 0 { msg = self.actionErrorText(error, "start transcription") }
                else if let a = error as? ApiError, a.status == 429 { msg = "Too many requests — wait a moment and try again." }
                else { msg = "Couldn't start transcription." }
                if var t = self.transcript.value, t.callId == id { t.err = msg; self.transcript.value = t }
            }
        }
    }

    /// Plain words for a failed request: never a raw HTML error page. The
    /// server's detail is used only when it is written for people.
    func callsErrorText(_ e: Error, fallback: String = "Couldn't load calls.") -> String {
        guard let a = e as? ApiError else { return fallback }
        if a.status == 0 && a.body.hasPrefix("timed out") { return "The server took too long to answer — try again." }
        if a.status == 0 { return "No connection — check your internet and try again." }
        if a.status == 401 { return "Your session expired — sign in again." }
        if a.status == 403 { return "You don't have access to calls." }
        if a.status == 429 { return "Too many requests — wait a moment and try again." }
        if a.status >= 500 { return "The server had a problem — try again shortly." }
        return fallback
    }

    /// "No connection — couldn't load the transcript.": the failure, and what it stopped.
    func actionErrorText(_ e: Error, _ action: String) -> String {
        guard let a = e as? ApiError else { return "Couldn't \(action)." }
        if a.status == 0 && a.body.hasPrefix("timed out") { return "The server took too long — couldn't \(action)." }
        if a.status == 0 { return "No connection — couldn't \(action)." }
        if a.status == 401 { return "Your session expired — sign in again." }
        if a.status == 429 { return "Too many requests — wait a moment and try again." }
        if a.status >= 500 { return "The server had a problem — couldn't \(action)." }
        return "Couldn't \(action)."
    }

    /// Relative time, recomputed on each render.
    public func ago(_ iso: String?) -> String { iso == nil ? "" : Fmt.timeAgo(iso) }

    public func close() {
        if closed { return }
        closed = true
        life.close()
        transcriptPoll?.cancel(); frameReload?.cancel()
        reads.cancel()
        for s in subs { s.cancel() }
        subs.removeAll()
    }
}
