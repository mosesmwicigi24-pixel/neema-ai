import Foundation
import XCTest
@testable import NeemaCore

/// The inbox stays live (Android `InboxLiveTest`). Every conversation frame
/// the backend publishes is pushed through a real `LiveSocket` on a fake
/// WebSocket, on virtual time: the list rows move, badges refetch once per
/// burst, the open thread paints without duplicates, and anything missed
/// while the socket was down or the app was away is caught up without a
/// pull-to-refresh.
@MainActor
final class InboxLiveTests: XCTestCase {
    var fake: FakeNeema!

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        InboxFixtures.install(fake)
    }

    override func tearDown() async throws { AppClock.reset(); try await super.tearDown() }

    /// A signed-in inbox with its socket open.
    func live() async -> (TestHost, InboxViewModel) {
        let host = TestHost(fake: fake)
        let vm = InboxViewModel(host: host, sleep: host.clock.sleeper)
        host.connectLive()
        await drain()
        return (host, vm)
    }

    func frame(_ host: TestHost, _ text: String) async { host.sockets.last.frame(text); await drain() }
    func advance(_ host: TestHost, _ ms: Int64) async { await host.clock.advance(by: ms) }
    func listFetches() -> Int { fake.callsTo("GET", "/admin/conversations").count }
    func threadFetches(_ id: String) -> Int { fake.callsTo("GET", "/admin/conversations/\(id)/messages").count }
    func row(_ vm: InboxViewModel, _ id: String) -> Conversation { vm.inbox.value.cache[id]! }
    func msgs(_ vm: InboxViewModel, _ id: String) -> [ThreadMsg] { vm.thread.value.messages[id] ?? [] }

    // ═══════════════ Rows move the moment a frame lands ═══════════════

    func testNewMessageMovesTheRowToTheTopNowThenOneRefetchConfirms() async {
        let (host, vm) = await live()
        let before = listFetches()
        XCTAssertNotEqual(vm.rows.first?.rep.id, "c3")
        await frame(host, #"{"type":"new_message","conversationId":"c3","sender":"user","text":"Nimefika — the photo is of the stole","waId":"255754333222"}"#)
        // Live: top of the list, the preview and the unread count, with no request yet.
        XCTAssertEqual(vm.rows.first?.rep.id, "c3")
        XCTAssertEqual(row(vm, "c3").lastMessagePreview, "Nimefika — the photo is of the stole")
        XCTAssertEqual(row(vm, "c3").unread, 1)
        XCTAssertEqual(listFetches(), before)
        // 1.5 s later the list and badges refetch — once.
        fake.on("GET", "/admin/conversations/summary", body: #"{"unread":4,"human":2,"yours":1,"unread_messages":{"all":5,"whatsapp":4,"messenger":1},"tags":["bulk","clergy","vip"]}"#)
        await advance(host, 1_500)
        XCTAssertEqual(listFetches(), before + 1)
        XCTAssertEqual(host.inboxSummary.value?.unread, 4)
        XCTAssertEqual(vm.inbox.value.summary?.unread, 4)
    }

    func testOutboundReplyZeroesUnreadLikeTheServerCounts() async {
        let (host, vm) = await live()
        XCTAssertEqual(row(vm, "c2").unread, 1)
        await frame(host, #"{"type":"new_message","conversationId":"c2","sender":"ai","text":"The purple cassock is KES 12,500."}"#)
        XCTAssertEqual(row(vm, "c2").unread, 0)
        XCTAssertEqual(row(vm, "c2").lastMessagePreview, "The purple cassock is KES 12,500.")
        // A media frame with no text keeps the last preview rather than blanking it.
        await frame(host, #"{"type":"new_message","conversationId":"c2","sender":"user","text":"","mediaType":"image","mediaUrl":"https://x/p.jpg"}"#)
        XCTAssertEqual(row(vm, "c2").lastMessagePreview, "The purple cassock is KES 12,500.")
        XCTAssertEqual(row(vm, "c2").unread, 1)
    }

    /// Web chat, ManyChat, TikTok and the Tier-2 agent's replies use `type:"message"`.
    func testLegacyMessageFramePaintsInTheOpenThreadAndMovesTheRow() async {
        let (host, vm) = await live()
        vm.select("c7"); await drain()
        let before = listFetches()
        // web_chat.py: direction but no sender — the customer.
        await frame(host, #"{"type":"message","conversationId":"c7","waId":"web_3fa9c1e20b7d4c5a9e11","direction":"inbound","text":"Hello from the website"}"#)
        let m = msgs(vm, "c7").last!
        XCTAssertEqual(m.text, "Hello from the website"); XCTAssertEqual(m.direction, "inbound"); XCTAssertEqual(m.sender, "user")
        XCTAssertEqual(vm.rows.first?.rep.id, "c7")
        // n8n_bridge.save_outbound_message: the Tier-2 agent's WhatsApp reply.
        await frame(host, #"{"type":"message","conversationId":"c7","waId":"web_3fa9c1e20b7d4c5a9e11","direction":"outbound","text":"Yes — we ship to Kampala."}"#)
        let r = msgs(vm, "c7").last!
        XCTAssertEqual(r.direction, "outbound"); XCTAssertEqual(r.sender, "ai")
        XCTAssertEqual(row(vm, "c7").unread, 0)
        await advance(host, 1_500)
        XCTAssertEqual(listFetches(), before + 1)
        // The next poll brings the server rows; the live bubbles give way to them (no doubles).
        fake.on("GET", "/admin/conversations/c7/messages", body: """
          [
          {"id":"s1","type":"message","direction":"inbound","sender":"user","text":"Hello from the website","created_at":"\(Inbox.nowIso())"},
          {"id":"s2","type":"message","direction":"outbound","sender":"ai","text":"Yes — we ship to Kampala.","created_at":"\(Inbox.nowIso())"}]
          """)
        await advance(host, 20_000)
        XCTAssertEqual(Array(msgs(vm, "c7").filter { !$0.isSystem }.map { $0.id }.suffix(2)), ["s1", "s2"])
        XCTAssertEqual(msgs(vm, "c7").filter { $0.text == "Hello from the website" || $0.text == "Yes — we ship to Kampala." }.count, 2)
    }

    /// Channel sends (Messenger/IG/FB) name the channel and the sender; a comment reply's reply_to is a comment id, not a quote.
    func testLegacyChannelSendWithCommentReplyIdPaintsPlainly() async {
        let (host, vm) = await live()
        vm.select("c2"); await drain()
        await frame(host, #"{"type":"message","conversationId":"c2","channel":"messenger","sender":"ai","direction":"outbound","text":"Sent you a DM 🙏","reply_to":"cmt_1"}"#)
        let m = msgs(vm, "c2").last!
        XCTAssertEqual(m.text, "Sent you a DM 🙏"); XCTAssertNil(m.replyTo); XCTAssertEqual(m.sender, "ai")
    }

    // ═══════════════ Bursts, duplicates, order ═══════════════

    func testBurstOfFramesAcrossThreadsIsOneRefetchNotAStorm() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain()
        await advance(host, 3_000) // opening cleared c1's badge; its quiet refresh has run
        let before = listFetches()
        for i in 0..<30 {
            let id = ["c1", "c2", "c3", "c4"][i % 4]
            await frame(host, "{\"type\":\"new_message\",\"conversationId\":\"\(id)\",\"sender\":\"user\",\"text\":\"burst \(i)\"}")
            await advance(host, 40) // 30 frames over 1.2 s
        }
        XCTAssertEqual(listFetches(), before)
        await advance(host, 300)
        XCTAssertEqual(listFetches(), before + 1)
        // Frames still pouring in after it ran get their own single refetch.
        await frame(host, "{\"type\":\"intercept_changed\",\"conversationId\":\"c2\",\"mode\":\"human\",\"assignedAgentId\":\"\(Fixtures.AGENT2_ID)\",\"assignedAgentName\":\"Grace Wanjiru\",\"eventKind\":\"intercept\",\"eventAgentName\":\"Grace Wanjiru\"}")
        await frame(host, #"{"type":"history_cleared","conversationId":"c4","clearedBy":"Grace"}"#)
        await advance(host, 1_500)
        XCTAssertEqual(listFetches(), before + 2)
        // Every c1 burst frame landed once, in order.
        XCTAssertEqual(msgs(vm, "c1").filter { $0.text?.hasPrefix("burst") == true }.map { $0.text }, stride(from: 0, to: 30, by: 4).map { "burst \($0)" })
    }

    func testDuplicatesAreDroppedButACustomersRepeatedOkIsKept() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain()
        let base = msgs(vm, "c1").count
        // The AI reply carries the DB id: delivered twice, shown once.
        for _ in 0..<2 { await frame(host, #"{"type":"new_message","conversationId":"c1","id":"db-9","sender":"ai","text":"Friday works 🙏"}"#) }
        // An id-less outbound relayed twice (both frame shapes for one send).
        await frame(host, #"{"type":"new_message","conversationId":"c1","sender":"ai","text":"Sending the M-Pesa details now"}"#)
        await frame(host, #"{"type":"message","conversationId":"c1","direction":"outbound","text":"Sending the M-Pesa details now"}"#)
        // The customer really did say "ok" twice.
        for _ in 0..<2 { await frame(host, #"{"type":"new_message","conversationId":"c1","sender":"user","text":"ok"}"#) }
        let added = Array(msgs(vm, "c1").dropFirst(base))
        XCTAssertEqual(added.map { $0.text }, ["Friday works 🙏", "Sending the M-Pesa details now", "ok", "ok"])
    }

    func testOutOfOrderFrameWithAnOlderTimestampSortsIntoPlace() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain()
        let t = AppClock.now()
        await frame(host, "{\"type\":\"new_message\",\"conversationId\":\"c1\",\"id\":\"late\",\"sender\":\"ai\",\"text\":\"second\",\"created_at\":\"\(Inbox.iso(ofMillis: t))\"}")
        await frame(host, "{\"type\":\"new_message\",\"conversationId\":\"c1\",\"id\":\"early\",\"sender\":\"user\",\"text\":\"first\",\"created_at\":\"\(Inbox.iso(ofMillis: t - 30_000))\"}")
        let shown = ThreadRows.sort(msgs(vm, "c1")).map { $0.id }
        XCTAssertLessThan(shown.firstIndex(of: "early")!, shown.firstIndex(of: "late")!)
    }

    // ═══════════════ Threads that aren't open, rows not loaded ═══════════════

    func testFramesForAThreadThatIsNotOpenTouchOnlyItsRow() async {
        let (host, vm) = await live()
        vm.select("c2"); await drain(); vm.select("c1"); await drain() // c2's thread is cached, c1 is open
        let c1Before = msgs(vm, "c1")
        let c2Before = msgs(vm, "c2")
        let composerBefore = vm.composer.value
        await frame(host, #"{"type":"new_message","conversationId":"c2","sender":"user","text":"Are you open Saturday?"}"#)
        await frame(host, #"{"type":"ai_draft_ready","conversationId":"c2","draft":"We are, 9–1."}"#)
        await frame(host, #"{"type":"translations","conversationId":"c2","items":[{"id":"m1","text":"x","lang":"sw"}]}"#)
        await frame(host, #"{"type":"intercept_changed","conversationId":"c2","eventKind":"escalated"}"#)
        XCTAssertEqual(msgs(vm, "c1"), c1Before)
        XCTAssertEqual(msgs(vm, "c2"), c2Before)           // not painted into a closed thread (the web's rule)
        XCTAssertEqual(vm.composer.value, composerBefore)  // another thread's draft is not this one's pill
        XCTAssertEqual(row(vm, "c2").lastMessagePreview, "Are you open Saturday?")
        // A clear on a cached-but-closed thread empties it, quietly.
        let toastsBefore = host.toasts.count
        await frame(host, #"{"type":"history_cleared","conversationId":"c2","clearedBy":"Grace"}"#)
        XCTAssertTrue(msgs(vm, "c2").isEmpty)
        XCTAssertNil(row(vm, "c2").lastMessagePreview); XCTAssertEqual(row(vm, "c2").unread, 0)
        XCTAssertEqual(host.toasts.count, toastsBefore)
    }

    func testFrameForAConversationNotLoadedYetAppearsWithTheRefetch() async {
        let (host, vm) = await live()
        XCTAssertNil(vm.inbox.value.cache["c99"])
        await frame(host, #"{"type":"new_message","conversationId":"c99","sender":"user","text":"Hello, new here"}"#)
        // Nothing invented locally…
        XCTAssertNil(vm.inbox.value.cache["c99"])
        XCTAssertNil(vm.thread.value.messages["c99"])
        // …the refetch brings the real row, on top.
        let newcomer = Fixtures.conv("c99", "Br. Paul Otieno", "254700111222", "whatsapp", "ai", "Hello, new here", 0, unread: 1)
        fake.on("GET", "/admin/conversations", body: "{\"items\":[\(newcomer),\(Fixtures.inbox.joined(separator: ","))],\"next_cursor\":\"cursor-2\"}")
        await advance(host, 1_500)
        XCTAssertEqual(vm.rows.first?.rep.id, "c99")
        XCTAssertEqual(row(vm, "c99").unread, 1)
    }

    func testNewRowOnASearchWaitsForTheServer() async {
        let (host, vm) = await live()
        let first = Fixtures.inbox.first!
        fake.on("GET", "/admin/conversations") { r, _ in
            (200, r.param("q") == "Peter" ? "{\"items\":[\(first)],\"next_cursor\":null}" : Fixtures.conversationPage)
        }
        vm.setSearch("Peter"); await advance(host, 301)
        XCTAssertEqual(vm.rows.map { $0.rep.id }, ["c1"])
        await frame(host, #"{"type":"new_message","conversationId":"c4","sender":"user","text":"albs?"}"#)
        XCTAssertFalse(vm.rows.contains { $0.rep.id == "c4" })
    }

    // ═══════════════ Mode changes, drafts, translations, clears ═══════════════

    func testInterceptChangedSetsTheRowsModeAndOwnerAndOnePillPerKind() async {
        let (host, vm) = await live()
        vm.select("c2"); await drain()
        await frame(host, "{\"type\":\"intercept_changed\",\"conversationId\":\"c2\",\"mode\":\"human\",\"assignedAgentId\":\"\(Fixtures.ME_ID)\",\"assignedAgentName\":\"Moses Mwicigi\",\"eventKind\":\"intercept\",\"eventAgentName\":\"Moses Mwicigi\"}")
        XCTAssertEqual(row(vm, "c2").interceptMode, "human"); XCTAssertEqual(row(vm, "c2").assignedAgentId, Fixtures.ME_ID)
        XCTAssertEqual(row(vm, "c2").assignedAgentName, "Moses Mwicigi")
        // The "Yours" tab counts it at once.
        vm.setTab("yours"); await drain()
        await frame(host, "{\"type\":\"intercept_changed\",\"conversationId\":\"c2\",\"mode\":\"human\",\"assignedAgentId\":\"\(Fixtures.ME_ID)\",\"eventKind\":\"intercept\",\"eventAgentName\":\"Moses Mwicigi\"}")
        XCTAssertEqual(msgs(vm, "c2").filter { $0.id.hasPrefix("live-evt-") && $0.eventKind == "intercept" }.count, 1)
        // Released: no owner.
        await frame(host, #"{"type":"intercept_changed","conversationId":"c2","mode":"ai","assignedAgentId":null,"eventKind":"release","eventAgentName":"Moses Mwicigi"}"#)
        XCTAssertEqual(row(vm, "c2").interceptMode, "ai"); XCTAssertNil(row(vm, "c2").assignedAgentId)
        // An AI escalation carries no mode: the row waits for the refetch, the pill shows now.
        await frame(host, #"{"type":"intercept_changed","conversationId":"c2","eventKind":"escalated","eventReason":"Asked for a custom quote"}"#)
        XCTAssertEqual(row(vm, "c2").interceptMode, "ai")
        XCTAssertEqual(msgs(vm, "c2").last?.text, "Escalated — needs human")
    }

    func testAiDraftShowsAPillNotExpandedAndTranslationsFillInPlaceOnce() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain()
        await frame(host, #"{"type":"ai_draft_ready","conversationId":"c1","draft":"Yes Father, Friday works.","waId":"254712345678"}"#)
        let c = vm.composer.value
        XCTAssertTrue(c.draftVisible); XCTAssertFalse(c.draftExpanded); XCTAssertEqual(c.draftText, "Yes Father, Friday works.")
        await frame(host, #"{"type":"translations","conversationId":"c1","items":[{"id":"m3","text":"Inchi 16, mbili nyeusi","lang":"sw"},{"id":"nope","text":"x","lang":null}]}"#)
        let snap = vm.thread.value
        XCTAssertEqual(msgs(vm, "c1").first { $0.id == "m3" }?.translation, "Inchi 16, mbili nyeusi")
        // The same frame again changes nothing — not even the state object.
        await frame(host, #"{"type":"translations","conversationId":"c1","items":[{"id":"m3","text":"other","lang":"sw"}]}"#)
        XCTAssertEqual(vm.thread.value, snap)
    }

    func testHistoryClearedEmptiesTheOpenThreadAndTheRow() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain()
        await frame(host, #"{"type":"history_cleared","conversationId":"c1","clearedBy":"Grace Wanjiru"}"#)
        XCTAssertTrue(msgs(vm, "c1").isEmpty)
        XCTAssertNil(row(vm, "c1").lastMessagePreview)
        XCTAssertEqual(host.toasts.last?.message, "History cleared by Grace Wanjiru")
    }

    // ═══════════════ Agent notifications ═══════════════

    func testAgentNotificationsNeverPaintABubbleAndOnlyAnSmsArrivalRefetchesHere() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain()
        await advance(host, 3_000)
        let base = msgs(vm, "c1")
        let before = listFetches()
        // The shell refetches for these kinds; the inbox adds nothing.
        await frame(host, #"{"event":"notification","type":"intercept","title":"Picked up","body":"Grace took Fr. Peter","conversationId":"c1"}"#)
        await frame(host, #"{"event":"notification","type":"draft_ready","title":"Draft ready","body":"…","conversationId":"c1"}"#)
        await advance(host, 1_500)
        XCTAssertEqual(listFetches(), before)
        // sms.py's `new_message` ping is not a thread frame, but it is a new message.
        await frame(host, #"{"event":"notification","type":"new_message","title":"New SMS","body":"Hello","conv_id":"c1"}"#)
        await advance(host, 1_500)
        XCTAssertEqual(listFetches(), before + 1)
        XCTAssertEqual(msgs(vm, "c1"), base)
    }

    // ═══════════════ Missed events: reconnect and foreground ═══════════════

    func testReconnectCatchesUpTheListAndTheOpenThreadOnce() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain()
        await advance(host, 5_000)
        let list0 = listFetches(), thread0 = threadFetches("c1")
        // The socket drops; a message arrives server-side meanwhile and its frame is lost.
        host.sockets.last.fail()
        fake.on("GET", "/admin/conversations/c1/messages", body: withRows(Fixtures.messages, ["{\"id\":\"missed\",\"type\":\"message\",\"direction\":\"inbound\",\"sender\":\"user\",\"text\":\"Did you get my photo?\",\"created_at\":\"\(Inbox.nowIso())\"}"]))
        await advance(host, 2_000) // LiveSocket reconnects after 2 s
        XCTAssertEqual(host.sockets.count, 2)
        XCTAssertEqual(listFetches(), list0)
        host.sockets.last.open(); await drain()
        XCTAssertEqual(listFetches(), list0 + 1)
        XCTAssertEqual(threadFetches("c1"), thread0 + 1)
        XCTAssertTrue(msgs(vm, "c1").contains { $0.id == "missed" })
        // The app coming to the front right after is the same catch-up, not a second one.
        host.foreground.value = false; await drain()
        host.foreground.value = true; await drain()
        XCTAssertEqual(listFetches(), list0 + 1)
    }

    func testForegroundReturnRefetchesAndPicksUpADraftWrittenMeanwhile() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain() // human-held, mine; no draft yet
        XCTAssertFalse(vm.composer.value.draftVisible)
        await advance(host, 5_000)
        host.foreground.value = false; await drain()
        let list0 = listFetches(), thread0 = threadFetches("c1")
        // Away for ten minutes: neither poll runs.
        fake.on("GET", "/admin/conversations/c1/latest-draft", body: #"{"draft":"Father, Friday is confirmed 🙏"}"#)
        await advance(host, 10 * 60_000)
        XCTAssertEqual(listFetches(), list0); XCTAssertEqual(threadFetches("c1"), thread0)
        host.foreground.value = true; await drain()
        XCTAssertEqual(listFetches(), list0 + 1)
        XCTAssertEqual(threadFetches("c1"), thread0 + 1)
        let c = vm.composer.value
        XCTAssertTrue(c.draftVisible); XCTAssertFalse(c.draftExpanded); XCTAssertEqual(c.draftText, "Father, Friday is confirmed 🙏")
        // The poll tick that fell due while away does not fetch a second time on return.
        await advance(host, 59_000)
        XCTAssertEqual(listFetches(), list0 + 1)
    }

    func testPollCadencesMatchTheWebListEveryMinuteThreadEvery20s() async {
        let (host, vm) = await live()
        vm.select("c2"); await drain()
        await advance(host, 3_000)
        let list0 = listFetches(), thread0 = threadFetches("c2")
        await advance(host, 20_000)
        XCTAssertEqual(threadFetches("c2"), thread0 + 1)
        await advance(host, 40_000)
        XCTAssertEqual(threadFetches("c2"), thread0 + 3)
        XCTAssertEqual(listFetches(), list0 + 1)
    }

    func testSignedOutNoCatchUp() async {
        let (host, vm) = await live()
        vm.select("c1"); await drain()
        await advance(host, 5_000)
        host.sessionStore.clear()
        let list0 = listFetches()
        host.foreground.value = false; await drain()
        host.foreground.value = true; await drain()
        await advance(host, 120_000)
        XCTAssertEqual(listFetches(), list0)
    }

    // ═══════════════ Attachments stream through the core UploadFile ═══════════════

    func testUploadStreamsTheFileAndResendsItWholeAfterATokenRefresh() async throws {
        let file = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("measure-\(UUID().uuidString).pdf")
        try "%PDF-1.4 two black shirts, 16 inch".write(to: file, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: file) }
        let n = Ref(0)
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ in
            defer { n.mutate { $0 += 1 } }
            return n.value == 0 ? (401, #"{"detail":"Token expired"}"#) : (200, InboxFixtures.Contract.uploaded("document", "https://x/m.pdf", "Sizes"))
        }
        // A new pair, not the same token string back.
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ in (200, Fixtures.tokenResponse(access: fakeJwt(expiresInSec: 7_200))) }
        let host = TestHost(fake: fake)
        let item = PickedMedia(id: "1", file: file, name: "measure.pdf", mime: "application/pdf", size: 35, caption: "Sizes")
        let msg = try await InboxApi(http: host.http).upload(convId: "c1", item: item)
        XCTAssertEqual(msg.id, "srv-u1")
        let sent = fake.callsTo("POST", "/admin/conversations/c1/upload-media").map { $0.body! }
        XCTAssertEqual(sent.count, 2)
        for b in sent {
            XCTAssertTrue(b.contains("filename=\"measure.pdf\""), b); XCTAssertTrue(b.contains("Content-Type: application/pdf"), b)
            XCTAssertTrue(b.contains("%PDF-1.4 two black shirts, 16 inch"), b)
        }
    }
}

/// Owner, 2026-09-26: "The Facebook messages, Messenger and IG are not current"
/// on the phone while the web was current. On the live server the inbox page
/// takes seconds, and on a busy day a frame lands every second or so. Every
/// frame scheduled a refresh 1.5 s later, and every refresh CANCELLED the
/// page request still on its way — so no page ever arrived. A refresh now
/// joins the one in flight and runs once more after it; only a change of
/// filter cancels (Android `InboxBusyServerTest`).
@MainActor
final class InboxBusyServerTests: XCTestCase {
    var fake: FakeNeema!

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        InboxFixtures.install(fake)
    }

    override func tearDown() async throws { AppClock.reset(); try await super.tearDown() }

    func live() async -> (TestHost, InboxViewModel) {
        let host = TestHost(fake: fake)
        let vm = InboxViewModel(host: host, sleep: host.clock.sleeper)
        host.connectLive()
        await drain()
        return (host, vm)
    }

    /// Today's Messenger thread, on page one of the server's inbox.
    let newMessenger = #"{"id":"m-today","wa_id":null,"external_id":"psid-778899","person_id":"p-today","channel":"messenger","name":"Grace Wanjiru","intercept_mode":"ai","status":"open","unread":1,"last_message_at":"2026-09-25T09:00:30+00:00","last_message_preview":"Do you have the purple stole?","created_at":"2026-09-25T09:00:30+00:00","tags":[]}"#

    func serveToday() {
        let body = "{\"items\":[\(newMessenger),\(InboxFixtures.conversations.joined(separator: ","))],\"next_cursor\":null}"
        fake.on("GET", "/admin/conversations") { _, _ in (200, body) }
    }

    func testASlowServerUnderSteadyTrafficStillDeliversTheNewestPage() async {
        let (host, vm) = await live()
        XCTAssertNil(vm.inbox.value.cache["m-today"])
        // The live server: three seconds for a page, and today's Messenger thread on it.
        serveToday()
        fake.delay("GET", "/admin/conversations", ms: 3_000)
        // A frame every second for half a minute (other threads moving).
        for i in 0..<30 {
            host.sockets.last.frame("{\"type\":\"new_message\",\"conversationId\":\"c2\",\"sender\":\"ai\",\"text\":\"Reply \(i)\"}")
            await drain()
            await host.clock.advance(by: 1_000)
        }
        XCTAssertTrue(vm.rows.contains { $0.rep.id == "m-today" }, "today's Messenger thread reached the list while traffic kept flowing")
    }

    func testRefreshesDuringALoadJoinItAndOneMoreRunsAfterNoneCancelled() async {
        let (host, vm) = await live()
        serveToday()
        fake.delay("GET", "/admin/conversations", ms: 3_000)
        let before = fake.callsTo("GET", "/admin/conversations").count
        vm.refresh()          // starts a load
        await host.clock.advance(by: 500)
        vm.refresh(); vm.refresh(); vm.refresh()   // three more ask while it is on its way
        await host.clock.advance(by: 3_000)        // the first answers…
        XCTAssertTrue(vm.rows.contains { $0.rep.id == "m-today" })
        await host.clock.advance(by: 3_500)        // …and exactly one follow-up runs for the three
        XCTAssertEqual(fake.callsTo("GET", "/admin/conversations").count, before + 2)
        await host.clock.advance(by: 10_000)
        XCTAssertEqual(fake.callsTo("GET", "/admin/conversations").count, before + 2, "nothing further queued")
    }

    func testChangingTheChannelTabStillCancelsTheOldFiltersLoad() async {
        let (host, vm) = await live()
        fake.delay("GET", "/admin/conversations", ms: 3_000)
        let before = fake.callsTo("GET", "/admin/conversations").count
        vm.refresh()
        await host.clock.advance(by: 500)
        vm.setChannel("messenger")
        await host.clock.advance(by: 3_500)
        let since = fake.callsTo("GET", "/admin/conversations").dropFirst(before)
        XCTAssertTrue(since.contains { $0.params["channel"] == "messenger" }, "the Messenger page was fetched")
        // The unfiltered load was abandoned: its answer never replaced the Messenger list.
        XCTAssertEqual(vm.inbox.value.orderKey, Inbox.filterKey(of: InboxQuery(channel: "messenger")))
        XCTAssertTrue(vm.rows.allSatisfy { $0.rep.channel == "messenger" })
        XCTAssertFalse(vm.inbox.value.loading)
    }
}
