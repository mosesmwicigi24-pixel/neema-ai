import Foundation
import XCTest
@testable import NeemaCore

/// DealsView's behaviour: the board's loads, approve / veto, and every deal patch (Android `DealsBehaviourTest`).
final class DealsBehaviourTests: DealsTestCase {
    func testLoadsOpenDealsWonCountAndThePendingQueue() async {
        let vm = await vm()
        XCTAssertEqual(Set(gets("/admin/deals").compactMap { $0 }), ["status=open", "status=won"])
        XCTAssertEqual(gets("/admin/actions"), ["status=pending"])
        XCTAssertEqual(vm.ui.deals?.map { $0.id }, ["d1", "d2", "d3", "d4"])
        XCTAssertEqual(vm.ui.wonCount, 2)
        XCTAssertEqual(ids(vm.ui.actions), ["x1", "x2"])
        XCTAssertNil(vm.ui.loadError)
    }

    func testFailedLoadsShowTheReasonNotAnEmptyBoard() async {
        fake.on("GET", "/admin/deals", code: 500, body: "{}")
        fake.on("GET", "/admin/actions", code: 500, body: "{}")
        let vm = await vm()
        // The web shows "Nothing queued" and empty columns; here the error state says why.
        XCTAssertNil(vm.ui.deals)
        XCTAssertNil(vm.ui.actions)
        XCTAssertEqual(vm.ui.loadError, "The server hit an error — try again")
    }

    func testSendAsDraftedPostsAnEmptyBodyAndReloads() async {
        let vm = await vm()
        let before = gets("/admin/actions").count
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(fake.bodies("POST", "/admin/actions/x1/approve"), [[:]])
        XCTAssertEqual(lastToast()?.message, "Sent ✓")
        XCTAssertEqual(gets("/admin/actions").count, before + 1)
        XCTAssertTrue(vm.ui.acting.isEmpty)
    }

    func testEditAndSendPostsTheEditedDraft() async {
        let vm = await vm()
        vm.act("x1", "approve", draft: "  Father, we deliver Friday 🙏  ")
        await drain()
        XCTAssertEqual(fake.bodies("POST", "/admin/actions/x1/approve"), [["draft": .string("Father, we deliver Friday 🙏")]])
    }

    func testEmptiedDraftLetsNeemaWriteIt() async {
        let vm = await vm()
        vm.act("x2", "approve", draft: "   ")
        await drain()
        XCTAssertEqual(fake.bodies("POST", "/admin/actions/x2/approve"), [[:]])
    }

    func testVetoPostsToVeto() async {
        let vm = await vm()
        vm.act("x2", "veto")
        await drain()
        XCTAssertEqual(fake.bodies("POST", "/admin/actions/x2/veto"), [[:]])
        XCTAssertEqual(lastToast()?.message, "Vetoed")
    }

