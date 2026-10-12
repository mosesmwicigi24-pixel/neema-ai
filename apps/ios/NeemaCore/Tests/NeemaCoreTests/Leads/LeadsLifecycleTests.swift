import Foundation
import XCTest
@testable import NeemaCore

/// Lifecycle and state (the leads part of Android `SalesLifecycleTest`): a
/// sheet half-typed survives the app being reclaimed with its base, a swipe
/// keeps what was typed while Cancel throws it away, a save closes its draft.
final class LeadsLifecycleTests: LeadsTestCase {
    func testLeadSheetDraftSurvivesAReclaimWithItsBase() async {
        let a = await vm()
        let lead = lead(a, "u1")
        a.setFilterStage("proposal"); a.setSearch("peter")
        a.select(lead.id)
        var draft = a.sheetFor(lead)
        draft.notes += "\n\nCall after Mass on Sunday."; draft.tags = "vip, clergy"; draft.stage = "negotiation"
        a.editSheet(draft)
        let saved = JSONValue.parse(JSONValue.object(a.saveUi()).text)!.objectValue!
        let b = await vm()
        XCTAssertTrue(b.restoreIfFresh(saved))
        XCTAssertEqual(b.ui.filterStage, "proposal")
        XCTAssertEqual(b.ui.search, "peter")
        XCTAssertEqual(b.ui.selectedId, "u1")
        let back = b.ui.sheet!
        XCTAssertEqual(back, a.ui.sheet)
        // The restored sheet still diffs against the lead as it first opened.
        let edit = back.edit()
        XCTAssertEqual(edit.stage, "negotiation")
        XCTAssertEqual(edit.tags, ["vip", "clergy"])
        XCTAssertEqual(edit.notesBase, lead.notes)
    }

    func testSwipingTheSheetAwayKeepsWhatWasTypedCancelThrowsItAway() async {
        let vm = await vm()
        let lead = lead(vm, "u2")
        vm.select(lead.id)
        var d = vm.sheetFor(lead); d.notes = "Half a thought"
        vm.editSheet(d)
        vm.dismissSheet()                               // back / swipe / scrim
        XCTAssertNil(vm.ui.selectedId)
        vm.select(lead.id)
        XCTAssertEqual(vm.sheetFor(lead).notes, "Half a thought", "reopening shows it as typed")

        vm.select(nil)                                  // Cancel / close
        vm.select(lead.id)
        XCTAssertEqual(vm.sheetFor(lead).notes, lead.notes ?? "", "Cancel starts over from the lead")

        // Another lead never shows the first one's leftovers.
        var e = vm.sheetFor(lead); e.notes = "for u2"
        vm.editSheet(e)
        vm.dismissSheet()
        let other = self.lead(vm, "u5")
        vm.select(other.id)
        XCTAssertEqual(vm.sheetFor(other).notes, other.notes ?? "")
    }

    func testASavedSheetSendsOnlyWhatChangedAndClosesItsDraft() async {
        let vm = await vm()
        let lead = lead(vm, "u1")
        vm.select(lead.id)
        var d = vm.sheetFor(lead); d.tags = "vip"
        vm.editSheet(d)
        vm.save(lead, vm.ui.sheet!.edit())
        await drain()
        let body = fake.bodies("PATCH", "/admin/leads/u1").last!
        XCTAssertEqual(Set(body.keys), ["tags"])
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertNil(vm.ui.sheet, "the typed draft goes once the server has it")
    }

    func testAnEditForALeadThatIsNotOpenIsIgnored() async {
        let vm = await vm()
        let lead = vm.ui.leads[0]
        vm.editSheet(LeadSheetDraft.of(lead, vm.ui.stages))
        XCTAssertNil(vm.ui.sheet)
    }

    /// Restored after a reclaim, an open lead waits for the board before it can be called gone.
    func testARestoredOpenLeadWaitsForTheBoard() async {
        fake.on("GET", "/admin/leads", code: 500, body: "{}")
        let vm = await vm()
        vm.restoreUi(["selected": .string("u1")])
        XCTAssertTrue(vm.ui.leads.isEmpty)
        XCTAssertTrue(vm.loaded, "read (and failed): the screen may decide")
        XCTAssertEqual(vm.ui.selectedId, "u1")
    }
}
