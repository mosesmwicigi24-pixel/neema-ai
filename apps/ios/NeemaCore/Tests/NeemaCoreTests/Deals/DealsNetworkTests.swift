import Foundation
import XCTest
@testable import NeemaCore

/// The Deals board and Neema's action queue on a bad network (Android
/// `DealsNetworkTest`): every load and every action under offline, timeout,
/// lost answers, 401/404/409/429/5xx, HTML pages, garbage bodies, double
/// taps and leaving mid-request.
///
/// The one rule above all: a follow-up is words in front of a customer — it
/// must never be sent twice, and never be called "failed" when it went.
final class DealsNetworkTests: DealsTestCase {
    var server: QueueServer!

    override func setUp() async throws {
        try await super.setUp()
        server = QueueServer(fake)
    }

    private func posts(_ id: String) -> [FakeNeema.Call] { fake.callsTo("POST", "/admin/actions/\(id)/approve") }
    private func noRawHtml() { for t in host.toasts { XCTAssertFalse(t.message.contains("<"), t.message) } }
    private var dealsOpen: String { SalesFixtures.deals }

    /// GET /admin/deals answering `open` for the board and the won fixture for the count.
    private func serveDeals(_ open: String) {
        fake.on("GET", "/admin/deals") { r, _ in (200, r.param("status") == "won" ? SalesFixtures.wonDeals : open) }
    }

    // ── Approve: the answer is lost ─────────────────────────────────────────

    func testApproveThatTimesOutButWentIsSentNotFailed() async {
        server.install()
        let s = server!
        fake.failTimeout("POST", "/admin/actions/x1/approve") { _ in _ = s.approve("x1") }
        let vm = await vm()
        vm.act("x1", "approve")
        await drain()
        // The first re-read already shows x1 gone: it went.
        XCTAssertEqual(server.sent, ["x1"])
        XCTAssertEqual(lastToast()?.message, "Sent ✓")
        XCTAssertTrue(errors.isEmpty)
        XCTAssertTrue(vm.ui.acting.isEmpty && vm.ui.checking.isEmpty)
        XCTAssertFalse(ids(vm.ui.actions).contains("x1"))
    }

    func testWhileSettlingTheRowStaysLockedSoASecondTapCannotSendTwice() async {
        server.install()
        // The request reached the server and is still composing when the client gives up.
        fake.failTimeout("POST", "/admin/actions/x1/approve")
        let vm = await vm()
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(vm.ui.checking, ["x1"])
        XCTAssertEqual(lastToast()?.type, .info)
        XCTAssertTrue(lastToast()?.message.hasPrefix("No answer from the server — checking whether it was sent") == true)

        // Impatient taps while it is being settled: nothing goes out.
        vm.act("x1", "approve"); vm.act("x1", "approve", draft: "edited"); vm.act("x1", "veto")
        await drain()
        XCTAssertEqual(posts("x1").count, 1)
        XCTAssertTrue(fake.callsTo("POST", "/admin/actions/x1/veto").isEmpty)

        // Meanwhile the server finishes: the next re-read sees it gone.
        _ = server.approve("x1")
        await advance(DealsViewModel.SETTLE_MS)
        XCTAssertEqual(lastToast()?.message, "Sent ✓")
        XCTAssertTrue(vm.ui.acting.isEmpty)
        XCTAssertEqual(server.sent, ["x1"])
    }

    func testASendThatNeverLandsIsReleasedAfterSettlingAndSaysSo() async {
        server.install()
        fake.failTimeout("POST", "/admin/actions/x1/approve")
        let vm = await vm()
        vm.act("x1", "approve")
        await drain()
        await advance(DealsViewModel.SETTLE_MS * Int64(DealsViewModel.SETTLE_READS))
        XCTAssertEqual(errors.last, "Not sent — the server never confirmed it. You can send it again.")
        XCTAssertTrue(vm.ui.acting.isEmpty && vm.ui.checking.isEmpty)
        // Now a deliberate retry goes through, once.
        server.install()
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(server.sent, ["x1"])
        XCTAssertEqual(lastToast()?.message, "Sent ✓")
    }

