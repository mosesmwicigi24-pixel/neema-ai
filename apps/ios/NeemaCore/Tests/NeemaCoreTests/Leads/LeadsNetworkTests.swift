import Foundation
import XCTest
@testable import NeemaCore

/// The Leads pipeline on a bad network (Android `LeadsNetworkTest`): the
/// board's loads, the optimistic stage move and its rollback, and the detail
/// sheet's save (with `notes_base`) — whose typed text must survive every failure.
final class LeadsNetworkTests: LeadsTestCase {
    // ── The board ───────────────────────────────────────────────────────────

    func testOfflineFirstLoadShowsWhyNotAnEmptyPipeline() async {
        fake.failOffline("GET", "/admin/leads")
        let vm = await vm()
        XCTAssertFalse(vm.ui.loading)
        XCTAssertTrue(vm.ui.leads.isEmpty)
        XCTAssertEqual(vm.ui.loadError, "No connection — check your internet and try again")
        XCTAssertTrue(errors.isEmpty, "the banner/error state says it, no toast")
        SalesFixtures.install(fake)
        vm.load()
        await drain()
        XCTAssertEqual(vm.ui.leads.count, 8)
        XCTAssertNil(vm.ui.loadError)
    }

    func testAFailedRefreshKeepsTheBoard() async {
        let vm = await vm()
        fake.failTimeout("GET", "/admin/leads")
        vm.refresh(); await drain()
        XCTAssertFalse(vm.ui.refreshing)
        XCTAssertEqual(vm.ui.leads.count, 8)
        XCTAssertEqual(vm.ui.loadError, "The server took too long to answer — try again")
        fake.htmlPage("GET", "/admin/leads", code: 502)
        vm.refresh(); await drain()
        XCTAssertEqual(vm.ui.loadError, "The server is unavailable right now — try again shortly")
        fake.on("GET", "/admin/leads", body: "[{\"id\":")
        vm.refresh(); await drain()
        XCTAssertEqual(vm.ui.loadError, "The server sent an answer the app couldn't read")
        XCTAssertEqual(vm.ui.leads.count, 8)
    }

    func testAQuietCatchUpThatFailsKeepsTheBoard() async {
        let vm = await vm()
        fake.failOffline("GET", "/admin/leads")
        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(5_000)
        XCTAssertEqual(vm.ui.leads.count, 8)
    }

    // ── Stage move: optimistic, rolled back ─────────────────────────────────

    func testOfflineMoveRollsBackOnlyThatLead() async {
        let vm = await vm()
        let other = lead(vm, "u1")
        fake.failOffline("PATCH", "/admin/leads/u3")
        let reads = gets()
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertEqual(lead(vm, "u3").leadStage, "new")
        XCTAssertEqual(lead(vm, "u1"), other)
        XCTAssertEqual(errors.last, "Failed to update lead — no connection — check your internet and try again")
        XCTAssertEqual(gets(), reads, "nothing reached the server: no reload")
        XCTAssertTrue(vm.ui.saving.isEmpty)
    }

