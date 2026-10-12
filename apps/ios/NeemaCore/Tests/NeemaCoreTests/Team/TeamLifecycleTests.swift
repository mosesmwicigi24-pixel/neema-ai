import Foundation
import XCTest
@testable import NeemaCore

/// Round 9 (lifecycle): the Team dialogs' typed input across a rotation (the
/// model survives; its save still closes the dialog of the NEW screen) and
/// across the app being reclaimed (a fresh model gets the saved state back -
/// never the passwords). Android `TeamLifecycleTest`; its first row is
/// `TeamViewModelTests.testTheFormsSurviveARestartExceptThePasswords`.
final class TeamLifecycleTests: TeamTestCase {
    private var subs: [Subscription] = []

    override func tearDown() async throws {
        subs.forEach { $0.cancel() }
        subs = []
        try await super.tearDown()
    }

    /// The dialogs to close that a save announces, from now on.
    private func announced(_ vm: TeamViewModel) -> Ref<[String]> {
        let got = Ref<[String]>([])
        subs.append(vm.closedDialogs.observe { d in got.mutate { $0.append(d) } })
        return got
    }

    func testANewRoleKeepsItsDraftIdAcrossARestart() async {
        let vm = await vm()
        vm.editForms { $0.openRole(nil) }
        let id = vm.ui.forms.roleDraftId
        let fresh = await self.vm()
        fresh.restoreUi(vm.saveUi())
        XCTAssertEqual(fresh.ui.forms.roleDraftId, id, "a retry after the restart updates, never duplicates")
    }

    func testGarbageSavedStateIsIgnored() async {
        let fresh = await vm()
        fresh.restoreUi("not json")
        XCTAssertEqual(fresh.ui.forms.createName, "")
        XCTAssertEqual(fresh.ui.forms.createRole, "agent")
    }

    /// The phone turned while "Create Agent" was on the wire: the screen that
    /// started it is gone. The success is announced by the model and the new
    /// screen closes the dialog when it starts listening.
    func testASaveThatLandsDuringARotationClosesTheNewScreensDialog() async {
        let vm = await vm()
        let got = announced(vm)
        vm.editForms { $0.createName = "Jane Doe"; $0.createEmail = "jane@bethanyhouse.co.ke"; $0.createPassword = "s3cretpass" }
        // No screen is collecting (it is being recreated).
        let f = vm.ui.forms
        vm.createAgent(name: f.createName, email: f.createEmail, password: f.createPassword, roleId: f.createRole) { vm.closeDialog("create") }
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Agent created")
        XCTAssertEqual(got.value, ["create"])
        // The web clears createForm once the agent exists.
        let after = vm.ui.forms
        XCTAssertEqual([after.createName, after.createEmail, after.createPassword, after.createRole], ["", "", "", "agent"])
    }

    func testAFailedSaveKeepsTheDialogAndEveryField() async {
        status("POST", "/admin/agents", 422, "Invalid email")
        let vm = await vm()
        let got = announced(vm)
        vm.editForms { $0.createName = "Jane"; $0.createEmail = "jane@x"; $0.createPassword = "s3cretpass" }
        vm.createAgent(name: "Jane", email: "jane@x", password: "s3cretpass", roleId: "agent") { vm.closeDialog("create") }
        await settled(vm)
        XCTAssertTrue(got.value.isEmpty)
        let f = vm.ui.forms
        XCTAssertEqual([f.createName, f.createEmail, f.createPassword], ["Jane", "jane@x", "s3cretpass"])
    }

    func testAPasswordResetEmptiesTheBoxesOnceItLands() async {
        let vm = await vm()
        let got = announced(vm)
        vm.editForms { $0.password = "brandnew99"; $0.confirm = "brandnew99" }
        vm.savePassword(agent(Fixtures.AGENT2_ID), password: "brandnew99", confirm: "brandnew99") { vm.closeDialog("pw") }
        await settled(vm)
        XCTAssertEqual(got.value, ["pw"])
        XCTAssertEqual(vm.ui.forms.password, "")
        XCTAssertEqual(vm.ui.forms.confirm, "")
    }

    /// Where the web resets a form on open (and where it doesn't: Add Agent keeps its text across Cancel).
    func testOpeningADialogStartsItsFormWhereTheWebDoes() async {
        let vm = await vm()
        let got = announced(vm)
        let a = agent(Fixtures.AGENT2_ID)
        vm.editForms { $0.editName = "stale"; $0.password = "stale"; $0.confirm = "stale"; $0.roleName = "stale" }
        vm.editForms { $0.openEdit(a) }
        XCTAssertEqual(vm.ui.forms.editName, a.name); XCTAssertEqual(vm.ui.forms.editEmail, a.email)
        vm.editForms { $0.openPassword() }
        XCTAssertEqual(vm.ui.forms.password, ""); XCTAssertEqual(vm.ui.forms.confirm, "")
        let support = vm.ui.roles.first { $0.id == "support" }!
        vm.editForms { $0.openRole(support) }
        XCTAssertEqual(vm.ui.forms.roleName, support.name); XCTAssertEqual(vm.ui.forms.rolePerms, support.permissions)
        vm.editForms { $0.openRole(nil) }
        XCTAssertEqual(vm.ui.forms.roleName, ""); XCTAssertEqual(vm.ui.forms.rolePerms, [])
        let roles = vm.ui.roles
        vm.editForms { $0.openAssign(a, roles: roles) }
        XCTAssertEqual(vm.ui.forms.assignRole, a.customRoleId ?? "")
        XCTAssertEqual(vm.ui.forms.assignOverride, a.customPermissions != nil)
        XCTAssertNil(got.value.first, "no dialog was closed by opening others")
    }
}
