import Foundation
import XCTest
@testable import NeemaCore

/// AgentsView.tsx's handlers: every call's endpoint and body, validation, and failure handling (Android `AgentsViewModelTest`).
final class TeamViewModelTests: TeamTestCase {
    func testLoadsRolesOnOpen() async {
        let v = await vm()
        // roles.py list_roles: ORDER BY protected DESC, name.
        XCTAssertEqual(v.ui.roles.map { $0.id }, ["super_admin", "agent", "sales", "support", "trainee", "viewer"])
        XCTAssertFalse(v.ui.rolesLoading)
        XCTAssertNil(v.ui.rolesError)
        XCTAssertNil(v.ui.agentsError)
    }

    func testRolesFailingToLoadToasts() async {
        status("GET", "/admin/roles", 500, "boom")
        _ = await vm()
        XCTAssertEqual(lastToast()?.message, "Failed to load roles")
        XCTAssertEqual(lastToast()?.type, .error)
    }

    // ── Create ───────────────────────────────────────────────────────────────

    func testCreatePostsTheAgentWithItsDbRole() async {
        let vm = await vm()
        vm.createAgent(name: "  Jane Doe ", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "admin", onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "POST"); XCTAssertEqual(w.first?.path, "/admin/agents")
        XCTAssertEqual(json(w[0]), el(#"{"name":"Jane Doe","email":"jane@bethanyhouse.co.ke","password":"s3cretpass","role":"admin"}"#))
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Agent created")
        _ = await eventually { self.called("GET", "/admin/agents") }
        XCTAssertTrue(called("GET", "/admin/agents"), "refetches the team")
        XCTAssertEqual(vm.ui.forms.createName, "", "the web clears createForm only once an agent is made")
    }

    func testCreateNeedsNameEmailAndPassword() async {
        let vm = await vm()
        vm.createAgent(name: "", email: "jane@x.co", password: "s3cretpass", roleId: "agent", onDone: onDone)
        vm.createAgent(name: "Jane", email: "", password: "s3cretpass", roleId: "agent", onDone: onDone)
        vm.createAgent(name: "Jane", email: "jane@x.co", password: "", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(done, 0)
        XCTAssertTrue(toasts.allSatisfy { $0.message == "Name, email and password are required" && $0.type == .error })
        XCTAssertEqual(toasts.count, 3)
    }

    func testCreateNeedsEightCharacters() async {
        let vm = await vm()
        vm.createAgent(name: "Jane", email: "jane@x.co", password: "1234567", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(lastToast()?.message, "Password must be ≥8 characters")
    }

    func testCreateFailureKeepsTheDialogOpen() async {
        let vm = await vm()
        status("POST", "/admin/agents", 422, "Missing required fields: email")
        vm.createAgent(name: "Jane", email: "jane@x.co", password: "12345678", roleId: "readonly", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, "Missing required fields: email")
        XCTAssertFalse(vm.ui.saving)
    }

    func testDbRoleMapping() {
        XCTAssertEqual(toDbRole("admin"), "admin")
        XCTAssertEqual(toDbRole("agent"), "agent")
        XCTAssertEqual(toDbRole("readonly"), "readonly")
        XCTAssertEqual(toDbRole("super_admin"), "admin")
        XCTAssertEqual(toDbRole("viewer"), "readonly")
        XCTAssertEqual(toDbRole("role_17000"), "agent")
    }

    // ── Edit / password / remove ─────────────────────────────────────────────

    func testEditPatchesNameAndEmailOnly() async {
        let vm = await vm()
        vm.saveEdit(agent(Fixtures.AGENT2_ID), name: "Grace W.", email: "gw@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PATCH"); XCTAssertEqual(w.first?.path, "/admin/agents/\(Fixtures.AGENT2_ID)")
        XCTAssertEqual(json(w[0]), el(#"{"name":"Grace W.","email":"gw@bethanyhouse.co.ke"}"#))
        XCTAssertEqual(lastToast()?.message, "Agent updated")
        XCTAssertEqual(done, 1)
    }

    func testEditNeedsNameAndEmail() async {
        let vm = await vm()
        vm.saveEdit(agent(Fixtures.AGENT2_ID), name: " ", email: "gw@x.co", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(lastToast()?.message, "Name and email required")
    }

    func testPasswordLengthIsCheckedBeforeTheMatch() async {
        let vm = await vm()
        vm.savePassword(agent(Fixtures.AGENT2_ID), password: "short", confirm: "different", onDone: onDone)
        XCTAssertEqual(lastToast()?.message, "Password must be ≥8 characters")
        vm.savePassword(agent(Fixtures.AGENT2_ID), password: "longenough1", confirm: "longenough2", onDone: onDone)
        XCTAssertEqual(lastToast()?.message, "Passwords do not match")
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
    }

    func testPasswordResetSendsOnlyThePassword() async {
        let vm = await vm()
        vm.savePassword(agent(Fixtures.AGENT3_ID), password: "n3wpassword", confirm: "n3wpassword", onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PATCH"); XCTAssertEqual(w.first?.path, "/admin/agents/\(Fixtures.AGENT3_ID)")
        XCTAssertEqual(json(w[0]), el(#"{"password":"n3wpassword"}"#))
        XCTAssertEqual(lastToast()?.message, "Password updated")
        XCTAssertEqual(vm.ui.forms.password, "", "the password fields are emptied")
    }

    func testRemoveDeletesAndRefetches() async {
        let vm = await vm()
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "DELETE"); XCTAssertEqual(w.first?.path, "/admin/agents/\(Fixtures.AGENT3_ID)")
        XCTAssertEqual(lastToast()?.message, "Agent removed")
        _ = await eventually { self.called("GET", "/admin/agents") }
        XCTAssertTrue(called("GET", "/admin/agents"))
    }

    func testRemoveFailureUsesTheWebsWording() async {
        let vm = await vm()
        status("DELETE", "/admin/agents/.*", 500, "db down")
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Failed to remove")
        XCTAssertEqual(done, 0)
    }

    func testYouCannotRemoveYourselfOrTheLastAdmin() async {
        let vm = await vm()
        XCTAssertEqual(vm.removalBlocker(agent(Fixtures.ME_ID)), "You can't remove your own account — ask another admin")
        XCTAssertFalse(vm.requestRemove(agent(Fixtures.ME_ID)))
        XCTAssertEqual(lastToast()?.message, "You can't remove your own account — ask another admin")
        XCTAssertNil(vm.removalBlocker(agent(Fixtures.AGENT3_ID)))
        XCTAssertTrue(vm.requestRemove(agent(Fixtures.AGENT3_ID)))
        // Grace becomes the only admin (Moses a plain agent): she can't go either.
        host.agents.value = host.agents.value.map { a in
            var c = a
            if a.id == Fixtures.AGENT2_ID { c.role = "admin" }
            if a.id == Fixtures.ME_ID { c.role = "agent"; c.isSuperuser = false }
            return c
        }
        XCTAssertEqual(vm.removalBlocker(agent(Fixtures.AGENT2_ID)), "You can't remove the last admin")
        vm.deleteAgent(agent(Fixtures.AGENT2_ID), onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty, "the blocker is checked again at the button")
        XCTAssertEqual(done, 0)
    }

    // ── Availability ─────────────────────────────────────────────────────────

    func testAvailabilityPatchesTheFlippedValue() async {
        let vm = await vm()
        vm.toggleOnline(agent(Fixtures.AGENT2_ID), current: true)
        XCTAssertEqual(vm.ui.availability[Fixtures.AGENT2_ID], false, "flips the moment the switch is touched")
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PATCH"); XCTAssertEqual(w.first?.path, "/admin/agents/\(Fixtures.AGENT2_ID)")
        XCTAssertEqual(json(w[0]), el(#"{"is_available":false}"#))
        XCTAssertEqual(vm.ui.availability[Fixtures.AGENT2_ID], false)
    }

    func testAvailabilityRevertsOnFailure() async {
        let vm = await vm()
        status("PATCH", "/admin/agents/.*", 500, "x")
        vm.toggleOnline(agent(Fixtures.AGENT3_ID), current: false)
        await settled(vm)
        XCTAssertTrue(vm.ui.availability.isEmpty)
        XCTAssertEqual(lastToast()?.message, "Failed to update availability")
    }

    func testReconcileDropsValuesTheServerNowAgreesWith() async {
        let vm = await vm()
        vm.toggleOnline(agent(Fixtures.AGENT2_ID), current: true)
        await settled(vm)
        // The refetched list still says true (the fake doesn't store writes): the optimistic value stays.
        vm.reconcile(host.agents.value)
        XCTAssertEqual(vm.ui.availability[Fixtures.AGENT2_ID], false)
        vm.reconcile(host.agents.value.map { a in var c = a; if a.id == Fixtures.AGENT2_ID { c.isAvailable = false }; return c })
        XCTAssertTrue(vm.ui.availability.isEmpty)
    }

    // ── Role assignment ──────────────────────────────────────────────────────

    func testAssignSendsOnlyTheRoleLikeTheWeb() async {
        let vm = await vm()
        vm.saveAssign(agent(Fixtures.AGENT3_ID), roleId: "sales", customPermissions: nil, onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PATCH"); XCTAssertEqual(w.first?.path, "/admin/agents/\(Fixtures.AGENT3_ID)/role")
        XCTAssertEqual(json(w[0]), el(#"{"custom_role_id":"sales"}"#))
        XCTAssertEqual(lastToast()?.message, "Role assigned")
        XCTAssertEqual(done, 1)
    }

    func testAssignWithOverrideSendsThePermissions() async {
        let vm = await vm()
        vm.saveAssign(agent(TeamFixtures.AGENT4_ID), roleId: "support", customPermissions: ["view_conversations", "add_notes"], onDone: onDone)
        await settled(vm)
        let body = json(writes()[0])?.objectValue
        XCTAssertEqual(body?["custom_role_id"], .string("support"))
        XCTAssertEqual(body?["custom_permissions"], .array([.string("view_conversations"), .string("add_notes")]))
    }

    func testAssignNeedsARole() async {
        let vm = await vm()
        vm.saveAssign(agent(Fixtures.AGENT3_ID), roleId: "", customPermissions: nil, onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(lastToast()?.message, "Please select a role")
    }

    func testAssigningYourselfRefreshesMe() async {
        let vm = await vm()
        vm.saveAssign(agent(Fixtures.ME_ID), roleId: "super_admin", customPermissions: nil, onDone: onDone)
        await settled(vm)
        _ = await eventually { self.called("GET", "/admin/me") }
        XCTAssertTrue(called("GET", "/admin/me"))
    }

    // ── Roles ────────────────────────────────────────────────────────────────

    func testNewRolePostsAFreshIdAndTheForm() async {
        let vm = await vm()
        vm.saveRole(editing: nil, form: RoleForm(name: "Dispatch", description: "Ships orders", color: "#0891b2", permissions: ["view_orders", "manage_orders"]), onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "POST"); XCTAssertEqual(w.first?.path, "/admin/roles")
        var body = json(w[0])?.objectValue ?? [:]
        XCTAssertTrue((body["id"]?.stringValue ?? "").range(of: #"^role_\d+$"#, options: .regularExpression) != nil, "\(body)")
        body["id"] = nil
        XCTAssertEqual(JSONValue.object(body), el(##"{"name":"Dispatch","description":"Ships orders","color":"#0891b2","permissions":["view_orders","manage_orders"]}"##))
        XCTAssertEqual(toasts.first?.message, "Role created")
        XCTAssertTrue(called("GET", "/admin/roles"), "refetches roles")
        XCTAssertEqual(done, 1)
    }

    func testEditRolePatchesEveryField() async {
        let vm = await vm()
        let role = vm.ui.roles.first { $0.id == "sales" }!
        vm.saveRole(editing: role, form: RoleForm(name: "Sales", description: "Closes deals", color: "#b45309", permissions: []), onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "PATCH"); XCTAssertEqual(w.first?.path, "/admin/roles/sales")
        XCTAssertEqual(json(w[0]), el(##"{"name":"Sales","description":"Closes deals","color":"#b45309","permissions":[]}"##))
        XCTAssertEqual(toasts.first?.message, "Role updated")
    }

    func testRoleNeedsAName() async {
        let vm = await vm()
        vm.saveRole(editing: nil, form: RoleForm(name: "  "), onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(lastToast()?.message, "Role name required")
    }

    func testProtectedRoleRefusalIsShown() async {
        let vm = await vm()
        // The fixture answers as roles.py update_role does for a protected role.
        vm.saveRole(editing: vm.ui.roles.first { $0.id == "super_admin" }, form: RoleForm(name: "Admin"), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Cannot modify a protected role")
        XCTAssertEqual(done, 0)
    }

    func testDeleteRoleDeletesThenRefetches() async {
        let vm = await vm()
        vm.deleteRole(vm.ui.roles.first { $0.id == "trainee" }!, onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first?.method, "DELETE"); XCTAssertEqual(w.first?.path, "/admin/roles/trainee")
        XCTAssertEqual(lastToast()?.message, "Role deleted")
        XCTAssertTrue(called("GET", "/admin/roles"))
        _ = await eventually { self.called("GET", "/admin/agents") }
        XCTAssertTrue(called("GET", "/admin/agents"))
    }

    func testOneSaveAtATime() async {
        let vm = await vm()
        let inside = Ref(0)
        let vmRef = Ref<TeamViewModel?>(vm)
        let onDone = self.onDone
        fake.on("POST", "/admin/roles") { _, _ in
            inside.mutate { $0 += 1 }
            // A second tap while the first is in flight is ignored.
            onMainSync { vmRef.value?.saveRole(editing: nil, form: RoleForm(name: "Again"), onDone: onDone) }
            return (200, ##"{"id":"role_1","name":"x","description":"","color":"#589b31","permissions":[],"protected":false}"##)
        }
        vm.saveRole(editing: nil, form: RoleForm(name: "Once"), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(inside.value, 1)
    }

    // ── Replies: POST /admin/agents answers with whatever object the server sends ──

    func testCreateAcceptsTheFullAgentRow() async {
        let vm = await vm()
        // admin.py create_agent returns the new agent (the TeamFixtures route answers that way).
        vm.createAgent(name: "Jane Doe", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Agent created")
        XCTAssertEqual(lastToast()?.type, .success)
    }

    func testCreateAcceptsABareOk() async {
        let vm = await vm()
        // Any JSON object is a success; nothing in the reply is read.
        fake.on("POST", "/admin/agents", body: #"{"ok":true}"#)
        vm.createAgent(name: "Jane Doe", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Agent created")
    }

    func testCreateAcceptsAnEmptyObject() async {
        let vm = await vm()
        fake.on("POST", "/admin/agents", body: "{}")
        vm.createAgent(name: "Jane Doe", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
    }

    // ── The forms: what a restart gets back ──────────────────────────────────

    func testTheFormsSurviveARestartExceptThePasswords() async {
        let vm = await vm()
        vm.editForms { f in
            f.createName = "Jane"; f.createEmail = "jane@x.co"; f.createPassword = "hunter2hunter2"; f.createRole = "readonly"
            f.password = "n3wpassword"; f.confirm = "n3wpassword"
            f.openAssign(self.agent(TeamFixtures.AGENT4_ID), roles: vm.ui.roles)
            f.openRole(vm.ui.roles.first { $0.id == "sales" })
        }
        let saved = vm.saveUi()
        XCTAssertFalse(saved.contains("hunter2hunter2"))
        XCTAssertFalse(saved.contains("n3wpassword"))
        let fresh = await self.vm()
        XCTAssertTrue(fresh.restoreIfFresh(saved))
        let f = fresh.ui.forms
        XCTAssertEqual(f.createName, "Jane"); XCTAssertEqual(f.createEmail, "jane@x.co"); XCTAssertEqual(f.createRole, "readonly")
        XCTAssertEqual(f.createPassword, ""); XCTAssertEqual(f.password, ""); XCTAssertEqual(f.confirm, "")
        XCTAssertEqual(f.assignRole, "support"); XCTAssertTrue(f.assignOverride)
        XCTAssertEqual(f.assignPerms, ["view_conversations", "reply_conversations", "add_notes"])
        XCTAssertEqual(f.roleName, "Sales"); XCTAssertEqual(f.roleColor, "#3b82f6")
        XCTAssertEqual(f.rolePerms, ["view_conversations", "reply_conversations", "view_orders", "manage_orders"])
        // Assign without an override starts from the role's own permissions; a new role editor gets a fresh id.
        fresh.editForms { $0.openAssign(self.agent(Fixtures.AGENT2_ID), roles: fresh.ui.roles) }
        XCTAssertFalse(fresh.ui.forms.assignOverride)
        XCTAssertEqual(fresh.ui.forms.assignPerms, ["view_conversations", "reply_conversations", "view_orders", "manage_orders"])
        let before = fresh.ui.forms.roleDraftId
        AppClock.pin(to: PINNED.addingTimeInterval(5))
        fresh.editForms { $0.openRole(nil) }
        XCTAssertNotEqual(fresh.ui.forms.roleDraftId, before)
        XCTAssertEqual(fresh.ui.forms.roleName, "")
        fresh.restoreUi("not json")
        XCTAssertEqual(fresh.ui.forms.roleName, "")
    }
}
