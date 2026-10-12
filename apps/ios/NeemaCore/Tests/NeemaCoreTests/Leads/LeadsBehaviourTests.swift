import Foundation
import XCTest
@testable import NeemaCore

/// LeadsView's behaviour: stage moves, detail saves, search / filter, custom stages (Android `LeadsBehaviourTest`).
final class LeadsBehaviourTests: LeadsTestCase {
    private func make(_ id: String = "u1", stage: String = "proposal", notes: String? = "Buys for the parish.", tags: [String] = ["vip"]) -> Lead {
        Lead(id: id, waId: "254712345678", name: "Fr. Peter Kamau", leadStage: stage, tags: tags, notes: notes)
    }

    func testLoadsLeadsAndTheOperatorsStages() async {
        let vm = await vm()
        XCTAssertEqual(vm.ui.leads.count, 8)
        XCTAssertFalse(vm.ui.loading)
        XCTAssertEqual(vm.ui.stages.map { $0.id }, ["new", "contacted", "qualified", "proposal", "negotiation", "Measuring", "won", "lost"])
        XCTAssertTrue(vm.ui.stages[5].custom)
    }

    func testCustomStagesSitBetweenNegotiatingAndWon() {
        XCTAssertEqual(LeadsRules.buildStages([]), LeadsRules.BASE_STAGES)
        XCTAssertEqual(LeadsRules.buildStages(["measuring", " ", "fitting"]).map { $0.id },
                       ["new", "contacted", "qualified", "proposal", "negotiation", "measuring", "fitting", "won", "lost"])
        // Never a built-in id twice, never a repeat.
        XCTAssertEqual(LeadsRules.buildStages(["won", "fitting", "fitting"]).map { $0.id },
                       ["new", "contacted", "qualified", "proposal", "negotiation", "fitting", "won", "lost"])
    }

    func testStageMoveSendsOnlyTheStageAndMovesTheCardAtOnce() async {
        let vm = await vm()
        vm.moveTo(lead(vm, "u3"), "contacted")
        XCTAssertEqual(lead(vm, "u3").leadStage, "contacted", "optimistic: the card moves before the answer")
        await drain()
        XCTAssertEqual(fake.bodies("PATCH", "/admin/leads/u3"), [["lead_stage": .string("contacted")]])
        XCTAssertEqual(lead(vm, "u3").leadStage, "contacted")
        XCTAssertEqual(lastToast()?.message, "Lead updated")
    }

