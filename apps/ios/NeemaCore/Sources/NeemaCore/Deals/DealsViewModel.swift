import Foundation

/// The shell as the deals screen sees it: the socket, the API and the toasts.
public protocol DealsHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var socketConnected: Watched<Bool> { get }
    var socketEvents: Signal<JSONValue> { get }
    var api: NeemaApi { get }
    func toast(_ message: String, _ type: ToastType)
}

/// DealsView's state, in one watched value.
public struct DealsUi: Equatable, Sendable {
    /// nil = still loading (the web's `deals === null`).
    public var deals: [Deal]? = nil
    /// The won deals are fetched on their own so the header's count is real.
    public var wonCount = 0
    public var actions: [PlannedAction]? = nil
    /// Why the last load failed (nil when it worked): what was loaded stays, and this says why it is not fresh.
    public var loadError: String? = nil
    public var refreshing = false
    /// Ids of queue items with a send/veto in flight (or being settled), so a double tap can't double-send.
    public var acting: Set<String> = []
    /// Queue items whose send got no answer: the queue is being re-read to learn whether it went.
    public var checking: Set<String> = []
    /// Deals with a won / lost / guidance save in flight: their buttons wait.
    public var patching: Set<String> = []
    /// The deal whose guidance is open for editing, and its draft.
    public var editing: String? = nil
    public var guidanceDraft = ""
    /// Why the guidance didn't save — shown under the text, which stays as typed.
    public var guidanceError: String? = nil
    /// The planned action open in the edit-and-send dialog.
    public var draftFor: PlannedAction? = nil
    /// The dialog's text lives here, not in the dialog: a failed send leaves the dialog open with every word.
    public var draftText = ""
    public var draftError: String? = nil
    public init() {}
}

private extension Result {
    var error: Failure? { if case .failure(let e) = self { return e } else { return nil } }
}

/// DealsView's state: the open deals (the board), how many are won, and
/// Neema's initiative queue (Android `DealsViewModel`). Refreshes every
/// minute while on display, like the web's visibility-gated interval.
@MainActor
public final class DealsViewModel {
    /// DealsView's interval.
    nonisolated public static let POLL_MS: Int64 = 60_000
    /// Notifications that change the board or the queue.
    nonisolated public static let RELOAD_ON: Set<String> = ["planned_action", "hub_event"]
    /// After a send whose answer was lost, how often and how many times the
    /// queue is re-read to learn whether it went (≈30 s of checking). The
    /// row stays locked meanwhile, so a second tap can't race the first.
    nonisolated public static let SETTLE_MS: Int64 = 10_000
    nonisolated public static let SETTLE_READS = 4

    public let host: DealsHost
    public let state = Watched<DealsUi>(DealsUi())
    public private(set) var life: ScreenLife!
    private var loads: SingleFlight<Bool>!
    private var onEvent: Coalescer!
    private let sleep: Sleeper
    private var jobs: [UUID: Job] = [:]
    private var subs: [Subscription] = []
    private var closed = false
    public var uiAttached = false
    private var draftTextFor: String?
    /// The dialog's action, restored before the queue has loaded: it reopens once the action is read.
    private var pendingDraftFor: String?
    /// Queue items sent or vetoed here, by the `gen` at which they left: a load
    /// that was already on the wire when one left must not bring it back.
    private var left: [String: Int64] = [:]
    private var gen: Int64 = 0

    public init(host: DealsHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        self.sleep = sleep
        loads = SingleFlight { [weak self] () async throws -> Bool in
            guard let self = self else { return false }
            return await self.loadOnce()
        }
        // DealsView loads on mount and every 60 s while the tab is visible. Here:
        // only while this screen is on display and the app in front, reloading on
        // every return to it and after the live socket reconnects.
        life = ScreenLife(foreground: host.foreground, connected: host.socketConnected, pollMs: Self.POLL_MS, sleep: sleep,
                          poll: { [weak self] in _ = await self?.load() }, catchUp: { [weak self] in _ = await self?.load() })
        // Neema moving a follow-up into the approval queue and a hub event arrive as
        // notifications: the board reloads at once (800 ms, coalesced) while it is on display.
        onEvent = Coalescer(windowMs: Coalescer.EVENT_WINDOW_MS, sleep: sleep) { [weak self] in _ = await self?.load() }
        launch { [weak self] in _ = await self?.load() }
        subs.append(host.socketEvents.observe { [weak self] e in
            guard e.str("event") == "notification", let t = e.str("type"), Self.RELOAD_ON.contains(t) else { return }
            onMain {
                guard let self = self, !self.closed, self.life.active else { return }
                self.onEvent.kick()
            }
        })
    }

