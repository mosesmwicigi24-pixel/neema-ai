import Foundation

/// The shell as the leads screen sees it: the API and the toasts.
public protocol LeadsHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var api: NeemaApi { get }
    func toast(_ message: String, _ type: ToastType)
}

/// LeadsView's state, in one watched value.
public struct LeadsUi: Equatable, Sendable {
    public var leads: [Lead] = []
    public var loading = true
    public var refreshing = false
    /// Why the last read of the leads failed (nil when it worked): what was read stays on screen under a banner.
    public var loadError: String? = nil
    public var stages: [LeadStage] = LeadsRules.BASE_STAGES
    /// "all" or a stage id.
    public var filterStage = "all"
    public var search = ""
    public var selectedId: String? = nil
    /// Leads with a save in flight: their move buttons wait, and a second save can't overtake the first.
    public var saving: Set<String> = []
    /// Why the open sheet's save failed — shown in the sheet, over the fields as typed.
    public var sheetError: String? = nil
    /// The open lead's sheet as typed (nil until the sheet has shown once for it).
    public var sheet: LeadSheetDraft? = nil
    public init() {}
}

/// LeadsView's state: the leads, the pipeline's columns, filter/search and the open lead (Android `LeadsViewModel`).
@MainActor
public final class LeadsViewModel {
    public let host: LeadsHost
    public let state = Watched<LeadsUi>(LeadsUi())
    public private(set) var life: ScreenLife!
    private let api: LeadsApi
    private var reads: SingleFlight<Bool>!
    private var jobs: [UUID: Job] = [:]
    private var closed = false
    public var uiAttached = false
    /// Local changes by lead id, stamped with `gen`: a read that began before one must not undo it.
    private var touchedAt: [String: Int64] = [:]
    private var gen: Int64 = 0
    /// Leads with an optimistic move on the wire: every read keeps their local row until it settles.
    private var moving: Set<String> = []
    /// Leads whose next read must be the server's row (a save being settled).
    private var truth: Set<String> = []

    public init(host: LeadsHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        api = LeadsApi(http: host.api.http)
        reads = SingleFlight { [weak self] () async throws -> Bool in
            guard let self = self else { return false }
            return await self.fetchNow()
        }
        // LeadsView loads its stages and leads on mount, so every visit reads them
        // fresh; this model outlives the screen, so each return to it — and each
        // return to the app — re-reads both quietly (no spinner; a failure keeps the board).
        life = ScreenLife(foreground: host.foreground, sleep: sleep) { [weak self] in await self?.reread() }
        launch { [weak self] in await self?.loadStages() }
        load()
    }

    public var ui: LeadsUi { state.value }

