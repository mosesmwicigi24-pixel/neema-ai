import Foundation
import XCTest
@testable import NeemaCore

/// The inbox's behaviour against the fake backend: useInbox's semantics, the
/// thread's merge/dedupe with socket frames, and every control's request
/// (Android `ConversationsViewModelTest`).
@MainActor
final class ConversationsViewModelTests: XCTestCase {
    var fake: FakeNeema!

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        InboxFixtures.install(fake)
    }

    override func tearDown() async throws { AppClock.reset(); try await super.tearDown() }

    func vm(role: String = "admin", superuser: Bool = true) async -> (TestHost, InboxViewModel) {
        let host = TestHost(fake: fake, role: role, superuser: superuser)
        let vm = InboxViewModel(host: host, sleep: host.clock.sleeper)
        await drain()
        return (host, vm)
    }

    func calls(_ method: String, _ path: String) -> [FakeNeema.Call] { fake.callsTo(method, path) }
    func lastBody(_ method: String, _ path: String) -> [String: JSONValue] { json(calls(method, path).last?.body ?? "{}") }
    func socket(_ host: TestHost, _ text: String) async { host.socket.events.emit(JSONValue.parse(text)!); await drain() }
    func page(_ ids: String..., cursor: String? = nil) -> String { InboxFixtures.page(ids, cursor: cursor) }

    // ═══════════════ useInbox ═══════════════

    func testPageOneLoadsGroupsPeopleAndBadges() async {
        let (_, vm) = await vm()
        let s = vm.inbox.value
        XCTAssertTrue(s.freshLoaded); XCTAssertFalse(s.loading); XCTAssertTrue(s.hasMore)
        XCTAssertEqual(calls("GET", "/admin/conversations").first?.query, "limit=50")
        XCTAssertEqual(s.summary?.unread, 3)   // Fixtures.inboxSummary: c1, c2 and the web visitor
        // c1 (WhatsApp) + c5 (Facebook) are one person: one row, WhatsApp chip first.
        let rows = vm.rows
        let row = rows.first { $0.key == "p1" }
        XCTAssertEqual(row?.siblings.map { $0.channel }, ["whatsapp", "facebook"])
        XCTAssertEqual(rows.count, 6)
    }

    func testRowsAreReadyTheMomentThePageIs() async {
        let (_, vm) = await vm()
        XCTAssertEqual(vm.rows.count, 6)
        vm.setTab("human")
        await drain()
        XCTAssertEqual(Set(vm.rows.map { $0.rep.id }), ["c1", "c6"])
    }

    /// After a failure the list offers Retry instead of "Loading…" forever.
    func testListLoadFailureFlagsTheErrorAndRetryRecovers() async {
        fake.on("GET", "/admin/conversations", code: 500, body: #"{"detail":"down"}"#)
        let (_, vm) = await vm()
        XCTAssertTrue(vm.inbox.value.loadError); XCTAssertFalse(vm.inbox.value.loading); XCTAssertFalse(vm.inbox.value.freshLoaded)
        XCTAssertTrue(vm.rows.isEmpty)
        fake.on("GET", "/admin/conversations", body: InboxFixtures.page)
        vm.refresh()
        await drain()
        XCTAssertFalse(vm.inbox.value.loadError); XCTAssertTrue(vm.inbox.value.freshLoaded)
        XCTAssertEqual(vm.rows.count, 6)
    }

    func testListLoadFailureIsTheLiveFiltersOwnANewFilterStartsClean() async {
        fake.on("GET", "/admin/conversations") { r, _ in
            r.param("tab") == "unread" ? (500, #"{"detail":"down"}"#) : (200, InboxFixtures.page)
        }
        let (_, vm) = await vm()
        XCTAssertFalse(vm.inbox.value.loadError)
        vm.setTab("unread"); await drain()
        XCTAssertTrue(vm.inbox.value.loadError)
        vm.setTab("all"); await drain()
        XCTAssertFalse(vm.inbox.value.loadError)
        XCTAssertEqual(vm.rows.count, 6)
    }

    func testListLoadFailureAfterASnapshotOrPageOneKeepsTheRowsQuietly() async {
        let (_, vm) = await vm()
        fake.on("GET", "/admin/conversations", code: 500, body: #"{"detail":"down"}"#)
        vm.refresh(); await drain()
        // A background refresh failing leaves the list as it was (the web's rule).
        XCTAssertEqual(vm.rows.count, 6)
        XCTAssertFalse(vm.inbox.value.loading)
    }

    /// A web-chat visitor's `web_<hash>` (or a Meta PSID) is never dialled.
    func testCallIsRefusedForWebVisitorsAndNonNumbers() async {
        let (host, vm) = await vm()
        vm.call(waId: "web_3fa9c1e20b7d4c5a9e11", name: nil)
        vm.call(waId: "3fa9c1e20b7d4c5a9e11", name: nil)
        vm.call(waId: "25898765432101234567", name: nil)   // a 20-digit PSID
        await drain()
        XCTAssertTrue(host.placedCalls.isEmpty)
        XCTAssertTrue(host.toasts.allSatisfy { !$0.message.lowercased().contains("call") })
    }

    func testNewestRequestWinsAnOlderResponseLandingLastIsDropped() async {
        let n = Ref(0)
        let vmRef = Ref<InboxViewModel?>(nil)
        fake.on("GET", "/admin/conversations") { _, _ in
            n.mutate { $0 += 1 }
            let k = n.value
            // While the first (older) request is in flight, a newer refresh starts and finishes.
            if k == 2 { onMainSync { vmRef.value?.refresh() } }
            return (200, k == 2 ? InboxFixtures.page(["c1", "c2"]) : InboxFixtures.page(["c3"]))
        }
        let (_, vm) = await vm()
        vmRef.value = vm
        n.value = 1
        vm.refresh()
        await drain(); await drain()
        // The newer request (c3) won; the older (c1, c2) response was ignored.
        XCTAssertEqual(vm.inbox.value.orderIds, ["c3"])
    }

    func testRefreshReplacesPageOneButMergesOnceScrolledFurther() async {
        fake.on("GET", "/admin/conversations") { r, _ in
            (200, r.param("cursor") == "cursor-2" ? InboxFixtures.page(["c6", "c7"]) : InboxFixtures.page(["c1", "c2", "c3"], cursor: "cursor-2"))
        }
        let (_, vm) = await vm()
        XCTAssertEqual(vm.inbox.value.orderIds, ["c1", "c2", "c3"])
        // Only page one loaded: a refresh REPLACES it (c3 fell off page one → gone).
        fake.on("GET", "/admin/conversations") { r, _ in
            (200, r.param("cursor") == "cursor-2" ? InboxFixtures.page(["c6", "c7"]) : InboxFixtures.page(["c2", "c1"], cursor: "cursor-2"))
        }
        vm.refresh(); await drain()
        XCTAssertEqual(vm.inbox.value.orderIds, ["c2", "c1"])
        // Scrolled to page two: a refresh keeps page two below the fresh page one.
        vm.loadMore(); await drain()
        XCTAssertEqual(calls("GET", "/admin/conversations").last?.query?.split(separator: "&").sorted().joined(separator: "&"), "cursor=cursor-2&limit=50")
        XCTAssertEqual(vm.inbox.value.orderIds, ["c2", "c1", "c6", "c7"])
        fake.on("GET", "/admin/conversations", body: page("c4", "c1"))
        vm.refresh(); await drain()
        XCTAssertEqual(vm.inbox.value.orderIds, ["c4", "c1", "c2", "c6", "c7"])
        // The cache never loses a row: c3 is still there for lookups.
        XCTAssertNotNil(vm.inbox.value.cache["c3"])
    }

    func testLoadMoreInFlightIsCancelledByAPageOneReplace() async {
        let vmRef = Ref<InboxViewModel?>(nil)
        let pageOnes = Ref(0)
        fake.on("GET", "/admin/conversations") { r, _ in
            if r.param("cursor") != nil {
                // Page one lands (a replace) while the old-cursor page is still in flight:
                // Android's fake answers it synchronously, so here the handler waits for
                // the fresh page one (reordered, so its landing shows) before answering.
                onMainSync { vmRef.value?.refresh() }
                let deadline = Date().addingTimeInterval(5)
                while Date() < deadline {
                    let ids = Ref<[String]>([])
                    onMainSync { ids.value = vmRef.value?.inbox.value.orderIds ?? [] }
                    if ids.value == ["c2", "c1"] { break }
                    Thread.sleep(forTimeInterval: 0.005)
                }
                return (200, InboxFixtures.page(["c6", "c7"], cursor: "cursor-3"))
            }
            pageOnes.mutate { $0 += 1 }
            return (200, pageOnes.value == 1 ? InboxFixtures.page(["c1", "c2"], cursor: "cursor-2") : InboxFixtures.page(["c2", "c1"], cursor: "cursor-2b"))
        }
        let (_, vm) = await vm()
        vmRef.value = vm
        vm.loadMore()
        await drain(); await drain()
        let s = vm.inbox.value
        XCTAssertEqual(s.orderIds, ["c2", "c1"])   // no stale page appended past a moved boundary
        XCTAssertFalse(s.loadingMore)
        XCTAssertTrue(s.hasMore)
        XCTAssertEqual(pageOnes.value, 2)
    }

    func testFiltersEachStartsItsOwnListAndSearchIsDebounced() async {
        let (host, vm) = await vm()
        fake.on("GET", "/admin/conversations", body: page("c1", "c2"))
        vm.setTab("unread"); await drain()
        XCTAssertTrue(calls("GET", "/admin/conversations").last!.query!.contains("tab=unread"))
        XCTAssertEqual(Set(vm.rows.map { $0.key }), ["p1", "c2"])
        vm.setChannel("messenger"); await drain()
        XCTAssertTrue(calls("GET", "/admin/conversations").last!.query!.contains("channel=messenger"))
        XCTAssertEqual(vm.rows.map { $0.rep.id }, ["c2"])
        let before = calls("GET", "/admin/conversations").count
        vm.setSearch("pe"); vm.setSearch("peter")
        await drain()
        XCTAssertEqual(calls("GET", "/admin/conversations").count, before) // not yet — waits for a pause
        await host.clock.advance(by: 301)
        XCTAssertEqual(calls("GET", "/admin/conversations").count, before + 1)
        XCTAssertTrue(calls("GET", "/admin/conversations").last!.query!.contains("q=peter"))
        vm.setTag("vip"); await drain(); vm.setMode("human"); await drain()
        let q = calls("GET", "/admin/conversations").last!.query!
        XCTAssertTrue(q.contains("tag=vip") && q.contains("mode=human"))
    }

    func testWatchKeepsTheOpenThreadFreshWhenOffPageOne() async {
        let (_, vm) = await vm()
        vm.select("c6"); await drain()
        fake.on("GET", "/admin/conversations", body: page("c1", "c2"))
        let before = calls("GET", "/admin/conversations/c6").count
        vm.refresh(); await drain()
        XCTAssertEqual(calls("GET", "/admin/conversations/c6").count, before + 1)
    }

    // ═══════════════ openConvKey ═══════════════

    func testOpenKeyMatchesPhonePreferringWhatsAppAndConsumesTheKey() async {
        let (host, vm) = await vm()
        host.openConversationFor("+254712345678|BH-1042")
        await drain()
        XCTAssertEqual(vm.thread.value.activeId, "c1")
        XCTAssertNil(host.openConvKey.value)
        XCTAssertFalse(fake.called("GET", "/admin/conversations/resolve"))
    }

    func testOpenKeyUnknownPhoneWithRefResolvesOnTheServerAndReveals() async {
        fake.on("GET", "/admin/conversations/resolve", body: #"{"conversation_id":"c99"}"#)
        fake.on("GET", "/admin/conversations/c99", body: Fixtures.conv("c99", "Bishop Otieno", "254799000111", "whatsapp", "ai", "Old thread", 60 * 24 * 90))
        let (host, vm) = await vm()
        host.openConversationFor("254799000111|BH-0999")
        await drain()
        let r = calls("GET", "/admin/conversations/resolve")
        XCTAssertEqual(r.count, 1)
        XCTAssertEqual(r.first?.query, "key=254799000111&ref=BH-0999")
        XCTAssertEqual(vm.thread.value.activeId, "c99")
        XCTAssertTrue(vm.inbox.value.orderIds.contains("c99"))   // revealed: survives the next page-one replace
        vm.refresh(); await drain()
        XCTAssertTrue(vm.inbox.value.orderIds.contains("c99"))
    }

    func testOpenKeyNoConversationWarns() async {
        fake.on("GET", "/admin/conversations/resolve", body: #"{"conversation_id":null}"#)
        let (host, vm) = await vm()
        host.openConversationFor("254700000000")
        await drain()
        XCTAssertEqual(vm.thread.value.activeId, "")
        XCTAssertEqual(host.toasts.last?.type, .warning)
        XCTAssertEqual(host.toasts.last?.message, "No conversation yet — they haven't messaged. Use Invite to WhatsApp.")
    }

    func testOpenKeyWaitsForTheFreshList() async {
        fake.on("GET", "/admin/conversations", code: 500, body: #"{"detail":"down"}"#)
        fake.on("GET", "/admin/conversations/resolve", body: #"{"conversation_id":"c1"}"#)
        let (host, _) = await vm()
        host.openConversationFor("254700000000")
        await drain()
        // Empty list: the key is kept, nothing resolved against it.
        XCTAssertEqual(host.openConvKey.value, "254700000000")
        XCTAssertFalse(fake.called("GET", "/admin/conversations/resolve"))
    }

    // ═══════════════ The thread ═══════════════

    func testSelectLoadsNewestPageClearsUnreadSnapshotsDivider() async {
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        XCTAssertEqual(calls("GET", "/admin/conversations/c1/messages").last?.query, "limit=50")
        XCTAssertEqual(vm.thread.value.messages["c1"]?.count, 8)
        XCTAssertEqual(vm.thread.value.hasMore["c1"], false)
        XCTAssertEqual(vm.thread.value.unreadSnapshot["c1"], 2)
        XCTAssertEqual(vm.inbox.value.cache["c1"]?.unread, 0)
        XCTAssertTrue(fake.called("GET", "/admin/conversations/c1/window"))
        XCTAssertTrue(fake.called("GET", "/admin/conversations/c1/latest-draft"))  // human-held → the draft pill
    }

    func testLoadErrorSaysSoAndRetries() async {
        fake.on("GET", "/admin/conversations/[^/]+/messages", code: 500, body: #"{"detail":"boom"}"#)
        let (host, vm) = await vm()
        vm.select("c2"); await drain()
        XCTAssertTrue(vm.thread.value.error)
        XCTAssertEqual(host.toasts.last?.message, "Failed to load messages")
        fake.on("GET", "/admin/conversations/[^/]+/messages", body: Fixtures.messages)
        vm.loadMessages("c2"); await drain()
        XCTAssertFalse(vm.thread.value.error)
        XCTAssertEqual(vm.thread.value.messages["c2"]?.count, 8)
    }

    func testPagingOlderUsesBeforeAndMerges() async {
        fake.on("GET", "/admin/conversations/[^/]+/messages") { r, _ in
            (200, r.param("before") != nil ? InboxFixtures.plainPage("old", 10, 500) : InboxFixtures.plainPage("new", 50, 100))
        }
        let (_, vm) = await vm()
        vm.select("c2"); await drain()
        XCTAssertEqual(vm.thread.value.hasMore["c2"], true)
        let oldest = vm.thread.value.messages["c2"]!.first!.createdAt
        vm.loadOlder(); await drain()
        let q = calls("GET", "/admin/conversations/c2/messages").last!
        XCTAssertTrue(q.query!.contains("before=") && q.query!.contains("limit=50"))
        XCTAssertEqual(q.param("before"), oldest)
        let msgs = vm.thread.value.messages["c2"]!
        XCTAssertEqual(msgs.count, 60)
        XCTAssertEqual(msgs.first?.id, "old0")
        XCTAssertEqual(vm.thread.value.hasMore["c2"], false)   // 10 < 50: the start of the thread
    }

    func testSocketNewMessageAppendsDedupesByIdAndByMediaWithin15s() async {
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        await socket(host, #"{"type":"new_message","conversationId":"c1","id":"w1","direction":"inbound","sender":"user","text":"Hello again"}"#)
        await socket(host, #"{"type":"new_message","conversationId":"c1","id":"w1","direction":"inbound","sender":"user","text":"Hello again"}"#)
        let now = AppClock.now()
        await socket(host, "{\"type\":\"new_message\",\"conversationId\":\"c1\",\"id\":\"a-rand-1\",\"direction\":\"outbound\",\"sender\":\"ai\",\"text\":\"\",\"mediaType\":\"audio\",\"mediaUrl\":\"https://x/a.ogg\",\"created_at\":\"\(Inbox.iso(ofMillis: now))\"}")
        await socket(host, "{\"type\":\"new_message\",\"conversationId\":\"c1\",\"id\":\"a-rand-2\",\"direction\":\"outbound\",\"sender\":\"ai\",\"text\":\"\",\"mediaType\":\"audio\",\"mediaUrl\":\"https://x/a.ogg\",\"created_at\":\"\(Inbox.iso(ofMillis: now + 5_000))\"}")
        // Another conversation's frame never lands in this thread.
        await socket(host, #"{"type":"new_message","conversationId":"c2","id":"z","direction":"inbound","sender":"user","text":"other"}"#)
        let ids = vm.thread.value.messages["c1"]!.map { $0.id }
        XCTAssertEqual(ids.filter { $0 == "w1" }.count, 1)
        XCTAssertTrue(ids.contains("a-rand-1")); XCTAssertFalse(ids.contains("a-rand-2")); XCTAssertFalse(ids.contains("z"))
        XCTAssertEqual(ids.count, 10)
    }

    func testSocketTranslationsDraftsPillsAndClear() async {
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        await socket(host, #"{"type":"translations","conversationId":"c1","items":[{"id":"m3","text":"Inchi 16, mbili nyeusi","lang":"sw"}]}"#)
        let m3 = vm.thread.value.messages["c1"]!.first { $0.id == "m3" }!
        XCTAssertEqual(m3.translation, "Inchi 16, mbili nyeusi"); XCTAssertEqual(m3.translatedFrom, "sw")

        await socket(host, #"{"type":"ai_draft_ready","conversationId":"c1","draft":"Yes Father, Friday works."}"#)
        XCTAssertTrue(vm.composer.value.draftVisible); XCTAssertFalse(vm.composer.value.draftExpanded)
        XCTAssertEqual(vm.composer.value.draftText, "Yes Father, Friday works.")

        await socket(host, #"{"type":"intercept_changed","conversationId":"c1","eventKind":"release","eventAgentName":"Grace"}"#)
        await socket(host, #"{"type":"intercept_changed","conversationId":"c1","eventKind":"release","eventAgentName":"Grace"}"#)
        let live = vm.thread.value.messages["c1"]!.filter { $0.id.hasPrefix("live-evt-") }
        XCTAssertEqual(live.count, 1); XCTAssertEqual(live.first?.text, "Released to AI by Grace")

        await socket(host, #"{"type":"history_cleared","conversationId":"c1","clearedBy":"Grace"}"#)
        XCTAssertTrue(vm.thread.value.messages["c1"]!.isEmpty)
        XCTAssertEqual(host.toasts.last?.message, "History cleared by Grace")
    }

    // ═══════════════ Sending ═══════════════

    func testSendReplyOptimisticBubbleIsReplacedByTheServerRow() async {
        let serverHasIt = Ref(false)
        fake.on("GET", "/admin/conversations/[^/]+/messages") { _, _ in
            let extra = serverHasIt.value ? ["{\"id\":\"srv-1\",\"type\":\"message\",\"direction\":\"outbound\",\"sender\":\"human_agent\",\"text\":\"On its way Friday\",\"created_at\":\"\(Inbox.nowIso())\"}"] : []
            return (200, withRows(Fixtures.messages, extra))
        }
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ in serverHasIt.value = true; return (200, #"{"ok":true}"#) }
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("On its way Friday")
        vm.sendReply(); await drain()
        XCTAssertEqual(lastBody("POST", "/admin/conversations/c1/reply")["text"]?.content, "On its way Friday")
        let msgs = vm.thread.value.messages["c1"]!
        XCTAssertEqual(msgs.filter { $0.body == "On its way Friday" }.count, 1)
        XCTAssertEqual(msgs.last?.id, "srv-1")
        XCTAssertEqual(vm.composer.value.replyText, "")
    }

    func testSendReplyDeliveryFailureRestoresTheTextAndSaysWhy() async {
        fake.on("POST", "/admin/conversations/c1/reply", body: #"{"ok":false,"error":"Couldn't send the reply: window closed"}"#)
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setReplyText("Hello")
        vm.sendReply(); await drain()
        XCTAssertTrue(vm.thread.value.messages["c1"]!.allSatisfy { !$0.id.hasPrefix("optimistic-") })
        XCTAssertEqual(vm.composer.value.replyText, "Hello")
        XCTAssertEqual(host.toasts.last?.type, .error)
        XCTAssertEqual(host.toasts.last?.message, "Couldn't send the reply: window closed")
    }

    func testSendReplySameChannelQuoteThreadsCrossChannelQuotePrefixes() async {
        let (_, vm) = await vm()
        vm.select("c1"); await drain()
        let m6 = vm.thread.value.messages["c1"]!.first { $0.id == "m6" }!
        vm.beginReplyTo(m6)
        vm.setReplyText("Yes")
        vm.sendReply(); await drain()
        var b = lastBody("POST", "/admin/conversations/c1/reply")
        XCTAssertEqual(b["reply_to"]?.content, "m6"); XCTAssertEqual(b["text"]?.content, "Yes")
        // A quote grabbed on WhatsApp, answered on the Facebook sibling: a text prefix.
        vm.beginReplyTo(m6)
        vm.select("c5"); await drain()
        vm.setReplyText("Yes")
        vm.sendReply(); await drain()
        b = lastBody("POST", "/admin/conversations/c5/reply")
        XCTAssertNil(b["reply_to"])
        XCTAssertEqual(b["text"]?.content, "↩ Re (WhatsApp): \"Can you deliver to Nyeri by Friday?\"\n\nYes")
    }

    func testTranslateToggleSendsTheirLanguageWithTheEnglishAlong() async {
        fake.on("GET", "/admin/conversations/[^/]+/messages", body: "[{\"id\":\"t1\",\"type\":\"message\",\"direction\":\"inbound\",\"sender\":\"user\",\"text\":\"Habari\",\"created_at\":\"\(Fixtures.ago(3))\",\"translation\":\"Hello\",\"translated_from\":\"sw\"}]")
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        XCTAssertTrue(vm.txOn())          // ON by default: the thread reads foreign
        vm.setReplyText("Yes, Friday")
        await host.clock.advance(by: 701)
        XCTAssertEqual(lastBody("POST", "/admin/conversations/c1/translate-reply")["text"]?.content, "Yes, Friday")
        XCTAssertEqual(vm.composer.value.txPreview?.text, "Ndiyo, tutafikisha Ijumaa.")
        let before = calls("POST", "/admin/conversations/c1/translate-reply").count
        vm.sendReply(); await drain()
        // The preview is reused — nothing is translated twice.
        XCTAssertEqual(calls("POST", "/admin/conversations/c1/translate-reply").count, before)
        let b = lastBody("POST", "/admin/conversations/c1/reply")
        XCTAssertEqual(b["text"]?.content, "Ndiyo, tutafikisha Ijumaa.")
        XCTAssertEqual(b["original_text"]?.content, "Yes, Friday")
        XCTAssertEqual(b["original_lang"]?.content, "Swahili")   // translate_reply names the language
        vm.toggleTx()
        XCTAssertFalse(vm.txOn())
    }

    // ═══════════════ Controls → endpoints ═══════════════

    func testControlsCallTheRightEndpointsWithTheRightBodiesAndSucceed() async {
        let (host, vm) = await vm()
        vm.select("c2"); await drain()
        vm.intercept("c2"); await drain()
        XCTAssertEqual(calls("POST", "/admin/conversations/c2/intercept").count, 1)
        XCTAssertEqual(calls("POST", "/admin/conversations/c2/intercept").first?.body, "{}")
        XCTAssertEqual(host.toasts.last?.message, "Conversation claimed — you now control replies")
        XCTAssertEqual(host.toasts.last?.type, .success)
        vm.pause("c2"); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Paused — Neema holds all replies until you resume")
        vm.release("c2"); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Conversation released back to AI")
        vm.transfer(agentId: Fixtures.AGENT2_ID, agentName: "Grace Wanjiru"); await drain()
        XCTAssertEqual(lastBody("POST", "/admin/conversations/c2/transfer")["agent_id"]?.content, Fixtures.AGENT2_ID)
        XCTAssertEqual(host.toasts.last?.message, "Transferred to Grace Wanjiru")
        XCTAssertTrue(vm.thread.value.busy.isEmpty)
    }

    func testInterceptConflictSaysAlreadyClaimed() async {
        fake.on("POST", "/admin/conversations/[^/]+/intercept", code: 409, body: #"{"detail":"Already intercepted"}"#)
        let (host, vm) = await vm()
        vm.intercept("c2"); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Already claimed by another agent")
        fake.on("POST", "/admin/conversations/[^/]+/pause", code: 409, body: #"{"detail":"held"}"#)
        vm.pause("c2"); await drain()
        XCTAssertEqual(host.toasts.last?.message, "Handled by another agent — they must pause it")
    }

    func testNoteDraftClearBodies() async {
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.showNote(true); vm.setNoteText("  Measure on Friday  "); vm.saveNote(); await drain()
        XCTAssertEqual(lastBody("POST", "/admin/conversations/c1/note")["text"]?.content, "Measure on Friday")
        XCTAssertFalse(vm.dialogs.value.note)

        vm.generateDraft(); await drain()
        XCTAssertTrue(fake.called("POST", "/admin/conversations/c1/generate-draft"))
        XCTAssertTrue(vm.composer.value.draftVisible && vm.composer.value.draftExpanded)
        vm.setDraftText("Edited draft")
        vm.approveDraft(); await drain()
        XCTAssertEqual(lastBody("POST", "/admin/conversations/c1/approve-draft")["text"]?.content, "Edited draft")
        XCTAssertEqual(host.toasts.last?.message, "AI draft approved & sent")
        XCTAssertFalse(vm.composer.value.draftVisible)

        vm.showClear(true); vm.clearHistory(); await drain()
        XCTAssertEqual(calls("DELETE", "/admin/conversations/c1/messages").count, 1)
        XCTAssertTrue(vm.thread.value.messages["c1"]!.isEmpty)
        XCTAssertFalse(vm.dialogs.value.clearConfirm)
    }

    /// Refused (a 4xx): nothing was saved, so the note goes back in its box.
    func testNoteFailurePutsTheNoteBack() async {
        fake.on("POST", "/admin/conversations/[^/]+/note", code: 422, body: #"{"detail":"text is required"}"#)
        let (host, vm) = await vm()
        vm.select("c1"); await drain()
        vm.setNoteText("Keep me"); vm.saveNote(); await drain()
        XCTAssertTrue(vm.dialogs.value.note); XCTAssertEqual(vm.dialogs.value.noteText, "Keep me")
        XCTAssertTrue(vm.thread.value.messages["c1"]!.allSatisfy { !$0.id.hasPrefix("optimistic-note-") })
        XCTAssertEqual(host.toasts.last?.message, "Failed to save note")
    }

    func testClearForbiddenSaysSo() async {
        fake.on("DELETE", "/admin/conversations/[^/]+/messages", code: 403, body: #"{"detail":"Only admins can clear chat history"}"#)
        let (host, vm) = await vm()
        vm.select("c1"); await drain(); vm.clearHistory(); await drain()
        XCTAssertEqual(host.toasts.last?.message, "You don't have permission to clear chat history")
    }

    func testBulkReleaseReleasesOnlyHumanHeldThreads() async {
        let (host, vm) = await vm()
        vm.enterSelect("p1")          // Fr. Peter — c1 held, c5 with Neema
        vm.toggleRow("c6")            // held by Grace
        vm.toggleRow("c2")            // with Neema: selectable, costs nothing
        XCTAssertEqual(Set(vm.selectedHeldIds()), ["c1", "c6"])
        vm.releaseSelected(); await drain()
        XCTAssertEqual(Set(fake.calls.filter { $0.method == "POST" && $0.path.hasSuffix("/release") }.map { $0.path }),
                       ["/admin/conversations/c1/release", "/admin/conversations/c6/release"])
        XCTAssertEqual(host.toasts.last?.message, "2 conversations released back to Neema")
        XCTAssertFalse(vm.list.value.selectMode)
    }

    func testBulkReleaseNothingHeldWarns() async {
        let (host, vm) = await vm()
        vm.enterSelect("c2")
        vm.releaseSelected(); await drain()
        XCTAssertEqual(host.toasts.last?.message, "None of those are held by a human")
        XCTAssertFalse(fake.calls.contains { $0.path.hasSuffix("/release") })
    }

    func testChangingTheListClearsThePicks() async {
        let (_, vm) = await vm()
        vm.enterSelect("p1")
        vm.setTab("human"); await drain()
        XCTAssertTrue(vm.list.value.selected.isEmpty)
        vm.toggleRow("c6")
        vm.setMode("paused"); await drain()          // like the web, the mode filter keeps the picks
        XCTAssertEqual(vm.list.value.selected, ["c6"])
    }
}