    public var ui: DealsUi { state.value }

    private func mut(_ f: (inout DealsUi) -> Void) {
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

    private static func attempt<T>(_ block: () async throws -> T) async -> Result<T, Error> {
        do { return .success(try await block()) } catch { return .failure(error) }
    }

    // ── Guidance and the dialog ─────────────────────────────────────────────

    public func startGuidance(_ d: Deal) { mut { $0.editing = d.id; $0.guidanceDraft = d.guidance ?? ""; $0.guidanceError = nil } }
    /// The web's `e.target.value.slice(0, 400)`.
    public func setGuidanceDraft(_ text: String) { mut { $0.guidanceDraft = String(text.prefix(400)) } }
    public func cancelGuidance() { mut { $0.editing = nil; $0.guidanceError = nil } }

    /// Open (or close, with nil) the edit-and-send dialog. Reopening the same
    /// action keeps what was typed; another action starts from its own draft.
    public func openDraft(_ a: PlannedAction?) {
        if let a = a, a.id != draftTextFor {
            draftTextFor = a.id
            mut { $0.draftText = a.draft ?? "" }
        }
        let current = ui.draftFor?.id
        mut { s in
            if a == nil || a!.id != current { s.draftError = nil }
            s.draftFor = a
        }
    }

    public func setDraftText(_ text: String) { mut { $0.draftText = text } }

    // ── The app reclaimed: the guidance being typed and the dialog come back ──

    public func saveUi() -> [String: JSONValue] {
        func s(_ v: String?) -> JSONValue { v.map { .string($0) } ?? .null }
        return [
            "editing": s(ui.editing), "guidance": .string(ui.guidanceDraft),
            "draftFor": s(ui.draftFor?.id ?? pendingDraftFor), "draftTextFor": s(draftTextFor), "draftText": .string(ui.draftText),
        ]
    }

    public func restoreUi(_ saved: [String: JSONValue]) {
        if let e = saved["editing"]?.stringValue {
            mut { $0.editing = e; $0.guidanceDraft = String((saved["guidance"]?.stringValue ?? "").prefix(400)) }
        }
        if let f = saved["draftTextFor"]?.stringValue {
            draftTextFor = f
            mut { $0.draftText = saved["draftText"]?.stringValue ?? "" }
        }
        pendingDraftFor = saved["draftFor"]?.stringValue
        reopenDraft()
    }

    @discardableResult
    public func restoreIfFresh(_ saved: [String: JSONValue]?) -> Bool {
        if uiAttached { return false }
        uiAttached = true
        guard let s = saved else { return false }
        restoreUi(s)
        return true
    }

    /// Reopens a restored dialog once its action is in the queue (and forgets it if the action left).
    private func reopenDraft() {
        guard let id = pendingDraftFor, let list = ui.actions else { return }
        pendingDraftFor = nil
        if let a = list.first(where: { $0.id == id }) { openDraft(a) }
    }

    // ── Loads ────────────────────────────────────────────────────────────────

    /// Read the board, the won count and the queue together. Each part that
    /// fails keeps what was on screen; true only when all of it was read.
    /// Loads never overlap: a load asked for while one is on the wire waits
    /// for it and then reads once more, so it still sees the change that prompted it.
    private func load() async -> Bool { (try? await loads.run()) ?? false }

    private func loadOnce() async -> Bool {
        let startGen = gen
        let api = host.api
        async let d = Self.attempt { try await api.deals.list(status: "open") }
        async let w = Self.attempt { try await api.deals.list(status: "won").count }
        async let a = Self.attempt { try await api.actions.list() }
        let (dr, wr, ar) = await (d, w, a)
        if closed { return false }
        if [dr.error, wr.error, ar.error].compactMap({ $0 }).contains(where: { SalesErrors.isCancellation($0) }) { return false }
        if case .success(let list) = dr { mut { $0.deals = list } }
        if case .success(let n) = wr { mut { $0.wonCount = n } }
        if case .success(let list) = ar {
            let shown = left.isEmpty ? list : list.filter { (left[$0.id] ?? -1) <= startGen }
            mut { $0.actions = shown }
            // What left before this read began is in the server's answer now.
            left = left.filter { $0.value > startGen }
            reopenDraft()
        }
        let failed = dr.error ?? ar.error ?? wr.error
        mut { $0.loadError = failed.map { SalesErrors.failure(of: $0).message() } }
        return failed == nil
    }

    public func reload() { launch { [weak self] in _ = await self?.load() } }

    public func refresh() {
        if ui.refreshing { return }
        mut { $0.refreshing = true }
        launch { [weak self] in
            guard let self = self else { return }
            _ = await self.load()
            self.mut { $0.refreshing = false }
        }
    }

    // ── Deal patches ─────────────────────────────────────────────────────────

    /// PATCH a deal. The web toasts "Update failed" for anything; here the
    /// reason is said, a deleted deal (404) leaves the board, and a failure
    /// that may have landed (timeout, lost answer) is settled by re-reading the
    /// board: `landed` reads the fresh board to say whether the change took.
    private func patchDeal(_ id: String, _ body: JSONValue, _ msg: String, landed: @escaping () -> Bool,
                           onSaved: @escaping () -> Void = {}, onFailed: @escaping (String) -> Void = { _ in }) {
        if ui.patching.contains(id) { return }
        mut { $0.patching.insert(id) }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.patching.remove(id) } }
            do {
                _ = try await self.host.api.deals.patch(id: id, body: body)
                if self.closed { return }
                onSaved()
                self.host.toast(msg, .success)
                _ = await self.load()
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                let f = SalesErrors.failure(of: error)
                switch f.kind {
                case .notFound:
                    onSaved()
                    self.host.toast("This deal no longer exists — someone may have deleted it", .error)
                    _ = await self.load()
                case _ where f.mayHaveHappened:
                    let read = await self.load()
                    if self.closed { return }
                    if read && landed() {
                        onSaved()
                        self.host.toast(msg, .success)
                    } else if read {
                        let m = "Not saved — \(SalesErrors.lowerFirst(f.message()))"
                        onFailed(m); self.host.toast(m, .error)
                    } else {
                        let m = "No answer from the server — it may not have saved. Pull down to check."
                        onFailed(m); self.host.toast(m, .error)
                    }
                case .sessionExpired:
                    onFailed("Your session expired — sign in again, then save.")
                default:
                    let m = "Update failed — \(SalesErrors.lowerFirst(f.message()))"
                    onFailed(m); self.host.toast(m, .error)
                    if f.kind == .conflict { _ = await self.load() }
                }
            }
        }
    }

    /// Save the open guidance: the editor closes when the save lands and stays
    /// open, text intact, with the reason under it when it doesn't.
    public func saveGuidance(_ id: String, guidance: String? = nil) {
        let g = guidance ?? ui.guidanceDraft
        mut { $0.guidanceError = nil }
        patchDeal(id, .object(["guidance": .string(g)]), "Guidance saved — Neema obeys it now",
                  landed: { [weak self] in (self?.ui.deals?.first { $0.id == id }?.guidance ?? "") == g },
                  onSaved: { [weak self] in if self?.ui.editing == id { self?.mut { $0.editing = nil; $0.guidanceError = nil } } },
                  onFailed: { [weak self] m in if self?.ui.editing == id { self?.mut { $0.guidanceError = m } } })
    }

    /// Won / lost take the deal off the open board — it being gone is the sign it landed.
    private func closedOnBoard(_ id: String) -> Bool { ui.deals?.contains { $0.id == id } == false }

    public func markWon(_ id: String) {
        patchDeal(id, .object(["status": .string("won"), "stage": .string("won")]), "Marked won 🎉", landed: { [weak self] in self?.closedOnBoard(id) ?? false })
    }

    public func markLost(_ id: String) {
        patchDeal(id, .object(["status": .string("lost"), "stage": .string("lost")]), "Marked lost", landed: { [weak self] in self?.closedOnBoard(id) ?? false })
    }

    // ── Send / veto ──────────────────────────────────────────────────────────

    /// Approve (send now) or veto a planned action. `draft` is the operator's
    /// edited text; nil sends Neema's own draft (or lets her compose one).
    ///
    /// A send puts words in front of a customer, so it must never go twice:
    /// the row is locked from the first tap until the outcome is known. When
    /// the answer is lost (timeout, dropped connection, a gateway error) the
    /// send may well have gone, so it is never reported as failed — the queue
    /// is re-read until the action leaves it (sent) or ~30 s pass (not sent).
    public func act(_ id: String, _ verb: String, draft: String? = nil) {
        if ui.acting.contains(id) { return }
        mut { s in
            s.acting.insert(id)
            if s.draftFor?.id == id { s.draftError = nil }
        }
        launch { [weak self] in
            guard let self = self else { return }
            var settling = false
            defer { if !settling { self.mut { $0.acting.remove(id) } } }
            do {
                if verb == "approve" {
                    let d = draft?.trimmingCharacters(in: .whitespacesAndNewlines)
                    _ = try await self.host.api.actions.approve(id: id, draft: (d?.isEmpty == false) ? d : nil)
                } else {
                    _ = try await self.host.api.actions.veto(id: id)
                }
                if self.closed { return }
                self.resolved(id, verb)
                _ = await self.load()
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                let f = SalesErrors.failure(of: error)
                switch f.kind {
                // crm.py approve_action: 409 "Action is sent|vetoed" when the scheduler
                // (or a colleague) resolved it first. Nothing was sent twice.
                case .conflict:
                    self.closeDraft(id)
                    self.host.toast(self.conflictText(verb, f), .error)
                    _ = await self.load()
                // 404 "Action not found" / "Conversation gone": it can't be sent any more.
                case .notFound:
                    self.closeDraft(id)
                    let why = f.detail == "Conversation gone" ? "its conversation was deleted" : "someone else removed it"
                    self.host.toast("This follow-up is gone — \(why)", .error)
                    _ = await self.load()
                case _ where f.mayHaveHappened:
                    settling = true
                    await self.settle(id, verb)
                // The session dialog is up; the dialog keeps the text for a retry after sign-in.
                case .sessionExpired:
                    self.failedAct(id, "Your session expired — sign in again, then send.", toast: false)
                default:
                    self.failedAct(id, "\(self.couldnt(verb)) — \(SalesErrors.lowerFirst(f.message()))")
                }
            }
        }
    }

    private func resolved(_ id: String, _ verb: String) {
        closeDraft(id, clearText: true)
        gen += 1
        left[id] = gen
        mut { $0.actions = $0.actions?.filter { $0.id != id } }
        host.toast(verb == "approve" ? "Sent ✓" : "Vetoed", .success)
    }

    private func closeDraft(_ id: String, clearText: Bool = false) {
        if ui.draftFor?.id == id { mut { $0.draftFor = nil; $0.draftError = nil } }
        if clearText && draftTextFor == id { draftTextFor = nil; mut { $0.draftText = "" } }
    }

    /// A failure the operator must see: in the open dialog when it's this action's, else a toast.
    private func failedAct(_ id: String, _ message: String, toast: Bool = true) {
        if ui.draftFor?.id == id { mut { $0.draftError = message } }
        else if toast { host.toast(message, .error) }
    }

    private func conflictText(_ verb: String, _ f: SalesFailure) -> String {
        switch f.detail {
        case "Action is sent": return "Already sent — nothing was sent twice"
        case "Action is vetoed": return "Already vetoed — nothing was sent"
        default: return "\(couldnt(verb)) — \(SalesErrors.lowerFirst(f.message()))"
        }
    }

    private func couldnt(_ verb: String) -> String { verb == "approve" ? "Couldn't send" : "Couldn't veto" }

    /// Learn whether a send/veto whose answer was lost actually happened. The row stays locked throughout.
    private func settle(_ id: String, _ verb: String) async {
        mut { $0.checking.insert(id) }
        defer { mut { $0.checking.remove(id); $0.acting.remove(id) } }
        let went = verb == "approve" ? "sent" : "vetoed"
        if ui.draftFor?.id == id { mut { $0.draftError = "No answer from the server — checking whether it was \(went)…" } }
        else { host.toast("No answer from the server — checking whether it was \(went)…", .info) }
        var readOnce = false
        for i in 0..<Self.SETTLE_READS {
            if i > 0 {
                do { try await sleep(Self.SETTLE_MS) } catch { return }
            }
            if closed { return }
            let list = try? await host.api.actions.list()
            if closed { return }
            if let list = list {
                readOnce = true
                if !list.contains(where: { $0.id == id }) {
                    resolved(id, verb)
                    _ = await load()
                    return
                }
                mut { $0.actions = list }
            }
        }
        let msg: String
        if readOnce {
            msg = verb == "approve" ? "Not sent — the server never confirmed it. You can send it again."
                : "Not vetoed — the server never confirmed it. You can try again."
        } else {
            msg = verb == "approve" ? "Couldn't confirm whether it was sent — the server can't be reached. Open the chat to see whether it went before sending again."
                : "Couldn't confirm the veto — the server can't be reached. Pull down to check before trying again."
        }
        failedAct(id, msg)
    }

    public func close() {
        if closed { return }
        closed = true
        life.close()
        onEvent.cancel()
        subs.forEach { $0.cancel() }
        subs = []
        for j in jobs.values { j.cancel() }
        jobs = [:]
        loads.cancel()
    }
}
