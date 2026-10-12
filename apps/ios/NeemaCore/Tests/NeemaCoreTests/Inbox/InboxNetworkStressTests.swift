import Foundation
import XCTest
@testable import NeemaCore

/// Errors and network stress (Android `InboxNetworkStressTest`): every load
/// and every action of the inbox and the thread against a server that times
/// out, can't be reached, drops the connection halfway, answers
/// 401/403/404/409/422/429/5xx or garbage — with the rule above all: a sent
/// message is never duplicated and never falsely reported as failed, and
/// what the agent typed is never lost.
@MainActor
final class InboxNetworkStressTests: XCTestCase {
    var fake: FakeNeema!
    var server: InboxNetFixtures.Server!

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        InboxFixtures.install(fake)
        server = InboxNetFixtures.Server(fake)
    }

    override func tearDown() async throws { AppClock.reset(); try await super.tearDown() }

    func vm() async -> (TestHost, InboxViewModel) {
        let host = TestHost(fake: fake)
        let vm = InboxViewModel(host: host, sleep: host.clock.sleeper)
        await drain()
        return (host, vm)
    }

    func idle(_ host: TestHost, _ ms: Int64) async { await host.clock.advance(by: ms) }
    func posts(_ path: String) -> [FakeNeema.Call] { fake.calls.filter { $0.method == "POST" && $0.path == path } }
    func thread(_ vm: InboxViewModel, _ id: String = "c1") -> [ThreadMsg] { vm.thread.value.messages[id] ?? [] }
    func mine(_ vm: InboxViewModel, _ id: String = "c1") -> [ThreadMsg] { thread(vm, id).filter { $0.id.hasPrefix("optimistic-") } }
    func replyRoute(_ conv: String = "c1", _ answer: @escaping () throws -> (Int, String)) { fake.on("POST", "/admin/conversations/\(conv)/reply") { _, _ in try answer() } }
    func api(_ code: Int, _ body: String) -> ApiError { ApiError(status: code, method: "POST", path: "/x", body: body) }

    // ═══════════════════ What a failure means ═══════════════════

    func testFateClassifiesEveryFailure() {
        XCTAssertEqual(NetErrors.fate(of: api(0, "timed out after 30s")), .unknown)
        XCTAssertEqual(NetErrors.fate(of: api(0, "unexpected end of stream on https://neema.test/...")), .unknown)
        XCTAssertEqual(NetErrors.fate(of: api(0, "Failed to connect to neema.test/10.0.0.1:443")), .notSent)
        XCTAssertEqual(NetErrors.fate(of: api(0, "Unable to resolve host \"neema.test\": No address associated with hostname")), .notSent)
        for c in [500, 502, 503, 504] { XCTAssertEqual(NetErrors.fate(of: api(c, "x")), .unknown, "\(c)") }
        for c in [400, 401, 403, 404, 409, 413, 415, 422, 429] { XCTAssertEqual(NetErrors.fate(of: api(c, "x")), .notSent, "\(c)") }
        XCTAssertEqual(NetErrors.fate(of: NotDelivered("window closed")), .notSent)
        XCTAssertEqual(NetErrors.fate(of: DecodingError.dataCorrupted(.init(codingPath: [], debugDescription: "bad body"))), .done)
        XCTAssertEqual(NetErrors.fate(of: ApiError(status: 200, method: "POST", path: "/x", body: "<html>", malformed: true)), .done)
        // The words: plain for transport trouble, the server's own when written for people, never HTML.
        XCTAssertEqual(NetErrors.whyFailed(api(502, "<html>Bad Gateway</html>"), "F"), "Neema's server is unavailable right now — try again shortly.")
        XCTAssertEqual(NetErrors.whyFailed(api(403, "<html>Forbidden</html>"), "F", useDetail: true), "F")
        XCTAssertEqual(NetErrors.whyFailed(api(422, #"{"detail":[{"msg":"Field required"}]}"#), "F", useDetail: true), "F")
        XCTAssertEqual(NetErrors.whyFailed(api(409, #"{"detail":"Nope."}"#), "F", useDetail: true), "Nope.")
        XCTAssertTrue(NetErrors.conversationGone(api(404, #"{"detail":"Conversation not found"}"#)))
        XCTAssertFalse(NetErrors.conversationGone(api(404, #"{"detail":"Not Found"}"#)))   // a route the server lacks
    }

    // ═══════════════════ Reply: timeout — the critical rule ═══════════════════

    /// The reply reached the customer but the answer was lost: one bubble, confirmed, never "failed".
    func testReplyTimesOutButWasDeliveredIsConfirmedByRefetchNeverDuplicated() async {
        let server = self.server!
        replyRoute { server.add(InboxNetFixtures.row("srv-r1", "On its way Friday")); return try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("On its way Friday"); vm.sendReply(); await drain()
        // At once: the box is free and the bubble says "sending…" — nothing claims failure.
        XCTAssertEqual(vm.composer.value.replyText, "")
        XCTAssertEqual(mine(vm).first?.sendState, "sending")
        XCTAssertTrue(host.errors.isEmpty)
        await idle(host, 2_100)
        let all = thread(vm)
        XCTAssertEqual(all.filter { $0.body == "On its way Friday" }.count, 1)
        XCTAssertEqual(all.last?.id, "srv-r1")
        XCTAssertTrue(mine(vm).isEmpty)
        XCTAssertEqual(posts("/admin/conversations/c1/reply").count, 1)
        XCTAssertTrue(host.errors.isEmpty)
    }

    /// It never reached the server: after the checks it turns "Not sent" with Retry, and Retry sends it once.
    func testReplyTimesOutAndWasNotDeliveredTurnsNotSentThenRetrySendsItOnce() async {
        replyRoute { try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Shall I send the M-Pesa details?"); vm.sendReply(); await drain()
        await idle(host, 2_100); await idle(host, 8_000)
        XCTAssertEqual(mine(vm).first?.sendState, "sending")   // still checking — not failed yet
        XCTAssertTrue(host.errors.isEmpty)
        await idle(host, 20_000)
        let failed = mine(vm).first!
        XCTAssertEqual(failed.sendState, "failed")
        XCTAssertEqual(failed.body, "Shall I send the M-Pesa details?")   // the words are all there
        XCTAssertNotNil(failed.sendError)
        XCTAssertTrue(host.errors.last!.message.lowercased().contains("tap retry"))

        let server = self.server!
        replyRoute { server.add(InboxNetFixtures.row("srv-r2", "Shall I send the M-Pesa details?")); return (200, #"{"ok":true}"#) }
        vm.retrySend(failed.id); await drain()
        XCTAssertEqual(posts("/admin/conversations/c1/reply").count, 2)
        XCTAssertEqual(thread(vm).filter { $0.body == "Shall I send the M-Pesa details?" }.count, 1)
        XCTAssertTrue(mine(vm).isEmpty)
    }

    /// It turned up on the server after all: Retry finds it and does NOT send it a second time.
    func testReplyRetryOfATimedOutSendFindsItOnTheServerAndNeverSendsTwice() async {
        replyRoute { try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Asante Father"); vm.sendReply(); await drain()
        await idle(host, 31_000)
        let failed = mine(vm).first!
        XCTAssertEqual(failed.sendState, "failed")
        server.add(InboxNetFixtures.row("srv-late", "Asante Father"))   // the slow server finished delivering it
        vm.retrySend(failed.id); await drain()
        XCTAssertEqual(posts("/admin/conversations/c1/reply").count, 1)
        XCTAssertEqual(thread(vm).filter { $0.body == "Asante Father" }.count, 1)
        XCTAssertEqual(host.toasts.last?.message, "It had already gone through — not sent twice.")
    }

    /// A later poll that brings the row settles even a "Not sent" bubble — it did go.
    func testReplyFailedBubbleIsReplacedWhenThePollBringsTheRealRow() async {
        replyRoute { try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Late but sent"); vm.sendReply(); await drain()
        await idle(host, 31_000)
        XCTAssertEqual(mine(vm).first?.sendState, "failed")
        server.add(InboxNetFixtures.row("srv-poll", "Late but sent"))
        vm.loadMessages("c1", silent: true); await drain()
        XCTAssertEqual(thread(vm).filter { $0.body == "Late but sent" }.count, 1)
        XCTAssertTrue(mine(vm).isEmpty)
    }

    /// The checks themselves can't reach the server: stay "sending…" — then the next good read settles it.
    func testReplyTimesOutAndTheChecksAreOfflineStaysSendingUntilAReadSucceeds() async {
        replyRoute { try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        server.threadDown = { try InboxNetFixtures.offline() }
        vm.setReplyText("Karibu"); vm.sendReply(); await drain()
        await idle(host, 31_000)
        XCTAssertEqual(mine(vm).first?.sendState, "sending")
        XCTAssertTrue(host.errors.allSatisfy { !$0.message.contains("Karibu") && !$0.message.contains("Retry") })
        // Back online (the catch-up / 20 s poll): the server never got it → Not sent, with Retry.
        server.threadDown = nil
        vm.loadMessages("c1", silent: true); await drain()
        XCTAssertEqual(mine(vm).first?.sendState, "failed")
        XCTAssertEqual(mine(vm).first?.body, "Karibu")
    }

    /// A connection that drops mid-answer is "maybe": checked, never reported failed while it was delivered.
    func testReplyDroppedConnectionAnd502And500AreAllCheckedBeforeAnyVerdict() async {
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        let fails: [() throws -> (Int, String)] = [
            { try InboxNetFixtures.dropped() },
            { (502, "<html><body>502 Bad Gateway</body></html>") },
            { (500, "Internal Server Error") },
        ]
        let server = self.server!
        for (i, fail) in fails.enumerated() {
            let text = "Reply \(i)"
            replyRoute { server.add(InboxNetFixtures.row("srv-x\(i)", text)); return try fail() }
            vm.setReplyText(text); vm.sendReply(); await drain()
            XCTAssertEqual(mine(vm).first?.sendState, "sending")
            await idle(host, 2_100)
            XCTAssertEqual(thread(vm).filter { $0.body == text }.count, 1)
            XCTAssertTrue(mine(vm).isEmpty)
        }
        XCTAssertTrue(host.errors.isEmpty)
        XCTAssertTrue(host.toasts.allSatisfy { !$0.message.contains("<html") })
    }

    // ═══════════════════ Reply: definite failures ═══════════════════

    /// No connection at all: it never left the phone — the words go straight back in the box, and it says why.
    func testReplyOfflineTextBackInTheBoxAndAPlainReason() async {
        replyRoute { try InboxNetFixtures.offline() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Habari"); vm.sendReply(); await drain()
        XCTAssertEqual(vm.composer.value.replyText, "Habari")
        XCTAssertTrue(mine(vm).isEmpty)
        XCTAssertEqual(host.errors.last?.message, "No connection — check your internet and try again.")
    }

    func testReplyEachStatusGetsTheRightWordsAndTheTextSurvives() async {
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        for (code, body, said) in [
            (403, "<html><h1>403 Forbidden</h1></html>", "Failed to send message"),
            (422, #"{"detail":[{"loc":["body","text"],"msg":"Field required","type":"missing"}]}"#, "Failed to send message"),
            (429, #"{"detail":"Too Many Requests"}"#, "Too many requests — wait a moment and try again."),
            (400, #"{"detail":"SMS is receive-only — Neema cannot send SMS. Reach this customer on WhatsApp or by phone."}"#,
             "SMS is receive-only — Neema cannot send SMS. Reach this customer on WhatsApp or by phone."),
        ] {
            replyRoute { (code, body) }
            vm.setReplyText("Hi \(code)"); vm.sendReply(); await drain()
            XCTAssertEqual(host.errors.last?.message, said)
            XCTAssertEqual(vm.composer.value.replyText, "Hi \(code)")
            vm.setReplyText("")
        }
        XCTAssertTrue(host.toasts.allSatisfy { !$0.message.contains("<") && !$0.message.contains("loc") })
    }

    /// 409: someone else holds it — the reason, the current truth fetched, the words kept.
    func testReply409ShowsWhoHoldsItRefetchesTheRowAndKeepsTheText() async {
        replyRoute { (409, #"{"detail":"Conversation is handled by Grace Wanjiru."}"#) }
        let got = Ref(0)
        let c1 = InboxFixtures.conversations.first { $0.contains("\"id\":\"c1\"") }!
        fake.on("GET", "/admin/conversations/c1") { _, _ in got.value += 1; return (200, c1) }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Mine now?"); vm.sendReply(); await drain()
        XCTAssertEqual(host.errors.last?.message, "Conversation is handled by Grace Wanjiru.")
        XCTAssertEqual(vm.composer.value.replyText, "Mine now?")
        XCTAssertGreaterThanOrEqual(got.value, 1)
    }

    /// 404: someone deleted the conversation — it leaves the list and the agent is told.
    func testReply404ConversationDeletedIsRemovedAndSaid() async {
        replyRoute { (404, #"{"detail":"Conversation not found"}"#) }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Hello?"); vm.sendReply(); await drain()
        XCTAssertNil(vm.inbox.value.cache["c1"])
        XCTAssertEqual(vm.thread.value.activeId, "")
        XCTAssertTrue(host.toasts.last!.message.contains("deleted"))
    }

    /// 200 {ok:false}: the channel refused — never "sent", never silent.
    func testReplyOkFalseAndA2xxWithGarbage() async {
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        replyRoute { (200, #"{"ok":false,"error":"Couldn't send the reply: page token expired"}"#) }
        vm.setReplyText("One"); vm.sendReply(); await drain()
        XCTAssertEqual(vm.composer.value.replyText, "One")
        XCTAssertEqual(host.errors.last?.message, "Couldn't send the reply: page token expired")
        // A 2xx whose body is not JSON at all is still a delivered reply.
        let server = self.server!
        replyRoute { server.add(InboxNetFixtures.row("srv-g", "One")); return (200, "<html>ok</html>") }
        vm.sendReply(); await drain()
        XCTAssertEqual(vm.composer.value.replyText, "")
        XCTAssertEqual(thread(vm).filter { $0.body == "One" }.count, 1)
    }

    // ═══════════════════ 401 mid-send ═══════════════════

    func testReply401RefreshesTheTokenSilentlyAndSendsOnce() async {
        let n = Ref(0)
        let server = self.server!
        replyRoute {
            defer { n.value += 1 }
            if n.value == 0 { return (401, #"{"detail":"Token expired"}"#) }
            server.add(InboxNetFixtures.row("srv-a", "After refresh")); return (200, #"{"ok":true}"#)
        }
        // A genuinely NEW access token (the default fixture could mint the very same string in the same second).
        fake.on("POST", "/(agent-auth|auth)/refresh", body: Fixtures.tokenResponse(access: fakeJwt(expiresInSec: 300 * 24 * 3600)))
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("After refresh"); vm.sendReply(); await drain()
        XCTAssertFalse(host.sessionExpired.value)
        XCTAssertEqual(thread(vm).filter { $0.body == "After refresh" }.count, 1)
        XCTAssertTrue(mine(vm).isEmpty)
        XCTAssertTrue(host.errors.isEmpty)
        XCTAssertTrue(fake.called("POST", "/auth/refresh") || fake.called("POST", "/agent-auth/refresh"))
    }

    /// The words wait on their own bubble while the SessionExpired dialog is up and go by themselves — once — on sign-in.
    func testReply401AndTheRefreshFailsSessionExpiredDialogAndTheWordsGoOnceAfterSignIn() async {
        replyRoute { (401, #"{"detail":"Token expired"}"#) }
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Please keep me"); vm.sendReply(); await drain()
        XCTAssertTrue(host.sessionExpired.value)
        let held = mine(vm).first!
        XCTAssertEqual(held.body, "Please keep me")
        XCTAssertEqual(held.sendState, "failed")
        XCTAssertEqual(held.sendError, InboxViewModel.AUTH_HELD)
        // No error toast over the dialog: the dialog already says what happened.
        XCTAssertTrue(host.errors.isEmpty)
        // Signed back in: it goes by itself, exactly once.
        fake.on("POST", "/(agent-auth|auth)/refresh", body: Fixtures.tokenResponse())
        let server = self.server!
        replyRoute { server.add(InboxNetFixtures.row("srv-b", "Please keep me")); return (200, #"{"ok":true}"#) }
        host.onReauthenticated(); await drain()
        XCTAssertEqual(thread(vm).filter { $0.body == "Please keep me" }.count, 1)
        XCTAssertTrue(mine(vm).isEmpty)
        XCTAssertEqual(fake.calls.filter { $0.method == "POST" && $0.path == "/admin/conversations/c1/reply" }.count, 2)
    }

    // ═══════════════════ Impatient users, moving on ═══════════════════

    func testDoubleTapSendSendsOnce() async {
        replyRoute { try InboxNetFixtures.timeout() }   // the slowest case: still in flight on the second tap
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Once"); vm.sendReply(); vm.sendReply(); vm.sendReply(); await drain()
        XCTAssertEqual(posts("/admin/conversations/c1/reply").count, 1)
        XCTAssertEqual(mine(vm).count, 1)
    }

    /// Switching threads mid-send: the answer lands on the thread it belongs to; the new thread's box is untouched.
    func testSwitchingThreadsMidSendTheResultLandsOnTheRightThread() async {
        let vmRef = Ref<InboxViewModel?>(nil)
        replyRoute {
            // The agent moved on to Mary and started typing while this was in flight.
            onMainSync { vmRef.value?.select("c2"); vmRef.value?.setReplyText("For Mary") }
            return (422, #"{"detail":"text is required"}"#)
        }
        let (host, vm) = await vm(); vmRef.value = vm
        vm.select("c1"); await drain()
        vm.setReplyText("For Peter"); vm.sendReply(); await drain()
        XCTAssertEqual(vm.thread.value.activeId, "c2")
        XCTAssertEqual(vm.composer.value.replyText, "For Mary")          // never overwritten
        XCTAssertTrue(mine(vm, "c2").isEmpty)                            // nothing landed on Mary
        let failed = mine(vm, "c1").first!                               // Peter's words wait on Peter's thread
        XCTAssertEqual(failed.sendState, "failed"); XCTAssertEqual(failed.body, "For Peter")
        XCTAssertTrue(host.errors.last!.message.hasPrefix("Reply to Fr. Peter Kamau not sent"))
        // Back on Peter: Edit puts the words back in HIS box.
        vm.select("c1"); await drain()
        XCTAssertEqual(vm.composer.value.replyText, "")
        vm.editFailed(failed.id)
        XCTAssertEqual(vm.composer.value.replyText, "For Peter")
        XCTAssertTrue(mine(vm).isEmpty)
        vm.select("c2"); await drain()
        XCTAssertEqual(vm.composer.value.replyText, "For Mary")
    }

    /// Each customer keeps their own composer: Peter's half-typed reply never shows in Mary's box.
    func testComposerTextBelongsToItsCustomer() async {
        let (_, vm) = await vm()
        vm.select("c1"); vm.setReplyText("Peter's words")
        vm.select("c2")
        XCTAssertEqual(vm.composer.value.replyText, "")
        vm.setReplyText("Mary's words")
        vm.select("c1")
        XCTAssertEqual(vm.composer.value.replyText, "Peter's words")
        // Peter's Facebook thread (same person) shares his box — a WhatsApp quote can be answered there.
        vm.select("c5")
        XCTAssertEqual(vm.composer.value.replyText, "Peter's words")
        await drain()
    }

    // ═══════════════════ Approve and note ═══════════════════

    func testApproveTimesOutButWasSentConfirmedOnceAndNeverResent() async {
        let server = self.server!
        fake.on("POST", "/admin/conversations/c1/approve-draft") { _, _ in server.add(InboxNetFixtures.row("srv-ai", "Yes Father", sender: "ai")); return try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setDraftText("Yes Father"); vm.approveDraft(); vm.approveDraft(); await drain()
        XCTAssertEqual(posts("/admin/conversations/c1/approve-draft").count, 1)
        XCTAssertTrue(host.errors.isEmpty)
        await idle(host, 2_100)
        XCTAssertEqual(thread(vm).filter { $0.body == "Yes Father" }.count, 1)
        XCTAssertEqual(host.toasts.last?.message, "AI draft approved & sent")
        XCTAssertFalse(vm.composer.value.draftVisible)
    }

    func testApproveOfflineDraftComesBack() async {
        fake.on("POST", "/admin/conversations/c1/approve-draft") { _, _ in try InboxNetFixtures.offline() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setDraftText("Keep this draft"); vm.approveDraft(); await drain()
        XCTAssertTrue(vm.composer.value.draftVisible && vm.composer.value.draftExpanded)
        XCTAssertEqual(vm.composer.value.draftText, "Keep this draft")
        XCTAssertEqual(host.errors.last?.message, "Failed to approve draft. No connection — check your internet and try again.")
    }

    func testNoteTimesOutButWasSavedNotSavedTwiceAndNoDialogBack() async {
        let server = self.server!
        fake.on("POST", "/admin/conversations/c1/note") { _, _ in server.add(InboxNetFixtures.row("srv-n", "Repeat buyer", note: true)); return try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.showNote(true); vm.setNoteText("Repeat buyer"); vm.saveNote(); await drain()
        XCTAssertFalse(vm.dialogs.value.note)
        XCTAssertEqual(mine(vm).first?.sendState, "sending")
        XCTAssertTrue(host.toasts.allSatisfy { $0.message != "Note saved" })   // not claimed before the server says so
        await idle(host, 2_100)
        XCTAssertEqual(thread(vm).filter { $0.body == "Repeat buyer" && $0.isNote }.count, 1)
        XCTAssertEqual(host.toasts.last?.message, "Note saved")
        XCTAssertEqual(posts("/admin/conversations/c1/note").count, 1)
        XCTAssertFalse(vm.dialogs.value.note)
    }

    func testNoteOfflineBackInItsDialog() async {
        fake.on("POST", "/admin/conversations/c1/note") { _, _ in try InboxNetFixtures.offline() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.showNote(true); vm.setNoteText("Measurements next week"); vm.saveNote(); await drain()
        XCTAssertTrue(vm.dialogs.value.note)
        XCTAssertEqual(vm.dialogs.value.noteText, "Measurements next week")
        XCTAssertEqual(host.errors.last?.message, "Failed to save note. No connection — check your internet and try again.")
    }

    // ═══════════════════ Generate draft (the long client) ═══════════════════

    func testGenerateDraftTimeoutSaysSoAndTheButtonComesBack() async {
        fake.on("POST", "/admin/conversations/c1/generate-draft") { _, _ in try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.generateDraft(); await drain()
        XCTAssertFalse(vm.composer.value.generatingDraft)
        // A draft is read-only: a timeout lost nothing, so it is a warning, not a failure.
        XCTAssertEqual(host.toasts.last?.type, .warning)
        XCTAssertEqual(host.toasts.last?.message, "Neema took too long to write a draft — nothing was sent. Try again.")
    }

    func testGenerateDraftLandsOnTheThreadThatAskedForIt() async {
        let vmRef = Ref<InboxViewModel?>(nil)
        fake.on("POST", "/admin/conversations/c1/generate-draft") { _, _ in
            onMainSync { vmRef.value?.select("c2") }
            return (200, #"{"draft":"Yes Father — Friday."}"#)
        }
        let (host, vm) = await vm(); vmRef.value = vm
        vm.select("c1"); await drain(); vm.generateDraft(); await drain()
        XCTAssertFalse(vm.composer.value.draftVisible)       // not in Mary's box
        XCTAssertEqual(host.toasts.last?.message, "Draft ready for Fr. Peter Kamau — open their chat to review it.")
        vm.select("c1"); await drain()
        XCTAssertTrue(vm.composer.value.draftVisible && vm.composer.value.draftExpanded)
        XCTAssertEqual(vm.composer.value.draftText, "Yes Father — Friday.")
        XCTAssertFalse(vm.composer.value.generatingDraft)
    }

    // ═══════════════════ Loads ═══════════════════

    func testListOfflineKeepsTheRowsSaysWhyAndRetryRecovers() async {
        let (_, vm) = await vm()
        XCTAssertEqual(vm.rows.count, 6)
        fake.on("GET", "/admin/conversations") { _, _ in try InboxNetFixtures.offline() }
        vm.refresh(); await drain()
        XCTAssertTrue(vm.inbox.value.loadError); XCTAssertFalse(vm.inbox.value.loading)
        XCTAssertEqual(vm.inbox.value.errorText, "No connection — check your internet and try again.")
        XCTAssertEqual(vm.rows.count, 6)                  // cached rows stay
        fake.on("GET", "/admin/conversations", body: InboxFixtures.page)
        vm.refresh(); await drain()
        XCTAssertFalse(vm.inbox.value.loadError); XCTAssertNil(vm.inbox.value.errorText)
    }

    func testListEachFailureGetsPlainWordsNeverRawHtml() async {
        let (_, vm) = await vm()
        let cases: [(() throws -> (Int, String), String)] = [
            ({ try InboxNetFixtures.timeout() }, "No answer from the server — the connection is too slow right now."),
            ({ (503, "<html><body>Service Unavailable</body></html>") }, "Neema's server is unavailable right now — try again shortly."),
            ({ (429, #"{"detail":"slow down"}"#) }, "Too many requests — wait a moment and try again."),
            ({ (200, "<html>captive portal</html>") }, "The server sent an answer the app couldn't read."),
            ({ (200, "") }, "The server sent an answer the app couldn't read."),
        ]
        for (reply, said) in cases {
            fake.on("GET", "/admin/conversations") { _, _ in try reply() }
            vm.refresh(); await drain()
            XCTAssertEqual(vm.inbox.value.errorText, said)
        }
    }

    /// A failed next page stops auto-paging (no tight loop offline) until Retry.
    func testLoadMoreFailureStopsAutoPagingUntilRetry() async {
        let (_, vm) = await vm()
        XCTAssertTrue(vm.inbox.value.hasMore)
        fake.on("GET", "/admin/conversations") { r, _ in r.param("cursor") != nil ? try InboxNetFixtures.offline() : (200, InboxFixtures.page) }
        vm.loadMore(); await drain()
        XCTAssertTrue(vm.inbox.value.moreError); XCTAssertFalse(vm.inbox.value.loadingMore)
        let n = fake.calls.filter { $0.params["cursor"] != nil }.count
        vm.loadMore(); vm.loadMore(); await drain()                        // what scrolling would do
        XCTAssertEqual(fake.calls.filter { $0.params["cursor"] != nil }.count, n)
        vm.loadMore(force: true); await drain()                            // the Retry button
        XCTAssertEqual(fake.calls.filter { $0.params["cursor"] != nil }.count, n + 1)
    }

    func testThreadOfflineEmptySaysWhyAndRetryWorks() async {
        server.threadDown = { try InboxNetFixtures.offline() }
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        XCTAssertTrue(vm.thread.value.error); XCTAssertFalse(vm.thread.value.loading)
        XCTAssertEqual(vm.thread.value.errorText, "No connection — check your internet and try again.")
        server.threadDown = nil
        vm.loadMessages("c1"); await drain()
        XCTAssertFalse(vm.thread.value.error)
        XCTAssertFalse(thread(vm).isEmpty)
    }

    /// An HTML page with a 200 (a captive portal) is an error — never "No messages yet".
    func testThreadGarbageBodyIsAnErrorNotAnEmptyThread() async {
        fake.on("GET", "/admin/conversations/c1/messages", body: "<html>Log in to Safaricom Wi-Fi</html>")
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        XCTAssertTrue(vm.thread.value.error)
        XCTAssertTrue(thread(vm).isEmpty)
    }

    func testThread404TheConversationWasDeleted() async {
        fake.on("GET", "/admin/conversations/c1/messages", code: 404, body: #"{"detail":"Conversation not found"}"#)
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        XCTAssertNil(vm.inbox.value.cache["c1"])
        XCTAssertFalse(vm.thread.value.threadOpen)
        XCTAssertTrue(host.toasts.last!.message.contains("deleted"))
        XCTAssertFalse(vm.rows.contains { g in g.siblings.contains { $0.id == "c1" } })
    }

    /// Peter's load fails after the agent already opened Mary: Mary's pane never shows Peter's error.
    func testThreadALateFailureForTheThreadLeftBehindNeverTouchesTheOpenOne() async {
        let vmRef = Ref<InboxViewModel?>(nil)
        fake.on("GET", "/admin/conversations/c1/messages") { _, _ in onMainSync { vmRef.value?.select("c2") }; return try InboxNetFixtures.offline() }
        let (host, vm) = await vm(); vmRef.value = vm
        vm.select("c1"); await drain(); await drain()
        XCTAssertEqual(vm.thread.value.activeId, "c2")
        XCTAssertFalse(vm.thread.value.error); XCTAssertFalse(vm.thread.value.loading)
        XCTAssertTrue(host.toasts.allSatisfy { $0.message != "Failed to load messages" })
        XCTAssertFalse(thread(vm, "c2").isEmpty)
    }

    func testOlderPageFailureOffersATapAndTheTapRetries() async {
        let many = (1...50).map { i in InboxNetFixtures.row("h\(i)", "old \(i)", sender: "user", direction: "inbound") }
        server.rows = many
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        XCTAssertEqual(vm.thread.value.hasMore["c1"], true)
        fake.on("GET", "/admin/conversations/c1/messages") { r, _ in r.param("before") != nil ? try InboxNetFixtures.timeout() : (200, InboxNetFixtures.thread(many)) }
        vm.loadOlder(); await drain()
        XCTAssertEqual(vm.thread.value.olderError, "c1"); XCTAssertEqual(vm.thread.value.olderLoading, "")
        fake.on("GET", "/admin/conversations/c1/messages") { r, _ in (200, r.param("before") != nil ? "[]" : InboxNetFixtures.thread(many)) }
        vm.loadOlder(); await drain()
        XCTAssertEqual(vm.thread.value.olderError, "")
    }

    // ═══════════════════ Ownership ═══════════════════

    func convRow(_ id: String, _ mode: String, _ agent: String?) -> String {
        InboxFixtures.conversations.first { $0.contains("\"id\":\"\(id)\"") }!
            .replacingOccurrences(of: #""intercept_mode":"[a-z]+""#, with: "\"intercept_mode\":\"\(mode)\"", options: .regularExpression)
            .replacingOccurrences(of: #""assigned_agent_id":(null|"[^"]*")"#, with: "\"assigned_agent_id\":\(agent.map { "\"\($0)\"" } ?? "null")", options: .regularExpression)
    }

    func testInterceptTimesOutButHappenedSaysClaimed() async {
        fake.on("POST", "/admin/conversations/c2/intercept") { _, _ in try InboxNetFixtures.timeout() }
        let row = convRow("c2", "human", Fixtures.ME_ID)
        fake.on("GET", "/admin/conversations/c2") { _, _ in (200, row) }
        let (host, vm) = await vm()
        vm.select("c2"); await drain(); vm.intercept("c2"); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Conversation claimed — you now control replies")
        XCTAssertTrue(fake.called("GET", "/admin/conversations/c2"))
        XCTAssertTrue(vm.thread.value.busy.isEmpty)
    }

    func testInterceptTimesOutAndDidNotHappenSaysFailedWithWhy() async {
        fake.on("POST", "/admin/conversations/c2/intercept") { _, _ in try InboxNetFixtures.timeout() }
        let row = convRow("c2", "ai", nil)
        fake.on("GET", "/admin/conversations/c2") { _, _ in (200, row) }
        let (host, vm) = await vm()
        vm.select("c2"); await drain(); vm.intercept("c2"); await drain()
        XCTAssertEqual(host.errors.last?.message, "Failed to claim conversation. No answer from the server — the connection is too slow right now.")
    }

    func testInterceptTimesOutAndCantCheckNeverSaysFailed() async {
        fake.on("POST", "/admin/conversations/c2/intercept") { _, _ in try InboxNetFixtures.timeout() }
        fake.on("GET", "/admin/conversations/c2") { _, _ in try InboxNetFixtures.offline() }
        let (host, vm) = await vm()
        vm.select("c2"); await drain(); vm.intercept("c2"); await drain()
        XCTAssertTrue(host.errors.allSatisfy { !$0.message.hasPrefix("Failed") })
        XCTAssertEqual(host.toasts.last?.type, .warning)
        XCTAssertTrue(host.toasts.last!.message.hasPrefix("Couldn't confirm"))
    }

    /// Double taps claim once; a slow claim on one thread never blocks another thread's controls.
    func testControlsExactlyOncePerThreadButNeverBlockAnotherThread() async {
        let vmRef = Ref<InboxViewModel?>(nil)
        fake.on("POST", "/admin/conversations/c2/intercept") { _, _ in
            onMainSync {
                vmRef.value?.intercept("c2"); vmRef.value?.intercept("c2")   // impatient taps while in flight
                vmRef.value?.pause("c4")                                       // another thread: goes ahead
            }
            return (200, InboxFixtures.Contract.intercept)
        }
        let (_, vm) = await vm(); vmRef.value = vm
        vm.intercept("c2"); await drain(); await drain()
        XCTAssertEqual(posts("/admin/conversations/c2/intercept").count, 1)
        XCTAssertEqual(posts("/admin/conversations/c4/pause").count, 1)
        XCTAssertTrue(vm.thread.value.busy.isEmpty)
    }

    func testOwnership404And403And409() async {
        let (host, vm) = await vm()
        fake.on("POST", "/admin/conversations/c4/release", code: 404, body: #"{"detail":"Conversation not found"}"#)
        vm.select("c4"); await drain(); vm.release("c4"); await drain()
        XCTAssertNil(vm.inbox.value.cache["c4"])
        XCTAssertTrue(host.toasts.last!.message.contains("deleted"))
        fake.on("POST", "/admin/conversations/c2/pause", code: 403, body: #"{"detail":"Only the agent handling it or an admin can pause it."}"#)
        vm.pause("c2"); await drain()
        XCTAssertEqual(host.errors.last?.message, "Failed to pause. Only the agent handling it or an admin can pause it.")
        let truth = Ref(0)
        let row = convRow("c2", "human", Fixtures.AGENT2_ID)
        fake.on("GET", "/admin/conversations/c2") { _, _ in truth.value += 1; return (200, row) }
        fake.on("POST", "/admin/conversations/c2/intercept", code: 409, body: InboxFixtures.Contract.interceptConflict)
        vm.intercept("c2"); await drain()
        XCTAssertEqual(host.errors.last?.message, "Already claimed by another agent")
        XCTAssertEqual(truth.value, 1)
    }

    func testTransferDroppedButDoneClosesTheDialog() async {
        fake.on("POST", "/admin/conversations/c1/transfer") { _, _ in try InboxNetFixtures.dropped() }
        let row = convRow("c1", "human", Fixtures.AGENT2_ID)
        fake.on("GET", "/admin/conversations/c1") { _, _ in (200, row) }
        let (host, vm) = await vm()
        vm.select("c1"); await drain(); vm.showTransfer(true)
        vm.transfer(agentId: Fixtures.AGENT2_ID, agentName: "Grace Wanjiru"); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Transferred to Grace Wanjiru")
        XCTAssertFalse(vm.dialogs.value.transfer)
    }

    func testBulkReleaseCountsWhatReallyHappened() async {
        fake.on("POST", "/admin/conversations/c1/release") { _, _ in try InboxNetFixtures.timeout() }   // it did release
        let row = convRow("c1", "ai", nil)
        fake.on("GET", "/admin/conversations/c1") { _, _ in (200, row) }
        fake.on("POST", "/admin/conversations/c6/release") { _, _ in try InboxNetFixtures.offline() }   // never left the phone
        let (host, vm) = await vm()
        vm.enterSelect(); vm.selectAllOrClear()
        vm.releaseSelected(); await drain(); await drain()
        XCTAssertEqual(host.errors.last?.message, "Released 1 — 1 failed. No connection — check your internet and try again.")
        XCTAssertFalse(vm.list.value.bulkBusy)
    }

    func testClearHistoryTimesOutButTheThreadIsEmptyIsClearedAndDoubleTapClearsOnce() async {
        let n = Ref(0)
        let fake = self.fake!
        fake.on("DELETE", "/admin/conversations/c1/messages") { _, _ in n.value += 1; fake.on("GET", "/admin/conversations/c1/messages", body: "[]"); return try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain(); vm.showClear(true)
        vm.clearHistory(); vm.clearHistory(); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Chat history cleared")
        XCTAssertEqual(n.value, 1)
        XCTAssertFalse(vm.dialogs.value.clearConfirm)
    }

    // ═══════════════════ Attachments ═══════════════════

    let video = PickedMedia(id: "v1", file: nil, name: "clip.mp4", mime: "video/mp4", size: 150 * 1024 * 1024 - 1, bytes: Data([1, 2, 3]), caption: "Fitting video")

    /// A 150 MB video times out and the server never got it: it stays in the tray, captioned, with the reason.
    func testVideoTimesOutNotOnServerStaysInTheTrayWithWhy() async {
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ in try InboxNetFixtures.timeout() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain(); vm.pickMedia([video])
        vm.sendMedia(); await drain()
        let left = vm.composer.value.media.first!
        XCTAssertEqual(left.caption, "Fitting video")
        XCTAssertEqual(left.error, "upload timed out — check your connection and try again")
        XCTAssertTrue(left.unconfirmed)
        XCTAssertFalse(vm.composer.value.uploading)
        XCTAssertEqual(host.errors.last?.message, "clip.mp4: upload timed out — check your connection and try again")
    }

    /// It dropped halfway but the server DID finish: counted as sent, never uploaded twice.
    func testVideoDropsHalfwayButArrivedIsSentNotUploadedTwice() async {
        let server = self.server!
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ in server.add(InboxNetFixtures.row("srv-v", "Fitting video", mediaType: "video")); return try InboxNetFixtures.dropped() }
        let (host, vm) = await vm()
        vm.select("c1"); await drain(); vm.pickMedia([video])
        vm.sendMedia(); await drain()
        XCTAssertTrue(vm.composer.value.media.isEmpty)
        XCTAssertEqual(host.toasts.last?.message, "Media sent")
        XCTAssertEqual(posts("/admin/conversations/c1/upload-media").count, 1)
    }

    /// Retry of a file whose upload went unanswered: found on the server → not uploaded again.
    func testVideoRetryAfterTimeoutChecksFirst() async {
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ in try InboxNetFixtures.timeout() }
        let (_, vm) = await vm()
        vm.select("c1"); await drain(); vm.pickMedia([video])
        vm.sendMedia(); await drain()
        server.add(InboxNetFixtures.row("srv-v2", "Fitting video", mediaType: "video"))   // the server finished after all
        vm.sendMedia(); await drain()
        XCTAssertEqual(posts("/admin/conversations/c1/upload-media").count, 1)
        XCTAssertTrue(vm.composer.value.media.isEmpty)
    }

    /// Signing out while a video uploads: no crash, no toast for a screen that is gone, nothing for the next agent.
    func testSignOutMidUploadIsSilent() async {
        let hostRef = Ref<TestHost?>(nil), vmRef = Ref<InboxViewModel?>(nil)
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ in
            onMainSync { hostRef.value?.logout(); vmRef.value?.close() }     // the signed-in scope is gone
            return (200, InboxFixtures.Contract.uploaded("video", "https://api.bethanyhouse.co.ke/api/admin/media/v.mp4", "Fitting video"))
        }
        let (host, vm) = await vm(); hostRef.value = host; vmRef.value = vm
        vm.select("c1"); await drain(); vm.pickMedia([video])
        let before = host.toasts.count
        vm.sendMedia(); await drain(); await drain()
        XCTAssertEqual(host.toasts.count, before)
        XCTAssertNil(host.session.value)
    }

    /// Switching threads mid-upload: the sent file leaves ITS thread's tray, not the open one's.
    func testUploadSwitchThreadsMidUploadResultLandsOnItsThread() async {
        let vmRef = Ref<InboxViewModel?>(nil)
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ in
            onMainSync { vmRef.value?.select("c2") }
            return (200, InboxFixtures.Contract.uploaded("video", "https://api.bethanyhouse.co.ke/api/admin/media/v.mp4", "Fitting video"))
        }
        let (_, vm) = await vm(); vmRef.value = vm
        vm.select("c1"); await drain(); vm.pickMedia([video])
        vm.sendMedia(); await drain(); await drain()
        XCTAssertTrue(thread(vm, "c1").contains { $0.id == "srv-u1" })
        XCTAssertFalse(thread(vm, "c2").contains { $0.id == "srv-u1" })
        XCTAssertFalse(vm.composer.value.uploading)
        vm.select("c1"); await drain()
        XCTAssertTrue(vm.composer.value.media.isEmpty); XCTAssertFalse(vm.composer.value.uploading)
    }

    // ═══════════════════ Recover media, Ask / Answer, invite, deep links ═══════════════════

    func testRecoverMediaOfflineIsTryAgain404IsGone() async {
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        var got: Recovery? = nil
        fake.on("POST", "/admin/messages/m2/recover-media") { _, _ in try InboxNetFixtures.offline() }
        vm.recoverMedia("m2") { got = $0 }; await drain()
        XCTAssertEqual(got, .failed(why: "No connection — check your internet and try again."))
        fake.on("POST", "/admin/messages/m2/recover-media", code: 404, body: InboxFixtures.Contract.recoverGone)
        vm.recoverMedia("m2") { got = $0 }; await drain()
        XCTAssertEqual(got, .gone)
    }

    func testAskNeemaOfflineAndTimeoutSayWhy() async {
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        fake.on("POST", "/admin/conversations/c1/ask") { _, _ in try InboxNetFixtures.offline() }
        let a = await vm.askNeema("sizes?")
        XCTAssertEqual(a, "No connection — check your internet and try again.")
        fake.on("POST", "/admin/conversations/c1/ask") { _, _ in try InboxNetFixtures.timeout() }
        let b = await vm.askNeema("sizes?")
        XCTAssertEqual(b, "Neema took too long to answer — try again.")
    }

    /// The answer went out but the connection dropped: the new message from Neema proves it.
    func testAnswerViaNeemaDroppedButSentIsReportedSent() async {
        let server = self.server!
        fake.on("POST", "/admin/conversations/c1/answer") { _, _ in server.add(InboxNetFixtures.row("srv-ans", "Yes Reverend — KES 12,500 🙏", sender: "ai")); return try InboxNetFixtures.dropped() }
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        let r = await vm.answerViaNeema("yes, KES 12,500")
        XCTAssertTrue(r.0); XCTAssertEqual(r.1, "Neema sent: “Yes Reverend — KES 12,500 🙏”")
    }

    func testInviteTimeoutIsUnknownOfflineAndRefusalFallBack() async {
        let (_, vm) = await vm()
        fake.on("POST", "/admin/whatsapp-invite") { _, _ in try InboxNetFixtures.timeout() }
        if case .unknown = await vm.invite(phone: "254700000001", name: nil) {} else { XCTFail("timeout should be unknown") }
        fake.on("POST", "/admin/whatsapp-invite") { _, _ in try InboxNetFixtures.offline() }
        let r2 = await vm.invite(phone: "254700000001", name: nil)
        XCTAssertEqual(r2, .refused)
        fake.on("POST", "/admin/whatsapp-invite", code: 503, body: #"{"detail":"WhatsApp sending is not configured."}"#)
        if case .unknown = await vm.invite(phone: "254700000001", name: nil) {} else { XCTFail("503 should be unknown") }
    }

    /// A deep link resolved while offline opens by itself once the app is back.
    func testDeepLinkOfflineOpensOnReconnect() async {
        fake.on("GET", "/admin/conversations/resolve") { _, _ in try InboxNetFixtures.offline() }
        let (host, vm) = await vm()
        host.openConversationFor("254799999999"); await drain()
        XCTAssertTrue(host.errors.last!.message.hasPrefix("Couldn't open that chat — no connection"))
        XCTAssertEqual(vm.thread.value.activeId, "")
        fake.on("GET", "/admin/conversations/resolve", body: #"{"conversation_id":"c2"}"#)
        host.foreground.value = false; host.foreground.value = true   // back
        await drain(); await drain()
        XCTAssertEqual(vm.thread.value.activeId, "c2")
    }

    func testOpenIdentityOfflineNeverClaimsThereIsNoConversation() async {
        fake.on("GET", "/admin/conversations") { r, _ in r.param("q") != nil ? try InboxNetFixtures.offline() : (200, InboxFixtures.page) }
        let (host, vm) = await vm()
        vm.openIdentity(channel: "instagram", externalId: "17849999999999999"); await drain()
        XCTAssertTrue(host.toasts.allSatisfy { $0.message != "No conversation on that channel yet." })
        XCTAssertEqual(host.errors.last?.message, "Couldn't open that conversation. No connection — check your internet and try again.")
    }
}