    func testWhenTheQueueCannotBeReadEitherItSaysCheckTheChat() async {
        server.install()
        fake.failTimeout("POST", "/admin/actions/x1/approve")
        let vm = await vm()
        fake.failOffline("GET", "/admin/actions")
        vm.act("x1", "approve")
        await drain()
        await advance(DealsViewModel.SETTLE_MS * Int64(DealsViewModel.SETTLE_READS))
        XCTAssertEqual(errors.last, "Couldn't confirm whether it was sent — the server can't be reached. Open the chat to see whether it went before sending again.")
        XCTAssertTrue(vm.ui.acting.isEmpty)
    }

    func testADroppedConnectionInTheDialogClosesItOnceItIsKnownToHaveGone() async {
        server.install()
        let s = server!
        fake.failDropped("POST", "/admin/actions/x2/approve") { _ in _ = s.approve("x2") }
        let vm = await vm()
        vm.openDraft(vm.ui.actions!.first { $0.id == "x2" })
        vm.setDraftText("Habari Deacon James — did choir practice go well? 🙏")
        vm.act("x2", "approve", draft: vm.ui.draftText)
        await drain()
        XCTAssertNil(vm.ui.draftFor)
        XCTAssertEqual(vm.ui.draftText, "")
        XCTAssertEqual(lastToast()?.message, "Sent ✓")
        XCTAssertEqual(server.sent, ["x2"])
    }

    func testA502PageIsNeverShownAndIsSettledLikeATimeout() async {
        server.install()
        fake.htmlPage("POST", "/admin/actions/x1/approve", code: 502)
        let vm = await vm()
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(vm.ui.checking, ["x1"])
        await advance(DealsViewModel.SETTLE_MS * Int64(DealsViewModel.SETTLE_READS))
        XCTAssertEqual(errors.last, "Not sent — the server never confirmed it. You can send it again.")
        noRawHtml()
    }

    // ── Approve: the answer says no ─────────────────────────────────────────

    func testOfflineSendKeepsTheDialogAndEveryWordTyped() async {
        server.install()
        fake.failOffline("POST", "/admin/actions/x1/approve")
        let vm = await vm()
        vm.openDraft(vm.ui.actions!.first { $0.id == "x1" })
        vm.setDraftText("Father, Friday it is — M-Pesa details below.")
        vm.act("x1", "approve", draft: vm.ui.draftText)
        await drain()
        // Nothing reached the server: it is plainly not sent, no settling.
        XCTAssertTrue(vm.ui.checking.isEmpty && vm.ui.acting.isEmpty)
        XCTAssertNotNil(vm.ui.draftFor)
        XCTAssertEqual(vm.ui.draftText, "Father, Friday it is — M-Pesa details below.")
        XCTAssertEqual(vm.ui.draftError, "Couldn't send — no connection — check your internet and try again")
        // Back online, Send again: once.
        server.install()
        vm.act("x1", "approve", draft: vm.ui.draftText)
        await drain()
        XCTAssertEqual(server.sent, ["x1"])
        XCTAssertNil(vm.ui.draftFor)
        XCTAssertNil(vm.ui.draftError)
    }

    func testClosingAndReopeningTheDialogKeepsTheText() async {
        let vm = await vm()
        let x1 = vm.ui.actions!.first { $0.id == "x1" }!
        vm.openDraft(x1)
        vm.setDraftText("my words")
        vm.openDraft(nil)
        vm.openDraft(x1)
        XCTAssertEqual(vm.ui.draftText, "my words")
        // Another action starts from its own draft.
        vm.openDraft(vm.ui.actions!.first { $0.id == "x2" })
        XCTAssertEqual(vm.ui.draftText, "")
    }

    func testConflictMeansAlreadySentAndTheQueueShowsTheTruth() async {
        server.install()
        let vm = await vm()
        vm.openDraft(vm.ui.actions!.first { $0.id == "x1" })
        _ = server.approve("x1") // the scheduler got there first
        let reads = fake.callsTo("GET", "/admin/actions").count
        vm.act("x1", "approve", draft: "edited")
        await drain()
        XCTAssertEqual(errors.last, "Already sent — nothing was sent twice")
        XCTAssertEqual(server.sent, ["x1"])
        XCTAssertNil(vm.ui.draftFor)
        XCTAssertEqual(fake.callsTo("GET", "/admin/actions").count, reads + 1)
        XCTAssertFalse(ids(vm.ui.actions).contains("x1"))
    }

