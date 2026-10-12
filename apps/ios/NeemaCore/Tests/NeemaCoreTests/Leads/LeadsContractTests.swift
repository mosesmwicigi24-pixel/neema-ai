import Foundation
import XCTest
@testable import NeemaCore

/// The Leads board against crm.py `list_leads` / `update_lead` (Android `LeadsContractTest`).
final class LeadsContractTests: LeadsTestCase {
    private func decode(_ s: String) -> [Lead] { try! NeemaJSON.decode([Lead].self, from: s) }

    // ── GET /admin/leads ────────────────────────────────────────────────────

    func testListIsABareArrayWithNoQuery() async throws {
        let leads = try await leadsApi.list()
        XCTAssertNil(fake.callsTo("GET", "/admin/leads").last?.query)
        XCTAssertEqual(leads.count, 8)
        let u1 = leads[0]
        XCTAssertEqual(u1.leadScore, 86)
        XCTAssertEqual(u1.totalSpent, 24500.0)
        XCTAssertEqual(u1.tier, "regular")
        XCTAssertEqual(u1.buyingRhythm?.daysSinceLast, 12.0)
        XCTAssertEqual(u1.buyingRhythm?.avgIntervalDays, 30.5)
        XCTAssertNotNil(Fmt.millis(u1.lastSeenAt))
        // No orders: Python's sum([]) is the int 0, and the rhythm is all nulls.
        let u2 = leads.first { $0.id == "u2" }!
        XCTAssertEqual(u2.totalSpent, 0.0)
        XCTAssertEqual(u2.tier, "prospect")
        XCTAssertNil(u2.buyingRhythm?.daysSinceLast); XCTAssertNil(u2.buyingRhythm?.cadenceLabel)
        // An Instagram handle is no phone: phone is null, the handle is the wa_id.
        let u4 = leads.first { $0.id == "u4" }!
        XCTAssertNil(u4.phone)
        XCTAssertEqual(u4.handle, "17840000000000001")
        // Never seen.
        XCTAssertNil(leads.first { $0.id == "u8" }!.lastSeenAt)
    }

    func testStageQueryIsNormalisedLikeTheServer() async throws {
        _ = try await leadsApi.list(stage: "Measuring")
        XCTAssertEqual(fake.callsTo("GET", "/admin/leads").last?.query, "stage=measuring")
        _ = try await leadsApi.list(stage: " Negotiating ")
        XCTAssertEqual(fake.callsTo("GET", "/admin/leads").last?.query, "stage=negotiation")
        XCTAssertEqual(Leads.normaliseStage(nil), "new")
        XCTAssertEqual(Leads.normaliseStage("  "), "")
    }

