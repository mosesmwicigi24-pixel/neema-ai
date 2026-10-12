import Foundation

/// The routes the "WhatsApp calling" card uses (manage_settings) — a protocol so the rules run without a server.
public protocol CallingSettingsApi: AnyObject {
    func settings() async throws -> CallingSettings
    func save(_ change: JSONValue) async throws -> CallingSettingsSaved
    func template() async throws -> PermissionTemplate
    func createTemplate() async throws
}

public final class NeemaCallingSettingsApi: CallingSettingsApi {
    private let api: NeemaApi
    public init(_ api: NeemaApi) { self.api = api }
    public func settings() async throws -> CallingSettings { try await api.calls.settings() }
    public func save(_ change: JSONValue) async throws -> CallingSettingsSaved { try await api.calls.saveSettings(change) }
    public func template() async throws -> PermissionTemplate { try await api.calls.permissionTemplate() }
    public func createTemplate() async throws { _ = try await api.calls.createPermissionTemplate() }
}

/// The card's state: what WhatsApp has (`loaded`), what the admin is changing (`draft`), and how saving went.
public struct CallingSettingsUi: Equatable, Sendable {
    public var loaded: CallingSettings? = nil
    public var draft: CallingSettings? = nil
    public var loading = false
    public var loadError: String? = nil
    public var saving = false
    /// Why the last save failed (the server's sentence).
    public var saveError: String? = nil
    /// "Saved — …" after a save went through.
    public var saved = false
    /// Field → what is wrong with it (checked before anything is sent).
    public var fieldErrors: [String: String] = [:]
    /// WhatsApp said the settings changed (`call_settings`) while edits were unsaved.
    public var changedElsewhere = false
    public var template: PermissionTemplate? = nil
    public var templateError: String? = nil
    public var templateBusy = false
    public init() {}

    public var dirty: Bool {
        guard let l = loaded, let d = draft else { return false }
        return !CallingSettingsModel.changes(loaded: l, draft: d).isEmpty
    }
}

/// Settings → WhatsApp calling (CALLING_UX.md §2.1; Android
/// `CallingSettingsModel`): the number's calling settings as WhatsApp holds
/// them — callback permission, the call icon, voicemail, weekly call hours
/// and holidays, Meta's restrictions (read only) — plus the call-request
/// template used outside the 24 h window.
///
/// A save sends ONLY the fields the admin changed (the server merges
/// call_hours / voicemail over the current ones and always re-sends the
/// holiday schedule); nothing is sent when nothing changed. Changes can take
/// up to 7 days to reach customers' phones.
@MainActor
public final class CallingSettingsModel {
    public let state = Watched<CallingSettingsUi>(CallingSettingsUi())
    private let api: CallingSettingsApi
    /// Live frames: `call_settings` reloads the card.
    private let events: Signal<JSONValue>?
    private var started = false
    private var closed = false
    private var loadJob: Job?
    private var jobs: [UUID: Job] = [:]
    private var sub: Subscription?

    public init(api: CallingSettingsApi, events: Signal<JSONValue>? = nil) {
        self.api = api
        self.events = events
    }

    public var ui: CallingSettingsUi { state.value }

