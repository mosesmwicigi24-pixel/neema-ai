import Foundation

/// Operator-added pipeline stages (Settings-backed, global): fetched once per process, like the web's module cache.
@MainActor
public enum StageCache {
    public static var stages: [String]? = nil
}

public enum CustomerTab: String, Sendable, CaseIterable { case profile, insights, activity }

/// The Calls section's call request: in flight, what it said, and a refusal's details.
public struct CallRequestUi: Equatable, Sendable {
    public var busy = false
    /// "Call request sent — …" once the server took it.
    public var sent = false
    /// They had allowed calls permanently already: offer "Call now".
    public var alreadyAllowed = false
    public var error: String? = nil
    /// template_required and this agent can fix it in Settings → WhatsApp calling.
    public var adminCanFix = false
    /// Outside the 24 h window with no template: asking again can't work until an admin creates it.
    public var templateRequired = false
    public init(busy: Bool = false, sent: Bool = false, alreadyAllowed: Bool = false, error: String? = nil, adminCanFix: Bool = false, templateRequired: Bool = false) {
        self.busy = busy; self.sent = sent; self.alreadyAllowed = alreadyAllowed; self.error = error; self.adminCanFix = adminCanFix; self.templateRequired = templateRequired
    }
}

/// Everything the customer panel shows, in one watched value.
public struct CustomerUi: Equatable, Sendable {
    public var loading = true
    public var profile: CustomerProfile? = nil
    /// Pull-to-refresh: reloading over an already-painted profile.
    public var refreshing = false
    public var saving = false
    /// Why the last profile GET failed (nil once one succeeds).
    public var loadError: String? = nil
    /// A stage move is in flight: the stepper and Quick Actions wait, so a double tap can't skip a stage.
    public var stageBusy = false
    /// Input is sacred: the text of a field edit that did not save comes back here, keyed by field, for its editor to reopen with.
    public var drafts: [String: String] = [:]
    /// The inputs of the panel, held here so a failure, a tab switch or a reload never loses them.
    public var tagInput = ""
    public var mergeQuery = ""
    public var askDraft = ""
    public var answerDraft = ""
    /// The "+ Add stage" input: cleared only once the server kept the stage.
    public var newStage = ""
    public var tab: CustomerTab = .profile
    public var stageEditorOpen = false
    public var editNotes = false
    /// The notes editor's text and the snapshot it started from (nil when not editing).
    public var noteDraft = ""
    public var notesBase: String? = nil
    public var customStages: [String] = []
    public var stagesSaving = false
    public var enquiry: ProductionEnquiry? = nil
    public var pushing = false
    public var showMerge = false
    /// nil = still scanning for duplicates.
    public var mergeSugs: [MergeSuggestion]? = nil
    /// The duplicate scan failed (offline, 5xx): said as such, not as "no duplicates".
    public var mergeSugsError: String? = nil
    public var merging = false
    /// Merged ids with an unmerge in flight (their chip waits).
    public var unmerging: Set<String> = []
    public var templateBusy = false
    public var inviteBusy = false
    public var callBusy = false
    /// This customer's last calls — the panel's "Calls" section (nil until first read).
    public var recentCalls: [Call]? = nil
    /// Whether this customer allowed calls — nil until read, or when it couldn't be.
    public var callPermission: CallPermission? = nil
    public var callRequest = CallRequestUi()
    /// Ask-Neema: read-only lookups; nothing reaches the customer.
    public var askAnswer: String? = nil
    public var askBusy = false
    /// Answer-via-Neema: the team's confirmed facts, delivered in Neema's voice.
    public var answerStatus: String? = nil
    public var answerBusy = false
    public init() {}
}

/// State and actions of the customer panel (components/ui/CustomerSidebar.tsx,
/// Android `CustomerViewModel`). One per conversation: every edit PATCHes
/// /admin/customers/{key}?channel=…, keyed on the channel-native handle so
/// Messenger/IG/FB contacts persist too.
///
/// Built for a flaky network (CustomerErrors.swift): every action has one
/// request in flight at most, says why it failed in plain words, never calls a
/// request that may have landed (a timeout) a failure — it checks with the
/// server instead — and gives back whatever the agent typed when a save fails.
@MainActor
public final class CustomerViewModel {
    /// Live triggers landing within this window cost one GET.
    nonisolated public static let RELOAD_COALESCE_MS: Int64 = 400
    /// How many calls the panel's "Calls" section lists.
    nonisolated public static let RECENT_CALLS = 3
    nonisolated static let CALLS_DEBOUNCE_MS: Int64 = 500

    public let host: CustomerHost
    public let state = Watched<CustomerUi>(CustomerUi())
    public private(set) var conversation: Conversation
    private let crm: CrmApi
    private let fetchProfile: (String, String?) async throws -> CustomerProfile
    private let sleep: Sleeper

    private var jobs: [UUID: Job] = [:]
    private var closed = false
    private var liveSubs: [Subscription] = []
    private var shownBefore = false
    /// Off screen (another thread, another view): no "Saved" for a panel that is gone.
    private var hidden = false
    private var reloadJob: Job?
    private var loadJob: Job?
    private var stagesJob: Job?
    private var enquiryJob: Job?
    private var mergeJob: Job?
    private var callsJob: Job?
    private var permissionJob: Job?
    private var callsWatch: Subscription?
    private var callsPending: Job?
    /// Bumped per GET; only the newest GET's answer is ever painted.
    private var loadSeq = 0
    /// Bumped per local edit; a GET that left before an edit is not painted over it.
    private var editSeq = 0
    private var patchesInFlight = 0
    /// A reload was held back by an edit in flight; run it once the edits settle.
    private var reloadAfterEdits = false
    /// The profile last loaded or fallen back to, with every CONFIRMED edit applied.
    private var confirmed: CustomerProfile?
    /// Whether `confirmed` came from the server (not the fallback).
    private var realLoaded = false
    private var declining = false
    /// The last enquiry / stage-list GET failed: the next good profile load tries them again.
    private var enquiryFailed = false
    private var stagesFailed = false
    /// Bumped by every push / dismiss; an enquiry GET that left before one is not painted over it.
    private var enquirySeq = 0
    private var lastMyOrders: [Order]? = nil

