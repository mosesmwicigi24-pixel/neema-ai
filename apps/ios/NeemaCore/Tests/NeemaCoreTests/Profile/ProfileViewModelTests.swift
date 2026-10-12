import Foundation
import XCTest
@testable import NeemaCore

/// ProfileView.tsx: PATCH /admin/me for name/email and password, plus the personal switches (Android `ProfileViewModelTest`).
final class ProfileViewModelTests: ProfileTestCase {
    override func install(_ f: FakeNeema) { TeamFixtures.writes(f) }

    func testSaveProfilePatchesMeAndRefetches() async {
        let vm = await vm()
        vm.saveProfile(name: " Moses M. ", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first.map(route), "PATCH /admin/me")
        XCTAssertEqual(w.first.flatMap(json), el(#"{"name":"Moses M.","email":"moses@bethanyhouse.co.ke"}"#))
        XCTAssertEqual(lastToast()?.message, "Profile updated")
        XCTAssertEqual(done, 1)
        _ = await eventually { self.called("GET", "/admin/me") && self.called("GET", "/admin/agents") }
        XCTAssertTrue(called("GET", "/admin/me"))
        XCTAssertTrue(called("GET", "/admin/agents"))
    }

    func testBlankNameIsNotSent() async {
        let vm = await vm()
        // The web would PATCH an empty name; the server stores it. Caught here instead.
        vm.saveProfile(name: "", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(lastToast()?.message, "Name and email required")
    }

    func testSaveProfileFailureKeepsEditing() async {
        let vm = await vm()
        // update_me has no error handling: a refused write is a bare 500.
        fake.on("PATCH", "/admin/me", code: 500, body: TeamFixtures.SERVER_ERROR)
        vm.saveProfile(name: "Moses", email: "moses.m@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, "Failed to update profile — that email may already be in use")
        XCTAssertEqual(lastToast()?.type, .error)
    }

    func testAnotherAgentsEmailIsCaughtBeforeTheServer500s() async {
        let vm = await vm()
        vm.saveProfile(name: "Moses", email: " Grace@BethanyHouse.co.ke ", onDone: onDone)
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(lastToast()?.message, "Another agent already uses that email")
        XCTAssertEqual(done, 0)
    }

    func testPasswordMatchIsCheckedBeforeLength() async {
        let vm = await vm()
        vm.changePassword(password: "abc", confirm: "abd", onDone: onDone)
        XCTAssertEqual(lastToast()?.message, "Passwords don't match")
        vm.changePassword(password: "abc", confirm: "abc", onDone: onDone)
        XCTAssertEqual(lastToast()?.message, "Password must be at least 8 characters")
        await settled(vm)
        XCTAssertTrue(writes().isEmpty)
        XCTAssertEqual(done, 0)
    }

    func testPasswordChangeSendsOnlyThePassword() async {
        let vm = await vm()
        vm.changePassword(password: "longpassword", confirm: "longpassword", onDone: onDone)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first.map(route), "PATCH /admin/me")
        XCTAssertEqual(w.first.flatMap(json), el(#"{"password":"longpassword"}"#))
        XCTAssertEqual(lastToast()?.message, "Password changed successfully")
        XCTAssertEqual(done, 1)
    }

    func testAvailabilityPatchesYourOwnRow() async {
        let vm = await vm()
        vm.setAvailable(agentId: Fixtures.ME_ID, available: false)
        XCTAssertEqual(vm.ui.availableOverride, false)
        await settled(vm)
        let w = writes()
        XCTAssertEqual(w.count, 1)
        XCTAssertEqual(w.first.map(route), "PATCH /admin/agents/\(Fixtures.ME_ID)")
        XCTAssertEqual(w.first.flatMap(json), el(#"{"is_available":false}"#))
        XCTAssertEqual(vm.ui.availableOverride, false)
        XCTAssertEqual(lastToast()?.message, "You're away")
        vm.reconcile(false)
        XCTAssertNil(vm.ui.availableOverride)
    }

    func testAvailabilityFailureReverts() async {
        let vm = await vm()
        fail("PATCH", "/admin/agents/.*", 500, "x")
        vm.setAvailable(agentId: Fixtures.ME_ID, available: false)
        await settled(vm)
        XCTAssertNil(vm.ui.availableOverride)
        XCTAssertEqual(lastToast()?.message, "Failed to update availability")
    }

    func testNotificationSwitchesStartAtTheWebDefaultsAndPersist() async {
        let vm = await vm()
        XCTAssertEqual(vm.ui.notifs, ["new_conv": true, "human_transfer": true, "order_updates": false, "daily_summary": true])
        vm.toggleNotif("order_updates")
        vm.toggleNotif("daily_summary")
        XCTAssertEqual(vm.ui.notifs["order_updates"], true)
        XCTAssertEqual(vm.ui.notifs["daily_summary"], false)
        // A fresh screen reads them back from the device.
        let again = await self.vm()
        XCTAssertEqual(again.ui.notifs["order_updates"], true)
        XCTAssertEqual(again.ui.notifs["daily_summary"], false)
        XCTAssertTrue(fake.calls.filter { $0.method != "GET" }.isEmpty, "notification switches never touch the API")
        XCTAssertEqual(NOTIF_PREFS.count, 4)
    }

    func testBackgroundSwitchIsADevicePreference() async {
        _ = await vm()
        let prefs = AppPrefs(store: host.prefs)
        let before = prefs.backgroundLive.value
        prefs.setBackgroundLive(!before)
        XCTAssertEqual(prefs.backgroundLive.value, !before)
        XCTAssertEqual(AppPrefs(store: host.prefs).backgroundLive.value, !before, "read back from the device")
        XCTAssertTrue(fake.calls.filter { $0.method != "GET" }.isEmpty)
    }

    // ── Replies: PATCH /admin/me answers with the agent object ──────────────

    func testSaveAcceptsTheAgentRowReply() async {
        let vm = await vm()
        // admin.py update_me returns the bare ORM agent (TeamFixtures.ormAgent, password_hash and all).
        vm.saveProfile(name: "Moses", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 1)
        XCTAssertEqual(lastToast()?.message, "Profile updated")
    }

    func testSaveAcceptsABareOk() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/me", body: #"{"ok":true}"#)
        vm.saveProfile(name: "Moses", email: "moses@bethanyhouse.co.ke", onDone: onDone)
        await settled(vm)
        vm.changePassword(password: "longpassword", confirm: "longpassword", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 2)
        XCTAssertEqual(lastToast()?.message, "Password changed successfully")
    }

    func testPasswordFailureShowsTheServersReason() async {
        let vm = await vm()
        status("PATCH", "/admin/me", 422, "Password too weak")
        vm.changePassword(password: "longpassword", confirm: "longpassword", onDone: onDone)
        await settled(vm)
        XCTAssertEqual(done, 0)
        XCTAssertEqual(lastToast()?.message, "Password too weak")
        XCTAssertEqual(lastToast()?.type, .error)
    }

    // ── Sounds & vibration: the mute words ───────────────────────────────────

    func testMuteStatusWords() {
        let zone = TimeZone(identifier: "Africa/Nairobi")!
        // The pinned clock is 09:00 UTC = noon in Nairobi, a Friday.
        let now = Int64(PINNED.timeIntervalSince1970 * 1000)
        let hour: Int64 = 3_600_000
        XCTAssertNil(muteStatus(until: 0, now: now, zone: zone))
        XCTAssertNil(muteStatus(until: now, now: now, zone: zone))
        XCTAssertEqual(muteStatus(until: now + hour, now: now, zone: zone), "Muted until 1:00 PM")
        XCTAssertEqual(muteStatus(until: now + 13 * hour, now: now, zone: zone), "Muted until tomorrow, 1:00 AM")
        XCTAssertEqual(muteStatus(until: now + 72 * hour, now: now, zone: zone), "Muted until Mon 28 Sep, 12:00 PM")
        XCTAssertEqual(muteStatus(until: AlertSettings.FOREVER, now: now, zone: zone), "Muted until you turn it back on")
        XCTAssertEqual(MUTE_CHOICES.map { $0.label }, ["1 hour", "8 hours", "Until I turn it back on"])
        XCTAssertEqual(MUTE_CHOICES.map { $0.ms }, [hour, 8 * hour, nil])
    }

    func testMuteForAndUnmuteFollowTheClock() {
        let prefs = AppPrefs(store: MemoryPrefs())
        let now = Int64(PINNED.timeIntervalSince1970 * 1000)
        prefs.muteFor(3_600_000, now: now)
        XCTAssertTrue(prefs.alerts.value.muted(now + 1))
        XCTAssertFalse(prefs.alerts.value.muted(now + 3_600_001))
        XCTAssertFalse(prefs.alerts.value.messageSoundAt(now + 1), "muted: no beep")
        prefs.muteFor(nil, now: now)
        XCTAssertEqual(prefs.alerts.value.mutedUntil, AlertSettings.FOREVER)
        prefs.unmute()
        XCTAssertFalse(prefs.alerts.value.muted(now))
        XCTAssertTrue(prefs.alerts.value.messageSoundAt(now))
    }
}
