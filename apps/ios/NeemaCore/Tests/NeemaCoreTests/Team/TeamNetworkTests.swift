import Foundation
import XCTest
@testable import NeemaCore

/// The Team screen on a bad phone network: every load and every write under
/// offline, timeout, 401, 403 / 404 / 422 / 429 / 5xx, HTML pages, garbled
/// bodies, double taps and sign-out mid-request (Android `TeamNetworkTest`).
final class TeamNetworkTests: TeamTestCase {
    private let html502 = "<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center><hr><center>nginx</center></body></html>"

    // ── Loads ────────────────────────────────────────────────────────────────

    func testRolesOfflineTabSaysWhyWithRetryThenRetryLoads() async {
        fake.failOffline("GET", "/admin/roles")
        let v = await vm()
        XCTAssertEqual(v.ui.rolesError, FriendlyErrors.OFFLINE_TEXT)
        XCTAssertTrue(v.ui.roles.isEmpty)
        XCTAssertFalse(v.ui.rolesLoading)
        // Back online: Retry (the tab's button) reads them and clears the notice.
        fake.on("GET", "/admin/roles", body: TeamFixtures.roles)
        v.refresh()
        _ = await eventually(timeout: 10) { !v.ui.refreshing }
        await drain()
        XCTAssertNil(v.ui.rolesError)
        XCTAssertEqual(v.ui.roles.count, 6)
        XCTAssertFalse(v.ui.refreshing)
    }

    func testTeamNeverLoadedScreenAsksAtOnceAndSaysWhy() async {
        // Signed in offline: the dashboard's first read failed, the list is empty.
        let f = Fixtures.withFixtures()
        TeamFixtures.install(f)
        f.failTimeout("GET", "/admin/agents")
        fake = f
        let h = TestHost(fake: f)
        let v = TeamViewModel(host: h, sleep: h.clock.sleeper)
        vms.append(v)
        await drain()
        _ = await eventually(timeout: 10) { v.ui.agentsError != nil }
        XCTAssertTrue(h.agents.value.isEmpty)
        XCTAssertEqual(v.ui.agentsError, FriendlyErrors.TIMEOUT_TEXT)
        // The next successful read (any poller) clears it.
        f.on("GET", "/admin/agents", body: TeamFixtures.agents)
        v.refresh()
        _ = await eventually(timeout: 10) { !v.ui.refreshing }
        await drain()
        XCTAssertNil(v.ui.agentsError)
        XCTAssertEqual(h.agents.value.count, 4)
        h.logout()
    }

    func testPullToRefreshFailingKeepsTheTeamAndSaysSo() async {
        let vm = await vm()
        fake.htmlPage("GET", "/admin/agents", code: 503)
        vm.refresh()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        await drain()
        XCTAssertEqual(host.agents.value.count, 4)
        XCTAssertEqual(toasts.filter { $0.type == .error }.map { $0.message }, ["Couldn't refresh the team. \(FriendlyErrors.DOWN_TEXT)"])
        XCTAssertFalse(vm.ui.refreshing, "the spinner stops")
    }

    func testGarbledRolesNoCrashSensibleState() async {
        fake.on("GET", "/admin/roles", body: #"{"roles": "definitely not a list""#)
        let v = await vm()
        XCTAssertTrue(v.ui.roles.isEmpty)
        XCTAssertEqual(v.ui.rolesError, "The server sent an answer the app couldn't read — try again.")
    }

    // ── Create: duplicate email, timeouts, double taps ──────────────────────

    func testDuplicateEmailRaceBecomesA500SaysWhyAndKeepsTheForm() async {
        let vm = await vm()
        // Someone added this address after the list was read: the API's unhandled IntegrityError.
        fake.on("POST", "/admin/agents", code: 500, body: "Internal Server Error")
        vm.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, "Couldn't create the agent — that email may already be in use")
        XCTAssertFalse(vm.ui.saving)
    }

    func testCreateTimesOutButTheServerMadeThemCountsAsCreated() async {
        let vm = await vm()
        let fake = self.fake!
        let list = agentsWith { rows in
            var jane = rows[0]
            jane["id"] = .string(TeamFixtures.NEW_AGENT_ID); jane["name"] = .string("Jane"); jane["email"] = .string("jane@bethanyhouse.co.ke")
            rows.append(jane)
        }
        fake.failTimeout("POST", "/admin/agents") { _ in fake.on("GET", "/admin/agents", body: list) }
        vm.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Agent created")
        XCTAssertEqual(writesTo("POST", "/admin/agents"), 1)
    }

    func testCreateTimesOutAndTheyAreNotThereKeepsTheFormAndSaysItMayNotHaveSaved() async {
        let vm = await vm()
        fake.failTimeout("POST", "/admin/agents")
        vm.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        XCTAssertFalse(vm.ui.saving)
    }

