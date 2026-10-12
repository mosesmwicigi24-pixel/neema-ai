import Foundation

/// The shell as the Team screen sees it: the dashboard's team list and the
/// signed-in agent, the API and the toasts.
public protocol TeamHost: AnyObject {
    var foreground: Watched<Bool> { get }
    var agents: Watched<[Agent]> { get }
    /// The signed-in agent's own row (GET /admin/me), as the dashboard keeps it.
    var me: Watched<Agent?> { get }
    var session: Watched<Session?> { get }
    var api: NeemaApi { get }
    /// Refetch the team and return when it has landed; throws on failure.
    func refreshAgents() async throws
    /// Refetch in the background; a failure keeps what is on screen.
    func refetchAgents()
    func refetchMe()
    func toast(_ message: String, _ type: ToastType)
}

/// AgentsView's state, in one watched value.
public struct TeamUi: Equatable, Sendable {
    public var roles: [CustomRole] = []
    public var rolesLoading = true
    /// Why the roles couldn't be read; the Roles tab shows it (with Retry) rather than "No roles yet".
    public var rolesError: String? = nil
    /// Why the team couldn't be read when this screen asked; shown instead of "No agents yet." while the list is empty.
    public var agentsError: String? = nil
    public var saving = false
    public var refreshing = false
    /// Availability flips the moment the switch is touched; the refetched
    /// list confirms it. Cleared per agent once the server answers.
    public var availability: [String: Bool] = [:]
    /// The dialogs' typed input: outlives a rotation and a restart, passwords excepted.
    public var forms = TeamForms()
    public init() {}
}

/// Team management (AgentsView.tsx; Android `AgentsViewModel`): agents come
/// from the dashboard's shared list; custom roles are loaded here. Every
/// write refetches whatever it changed, like the web, and reports through the
/// dashboard's toasts. Dialog callbacks (`onDone`) fire only on success so a
/// failed save keeps the form open with what was typed.
///
/// On a phone network three failures get more than a toast:
/// - No answer (a timeout, a dropped connection): the write may have landed,
///   so the truth is re-read, and if it shows the change the save counts as
///   done; otherwise the form stays open, input intact, and says so.
/// - 404: someone else deleted the agent or role — the list is re-read (the
///   row disappears) and the toast says who is gone.
/// - A cancelled write (signing out mid-save) says nothing at all.
@MainActor
public final class TeamViewModel {
    public let host: TeamHost
    public let state = Watched<TeamUi>(TeamUi())
    /// Dialogs to close because their save succeeded ("create", "edit", "pw",
    /// "del", "assign", "role", "delrole"). A save outlives the screen that
    /// started it, so its success is announced here and the screen on display
    /// then closes the dialog.
    public let closedDialogs = Signal<String>(buffer: 8)
    /// The team (availability, last seen, active chats) is the dashboard's
    /// 3-minute poll, which pauses in the background and refetches on return;
    /// nothing on the socket announces presence. AgentsView reads its roles on
    /// mount. Each return to this screen re-reads both, so the list is never
    /// older than the moment it was opened.
    public private(set) var life: ScreenLife!
    private let team: TeamApi
    private var jobs: [UUID: Job] = [:]
    private var subs: [Subscription] = []
    private var closed = false
    public var uiAttached = false
    /// Agents whose availability change is on the wire: a second tap waits for the first.
    private var toggling: Set<String> = []

    public init(host: TeamHost, sleep: @escaping Sleeper = realSleep) {
        self.host = host
        team = TeamApi(http: host.api.http)
        life = ScreenLife(foreground: host.foreground, catchUpOnForeground: false, sleep: sleep, catchUp: { [weak self] in
            guard let self = self else { return }
            async let a: Error? = self.loadAgents()
            async let r: Void = self.rereadRolesQuietly()
            _ = await (a, r)
        })
        launch { [weak self] in await self?.fetchRoles() }
        // The sign-in read of the team failed (offline at start): ask now rather than wait 3 minutes.
        if host.agents.value.isEmpty { launch { [weak self] in _ = await self?.loadAgents() } }
        subs.append(host.agents.observe { [weak self] list in
            onMain { [weak self] in
                guard let self = self, !self.closed else { return }
                if !list.isEmpty { self.mut { $0.agentsError = nil } }
                self.reconcile(list)
            }
        })
    }

    public var ui: TeamUi { state.value }

    private func mut(_ f: (inout TeamUi) -> Void) {
        var s = state.value
        f(&s)
        state.update(s)
    }

