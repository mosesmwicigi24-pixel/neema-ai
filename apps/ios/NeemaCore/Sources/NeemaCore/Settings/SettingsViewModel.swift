import Foundation

/// The shell as the Settings screen sees it: the API, the app's foreground
/// state, the live socket's frames (the calling card follows `call_settings`)
/// and the toasts.
public protocol SettingsHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var api: NeemaApi { get }
    var socketEvents: Signal<JSONValue> { get }
    func toast(_ message: String, _ type: ToastType)
}

/// SettingsScreen's state, in one watched value.
public struct SettingsUi: Equatable, Sendable {
    // Standing orders
    public var directives = ""
    public var maxChars = 600
    /// The box unlocks only once the real text has arrived (see `loadDirectives`).
    public var directivesLoaded = false
    public var savingDirectives = false
    // Translation
    public var translation: TranslationSetting? = nil
    // Offer
    public var offer: OfferSetting? = nil
    public var draft = Campaign()
    public var savingOffer = false
    // Pipeline stages
    /// The "add a stage" box. Held here so a save on the wire when the phone turns still clears it.
    public var newStage = ""
    public var stages: [String]? = nil
    public var savingStages = false
    // Local-only
    public var biz = BizSettings()
    public var ai = AiSettings()
    public var integrations = INTEGRATIONS
    public var integConfig: [String: [String: String]] = [:]
    public var savingBiz = false
    public var savingAi = false
    public var refreshing = false
    /// Why a live card couldn't be read, by card ("directives", "translation",
    /// "offer", "stages"). The web leaves such a card on "Loading…" forever
    /// (or, for standing orders, unlocks an empty box whose save would wipe
    /// the real ones); here the card says why and offers Retry.
    public var loadErrors: [String: String] = [:]
    public init() {}
}

/// SettingsView.tsx (Android `SettingsViewModel`). Four cards are live
/// (standing orders, translation, the offer, and the custom pipeline stages
/// the web edits from the customer panel); Business, AI, Integrations and
/// Danger Zone are local-only on the web too and behave the same here (they
/// toast but persist nothing).
@MainActor
public final class SettingsViewModel {
    public let host: SettingsHost
    public let state = Watched<SettingsUi>(SettingsUi())
    /// Settings → WhatsApp calling (read only when its card is on screen, for manage_settings).
    public let calling: CallingSettingsModel
    /// SettingsView reads its four live cards on mount. This model outlives
    /// the screen, so each return to it re-reads them — except a card with
    /// unsaved typing: the web's remount throws a half-written standing order
    /// or offer away, here it is kept (pull-to-refresh still reloads all).
    public private(set) var life: ScreenLife!
    private let api: NeemaApi.Settings
    private let sleep: Sleeper
    private var jobs: [UUID: Job] = [:]
    private var closed = false
    /// Reads on the wire, by card: a card's Retry while it is on the wire does nothing.
    private var inFlight: [String: Int] = [:]
    private var savingTranslation = false
    /// What the directives box / offer draft held when last loaded or saved: equal means nothing unsaved.
    private var directivesBase: String? = nil
    private var draftBase: Campaign? = nil
    /// Unsaved standing orders / offer from before iOS reclaimed the app, put back once the card has loaded.
    private var pendingDirectives: String? = nil
    private var pendingDraft: Campaign? = nil
    public var uiAttached = false

    public init(host: SettingsHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        self.sleep = sleep
        api = host.api.settings
        calling = CallingSettingsModel(api: NeemaCallingSettingsApi(host.api), events: host.socketEvents)
        life = ScreenLife(foreground: host.foreground, catchUpOnForeground: false, sleep: sleep, catchUp: { [weak self] in
            await self?.reread()
        })
        launch { [weak self] in await self?.loadAll() }
    }

    public var ui: SettingsUi { state.value }

    /// A read or a write is on the wire (tests wait for it to land).
    public var busy: Bool {
        let s = ui
        return inFlight.values.contains { $0 > 0 } || s.savingDirectives || savingTranslation || s.savingOffer || s.savingStages
            || s.refreshing || s.savingBiz || s.savingAi
    }