    private func mut(_ f: (inout CallingSettingsUi) -> Void) {
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

    /// The card came on screen: read once, then follow `call_settings`.
    public func start() {
        if started || closed { return }
        started = true
        load()
        loadTemplate()
        sub = events?.observe { [weak self] e in
            guard e["type"]?.stringValue == "call_settings" else { return }
            onMain { [weak self] in
                guard let self = self, !self.closed else { return }
                if self.ui.dirty { self.mut { $0.changedElsewhere = true } } else { self.load() }
            }
        }
    }

    /// Pull-to-refresh on Settings: read again, unless the admin has unsaved changes.
    public func refreshIfShown() {
        if started && !ui.dirty { load(); loadTemplate() }
    }

    public func load() {
        if loadJob?.isActive == true { return }
        mut { $0.loading = true; $0.loadError = nil }
        loadJob = launch { [weak self] in
            guard let self = self else { return }
            do {
                let s = try await self.api.settings()
                if self.closed { return }
                self.mut { $0.loaded = s; $0.draft = s; $0.loading = false; $0.changedElsewhere = false; $0.fieldErrors = [:] }
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                self.mut { $0.loading = false; $0.loadError = Self.reason(error, fallback: "Couldn't read the calling settings from WhatsApp.") }
            }
        }
    }

    public func loadTemplate() {
        launch { [weak self] in
            guard let self = self else { return }
            do {
                let t = try await self.api.template()
                if self.closed { return }
                self.mut { $0.template = t; $0.templateError = nil }
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                self.mut { $0.templateError = Self.reason(error, fallback: "Couldn't check the call-request template.") }
            }
        }
    }

    /// Change the draft (a toggle, a field).
    public func edit(_ change: (CallingSettings) -> CallingSettings) {
        guard let d = ui.draft else { return }
        let next = change(d)
        mut { $0.draft = next; $0.saved = false; $0.saveError = nil; $0.fieldErrors = [:] }
    }

    public func discard() {
        mut { $0.draft = $0.loaded; $0.fieldErrors = [:]; $0.saveError = nil; $0.changedElsewhere = false }
    }

    /// Save what changed — and only that.
    public func save() {
        let u = ui
        guard let loaded = u.loaded, let draft = u.draft, !u.saving else { return }
        let errors = Self.validate(draft)
        if !errors.isEmpty { mut { $0.fieldErrors = errors }; return }
        let change = Self.changes(loaded: loaded, draft: draft)
        if change.isEmpty { return }
        mut { $0.saving = true; $0.saveError = nil; $0.saved = false }
        launch { [weak self] in
            guard let self = self else { return }
            do {
                let r = try await self.api.save(.object(change))
                if self.closed { return }
                let fresh = r.settings ?? draft
                self.mut { $0.saving = false; $0.saved = true; $0.loaded = fresh; $0.draft = fresh; $0.changedElsewhere = false }
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                self.mut { $0.saving = false; $0.saveError = Self.reason(error, fallback: "Couldn't save the calling settings.") }
            }
        }
    }

    /// "Create template": the server's default wording; Meta reviews it before requests use it.
    public func createTemplate() {
        if ui.templateBusy { return }
        mut { $0.templateBusy = true; $0.templateError = nil }
        launch { [weak self] in
            guard let self = self else { return }
            do {
                try await self.api.createTemplate()
                let t = try? await self.api.template()
                if self.closed { return }
                self.mut { s in
                    s.templateBusy = false
                    if let t = t {
                        s.template = t
                    } else if var p = s.template {
                        p.configured = true; p.exists = true; p.status = "pending"
                        s.template = p
                    }
                }
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                self.mut { $0.templateBusy = false; $0.templateError = Self.reason(error, fallback: "Couldn't create the template.") }
            }
        }
    }

    public func close() {
        if closed { return }
        closed = true
        sub?.cancel()
        sub = nil
        loadJob?.cancel()
        for j in jobs.values { j.cancel() }
        jobs = [:]
    }

    // ── Rules ────────────────────────────────────────────────────────────────

    nonisolated public static let DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]

    private nonisolated static func json<T: Encodable>(_ v: T) -> JSONValue { (try? JSONValue(encoding: v)) ?? .null }

    /// The body of POST /calls/settings: only what differs between what
    /// WhatsApp has and the draft. call_hours / voicemail carry only their
    /// changed keys (the server merges them over the current ones).
    nonisolated public static func changes(loaded: CallingSettings, draft: CallingSettings) -> [String: JSONValue] {
        var o: [String: JSONValue] = [:]
        if draft.callbackPermissionStatus != loaded.callbackPermissionStatus, let v = draft.callbackPermissionStatus {
            o["callback_permission_status"] = .string(v)
        }
        if draft.callIconVisibility != loaded.callIconVisibility, let v = draft.callIconVisibility {
            o["call_icon_visibility"] = .string(v)
        }
        let lv = loaded.voicemail ?? CallVoicemail()
        let dv = draft.voicemail ?? CallVoicemail()
        var vm: [String: JSONValue] = [:]
        if dv.status != lv.status, let s = dv.status { vm["status"] = .string(s) }
        if dv.timeoutSeconds != lv.timeoutSeconds, let t = dv.timeoutSeconds { vm["timeout_seconds"] = .number(Double(t)) }
        if !vm.isEmpty { o["voicemail"] = .object(vm) }
        let lh = loaded.callHours ?? CallHours()
        let dh = draft.callHours ?? CallHours()
        var hours: [String: JSONValue] = [:]
        if dh.status != lh.status, let s = dh.status { hours["status"] = .string(s) }
        if dh.timezoneId != lh.timezoneId, let t = dh.timezoneId { hours["timezone_id"] = .string(t) }
        if dh.weekly != lh.weekly { hours["weekly_operating_hours"] = .array(dh.weekly.map(json)) }
        if dh.holidays != lh.holidays { hours["holiday_schedule"] = .array(dh.holidays.map(json)) }
        if !hours.isEmpty { o["call_hours"] = .object(hours) }
        return o
    }