    private func mut(_ f: (inout LeadsUi) -> Void) {
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

    private func loadStages() async {
        if let s = try? await host.api.settings.getPipelineStages(), !closed { mut { $0.stages = LeadsRules.buildStages(s) } }
    }

    private func reread() async {
        await loadStages()
        _ = await fetch()
    }

    public func load() {
        mut { $0.loading = true }
        launch { [weak self] in
            guard let self = self else { return }
            _ = await self.fetch()
            self.mut { $0.loading = false }
        }
    }

    public func refresh() {
        if ui.refreshing { return }
        mut { $0.refreshing = true }
        launch { [weak self] in
            guard let self = self else { return }
            await self.loadStages()
            _ = await self.fetch()
            self.mut { $0.refreshing = false }
        }
    }

    /// Read the board. A failure keeps what is on screen and says why; true
    /// when the board now shows the server's truth. `truthFor`: a lead whose
    /// save is being settled — its row is taken from the server even though a
    /// local change to it is pending, so the answer says whether the save landed.
    private func fetch(truthFor: String? = nil) async -> Bool {
        if let t = truthFor { truth.insert(t) }
        return (try? await reads.run()) ?? false
    }

    private func fetchNow() async -> Bool {
        let startGen = gen
        let trusted = truth
        truth = []
        do {
            let list = try await api.list()
            if closed { return false }
            mut { $0.leads = LeadsRules.overlayLocal(list, onScreen: $0.leads, keepLocal: protectedSince(startGen).subtracting(trusted)) }
            touchedAt = touchedAt.filter { $0.value > startGen }
            mut { $0.loadError = nil }
            return true
        } catch {
            if closed || SalesErrors.isCancellation(error) { return false }
            mut { $0.loadError = SalesErrors.failure(of: error).message() }
            return false
        }
    }

    /// Leads changed here after a read began, or with a move still on the wire: that read predates them.
    private func protectedSince(_ startGen: Int64) -> Set<String> {
        if touchedAt.isEmpty && moving.isEmpty { return [] }
        return Set(touchedAt.filter { $0.value > startGen }.keys).union(moving)
    }

    /// Marks `id` as changed here, now.
    private func touch(_ id: String) { gen += 1; touchedAt[id] = gen }

    // ── Selection and the sheet ──────────────────────────────────────────────

    public func select(_ id: String?) {
        mut { s in
            if id != s.selectedId { s.sheetError = nil }
            s.selectedId = id
            // Cancel / close / a save that landed: what was typed goes with the sheet.
            if id == nil { s.sheet = nil }
        }
    }

    /// The draft for `lead`'s sheet, started from the lead as it is now if there is none yet.
    public func sheetFor(_ lead: Lead) -> LeadSheetDraft {
        if let d = ui.sheet, d.leadId == lead.id { return d }
        let d = LeadSheetDraft.of(lead, ui.stages)
        mut { $0.sheet = d }
        return d
    }

    public func editSheet(_ d: LeadSheetDraft) { if d.leadId == ui.selectedId { mut { $0.sheet = d } } }

    /// The sheet was swiped away: it closes, but what was typed stays for this lead.
    public func dismissSheet() { mut { $0.sheetError = nil; $0.selectedId = nil } }

    public func setFilterStage(_ s: String) { mut { $0.filterStage = s } }
    public func setSearch(_ q: String) { mut { $0.search = q } }

    /// The board has been read (or failed to be): an open lead missing from it is really gone.
    public var loaded: Bool { !ui.loading }

    // ── The app reclaimed: filter, search, the open lead and its typed fields come back ──

    public func saveUi() -> [String: JSONValue] {
        func s(_ v: String?) -> JSONValue { v.map { .string($0) } ?? .null }
        let d = ui.sheet
        return [
            "filter": .string(ui.filterStage), "search": .string(ui.search), "selected": s(ui.selectedId),
            "sheet.lead": s(d?.leadId), "sheet.stage": s(d?.stage), "sheet.tags": s(d?.tags), "sheet.notes": s(d?.notes),
            "sheet.baseStage": s(d?.baseStage), "sheet.baseTags": d.map { .array($0.baseTags.map { .string($0) }) } ?? .null,
            "sheet.baseNotes": s(d?.baseNotes),
        ]
    }

    public func restoreUi(_ saved: [String: JSONValue]) {
        mut { s in
            if let f = saved["filter"]?.stringValue { s.filterStage = f }
            if let q = saved["search"]?.stringValue { s.search = q }
            s.selectedId = saved["selected"]?.stringValue
            if let lead = saved["sheet.lead"]?.stringValue {
                s.sheet = LeadSheetDraft(
                    leadId: lead, stage: saved["sheet.stage"]?.stringValue ?? "", tags: saved["sheet.tags"]?.stringValue ?? "",
                    notes: saved["sheet.notes"]?.stringValue ?? "", baseStage: saved["sheet.baseStage"]?.stringValue,
                    baseTags: (saved["sheet.baseTags"]?.arrayValue ?? []).compactMap { $0.stringValue },
                    baseNotes: saved["sheet.baseNotes"]?.stringValue ?? ""
                )
            }
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

    // ── Saves ────────────────────────────────────────────────────────────────

    public func moveTo(_ lead: Lead, _ stage: String) { update(lead, stage: stage) }

    private func apply(_ id: String, _ edit: LeadEdit) {
        touch(id)
        mut { s in
            s.leads = s.leads.map { l in
                guard l.id == id else { return l }
                var c = l
                if let st = edit.stage { c.leadStage = st }
                if let t = edit.tags { c.tags = t }
                if let n = edit.notes { c.notes = n }
                return c
            }
        }
    }

    private func bodyOf(_ edit: LeadEdit) -> JSONValue {
        var o: [String: JSONValue] = [:]
        if let st = edit.stage { o["lead_stage"] = .string(st) }
        if let t = edit.tags { o["tags"] = .array(t.map { .string($0) }) }
        if let n = edit.notes {
            o["notes"] = .string(n)
            o["notes_base"] = .string(edit.notesBase)
        }
        return .object(o)
    }

    private func rollback(_ id: String, _ before: Lead, _ edit: LeadEdit) {
        touch(id)
        mut { s in
            s.leads = s.leads.map { l in
                guard l.id == id else { return l }
                var c = l
                if edit.stage != nil { c.leadStage = before.leadStage }
                if edit.tags != nil { c.tags = before.tags }
                if edit.notes != nil { c.notes = before.notes }
                return c
            }
        }
    }

    /// A card's stage move (or any direct edit): optimistic — the board changes
    /// at once. A failed save puts the lead back as it was (only that lead) and
    /// says why; a deleted lead (404) leaves the board; a save whose answer was
    /// lost is settled by re-reading the board, whose truth decides what is said.
    public func update(_ lead: Lead, stage: String? = nil, tags: [String]? = nil, notes: String? = nil, notesBase: String? = nil) {
        if ui.saving.contains(lead.id) { return }
        let edit = LeadEdit(stage: stage, tags: tags, notes: notes, notesBase: notesBase ?? (lead.notes ?? ""))
        let before = ui.leads.first { $0.id == lead.id } ?? lead
        mut { $0.saving.insert(lead.id) }
        moving.insert(lead.id)
        apply(lead.id, edit)
        launch { [weak self] in
            guard let self = self else { return }
            defer {
                self.moving.remove(lead.id)
                self.mut { $0.saving.remove(lead.id) }
            }
            do {
                _ = try await self.api.update(id: lead.id, body: self.bodyOf(edit))
                if self.closed { return }
                self.host.toast("Lead updated", .success)
                // crm.py update_lead stores merge_notes(base, mine, current) and replies {"ok": true}:
                // re-read quietly so the board shows what was actually stored.
                if notes != nil { _ = await self.fetch(truthFor: lead.id) }
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                let f = SalesErrors.failure(of: error)
                switch f.kind {
                case .notFound:
                    self.gone(lead.id)
                case _ where f.mayHaveHappened:
                    if await self.fetch(truthFor: lead.id) {
                        if self.closed { return }
                        let now = self.ui.leads.first { $0.id == lead.id }
                        if now == nil { self.host.toast("This lead no longer exists — someone may have deleted or merged it", .error) }
                        else if LeadsRules.editLanded(edit, now!) { self.host.toast("Lead updated", .success) }
                        else { self.host.toast("Lead not updated — \(SalesErrors.lowerFirst(f.message()))", .error) }
                    } else {
                        if self.closed { return }
                        self.rollback(lead.id, before, edit)
                        self.host.toast("No answer from the server — the lead may not have changed. Pull down to check.", .error)
                    }
                case .sessionExpired:
                    self.rollback(lead.id, before, edit) // the session dialog says why
                default:
                    self.rollback(lead.id, before, edit)
                    self.host.toast("Failed to update lead — \(SalesErrors.lowerFirst(f.message()))", .error)
                    if f.kind == .conflict { _ = await self.fetch(truthFor: lead.id) }
                }
            }
        }
    }

    /// The detail sheet's Save: the sheet stays open (fields as typed, Save
    /// showing progress) until the server has the change, and a failure is
    /// explained inside it. Nothing typed is ever lost.
    public func save(_ lead: Lead, _ edit: LeadEdit) {
        if edit.isEmpty { select(nil); return }
        if ui.saving.contains(lead.id) { return }
        mut { $0.saving.insert(lead.id); $0.sheetError = nil }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.saving.remove(lead.id) } }
            do {
                _ = try await self.api.update(id: lead.id, body: self.bodyOf(edit))
                if self.closed { return }
                await self.saved(lead.id, edit)
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                let f = SalesErrors.failure(of: error)
                switch f.kind {
                case .notFound:
                    self.gone(lead.id)
                case _ where f.mayHaveHappened:
                    let read = await self.fetch(truthFor: lead.id)
                    if self.closed { return }
                    let now = self.ui.leads.first { $0.id == lead.id }
                    if read && now == nil { self.gone(lead.id) }
                    // The board was just re-read: it already shows what was stored.
                    else if read, let n = now, LeadsRules.editLanded(edit, n) { await self.saved(lead.id, edit, fresh: true) }
                    else if read { self.sheetFailed(lead.id, "Not saved — \(SalesErrors.lowerFirst(f.message()))") }
                    else { self.sheetFailed(lead.id, "No answer from the server — your changes may not have saved. Save again to be sure.") }
                case .sessionExpired:
                    self.sheetFailed(lead.id, "Your session expired — sign in again, then save.")
                default:
                    self.sheetFailed(lead.id, "Couldn't save — \(SalesErrors.lowerFirst(f.message()))")
                }
            }
        }
    }

