import Foundation
import XCTest
@testable import NeemaCore

/// The Profile forms across a rotation, a restart, and a save on the wire (Android `ProfileLifecycleTest`).
final class ProfileLifecycleTests: ProfileTestCase {
    override func install(_ f: FakeNeema) { TeamFixtures.writes(f) }

    /// The forms `vm` folds away, from now on.
    private func announcements(_ vm: ProfileViewModel) -> Ref<[String]> {
        let got = Ref<[String]>([])
        let sub = vm.closedForms.observe { f in got.mutate { $0.append(f) } }
        subs.append(sub)
        return got
    }
    private var subs: [Subscription] = []

    override func tearDown() async throws {
        subs.forEach { $0.cancel() }
        subs = []
        try await super.tearDown()
    }

    func testTheEditFormSurvivesARestartButThePasswordsDoNot() async {
        let vm = await vm()
        vm.fillForm(me())
        vm.editForm { $0.name = "Moses M."; $0.department = "Sales"; $0.password = "brandnew-pass-9"; $0.confirm = "brandnew-pass-9" }
        let saved = vm.saveUi()!
        XCTAssertFalse(saved.contains("brandnew-pass-9"), "passwords never go into saved state")

        let fresh = await self.vm()
        fresh.restoreUi(saved)
        // The screen fills the form from /me on its first frame: the restored typing wins.
        fresh.fillForm(me())
        XCTAssertEqual(fresh.ui.form.name, "Moses M.")
        XCTAssertEqual(fresh.ui.form.department, "Sales")
        XCTAssertEqual(fresh.ui.form.email, me().email)
        XCTAssertEqual(fresh.ui.form.password, "")
        XCTAssertEqual(fresh.ui.form.confirm, "")
    }

    func testNothingIsSavedBeforeTheFormIsFilled() async {
        let vm = await vm()
        XCTAssertNil(vm.saveUi())
    }

    /// Like the web's `form`: filled once per agent, never refilled over the typing.
    func testTheFormIsFilledOncePerAgent() async {
        let vm = await vm()
        vm.fillForm(me())
        vm.editForm { $0.name = "typed" }
        vm.fillForm(me())
        XCTAssertEqual(vm.ui.form.name, "typed")
    }

    func testAPasswordChangeThatLandsDuringARotationFoldsTheNewScreensForm() async {
        let vm = await vm()
        let announced = announcements(vm)
        vm.editForm { $0.password = "brandnew-pass-9"; $0.confirm = "brandnew-pass-9" }
        vm.changePassword(password: vm.ui.form.password, confirm: vm.ui.form.confirm) { vm.closeForm("password") }
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Password changed successfully")
        XCTAssertEqual(announced.value, ["password"])
        XCTAssertEqual(vm.ui.form.password, "")
        XCTAssertEqual(vm.ui.form.confirm, "")
    }

    func testAFailedPasswordChangeKeepsTheBoxes() async {
        let vm = await vm()
        fail("PATCH", "/admin/me", 400, "Nope")
        let announced = announcements(vm)
        vm.editForm { $0.password = "brandnew-pass-9"; $0.confirm = "brandnew-pass-9" }
        vm.changePassword(password: vm.ui.form.password, confirm: vm.ui.form.confirm) { vm.closeForm("password") }
        await settled(vm)
        XCTAssertEqual(announced.value, [])
        XCTAssertEqual(vm.ui.form.password, "brandnew-pass-9")
    }

    /// A restore only counts once per screen life, and never over a sheet the agent has already touched.
    func testRestoreIfFreshAppliesOnce() async {
        let vm = await vm()
        vm.fillForm(me())
        vm.editForm { $0.name = "Moses M." }
        let saved = vm.saveUi()!
        let fresh = await self.vm()
        XCTAssertTrue(fresh.restoreIfFresh(saved))
        XCTAssertEqual(fresh.ui.form.name, "Moses M.")
        fresh.editForm { $0.name = "typed since" }
        XCTAssertFalse(fresh.restoreIfFresh(saved), "a second attach never replays the old copy")
        XCTAssertEqual(fresh.ui.form.name, "typed since")
        XCTAssertFalse(fresh.restoreIfFresh(nil))
    }
}
