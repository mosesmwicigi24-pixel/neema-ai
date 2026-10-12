import Foundation

/// The shell as the Profile screen sees it: the signed-in agent's own row and
/// the team (whose row carries the custom role), the API, the device's small
/// preferences and the toasts.
public protocol ProfileHost: AnyObject {
    /// The signed-in agent's own row (GET /admin/me), as the dashboard keeps it.
    var me: Watched<Agent?> { get }
    var agents: Watched<[Agent]> { get }
    var session: Watched<Session?> { get }
    var api: NeemaApi { get }
    /// Small device preferences: the notification switches persist here as "notif_<key>".
    var prefs: KeyValueStore { get }
    func refetchMe()
    func refetchAgents()
    /// Refetch the team and return when it has landed; throws on failure.
    func refreshAgents() async throws
    func toast(_ message: String, _ type: ToastType)
}

/// One of the web's four notification preferences (NotifSettings).
public struct NotifPref: Equatable, Sendable, Identifiable {
    public let key: String
    public let label: String
    public let desc: String
    public let def: Bool
    public var id: String { key }
    public init(_ key: String, _ label: String, _ desc: String, _ def: Bool) { self.key = key; self.label = label; self.desc = desc; self.def = def }
}

public let NOTIF_PREFS: [NotifPref] = [
    NotifPref("new_conv", "New conversations", "Alert when a new chat arrives", true),
    NotifPref("human_transfer", "Human transfers", "Alert when a conversation is transferred to you", true),
    NotifPref("order_updates", "Order updates", "Notify on order status changes", false),
    NotifPref("daily_summary", "Daily summary", "Morning digest of activity", true),
]

/// What a password change with no answer says: it can't be read back, and setting it again is harmless.
public let PASSWORD_UNCERTAIN =
    "No answer from the server, so your password may not have changed — what you typed is kept. Check your connection and tap Change Password again."

/// ProfileView.tsx's `form` and `passwordForm`. Held by the model, not the
/// screen: like the web's, they keep what was typed when Cancel folds them
/// away, and here they also outlive a rotation, a save still on the wire when
/// the phone turns, and a trip to another screen. The name/email/department
/// come back after iOS reclaims the app; the passwords are never saved anywhere.
public struct ProfileForm: Equatable, Sendable {
    /// Whose profile the form was filled from (the web re-fills it when agent.id changes).
    public var formFor: String? = nil
    public var name = ""
    public var email = ""
    /// The web shows a Department field but never sends it (PATCH /me has no such column).
    public var department = ""
    /// Never saved.
    public var password = ""
    /// Never saved.
    public var confirm = ""
    public init() {}
}

/// ProfileScreen's state, in one watched value.
public struct ProfileUi: Equatable, Sendable {
    public var form = ProfileForm()
    public var saving = false
    public var refreshing = false
    /// Why the profile couldn't be read, while there is nothing to show
    /// (signed in offline: no /me and no team row). The screen shows it with a
    /// Retry instead of "Loading profile…" forever.
    public var loadError: String? = nil
    /// nil = follow the server's value; set while an availability change is in flight.
    public var availableOverride: Bool? = nil
    /// The web keeps these in component state only. Here they persist on the
    /// device so a choice survives a restart (keys prefixed "notif_").
    public var notifs: [String: Bool] = [:]
    public init() {}
}

/// ProfileView.tsx (Android `ProfileViewModel`): edit your name/email, change
/// your password, and personal preferences. Saves go to PATCH /admin/me, then
/// /me is refetched so the shell (sidebar avatar, permissions) follows.
///
/// Every failure keeps the form open with what was typed (the forms close only
/// through `onDone`), a save with no answer is checked against the server
/// before it is called a failure, and a typed password is never shown back.
@MainActor
public final class ProfileViewModel {
    public let host: ProfileHost
    public let state = Watched<ProfileUi>(ProfileUi())
    /// Forms to fold away because their save succeeded ("edit", "password"),
    /// for whichever screen is on display — the one that started the save may
    /// have been replaced while it was on the wire.
    public let closedForms = Signal<String>(buffer: 8)
    private let team: TeamApi
    private var jobs: [UUID: Job] = [:]
    private var subs: [Subscription] = []
    private var closed = false
    /// An availability change is on the wire: a second tap waits for the first.
    public private(set) var settingAvailable = false
    public var uiAttached = false