    func testCreateOfflineSaysOfflineNeverClaimsItMightHaveSaved() async {
        let vm = await vm()
        fake.failOffline("POST", "/admin/agents")
        vm.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.OFFLINE_TEXT)
    }

    func testDoubleTapOnCreateSendsOnce() async {
        let vm = await vm()
        let vmRef = Ref<TeamViewModel?>(vm)
        let onDone = self.onDone
        // The second tap lands while the first request is on the wire.
        fake.on("POST", "/admin/agents") { _, _ in
            onMainSync { vmRef.value?.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone) }
            return (200, TeamFixtures.ormAgent(id: TeamFixtures.NEW_AGENT_ID, name: "Jane", email: "jane@bethanyhouse.co.ke", role: "agent"))
        }
        vm.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "s3cretpass", roleId: "agent", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(writesTo("POST", "/admin/agents"), 1)
        XCTAssertEqual(done, 1)
    }

    func testThePasswordIsNeverReadBack() async {
        let vm = await vm()
        // A server that echoes the password in its error (a pydantic-style detail).
        status("POST", "/admin/agents", 422, "Value 'hunter2hunter2' is not a valid password")
        vm.createAgent(name: "Jane", email: "jane@bethanyhouse.co.ke", password: "hunter2hunter2", roleId: "agent", onDone: onDone)
        await settled(vm)
        let msg = lastToast()?.message ?? ""
        XCTAssertFalse(msg.contains("hunter2hunter2"), msg)
        XCTAssertTrue(msg.contains("••••••"), msg)
        status("PATCH", "/admin/agents/[^/]+", 422, "hunter2hunter2 is too common")
        vm.savePassword(agent(Fixtures.AGENT3_ID), password: "hunter2hunter2", confirm: "hunter2hunter2", onDone: onDone)
        await settled(vm)
        XCTAssertFalse((lastToast()?.message ?? "").contains("hunter2hunter2"))
    }

    // ── Edit / password / assign / remove ────────────────────────────────────

    func testEditTimesOutButLandedClosesAsSaved() async {
        let vm = await vm()
        let fake = self.fake!
        let list = agentsWith { rows in
            if let i = rows.firstIndex(where: { $0["id"]?.stringValue == Fixtures.AGENT2_ID }) { rows[i]["name"] = .string("Grace W.") }
        }
        fake.failTimeout("PATCH", "/admin/agents/[^/]+") { _ in fake.on("GET", "/admin/agents", body: list) }
        vm.saveEdit(agent(Fixtures.AGENT2_ID), name: "Grace W.", email: "grace@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Agent updated")
    }

    func testEditTimesOutNotLandedKeepsTheForm() async {
        let vm = await vm()
        fake.failTimeout("PATCH", "/admin/agents/[^/]+")
        vm.saveEdit(agent(Fixtures.AGENT2_ID), name: "Grace W.", email: "grace@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
    }

    func testPasswordTimeoutKeepsBothFieldsForAnotherGo() async {
        let vm = await vm()
        fake.failTimeout("PATCH", "/admin/agents/[^/]+")
        vm.savePassword(agent(Fixtures.AGENT3_ID), password: "n3wpassword", confirm: "n3wpassword", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        // Setting it again is harmless: the retry goes out and succeeds.
        fake.on("PATCH", "/admin/agents/[^/]+", body: #"{"ok":true}"#)
        vm.savePassword(agent(Fixtures.AGENT3_ID), password: "n3wpassword", confirm: "n3wpassword", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
    }

    func testAgentDeletedElsewhereEveryActionRemovesThemAndSaysSo() async {
        let vm = await vm()
        // Brian is gone on the server: every write about him answers 404, and the list no longer has him.
        fake.on("GET", "/admin/agents", body: agentsWith { rows in rows.removeAll { $0["id"]?.stringValue == Fixtures.AGENT3_ID } })
        let brian = agent(Fixtures.AGENT3_ID)
        status("PATCH", "/admin/agents/[^/]+", 404, "Agent not found")
        status("PATCH", "/admin/agents/[^/]+/role", 404, "Agent not found")
        vm.saveEdit(brian, name: "Brian O.", email: "brian@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Brian Otieno was removed by someone else")
        XCTAssertFalse(host.agents.value.contains { $0.id == Fixtures.AGENT3_ID }, "the card goes")
        vm.saveAssign(brian, roleId: "sales", customPermissions: nil, onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Brian Otieno was removed by someone else")
        vm.toggleOnline(brian, current: false)
        await settled(vm)
        _ = await eventually(timeout: 5) { vm.ui.availability.isEmpty }
        XCTAssertEqual(lastToast()?.message, "Brian Otieno was removed by someone else")
        XCTAssertTrue(vm.ui.availability.isEmpty, "no optimistic switch left behind")
        XCTAssertEqual(done, 2)
    }

    func testRemovingSomeoneAlreadyRemovedCountsAsDone() async {
        let vm = await vm()
        status("DELETE", "/admin/agents/[^/]+", 404, "Agent not found")
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Brian Otieno was already removed")
        XCTAssertEqual(lastToast()?.type, .success)
    }

    func testRemoveTimesOutButTheyAreGoneCountsAsRemoved() async {
        let vm = await vm()
        let fake = self.fake!
        let list = agentsWith { rows in rows.removeAll { $0["id"]?.stringValue == Fixtures.AGENT3_ID } }
        fake.failTimeout("DELETE", "/admin/agents/[^/]+") { _ in fake.on("GET", "/admin/agents", body: list) }
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Agent removed")
    }

    func testRemoveOfflineSaysOfflineNotTheWebsFixedWords() async {
        let vm = await vm()
        fake.failOffline("DELETE", "/admin/agents/[^/]+")
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.OFFLINE_TEXT)
        XCTAssertEqual(done, 0)
    }

    func testDoubleTapOnRemoveSendsOneDelete() async {
        let vm = await vm()
        let vmRef = Ref<TeamViewModel?>(vm)
        let brian = agent(Fixtures.AGENT3_ID)
        let onDone = self.onDone
        fake.on("DELETE", "/admin/agents/[^/]+") { _, _ in
            onMainSync { vmRef.value?.deleteAgent(brian, onDone: onDone) }
            return (200, #"{"ok":true}"#)
        }
        vm.deleteAgent(brian, onDone: onDone)
        await settled(vm)
        XCTAssertEqual(writesTo("DELETE", "/admin/agents/.*"), 1)
    }

    func testAvailabilityDoubleTapSendsOneAndATimeoutShowsTheServersValue() async {
        let vm = await vm()
        let sent = Ref(0)
        let vmRef = Ref<TeamViewModel?>(vm)
        let brian = agent(Fixtures.AGENT3_ID)
        fake.on("PATCH", "/admin/agents/[^/]+") { _, _ in
            sent.mutate { $0 += 1 }
            onMainSync { vmRef.value?.toggleOnline(brian, current: true) } // impatient second tap
            return (200, #"{"ok":true}"#)
        }
        vm.toggleOnline(brian, current: false)
        await settled(vm)
        _ = await eventually(timeout: 5) { vm.ui.availability.isEmpty || sent.value >= 1 }
        await settle(ms: 30)
        XCTAssertEqual(sent.value, 1)
        // No answer, and the server still says offline: the switch shows that, and says so.
        fake.failTimeout("PATCH", "/admin/agents/[^/]+")
        vm.toggleOnline(brian, current: false)
        await settled(vm)
        _ = await eventually(timeout: 5) { vm.ui.availability.isEmpty }
        XCTAssertTrue(vm.ui.availability.isEmpty)
        XCTAssertEqual(lastToast()?.message, "Couldn't reach the server — availability unchanged")
    }

    func testAssignTimesOutButLandedClosesAsAssigned() async {
        let vm = await vm()
        let fake = self.fake!
        let list = agentsWith { rows in
            if let i = rows.firstIndex(where: { $0["id"]?.stringValue == Fixtures.AGENT3_ID }) { rows[i]["custom_role_id"] = .string("sales") }
        }
        fake.failTimeout("PATCH", "/admin/agents/[^/]+/role") { _ in fake.on("GET", "/admin/agents", body: list) }
        vm.saveAssign(agent(Fixtures.AGENT3_ID), roleId: "sales", customPermissions: nil, onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Role assigned")
    }

    // ── Roles ────────────────────────────────────────────────────────────────

    func testNewRoleRetriedAfterATimeoutReusesItsIdSoNoTwinIsMade() async {
        let vm = await vm()
        fake.failTimeout("POST", "/admin/roles")
        let form = RoleForm(name: "Delivery", description: "Riders", permissions: ["view_orders"], id: "role_1759000000000")
        vm.saveRole(editing: nil, form: form, onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        fake.on("POST", "/admin/roles") { _, b in (200, b ?? "{}") }
        vm.saveRole(editing: nil, form: form, onDone: onDone)
        await settled(vm)
        let ids = since.filter { $0.method == "POST" && $0.path == "/admin/roles" }.map { JSONValue.parse($0.body ?? "")?.objectValue?["id"]?.stringValue ?? "" }
        XCTAssertEqual(ids, ["role_1759000000000", "role_1759000000000"])
        XCTAssertEqual(done, 1)
    }

    func testRoleEditedAfterSomeoneDeletedItClosesAndSaysSo() async {
        let vm = await vm()
        status("PATCH", "/admin/roles/[^/]+", 404, "Role not found")
        vm.saveRole(editing: vm.ui.roles.first { $0.id == "sales" }, form: RoleForm(name: "Sales 2"), onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "That role was deleted by someone else")
        XCTAssertEqual(done, 1)
    }

    func testRoleDeleteTimesOutButItIsGoneCountsAsDeleted() async {
        let vm = await vm()
        let fake = self.fake!
        let remaining = JSONValue.array((JSONValue.parse(TeamFixtures.roles)?.arrayValue ?? []).filter { $0.objectValue?["id"]?.stringValue != "trainee" }).text
        fake.failTimeout("DELETE", "/admin/roles/[^/]+") { _ in fake.on("GET", "/admin/roles", body: remaining) }
        vm.deleteRole(vm.ui.roles.first { $0.id == "trainee" }!, onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Role deleted")
        XCTAssertFalse(vm.ui.roles.contains { $0.id == "trainee" })
    }

    // ── Status codes ─────────────────────────────────────────────────────────

    func testEveryStatusGetsPlainWords() async {
        let vm = await vm()
        let cases: [(Int, String, String)] = [
            (403, #"{"detail":"Cannot modify a protected role"}"#, "Cannot modify a protected role"),
            (422, #"{"detail":[{"loc":["body","name"],"msg":"Field required","type":"missing"}]}"#, "Field required"),
            (429, #"{"detail":"Too Many Requests"}"#, FriendlyErrors.BUSY_TEXT),
            (500, "Internal Server Error", "Something went wrong — please try again"),
            (502, html502, FriendlyErrors.DOWN_TEXT),
            (503, "", FriendlyErrors.DOWN_TEXT),
            (418, "<html>teapot</html>", "Something went wrong — please try again"),
        ]
        for (code, body, want) in cases {
            fake.on("PATCH", "/admin/roles/[^/]+", code: code, body: body)
            vm.saveRole(editing: vm.ui.roles.first { $0.id == "sales" }, form: RoleForm(name: "Sales"), onDone: onDone)
            await settled(vm)
            let got = lastToast()?.message ?? ""
            XCTAssertEqual(got, want, "\(code)")
            XCTAssertFalse(got.contains("<"), "no markup for \(code)")
        }
        XCTAssertEqual(done, 0)
    }

    // ── 401 mid-action ───────────────────────────────────────────────────────

    func testStaleTokenRefreshesSilentlyAndTheSaveCompletes() async {
        let vm = await vm()
        fake.on("POST", "/(agent-auth|auth)/refresh", body: Fixtures.tokenResponse(access: fakeJwt(expiresInSec: 300 * 24 * 3600)))
        fake.expiredOnce("PATCH", "/admin/agents/[^/]+") { (200, #"{"ok":true}"#) }
        vm.saveEdit(agent(Fixtures.AGENT2_ID), name: "Grace W.", email: "grace@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Agent updated")
        XCTAssertFalse(host.sessionExpired.value)
        XCTAssertTrue(called("POST", "/auth/refresh") || called("POST", "/agent-auth/refresh"))
    }

    func testSessionGoneDialogShowsFormKeptAndTheRetryWorksAfterSignIn() async {
        let vm = await vm()
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        fake.on("PATCH", "/admin/agents/[^/]+", code: 401, body: #"{"detail":"Could not validate credentials"}"#)
        vm.saveEdit(agent(Fixtures.AGENT2_ID), name: "Grace W.", email: "grace@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(host.sessionExpired.value, "the session-expired dialog")
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.EXPIRED_TEXT)
        XCTAssertFalse(vm.ui.saving)
        // Signed back in: the same input, the same button, and it goes through.
        fake.on("POST", "/(agent-auth|auth)/refresh", body: Fixtures.tokenResponse())
        fake.on("PATCH", "/admin/agents/[^/]+", body: #"{"ok":true}"#)
        host.onReauthenticated()
        vm.saveEdit(agent(Fixtures.AGENT2_ID), name: "Grace W.", email: "grace@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
    }

    // ── Leaving mid-request ──────────────────────────────────────────────────

    func testSigningOutMidSaveSaysNothingAndClosesNothing() async {
        let vm = await vm()
        let vmRef = Ref<TeamViewModel?>(vm)
        // The agent signs out while the save is on the wire: the screen's model is closed.
        fake.on("PATCH", "/admin/agents/[^/]+") { _, _ in onMainSync { vmRef.value?.close() }; return (500, "Internal Server Error") }
        vm.saveEdit(agent(Fixtures.AGENT2_ID), name: "Grace W.", email: "grace@bethanyhouse.co.ke", onDone: onDone)
        await drain()
        await settle(ms: 100)
        XCTAssertTrue(toasts.allSatisfy { $0.type != .error }, "no toast for a screen that is gone: \(toasts)")
        XCTAssertEqual(done, 0)
    }
}
