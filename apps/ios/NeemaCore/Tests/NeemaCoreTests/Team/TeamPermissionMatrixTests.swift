import Foundation
import XCTest
@testable import NeemaCore

/// Round 6 permission matrix for Team / Profile / Settings (Android
/// `PermissionMatrixTest`).
///
/// What the web does (and so what this proves):
///  - AgentsView.tsx, SettingsView.tsx and ProfileView.tsx test no permission
///    at all. page.tsx only decides whether the nav lists Team
///    (manage_agents) and Settings (manage_settings); the account menu's
///    Settings entry and ?view= links open either screen for anyone.
///  - The only gate inside Team is `role.protected` (no Edit / Delete).
///  - ProfileView lists getAgentPermissions(agent) for the signed-in agent.
///
/// What the server does: admin.py's agent routes (list / create / update /
/// delete / assign role) and roles.py's list / create check only that the
/// caller is signed in; roles.py refuses a protected role's edit / delete
/// (403); crm.py's settings PUTs refuse anyone whose DB role isn't admin
/// (or superuser) with 403 "Admin only" - manage_settings plays no part.
@MainActor
final class TeamPermissionMatrixTests: XCTestCase {
    private let salesPerms = ["view_conversations", "reply_conversations", "view_orders", "manage_orders"]
    private let sales = ("sales", "Sales", "#3b82f6")

    /// One signed-in persona: their /admin/agents row, session role, and whether crm.py treats them as admin.
    private struct Persona {
        let name: String, role: String, superuser: Bool
        var customRole: (String, String, String)? = nil
        var rolePermissions: [String]? = nil
        var customPermissions: [String]? = nil
        /// crm.py: `is_superuser or role == "admin"`.
        var serverAdmin: Bool { superuser || role == "admin" }
    }

    private lazy var superuser = Persona(name: "superuser", role: "admin", superuser: true)
    private lazy var admin = Persona(name: "admin role", role: "admin", superuser: false)
    private lazy var agent = Persona(name: "legacy agent", role: "agent", superuser: false)
    private lazy var readonly = Persona(name: "legacy readonly", role: "readonly", superuser: false)
    private lazy var salesRole = Persona(name: "custom Sales role", role: "agent", superuser: false, customRole: sales, rolePermissions: salesPerms)
    private lazy var override = Persona(name: "per-agent override", role: "agent", superuser: false, customRole: sales, rolePermissions: salesPerms,
                                        customPermissions: ["view_conversations", "manage_agents", "manage_settings"])
    private lazy var emptyOverride = Persona(name: "empty override []", role: "readonly", superuser: false, customRole: sales, rolePermissions: salesPerms,
                                             customPermissions: [])
    private lazy var all = [superuser, admin, agent, readonly, salesRole, override, emptyOverride]

    /// A signed-in persona (Android `Signed`): the fake, the host, and the call log / toasts from sign-in.
    private final class Signed {
        let fake: FakeNeema
        let host: TestHost
        var callBase = 0
        var toastBase = 0
        init(fake: FakeNeema, host: TestHost) { self.fake = fake; self.host = host }
        func mark() { callBase = fake.calls.count; toastBase = host.toasts.count }
        var since: [FakeNeema.Call] { Array(fake.calls.dropFirst(callBase)) }
        var toasts: [Toast] { Array(host.toasts.dropFirst(toastBase)) }
        var errors: [String] { toasts.filter { $0.type == .error }.map { $0.message } }
        func called(_ method: String, _ path: String) -> Bool { since.contains { $0.method == method && $0.path == path } }
        /// What page.tsx's `can()` resolves over `team` (the dashboard's list by default).
        func access(_ team: [Agent]? = nil) -> Access { ShellRules.access(agents: team ?? host.agents.value, me: host.me.value, session: host.session.value) }
        func nav(_ team: [Agent]? = nil) -> [ViewId] {
            let a = access(team)
            return ShellRules.navItems(can: { a.can($0) }, humanConvs: 0, pendingOrders: 0).map { $0.view }
        }
        /// What ProfileView's "Your Permissions" ticks: getAgentPermissions(signed-in team row).
        func profilePerms(_ team: [Agent]? = nil) -> Set<String> { access(team).permissions.filter { Perms.ALL.contains($0) } }
    }