    func testFailedSaveToastsAndRollsBackThatLead() async {
        fake.on("PATCH", "/admin/leads/.*", code: 422, body: #"{"detail":"Invalid stage"}"#)
        let vm = await vm()
        vm.moveTo(lead(vm, "u3"), "contacted")
        await drain()
        XCTAssertEqual(lastToast()?.type, .error)
        XCTAssertEqual(lastToast()?.message, "Failed to update lead — invalid stage")
        // Rolled back in place: no reload that could empty the board offline.
        XCTAssertEqual(lead(vm, "u3").leadStage, "new")
        XCTAssertEqual(vm.ui.leads.count, 8)
    }

    func testUntouchedSheetSendsNothing() {
        let e = LeadsRules.diffLead(make(), stage: "proposal", tagsText: "vip", notes: "Buys for the parish.")
        XCTAssertTrue(e.isEmpty)
        // Case and spacing of the stage / tags don't count as changes.
        XCTAssertTrue(LeadsRules.diffLead(make(stage: "Proposal"), stage: "proposal", tagsText: " vip , ", notes: "Buys for the parish.").isEmpty)
    }

    func testSheetSendsOnlyChangedFields() {
        let stageOnly = LeadsRules.diffLead(make(), stage: "won", tagsText: "vip", notes: "Buys for the parish.")
        XCTAssertEqual(stageOnly.stage, "won"); XCTAssertNil(stageOnly.tags); XCTAssertNil(stageOnly.notes)

        let tagsOnly = LeadsRules.diffLead(make(), stage: "proposal", tagsText: "vip, clergy,,  nyeri ", notes: "Buys for the parish.")
        XCTAssertNil(tagsOnly.stage); XCTAssertEqual(tagsOnly.tags, ["vip", "clergy", "nyeri"])

        let notes = LeadsRules.diffLead(make(), stage: "proposal", tagsText: "vip", notes: "Buys for the parish. Wants Friday delivery.")
        XCTAssertEqual(notes.notes, "Buys for the parish. Wants Friday delivery.")
        XCTAssertEqual(notes.notesBase, "Buys for the parish.")

        let cleared = LeadsRules.diffLead(make(), stage: "proposal", tagsText: "", notes: "")
        XCTAssertEqual(cleared.tags, [])
        XCTAssertEqual(cleared.notes, "")
    }

    func testNotesSaveCarriesTheBaseItStartedFrom() async {
        let vm = await vm()
        let u1 = lead(vm, "u1")
        let edit = LeadsRules.diffLead(u1, stage: "proposal", tagsText: u1.tags.joined(separator: ", "), notes: "New note")
        vm.update(u1, stage: edit.stage, tags: edit.tags, notes: edit.notes, notesBase: edit.notesBase)
        await drain()
        XCTAssertEqual(fake.bodies("PATCH", "/admin/leads/u1"),
                       [["notes": .string("New note"), "notes_base": .string("Buys for the whole parish. Prefers delivery on Fridays.")]])
        // The fixture server stored nothing, so the quiet re-read shows its notes again.
        XCTAssertEqual(gets(), 2)
        XCTAssertEqual(lead(vm, "u1").notes, "Buys for the whole parish. Prefers delivery on Fridays.")
    }

    func testFirstNoteHasAnEmptyBase() async {
        let vm = await vm()
        let u2 = lead(vm, "u2")
        let edit = LeadsRules.diffLead(u2, stage: "qualified", tagsText: "", notes: "Asked for the purple cassock")
        vm.update(u2, stage: edit.stage, tags: edit.tags, notes: edit.notes, notesBase: edit.notesBase)
        await drain()
        XCTAssertEqual(fake.bodies("PATCH", "/admin/leads/u2"), [["notes": .string("Asked for the purple cassock"), "notes_base": .string("")]])
    }

    func testStageAndTagsTogether() async {
        let vm = await vm()
        let u4 = lead(vm, "u4")
        let edit = LeadsRules.diffLead(u4, stage: "qualified", tagsText: "convent, bulk", notes: "")
        vm.update(u4, stage: edit.stage, tags: edit.tags, notes: edit.notes, notesBase: edit.notesBase)
        await drain()
        XCTAssertEqual(fake.bodies("PATCH", "/admin/leads/u4"), [["lead_stage": .string("qualified"), "tags": .array([.string("convent"), .string("bulk")])]])
    }

    func testParseTagsLikeTheWeb() { XCTAssertEqual(Leads.parseTags(" a,b c ,, d,"), ["a", "b c", "d"]) }

    func testSearchAndFilter() async {
        let all = (await vm()).ui.leads
        XCTAssertEqual(LeadsRules.filterLeads(all, filterStage: "proposal", search: "").map { $0.id }, ["u1"])
        XCTAssertEqual(LeadsRules.filterLeads(all, filterStage: "all", search: "achieng").map { $0.id }, ["u2"])
        XCTAssertEqual(LeadsRules.filterLeads(all, filterStage: "all", search: "ACKNYERI").map { $0.id }, ["u1"]) // email
        XCTAssertEqual(LeadsRules.filterLeads(all, filterStage: "all", search: "nyeri").map { $0.id }, ["u1"]) // location
        XCTAssertEqual(LeadsRules.filterLeads(all, filterStage: "all", search: "2557543").map { $0.id }, ["u3"]) // nameless: by wa_id
        XCTAssertEqual(LeadsRules.filterLeads(all, filterStage: "Measuring", search: "").map { $0.id }, ["u6"])
        XCTAssertEqual(LeadsRules.filterLeads(all, filterStage: "won", search: "achieng").map { $0.id }, [])
        XCTAssertEqual(LeadsRules.filterLeads(all, filterStage: "all", search: "").count, 8)
    }
}
