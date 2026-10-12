import Foundation
import XCTest
@testable import NeemaCore

/// The inbox against the REAL backend contract (Android `InboxContractTest`):
/// every request asserted exactly (method, path, query, body) and every
/// response decoded from the shape its handler in admin.py actually returns —
/// Meta rows with a null wa_id, "+00:00" microsecond timestamps, tags that
/// aren't a list, 200 {ok:false} replies, pydantic 422 lists, proxy HTML
/// error pages, and socket frames without an id or a direction.
@MainActor
final class InboxContractTests: XCTestCase {
    typealias Contract = InboxFixtures.Contract
    var fake: FakeNeema!

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        InboxFixtures.install(fake)
        fake.on("GET", "/admin/conversations", body: Contract.page([Contract.peterWa, Contract.maryMsgr, Contract.peterFb, Contract.visitor], cursor: Contract.CURSOR))
        fake.on("GET", "/admin/conversations/summary", body: Contract.summary)
        fake.on("GET", "/admin/conversations/[^/]+/messages", body: Contract.thread())
    }

    override func tearDown() async throws { AppClock.reset(); try await super.tearDown() }

    func vm(role: String = "admin", superuser: Bool = true) async -> (TestHost, InboxViewModel) {
        let host = TestHost(fake: fake, role: role, superuser: superuser)
        let vm = InboxViewModel(host: host, sleep: host.clock.sleeper)
        await drain()
        return (host, vm)
    }

    func api() -> InboxApi { InboxApi(http: TestHost(fake: fake).http) }
    func calls(_ method: String, _ path: String) -> [FakeNeema.Call] { fake.callsTo(method, path) }
    func body(_ method: String, _ path: String) -> [String: JSONValue] { json(calls(method, path).last?.body ?? "{}") }
    func socket(_ host: TestHost, _ text: String) async { host.socket.events.emit(JSONValue.parse(text)!); await drain() }

    // ═══════════════ The list: page, summary, get, resolve ═══════════════

    func testPageSendsTheServersQueryNamesAndDecodesRealRows() async throws {
        let res = try await api().page(InboxQuery(tab: "unread", channel: "messenger", mode: "human", tag: "vip", q: "  Nyeri Friday "), limit: 50, cursor: Contract.CURSOR)
        let c = fake.calls.last!
        XCTAssertEqual(c.method, "GET"); XCTAssertEqual(c.path, "/admin/conversations")
        // list_conversations(limit, cursor, tab, channel, mode, tag, q) — spaces encoded, the search trimmed.
        XCTAssertEqual(c.query, "limit=50&cursor=\(Contract.CURSOR)&tab=unread&channel=messenger&mode=human&tag=vip&q=Nyeri+Friday")
        XCTAssertEqual(res.nextCursor, Contract.CURSOR)
        let mary = res.items.first { $0.id == "k2" }!
        XCTAssertNil(mary.waId)                                  // Meta rows carry no wa_id…
        XCTAssertEqual(mary.externalId, "7123456789012345")      // …the PSID is the key
        XCTAssertEqual(mary.channel, "messenger"); XCTAssertNil(mary.countryIso); XCTAssertNil(mary.leadStage)
        let peter = res.items.first { $0.id == "k1" }!
        XCTAssertEqual(peter.tags, ["vip", "clergy"]); XCTAssertEqual(peter.ordersCount, 3)
        XCTAssertEqual(peter.assignedAgentId, Fixtures.ME_ID); XCTAssertEqual(peter.interceptMode, "human")
        // Python's "+00:00" microsecond timestamps parse to the right instant.
        XCTAssertLessThan(abs(AppClock.now() - 2 * 60_000 - Fmt.millis(peter.lastMessageAt)!), 60_000)
    }

    func testPageAllFiltersOmitsTheirKeys() async throws {
        _ = try await api().page(InboxQuery(), limit: 50)
        XCTAssertEqual(fake.calls.last?.query, "limit=50")
    }

    func testPageLegacyBareArrayIsOneFinalPage() async throws {
        fake.on("GET", "/admin/conversations", body: "[\(Contract.peterWa),\(Contract.maryMsgr)]")
        let res = try await api().page(InboxQuery(), limit: 50)
        XCTAssertEqual(res.items.map { $0.id }, ["k1", "k2"]); XCTAssertNil(res.nextCursor)
    }

    /// `tags` comes off free-form JSONB: a bare string, nulls, numbers — none may blank the inbox.
    func testPageOddTagsAreNormalisedNotFatal() async throws {
        let noTags = Contract.row("k9", "No tags", "254700000009", "254700000009", "whatsapp", "ai", "hi", 5).replacingOccurrences(of: "\"tags\":[]", with: "\"tags\":null")
        fake.on("GET", "/admin/conversations", body: "{\"items\":[\(Contract.oddTags),\(Contract.mixedTags),{\"wa_id\":\"x\"},\(noTags)],\"next_cursor\":null}")
        let res = try await api().page(InboxQuery(), limit: 50)
        XCTAssertEqual(res.items.map { $0.id }, ["k3", "k4", "k9"])   // the id-less row drops, nothing else
        XCTAssertEqual(res.items[0].tags, ["vip"])
        XCTAssertEqual(res.items[1].tags, ["bulk", "7"])
        XCTAssertEqual(res.items[2].tags, [])
    }

    func testPageBadCursor400LeavesTheListAndSaysNothing() async {
        let (host, vm) = await vm()
        XCTAssertTrue(vm.inbox.value.hasMore)
        fake.on("GET", "/admin/conversations") { r, _ in
            r.param("cursor") != nil ? (400, #"{"detail":"bad cursor"}"#) : (200, Contract.page([Contract.peterWa], cursor: Contract.CURSOR))
        }
        let before = vm.inbox.value.orderIds
        vm.loadMore(); await drain()
        XCTAssertEqual(vm.inbox.value.orderIds, before); XCTAssertFalse(vm.inbox.value.loadingMore)
        XCTAssertTrue(host.errors.isEmpty)
    }

    func testSummaryDecodesEveryBadge() async {
        let (_, vm) = await vm()
        let s = vm.inbox.value.summary!
        XCTAssertEqual(s.unread, 2); XCTAssertEqual(s.human, 1); XCTAssertEqual(s.yours, 1)
        XCTAssertEqual(s.unreadMessages, ["all": 3, "whatsapp": 2, "messenger": 1])
        XCTAssertEqual(s.tags, ["bulk", "clergy", "vip"])
    }

    func testGetOneRowAndA404Throws() async throws {
        fake.on("GET", "/admin/conversations/k2", body: Contract.maryMsgr)
        let got = try await api().get(id: "k2")
        XCTAssertEqual(got.externalId, "7123456789012345")
        fake.on("GET", "/admin/conversations/nope", code: 404, body: #"{"detail":"conversation not found"}"#)
        let e = await expectApi { try await self.api().get(id: "nope") }
        XCTAssertEqual(e?.status, 404); XCTAssertEqual(e?.detail, "conversation not found")
    }

    func testResolveSendsKeyAndRefAndRevealsTheThread() async {
        fake.on("GET", "/admin/conversations/resolve", body: Contract.resolved)
        fake.on("GET", "/admin/conversations/k2", body: Contract.maryMsgr)
        fake.on("GET", "/admin/conversations", body: Contract.page([Contract.peterWa]))
        let (host, vm) = await vm()
        host.openConvKey.value = "+250788123456|BH-1042"
        await drain()
        let r = calls("GET", "/admin/conversations/resolve")
        XCTAssertEqual(r.count, 1)
        XCTAssertEqual(r.first?.query, "key=250788123456&ref=BH-1042")
        XCTAssertEqual(vm.thread.value.activeId, "k2")
        XCTAssertTrue(vm.inbox.value.orderIds.contains("k2"))
    }

    func testResolveNullWarnsToInvite() async {
        fake.on("GET", "/admin/conversations/resolve", body: Contract.unresolved)
        let (host, _) = await vm()
        host.openConvKey.value = "250788000000"
        await drain()
        XCTAssertEqual(host.toasts.last?.message, "No conversation yet — they haven't messaged. Use Invite to WhatsApp.")
    }

    // ═══════════════ The thread: messages, paging, activity, window ═══════════════

    func testMessagesDecodeTheRealShapeNullsAndAll() async {
        let (_, vm) = await vm()
        vm.select("k2"); await drain()
        XCTAssertEqual(calls("GET", "/admin/conversations/k2/messages").last?.query, "limit=50")
        var m: [String: ThreadMsg] = [:]
        for x in vm.thread.value.messages["k2"]! { m[x.id] = x }
        XCTAssertEqual(m.count, 6)
        XCTAssertEqual(m["m1"]?.translation, "Hello, do you deliver to Kigali?"); XCTAssertEqual(m["m1"]?.translatedFrom, "French")
        XCTAssertTrue(m["evt-9f1"]!.isSystem); XCTAssertEqual(m["evt-9f1"]?.eventKind, "escalated")
        XCTAssertNil(m["m2"]!.text); XCTAssertEqual(m["m2"]?.mediaType, "image"); XCTAssertEqual(m["m2"]?.mediaCaption, "A purple clergy stole")
        XCTAssertEqual(m["m3"]?.replyTo?.id, "m1"); XCTAssertEqual(m["m3"]?.replyTo?.sender, "user")
        XCTAssertTrue(m["m4"]!.isNote)
        XCTAssertEqual(m["m5"]?.commentContext?.postId, "p_77"); XCTAssertNil(m["m5"]?.commentContext?.thumb)
        // The thread reads French → the translate toggle starts ON (threadLang from inbound rows).
        XCTAssertEqual(vm.threadLang(), "French")
    }

    /// One malformed row (or a non-object comment_context) must not blank the thread.
    func testMessagesABadRowDropsOutTheRestShow() async throws {
        fake.on("GET", "/admin/conversations/[^/]+/messages", body: """
          [
          {"id":"ok1","type":"message","direction":"inbound","sender":"user","text":"hi","created_at":"\(InboxFixtures.iso(3))"},
          {"id":"bad","type":"message","direction":"inbound","sender":"user","text":{"oops":1},"created_at":"\(InboxFixtures.iso(2))"},
          {"id":"ok2","type":"message","direction":"inbound","sender":"user","text":"[comment] hey","comment_context":"legacy-string","created_at":"\(InboxFixtures.iso(1))"}
          ]
          """)
        let msgs = try await api().messages(id: "k1")
        XCTAssertEqual(msgs.map { $0.id }, ["ok1", "ok2"])
        XCTAssertNil(msgs[1].commentContext)
    }

    func testMessagesANonArrayIsAnErrorNotAnEmptyThread() async {
        fake.on("GET", "/admin/conversations/[^/]+/messages", body: #"{"detail":"weird"}"#)
        let (_, vm) = await vm()
        vm.select("k2"); await drain()
        XCTAssertTrue(vm.thread.value.error)
    }

    /// `before` is the oldest row's created_at verbatim — its "+00:00" must reach FastAPI as "+", not a space.
    func testOlderPageEncodesTheOffset() async {
        let page = InboxFixtures.plainPage("n", 50, 100).replacingOccurrences(of: #""created_at":"[^"]+""#, with: "\"created_at\":\"\(InboxFixtures.iso(100))\"", options: .regularExpression)
        fake.on("GET", "/admin/conversations/[^/]+/messages") { r, _ in (200, r.param("before") != nil ? "[]" : page) }
        let (_, vm) = await vm()
        vm.select("k1"); await drain()
        vm.loadOlder(); await drain()
        let q = calls("GET", "/admin/conversations/k1/messages").last!.query!
        XCTAssertTrue(q.hasPrefix("limit=50&before="), q)
        XCTAssertTrue(q.contains("%2B00%3A00"), q)
        XCTAssertEqual(vm.thread.value.hasMore["k1"], false)   // an empty older page: the start of the thread
    }

    func testActivityDecodesBlankDetailsHiddenLabelLessDropped() async throws {
        let ev = try await api().activity(id: "k1")
        XCTAssertEqual(ev.map { $0.id }, ["icpt-1", "act-2", "ord-3", "tool-4"])
        XCTAssertEqual(ev[1].detail ?? "", ""); XCTAssertNil(ev[2].at); XCTAssertNil(ev[3].detail)
        fake.on("GET", "/admin/conversations/[^/]+/activity", body: #"{"events":[{"id":"x","kind":"deal","label":null},{"kind":"call","label":"Call ended · 1:04","at":null}]}"#)
        let ev2 = try await api().activity(id: "k1")
        XCTAssertEqual(ev2.count, 1); XCTAssertEqual(ev2.first?.label, "Call ended · 1:04")
    }

    func testWindowDecodesEveryMode() async {
        for (fixture, mode) in [(InboxFixtures.windowOpen(), "open"), (InboxFixtures.windowHumanAgent(), "human_agent"), (InboxFixtures.windowClosed(), "closed"),
                                (#"{"mode":"n/a","channel":"facebook"}"#, "n/a")] {
            fake.on("GET", "/admin/conversations/[^/]+/window", body: fixture)
            let (_, vm) = await vm()
            vm.select("k1"); await drain()
            let w = vm.thread.value.window!
            XCTAssertEqual(w.mode, mode)
            if mode == "closed" { XCTAssertEqual(w.reason, "Outside the messaging window — an approved template is the only way in") }
            if mode == "n/a" { XCTAssertNil(w.expiresAt) }
        }
    }

    // ═══════════════ Replies ═══════════════

    func testReplyBodyKeysAreExactlyTheServers() async {
        fake.on("POST", "/admin/conversations/k1/translate-reply", body: Contract.untranslated)
        let (host, vm) = await vm()
        vm.select("k1"); await drain()
        vm.toggleTx() // this thread reads French → toggle it OFF: plain English goes out
        vm.setReplyText("Yes, Friday.")
        vm.sendReply(); await drain()
        let b = body("POST", "/admin/conversations/k1/reply")
        XCTAssertEqual(Set(b.keys), ["text", "client_msg_id"])
        XCTAssertEqual(b["text"]?.content, "Yes, Friday.")
        // The outbox bubble's id: the server sends each id once, so a resend after a lost answer can't reach the customer twice.
        XCTAssertFalse((b["client_msg_id"]?.content ?? "").isEmpty)
        XCTAssertEqual(vm.composer.value.replyText, "")
        XCTAssertTrue(host.errors.isEmpty)
    }

    func testReplyTranslatedCarriesTheEnglishAlong() async {
        fake.on("POST", "/admin/conversations/k1/translate-reply", body: Contract.translated)
        let (_, vm) = await vm()
        vm.select("k1"); await drain()
        vm.setReplyText("Yes, we deliver Friday.")
        vm.sendReply(); await drain()
        XCTAssertEqual(json(calls("POST", "/admin/conversations/k1/translate-reply").last!.body!), ["text": .string("Yes, we deliver Friday.")])
        let b = body("POST", "/admin/conversations/k1/reply")
        XCTAssertEqual(Set(b.keys), ["text", "client_msg_id", "original_text", "original_lang"])
        XCTAssertEqual(b["text"]?.content, "Oui, nous livrons vendredi.")
        XCTAssertEqual(b["original_text"]?.content, "Yes, we deliver Friday."); XCTAssertEqual(b["original_lang"]?.content, "French")
    }

    /// 200 {ok:false, error} is a DELIVERY failure: the text comes back and the reason is shown.
    func testReplyOkFalseIsAFailure() async {
        fake.on("POST", "/admin/conversations/k1/reply", body: Contract.replyFailed)
        let (host, vm) = await vm()
        vm.select("k1"); await drain(); vm.toggleTx()
        vm.setReplyText("Hello"); vm.sendReply(); await drain()
        XCTAssertEqual(vm.composer.value.replyText, "Hello")
        XCTAssertEqual(host.toasts.last?.message, "Couldn't send the reply: (#10) This message is sent outside of allowed window.")
        XCTAssertTrue(vm.thread.value.messages["k1"]!.allSatisfy { !$0.id.hasPrefix("optimistic-") })
    }

    func testReply409And400ShowTheServersReason() async {
        let (host, vm) = await vm()
        vm.select("k1"); await drain(); vm.toggleTx()
        for (code, bodyJson, msg) in [
            (409, Contract.replyLocked, "Conversation is handled by Grace Wanjiru."),
            (400, Contract.replySms, "SMS is receive-only — Neema cannot send SMS. Reach this customer on WhatsApp or by phone."),
        ] {
            fake.on("POST", "/admin/conversations/k1/reply", code: code, body: bodyJson)
            vm.setReplyText("Hi"); vm.sendReply(); await drain()
            XCTAssertEqual(host.toasts.last?.message, msg); XCTAssertEqual(vm.composer.value.replyText, "Hi")
        }
    }

    /// Sent, then the refetch fails: still a success — never restore the text for a second send.
    func testReplySentButRefetchFailsIsStillSent() async {
        let (host, vm) = await vm()
        vm.select("k1"); await drain(); vm.toggleTx()
        fake.on("GET", "/admin/conversations/[^/]+/messages", code: 502, body: "<html>Bad Gateway</html>")
        vm.setReplyText("On its way"); vm.sendReply(); await drain()
        XCTAssertEqual(vm.composer.value.replyText, "")
        XCTAssertTrue(host.errors.isEmpty)
        XCTAssertTrue(vm.thread.value.messages["k1"]!.contains { $0.id.hasPrefix("optimistic-") && $0.body == "On its way" })
    }

    func testNoteBodyAndServerRowAndARefetchFailureIsNotAFailedSave() async {
        let (host, vm) = await vm()
        vm.select("k1"); await drain()
        fake.on("POST", "/admin/conversations/k1/note", body: Contract.note("Repeat buyer"))
        fake.on("GET", "/admin/conversations/[^/]+/messages", code: 500, body: #"{"detail":"db"}"#)
        vm.showNote(true); vm.setNoteText("Repeat buyer"); vm.saveNote(); await drain()
        XCTAssertEqual(json(calls("POST", "/admin/conversations/k1/note").first!.body!), ["text": .string("Repeat buyer")])
        XCTAssertFalse(vm.dialogs.value.note)
        XCTAssertEqual(host.toasts.last?.message, "Note saved")
    }

    // ═══════════════ Drafts, ask, answer ═══════════════

    func testDraftsLatestGenerateApproveBodiesAndErrors() async {
        fake.on("GET", "/admin/conversations/k1/latest-draft", body: Contract.latestDraft)
        let (host, vm) = await vm()
        vm.select("k1"); await drain()   // human-held → the latest held draft shows as the pill
        XCTAssertTrue(vm.composer.value.draftVisible); XCTAssertFalse(vm.composer.value.draftExpanded)

        fake.on("POST", "/admin/conversations/k1/generate-draft", body: Contract.generated)
        vm.generateDraft(); await drain()
        XCTAssertEqual(calls("POST", "/admin/conversations/k1/generate-draft").first?.body, "{}")
        XCTAssertEqual(vm.composer.value.draftText, "Yes Father — Nyeri by Friday. Shall I send the M-Pesa details?")

        fake.on("POST", "/admin/conversations/k1/generate-draft", code: 422, body: Contract.generateNoMessages)
        vm.generateDraft(); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Failed to generate draft"); XCTAssertFalse(vm.composer.value.generatingDraft)

        // approve_draft answers the sent ROW, not {ok}: a success all the same.
        fake.on("POST", "/admin/conversations/k1/approve-draft", body: Contract.approved("Yes Father"))
        vm.setDraftText("Yes Father"); vm.approveDraft(); await drain()
        XCTAssertEqual(json(calls("POST", "/admin/conversations/k1/approve-draft").last!.body!), ["text": .string("Yes Father")])
        XCTAssertEqual(host.toasts.last?.message, "AI draft approved & sent")

        // No text → {"text": null}: the server sends its own held draft.
        vm.dismissDraft(); vm.approveDraft(); await drain()
        XCTAssertEqual(body("POST", "/admin/conversations/k1/approve-draft")["text"], JSONValue.null)

        fake.on("POST", "/admin/conversations/k1/approve-draft", code: 422, body: Contract.noDraft)
        vm.setDraftText("x"); vm.approveDraft(); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Failed to approve draft")
        XCTAssertTrue(vm.composer.value.draftVisible && vm.composer.value.draftExpanded)
    }

    func testApproveSentButRefetchFailsNeverBringsTheDraftBack() async {
        let (host, vm) = await vm()
        vm.select("k1"); await drain()
        fake.on("GET", "/admin/conversations/[^/]+/messages", code: 500, body: #"{"detail":"db"}"#)
        vm.setDraftText("Yes Father"); vm.approveDraft(); await drain()
        XCTAssertEqual(host.toasts.last?.message, "AI draft approved & sent")
        XCTAssertFalse(vm.composer.value.draftVisible)
    }

    func testAskAndAnswerBodiesAndThe409() async {
        fake.on("POST", "/admin/conversations/k1/ask", body: Contract.answer)
        fake.on("POST", "/admin/conversations/k1/answer", body: Contract.sent)
        let (_, vm) = await vm()
        vm.select("k1"); await drain()
        let a = await vm.askNeema("What were his sizes?")
        XCTAssertEqual(a, "Collar 16 inch, chest 42 — from BH-1042.")
        XCTAssertEqual(json(calls("POST", "/admin/conversations/k1/ask").first!.body!), ["question": .string("What were his sizes?")])
        let r1 = await vm.answerViaNeema("yes, KES 12,500")
        XCTAssertTrue(r1.0); XCTAssertEqual(r1.1, "Neema sent: “Yes Reverend — KES 12,500, ready in 5 days 🙏”")
        XCTAssertEqual(json(calls("POST", "/admin/conversations/k1/answer").first!.body!), ["facts": .string("yes, KES 12,500")])
        fake.on("POST", "/admin/conversations/k1/answer", code: 409, body: Contract.outsideWindow)
        let r2 = await vm.answerViaNeema("x")
        XCTAssertFalse(r2.0); XCTAssertEqual(r2.1, "Outside the messaging window — reply yourself when they next write.")
        fake.on("POST", "/admin/conversations/k1/answer", code: 422, body: #"{"detail":"facts is required — what the team confirmed"}"#)
        let r3 = await vm.answerViaNeema("x")
        XCTAssertFalse(r3.0); XCTAssertEqual(r3.1, "Couldn't send right now — try again.")
        // A gateway error mid-turn may still end with Neema sending it: never "failed".
        fake.on("POST", "/admin/conversations/k1/answer", code: 502, body: "<html>502 Bad Gateway</html>")
        let r4 = await vm.answerViaNeema("x")
        XCTAssertFalse(r4.0); XCTAssertEqual(r4.1, "No answer from the server — Neema may still be sending it. Watch the thread before sending it again.")
    }

    // ═══════════════ State and ownership ═══════════════

    func testControlsBodiesPathsAndTheirRealAnswers() async {
        let (host, vm) = await vm()
        vm.select("k1"); await drain()
        vm.intercept("k1"); await drain(); vm.release("k1"); await drain(); vm.pause("k1"); await drain()
        vm.transfer(agentId: Fixtures.AGENT2_ID, agentName: "Grace Wanjiru"); await drain()
        for a in ["intercept", "release", "pause"] {
            XCTAssertEqual(calls("POST", "/admin/conversations/k1/\(a)").count, 1)
            XCTAssertEqual(calls("POST", "/admin/conversations/k1/\(a)").first?.body, "{}")
        }
        XCTAssertEqual(json(calls("POST", "/admin/conversations/k1/transfer").first!.body!), ["agent_id": .string(Fixtures.AGENT2_ID)])
        XCTAssertTrue(host.errors.isEmpty)
        XCTAssertEqual(host.toasts.last?.message, "Transferred to Grace Wanjiru")
        // The idempotent re-click answers a different envelope — still a success.
        fake.on("POST", "/admin/conversations/k1/intercept", body: Contract.interceptAlready)
        fake.on("POST", "/admin/conversations/k1/release", body: Contract.releaseAlready)
        vm.intercept("k1"); await drain(); XCTAssertEqual(host.toasts.last?.message, "Conversation claimed — you now control replies")
        vm.release("k1"); await drain(); XCTAssertEqual(host.toasts.last?.message, "Conversation released back to AI")
    }

    func testControls409s() async {
        let (host, vm) = await vm(role: "agent", superuser: false)
        vm.select("k1"); await drain()
        fake.on("POST", "/admin/conversations/k1/intercept", code: 409, body: Contract.interceptConflict)
        vm.intercept("k1"); await drain(); XCTAssertEqual(host.toasts.last?.message, "Already claimed by another agent")
        fake.on("POST", "/admin/conversations/k1/pause", code: 409, body: Contract.pauseConflict)
        vm.pause("k1"); await drain(); XCTAssertEqual(host.toasts.last?.message, "Handled by another agent — they must pause it")
        XCTAssertTrue(vm.thread.value.busy.isEmpty)
    }

    func testClearHistoryDeleteAndThe403() async {
        let (host, vm) = await vm()
        vm.select("k1"); await drain(); vm.showClear(true); vm.clearHistory(); await drain()
        XCTAssertEqual(calls("DELETE", "/admin/conversations/k1/messages").count, 1)
        XCTAssertEqual(host.toasts.last?.message, "Chat history cleared")
        fake.on("DELETE", "/admin/conversations/k1/messages", code: 403, body: Contract.clearForbidden)
        vm.clearHistory(); await drain()
        XCTAssertEqual(host.toasts.last?.message, "You don't have permission to clear chat history")
    }

    // ═══════════════ Media ═══════════════

    /// upload_media(file: UploadFile, caption: Form) — the part names, the filename, the type, the caption.
    func testUploadMultipartFieldsAndTheRowItReturns() async throws {
        fake.on("POST", "/admin/conversations/k1/upload-media", body: Contract.uploaded("image", "https://api.bethanyhouse.co.ke/api/admin/media/ab.jpg", nil))
        let item = PickedMedia(id: "x", file: nil, name: "photo.jpg", mime: "image/jpeg", size: 3, bytes: Data([1, 2, 3]), caption: "  The black one  ")
        let msg = try await api().upload(convId: "k1", item: item)
        let b = calls("POST", "/admin/conversations/k1/upload-media").first!.body!
        XCTAssertTrue(b.contains("Content-Disposition: form-data; name=\"file\"; filename=\"photo.jpg\""), b)
        XCTAssertTrue(b.contains("Content-Type: image/jpeg"), b)
        XCTAssertTrue(b.contains("name=\"caption\""), b); XCTAssertTrue(b.contains("The black one"), b)
        XCTAssertEqual(msg.id, "srv-u1"); XCTAssertEqual(msg.mediaType, "image"); XCTAssertNil(msg.text)
        // No caption → no caption part at all (the server's Form(None)).
        var blank = item; blank.caption = " "
        _ = try await api().upload(convId: "k1", item: blank)
        XCTAssertFalse(calls("POST", "/admin/conversations/k1/upload-media").last!.body!.contains("name=\"caption\""))
    }

    func testUploadErrorsReadAsTheServerWroteOrPlainly() {
        func err(_ code: Int, _ body: String) -> ApiError { ApiError(status: code, method: "POST", path: "/admin/conversations/k1/upload-media", body: body) }
        XCTAssertEqual(Inbox.uploadError(of: err(413, Contract.tooLarge)), "Image too large — max 5 MB.")
        XCTAssertEqual(Inbox.uploadError(of: err(415, Contract.unsupported)), "Unsupported media type: video/webm")
        XCTAssertEqual(Inbox.uploadError(of: err(422, Contract.unconvertible)), "Couldn't convert this video for WhatsApp — try a shorter clip or export it as MP4 (H.264).")
        XCTAssertEqual(Inbox.uploadError(of: err(413, Contract.proxyTooLarge)), "too large to upload")
        XCTAssertEqual(Inbox.uploadError(of: err(422, Contract.pydantic422)), "the server couldn't process this file")
        XCTAssertEqual(Inbox.uploadError(of: ApiError(status: 0, method: "POST", path: "/x", body: "timed out after 30s")), "upload timed out — check your connection and try again")
        XCTAssertEqual(Inbox.uploadError(of: err(500, "Internal Server Error")), "Internal Server Error")
    }

    func testUploadOnlyWhatTheServerAccepts() {
        for (mime, name) in [("image/jpeg", "a.jpg"), ("video/quicktime", "a.mov"), ("audio/ogg", "a.ogg"), ("application/pdf", "a.pdf"),
                             ("application/octet-stream", "IMG_1.MOV"), ("", "clip.m4v")] { XCTAssertTrue(Inbox.uploadable(mime: mime, name: name), "\(mime) \(name)") }
        for (mime, name) in [("video/webm", "a.webm"), ("audio/mp4", "a.m4a"), ("image/heic", "a.heic"), ("application/zip", "a.zip"),
                             ("application/octet-stream", "a.bin")] { XCTAssertFalse(Inbox.uploadable(mime: mime, name: name), "\(mime) \(name)") }
    }

    /// A 413 on the second of two files: one sent, one failed, the server's reason named.
    func testSendMediaPartialFailure() async {
        let n = Ref(0)
        fake.on("POST", "/admin/conversations/k1/upload-media") { _, _ in
            defer { n.value += 1 }
            return n.value == 0 ? (200, Contract.uploaded("document", "https://api.bethanyhouse.co.ke/api/admin/media/m.pdf", "Measurements")) : (413, Contract.tooLarge)
        }
        let (host, vm) = await vm()
        vm.select("k1"); await drain()
        vm.pickMedia([
            PickedMedia(id: "1", file: nil, name: "Measurements.pdf", mime: "application/pdf", size: 3, bytes: Data([1, 2, 3])),
            PickedMedia(id: "2", file: nil, name: "big.jpg", mime: "image/jpeg", size: 3, bytes: Data([1, 2, 3])),
        ])
        vm.sendMedia(); await drain()
        XCTAssertTrue(host.toasts.contains { $0.message == "big.jpg: Image too large — max 5 MB." })
        XCTAssertEqual(host.toasts.last?.message, "Sent 1, 1 failed")
        XCTAssertTrue(vm.thread.value.messages["k1"]!.contains { $0.id == "srv-u1" && $0.mediaType == "document" })
        // Input is sacred: the file that failed stays in the tray, with why, for a retry.
        XCTAssertEqual(vm.composer.value.media.map { $0.name }, ["big.jpg"])
        XCTAssertEqual(vm.composer.value.media.first?.error, "Image too large — max 5 MB.")
        XCTAssertFalse(vm.composer.value.uploading)
    }

    func testReplyMediaBodyKeys() async throws {
        let host = TestHost(fake: fake)
        fake.on("POST", "/admin/conversations/k1/reply-media", body: Contract.uploaded("image", "https://cdn/x.jpg", "Hi"))
        let m = try await host.api.conversations.sendMediaUrl(convId: "k1", mediaUrl: "https://cdn/x.jpg", mediaType: "image", caption: "Hi", filename: "x.jpg")
        XCTAssertEqual(json(calls("POST", "/admin/conversations/k1/reply-media").first!.body!),
                       ["media_url": .string("https://cdn/x.jpg"), "media_type": .string("image"), "caption": .string("Hi"), "filename": .string("x.jpg")])
        XCTAssertEqual(m.id, "srv-u1")
    }

    func testRecoverMediaPathBodyAndTheUnrecoverable404() async {
        let (_, vm) = await vm()
        vm.select("k1"); await drain()
        fake.on("POST", "/admin/messages/m2/recover-media", body: Contract.recovered)
        var got: Recovery? = nil
        vm.recoverMedia("m2") { got = $0 }; await drain()
        XCTAssertEqual(calls("POST", "/admin/messages/m2/recover-media").first?.body, "{}")
        XCTAssertEqual(got, .found(url: "https://api.bethanyhouse.co.ke/api/admin/media/rehosted.jpg"))
        XCTAssertEqual(vm.thread.value.recovered["m2"], "https://api.bethanyhouse.co.ke/api/admin/media/rehosted.jpg")
        fake.on("POST", "/admin/messages/m9/recover-media", code: 404, body: Contract.recoverGone)
        vm.recoverMedia("m9") { got = $0 }; await drain()
        XCTAssertEqual(got, .gone)
    }

    func testPostVideoPathEncodingAndChannel() async throws {
        let host = TestHost(fake: fake)
        fake.on("GET", "/admin/post-video/.+", body: Contract.postVideo)
        let url = try await host.api.conversations.postVideo(postId: "1784_99", channel: "instagram")
        XCTAssertEqual(url, "https://video.xx.fbcdn.net/v/t42/reel.mp4?oe=1")
        let c = fake.calls.last!
        XCTAssertEqual(c.path, "/admin/post-video/1784_99"); XCTAssertEqual(c.query, "channel=instagram")
    }

    // ═══════════════ WhatsApp invite ═══════════════

    func testInviteBodyAndFailure() async {
        let (_, vm) = await vm()
        vm.select("k2"); await drain()
        fake.on("POST", "/admin/whatsapp-invite", body: Contract.invited)
        let r1 = await vm.invite(phone: "250788123456", name: "Rev. Mary Achieng")
        XCTAssertEqual(r1, .sent)
        XCTAssertEqual(json(calls("POST", "/admin/whatsapp-invite").last!.body!), ["phone": .string("250788123456"), "name": .string("Rev. Mary Achieng")])
        fake.on("POST", "/admin/whatsapp-invite", code: 400, body: Contract.inviteBadPhone)
        let r2 = await vm.invite(phone: "123", name: nil)
        XCTAssertEqual(r2, .refused)
        XCTAssertEqual(json(calls("POST", "/admin/whatsapp-invite").last!.body!), ["phone": .string("123")])
    }

    /// The thread menu offers the invite only as CustomerSidebar does.
    func testInviteShortcutFollowsTheProfile() async {
        func profile(_ phone: String?, _ channels: String) -> String {
            "{\"id\":\"7123456789012345\",\"wa_id\":null,\"name\":\"Rev. Mary Achieng\",\"phone\":\(phone.map { "\"\($0)\"" } ?? "null"),\"lead_stage\":\"new\",\"channels\":\(channels),\"merged_ids\":[]}"
        }
        let msgr = #"[{"channel":"messenger","identifier":null,"conversation_count":1}]"#
        // A Messenger customer with a captured phone and no WhatsApp thread → offered, to THAT phone.
        fake.on("GET", "/admin/customers/7123456789012345", body: profile("+250 788 123 456", msgr))
        var v = await vm().1
        v.select("k2"); await drain()
        XCTAssertEqual(calls("GET", "/admin/customers/7123456789012345").last?.query, "channel=messenger")
        XCTAssertEqual(Inbox.inviteTarget(v.thread.value.reach, "k2"), "250788123456")
        // No phone on the profile → not offered.
        fake.on("GET", "/admin/customers/7123456789012345", body: profile(nil, msgr))
        v = await vm().1; v.select("k2"); await drain()
        XCTAssertNil(Inbox.inviteTarget(v.thread.value.reach, "k2"))
        // Already on WhatsApp (per the profile's channels) → not offered.
        fake.on("GET", "/admin/customers/7123456789012345", body: profile("+250788123456", #"[{"channel":"whatsapp","identifier":"250788123456"}]"#))
        v = await vm().1; v.select("k2"); await drain()
        XCTAssertNil(Inbox.inviteTarget(v.thread.value.reach, "k2"))
        // The profile can't be read → hidden, never guessed.
        fake.on("GET", "/admin/customers/7123456789012345", code: 500, body: #"{"detail":"x"}"#)
        v = await vm().1; v.select("k2"); await drain()
        XCTAssertNil(Inbox.inviteTarget(v.thread.value.reach, "k2"))
        // A person whose WhatsApp thread is in the list needs no lookup at all (Peter on Facebook).
        let before = fake.calls.filter { $0.path.hasPrefix("/admin/customers/") }.count
        v = await vm().1; v.select("k6"); await drain()
        XCTAssertEqual(fake.calls.filter { $0.path.hasPrefix("/admin/customers/") }.count, before)
        XCTAssertNil(Inbox.inviteTarget(v.thread.value.reach, "k6"))
        // A web visitor's hash is never a phone, even with 7–15 digits in it.
        XCTAssertNil(Inbox.inviteTarget(Reach(convId: "k5", phone: "web_3fa9c1e20b7d4c5a9e11", hasWhatsApp: false), "k5"))
        // A 20-digit PSID is not a phone either.
        XCTAssertNil(Inbox.inviteTarget(Reach(convId: "k2", phone: "25898765432101234567", hasWhatsApp: false), "k2"))
        // A stale answer for another thread never shows.
        XCTAssertNil(Inbox.inviteTarget(Reach(convId: "k1", phone: "+250788123456", hasWhatsApp: false), "k2"))
    }

    // ═══════════════ Live frames (what app/services, app/agent and app/routers publish) ═══════════════

    /// The WhatsApp webhook / meta_webhook / sms / public forms publish INBOUND frames with no `direction`.
    func testWsInboundFrameWithoutDirectionIsInbound() async {
        let (host, vm) = await vm()
        vm.select("k2"); await drain()
        await socket(host, #"{"type":"new_message","conversationId":"k2","channel":"messenger","sender":"user","text":"Still there?","mediaType":null,"mediaUrl":null}"#)
        let m = vm.thread.value.messages["k2"]!.last!
        XCTAssertEqual(m.body, "Still there?"); XCTAssertTrue(m.inbound); XCTAssertEqual(m.sender, "user")
        // n8n_bridge's inbound WhatsApp frame: media fields, no id / direction.
        await socket(host, #"{"type":"new_message","conversationId":"k2","waId":"250788123456","sender":"user","text":"[image]","mediaType":"image","mediaId":"wamid.M2","mediaUrl":"https://x/p.jpg","mediaCaption":null,"mimeType":"image/jpeg","filename":null}"#)
        let img = vm.thread.value.messages["k2"]!.last!
        XCTAssertTrue(img.inbound); XCTAssertEqual(img.mimeType, "image/jpeg"); XCTAssertEqual(img.mediaId, "wamid.M2")
    }

    /// The SMS bridge also pings agents:all with `event: notification, type: new_message` — not a message.
    func testWsNotificationFramesNeverPaintBubbles() async {
        let (host, vm) = await vm()
        vm.select("k2"); await drain()
        let n = vm.thread.value.messages["k2"]!.count
        await socket(host, #"{"event":"notification","type":"new_message","title":"SMS to the business number from +250788","body":"hi","conversationId":"k2"}"#)
        await socket(host, #"{"event":"notification","type":"draft_ready","title":"✍️ Draft ready — one tap to send","body":"x","conversationId":"k2"}"#)
        XCTAssertEqual(vm.thread.value.messages["k2"]!.count, n)
        XCTAssertFalse(vm.composer.value.draftVisible)
    }

    /// send_agent_reply's echo has no id: once the refetch holds the real row, it must not double up.
    func testWsOurReplyEchoAfterTheRefetchIsNotADuplicate() async {
        let serverHasIt = Ref(false)
        fake.on("GET", "/admin/conversations/[^/]+/messages") { _, _ in
            let extra = serverHasIt.value ? ["{\"id\":\"srv-r1\",\"type\":\"message\",\"direction\":\"outbound\",\"sender\":\"human_agent\",\"text\":\"On its way\",\"isNote\":false,\"created_at\":\"\(InboxFixtures.iso(0))\"}"] : []
            return (200, withRows(Contract.thread(), extra))
        }
        fake.on("POST", "/admin/conversations/k1/reply") { _, _ in serverHasIt.value = true; return (200, Contract.replySent("On its way")) }
        let (host, vm) = await vm()
        vm.select("k1"); await drain(); vm.toggleTx()
        vm.setReplyText("On its way"); vm.sendReply(); await drain()
        await socket(host, #"{"type":"new_message","conversationId":"k1","sender":"human_agent","text":"On its way","replyTo":null,"translation":null,"translatedFrom":null}"#)
        XCTAssertEqual(vm.thread.value.messages["k1"]!.filter { $0.body == "On its way" }.count, 1)
        // Same words from a different sender (m3 is the human's; this is Neema's) are a new line.
        await socket(host, #"{"type":"new_message","conversationId":"k1","sender":"ai","text":"Oui, 5 jours."}"#)
        XCTAssertEqual(vm.thread.value.messages["k1"]!.filter { $0.body == "Oui, 5 jours." && $0.sender == "ai" }.count, 1)
        // …but a customer who says "ok" twice is heard twice.
        await socket(host, #"{"type":"new_message","conversationId":"k1","sender":"user","text":"ok"}"#)
        await socket(host, #"{"type":"new_message","conversationId":"k1","sender":"user","text":"ok"}"#)
        XCTAssertEqual(vm.thread.value.messages["k1"]!.filter { $0.body == "ok" }.count, 2)
    }

    /// The AI reply frame (n8n_bridge) carries the DB id and, for voice, the media.
    func testWsAiReplyAndTranslationsAndPills() async {
        let (host, vm) = await vm()
        vm.select("k1"); await drain()
        await socket(host, #"{"type":"new_message","id":"ai-1","conversationId":"k1","sender":"ai","text":"Sawa","mediaType":"audio","mediaUrl":"https://x/r.ogg","mediaCaption":"🛒 2 × Shirt"}"#)
        await socket(host, #"{"type":"new_message","id":"ai-1","conversationId":"k1","sender":"ai","text":"Sawa"}"#)
        let ai = vm.thread.value.messages["k1"]!.filter { $0.id == "ai-1" }
        XCTAssertEqual(ai.count, 1); XCTAssertFalse(ai.first!.inbound); XCTAssertEqual(ai.first?.mediaCaption, "🛒 2 × Shirt")
        // translate.py: {type:"translations", items:[{id, text, lang}]} — lang may be null.
        await socket(host, #"{"type":"translations","conversationId":"k1","items":[{"id":"m5","text":"Price?","lang":null}]}"#)
        XCTAssertEqual(vm.thread.value.messages["k1"]!.first { $0.id == "m5" }?.translation, "Price?")
        // record_escalation's frame has no agent; transfer's carries eventNote.
        await socket(host, #"{"type":"intercept_changed","conversationId":"k1","eventKind":"escalated","eventReason":"Wants a quote"}"#)
        await socket(host, "{\"type\":\"intercept_changed\",\"conversationId\":\"k1\",\"mode\":\"human\",\"assignedAgentId\":\"\(Fixtures.AGENT2_ID)\",\"assignedAgentName\":\"Grace Wanjiru\",\"eventKind\":\"transfer\",\"eventAgentName\":\"Grace Wanjiru\",\"eventNote\":\"Moses Mwicigi → Grace Wanjiru\"}")
        var live: [String: ThreadMsg] = [:]
        for m in vm.thread.value.messages["k1"]!.filter({ $0.id.hasPrefix("live-evt-") }) { live[m.eventKind ?? ""] = m }
        XCTAssertEqual(live["escalated"]?.eventReason, "Wants a quote")
        XCTAssertEqual(live["transfer"]?.text, "Transferred — Moses Mwicigi → Grace Wanjiru")
        // copilot / runtime ai_draft_ready.
        await socket(host, #"{"type":"ai_draft_ready","conversationId":"k1","waId":"254712345678","draft":"Yes Father"}"#)
        XCTAssertEqual(vm.composer.value.draftText, "Yes Father")
        // clear_chat_history.
        await socket(host, #"{"type":"history_cleared","conversationId":"k1","clearedBy":"Grace Wanjiru"}"#)
        XCTAssertTrue(vm.thread.value.messages["k1"]!.isEmpty)
        XCTAssertEqual(host.toasts.last?.message, "History cleared by Grace Wanjiru")
    }
}