    func testDecimalsAndFloatScoresAndMissingKeysDecode() {
        let l = decode(#"[{"id":"0c7d0a3e-1d2b-4c5e-8f90-a1b2c3d4e5f6","wa_id":"254700000001","lead_stage":"new","lead_score":42.0,"total_spent":"18000.50","total_orders":1}]"#)[0]
        XCTAssertEqual(l.leadScore, 42)
        XCTAssertEqual(l.totalSpent, 18000.5)
        XCTAssertNil(l.buyingRhythm); XCTAssertNil(l.tier); XCTAssertNil(l.name); XCTAssertNil(l.notes)
        XCTAssertEqual(l.tags, []); XCTAssertEqual(l.channels, [])
    }

    func testTagsAsStoredNeverFailTheBoard() {
        // state["tags"] is written verbatim by PATCH /leads and PATCH /customers.
        let rows = decode("""
        [
          {"id":"a","wa_id":"1","tags":null},
          {"id":"b","wa_id":"2","tags":"vip, clergy"},
          {"id":"c","wa_id":"3","tags":["vip",5,null,{"x":1}," "]},
          {"id":"d","wa_id":"4","tags":{"odd":true}}
        ]
        """)
        XCTAssertEqual(rows.map { $0.tags }, [[], ["vip", "clergy"], ["vip", "5"], []])
    }

    func testAnExtraneousStageStillDecodesAndMatchesCaseInsensitively() {
        let l = decode(#"[{"id":"x","wa_id":"1","lead_stage":"measuring"}]"#)[0]
        XCTAssertEqual(l.leadStage, "measuring")
        XCTAssertTrue(LeadStage("Measuring", "Measuring", custom: true).matches(l.leadStage))
    }

    func testFailedLoadShowsTheServersReason() async {
        fake.on("GET", "/admin/leads", code: 500, body: #"{"detail":"database is down"}"#)
        let vm = await vm()
        XCTAssertTrue(vm.ui.leads.isEmpty)
        XCTAssertFalse(vm.ui.loading)
        // Shown in the board's error state (with Retry), not a toast.
        XCTAssertEqual(vm.ui.loadError, "database is down")
        XCTAssertTrue(host.toasts.isEmpty)
    }

    // ── PATCH /admin/leads/{id} ─────────────────────────────────────────────

    func testPatchKeysOnTheUserIdAndReadsOk() async throws {
        let r = try await leadsApi.update(id: "0c7d0a3e-1d2b-4c5e-8f90-a1b2c3d4e5f6", body: .object(["lead_stage": .string("Measuring")]))
        XCTAssertTrue(r.ok)
        XCTAssertEqual(fake.bodies("PATCH", "/admin/leads/0c7d0a3e-1d2b-4c5e-8f90-a1b2c3d4e5f6"), [["lead_stage": .string("Measuring")]])
    }

    func testUnchangedStageIsNeverSentSoTheAiStaysUnlocked() async {
        // update_lead sets lead_stage_source="manual" whenever lead_stage is in the
        // body — so a notes-only save must not carry the stage.
        let vm = await vm()
        let u1 = lead(vm, "u1")
        let edit = LeadsRules.diffLead(u1, stage: "Proposal", tagsText: u1.tags.joined(separator: ", "), notes: (u1.notes ?? "") + "\n\nCalled: wants 3 more.")
        vm.update(u1, stage: edit.stage, tags: edit.tags, notes: edit.notes, notesBase: edit.notesBase)
        await drain()
        let bodies = fake.bodies("PATCH", "/admin/leads/u1")
        XCTAssertEqual(bodies.count, 1)
        XCTAssertNil(bodies[0]["lead_stage"], "stage must not be sent")
        XCTAssertNil(bodies[0]["tags"], "tags must not be sent")
        XCTAssertEqual(bodies[0]["notes_base"]?.stringValue, u1.notes)
    }

    func testNotesSaveReReadsTheServersMergedNotes() async {
        // A server that merges like crm.py merge_notes: a call summary appended
        // while the operator typed survives their save, and the board shows it.
        let summary = "📞 Call summary: wants three more shirts."
        let stored = Ref("Buys for the whole parish. Prefers delivery on Fridays.\n\n\(summary)")
        func paras(_ s: String?) -> [String] { (s ?? "").components(separatedBy: "\n\n").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty } }
        fake.on("PATCH", "/admin/leads/u1") { _, body in
            let b = json(body ?? "{}")
            let base = paras(b["notes_base"]?.stringValue)
            let mine = paras(b["notes"]?.stringValue)
            let cur = paras(stored.value)
            stored.value = (mine + cur.filter { !base.contains($0) && !mine.contains($0) }).joined(separator: "\n\n")
            return (200, #"{"ok":true}"#)
        }
        fake.on("GET", "/admin/leads") { _, _ in
            (200, SalesFixtures.leadsJson([SalesFixtures.lead("u1", "254712345678", "Fr. Peter Kamau", "proposal", 86, spent: 24500.0, orders: 3, notes: stored.value)]))
        }
        let vm = await vm()
        let u1 = vm.ui.leads[0]
        // The operator opened the sheet before the summary landed: their base is the old text.
        var opened = u1
        opened.notes = "Buys for the whole parish. Prefers delivery on Fridays."
        let edit = LeadsRules.diffLead(opened, stage: "proposal", tagsText: "", notes: "Buys for the whole parish. Prefers delivery on Fridays.\n\nVIP pricing agreed.")
        vm.update(opened, stage: edit.stage, tags: edit.tags, notes: edit.notes, notesBase: edit.notesBase)
        await drain()
        XCTAssertEqual(lastToast()?.message, "Lead updated")
        XCTAssertEqual(vm.ui.leads[0].notes, "Buys for the whole parish. Prefers delivery on Fridays.\n\nVIP pricing agreed.\n\n\(summary)")
    }

    func testPatchNotFoundRemovesTheDeletedLead() async {
        fake.on("PATCH", "/admin/leads/.*", code: 404, body: #"{"detail":"Lead not found"}"#)
        let vm = await vm()
        vm.moveTo(lead(vm, "u2"), "won")
        await drain()
        XCTAssertEqual(lastToast()?.message, "This lead no longer exists — someone may have deleted or merged it")
        XCTAssertFalse(vm.ui.leads.contains { $0.id == "u2" })
    }

    func testPatchServerErrorRollsBack() async {
        fake.on("PATCH", "/admin/leads/.*", code: 500, body: #"{"detail":"database is down"}"#)
        let vm = await vm()
        vm.moveTo(lead(vm, "u2"), "won")
        await drain()
        XCTAssertEqual(lastToast()?.message, "Failed to update lead — database is down")
        XCTAssertEqual(lead(vm, "u2").leadStage, "qualified")
    }
}
