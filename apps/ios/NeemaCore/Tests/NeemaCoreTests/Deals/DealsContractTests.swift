import Foundation
import XCTest
@testable import NeemaCore

/// Deals, planned actions and pipeline stages against crm.py's real handlers
/// (`list_deals`, `update_deal`, `list_actions`, `approve_action`,
/// `veto_action`, `get_pipeline_stages`) — Android `DealsContractTest`.
final class DealsContractTests: DealsTestCase {
    private var api: NeemaApi { host.api }

    // ── GET /admin/deals ────────────────────────────────────────────────────

    func testDealsListIsAnEnvelopeKeyedByStatus() async throws {
        let open = try await api.deals.list()
        XCTAssertEqual(fake.callsTo("GET", "/admin/deals").last?.query, "status=open")
        XCTAssertEqual(open.count, 4)
        let d1 = open[0]
        XCTAssertEqual(d1.customer, "Fr. Peter Kamau")
        XCTAssertEqual(d1.conversationId, "c1")
        // items_snapshot's price is the cart line's `price`, absent on Tier 2 lines → null.
        XCTAssertEqual(d1.items.count, 1)
        XCTAssertEqual(d1.items[0].qty, 2.0)
        XCTAssertNil(d1.items[0].price)
        XCTAssertEqual(d1.nextAction?.owner, "ai")
        XCTAssertNotNil(Fmt.millis(d1.nextAction?.dueAt))
        XCTAssertNotNil(Fmt.millis(d1.updatedAt))
        // A deal whose conversation is gone: customer "Unknown", no wa_id / channel.
        let d4 = open[3]
        XCTAssertNil(d4.conversationId); XCTAssertNil(d4.waId); XCTAssertNil(d4.channel)
        XCTAssertEqual(d4.customer, "Unknown")

        let won = try await api.deals.list(status: "won")
        XCTAssertEqual(fake.callsTo("GET", "/admin/deals").last?.query, "status=won")
        XCTAssertEqual(won.count, 2)
        // title / updated_at may be null.
        XCTAssertNil(won[1].title); XCTAssertNil(won[1].updatedAt)
    }

    func testDealWithEveryOptionalMissingOrNullDecodes() async throws {
        fake.on("GET", "/admin/deals", body: """
            {"deals":[{"id":"8c1e0f2a-1111-4222-8333-444455556666","customer":"Unknown",
            "items":[{"name":null,"qty":"1","price":"3500.00"}],"stage":"new","status":"open","next_action":null}]}
            """)
        let d = try await api.deals.list()[0]
        XCTAssertEqual(d.items[0].price, 3500.0) // Decimal-as-string
        XCTAssertNil(d.items[0].name)
        XCTAssertNil(d.nextAction); XCTAssertNil(d.guidance); XCTAssertNil(d.blocking); XCTAssertNil(d.updatedAt)
    }