    /// An optimistic edit in flight: rolled back alone, never by restoring a whole snapshot.
    private struct Edit { let body: String; let stage: Bool; let apply: (CustomerProfile) -> CustomerProfile }
    private var edits: [Edit] = []
    /// What to do with the agent's text if a save does not land: did it land, and how to give it back.
    private struct Draft { let landed: (CustomerProfile) -> Bool; let restore: () -> Void }
    /// Saves whose answer never came (a timeout): checked against the next profile that loads.
    private var unconfirmed: [Draft] = []

    public init(host: CustomerHost, conversation: Conversation,
                fetchProfile: ((String, String?) async throws -> CustomerProfile)? = nil, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        self.conversation = conversation
        self.sleep = sleep
        let crm = CrmApi(http: host.api.http)
        self.crm = crm
        self.fetchProfile = fetchProfile ?? { k, ch in try await crm.profile(key: k, channel: ch) }
        mut { $0.customStages = StageCache.stages ?? [] }
        load()
        loadEnquiry()
        loadStagesIfNeeded()
    }

    /// Every task stops; nothing more is painted or toasted.
    public func close() {
        closed = true
        onHidden()
        for j in jobs.values { j.cancel() }
        jobs.removeAll()
    }

    // ── State access ────────────────────────────────────────────────────────

    public var ui: CustomerUi { state.value }
    public var profile: CustomerProfile? { state.value.profile }

    private func mut(_ f: (inout CustomerUi) -> Void) {
        var s = state.value
        f(&s)
        state.update(s)
    }

    public func setTab(_ t: CustomerTab) { mut { $0.tab = t } }
    public func setTagInput(_ v: String) { mut { $0.tagInput = v } }
    public func setMergeQuery(_ v: String) { mut { $0.mergeQuery = v } }
    public func setAskDraft(_ v: String) { mut { $0.askDraft = v } }
    public func setAnswerDraft(_ v: String) { mut { $0.answerDraft = v } }
    public func setNewStage(_ v: String) { mut { $0.newStage = String(v.prefix(18)) } }
    public func setNoteDraft(_ v: String) { mut { $0.noteDraft = v } }
    public func setStageEditorOpen(_ v: Bool) { mut { $0.stageEditorOpen = v } }
    /// The editor takes a failed save's text back.
    public func takeDraft(_ key: String) { mut { $0.drafts[key] = nil } }
    private func keepDraft(_ key: String, _ v: String) { mut { $0.drafts[key] = v } }

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