    func testFailedApproveSaysWhich() async {
        fake.on("POST", "/admin/actions/.*/approve", code: 409, body: #"{"detail":"Action is sent"}"#)
        let vm = await vm()
        vm.act("x1", "approve")
        await drain()
        let t = lastToast()
        XCTAssertEqual(t?.type, .error)
        // A 409 "Action is sent" (crm.py approve_action): nothing went twice; the queue reloads.
        XCTAssertEqual(t?.message, "Already sent — nothing was sent twice")
        XCTAssertTrue(vm.ui.acting.isEmpty)
    }

    func testWonAndLostPatchStatusAndStage() async {
        let vm = await vm()
        vm.markWon("d1")
        vm.markLost("d2")
        await drain()
        XCTAssertEqual(fake.bodies("PATCH", "/admin/deals/d1"), [["status": .string("won"), "stage": .string("won")]])
        XCTAssertEqual(fake.bodies("PATCH", "/admin/deals/d2"), [["status": .string("lost"), "stage": .string("lost")]])
        XCTAssertEqual(Set(host.toasts.suffix(2).map { $0.message }), ["Marked won 🎉", "Marked lost"])
    }

    func testGuidanceEditorSavesOnlyGuidanceAndCloses() async {
        let vm = await vm()
        vm.startGuidance(vm.ui.deals!.first { $0.id == "d1" }!)
        XCTAssertEqual(vm.ui.editing, "d1")
        XCTAssertEqual(vm.ui.guidanceDraft, "Offer free delivery to Nyeri")
        vm.setGuidanceDraft(String(repeating: "x", count: 450))
        XCTAssertEqual(vm.ui.guidanceDraft.count, 400)
        vm.setGuidanceDraft("No discount on this one")
        vm.saveGuidance("d1")
        await drain()
        XCTAssertEqual(fake.bodies("PATCH", "/admin/deals/d1"), [["guidance": .string("No discount on this one")]])
        XCTAssertEqual(lastToast()?.message, "Guidance saved — Neema obeys it now")
        XCTAssertNil(vm.ui.editing)
    }

    func testCancelLeavesGuidanceUntouched() async {
        let vm = await vm()
        vm.startGuidance(vm.ui.deals!.first!)
        vm.cancelGuidance()
        XCTAssertNil(vm.ui.editing)
        XCTAssertFalse(fake.calls.contains { $0.method == "PATCH" })
    }

    func testFailedPatchToasts() async {
        fake.on("PATCH", "/admin/deals/.*", code: 404, body: #"{"detail":"Deal not found"}"#)
        let vm = await vm()
        vm.markWon("d1")
        await drain()
        XCTAssertEqual(lastToast()?.type, .error)
        XCTAssertEqual(lastToast()?.message, "This deal no longer exists — someone may have deleted it")
        fake.on("PATCH", "/admin/deals/.*", code: 500, body: "Internal Server Error")
        vm.markLost("d2")
        await drain()
        XCTAssertEqual(lastToast()?.message, "Update failed — the server hit an error — try again")
    }

    func testDueLabels() {
        let now = Fmt.millis("2026-09-25T12:00:00Z")!
        XCTAssertEqual(DealsRules.fmtDue(nil, now: now), "")
        XCTAssertEqual(DealsRules.fmtDue("2026-09-25T11:59:00Z", now: now), "due now")
        XCTAssertEqual(DealsRules.fmtDue("2026-09-25T12:00:20Z", now: now), "in 1m")
        XCTAssertEqual(DealsRules.fmtDue("2026-09-25T12:45:00Z", now: now), "in 45m")
        XCTAssertEqual(DealsRules.fmtDue("2026-09-25T17:30:00Z", now: now), "in 5h")
        XCTAssertEqual(DealsRules.fmtDue("2026-09-27T11:00:00Z", now: now), "in 47h")
        XCTAssertEqual(DealsRules.fmtDue("2026-09-28T13:00:00Z", now: now), "in 3d")
    }

    func testTheGuidanceAndTheDialogSurviveAReclaim() async {
        let a = await vm()
        let deal = a.ui.deals!.first { $0.id == "d2" }!
        a.startGuidance(deal); a.setGuidanceDraft("No discount — he is a regular")
        let action = a.ui.actions!.first { $0.id == "x1" }!
        a.openDraft(action); a.setDraftText("Father, both shirts go out Friday 🙏")
        let saved = JSONValue.parse(JSONValue.object(a.saveUi()).text)!.objectValue!
        let b = await vm()
        XCTAssertTrue(b.restoreIfFresh(saved))
        XCTAssertEqual(b.ui.editing, "d2")
        XCTAssertEqual(b.ui.guidanceDraft, "No discount — he is a regular")
        XCTAssertEqual(b.ui.draftFor?.id, "x1", "the dialog reopens on its action once the queue is read")
        XCTAssertEqual(b.ui.draftText, "Father, both shirts go out Friday 🙏")
        // A restored dialog whose action left the queue stays closed.
        let c = await vm()
        c.restoreUi(["draftFor": .string("x-gone"), "draftTextFor": .string("x-gone"), "draftText": .string("words")])
        XCTAssertNil(c.ui.draftFor)
        // Closing the dialog with back keeps the text.
        c.openDraft(action); c.setDraftText("my words")
        c.openDraft(nil)
        c.openDraft(action)
        XCTAssertEqual(c.ui.draftText, "my words")
    }
}
