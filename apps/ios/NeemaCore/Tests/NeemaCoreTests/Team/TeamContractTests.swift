import Foundation
import XCTest
@testable import NeemaCore

/// The Team screen and /me against the API's real contract (admin.py agents +
/// me, roles.py): exact requests, the shapes the handlers really return, and
/// each error they raise (Android `TeamContractTest`; the rows its
/// `TeamViewModelTests` and `TeamNetworkTests` already prove are left out).
/// TeamFixtures re-implements every handler's checks.
final class TeamContractTests: TeamTestCase {
    /// page.tsx `can()` over the dashboard's lists.
    private func access() -> Access { ShellRules.access(agents: host.agents.value, me: host.me.value, session: host.session.value) }

    // ---- GET /admin/agents (list_agents) ----

    func testListDecodesTheJoinedRows() {
        let list = host.agents.value
        XCTAssertEqual(list.map { $0.name }, ["Brian Otieno", "Grace Wanjiru", "Moses Mwicigi", "Wanjiku Kamau-Ochieng Nyambura"], "ORDER BY name")
        let grace = agent(Fixtures.AGENT2_ID)
        XCTAssertEqual(grace.customRoleId, "sales")
        XCTAssertEqual(grace.roleName, "Sales")
        XCTAssertEqual(grace.roleColor, "#3b82f6")
        XCTAssertNil(grace.customPermissions)
        XCTAssertEqual(grace.permissions, grace.rolePermissions, "no override: the role's permissions")
        let wanjiku = agent(TeamFixtures.AGENT4_ID)
        XCTAssertEqual(wanjiku.permissions, ["view_conversations", "reply_conversations", "add_notes"], "an override wins over the role")
        XCTAssertNil(wanjiku.lastSeenAt)
        let brian = agent(Fixtures.AGENT3_ID)
        XCTAssertNil(brian.customRoleId)
        XCTAssertTrue(brian.permissions.isEmpty)
        // Python isoformat: "+00:00", with microseconds only when they are not zero.
        let created = grace.createdAt ?? ""
        XCTAssertNotNil(created.range(of: #"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{6})?\+00:00$"#, options: .regularExpression), created)
        XCTAssertNotNil(Fmt.millis(grace.createdAt))
        XCTAssertTrue(Fmt.timeAgo(grace.lastSeenAt).hasSuffix("ago"))
    }

    func testListToleratesMissingAndNullKeys() async throws {
        // A row from before the custom-role migration: no role_* / custom_* keys, active_convs null.
        fake.on("GET", "/admin/agents", body: """
            [{"id":"x1","name":"Old Row","email":"old@b.co","role":"agent","is_available":null,
            "is_superuser":false,"avatar_url":null,"created_at":"2025-01-01T08:00:00+00:00","last_seen_at":null,"active_convs":null}]
            """)
        try await host.refreshAgents()
        XCTAssertEqual(host.agents.value.count, 1)
        let a = host.agents.value[0]
        XCTAssertEqual(a.name, "Old Row")
        XCTAssertFalse(a.isAvailable)
        XCTAssertEqual(a.activeConvs, 0)
        XCTAssertTrue(a.permissions.isEmpty)
    }

    // ---- GET /admin/me (get_me: the bare ORM row) ----

    func testMeIsTheBareOrmRowAndPermissionsComeFromTheTeamList() async {
        let me = host.me.value!
        XCTAssertEqual(me.id, Fixtures.ME_ID)
        XCTAssertEqual(me.role, "admin")
        XCTAssertTrue(me.isSuperuser)
        XCTAssertNil(me.customRoleId, "get_me has no custom-role columns")
        XCTAssertNil(me.rolePermissions)
        // An agent whose power comes from a custom role keeps it although /me omits it.
        fake.on("GET", "/admin/me", body: TeamFixtures.ormAgent(id: TeamFixtures.AGENT4_ID, name: "Wanjiku", email: "wanjiku.kamau-ochieng.nyambura@bethanyhouse.co.ke",
                                                                 role: "agent", superuser: false))
        host.refetchMe()
        _ = await eventually(timeout: 5) { self.host.me.value?.id == TeamFixtures.AGENT4_ID }
        XCTAssertEqual(host.me.value?.id, TeamFixtures.AGENT4_ID)
        XCTAssertTrue(access().can(Perms.ADD_NOTES))
    }

    // ---- POST /admin/agents (create_agent) ----

    func testCreateSendsExactlyTheWebsBodyAndAcceptsTheOrmRow() async {
        let vm = await vm()
        vm.createAgent(name: "Jane Doe", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "viewer", onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "POST"); XCTAssertEqual(w.first?.path, "/admin/agents")
        XCTAssertNil(w.first?.query)
        XCTAssertEqual(json(w[0]), el(#"{"name":"Jane Doe","email":"jane@bethanyhouse.co.ke","password":"s3cretpass","role":"readonly"}"#))
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Agent created")
    }

    func testATakenEmailIsCaughtBeforeTheServer500s() async {
        let vm = await vm()
        vm.createAgent(name: "Grace Again", email: " GRACE@bethanyhouse.co.ke ", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(lastToast()?.message, "An agent with that email already exists")
        XCTAssertEqual(done, 0)
    }

    func testAServer500SaysWhatUsuallyCausesIt() async {
        let vm = await vm()
        // Someone else took the email since the list loaded: agents.email UNIQUE -> unhandled IntegrityError.
        fake.on("POST", "/admin/agents", code: 500, body: TeamFixtures.SERVER_ERROR)
        vm.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Couldn't create the agent — that email may already be in use")
        XCTAssertEqual(done, 0)
        // A 409 (a proxy or a future handler) reads the same way.
        status("POST", "/admin/agents", 409, "Email already registered")
        vm.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "An agent with that email already exists")
    }

    // ---- PATCH /admin/agents/{id} (update_agent -> {"ok": true}) ----

    func testEditRefusesAnotherAgentsEmail() async {
        let vm = await vm()
        vm.saveEdit(agent(Fixtures.AGENT3_ID), name: "Brian", email: "grace@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(lastToast()?.message, "An agent with that email already exists")
        // Keeping your own email is fine.
        vm.saveEdit(agent(Fixtures.AGENT3_ID), name: "Brian O.", email: "brian@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0]), el(#"{"name":"Brian O.","email":"brian@bethanyhouse.co.ke"}"#))
        XCTAssertEqual(done, 1)
    }

    /// Someone else removed them: the list is re-read, the dialog closes, and the toast names who is gone.
    func testEditOfAnAgentSomeoneElseRemovedSaysSo() async {
        let vm = await vm()
        status("PATCH", "/admin/agents/[^/]+", 404, "Agent not found")
        vm.savePassword(agent(Fixtures.AGENT3_ID), password: "n3wpassword", confirm: "n3wpassword", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Brian Otieno was removed by someone else")
        XCTAssertEqual(done, 1)
        XCTAssertTrue(called("GET", "/admin/agents"))
    }

    // ---- PATCH /admin/agents/{id}/role (assign_agent_role) ----

    func testAnEmptyOverrideIsSentAsAnEmptyList() async {
        let vm = await vm()
        // [] is a real override (no permissions at all); only null means "use the role's".
        vm.saveAssign(agent(TeamFixtures.AGENT4_ID), roleId: "support", customPermissions: [], onDone: onDone)
        await settled(vm)
        XCTAssertEqual(writes().count, 1)
        XCTAssertEqual(json(writes()[0]), el(#"{"custom_role_id":"support","custom_permissions":[]}"#))
        XCTAssertEqual(done, 1)
    }

    /// The role went, not the agent: roles are re-read and the dialog stays open to pick another.
    func testAssigningARoleSomeoneJustDeletedSaysSo() async {
        let vm = await vm()
        vm.saveAssign(agent(Fixtures.AGENT3_ID), roleId: "role_gone", customPermissions: nil, onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "That role was deleted by someone else — pick another")
        XCTAssertEqual(done, 0)
        XCTAssertTrue(called("GET", "/admin/roles"))
    }

    // ---- /admin/roles ----

    func testRolesDecodeWithTheirTimestamps() async {
        let vm = await vm()
        let r = vm.ui.roles.first { $0.id == "super_admin" }!
        XCTAssertTrue(r.isProtected)
        XCTAssertEqual(r.permissions.count, 20)
        XCTAssertTrue((r.createdAt ?? "").hasSuffix("+00:00"))
        XCTAssertEqual(vm.ui.roles.first { $0.id == "trainee" }?.description, "")
    }

    func testCreateRoleSendsAnIdTheUpsertCannotCollideWith() async {
        let vm = await vm()
        // create_role upserts ON CONFLICT (id) - even over a protected role - so the id must be fresh.
        vm.saveRole(editing: nil, form: RoleForm(name: "Dispatch", description: "", color: "#0891b2", permissions: ["view_orders"]), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(writes().count, 1)
        let id = json(writes()[0])?.objectValue?["id"]?.stringValue ?? ""
        XCTAssertNotNil(id.range(of: #"^role_\d{13}$"#, options: .regularExpression), id)
        XCTAssertFalse(vm.ui.roles.map { $0.id }.contains(id))
        XCTAssertEqual(done, 1)
    }

    func testProtectedRoleRefusalsAreShown() async {
        let vm = await vm()
        vm.deleteRole(vm.ui.roles.first { $0.id == "super_admin" }!, onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Cannot delete a protected role")
        vm.saveRole(editing: vm.ui.roles.first { $0.id == "super_admin" }, form: RoleForm(name: "X"), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Cannot modify a protected role")
        XCTAssertEqual(done, 0)
    }

    /// Already gone is what was asked for: the dialog closes and the list is re-read.
    func testDeletingARoleAlreadyGoneCountsAsDone() async {
        let vm = await vm()
        status("DELETE", "/admin/roles/[^/]+", 404, "Role not found")
        vm.deleteRole(vm.ui.roles.first { $0.id == "trainee" }!, onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "That role was already deleted")
        XCTAssertEqual(done, 1)
    }

    /// No answer, and the re-read shows the role unchanged: the form stays open, saying it may not have saved.
    func testANetworkDropSaysSo() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/roles/[^/]+") { _, _ in throw TransportError.network("reset") }
        vm.saveRole(editing: vm.ui.roles.first { $0.id == "sales" }, form: RoleForm(name: "Sales"), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        XCTAssertEqual(done, 0)
    }

    func testCanStillManageTheTeamFromTheListRow() {
        XCTAssertTrue(access().can(Perms.MANAGE_AGENTS))
    }
}