    private var signed: [Signed] = []
    private var closers: [() -> Void] = []

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
    }

    override func tearDown() async throws {
        for c in closers { c() }
        closers = []
        for s in signed { s.host.logout() }
        signed = []
        AppClock.reset()
        try await super.tearDown()
    }

    private func rows(_ p: Persona) -> String {
        TeamFixtures.agentsWithMe(role: p.role, superuser: p.superuser, customPermissions: p.customPermissions, customRole: p.customRole, rolePermissions: p.rolePermissions)
    }

    private func fakeFor(_ p: Persona) -> FakeNeema {
        let f = Fixtures.withFixtures()
        TeamFixtures.install(f)
        TeamFixtures.settings(f, admin: p.serverAdmin)
        f.on("GET", "/admin/agents", body: rows(p))
        f.on("GET", "/admin/me", body: TeamFixtures.ormAgent(role: p.role, superuser: p.superuser))
        return f
    }

    private func signIn(_ p: Persona, fake: FakeNeema? = nil) async -> Signed {
        let f = fake ?? fakeFor(p)
        let h = TestHost(fake: f, role: p.role, superuser: p.superuser)
        _ = try? await h.refreshAgents()
        h.refetchMe()
        await drain()
        _ = await eventually(timeout: 5) { h.me.value != nil }
        let s = Signed(fake: f, host: h)
        s.mark()
        signed.append(s)
        return s
    }

    private func team(_ s: Signed) async -> TeamViewModel {
        let v = TeamViewModel(host: s.host, sleep: s.host.clock.sleeper)
        closers.append { v.close() }
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.rolesLoading }
        await drain()
        return v
    }
    private func settings(_ s: Signed) async -> SettingsViewModel {
        let v = SettingsViewModel(host: s.host, sleep: s.host.clock.sleeper)
        closers.append { v.close() }
        await settled(v)
        return v
    }
    private func profile(_ s: Signed) async -> ProfileViewModel {
        let v = ProfileViewModel(host: s.host)
        closers.append { v.close() }
        await drain()
        _ = await eventually(timeout: 5) { !v.ui.refreshing }
        await drain()
        return v
    }
    private func settled(_ v: TeamViewModel) async {
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.saving }
        await drain()
    }
    private func settled(_ v: SettingsViewModel) async {
        await drain()
        _ = await eventually(timeout: 10) { !v.busy }
        await drain()
    }
    private func settled(_ v: ProfileViewModel) async {
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.saving && !v.settingAvailable && !v.ui.refreshing }
        await drain()
    }
    /// Core batches a burst of 403s into one access re-read after a short window.
    private func settle(_ s: Signed) async { await s.host.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain() }

    // ---- Effective permissions (Profile's list, and the nav core builds from them) ----

    func testEffectivePermissionsPerPersona() async {
        let legacyAgent: Set<String> = ["view_conversations", "reply_conversations", "intercept_release", "close_conversations",
                                        "transfer_conversations", "add_notes", "view_orders", "manage_orders", "view_catalog", "view_crm", "view_leads"]
        let legacyReadonly: Set<String> = ["view_conversations", "view_orders", "view_catalog", "view_crm", "view_leads", "view_analytics"]
        let expected: [String: Set<String>] = [
            superuser.name: Set(Perms.ALL),
            admin.name: Set(Perms.ALL),
            agent.name: legacyAgent,
            readonly.name: legacyReadonly,
            salesRole.name: Set(salesPerms),
            override.name: ["view_conversations", "manage_agents", "manage_settings"],
            // custom_permissions [] is not null, so mapAgent keeps it; getAgentPermissions then
            // sees an empty list and falls back to the BASE role - not the Sales role, not nothing.
            emptyOverride.name: legacyReadonly,
        ]
        for p in all {
            let s = await signIn(p)
            XCTAssertEqual(s.profilePerms(), expected[p.name]!, p.name)
        }
    }

    func testNavListsTeamAndSettingsExactlyLikePageTsx() async {
        // page.tsx: Team with can(manage_agents); Settings with can(manage_settings); Profile always.
        let team = [superuser.name: true, admin.name: true, agent.name: false, readonly.name: false, salesRole.name: false, override.name: true, emptyOverride.name: false]
        for p in all {
            let nav = await signIn(p).nav()
            XCTAssertEqual(nav.contains(.agents), team[p.name]!, "\(p.name): Team")
            XCTAssertEqual(nav.contains(.settings), team[p.name]!, "\(p.name): Settings")
            XCTAssertTrue(nav.contains(.profile), "\(p.name): Profile")
        }
    }

    // ---- Team: no client-side gate - every persona's request reaches the server ----

    func testTeamWritesAreNeverBlockedClientSide() async {
        for p in [readonly, agent, emptyOverride] {
            let s = await signIn(p)
            let vm = await team(s)
            // The web's Roles tab loads for anyone who opens Team.
            XCTAssertFalse(vm.ui.roles.isEmpty, p.name)
            s.mark()
            let grace = s.host.agents.value.first { $0.id == Fixtures.AGENT2_ID }!
            let brian = s.host.agents.value.first { $0.id == Fixtures.AGENT3_ID }!
            vm.createAgent(name: "Jane Doe", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent") {}
            await settled(vm)
            vm.saveEdit(grace, name: "Grace W.", email: grace.email) {}
            await settled(vm)
            vm.savePassword(grace, password: "newpassword", confirm: "newpassword") {}
            await settled(vm)
            vm.toggleOnline(grace, current: grace.isAvailable)
            await drain()
            _ = await eventually(timeout: 10) { s.since.filter { $0.method == "PATCH" }.count >= 3 }
            vm.saveAssign(grace, roleId: "support", customPermissions: nil) {}
            await settled(vm)
            vm.saveRole(editing: nil, form: RoleForm(name: "Night shift", description: "", color: "#589b31", permissions: ["view_conversations"])) {}
            await settled(vm)
            vm.deleteRole(vm.ui.roles.first { $0.id == "trainee" }!) {}
            await settled(vm)
            vm.deleteAgent(brian) {}
            await settled(vm)
            let sent = s.since.filter { $0.method != "GET" }.map { "\($0.method) \($0.path)" }
            XCTAssertEqual(sent, [
                "POST /admin/agents", "PATCH /admin/agents/\(Fixtures.AGENT2_ID)", "PATCH /admin/agents/\(Fixtures.AGENT2_ID)",
                "PATCH /admin/agents/\(Fixtures.AGENT2_ID)", "PATCH /admin/agents/\(Fixtures.AGENT2_ID)/role",
                "POST /admin/roles", "DELETE /admin/roles/trainee", "DELETE /admin/agents/\(Fixtures.AGENT3_ID)",
            ], p.name)
        }
    }

    func testProtectedRoleRefusalSaysWhyAndRereadsWhoIAm() async {
        let s = await signIn(admin)
        let vm = await team(s)
        s.mark()
        // Hidden in the UI (web: !role.protected); a stale screen can still ask - the server's words come back.
        vm.saveRole(editing: vm.ui.roles.first { $0.id == "super_admin" }, form: RoleForm(name: "Super Admin", description: "x", color: "#7c3aed", permissions: [])) {}
        await settled(vm)
        XCTAssertEqual(s.toasts.last?.type, .error)
        XCTAssertEqual(s.toasts.last?.message, "Cannot modify a protected role")
        await settle(s)
        XCTAssertTrue(s.called("GET", "/admin/agents"), "a 403 re-reads the team")
        XCTAssertTrue(s.called("GET", "/admin/me"), "a 403 re-reads /me")
        XCTAssertEqual(s.host.accessRereads, 1)
    }

    // ---- Settings: loads for everyone, the server decides saves ----

    func testSettingsLoadsForEveryPersona() async {
        for p in all {
            let s = await signIn(p)
            let vm = await settings(s)
            for card in ["directives", "translation", "offer", "pipeline-stages"] {
                XCTAssertTrue(s.called("GET", "/admin/settings/\(card)"), "\(p.name) reads \(card)")
            }
            XCTAssertTrue(vm.ui.directivesLoaded, p.name)
            XCTAssertTrue(vm.ui.loadErrors.isEmpty, p.name)
        }
    }

    func testSettingsSavesSucceedOnlyForServerAdmins() async {
        for p in all {
            let s = await signIn(p)
            let vm = await settings(s)
            s.mark()
            vm.setDirectives("Push copes this week.")
            vm.saveDirectives()
            await settled(vm)
            vm.toggleTranslation()
            await settled(vm)
            vm.saveOffer(nil)
            await settled(vm)
            vm.addStage("Sampling")
            await settled(vm)
            let puts = s.since.filter { $0.method == "PUT" }.map { $0.path }
            XCTAssertEqual(puts, ["/admin/settings/directives", "/admin/settings/translation", "/admin/settings/offer", "/admin/settings/pipeline-stages"],
                           "\(p.name): every save is sent")
            if p.serverAdmin {
                XCTAssertEqual(s.errors, [], p.name)
            } else {
                // The web's own words for a refused save, card by card.
                XCTAssertEqual(s.errors, [
                    "Couldn't save (admin only)", "Couldn't change that (admin only)",
                    "Couldn't save that offer (admin only)", "Only an admin can change pipeline stages.",
                ], p.name)
                XCTAssertEqual(vm.ui.translation?.enabled, true, "\(p.name): the switch goes back")
                XCTAssertEqual(vm.ui.directives, "Push copes this week.", "\(p.name): typing is kept")
                await settle(s)
                XCTAssertTrue(s.called("GET", "/admin/agents"), "\(p.name): a 403 re-reads the team")
                XCTAssertTrue(s.called("GET", "/admin/me"), "\(p.name): a 403 re-reads /me")
            }
        }
    }

    // ---- Profile: every persona edits their own account ----

    func testProfileWritesAreOpenToEveryone() async {
        for p in all {
            let s = await signIn(p)
            let vm = await profile(s)
            s.mark()
            vm.saveProfile(name: "Moses M.", email: "moses@bethanyhouse.co.ke") {}
            await settled(vm)
            vm.changePassword(password: "newpassword", confirm: "newpassword") {}
            await settled(vm)
            vm.setAvailable(agentId: Fixtures.ME_ID, available: false)
            await settled(vm)
            let sent = s.since.filter { $0.method != "GET" }.map { "\($0.method) \($0.path)" }
            XCTAssertEqual(sent, ["PATCH /admin/me", "PATCH /admin/me", "PATCH /admin/agents/\(Fixtures.ME_ID)"], p.name)
        }
    }

    // ---- Persona 8: an admin changes my role while the app is open ----

    func testRoleChangePicksUpOnThePollAndOnA403() async throws {
        // Signed in on a custom role with manage_settings (so the nav lists Settings) but base role agent.
        let p = Persona(name: "custom manage_settings", role: "agent", superuser: false, customRole: ("ops", "Ops", "#0f766e"),
                        rolePermissions: ["view_conversations", "manage_settings"])
        let s = await signIn(p)
        XCTAssertTrue(s.access().can(Perms.MANAGE_SETTINGS))
        XCTAssertTrue(s.nav().contains(.settings))

        // An admin moves them to Sales meanwhile. Nothing changes until the app re-reads the team...
        s.fake.on("GET", "/admin/agents", body: rows(salesRole))
        XCTAssertTrue(s.access().can(Perms.MANAGE_SETTINGS))

        // ...which a 403 now triggers at once (the web waits for its 3-minute agents poll).
        let vm = await settings(s)
        s.mark()
        vm.saveDirectives()
        await settled(vm)
        XCTAssertEqual(s.toasts.last?.message, "Couldn't save (admin only)")
        await settle(s)
        XCTAssertEqual(s.host.accessRereads, 1, "the refused save re-read who this agent is")
        // The team as that re-read got it: the permissions are the Sales role's.
        let reread = try await s.host.api.agents.list()
        XCTAssertFalse(s.access(reread).can(Perms.MANAGE_SETTINGS), "the refused save corrected the permissions")
        XCTAssertFalse(s.nav(reread).contains(.settings))
        XCTAssertEqual(s.profilePerms(reread), Set(salesPerms))

        // And a promotion arrives with the next poll / refresh.
        s.fake.on("GET", "/admin/agents", body: rows(admin))
        try await s.host.refreshAgents()
        XCTAssertTrue(s.access().can(Perms.MANAGE_AGENTS))
        XCTAssertEqual(s.profilePerms(), Set(Perms.ALL))
    }
}