    public init(host: ProfileHost) {
        self.host = host
        team = TeamApi(http: host.api.http)
        var s = ProfileUi()
        s.notifs = Dictionary(uniqueKeysWithValues: NOTIF_PREFS.map { ($0.key, host.prefs.bool("notif_\($0.key)", default: $0.def)) })
        state.update(s)
        if host.me.value == nil { launch { [weak self] in _ = await self?.load() } }
        subs.append(host.me.observe { [weak self] m in
            onMain { [weak self] in
                guard let self = self, !self.closed, m != nil, self.ui.loadError != nil else { return }
                self.mut { $0.loadError = nil }
            }
        })
    }

    public var ui: ProfileUi { state.value }

    private func mut(_ f: (inout ProfileUi) -> Void) {
        var s = state.value
        f(&s)
        state.update(s)
    }

    /// Change the forms' typed input.
    public func editForm(_ f: (inout ProfileForm) -> Void) { mut { f(&$0.form) } }

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

    /// Fill the form from `agent` — once per agent, as the web's `useEffect([agent?.id])`.
    public func fillForm(_ agent: Agent) {
        if ui.form.formFor == agent.id { return }
        mut { $0.form.formFor = agent.id; $0.form.name = agent.name; $0.form.email = agent.email; $0.form.department = "" }
    }

    /// Fold `form` away on whichever screen is showing (see `closedForms`).
    public func closeForm(_ form: String) { closedForms.emit(form) }

    // ── Load ─────────────────────────────────────────────────────────────────

    /// /me straight from the server (so its failure is known), then the shell's copy and the team row.
    private func load() async -> Error? {
        var failed: Error? = nil
        do { _ = try await host.api.profile.me() } catch { failed = error }
        if closed { return failed }
        if let e = failed {
            if host.me.value == nil {
                mut { $0.loadError = FriendlyErrors.text(of: e, fallback: "The server couldn't send your profile just now.") }
            }
        } else {
            mut { $0.loadError = nil }
            host.refetchMe()
        }
        await quietly { try await self.host.refreshAgents() }
        return failed
    }

    public func toggleNotif(_ key: String) {
        let next = !(ui.notifs[key] ?? false)
        mut { $0.notifs[key] = next }
        host.prefs.set(next, for: "notif_\(key)")
    }

    /// Pull-to-refresh and the Retry button: the spinner lasts until /me and the team row have landed.
    public func refresh() {
        if ui.refreshing { return }
        mut { $0.refreshing = true }
        launch { [weak self] in
            guard let self = self else { return }
            let failed = await self.load()
            if self.closed { return }
            if let e = failed, self.host.me.value != nil {
                self.host.toast("Couldn't refresh your profile. \(FriendlyErrors.text(of: e))", .error)
            }
            self.mut { $0.refreshing = false }
        }
    }

    // ── Saves ────────────────────────────────────────────────────────────────

    /// Runs `write` under the saving flag; a second tap while it is on the wire does nothing.
    private func save(
        failText: @escaping @MainActor (Error) -> String,
        uncertain: String,
        verify: (@MainActor () async throws -> Bool)?,
        write: @escaping @MainActor () async throws -> Void,
        done: @escaping @MainActor () async -> Void
    ) {
        if ui.saving { return }
        mut { $0.saving = true }
        launch { [weak self] in
            guard let self = self else { return }
            defer { if !self.closed { self.mut { $0.saving = false } } }
            do {
                try await write()
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                let lost = FriendlyErrors.mayHaveApplied(error)
                if lost, let v = verify, (try? await v()) == true {
                    if self.closed { return }
                    await done()
                    return
                }
                if self.closed { return }
                self.host.toast(lost ? uncertain : failText(error), .error)
                return
            }
            if self.closed { return }
            await done()
        }
    }