    func testVetoedElsewhereSaysSo() async {
        fake.on("POST", "/admin/actions/.*/approve", code: 409, body: #"{"detail":"Action is vetoed"}"#)
        let vm = await vm()
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(errors.last, "Already vetoed — nothing was sent")
    }

    func testGoneConversationRemovesTheRowAndSaysWhy() async {
        server.install()
        let vm = await vm()
        fake.on("POST", "/admin/actions/x1/approve", code: 404, body: #"{"detail":"Conversation gone"}"#)
        server.pending.remove("x1")
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(errors.last, "This follow-up is gone — its conversation was deleted")
        XCTAssertFalse(ids(vm.ui.actions).contains("x1"))
        fake.on("POST", "/admin/actions/x2/veto", code: 404, body: #"{"detail":"Action not found"}"#)
        vm.act("x2", "veto")
        await drain()
        XCTAssertEqual(errors.last, "This follow-up is gone — someone else removed it")
    }

    func testEachStatusGetsItsOwnWords() async {
        let vm = await vm()
        func after(_ code: Int, _ body: String) async -> String? {
            fake.on("POST", "/admin/actions/x1/approve", code: code, body: body)
            vm.act("x1", "approve")
            await drain()
            return errors.last
        }
        let cases: [(Int, String, String)] = [
            (500, #"{"detail":"Could not compose the message"}"#, "Couldn't send — could not compose the message"),
            (500, "Internal Server Error", "Couldn't send — the server hit an error — try again"),
            (500, "<html><body>Traceback…</body></html>", "Couldn't send — the server hit an error — try again"),
            (429, #"{"detail":"Rate limit exceeded"}"#, "Couldn't send — too many requests — wait a moment and try again"),
            (403, #"{"detail":""}"#, "Couldn't send — your role doesn't allow that"),
            (503, "<html>Service Unavailable</html>", "Couldn't send — the server is unavailable right now — try again shortly"),
            (422, #"{"detail":"Invalid action id"}"#, "Couldn't send — invalid action id"),
        ]
        for (code, body, expected) in cases {
            let got = await after(code, body)
            XCTAssertEqual(got, expected, "\(code) \(body)")
        }
        noRawHtml()
        XCTAssertTrue(vm.ui.acting.isEmpty)
    }

    // ── 401 mid-action ──────────────────────────────────────────────────────

    func testAnExpiredTokenIsRefreshedSilentlyAndTheSendCompletesOnce() async {
        server.install()
        let s = server!
        fake.expiredOnce("POST", "/admin/actions/x1/approve") { s.approve("x1") }
        // A genuinely new token (the fixture's would be byte-identical within the same second).
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ in (200, Fixtures.tokenResponse(access: fakeJwt() + "r")) }
        let vm = await vm()
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(server.sent, ["x1"])
        XCTAssertEqual(posts("x1").count, 2) // the rejected one never reached the handler's send
        XCTAssertEqual(lastToast()?.message, "Sent ✓")
        XCTAssertFalse(host.sessionExpired.value)
    }

    func testADeadSessionKeepsTheDialogAndTextUntilSignedInAgain() async {
        server.install()
        fake.on("POST", "/admin/actions/x1/approve", code: 401, body: #"{"detail":"Could not validate credentials"}"#)
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let vm = await vm()
        vm.openDraft(vm.ui.actions!.first { $0.id == "x1" })
        vm.setDraftText("Father, Friday delivery confirmed.")
        vm.act("x1", "approve", draft: vm.ui.draftText)
        await drain()
        XCTAssertTrue(host.sessionExpired.value)
        XCTAssertNotNil(vm.ui.draftFor)
        XCTAssertEqual(vm.ui.draftText, "Father, Friday delivery confirmed.")
        XCTAssertEqual(vm.ui.draftError, "Your session expired — sign in again, then send.")
        XCTAssertTrue(errors.isEmpty)

        // Signed in again: the same words go, once.
        SalesFixtures.install(fake); server.install()
        fake.on("POST", "/(agent-auth|auth)/(login|refresh)") { _, _ in (200, Fixtures.tokenResponse(access: fakeJwt() + "r")) }
        host.onReauthenticated()
        vm.act("x1", "approve", draft: vm.ui.draftText)
        await drain()
        XCTAssertEqual(server.sent, ["x1"])
        XCTAssertEqual(json(posts("x1").last?.body ?? ""), ["draft": .string("Father, Friday delivery confirmed.")])
    }

    // ── Double taps ─────────────────────────────────────────────────────────

    func testASecondTapWhileTheFirstIsInFlightSendsNothing() async {
        server.install()
        let box = Ref<DealsViewModel?>(nil)
        let s = server!
        fake.on("POST", "/admin/actions/x1/approve") { _, _ in
            // The operator taps Send, and Edit & send, again while the first is on the wire.
            onMainSync { box.value?.act("x1", "approve"); box.value?.act("x1", "approve", draft: "again") }
            return s.approve("x1")
        }
        let vm = await vm()
        box.value = vm
        vm.act("x1", "approve")
        await drain()
        XCTAssertEqual(posts("x1").count, 1)
        XCTAssertEqual(server.sent, ["x1"])
    }

    func testWonTappedTwiceWhileSavingPatchesOnce() async {
        let box = Ref<DealsViewModel?>(nil)
        fake.on("PATCH", "/admin/deals/d1") { _, _ in
            onMainSync { box.value?.markWon("d1"); box.value?.markLost("d1") }
            return (200, #"{"ok":true}"#)
        }
        let vm = await vm()
        box.value = vm
        vm.markWon("d1")
        await drain()
        XCTAssertEqual(fake.callsTo("PATCH", "/admin/deals/d1").count, 1)
        XCTAssertTrue(vm.ui.patching.isEmpty)
    }

    // ── Leaving mid-request ─────────────────────────────────────────────────

    func testLeavingWhileSettlingStopsQuietly() async {
        server.install()
        fake.failTimeout("POST", "/admin/actions/x1/approve")
        let vm = await vm()
        vm.act("x1", "approve")
        await drain()
        let before = host.toasts.count
        vm.close() // signed out / the agent's screens discarded
        await advance(DealsViewModel.SETTLE_MS * Int64(DealsViewModel.SETTLE_READS))
        XCTAssertEqual(host.toasts.count, before)
        XCTAssertEqual(posts("x1").count, 1)
    }

    // ── Loads ───────────────────────────────────────────────────────────────

    func testOfflineFirstLoadSaysSoInsteadOfAnEmptyBoard() async {
        fake.failOffline("GET", "/admin/deals")
        fake.failOffline("GET", "/admin/actions")
        let vm = await vm()
        XCTAssertNil(vm.ui.deals, "not an empty board")
        XCTAssertNil(vm.ui.actions, "not 'Nothing queued'")
        XCTAssertEqual(vm.ui.loadError, "No connection — check your internet and try again")
        // Back online: Retry loads it and the error goes.
        SalesFixtures.install(fake)
        vm.reload()
        await drain()
        XCTAssertEqual(vm.ui.deals?.count, 4)
        XCTAssertEqual(vm.ui.actions?.count, 2)
        XCTAssertNil(vm.ui.loadError)
    }

    func testAFailedRefreshKeepsTheBoardAndStopsTheSpinner() async {
        let vm = await vm()
        fake.failTimeout("GET", "/admin/deals")
        fake.htmlPage("GET", "/admin/actions", code: 502)
        vm.refresh()
        await drain()
        XCTAssertFalse(vm.ui.refreshing)
        XCTAssertEqual(vm.ui.deals?.count, 4)
        XCTAssertEqual(vm.ui.actions?.count, 2)
        XCTAssertEqual(vm.ui.loadError, "The server took too long to answer — try again")
    }

    func testGarbageBodiesDoNotCrash() async {
        fake.on("GET", "/admin/deals", body: #"{"deals":[{"id":"#)
        fake.on("GET", "/admin/actions", body: "<html>ok</html>")
        let vm = await vm()
        XCTAssertNil(vm.ui.deals)
        XCTAssertEqual(vm.ui.loadError, "The server sent an answer the app couldn't read")
        // An empty 200 is an empty list, not an error.
        fake.on("GET", "/admin/deals", body: "")
        fake.on("GET", "/admin/actions", body: "")
        vm.reload()
        await drain()
        XCTAssertEqual(vm.ui.deals, [])
        XCTAssertEqual(vm.ui.actions, [])
        XCTAssertNil(vm.ui.loadError)
    }

    func testASlowStaleLoadCannotOverwriteANewerOne() async {
        let n = Ref(0)
        let box = Ref<DealsViewModel?>(nil)
        let fake = self.fake!
        fake.on("GET", "/admin/deals") { r, _ in
            if r.param("status") == "won" { return (200, SalesFixtures.wonDeals) }
            n.mutate { $0 += 1 }
            // The second load's reply is stale: while it is on the wire a newer load starts and lands.
            if n.value == 2 {
                fake.on("GET", "/admin/deals") { rr, _ in (200, rr.param("status") == "won" ? SalesFixtures.wonDeals : #"{"deals":[]}"#) }
                onMainSync { box.value?.reload() }
            }
            return (200, SalesFixtures.deals)
        }
        let vm = await vm()
        box.value = vm
        vm.reload()
        await drain()
        XCTAssertEqual(vm.ui.deals, [])
    }

    // ── Deal patches ────────────────────────────────────────────────────────

    func testGuidanceThatFailsStaysOpenWithTheTextAndTheReason() async {
        let vm = await vm()
        vm.startGuidance(vm.ui.deals!.first { $0.id == "d2" }!)
        vm.setGuidanceDraft("No discount — parish rate already.")
        fake.failOffline("PATCH", "/admin/deals/d2")
        vm.saveGuidance("d2")
        await drain()
        XCTAssertEqual(vm.ui.editing, "d2")
        XCTAssertEqual(vm.ui.guidanceDraft, "No discount — parish rate already.")
        XCTAssertEqual(vm.ui.guidanceError, "Update failed — no connection — check your internet and try again")
        // Retry once back online: saved, closed.
        fake.on("PATCH", "/admin/deals/[^/]+", body: #"{"ok":true}"#)
        vm.saveGuidance("d2")
        await drain()
        XCTAssertNil(vm.ui.editing)
        XCTAssertNil(vm.ui.guidanceError)
        XCTAssertEqual(lastToast()?.message, "Guidance saved — Neema obeys it now")
    }

    func testGuidanceThatTimedOutButLandedIsSaved() async {
        let vm = await vm()
        vm.startGuidance(vm.ui.deals!.first { $0.id == "d1" }!)
        vm.setGuidanceDraft("Free delivery, no discount")
        let landed = SalesFixtures.deals.replacingOccurrences(of: "Offer free delivery to Nyeri", with: "Free delivery, no discount")
        fake.failTimeout("PATCH", "/admin/deals/d1") { [self] _ in serveDeals(landed) }
        vm.saveGuidance("d1")
        await drain()
        XCTAssertNil(vm.ui.editing)
        XCTAssertEqual(lastToast()?.message, "Guidance saved — Neema obeys it now")
        XCTAssertEqual(vm.ui.deals?.first { $0.id == "d1" }?.guidance, "Free delivery, no discount")
    }

    func testGuidanceThatTimedOutAndDidNotLandStaysOpen() async {
        let vm = await vm()
        vm.startGuidance(vm.ui.deals!.first { $0.id == "d1" }!)
        vm.setGuidanceDraft("Free delivery, no discount")
        fake.failTimeout("PATCH", "/admin/deals/d1")
        vm.saveGuidance("d1")
        await drain()
        XCTAssertEqual(vm.ui.editing, "d1")
        XCTAssertEqual(vm.ui.guidanceDraft, "Free delivery, no discount")
        XCTAssertEqual(vm.ui.guidanceError, "Not saved — the server took too long to answer — try again")
    }

    func testWonThatTimedOutButLandedIsWon() async {
        let vm = await vm()
        let gone = SalesFixtures.deals.replacingOccurrences(of: "\"id\":\"d2\"", with: "\"id\":\"gone\"")
        fake.failTimeout("PATCH", "/admin/deals/d2") { [self] _ in serveDeals(gone) }
        vm.markWon("d2")
        await drain()
        XCTAssertEqual(lastToast()?.message, "Marked won 🎉")
        XCTAssertTrue(errors.isEmpty)
    }

    func testADeletedDealLeavesTheBoardAndSaysSo() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/deals/d3", code: 404, body: #"{"detail":"Deal not found"}"#)
        serveDeals(SalesFixtures.deals.replacingOccurrences(of: "\"id\":\"d3\"", with: "\"id\":\"d3-deleted\""))
        vm.startGuidance(vm.ui.deals!.first { $0.id == "d3" }!)
        vm.saveGuidance("d3")
        await drain()
        XCTAssertEqual(errors.last, "This deal no longer exists — someone may have deleted it")
        XCTAssertFalse(vm.ui.deals!.contains { $0.id == "d3" })
        XCTAssertNil(vm.ui.editing, "the editor for a deleted deal closes")
    }
}