    /// A toast from this panel. Once it has left the screen, confirmations are
    /// dropped and a failure names whose profile it was.
    private func say(_ msg: String, _ type: ToastType = .success) {
        if !hidden { host.toast(msg, type); return }
        if type != .error { return }
        let who = [profile?.name, conversation.name].compactMap { $0 }.first { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        host.toast(who.map { "\($0): \(msg)" } ?? msg, type)
    }

    // ── Keys ─────────────────────────────────────────────────────────────────

    /// wa_id for WhatsApp, else the PSID / IGSID (WhatsApp's wa_id IS its external_id).
    private var custId: String { conversation.waId ?? conversation.externalId ?? "" }
    private var channel: String? { conversation.channel.isEmpty ? nil : conversation.channel }
    /// The key edits persist against: the profile's own wa_id (a shim for non-WhatsApp contacts), else the handle.
    private var key: String {
        if let w = profile?.waId, !w.isEmpty { return w }
        return custId
    }

    // ── Loading ──────────────────────────────────────────────────────────────

    /// The operator-added stages, once per process. A failure stays uncached and the next load tries again.
    private func loadStagesIfNeeded(force: Bool = false) {
        if (!force && StageCache.stages != nil) || stagesJob?.isActive == true { return }
        stagesJob = launch { [weak self] in
            guard let self = self else { return }
            do {
                let st = try await self.host.api.settings.getPipelineStages()
                if Task.isCancelled { return }
                StageCache.stages = st
                self.mut { s in
                    s.customStages = st
                    // A stage whose save timed out did land: its label leaves the input.
                    let typed = s.newStage.trimmingCharacters(in: .whitespaces)
                    if !typed.isEmpty && st.contains(typed) { s.newStage = "" }
                }
                self.stagesFailed = false
            } catch {
                if Task.isCancelled { return }
                self.stagesFailed = true
            }
        }
    }

    /// The web re-runs loadProfile whenever the thread's row changes (its deps:
    /// wa_id, name, channel, last_message_at) — and so does an AI-set stage or
    /// order count. Bursts of row updates coalesce into one request.
    public func sync(_ conv: Conversation) {
        let prev = conversation
        conversation = conv
        if conv.id != prev.id { return }
        if conv.lastMessageAt != prev.lastMessageAt || conv.name != prev.name || conv.waId != prev.waId || conv.externalId != prev.externalId ||
            conv.channel != prev.channel || conv.leadStage != prev.leadStage || conv.ordersCount != prev.ordersCount {
            requestReload()
        }
    }

    /// The panel is on screen: a re-shown panel refetches quietly; while shown it
    /// catches up on a foreground return, a socket reconnect and this customer's orders changing.
    public func onShown() {
        hidden = false
        if shownBefore { requestReload() }
        shownBefore = true
        for s in liveSubs { s.cancel() }
        liveSubs = []
        var fgWas = host.foreground.value
        liveSubs.append(host.foreground.observe { [weak self] v in
            onMain { if v && !fgWas { self?.requestReload() }; fgWas = v }
        })
        var sockWas = host.socketConnected.value
        liveSubs.append(host.socketConnected.observe { [weak self] v in
            onMain { if v && !sockWas { self?.requestReload() }; sockWas = v }
        })
        lastMyOrders = myOrders(host.orders.value)
        liveSubs.append(host.orders.observe { [weak self] all in
            onMain {
                guard let self = self else { return }
                let mine = self.myOrders(all)
                if mine != self.lastMyOrders { self.lastMyOrders = mine; self.requestReload() }
            }
        })
    }

    private func myOrders(_ all: [Order]) -> [Order] {
        guard let w = conversation.waId, !w.isEmpty else { return [] }
        return all.filter { $0.waId == w || $0.contactPhone == w }
    }

    /// The panel left the screen: nothing it would show is worth a request.
    public func onHidden() {
        hidden = true
        for s in liveSubs { s.cancel() }
        liveSubs = []
        reloadJob?.cancel()
        callsWatch?.cancel(); callsWatch = nil
        callsPending?.cancel()
    }

    /// A live trigger: reload quietly, coalescing everything within `RELOAD_COALESCE_MS` into one GET.
    public func requestReload() {
        reloadJob?.cancel()
        reloadJob = launch { [weak self] in
            guard let self = self else { return }
            try? await self.sleep(Self.RELOAD_COALESCE_MS)
            if Task.isCancelled { return }
            self.reloadJob = nil
            self.load(showSpinner: false)
        }
    }

    /// Pull-to-refresh / Retry: the profile, and whatever else failed to load before.
    public func refresh() {
        load(showSpinner: false)
        loadEnquiry()
        loadStagesIfNeeded()
    }

    /// GET the profile. The newest request wins; an answer that raced a local edit is not painted over it.
    /// A failure keeps what is painted (the last good profile, else a fallback from the chat row) and says why.
    public func load(showSpinner: Bool? = nil) {
        let spinner = showSpinner ?? (profile == nil)
        reloadJob?.cancel()
        if patchesInFlight > 0 { reloadAfterEdits = true; return }
        loadJob?.cancel()
        loadSeq += 1
        let seq = loadSeq
        let editsAtStart = editSeq
        if spinner { mut { $0.loading = true } } else { mut { $0.refreshing = true } }
        let id = custId, ch = channel
        loadJob = launch { [weak self] in
            guard let self = self else { return }
            defer {
                if seq == self.loadSeq {
                    self.mut { $0.loading = false; $0.refreshing = false }
                    if self.reloadAfterEdits && self.patchesInFlight == 0 { self.reloadAfterEdits = false; self.requestReload() }
                }
            }
            do {
                let fresh = try await self.fetchProfile(id, ch)
                if Task.isCancelled { return }
                // An empty 2xx body decodes to an all-defaults profile: that is no answer.
                if fresh.id.isEmpty && (fresh.waId ?? "").isEmpty { throw DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "empty profile")) }
                if seq != self.loadSeq { return }
                if self.editSeq != editsAtStart || self.patchesInFlight > 0 { self.reloadAfterEdits = true; return }
                self.confirmed = fresh
                self.realLoaded = true
                self.mut { $0.profile = fresh; $0.loadError = nil }
                self.settleUnconfirmed(fresh)
                if self.enquiryFailed { self.loadEnquiry() }
                if self.stagesFailed { self.loadStagesIfNeeded() }
            } catch {
                if Task.isCancelled { return }
                if seq == self.loadSeq {
                    // Fallback: a minimal profile from the conversation row, so the panel still works.
                    if self.profile == nil { let f = self.fallbackProfile(); self.confirmed = f; self.mut { $0.profile = f } }
                    self.mut { $0.loadError = self.loadErrorText(error) }
                }
            }
        }
    }

    private func loadErrorText(_ e: Error) -> String {
        if CrmErrors.failure(of: e) == .notFound {
            return "No saved profile for this customer — it may have been merged into another. Showing what this chat knows."
        }
        return realLoaded ? "Couldn't refresh — \(CrmErrors.reason(e)) Showing the profile as last loaded."
            : "Couldn't load the full profile — \(CrmErrors.reason(e)) Showing what this chat knows."
    }

    /// Saves that timed out, checked against the profile the server now serves.
    private func settleUnconfirmed(_ fresh: CustomerProfile) {
        if unconfirmed.isEmpty { return }
        let checks = unconfirmed
        unconfirmed = []
        let lost = checks.filter { !$0.landed(fresh) }
        for l in lost { l.restore() }
        if lost.isEmpty { say("Saved") }
        else { say("That change didn't reach the server — it's back in the editor to try again.", .error) }
    }

    private func fallbackProfile() -> CustomerProfile {
        CustomerProfile(
            id: custId, waId: custId, name: conversation.name,
            // As the server does (crm.py phone_display): a web visitor's `web_<hash>` key is not a phone.
            phone: Inbox.isWebVisitor(conversation.waId) ? nil : conversation.waId,
            leadStage: "new",
            channels: [CustomerChannel(channel: conversation.channel.isEmpty ? "whatsapp" : conversation.channel, identifier: conversation.waId,
                                       firstSeen: conversation.lastMessageAt, lastSeen: conversation.lastMessageAt, conversationCount: 1)],
            lastSeenAt: conversation.lastMessageAt, firstSeenAt: conversation.lastMessageAt, createdAt: conversation.lastMessageAt,
            countryIso: conversation.countryIso, country: conversation.country, flagUrl: conversation.flagUrl
        )
    }

    private func repaint() {
        guard let base = confirmed else { return }
        let p = edits.reduce(base) { acc, e in e.apply(acc) }
        mut { $0.profile = p }
    }

    // ── Optimistic PATCH ─────────────────────────────────────────────────────

    /// Apply `local` at once, send `body`. `onSaved` runs only after the server accepted it.
    /// - A second identical save while the first is in flight is a double tap: dropped.
    /// - A refusal rolls back THIS edit only and hands the typed text back through `draft`.
    /// - A timeout may have saved: the edit stays, the profile is refetched once edits settle,
    ///   and the text comes back only if the server doesn't have it.
    /// - 404 (merged away / removed) and 409 refetch the truth.
    private func patch(_ body: JSONValue, local: @escaping (CustomerProfile) -> CustomerProfile, draft: Draft? = nil, onSaved: (() -> Void)? = nil) {
        guard let cur = profile else { return }
        let sig = body.text
        if edits.contains(where: { $0.body == sig }) { return }
        if confirmed == nil { confirmed = cur }
        let k = key, ch = channel
        let isStage = body.objectValue?["lead_stage"] != nil
        let edit = Edit(body: sig, stage: isStage, apply: local)
        edits.append(edit)
        mut { $0.saving = true; if isStage { $0.stageBusy = true } }
        repaint()
        editSeq += 1
        patchesInFlight += 1
        launch { [weak self] in
            guard let self = self else { return }
            defer {
                self.patchesInFlight -= 1
                let stageStill = self.edits.contains { $0.stage }
                self.mut { $0.stageBusy = stageStill }
                if self.patchesInFlight == 0 {
                    self.mut { $0.saving = false }
                    // A live update arrived mid-save (or a save needs checking): fetch it now.
                    if self.reloadAfterEdits { self.reloadAfterEdits = false; self.requestReload() }
                }
            }
            do {
                try await self.crm.patch(key: k, channel: ch, body: body)
                if Task.isCancelled { return }
                self.confirmed = self.confirmed.map(local)
                self.edits.removeAll { $0.body == sig }
                self.repaint()
                self.say("Saved")
                onSaved?()
            } catch {
                if Task.isCancelled { return }
                self.edits.removeAll { $0.body == sig }
                if CrmErrors.mayHaveLanded(error) {
                    self.confirmed = self.confirmed.map(local)
                    self.repaint()
                    if let d = draft { self.unconfirmed.append(d) }
                    self.reloadAfterEdits = true
                    self.say("Couldn't confirm the save — checking with the server…", .info)
                } else {
                    self.repaint()
                    draft?.restore()
                    let f = CrmErrors.failure(of: error)
                    if f == .notFound || f == .conflict { self.reloadAfterEdits = true }
                    switch f {
                    case .notFound: self.say("Failed to save — this customer's profile is gone (it may have been merged into another). Refreshing.", .error)
                    case .conflict: self.say("Failed to save — it changed meanwhile. Refreshing to show the latest.", .error)
                    default: self.say("Failed to save — \(CrmErrors.reason(error))", .error)
                    }
                }
            }
        }
    }

    /// A text field's draft: landed when the server has exactly it; else back into that field's editor.
    private func fieldDraft(_ field: String, _ v: String, _ read: @escaping (CustomerProfile) -> String?) -> Draft {
        Draft(landed: { (read($0) ?? "") == v }, restore: { [weak self] in self?.keepDraft(field, v) })
    }

    public func saveName(_ v: String, onNameChange: @escaping (String, String) -> Void) {
        let waId = profile?.waId ?? custId
        patch(.object(["name": .string(v)]), local: { var p = $0; p.name = v; return p }, draft: fieldDraft("name", v) { $0.name }) {
            if !v.isEmpty { onNameChange(waId, v) }
        }
    }

    public func saveField(_ field: String, _ v: String, local: @escaping (CustomerProfile) -> CustomerProfile) {
        patch(.object([field: .string(v)]), local: local, draft: fieldDraft(field, v) { Self.readField($0, field) })
    }

    /// The contact fields by name, for the editors (role, organization, email, phone, country, location).
    public func saveContactField(_ field: String, _ v: String) {
        saveField(field, v) { p in
            var q = p
            switch field {
            case "role": q.role = v
            case "organization": q.organization = v
            case "email": q.email = v
            case "phone": q.phone = v
            case "country": q.country = v
            case "location": q.location = v
            default: break
            }
            return q
        }
    }

    private static func readField(_ p: CustomerProfile, _ field: String) -> String? {
        switch field {
        case "name": return p.name
        case "role": return p.role
        case "organization": return p.organization
        case "email": return p.email
        case "phone": return p.phone
        case "country": return p.country
        case "location": return p.location
        default: return nil
        }
    }

    private static let leadingInt = try! NSRegularExpression(pattern: #"^\s*([+-]?\d+)"#)

    /// `parseInt(v) || null` — leading digits count ("35 yrs" → 35); unparseable or zero is sent as null.
    public func saveAge(_ v: String) {
        var age: Int? = nil
        if let m = Self.leadingInt.firstMatch(in: v, range: NSRange(v.startIndex..., in: v)), let r = Range(m.range(at: 1), in: v), let n = Int(v[r]), n != 0 { age = n }
        patch(.object(["age": age.map { .number(Double($0)) } ?? .null]),
              local: { var p = $0; p.age = age; return p },
              draft: Draft(landed: { age == nil || $0.age == age }, restore: { [weak self] in self?.keepDraft("age", v) }))
    }

    /// Ignored while another stage move is in flight: an impatient double tap on "Advance" must not skip a stage.
    public func setStage(_ stage: String) {
        if ui.stageBusy { return }
        // The server locks an operator-set stage as "manual"; mirror it so the AI hint clears.
        patch(.object(["lead_stage": .string(stage)]), local: { var p = $0; p.leadStage = stage; p.leadStageSource = "manual"; return p })
    }

    /// Add the tag in the input; a refused save puts it back there.
    public func addTag(_ tag: String? = nil) {
        guard let p = profile else { return }
        let raw = tag ?? ui.tagInput
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty { return }
        if ui.tagInput.trimmingCharacters(in: .whitespacesAndNewlines) == t { mut { $0.tagInput = "" } }
        let next = p.tags + [t]
        patch(.object(["tags": .array(next.map { .string($0) })]),
              local: { var q = $0; q.tags = next; return q },
              draft: Draft(landed: { $0.tags.contains(t) }, restore: { [weak self] in
                  guard let self = self else { return }
                  if self.ui.tagInput.trimmingCharacters(in: .whitespaces).isEmpty { self.mut { $0.tagInput = t } }
              }))
    }

    public func removeTag(_ tag: String) {
        guard let p = profile else { return }
        let next = p.tags.filter { $0 != tag }
        patch(.object(["tags": .array(next.map { .string($0) })]), local: { var q = $0; q.tags = next; return q })
    }

    /// Open the notes editor on the notes as they are now; that text is the edit's base.
    public func startEditNotes() {
        let n = profile?.notes ?? ""
        mut { $0.noteDraft = n; $0.notesBase = n; $0.editNotes = true }
    }

    public func cancelEditNotes() { mut { $0.editNotes = false; $0.notesBase = nil } }

    /// notes_base = the snapshot the edit STARTED from, so the server MERGES rather than dropping a
    /// call summary appended while the agent typed. A save that fails reopens the editor on the same draft and base.
    public func saveNotes(_ draft: String? = nil) {
        let d = draft ?? ui.noteDraft
        let current = profile?.notes ?? ""
        let base = ui.notesBase ?? current
        mut { $0.editNotes = false; $0.notesBase = nil }
        let merged = base != current
        patch(.object(["notes": .string(d), "notes_base": .string(base)]),
              local: { var p = $0; p.notes = d; return p },
              draft: Draft(
                  landed: { ($0.notes ?? "") == d || ($0.notes ?? "").contains(d.trimmingCharacters(in: .whitespacesAndNewlines)) },
                  restore: { [weak self] in
                      guard let self = self, !self.ui.editNotes else { return }
                      self.mut { $0.noteDraft = d; $0.notesBase = base; $0.editNotes = true }
                  }
              )) { [weak self] in
            if merged { self?.requestReload() }
        }
    }

    // ── Custom pipeline stages (admin-only on the server) ────────────────────

    /// Add the label typed in `newStage`; the input clears once the server kept it.
    public func addCustomStage() {
        let label = ui.newStage.trimmingCharacters(in: .whitespacesAndNewlines)
        if label.isEmpty { return }
        saveCustomStages(ui.customStages + [label])
    }

    public func saveCustomStages(_ stages: [String]) {
        if ui.stagesSaving { return }
        mut { $0.stagesSaving = true }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.stagesSaving = false } }
            do {
                let r = try await self.host.api.settings.putPipelineStages(stages)
                if Task.isCancelled { return }
                StageCache.stages = r.stages
                self.mut { s in
                    s.customStages = r.stages
                    let typed = s.newStage.trimmingCharacters(in: .whitespaces)
                    if !typed.isEmpty && r.stages.contains(typed) { s.newStage = "" }
                }
            } catch {
                if Task.isCancelled { return }
                if CrmErrors.mayHaveLanded(error) {
                    self.say("Couldn't confirm the stage change — refreshing the stages.", .info)
                    self.loadStagesIfNeeded(force: true)
                } else {
                    let api = error as? ApiError
                    let detail = api?.detail.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                    if api?.status == 403 {
                        self.say("Only an admin can change pipeline stages.", .error)
                    } else if api?.status == 422 && detail.hasPrefix("At most") {
                        var d = detail
                        while d.hasSuffix(".") { d.removeLast() }
                        self.say(d + ".", .error)
                    } else {
                        self.say("Couldn't save pipeline stages — \(CrmErrors.reason(error))", .error)
                    }
                }
            }
        }
    }

    // ── Merge / unmerge ──────────────────────────────────────────────────────

    public func toggleMerge(_ open: Bool? = nil) {
        let o = open ?? !ui.showMerge
        mut { $0.showMerge = o; $0.mergeSugs = nil; $0.mergeSugsError = nil }
        mergeJob?.cancel()
        if !o { return }
        scanForDuplicates()
    }

    /// Retry a duplicate scan that failed.
    public func retryMergeScan() {
        if !ui.showMerge { return }
        mergeJob?.cancel()
        mut { $0.mergeSugs = nil; $0.mergeSugsError = nil }
        scanForDuplicates()
    }

    private func scanForDuplicates() {
        let k = key, ch = channel
        mergeJob = launch { [weak self] in
            guard let self = self else { return }
            do {
                let s = try await self.crm.mergeSuggestions(key: k, channel: ch)
                if Task.isCancelled { return }
                self.mut { $0.mergeSugs = s }
            } catch {
                if Task.isCancelled { return }
                // Never a spinner that never dies; and never "no duplicates" when we couldn't look.
                self.mut { $0.mergeSugs = []; $0.mergeSugsError = "Couldn't scan for duplicates — \(CrmErrors.reason(error))" }
            }
        }
    }

    public func merge(_ target: String? = nil, onDone: @escaping () -> Void = {}) {
        let t = (target ?? ui.mergeQuery).trimmingCharacters(in: .whitespacesAndNewlines)
        if t.isEmpty || ui.merging { return }
        mut { $0.merging = true }
        let k = key, ch = channel
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.merging = false } }
            do {
                try await self.crm.merge(key: k, channel: ch, target: t)
                if Task.isCancelled { return }
                self.say("Profiles merged successfully")
                self.toggleMerge(false)
                if self.ui.mergeQuery.trimmingCharacters(in: .whitespacesAndNewlines) == t { self.mut { $0.mergeQuery = "" } }
                onDone()
                self.load(showSpinner: false)
            } catch {
                if Task.isCancelled { return }
                if CrmErrors.mayHaveLanded(error) {
                    // It may well have merged: show where it stands; the typed target stays.
                    self.say("Couldn't confirm the merge — refreshing to show where it stands.", .info)
                    self.load(showSpinner: false)
                    self.retryMergeScan()
                } else {
                    let api = error as? ApiError
                    let primaryGone = api?.status == 404 && !(api?.detail.lowercased().contains("secondary") ?? false)
                    self.say(self.mergeError(error), .error)
                    if primaryGone || api?.status == 409 { self.load(showSpinner: false) }
                }
            }
        }
    }

    /// crm.py merge_customers refuses a typed target it can't find (404 "Secondary customer not found")
    /// and a profile merged into itself (422). The operator can act on the difference.
    private func mergeError(_ e: Error) -> String {
        let api = e as? ApiError
        if api?.status == 404 && (api?.detail.lowercased().contains("secondary") ?? false) {
            return "Failed to merge profiles — no customer found for that phone / wa_id"
        }
        if api?.status == 404 { return "Failed to merge profiles — this profile is gone (it may already have been merged into another). Refreshing." }
        if api?.status == 422 { return "Failed to merge profiles — that's this same profile" }
        if api?.status == 409 { return "Failed to merge profiles — \(CrmErrors.reason(e)) Refreshing." }
        return "Failed to merge profiles — \(CrmErrors.reason(e))"
    }

    public func unmerge(_ mergedId: String) {
        if ui.unmerging.contains(mergedId) { return }
        mut { $0.unmerging.insert(mergedId) }
        let k = key, ch = channel
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.unmerging.remove(mergedId) } }
            do {
                try await self.crm.unmerge(key: k, channel: ch, target: mergedId)
                if Task.isCancelled { return }
                self.say("Unmerged")
                self.load(showSpinner: false)
            } catch {
                if Task.isCancelled { return }
                switch CrmErrors.failure(of: error) {
                // crm.py: "No active merge to undo for this pair" — someone else already undid it.
                case .notFound:
                    self.say("Already unmerged — refreshed to show where it stands.", .info)
                    self.load(showSpinner: false)
                case .uncertain:
                    self.say("Couldn't confirm the unmerge — refreshing to show where it stands.", .info)
                    self.load(showSpinner: false)
                case .conflict:
                    self.say("Failed to unmerge — \(CrmErrors.reason(error)) Refreshing.", .error)
                    self.load(showSpinner: false)
                default:
                    self.say("Failed to unmerge — \(CrmErrors.reason(error))", .error)
                }
            }
        }
    }

    // ── Made-to-order enquiry ────────────────────────────────────────────────

    /// GET the conversation's enquiry. A failure keeps what is shown; the next reload tries again.
    private func loadEnquiry() {
        if enquiryJob?.isActive == true { return }
        let seq = enquirySeq
        let convId = conversation.id
        enquiryJob = launch { [weak self] in
            guard let self = self else { return }
            do {
                let e = try await self.crm.enquiry(conversationId: convId)
                if Task.isCancelled { return }
                self.enquiryFailed = false
                if seq == self.enquirySeq && !self.ui.pushing && !self.declining { self.mut { $0.enquiry = e } }
            } catch {
                if Task.isCancelled { return }
                // The web shows no card; a later reload (reconnect, pull) fills it in.
                self.enquiryFailed = true
            }
        }
    }

    private func refetchEnquiry() {
        enquiryJob?.cancel()
        enquirySeq += 1
        loadEnquiry()
    }

    public func pushProduction() {
        guard let e = ui.enquiry else { return }
        if ui.pushing || declining || e.status != "new" { return }
        mut { $0.pushing = true }
        enquirySeq += 1
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.pushing = false } }
            do {
                let r = try await self.crm.pushProduction(enquiryId: e.id)
                if Task.isCancelled { return }
                let n = r.hubOrderNumber ?? e.hubOrderNumber
                var pushed = e; pushed.status = "pushed"; pushed.hubOrderNumber = n
                self.mut { $0.enquiry = pushed }
                if r.already { self.say(n.map { "Already in production · \($0)" } ?? "Already in production") }
                else { self.say(r.hubOrderNumber.map { "Sent to production · \($0)" } ?? "Sent to production") }
            } catch {
                if Task.isCancelled { return }
                self.mut { $0.pushing = false }
                switch CrmErrors.failure(of: error) {
                // crm.py push_production is idempotent, so a second tap can never double the order.
                case .uncertain:
                    self.say("Couldn't confirm it reached production — checking. Pushing again is safe: it never makes a second order.", .info)
                    self.refetchEnquiry()
                case .notFound:
                    self.mut { $0.enquiry = nil }
                    self.say("This made-to-order request no longer exists — someone may have removed it.", .error)
                case .conflict:
                    self.say("This request was already handled — showing where it stands.", .info)
                    self.refetchEnquiry()
                // 422: the enquiry has no linked hub product — its detail tells the operator what to do instead.
                case .invalid:
                    self.say(CrmErrors.humanDetail(error) ?? "Couldn't send to production — \(CrmErrors.reason(error))", .error)
                // 502: the hub refused; its detail is an exception string, not for people.
                case .server:
                    self.say((error as? ApiError)?.status == 502 ? "Couldn't send to production — the hub didn't accept it. Try again in a moment."
                             : "Couldn't send to production — \(CrmErrors.reason(error))", .error)
                default:
                    self.say("Couldn't send to production — \(CrmErrors.reason(error))", .error)
                }
            }
        }
    }

    public func declineProduction() {
        guard let e = ui.enquiry else { return }
        if declining || ui.pushing || e.status != "new" { return }
        declining = true
        enquirySeq += 1
        var declined = e; declined.status = "declined"
        mut { $0.enquiry = declined }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.declining = false }
            do {
                try await self.crm.declineProduction(enquiryId: e.id)
            } catch {
                if Task.isCancelled { return }
                switch CrmErrors.failure(of: error) {
                case .uncertain: self.declining = false; self.refetchEnquiry()   // it may have: ask
                case .notFound: self.mut { $0.enquiry = nil }                      // gone either way
                default:
                    self.mut { $0.enquiry = e }
                    self.say("Couldn't dismiss — \(CrmErrors.reason(error))", .error)
                }
            }
        }
    }

    // ── Ask Neema / Answer via Neema ─────────────────────────────────────────

    /// The web keeps the question in the box after asking (to refine it); so does this.
    public func ask(_ question: String? = nil) {
        let q = (question ?? ui.askDraft).trimmingCharacters(in: .whitespacesAndNewlines)
        if q.isEmpty || ui.askBusy { return }
        mut { $0.askBusy = true; $0.askAnswer = nil }
        let convId = conversation.id
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.askBusy = false } }
            do {
                let a = try await self.host.api.askNeema(convId: convId, question: q).answer
                if Task.isCancelled { return }
                self.mut { $0.askAnswer = a }
            } catch {
                if Task.isCancelled { return }
                let text: String
                switch CrmErrors.failure(of: error) {
                case .offline: text = "You're offline — ask again once you're connected."
                case .uncertain: text = "Neema took too long to answer — try again."
                case .sessionExpired: text = "Your session expired — sign in again, then ask again."
                case .rateLimited: text = "Neema is busy — wait a moment, then ask again."
                case .notFound: text = "This conversation no longer exists."
                default: text = "Couldn't check right now — try again."
                }
                self.mut { $0.askAnswer = text }
            }
        }
    }

    /// Clears the box only once Neema sent it; any failure keeps the facts to send again.
    public func answerViaNeema(_ facts: String? = nil, onSent: @escaping () -> Void = {}) {
        let f = (facts ?? ui.answerDraft).trimmingCharacters(in: .whitespacesAndNewlines)
        if f.isEmpty || ui.answerBusy { return }
        mut { $0.answerBusy = true; $0.answerStatus = nil }
        let convId = conversation.id
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.answerBusy = false } }
            do {
                let r = try await self.host.api.answerViaNeema(convId: convId, facts: f)
                if Task.isCancelled { return }
                self.mut { s in
                    s.answerStatus = "Neema sent: “\(r.sent)”"
                    if s.answerDraft.trimmingCharacters(in: .whitespacesAndNewlines) == f { s.answerDraft = "" }
                }
                onSent()
            } catch {
                if Task.isCancelled { return }
                let api = error as? ApiError
                let text: String
                if CrmErrors.mayHaveLanded(error) {
                    // Never "couldn't send" for a turn that may have gone out to the customer.
                    text = "Couldn't confirm Neema sent it — check the thread before sending again."
                } else if api?.status == 409 || (api?.detail.lowercased().contains("window") ?? false) {
                    text = "Outside the messaging window — reply yourself when they next write."
                } else {
                    switch CrmErrors.failure(of: error) {
                    case .offline: text = "You're offline — your answer is kept; send it once you're connected."
                    case .sessionExpired: text = "Your session expired — sign in again, then send. Your answer is kept."
                    case .rateLimited: text = "Too many requests — wait a moment, then send again."
                    case .notFound: text = "This conversation no longer exists."
                    default: text = "Couldn't send right now — try again."
                    }
                }
                self.mut { $0.answerStatus = text }
            }
        }
    }

    // ── Calls ────────────────────────────────────────────────────────────────

    /// The WhatsApp number this customer's calls are logged under (nil: nobody to call).
    public func callsKey() -> String? {
        if conversation.channel == "whatsapp", let w = conversation.waId, let d = Crm.realPhoneDigits(w) { return d }
        return Crm.realPhoneDigits(profile?.phone)
    }

    /// A Messenger chat's PSID: its Messenger calls are this customer's too (never shown).
    public func psidForCalls() -> String? { CustomerWords.messengerPsid(conversation) }

    /// The Calls section's permission / request is about Messenger: a Messenger chat while Messenger can call.
    private func permissionOnMessenger() -> Bool { psidForCalls() != nil && host.messengerCallsOn }

    /// The name the Calls section addresses the customer by.
    public func displayNameForCalls() -> String? { profile?.name ?? conversation.name }

    /// GET /admin/calls?wa_id= (and ?psid= on a Messenger chat) — the last `RECENT_CALLS` calls on both apps we know them on.
    public func loadCalls() {
        let wa = callsKey()
        let psid = psidForCalls()
        if wa == nil && psid == nil { return }
        if callsJob?.isActive == true { return }
        callsJob = launch { [weak self] in
            guard let self = self else { return }
            do {
                var rows: [Call] = []
                if let w = wa { rows += try await self.host.api.calls.list(waId: w, limit: Self.RECENT_CALLS).filter { $0.waId == w } }
                if let p = psid { rows += try await self.host.api.calls.list(limit: Self.RECENT_CALLS, psid: p).filter { $0.externalId == p && $0.channel == "messenger" } }
                if Task.isCancelled { return }
                var seen = Set<String>()
                let distinct = rows.filter { seen.insert($0.callId).inserted }.sorted { ($0.startedAt ?? "") > ($1.startedAt ?? "") }
                self.mut { $0.recentCalls = Array(distinct.prefix(Self.RECENT_CALLS)) }
            } catch {
                if Task.isCancelled { return }
                if self.ui.recentCalls == nil { self.mut { $0.recentCalls = [] } }
            }
        }
    }

    /// GET /admin/calls/permission for this customer. A failure keeps what is shown.
    public func loadPermission() {
        let psid = permissionOnMessenger() ? psidForCalls() : nil
        let wa = callsKey()
        if psid == nil && wa == nil { return }
        if permissionJob?.isActive == true { return }
        permissionJob = launch { [weak self] in
            guard let self = self else { return }
            do {
                let p: CallPermission = psid != nil ? try await self.host.api.calls.messengerPermission(psid: psid!) : try await self.host.api.calls.permission(waId: wa!)
                if Task.isCancelled { return }
                self.mut { $0.callPermission = p }
            } catch {
                // keep what is shown
            }
        }
    }

    /// "Send call request" from the Calls section — only on the agent's tap (it messages the customer).
    /// The server's refusals say what to do next: `template_required`, `138009` (when they can ask again), `already_permitted`.
    public func sendCallRequest() {
        let messenger = permissionOnMessenger()
        guard let to = messenger ? psidForCalls() : callsKey() else { return }
        if ui.callRequest.busy { return }
        mut { $0.callRequest = CallRequestUi(busy: true) }
        let name = profile?.name ?? conversation.name
        let admin = host.canManageSettings
        launch { [weak self] in
            guard let self = self else { return }
            do {
                let resp = try await self.host.requestCallPermission(to: to, name: name, channel: messenger ? CallWords.MESSENGER : CallWords.WHATSAPP)
                if Task.isCancelled { return }
                self.mut { s in
                    s.callRequest = resp.alreadyPermitted ? CallRequestUi(alreadyAllowed: true) : CallRequestUi(sent: true)
                    if let p = resp.permission {
                        var cur = s.callPermission ?? p
                        cur.status = p.status; cur.permanent = p.permanent; cur.expiresAt = p.expiresAt; cur.at = p.at
                        cur.canCall = p.status == "granted" ? true : s.callPermission?.canCall
                        s.callPermission = cur
                    }
                }
            } catch {
                if Task.isCancelled { self.mut { $0.callRequest = CallRequestUi() }; return }
                let refusal = CallRequests.refusal(error, admin: admin)
                if refusal?.code == "138009" || refusal?.code == "request_limit" {
                    self.mut { s in
                        var cur = s.callPermission ?? CallPermission(waId: to)
                        cur.canRequest = false
                        cur.requestAvailableAt = (error as? ApiError)?.field("request_available_at") ?? cur.requestAvailableAt
                        s.callPermission = cur
                        s.callRequest = CallRequestUi()
                    }
                } else {
                    let text = refusal?.code == "template_required" ? refusal!.detail : CallRequests.permissionRequestError(error)
                    self.mut { $0.callRequest = CallRequestUi(error: text, adminCanFix: refusal?.adminCanFix == true, templateRequired: refusal?.code == "template_required") }
                }
            }
        }
    }

    /// While the section is on screen: a `call_update` for this customer lands in place;
    /// any other call frame reads the list again (a burst is one read).
    public func watchCalls() {
        callsWatch?.cancel()
        callsWatch = host.socketEvents.observe { [weak self] e in
            onMain { self?.onCallFrame(e) }
        }
    }

    private func onCallFrame(_ e: JSONValue) {
        let type = e["type"]?.content
        // Their answer to a call request (or WhatsApp's automatic revoke): read where it stands now.
        if type == "call_permission" {
            func field(_ k: String) -> String? { e[k]?.content.map { $0.hasPrefix("+") ? String($0.dropFirst()) : $0 } }
            let messenger = field("channel") == "messenger"
            let who = messenger ? field("external_id") : field("wa_id")
            if let w = who, w == (messenger ? psidForCalls() : callsKey()) { permissionJob?.cancel(); loadPermission() }
            return
        }
        guard type == "call_update" || type == "call_ended" || type == "incoming_call" || type == "call_answered" else { return }
        let wa = callsKey()
        let psid = psidForCalls()
        if wa == nil && psid == nil { return }
        if type == "call_update" {
            let row: Call? = e["call"].flatMap { c in (try? NeemaJSON.decode(Call.self, from: c.text)) }
            if let r = row, (wa != nil && r.waId == wa) || (psid != nil && r.channel == "messenger" && r.externalId == psid) {
                mut { s in
                    let cur = s.recentCalls ?? []
                    let next = cur.contains { $0.callId == r.callId } ? cur.map { $0.callId == r.callId ? r : $0 } : [r] + cur
                    s.recentCalls = Array(next.prefix(Self.RECENT_CALLS))
                }
                return
            }
            if row != nil { return }
        }
        if callsPending?.isActive == true { return }
        callsPending = launch { [weak self] in
            guard let self = self else { return }
            try? await self.sleep(Self.CALLS_DEBOUNCE_MS)
            if Task.isCancelled { return }
            self.loadCalls()
        }
    }

    /// "Ask for their WhatsApp number" (a Messenger / Instagram customer with no phone on file):
    /// the question goes in this thread's composer — never sent by itself.
    public func askForWhatsAppNumber() {
        let first = firstNameOf(profile?.name ?? conversation.name)
        host.composerPrefill.update(ComposerPrefill(convId: conversation.id,
            text: "Hi\(first.map { " \($0)" } ?? ""), could you share your WhatsApp number? We can give you a call there."))
    }

    // ── Reach-out: invite, template, call ────────────────────────────────────
    // Only ever to a real phone (realPhoneDigits): never a web visitor's hash.

    /// `profile.phone || digits`, as the web sends it — but never a web visitor's key.
    private func sendTo(_ p: CustomerProfile, _ digits: String) -> String {
        if let ph = p.phone, !ph.isEmpty, Crm.realPhoneDigits(ph) != nil { return ph }
        return digits
    }

    /// Send the approved WhatsApp invite; if that is refused, hand back a prefilled wa.me link to open
    /// instead (the web's fallback). A timeout may have delivered it: no second message then.
    public func inviteToWhatsApp(_ digits: String, openUrl: @escaping (String) -> Void) {
        guard let p = profile else { return }
        if Crm.realPhoneDigits(p.phone) == nil || ui.inviteBusy { return }
        mut { $0.inviteBusy = true }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.inviteBusy = false } }
            do {
                _ = try await self.host.api.whatsappInvite(phone: self.sendTo(p, digits), name: p.name ?? "")
                if Task.isCancelled { return }
                self.say("WhatsApp invite sent ✓")
            } catch {
                if Task.isCancelled { return }
                if CrmErrors.mayHaveLanded(error) {
                    self.say("Couldn't confirm the invite went out — check the WhatsApp thread before sending again.", .info)
                } else if CrmErrors.failure(of: error) == .sessionExpired || self.hidden {
                    // Signed out, or the panel is gone: never throw WhatsApp open out of nowhere.
                    self.say("Couldn't send the WhatsApp invite — \(CrmErrors.reason(error))", .error)
                } else {
                    let first = (p.name ?? "").trimmingCharacters(in: .whitespaces).split(whereSeparator: { $0.isWhitespace }).first.map(String.init) ?? ""
                    let invite = "Hello\(first.isEmpty ? "" : " \(first)"), this is Bethany House. Continuing our chat here on WhatsApp so we can finalise your order."
                    openUrl("https://wa.me/\(digits)?text=\(CustomerWords.urlEncode(invite))")
                }
            }
        }
    }

    public func sendTemplate(_ digits: String) {
        guard let p = profile else { return }
        if Crm.realPhoneDigits(p.phone) == nil || ui.templateBusy { return }
        mut { $0.templateBusy = true }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.templateBusy = false } }
            do {
                _ = try await self.host.api.whatsappInvite(phone: self.sendTo(p, digits), name: p.name ?? "")
                if Task.isCancelled { return }
                self.say("Template sent ✓")
            } catch {
                if Task.isCancelled { return }
                if CrmErrors.mayHaveLanded(error) {
                    self.say("Couldn't confirm the template went out — check the WhatsApp thread before sending again.", .info)
                } else {
                    let api = error as? ApiError
                    let why = (api?.status == 400 ? CrmErrors.humanDetail(error) : nil) ?? CrmErrors.reason(error)
                    self.say("Couldn't send the template — \(why)", .error)
                }
            }
        }
    }

    /// Messenger voice call (only offered while Messenger calling is on). The call screen carries what happens next.
    public func callOnMessenger(_ psid: String) {
        if ui.callBusy { return }
        mut { $0.callBusy = true }
        let name = profile?.name ?? conversation.name
        let chat = conversation.id.hasPrefix("call:") ? nil : conversation.id
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.callBusy = false } }
            let r = await self.host.placeMessengerCall(psid: psid, name: name, convId: chat)
            if Task.isCancelled { return }
            if case .failed(let m) = r { self.say(m.trimmingCharacters(in: .whitespaces).isEmpty ? "Couldn't place the call" : m, .error) }
        }
    }

    /// WhatsApp voice call. One at a time. The call screen carries what happens next;
    /// only a refusal the screen doesn't show is a toast.
    public func call(_ digits: String) {
        guard let p = profile else { return }
        if Crm.realPhoneDigits(p.phone) == nil || ui.callBusy { return }
        mut { $0.callBusy = true }
        // The call screen's "Open chat" opens this thread when it is the customer's WhatsApp one.
        let chat = conversation.channel == "whatsapp" && !conversation.id.hasPrefix("call:") ? conversation.id : nil
        let name = p.name
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.mut { $0.callBusy = false } }
            let r = await self.host.placeCall(waId: digits, name: name, convId: chat)
            if Task.isCancelled { return }
            if case .failed(let m) = r { self.say(m.trimmingCharacters(in: .whitespaces).isEmpty ? "Couldn't place the call" : m, .error) }
        }
    }
}