    public func saveProfile(name: String, email: String, onDone: @escaping () -> Void) {
        let trimmedName = name.trimmingCharacters(in: .whitespaces)
        let trimmedEmail = email.trimmingCharacters(in: .whitespaces)
        if trimmedName.isEmpty || trimmedEmail.isEmpty { return host.toast("Name and email required", .error) }
        // agents.email is UNIQUE and PATCH /admin/me turns a clash into a bare 500.
        let myId = host.me.value?.id ?? host.session.value?.agentId
        if host.agents.value.contains(where: { $0.id != myId && $0.email.trimmingCharacters(in: .whitespaces).caseInsensitiveCompare(trimmedEmail) == .orderedSame }) {
            return host.toast("Another agent already uses that email", .error)
        }
        save(
            failText: { [weak self] e in self?.failText(e, "Failed to update profile — that email may already be in use") ?? "" },
            uncertain: UNCERTAIN_SAVE,
            // No answer: if /me now reads what was typed, the save went through.
            verify: { [weak self] in
                guard let self = self else { return false }
                let m = try await self.host.api.profile.me()
                return m.name == trimmedName && m.email.caseInsensitiveCompare(trimmedEmail) == .orderedSame
            },
            write: { [weak self] in
                guard let self = self else { return }
                _ = try await self.host.api.profile.update(name: trimmedName, email: trimmedEmail)
            },
            done: { [weak self] in
                guard let self = self else { return }
                self.host.refetchMe()
                self.host.refetchAgents()
                onDone()
                self.host.toast("Profile updated", .success)
            }
        )
    }

    public func changePassword(password: String, confirm: String, onDone: @escaping () -> Void) {
        if password != confirm { return host.toast("Passwords don't match", .error) }
        if password.count < 8 { return host.toast("Password must be at least 8 characters", .error) }
        save(
            // Whatever the server said, the password itself never appears in it.
            failText: { [weak self] e in
                FriendlyErrors.masking(self?.failText(e, "Failed to change password") ?? "Failed to change password", secret: password)
            },
            uncertain: PASSWORD_UNCERTAIN,
            verify: nil,
            write: { [weak self] in
                guard let self = self else { return }
                _ = try await self.host.api.profile.update(password: password)
            },
            done: { [weak self] in
                guard let self = self else { return }
                // The web empties passwordForm once the change has gone through.
                self.mut { $0.form.password = ""; $0.form.confirm = "" }
                onDone()
                self.host.toast("Password changed successfully", .success)
            }
        )
    }

    /// The server's words, except a 5xx: update_me has no error handling, so a
    /// refused write comes back as a bare "Internal Server Error".
    private func failText(_ e: Error, _ serverError: String) -> String {
        switch FriendlyErrors.httpStatus(e) {
        case 409: return "Another agent already uses that email"
        case 429: return FriendlyErrors.BUSY_TEXT
        case 500, 501: return serverError
        default: return FriendlyErrors.text(of: e, fallback: serverError)
        }
    }

    // ── Availability ─────────────────────────────────────────────────────────

    /// Online / away for the signed-in agent — the same flag the Team screen toggles.
    public func setAvailable(agentId: String, available: Bool) {
        if settingAvailable { return }
        settingAvailable = true
        mut { $0.availableOverride = available }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.settingAvailable = false }
            do {
                _ = try await self.team.setAvailable(id: agentId, available: available)
                if self.closed { return }
                self.host.refetchMe()
                self.host.refetchAgents()
                self.host.toast(available ? "You're available" : "You're away", .success)
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                self.mut { $0.availableOverride = nil }
                if FriendlyErrors.mayHaveApplied(error) {
                    // It may have flipped: show what the server has instead of guessing.
                    let truth = try? await self.host.api.profile.me().isAvailable
                    if self.closed { return }
                    self.host.refetchMe()
                    if truth != available {
                        self.host.toast("Couldn't reach the server — availability unchanged", .error)
                    } else {
                        self.host.toast(available ? "You're available" : "You're away", .success)
                    }
                } else {
                    self.host.toast(availabilityFailure(error), .error)
                }
            }
        }
    }

    /// Drop the optimistic value once /me agrees.
    public func reconcile(_ serverValue: Bool?) {
        if let o = ui.availableOverride, o == serverValue { mut { $0.availableOverride = nil } }
    }

    // ── The app reclaimed: the typed name, email and department come back ────

    /// nil until the form has been filled (there is nothing to keep before that).
    public func saveUi() -> String? {
        guard let id = ui.form.formFor else { return nil }
        return JSONValue.object([
            "for": .string(id), "name": .string(ui.form.name), "email": .string(ui.form.email), "department": .string(ui.form.department),
        ]).text
    }

    public func restoreUi(_ saved: String) {
        guard let o = JSONValue.parse(saved)?.objectValue, let id = o["for"]?.stringValue else { return }
        mut {
            $0.form.formFor = id
            $0.form.name = o["name"]?.stringValue ?? ""
            $0.form.email = o["email"]?.stringValue ?? ""
            $0.form.department = o["department"]?.stringValue ?? ""
        }
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
        subs.forEach { $0.cancel() }
        subs = []
        for j in jobs.values { j.cancel() }
        jobs = [:]
    }
}
