import Foundation
import XCTest
@testable import NeemaCore

/// The Profile screen's saves and loads on a bad phone network (Android `ProfileNetworkTest`).
final class ProfileNetworkTests: ProfileTestCase {

    // ── Load ─────────────────────────────────────────────────────────────────

    func testSignedInOfflineSaysWhyInsteadOfLoadingForeverThenRetryLoads() async {
        let f = Fixtures.withFixtures()
        TeamFixtures.install(f)
        f.failOffline("GET", "/admin/me")
        f.failOffline("GET", "/admin/agents")
        let d = TestHost(fake: f)
        hosts.append(d)
        let v = ProfileViewModel(host: d)
        vms.append(v)
        await drain()
        _ = await eventually(timeout: 5) { v.ui.loadError != nil }
        XCTAssertNil(d.me.value)
        XCTAssertEqual(v.ui.loadError, FriendlyErrors.OFFLINE_TEXT)
        f.on("GET", "/admin/me", body: TeamFixtures.me)
        f.on("GET", "/admin/agents", body: TeamFixtures.agents)
        v.refresh()
        await drain()
        _ = await eventually(timeout: 5) { d.me.value != nil && !v.ui.refreshing }
        XCTAssertEqual(d.me.value?.name, "Moses Mwicigi")
        XCTAssertNil(v.ui.loadError)
        XCTAssertFalse(v.ui.refreshing)
    }

    func testPullToRefreshFailingKeepsTheProfileAndSaysSo() async {
        let vm = await vm()
        fake.failTimeout("GET", "/admin/me")
        vm.refresh()
        await settled(vm)
        XCTAssertEqual(host.me.value?.name, "Moses Mwicigi")
        XCTAssertEqual(lastToast()?.message, "Couldn't refresh your profile. \(FriendlyErrors.TIMEOUT_TEXT)")
    }

    // ── Save profile ─────────────────────────────────────────────────────────

    func testSaveTimesOutButLandedCountsAsSaved() async {
        let vm = await vm()
        let f = fake!
        f.failTimeout("PATCH", "/admin/me") { _ in f.on("GET", "/admin/me", body: TeamFixtures.ormAgent(name: "Moses M.")) }
        vm.saveProfile(name: "Moses M.", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Profile updated")
    }

    func testSaveTimesOutNotLandedKeepsTheForm() async {
        let vm = await vm()
        fake.failTimeout("PATCH", "/admin/me")
        vm.saveProfile(name: "Moses M.", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, UNCERTAIN_SAVE)
        XCTAssertFalse(vm.ui.saving)
    }

    func testDuplicateEmailRace500SaysWhy() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/me", code: 500, body: "Internal Server Error")
        vm.saveProfile(name: "Moses", email: "someone.new@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "Failed to update profile — that email may already be in use")
        XCTAssertEqual(done, 0)
    }

    func testStatusesGetPlainWords() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/me", code: 429, body: "{}")
        vm.saveProfile(name: "Moses", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.BUSY_TEXT, "429")
        fake.htmlPage("PATCH", "/admin/me", code: 502)
        vm.saveProfile(name: "Moses", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.DOWN_TEXT, "502")
        fake.on("PATCH", "/admin/me", code: 422, body: #"{"detail":[{"msg":"value is not a valid email address"}]}"#)
        vm.saveProfile(name: "Moses", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, "value is not a valid email address", "422")
        XCTAssertEqual(done, 0)
    }

    func testDoubleTapOnSaveSendsOnce() async {
        let vm = await vm()
        let onDone = self.onDone
        fake.on("PATCH", "/admin/me") { _, _ in
            onMainSync { vm.saveProfile(name: "Moses M.", email: "moses@bethanyhouse.co.ke", onDone: onDone) }
            return (200, TeamFixtures.ormAgent(name: "Moses M."))
        }
        vm.saveProfile(name: "Moses M.", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(patches(), 1)
        XCTAssertEqual(done, 1)
    }

    // ── Password ─────────────────────────────────────────────────────────────

    func testPasswordTimeoutIsNeverCalledAFailureAndKeepsWhatWasTyped() async {
        let vm = await vm()
        fake.failTimeout("PATCH", "/admin/me")
        vm.changePassword(password: "n3wpassword!", confirm: "n3wpassword!", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, PASSWORD_UNCERTAIN)
        XCTAssertFalse(lastToast()!.message.contains("n3wpassword!"))
        // The same entry, tapped again, goes through.
        fake.on("PATCH", "/admin/me", body: TeamFixtures.me)
        vm.changePassword(password: "n3wpassword!", confirm: "n3wpassword!", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Password changed successfully")
    }

    func testPasswordErrorsNeverEchoThePassword() async {
        let vm = await vm()
        status("PATCH", "/admin/me", 422, "'correct-horse-9' is in a breach list")
        vm.changePassword(password: "correct-horse-9", confirm: "correct-horse-9", onDone: onDone)
        await settled(vm)
        let msg = lastToast()!.message
        XCTAssertFalse(msg.contains("correct-horse-9"), msg)
        XCTAssertEqual(done, 0)
    }

    func testPasswordOfflineSaysOffline() async {
        let vm = await vm()
        fake.failOffline("PATCH", "/admin/me")
        vm.changePassword(password: "n3wpassword!", confirm: "n3wpassword!", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.OFFLINE_TEXT)
        XCTAssertEqual(done, 0)
    }

    func testPasswordWithAnExpiredSessionDialogShowsAndTheEntryIsKeptForTheRetry() async {
        let vm = await vm()
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        fake.on("PATCH", "/admin/me", code: 401, body: #"{"detail":"Could not validate credentials"}"#)
        vm.changePassword(password: "n3wpassword!", confirm: "n3wpassword!", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(host.sessionExpired.value, "the session-expired dialog")
        XCTAssertEqual(lastToast()?.message, FriendlyErrors.EXPIRED_TEXT)
        XCTAssertEqual(done, 0, "the form stays open")
    }

    // ── Availability ─────────────────────────────────────────────────────────

    func testAvailabilityDoubleTapSendsOnce() async {
        let vm = await vm()
        let sent = Ref(0)
        fake.on("PATCH", "/admin/agents/[^/]+") { _, _ in
            sent.mutate { $0 += 1 }
            onMainSync { vm.setAvailable(agentId: Fixtures.ME_ID, available: true) }
            return (200, #"{"ok":true}"#)
        }
        vm.setAvailable(agentId: Fixtures.ME_ID, available: false)
        await settled(vm)
        XCTAssertEqual(sent.value, 1)
    }

    func testAvailabilityTimeoutShowsTheServersValue() async {
        let vm = await vm()
        fake.failTimeout("PATCH", "/admin/agents/[^/]+")
        vm.setAvailable(agentId: Fixtures.ME_ID, available: false)
        await settled(vm)
        XCTAssertNil(vm.ui.availableOverride, "no optimistic value left behind")
        XCTAssertEqual(lastToast()?.message, "Couldn't reach the server — availability unchanged")
        XCTAssertEqual(lastToast()?.type, .error)
    }
}