    /// Change the dialogs' typed input.
    public func editForms(_ f: (inout TeamForms) -> Void) { mut { f(&$0.forms) } }

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

    /// Close `dialog` on whichever screen is showing (see `closedDialogs`).
    public func closeDialog(_ dialog: String) { closedDialogs.emit(dialog) }

    // ── Loads ────────────────────────────────────────────────────────────────

    private func loadAgents() async -> Error? {
        do {
            try await host.refreshAgents()
            if !closed { mut { $0.agentsError = nil } }
            return nil
        } catch {
            if closed || SalesErrors.isCancellation(error) { return nil }
            mut { $0.agentsError = FriendlyErrors.text(of: error, fallback: "The server couldn't send the team just now.") }
            return error
        }
    }

    /// A quiet re-read of the roles (a return to the screen): a failure keeps what is on screen.
    private func rereadRolesQuietly() async {
        if let roles = try? await host.api.roles.list(), !closed { mut { $0.roles = roles; $0.rolesError = nil } }
    }

    private func fetchRoles() async {
        mut { $0.rolesLoading = true }
        do {
            let roles = try await host.api.roles.list()
            if closed { return }
            mut { $0.roles = roles; $0.rolesError = nil }
        } catch {
            if closed || SalesErrors.isCancellation(error) { return }
            mut { $0.rolesError = FriendlyErrors.text(of: error, fallback: "The server couldn't send the roles just now.") }
            host.toast("Failed to load roles", .error)
        }
        if !closed { mut { $0.rolesLoading = false } }
    }

    /// Pull-to-refresh (and the Retry buttons): the spinner lasts until the team and the roles have both landed.
    public func refresh() {
        if ui.refreshing { return }
        mut { $0.refreshing = true }
        launch { [weak self] in
            guard let self = self else { return }
            async let a: Error? = self.loadAgents()
            async let r: Void = self.fetchRoles()
            let failed = await a
            _ = await r
            if self.closed { return }
            self.mut { $0.refreshing = false }
            // Agents on screen stay; the pull says it couldn't reach the server.
            if let e = failed, !self.host.agents.value.isEmpty {
                self.host.toast("Couldn't refresh the team. \(FriendlyErrors.text(of: e))", .error)
            }
        }
    }

    // ── One write at a time ──────────────────────────────────────────────────