    /// `fresh`: the board was re-read after the save, so it is already the server's truth.
    private func saved(_ id: String, _ edit: LeadEdit, fresh: Bool = false) async {
        if !fresh { apply(id, edit) }
        mut { s in
            if s.selectedId == id { s.selectedId = nil; s.sheetError = nil }
            if s.sheet?.leadId == id { s.sheet = nil }
        }
        host.toast("Lead updated", .success)
        // The notes stored are merged server-side: re-read so the board shows them.
        if !fresh && edit.notes != nil { _ = await fetch() }
    }

    private func sheetFailed(_ id: String, _ message: String) {
        if ui.selectedId == id { mut { $0.sheetError = message } }
        else { host.toast(message, .error) }
    }

    /// 404: someone deleted (or merged) this lead. It leaves the board, and its sheet closes.
    private func gone(_ id: String) {
        touch(id)
        mut { s in
            s.leads = s.leads.filter { $0.id != id }
            if s.selectedId == id { s.selectedId = nil; s.sheetError = nil }
            if s.sheet?.leadId == id { s.sheet = nil }
        }
        host.toast("This lead no longer exists — someone may have deleted or merged it", .error)
    }

    public func close() {
        if closed { return }
        closed = true
        life.close()
        for j in jobs.values { j.cancel() }
        jobs = [:]
        reads.cancel()
    }
}