    private func mut(_ f: (inout SettingsUi) -> Void) {
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

    private func gone(_ e: Error) -> Bool { closed || SalesErrors.isCancellation(e) }

    // ── Loads ────────────────────────────────────────────────────────────────

    private func loadFailed(_ card: String, _ e: Error) {
        mut { $0.loadErrors[card] = FriendlyErrors.text(of: e, fallback: SettingsWords.LOAD_FALLBACK) }
    }

    private func loaded(_ card: String) { mut { $0.loadErrors[card] = nil } }

    private func begin(_ card: String) { inFlight[card, default: 0] += 1 }
    private func end(_ card: String) { inFlight[card] = max(0, (inFlight[card] ?? 1) - 1) }

    private func reread() async {
        let d = ui.directives == directivesBase
        let o = ui.draft == draftBase
        async let a: Void = loadIf(d, "directives")
        async let b: Void = loadTranslation()
        async let c: Void = loadIf(o, "offer")
        async let e: Void = loadStages()
        _ = await (a, b, c, e)
    }

    /// Each card loads on its own; one failing must not blank the others.
    private func loadAll() async {
        async let a: Void = loadDirectives()
        async let b: Void = loadTranslation()
        async let c: Void = loadOffer()
        async let d: Void = loadStages()
        _ = await (a, b, c, d)
    }

    private func loadIf(_ run: Bool, _ card: String) async { if run { await load(card) } }

    private func load(_ card: String) async {
        switch card {
        case "directives": await loadDirectives()
        case "translation": await loadTranslation()
        case "offer": await loadOffer()
        case "stages": await loadStages()
        default: break
        }
    }

    /// Pull-to-refresh: every live card again (and the calling card, unless it has unsaved edits).
    public func refresh() {
        if ui.refreshing { return }
        mut { $0.refreshing = true }
        launch { [weak self] in
            guard let self = self else { return }
            self.calling.refreshIfShown()
            await self.loadAll()
            if !self.closed { self.mut { $0.refreshing = false } }
        }
    }

    /// A card's Retry: reads that one card again (a second tap while it is on the wire does nothing).
    public func retry(_ card: String) {
        if (inFlight[card] ?? 0) > 0 { return }
        launch { [weak self] in await self?.load(card) }
    }

    private func loadTranslation() async {
        begin("translation"); defer { end("translation") }
        do {
            let t = try await api.getTranslation()
            if closed { return }
            mut { $0.translation = t }
            loaded("translation")
        } catch {
            if gone(error) { return }
            // A card already showing the switch keeps it; only an empty one says why.
            if ui.translation == nil { loadFailed("translation", error) }
        }
    }

    private func loadStages() async {
        begin("stages"); defer { end("stages") }
        do {
            let s = try await api.getPipelineStages()
            if closed { return }
            mut { $0.stages = s }
            loaded("stages")
        } catch {
            if gone(error) { return }
            // Never fall back to "no custom stages": adding one to that would
            // replace the real list with a single stage.
            if ui.stages == nil { loadFailed("stages", error) }
        }
    }

    /// Deliberate fix: the web unlocks the box even when this read fails, so an
    /// admin on a dropped connection sees an empty box, and saving it would
    /// wipe the standing orders Neema is following. Here the box stays locked
    /// until the real text has arrived, and the card says why, with Retry.
    private func loadDirectives() async {
        begin("directives"); defer { end("directives") }
        do {
            let r = try await api.getDirectives()
            if closed { return }
            mut { s in
                s.directives = r.directives
                if r.maxChars > 0 { s.maxChars = r.maxChars }
            }
            directivesBase = ui.directives
            // Typing the process lost when iOS reclaimed the app goes back in the box, unsaved.
            if let p = pendingDirectives {
                pendingDirectives = nil
                mut { $0.directives = String(p.prefix($0.maxChars)) }
            }
            mut { $0.directivesLoaded = true }
            loaded("directives")
        } catch {
            if gone(error) { return }
            // Already loaded once: the box keeps what it holds.
            if !ui.directivesLoaded { loadFailed("directives", error) }
        }
    }

    private func loadOffer() async {
        begin("offer"); defer { end("offer") }
        do {
            let r = try await api.getOffer()
            if closed { return }
            mut { $0.offer = r; $0.draft = r.campaign ?? Self.blankCampaign() }
            draftBase = ui.draft
            if let p = pendingDraft {
                pendingDraft = nil
                mut { $0.draft = p }
            }
            loaded("offer")
        } catch {
            if gone(error) { return }
            // Never show a wrong state: an unread card says why (with Retry); a
            // card already showing the offer keeps it.
            if ui.offer == nil {
                draftBase = ui.draft
                loadFailed("offer", error)
            }
        }
    }

    /// What a save that failed says. `adminOnly` is the web's words for a 403;
    /// a timeout never reaches here (the caller re-reads the truth first). A
    /// 403 also makes the shell re-read who this agent is (the HTTP layer's
    /// `forbidden` signal), as Android's `refreshAfterForbidden`.
    private func saveFailure(_ e: Error, adminOnly: String, fallback: String) -> String {
        switch FriendlyErrors.httpStatus(e) {
        case 403: return adminOnly
        case 429: return FriendlyErrors.BUSY_TEXT
        case 422: return (e as? ApiError).flatMap(FriendlyErrors.readableDetail) ?? fallback
        default: return FriendlyErrors.text(of: e, fallback: fallback)
        }
    }

    private static func trimmed(_ s: String) -> String { s.trimmingCharacters(in: .whitespacesAndNewlines) }

    // ── Standing orders ──────────────────────────────────────────────────────

    public func setDirectives(_ v: String) { mut { $0.directives = String(v.prefix($0.maxChars)) } }

    public func saveDirectives() {
        if ui.savingDirectives || !ui.directivesLoaded { return }
        mut { $0.savingDirectives = true }
        let text = ui.directives
        let max = ui.maxChars
        launch { [weak self] in
            guard let self = self else { return }
            defer { if !self.closed { self.mut { $0.savingDirectives = false } } }
            do {
                let r = try await self.api.putDirectives(text)
                if self.closed { return }
                if let kept = r["directives"]?.stringValue { self.mut { $0.directives = kept } }
                self.directivesBase = self.ui.directives
                self.host.toast(SettingsWords.DIRECTIVES_SAVED, .success)
            } catch {
                if self.gone(error) { return }
                // No answer: read what the server holds now. If it is what was sent, it saved.
                let lost = FriendlyErrors.mayHaveApplied(error)
                var landed = false
                if lost, let now = try? await self.api.getDirectives() {
                    landed = Self.trimmed(now.directives) == Self.trimmed(String(Self.trimmed(text).prefix(max)))
                }
                if self.closed { return }
                if landed {
                    self.directivesBase = text
                    self.host.toast(SettingsWords.DIRECTIVES_SAVED, .success)
                } else {
                    // The API never refuses the text itself (it trims and cuts to
                    // max_chars); a refusal is the admin check. The typed text stays.
                    self.host.toast(
                        lost ? UNCERTAIN_SAVE : self.saveFailure(error, adminOnly: SettingsWords.DIRECTIVES_ADMIN_ONLY, fallback: SettingsWords.DIRECTIVES_FAILED),
                        .error
                    )
                }
            }
        }
    }

    // ── Translation ──────────────────────────────────────────────────────────

    public func toggleTranslation() {
        guard let state = ui.translation, !savingTranslation else { return }
        let next = !state.enabled
        var optimistic = state
        optimistic.enabled = next
        mut { $0.translation = optimistic }   // optimistic: the switch must feel instant
        savingTranslation = true
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.savingTranslation = false }
            do {
                _ = try await self.api.putTranslation(enabled: next)
                if self.closed { return }
                self.host.toast(next ? SettingsWords.TRANSLATION_ON : SettingsWords.TRANSLATION_OFF, .success)
            } catch {
                if self.gone(error) { return }
                if FriendlyErrors.mayHaveApplied(error) {
                    // No answer: it may have switched. Show the server's setting, not a guess.
                    let truth = try? await self.api.getTranslation()
                    if self.closed { return }
                    if let t = truth { self.mut { $0.translation = t } } else { self.mut { $0.translation?.enabled = !next } }
                    if truth?.enabled != next {
                        self.host.toast("Couldn't reach the server — translation is still \(next ? "off" : "on")", .error)
                    }
                } else {
                    self.mut { $0.translation?.enabled = !next }   // put it back; nothing was saved
                    self.host.toast(self.saveFailure(error, adminOnly: SettingsWords.TRANSLATION_ADMIN_ONLY, fallback: SettingsWords.TRANSLATION_FAILED), .error)
                }
            }
        }
    }

    // ── Offer ────────────────────────────────────────────────────────────────

    /// Today by the phone's calendar (Android `AppClock.today()`).
    public static func today() -> LocalDay { LocalDay.today(zone: Fmt.timeZone) }

    /// "For 1 month" is the common case, so a new offer ends a month from today.
    public static func blankCampaign() -> Campaign {
        Campaign(name: "", percent: 10, scope: "all", categories: [], skus: [], startsOn: nil, endsOn: today().plusMonths(1).description)
    }

    /// The card's cap: the server's `max_percent`, else promotions.MAX_PERCENT.
    public static func maxPercent(_ offer: OfferSetting?) -> Int {
        let m = Int(offer?.maxPercent ?? 0)
        return m > 0 ? m : 70
    }

    public func editDraft(_ change: (inout Campaign) -> Void) { mut { change(&$0.draft) } }

    /// `campaign` nil ends the offer now.
    public func saveOffer(_ campaign: Campaign?) {
        if ui.savingOffer { return }
        let max = Self.maxPercent(ui.offer)
        // What the server would answer with a 422 — said without the round trip, and naming the field.
        if let c = campaign, let problem = offerProblem(c, maxPercent: max) { return host.toast(problem, .error) }
        mut { $0.savingOffer = true }
        launch { [weak self] in
            guard let self = self else { return }
            defer { if !self.closed { self.mut { $0.savingOffer = false } } }
            do {
                let r = try await self.api.putOffer(campaign)
                if self.closed { return }
                self.offerSaved(r.campaign, running: r.running, says: r.says)
            } catch {
                if self.gone(error) { return }
                // No answer: read the offer back. If it is the one sent (or gone,
                // when ending it), the save landed; either way the card shows the truth.
                let lost = FriendlyErrors.mayHaveApplied(error)
                let now: OfferSetting? = lost ? (try? await self.api.getOffer()) : nil
                if self.closed { return }
                if let n = now, Self.sameOffer(n.campaign, campaign) {
                    self.mut { $0.offer = n }
                    self.offerSaved(n.campaign, running: n.running, says: n.says)
                    return
                }
                let status = FriendlyErrors.httpStatus(error)
                let msg: String
                if lost {
                    msg = UNCERTAIN_SAVE
                } else if status == 403 {
                    msg = SettingsWords.OFFER_ADMIN_ONLY
                } else if status == 422 {
                    // promotions.set_campaign's own reason ("a campaign needs a name, 1-70%, …").
                    msg = (error as? ApiError).flatMap(FriendlyErrors.readableDetail).map { "Couldn't save that offer — \($0)" } ?? OFFER_SAVE_FAILED
                } else if status == 0 || status == 401 || status == 429 || (502...504).contains(status ?? -1) {
                    msg = FriendlyErrors.text(of: error)
                } else {
                    msg = OFFER_SAVE_FAILED
                }
                self.host.toast(msg, .error)
            }
        }
    }

    /// The server kept `saved`: the card, the draft and the toast follow it.
    private func offerSaved(_ saved: Campaign?, running: Bool, says: String) {
        mut { s in
            if s.offer != nil { s.offer?.campaign = saved; s.offer?.running = running; s.offer?.says = says }
            s.draft = saved ?? Self.blankCampaign()
        }
        draftBase = ui.draft
        let msg: String
        if saved == nil {
            msg = SettingsWords.OFFER_ENDED
        } else if running && !Self.trimmed(says).isEmpty {
            msg = "Offer live — Neema will say: \(says)"
        } else if let s = saved?.startsOn, let d = parseIsoDate(s), d > Self.today() {
            // Saved but not live today: `says` is empty, so "Neema will say: " would promise nothing.
            msg = "Offer saved — Neema starts mentioning it on \(Fmt.date(s))"
        } else {
            msg = SettingsWords.OFFER_EXPIRED
        }
        host.toast(msg, .success)
    }

    /// Whether the stored offer is the one `sent` (the server may tidy lists and whitespace).
    static func sameOffer(_ stored: Campaign?, _ sent: Campaign?) -> Bool {
        guard let sent = sent else { return stored == nil }
        guard let stored = stored else { return false }
        func norm(_ l: [String]) -> Set<String> { Set(l.map { trimmed($0).lowercased() }.filter { !$0.isEmpty }) }
        return trimmed(stored.name) == trimmed(sent.name) && stored.percent == sent.percent
            && stored.scope == sent.scope && stored.endsOn == sent.endsOn
            && (stored.startsOn ?? "") == (sent.startsOn ?? "")
            && norm(stored.categories) == norm(sent.categories) && norm(stored.skus) == norm(sent.skus)
    }

    // ── Pipeline stages ──────────────────────────────────────────────────────

    /// The "add a stage" box, capped at the server's 18 characters.
    public func setNewStage(_ v: String) { mut { $0.newStage = String(v.prefix(PIPELINE_LABEL_MAX)) } }

    /// Sends `label` as a new stage; answers whether it went. `onSaved` runs
    /// once the server has kept it — the screen clears the typed label only
    /// then, so a failed save leaves it in the box to try again.
    @discardableResult
    public func addStage(_ label: String, onSaved: @escaping () -> Void = {}) -> Bool {
        let l = Self.trimmed(String(Self.trimmed(label).prefix(PIPELINE_LABEL_MAX)))
        if l.isEmpty { return false }
        // Not read yet: adding to "nothing" would replace the real list.
        guard let cur = ui.stages else { return false }
        if ui.savingStages { return false }
        if PIPELINE_CANONICAL.contains(l.lowercased()) {
            host.toast("“\(l)” is already a built-in stage", .warning); return false
        }
        if cur.contains(where: { $0.caseInsensitiveCompare(l) == .orderedSame }) {
            host.toast("“\(l)” is already a stage", .warning); return false
        }
        if cur.count >= PIPELINE_CUSTOM_MAX {
            host.toast("At most \(PIPELINE_CUSTOM_MAX) custom stages", .error); return false
        }
        saveStages(cur + [l], onSaved: onSaved)
        return true
    }

    public func removeStage(_ label: String) {
        guard let cur = ui.stages, let i = cur.firstIndex(of: label) else { return }
        var next = cur
        next.remove(at: i)
        saveStages(next)
    }

    private func saveStages(_ next: [String], onSaved: @escaping () -> Void = {}) {
        if ui.savingStages { return }
        mut { $0.savingStages = true }
        launch { [weak self] in
            guard let self = self else { return }
            defer { if !self.closed { self.mut { $0.savingStages = false } } }
            do {
                // The server drops blanks, duplicates and the built-in names; show what it kept.
                let r = try await self.api.putPipelineStages(next)
                if self.closed { return }
                self.mut { $0.stages = r.stages }
                onSaved()
            } catch {
                if self.gone(error) { return }
                // No answer: read the list back. The server's cleaning is
                // idempotent, so a list equal to what we sent (as it would keep it) means it saved.
                let lost = FriendlyErrors.mayHaveApplied(error)
                let now: [String]? = lost ? (try? await self.api.getPipelineStages()) : nil
                if self.closed { return }
                if let n = now { self.mut { $0.stages = n } }
                if let n = now, n.map({ $0.lowercased() }) == cleanStages(next).map({ $0.lowercased() }) { onSaved(); return }
                let status = FriendlyErrors.httpStatus(error)
                let msg: String
                if lost {
                    msg = UNCERTAIN_SAVE
                } else if status == 403 {
                    msg = SettingsWords.STAGES_ADMIN_ONLY
                } else if status == 422 {
                    msg = (error as? ApiError).flatMap(FriendlyErrors.readableDetail) ?? SettingsWords.STAGES_FAILED
                } else if status == 0 || status == 401 || status == 429 || (502...504).contains(status ?? -1) {
                    msg = FriendlyErrors.text(of: error)
                } else {
                    msg = SettingsWords.STAGES_FAILED
                }
                self.host.toast(msg, .error)
            }
        }
    }

    // ── Local-only sections ──────────────────────────────────────────────────

    public func editBiz(_ change: (inout BizSettings) -> Void) { mut { change(&$0.biz) } }
    public func editAi(_ change: (inout AiSettings) -> Void) { mut { change(&$0.ai) } }

    public func saveBiz() {
        if ui.savingBiz { return }
        mut { $0.savingBiz = true }
        launch { [weak self] in
            guard let self = self else { return }
            try? await self.sleep(600)
            if self.closed { return }
            self.mut { $0.savingBiz = false }
            self.host.toast("Business settings saved", .success)
        }
    }

    public func saveAi() {
        if ui.savingAi { return }
        mut { $0.savingAi = true }
        launch { [weak self] in
            guard let self = self else { return }
            try? await self.sleep(600)
            if self.closed { return }
            self.mut { $0.savingAi = false }
            self.host.toast("Neema settings saved", .success)
        }
    }

    public func toggleIntegration(_ key: String) {
        guard let integ = ui.integrations.first(where: { $0.key == key }) else { return }
        mut { s in s.integrations = s.integrations.map { var i = $0; if i.key == key { i.connected.toggle() }; return i } }
        host.toast("\(integ.name) \(integ.connected ? "disconnected" : "connected")", .success)
    }

    public func setConfig(_ integ: String, _ field: String, _ value: String) {
        mut { s in
            var fields = s.integConfig[integ] ?? [:]
            fields[field] = value
            s.integConfig[integ] = fields
        }
    }

    public func saveIntegConfig(_ key: String) {
        host.toast("\(ui.integrations.first { $0.key == key }?.name ?? "") settings saved", .success)
    }

    public func dangerAction() { host.toast(SettingsWords.DANGER, .warning) }

    // ── The app reclaimed ────────────────────────────────────────────────────

    /// What a restarted app gets back: unsaved typing in the standing orders
    /// and the offer (only when it differs from what the server holds), the
    /// stage being typed, and the local-only Business, AI and integration
    /// fields — every integration field marked secret (tokens, keys,
    /// passwords) excepted: those are never written to saved state.
    public func saveUi() -> String {
        var o: [String: JSONValue] = [:]
        let s = ui
        if let d = pendingDirectives ?? ((directivesBase != nil && s.directives != directivesBase) ? s.directives : nil) {
            o["directives"] = .string(d)
        }
        if let c = pendingDraft ?? ((draftBase != nil && s.draft != draftBase) ? s.draft : nil), let j = try? JSONValue(encoding: c) {
            o["offer"] = j
        }
        if !s.newStage.isEmpty { o["stage"] = .string(s.newStage) }
        if s.biz != BizSettings() {
            o["biz"] = .array([s.biz.businessName, s.biz.currency, s.biz.waNumber, s.biz.openHours, s.biz.timezone].map { .string($0) })
        }
        if s.ai != AiSettings() {
            o["ai"] = .array([.string(s.ai.autoInterceptThreshold), .bool(s.ai.draftApproval), .string(s.ai.responseDelayMs), .string(s.ai.escalationKeywords)])
        }
        let toggled = s.integrations.filter { i in i.connected != (INTEGRATIONS.first { $0.key == i.key }?.connected ?? i.connected) }
        if !toggled.isEmpty { o["toggled"] = .array(toggled.map { .string($0.key) }) }
        var plain: [String: JSONValue] = [:]
        for (k, fields) in s.integConfig {
            let secret = Set(INTEGRATIONS.first { $0.key == k }?.fields.filter { $0.secret }.map { $0.key } ?? [])
            let kept = fields.filter { !secret.contains($0.key) }
            if !kept.isEmpty { plain[k] = .object(kept.mapValues { .string($0) }) }
        }
        if !plain.isEmpty { o["config"] = .object(plain) }
        return JSONValue.object(o).text
    }

    public func restoreUi(_ saved: String) {
        guard let o = JSONValue.parse(saved)?.objectValue else { return }
        if let d = o["directives"]?.stringValue {
            if ui.directivesLoaded { mut { $0.directives = String(d.prefix($0.maxChars)) } } else { pendingDirectives = d }
        }
        if let e = o["offer"], let c = try? NeemaJSON.decode(Campaign.self, from: e) {
            if ui.offer != nil { mut { $0.draft = c } } else { pendingDraft = c }
        }
        if let st = o["stage"]?.stringValue { mut { $0.newStage = st } }
        if let a = o["biz"]?.arrayValue?.compactMap({ $0.stringValue }), a.count == 5 {
            mut { $0.biz = BizSettings(businessName: a[0], currency: a[1], waNumber: a[2], openHours: a[3], timezone: a[4]) }
        }
        if let a = o["ai"]?.arrayValue, a.count == 4 {
            mut {
                $0.ai = AiSettings(autoInterceptThreshold: a[0].stringValue ?? "", draftApproval: a[1].content == "true",
                                   responseDelayMs: a[2].stringValue ?? "", escalationKeywords: a[3].stringValue ?? "")
            }
        }
        if let keys = o["toggled"]?.arrayValue?.compactMap({ $0.stringValue }) {
            let set = Set(keys)
            mut { s in s.integrations = s.integrations.map { var i = $0; if set.contains(i.key) { i.connected.toggle() }; return i } }
        }
        if let cfg = o["config"]?.objectValue {
            var out: [String: [String: String]] = [:]
            for (k, v) in cfg { out[k] = (v.objectValue ?? [:]).compactMapValues { $0.stringValue } }
            mut { $0.integConfig = out }
        }
    }

    /// Restore once per model, the first time a screen attaches (iOS keeps the scene state per screen).
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
        calling.close()
        for j in jobs.values { j.cancel() }
        jobs = [:]
    }
}