    private nonisolated static func isHHMM(_ s: String) -> Bool { s.range(of: #"^([01]\d|2[0-3])[0-5]\d$"#, options: .regularExpression) != nil }
    private nonisolated static func isDate(_ s: String) -> Bool { s.range(of: #"^\d{4}-\d{2}-\d{2}$"#, options: .regularExpression) != nil }

    /// What would be refused, by field — said next to the field before anything is sent.
    nonisolated public static func validate(_ d: CallingSettings) -> [String: String] {
        var out: [String: String] = [:]
        if let t = d.voicemail?.timeoutSeconds, !(0...30).contains(t) { out["voicemail.timeout"] = "Between 0 and 30 seconds." }
        guard let h = d.callHours else { return out }
        for s in h.weekly {
            let key = "hours.\(s.dayOfWeek ?? "")"
            let o = s.openTime ?? "", c = s.closeTime ?? ""
            if !isHHMM(o) || !isHHMM(c) { out[key] = "Use 24-hour times like 09:00." }
            else if o >= c { out[key] = "Closing must be after opening." }
        }
        if h.holidays.count > 20 { out["holidays"] = "At most 20 holidays." }
        for (i, x) in h.holidays.enumerated() {
            let key = "holiday.\(i)"
            let start = x.startTime ?? "", end = x.endTime ?? ""
            if !isDate(x.date ?? "") { out[key] = "Use a date like 2026-12-25." }
            else if !isHHMM(start) || !isHHMM(end) { out[key] = "Use 24-hour times like 09:00." }
            else if start >= end { out[key] = "The end must be after the start." }
        }
        if h.status == "ENABLED" && (h.timezoneId ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            out["hours.timezone"] = "Choose a time zone (e.g. Africa/Nairobi)."
        }
        return out
    }

    /// "0900" ⇄ "09:00" for the time fields.
    nonisolated public static func showTime(_ hhmm: String?) -> String {
        guard let s = hhmm else { return "" }
        return s.count == 4 ? "\(s.prefix(2)):\(s.dropFirst(2))" : s
    }

    nonisolated public static func readTime(_ text: String) -> String {
        let digits = String(text.filter { $0.isASCII && $0.isNumber }.prefix(4))
        return digits.count == 3 ? "0" + digits : digits
    }

    /// The server's sentence for a refusal (its `detail`), else plain words for the failure.
    nonisolated public static func reason(_ e: Error, fallback: String) -> String {
        guard let a = e as? ApiError else { return fallback }
        if a.status == 0 && a.timedOut { return "The server took too long — try again." }
        if a.status == 0 { return "No connection — try again." }
        if a.status == 403 { return "Only admins can change calling settings." }
        let d = a.detail.trimmingCharacters(in: .whitespacesAndNewlines)
        return (!d.isEmpty && !ApiError.looksLikeHtml(d) && d.count <= 300) ? d : fallback
    }

    /// A restriction as Meta sends it (shape undocumented), in words.
    nonisolated public static func restrictionWords(_ e: JSONValue) -> String {
        func words(_ s: String) -> String {
            let t = s.replacingOccurrences(of: "_", with: " ").lowercased()
            return t.prefix(1).uppercased() + t.dropFirst()
        }
        switch e {
        case .object(let o):
            let parts: [String?] = [
                (o["type"] ?? o["restriction_type"] ?? o["reason"])?.content.map(words),
                (o["description"] ?? o["message"])?.content,
                (o["expiration"] ?? o["expiration_time"] ?? o["expires_at"])?.content.map { "until \($0)" },
            ]
            let joined = parts.compactMap { $0 }.joined(separator: " — ")
            return joined.isEmpty ? e.text : joined
        case .array, .null: return e.text
        default: return words(e.content ?? e.text)
        }
    }
}