    /// One write under the shared saving flag (a second tap while it is in
    /// flight does nothing). `write` is the request; `done` the success path
    /// (refetch, close the dialog, toast).
    ///
    /// - A timeout or dropped connection runs `verify` (a fresh read); true
    ///   means the write landed after all, so `done` runs.
    /// - A 404 goes to `onGone`, which answers whether it dealt with it.
    /// - Otherwise `fallbackError` replaces the server's words entirely (the
    ///   web's fixed "Failed to remove"); `serverError` is what a 5xx says
    ///   instead of the bare "Internal Server Error" the API sends when the
    ///   database refuses a write (admin.py has no handler for IntegrityError).
    /// - `secret` (a typed password) is masked out of anything shown.
    private func save(
        fallbackError: String? = nil,
        serverError: String = "Something went wrong — please try again",
        secret: String = "",
        verify: (@MainActor () async throws -> Bool)? = nil,
        onGone: (@MainActor (ApiError) async -> Bool)? = nil,
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
                if FriendlyErrors.mayHaveApplied(error) {
                    if let v = verify, (try? await v()) == true {
                        if self.closed { return }
                        await done()
                        return
                    }
                    if self.closed { return }
                    self.host.toast(UNCERTAIN_SAVE, .error)
                    return
                }
                if let api = error as? ApiError, api.status == 404, let g = onGone, await g(api) { return }
                if self.closed { return }
                // The web's fixed words are for a refusal, not for "you're offline" or "sign in again".
                let status = FriendlyErrors.httpStatus(error)
                let fixed = (status == 0 || status == 401) ? nil : fallbackError
                self.host.toast(FriendlyErrors.masking(fixed ?? self.failText(error, serverError), secret: secret), .error)
                return
            }
            if self.closed { return }
            await done()
        }
    }

    private func failText(_ e: Error, _ serverError: String) -> String {
        guard let status = FriendlyErrors.httpStatus(e) else { return FriendlyErrors.text(of: e, fallback: serverError) }
        switch status {
        case 409: return "An agent with that email already exists"
        case 429: return FriendlyErrors.BUSY_TEXT
        case 500, 501: return serverError
        default: return FriendlyErrors.text(of: e, fallback: serverError)
        }
    }

    /// agents.email is UNIQUE and the API turns a clash into an unhandled 500,
    /// so a duplicate is caught here, against the list already on screen.
    private func emailTaken(_ email: String, exceptId: String? = nil) -> Bool {
        let wanted = email.trimmingCharacters(in: .whitespaces)
        return host.agents.value.contains { $0.id != exceptId && $0.email.trimmingCharacters(in: .whitespaces).caseInsensitiveCompare(wanted) == .orderedSame }
    }

    /// The team as the server has it now (the dashboard's list follows).
    private func freshAgents() async throws -> [Agent] {
        try await host.refreshAgents()
        return host.agents.value
    }

    /// A 404 on `agent`: someone else removed them. The list is re-read so their card goes, and the dialog with it.
    private func agentGone(_ agent: Agent, onDone: @escaping () -> Void) -> @MainActor (ApiError) async -> Bool {
        { [weak self] e in
            guard let self = self else { return false }
            if e.detail.range(of: "Role not found", options: .caseInsensitive) != nil { return false }
            await quietly { try await self.host.refreshAgents() }
            if self.closed { return true }
            onDone()
            self.host.toast("\(agent.name.isEmpty ? "This agent" : agent.name) was removed by someone else", .error)
            return true
        }
    }

    // ── Agent CRUD ───────────────────────────────────────────────────────────

    public func createAgent(name: String, email: String, password: String, roleId: String, onDone: @escaping () -> Void) {
        let trimmedName = name.trimmingCharacters(in: .whitespaces)
        let trimmedEmail = email.trimmingCharacters(in: .whitespaces)
        if trimmedName.isEmpty || trimmedEmail.isEmpty || password.isEmpty {
            return host.toast("Name, email and password are required", .error)
        }
        if password.count < 8 { return host.toast("Password must be ≥8 characters", .error) }
        if emailTaken(email) { return host.toast("An agent with that email already exists", .error) }
        save(
            serverError: "Couldn't create the agent — that email may already be in use",
            secret: password,
            // No answer: if the address is on the team now, the create went through.
            verify: { [weak self] in
                guard let self = self else { return false }
                return try await self.freshAgents().contains { $0.email.trimmingCharacters(in: .whitespaces).caseInsensitiveCompare(trimmedEmail) == .orderedSame }
            },
            write: { [weak self] in
                guard let self = self else { return }
                _ = try await self.host.api.agents.create(name: trimmedName, email: trimmedEmail, password: password, role: toDbRole(roleId))
            },
            done: { [weak self] in
                guard let self = self else { return }
                self.host.refetchAgents()
                // The web clears createForm only once an agent is made.
                self.mut { $0.forms.resetCreate() }
                onDone()
                self.host.toast("Agent created", .success)
            }
        )
    }

    public func saveEdit(_ agent: Agent, name: String, email: String, onDone: @escaping () -> Void) {
        let trimmedName = name.trimmingCharacters(in: .whitespaces)
        let trimmedEmail = email.trimmingCharacters(in: .whitespaces)
        if trimmedName.isEmpty || trimmedEmail.isEmpty { return host.toast("Name and email required", .error) }
        if emailTaken(email, exceptId: agent.id) { return host.toast("An agent with that email already exists", .error) }
        save(
            serverError: "Couldn't update the agent — that email may already be in use",
            verify: { [weak self] in
                guard let self = self, let now = try await self.freshAgents().first(where: { $0.id == agent.id }) else { return false }
                return now.name == trimmedName && now.email.caseInsensitiveCompare(trimmedEmail) == .orderedSame
            },
            onGone: agentGone(agent, onDone: onDone),
            write: { [weak self] in
                guard let self = self else { return }
                _ = try await self.team.updateAgent(id: agent.id, body: .object(["name": .string(trimmedName), "email": .string(trimmedEmail)]))
            },
            done: { [weak self] in
                guard let self = self else { return }
                self.host.refetchAgents()
                onDone()
                self.host.toast("Agent updated", .success)
            }
        )
    }

    /// No `verify`: a password can't be read back. Setting the same one again
    /// is harmless, so a save with no answer keeps both fields for another go.
    public func savePassword(_ agent: Agent, password: String, confirm: String, onDone: @escaping () -> Void) {
        if password.count < 8 { return host.toast("Password must be ≥8 characters", .error) }
        if password != confirm { return host.toast("Passwords do not match", .error) }
        save(
            secret: password,
            onGone: agentGone(agent, onDone: onDone),
            write: { [weak self] in
                guard let self = self else { return }
                _ = try await self.team.updateAgent(id: agent.id, body: .object(["password": .string(password)]))
            },
            done: { [weak self] in
                guard let self = self else { return }
                self.mut { $0.forms.openPassword() }
                onDone()
                self.host.toast("Password updated", .success)
            }
        )
    }

    /// Why `agent` can't be removed from here, or nil when it can. The API
    /// deletes any row it is asked to — including the caller's own, after which
    /// every request answers 404 "Agent not found" (not 401), so the app could
    /// neither work nor sign out — and the last admin, which leaves nobody
    /// able to manage the team.
    public func removalBlocker(_ agent: Agent) -> String? {
        let meId = host.me.value?.id ?? host.session.value?.agentId
        if agent.id == meId { return "You can't remove your own account — ask another admin" }
        let isAdmin: (Agent) -> Bool = { $0.role == "admin" || $0.isSuperuser }
        if isAdmin(agent) && host.agents.value.filter(isAdmin).count <= 1 { return "You can't remove the last admin" }
        return nil
    }

    /// The trash button: true opens the confirmation; false has already said why not.
    public func requestRemove(_ agent: Agent) -> Bool {
        guard let why = removalBlocker(agent) else { return true }
        host.toast(why, .error)
        return false
    }

    public func deleteAgent(_ agent: Agent, onDone: @escaping () -> Void) {
        if let why = removalBlocker(agent) { return host.toast(why, .error) }
        save(
            fallbackError: "Failed to remove",
            // No answer: gone from the team means the delete went through.
            verify: { [weak self] in
                guard let self = self else { return false }
                return try await !self.freshAgents().contains { $0.id == agent.id }
            },
            // Someone else removed them first: what was asked for is done.
            onGone: { [weak self] _ in
                guard let self = self else { return false }
                await quietly { try await self.host.refreshAgents() }
                if self.closed { return true }
                onDone()
                self.host.toast("\(agent.name.isEmpty ? "This agent" : agent.name) was already removed", .success)
                return true
            },
            write: { [weak self] in
                guard let self = self else { return }
                _ = try await self.host.api.agents.delete(id: agent.id)
            },
            done: { [weak self] in
                guard let self = self else { return }
                self.host.refetchAgents()
                onDone()
                self.host.toast("Agent removed", .success)
            }
        )
    }

    public func toggleOnline(_ agent: Agent, current: Bool) {
        if toggling.contains(agent.id) { return }
        let next = !current
        toggling.insert(agent.id)
        mut { $0.availability[agent.id] = next }
        launch { [weak self] in
            guard let self = self else { return }
            defer { self.toggling.remove(agent.id) }
            do {
                _ = try await self.team.setAvailable(id: agent.id, available: next)
                if self.closed { return }
                self.host.refetchAgents()
                // The dashboard also polls /me; keep the signed-in agent's own row in step.
                if agent.id == self.host.me.value?.id { self.host.refetchMe() }
            } catch {
                if self.closed || SalesErrors.isCancellation(error) { return }
                if FriendlyErrors.mayHaveApplied(error) {
                    // It may have flipped: show the server's value rather than guess.
                    let truth = try? await self.freshAgents().first { $0.id == agent.id }?.isAvailable
                    if self.closed { return }
                    self.mut { $0.availability[agent.id] = nil }
                    if truth != next { self.host.toast("Couldn't reach the server — availability unchanged", .error) }
                } else if let api = error as? ApiError, api.status == 404 {
                    self.mut { $0.availability[agent.id] = nil }
                    _ = await self.agentGone(agent, onDone: {})(api)
                } else {
                    self.mut { $0.availability[agent.id] = nil }
                    self.host.toast(availabilityFailure(error), .error)
                }
            }
        }
    }

    /// Drop optimistic values the refetched list now agrees with.
    public func reconcile(_ agents: [Agent]) {
        let cur = ui.availability
        if cur.isEmpty { return }
        let kept = cur.filter { id, v in agents.first { $0.id == id }?.isAvailable != v }
        if kept != cur { mut { $0.availability = kept } }
    }

    // ── Role assignment ──────────────────────────────────────────────────────

    /// `customPermissions` non-nil gives this one agent their own permission
    /// set on top of the role (agents.custom_permissions); nil clears it.
    public func saveAssign(_ agent: Agent, roleId: String, customPermissions: [String]?, onDone: @escaping () -> Void) {
        if roleId.isEmpty { return host.toast("Please select a role", .error) }
        let gone = agentGone(agent, onDone: onDone)
        save(
            verify: { [weak self] in
                guard let self = self, let now = try await self.freshAgents().first(where: { $0.id == agent.id }) else { return false }
                return now.customRoleId == roleId && now.customPermissions == customPermissions
            },
            onGone: { [weak self] e in
                guard let self = self else { return false }
                if e.detail.range(of: "Role not found", options: .caseInsensitive) != nil {
                    // The role went, not the agent: re-read the roles and let them pick another.
                    await self.rereadRolesQuietly()
                    if self.closed { return true }
                    self.host.toast("That role was deleted by someone else — pick another", .error)
                    return true
                }
                return await gone(e)
            },
            write: { [weak self] in
                guard let self = self else { return }
                _ = try await self.team.assignRole(agentId: agent.id, roleId: roleId, customPermissions: customPermissions)
            },
            done: { [weak self] in
                guard let self = self else { return }
                self.host.refetchAgents()
                if agent.id == self.host.me.value?.id { self.host.refetchMe() }
                onDone()
                self.host.toast("Role assigned", .success)
            }
        )
    }

    // ── Role CRUD ────────────────────────────────────────────────────────────

    /// The roles as the server has them now.
    private func freshRoles() async throws -> [CustomRole] {
        let roles = try await host.api.roles.list()
        if !closed { mut { $0.roles = roles } }
        return roles
    }

    /// `editing` nil = create a new role.
    public func saveRole(editing: CustomRole?, form: RoleForm, onDone: @escaping () -> Void) {
        if form.name.trimmingCharacters(in: .whitespaces).isEmpty { return host.toast("Role name required", .error) }
        let newId = form.id ?? "role_\(AppClock.now())"
        let id = editing?.id ?? newId
        save(
            verify: { [weak self] in
                guard let self = self, let now = try await self.freshRoles().first(where: { $0.id == id }) else { return false }
                return now.name == form.name && now.description == form.description &&
                    now.color.caseInsensitiveCompare(form.color) == .orderedSame && Set(now.permissions) == Set(form.permissions)
            },
            onGone: { [weak self] _ in
                guard let self = self else { return false }
                await quietly { _ = try await self.freshRoles() }
                if self.closed { return true }
                onDone()
                self.host.toast("That role was deleted by someone else", .error)
                return true
            },
            write: { [weak self] in
                guard let self = self else { return }
                if let e = editing {
                    _ = try await self.host.api.roles.update(id: e.id, body: .object([
                        "name": .string(form.name), "description": .string(form.description), "color": .string(form.color),
                        "permissions": .array(form.permissions.map { .string($0) }),
                    ]))
                } else {
                    _ = try await self.host.api.roles.create(id: newId, name: form.name, description: form.description, color: form.color, permissions: form.permissions)
                }
            },
            done: { [weak self] in
                guard let self = self else { return }
                self.host.toast(editing == nil ? "Role created" : "Role updated", .success)
                await self.fetchRoles()
                if self.closed { return }
                // Agents on this role carry its permissions in their rows.
                self.host.refetchAgents()
                onDone()
            }
        )
    }

    public func deleteRole(_ role: CustomRole, onDone: @escaping () -> Void) {
        save(
            verify: { [weak self] in
                guard let self = self else { return false }
                return try await !self.freshRoles().contains { $0.id == role.id }
            },
            // Someone else deleted it first: what was asked for is done.
            onGone: { [weak self] _ in
                guard let self = self else { return false }
                await quietly { _ = try await self.freshRoles() }
                if self.closed { return true }
                self.host.refetchAgents()
                onDone()
                self.host.toast("That role was already deleted", .success)
                return true
            },
            write: { [weak self] in
                guard let self = self else { return }
                _ = try await self.host.api.roles.delete(id: role.id)
            },
            done: { [weak self] in
                guard let self = self else { return }
                await self.fetchRoles()
                if self.closed { return }
                self.host.refetchAgents()
                onDone()
                self.host.toast("Role deleted", .success)
            }
        )
    }

    // ── The app reclaimed: the dialogs' typed input comes back ───────────────

    public func saveUi() -> String { ui.forms.save() }

    public func restoreUi(_ saved: String) { mut { $0.forms.restore(saved) } }

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
        for j in jobs.values { j.cancel() }
        jobs = [:]
    }
}