    func testAnHtmlErrorIsNeverShownRaw() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/leads/u3", code: 500, body: "<html><body><h1>500 Internal Server Error</h1></body></html>")
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertEqual(errors.last, "Failed to update lead — the server hit an error — try again")
        XCTAssertEqual(lead(vm, "u3").leadStage, "new")
    }

    func testATimedOutMoveThatLandedStays() async {
        let vm = await vm()
        let fake = self.fake!
        let landed = boardWith("u3") { $0.replacingOccurrences(of: "\"lead_stage\":\"new\"", with: "\"lead_stage\":\"contacted\"") }
        fake.failTimeout("PATCH", "/admin/leads/u3") { _ in fake.on("GET", "/admin/leads", body: landed) }
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertEqual(lead(vm, "u3").leadStage, "contacted")
        XCTAssertEqual(lastToast()?.message, "Lead updated")
        XCTAssertTrue(errors.isEmpty)
    }

    func testATimedOutMoveThatDidNotLandShowsTheTruth() async {
        let vm = await vm()
        fake.failTimeout("PATCH", "/admin/leads/u3")
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertEqual(lead(vm, "u3").leadStage, "new")
        XCTAssertEqual(errors.last, "Lead not updated — the server took too long to answer — try again")
    }

    func testALostAnswerWithNoWayToCheckRollsBackAndSaysSo() async {
        let vm = await vm()
        fake.failDropped("PATCH", "/admin/leads/u3")
        fake.failOffline("GET", "/admin/leads")
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertEqual(lead(vm, "u3").leadStage, "new")
        XCTAssertEqual(errors.last, "No answer from the server — the lead may not have changed. Pull down to check.")
    }

    func testADeletedLeadLeavesTheBoard() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/leads/u3", code: 404, body: #"{"detail":"Lead not found"}"#)
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertFalse(vm.ui.leads.contains { $0.id == "u3" })
        XCTAssertEqual(errors.last, "This lead no longer exists — someone may have deleted or merged it")
    }

    func testASecondMoveWhileTheFirstIsInFlightIsIgnored() async {
        let box = Ref<LeadsViewModel?>(nil)
        fake.on("PATCH", "/admin/leads/u3") { _, _ in
            onMainSync { if let vm = box.value { vm.moveTo(vm.ui.leads.first { $0.id == "u3" }!, "qualified") } }
            return (200, #"{"ok":true}"#)
        }
        let vm = await vm()
        box.value = vm
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertEqual(fake.callsTo("PATCH", "/admin/leads/u3").count, 1)
        XCTAssertEqual(lead(vm, "u3").leadStage, "contacted")
    }

    func testADeadSessionRollsBackQuietly() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/leads/u3", code: 401, body: "{}")
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertTrue(host.sessionExpired.value)
        XCTAssertEqual(lead(vm, "u3").leadStage, "new")
        XCTAssertTrue(errors.isEmpty)
    }

    // ── The detail sheet ────────────────────────────────────────────────────

    private func typed(_ vm: LeadsViewModel) -> (Lead, LeadEdit) {
        let u1 = lead(vm, "u1")
        vm.select("u1")
        return (u1, LeadsRules.diffLead(u1, stage: "negotiation", tagsText: "vip, clergy", notes: "Buys for the whole parish. Prefers delivery on Fridays.\n\nWants 40 stoles by Easter."))
    }

    func testAnOfflineSaveKeepsTheSheetOpenWithTheReason() async {
        let vm = await vm()
        let (u1, edit) = typed(vm)
        fake.failOffline("PATCH", "/admin/leads/u1")
        vm.save(u1, edit)
        await drain()
        XCTAssertEqual(vm.ui.selectedId, "u1", "the sheet stays open — its fields keep what was typed")
        XCTAssertEqual(vm.ui.sheetError, "Couldn't save — no connection — check your internet and try again")
        XCTAssertEqual(lead(vm, "u1"), u1, "the board didn't pretend")
        XCTAssertTrue(vm.ui.saving.isEmpty)
        // Back online: the same edit saves and the sheet closes.
        SalesFixtures.install(fake)
        vm.save(u1, edit)
        await drain()
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertNil(vm.ui.sheetError)
        XCTAssertEqual(lastToast()?.message, "Lead updated")
        XCTAssertEqual(json(fake.callsTo("PATCH", "/admin/leads/u1").last?.body ?? ""), [
            "lead_stage": .string("negotiation"), "tags": .array([.string("vip"), .string("clergy")]),
            "notes": .string("Buys for the whole parish. Prefers delivery on Fridays.\n\nWants 40 stoles by Easter."),
            "notes_base": .string("Buys for the whole parish. Prefers delivery on Fridays."),
        ])
    }

    func testASaveThatTimedOutButLandedClosesTheSheet() async {
        let vm = await vm()
        let (u1, edit) = typed(vm)
        let fake = self.fake!
        // The server merged: our paragraphs plus a call summary appended meanwhile.
        let landed = boardWith("u1") {
            $0.replacingOccurrences(of: "\"lead_stage\":\"proposal\"", with: "\"lead_stage\":\"negotiation\"")
                .replacingOccurrences(of: "\"tags\":\\[[^\\]]*\\]", with: "\"tags\":[\"vip\",\"clergy\"]", options: .regularExpression)
                .replacingOccurrences(of: "Prefers delivery on Fridays.\"", with: "Prefers delivery on Fridays.\\n\\nWants 40 stoles by Easter.\\n\\nCall: confirmed Nyeri address.\"")
        }
        fake.failTimeout("PATCH", "/admin/leads/u1") { _ in fake.on("GET", "/admin/leads", body: landed) }
        vm.save(u1, edit)
        await drain()
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertEqual(lastToast()?.message, "Lead updated")
        XCTAssertTrue(lead(vm, "u1").notes?.hasSuffix("Call: confirmed Nyeri address.") == true)
    }

    func testASaveThatTimedOutAndDidNotLandStaysOpen() async {
        let vm = await vm()
        let (u1, edit) = typed(vm)
        fake.failTimeout("PATCH", "/admin/leads/u1")
        vm.save(u1, edit)
        await drain()
        XCTAssertEqual(vm.ui.selectedId, "u1")
        XCTAssertEqual(vm.ui.sheetError, "Not saved — the server took too long to answer — try again")
    }

    func testASaveWithNoWayToCheckSaysSaveAgain() async {
        let vm = await vm()
        let (u1, edit) = typed(vm)
        fake.failDropped("PATCH", "/admin/leads/u1")
        fake.failOffline("GET", "/admin/leads")
        vm.save(u1, edit)
        await drain()
        XCTAssertEqual(vm.ui.selectedId, "u1")
        XCTAssertEqual(vm.ui.sheetError, "No answer from the server — your changes may not have saved. Save again to be sure.")
    }

    func testASaveForADeletedLeadClosesTheSheetAndSaysSo() async {
        let vm = await vm()
        let (u1, edit) = typed(vm)
        fake.on("PATCH", "/admin/leads/u1", code: 404, body: #"{"detail":"Lead not found"}"#)
        vm.save(u1, edit)
        await drain()
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertFalse(vm.ui.leads.contains { $0.id == "u1" })
        XCTAssertEqual(errors.last, "This lead no longer exists — someone may have deleted or merged it")
    }

    func testASaveWhenTheSessionDiedKeepsTheSheetForAfterSignIn() async {
        let vm = await vm()
        let (u1, edit) = typed(vm)
        fake.on("PATCH", "/admin/leads/u1", code: 401, body: "{}")
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        vm.save(u1, edit)
        await drain()
        XCTAssertTrue(host.sessionExpired.value)
        XCTAssertEqual(vm.ui.selectedId, "u1")
        XCTAssertEqual(vm.ui.sheetError, "Your session expired — sign in again, then save.")
    }

    func testASaveRescuedByATokenRefreshJustSaves() async {
        let vm = await vm()
        let (u1, edit) = typed(vm)
        fake.expiredOnce("PATCH", "/admin/leads/u1") { (200, #"{"ok":true}"#) }
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ in (200, Fixtures.tokenResponse(access: fakeJwt() + "r")) }
        vm.save(u1, edit)
        await drain()
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertEqual(lastToast()?.message, "Lead updated")
        XCTAssertFalse(host.sessionExpired.value)
    }

    func testASecondSaveTapWhileSavingSendsNothing() async {
        let box = Ref<(LeadsViewModel, Lead, LeadEdit)?>(nil)
        fake.on("PATCH", "/admin/leads/u1") { _, _ in
            onMainSync { if let (vm, u1, edit) = box.value { vm.save(u1, edit); vm.moveTo(u1, "won") } }
            return (200, #"{"ok":true}"#)
        }
        let vm = await vm()
        let (u1, edit) = typed(vm)
        box.value = (vm, u1, edit)
        vm.save(u1, edit)
        await drain()
        XCTAssertEqual(fake.callsTo("PATCH", "/admin/leads/u1").count, 1)
    }

    func testAnUntouchedSheetClosesWithoutARequest() async {
        let vm = await vm()
        vm.select("u2")
        vm.save(lead(vm, "u2"), LeadEdit())
        await drain()
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertTrue(fake.callsTo("PATCH", "/admin/leads/u2").isEmpty)
    }

    // ── editLanded ──────────────────────────────────────────────────────────

    func testEditLandedReadsTheMergedNotes() {
        let base = Lead(id: "u", leadStage: "new", tags: ["x"], notes: "A\n\nB")
        let edit = LeadEdit(stage: "qualified", notes: "A\n\nC", notesBase: "A\n\nB")
        var landed = base; landed.leadStage = "Qualified"; landed.notes = "A\n\nC\n\nD (appended)"
        XCTAssertTrue(LeadsRules.editLanded(edit, landed))
        var kept = base; kept.leadStage = "qualified"; kept.notes = "A\n\nB\n\nC"
        XCTAssertFalse(LeadsRules.editLanded(edit, kept), "B was deleted on purpose")
        var stageless = base; stageless.notes = "A\n\nC"
        XCTAssertFalse(LeadsRules.editLanded(edit, stageless))
        XCTAssertFalse(LeadsRules.editLanded(LeadEdit(tags: ["y"]), base))
        XCTAssertTrue(LeadsRules.editLanded(LeadEdit(tags: ["x"]), base))
    }
}