    func testEmptyEnvelopeIsAnEmptyBoard() async throws {
        fake.on("GET", "/admin/deals", body: #"{"deals":[]}"#)
        let list = try await api.deals.list()
        XCTAssertTrue(list.isEmpty)
    }

    // ── PATCH /admin/deals/{id} ─────────────────────────────────────────────

    func testPatchSendsTheAcceptedFieldsAndReadsOk() async throws {
        let r = try await api.deals.patch(id: "d1", body: .object(["guidance": .string("No discount"), "stage": .string("proposal")]))
        XCTAssertTrue(r.ok)
        XCTAssertEqual(fake.bodies("PATCH", "/admin/deals/d1"), [["guidance": .string("No discount"), "stage": .string("proposal")]])
    }

    func testPatchWithABadIdToastsTheWebsCopy() async {
        fake.on("PATCH", "/admin/deals/.*", code: 422, body: #"{"detail":"Invalid deal id"}"#)
        let vm = await vm()
        vm.saveGuidance("not-a-uuid", guidance: "x")
        await drain()
        // The web's "Update failed", plus the server's reason.
        XCTAssertEqual(lastToast()?.message, "Update failed — invalid deal id")
        XCTAssertEqual(lastToast()?.type, .error)
    }

    // ── GET /admin/actions ──────────────────────────────────────────────────

    func testActionsQueueIsPendingByDefault() async throws {
        let list = try await api.actions.list()
        XCTAssertEqual(fake.callsTo("GET", "/admin/actions").last?.query, "status=pending")
        XCTAssertEqual(list.map { $0.status }, ["needs_approval", "planned"])
        XCTAssertEqual(list[0].createdBy, "ai")
        XCTAssertNotNil(Fmt.millis(list[0].dueAt))
        XCTAssertNil(list[1].draft)
    }

    // ── POST /admin/actions/{id}/approve | veto ─────────────────────────────

    func testApproveReadsTheSentEcho() async throws {
        let r = try await api.actions.approve(id: "x1", draft: "Father, Friday 🙏")
        XCTAssertTrue(r.ok)
        XCTAssertEqual(fake.bodies("POST", "/admin/actions/x1/approve"), [["draft": .string("Father, Friday 🙏")]])
    }

    func testApproveOfAnAlreadyResolvedActionSaysWhyAndDropsTheRow() async {
        let vm = await vm()
        let gets = fake.callsTo("GET", "/admin/actions").count
        // The scheduler sent it first: approve_action → 409 "Action is sent".
        fake.on("POST", "/admin/actions/.*/approve", code: 409, body: #"{"detail":"Action is sent"}"#)
        fake.on("GET", "/admin/actions", body: #"{"actions":[]}"#)
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(lastToast()?.message, "Already sent — nothing was sent twice")
        XCTAssertEqual(lastToast()?.type, .error)
        XCTAssertEqual(fake.callsTo("GET", "/admin/actions").count, gets + 1)
        XCTAssertEqual(vm.ui.actions, [])
        XCTAssertTrue(vm.ui.acting.isEmpty)
    }

    func testApproveWhenTheChatIsGoneSaysSo() async {
        let vm = await vm()
        fake.on("POST", "/admin/actions/.*/approve", code: 404, body: #"{"detail":"Conversation gone"}"#)
        vm.act("x2", "approve")
        await drain()
        XCTAssertEqual(lastToast()?.message, "This follow-up is gone — its conversation was deleted")
    }

    func testApproveServerCrashKeepsTheWebsToast() async {
        let vm = await vm()
        // An unhandled send failure is Starlette's plain-text 500, not JSON.
        fake.on("POST", "/admin/actions/.*/approve", code: 500, body: "Internal Server Error")
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(lastToast()?.message, "Couldn't send — the server hit an error — try again")
        // "Could not compose the message" is a JSON 500 meant for people: it is said.
        fake.on("POST", "/admin/actions/.*/approve", code: 500, body: #"{"detail":"Could not compose the message"}"#)
        vm.act("x2", "approve")
        await drain()
        XCTAssertEqual(lastToast()?.message, "Couldn't send — could not compose the message")
    }

    func testVetoPostsAnEmptyObjectAndReadsOk() async throws {
        let r = try await api.actions.veto(id: "x2")
        XCTAssertTrue(r.ok)
        XCTAssertEqual(fake.bodies("POST", "/admin/actions/x2/veto"), [[:]])
    }

    func testVetoOfAMissingActionSaysNotFound() async {
        let vm = await vm()
        fake.on("POST", "/admin/actions/.*/veto", code: 404, body: #"{"detail":"Action not found"}"#)
        vm.act("x2", "veto")
        await drain()
        XCTAssertEqual(lastToast()?.message, "This follow-up is gone — someone else removed it")
    }

    // ── GET /admin/settings/pipeline-stages ─────────────────────────────────

    func testPipelineStagesAreOperatorLabels() async throws {
        let labelled = try await api.settings.getPipelineStages()
        XCTAssertEqual(labelled, ["Measuring"])
        fake.on("GET", "/admin/settings/pipeline-stages", body: #"{"stages":[]}"#)
        let none = try await api.settings.getPipelineStages()
        XCTAssertEqual(none, [])
    }
}
