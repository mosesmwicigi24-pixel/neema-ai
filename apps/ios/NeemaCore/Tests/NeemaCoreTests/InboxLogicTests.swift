import XCTest
@testable import NeemaCore

/// Pure logic ported from the web: WaText, thread merge/dedupe, thread rows, keys (Android's InboxLogicTest).
final class InboxLogicTests: XCTestCase {
    private func styled(_ f: WaFormatted) -> [(String, String)] { f.spans.map { ($0.style.rawValue, f.text(of: $0)) } }
    private func assertStyled(_ f: WaFormatted, _ expected: [(String, String)], file: StaticString = #filePath, line: UInt = #line) {
        let got = styled(f)
        XCTAssertEqual(expected.map { "\($0.0):\($0.1)" }, got.map { "\($0.0):\($0.1)" }, file: file, line: line)
    }

    // ── WaText (lib/waText.tsx) ──

    func testWaTextBasicMarks() {
        let a = WaText.format("*bold* _it_ ~gone~ `mono`")
        XCTAssertEqual("bold it gone mono", a.plain)
        assertStyled(a, [("bold", "bold"), ("italic", "it"), ("strike", "gone"), ("code", "mono")])
    }

    func testWaTextLegacyDoubleStarWinsOverSingle() {
        let a = WaText.format("**x** and *y*")
        XCTAssertEqual("x and y", a.plain)
        assertStyled(a, [("bold", "x"), ("bold", "y")])
    }

    func testWaTextTripleStarKeepsOuterStars() {
        let a = WaText.format("***b***")
        XCTAssertEqual("*b*", a.plain)
        assertStyled(a, [("bold", "b")])
    }

    func testWaTextMarksNeverCrossNewlines() {
        let a = WaText.format("*a\nb* and _c\nd_")
        XCTAssertEqual("*a\nb* and _c\nd_", a.plain)
        XCTAssertTrue(a.spans.isEmpty)
    }

    func testWaTextUnmatchedAndEmptyDelimitersStayLiteral() {
        XCTAssertEqual("2 * 3 = 6", WaText.format("2 * 3 = 6").plain)
        XCTAssertEqual("** __ ~~", WaText.format("** __ ~~").plain)
        let snake = WaText.format("snake_case_name")
        XCTAssertEqual("snakecasename", snake.plain)
        assertStyled(snake, [("italic", "case")])
        XCTAssertEqual("", WaText.format(nil).plain)
        XCTAssertEqual("", WaText.format("").plain)
    }

    func testWaTextMidWordMarksLikeTheWeb() {
        let a = WaText.format("a*b*c")
        XCTAssertEqual("abc", a.plain)
        assertStyled(a, [("bold", "b")])
    }

    func testWaTextTripleBacktickIsMonospace() {
        let a = WaText.format("```x = 1```")
        XCTAssertEqual("x = 1", a.plain)
        assertStyled(a, [("code", "x = 1")])
    }

    func testWaTextLinksAreTappableAndDropTrailingPunctuation() {
        let a = WaText.format("See https://bethanyhouse.co.ke/shop, or www.neema.ke.")
        XCTAssertEqual([("https://bethanyhouse.co.ke/shop", "https://bethanyhouse.co.ke/shop"), ("https://www.neema.ke", "www.neema.ke")].map { "\($0.0)|\($0.1)" },
                       a.links.map { "\($0.url)|\(a.text(of: $0))" })
    }

    func testWaTextLinkInsideBoldStillWorks() {
        let a = WaText.format("*https://x.co*")
        XCTAssertEqual("https://x.co", a.plain)
        XCTAssertEqual(1, a.links.count)
    }

    // ── Thread merge (mergeThread / mergeServer) ──

    private func m(_ id: String, _ sec: Int64, _ text: String? = nil, dir: String = "inbound", sender: String = "user", media: String? = nil,
                   type: String = "message", kind: String? = nil, agent: String? = nil, mediaType: String? = nil, comment: PostContext? = nil) -> ThreadMsg {
        let d = Date(timeIntervalSince1970: TimeInterval(1_800_000_000 + sec))
        let f = ISO8601DateFormatter()
        return ThreadMsg(id: id, type: type, direction: dir, sender: sender, text: text ?? id, createdAt: f.string(from: d), agentName: agent,
                         eventKind: kind, mediaType: mediaType ?? (media != nil ? "image" : nil), mediaUrl: media, commentContext: comment)
    }

    func testMergeThreadUnionsByIdNewestStateWinsSortedByTime() {
        let existing = [m("a", 1), m("b", 2, "old")]
        let incoming = [m("b", 2, "new"), m("c", 0)]
        let out = Inbox.mergeThread(existing, incoming)
        XCTAssertEqual(["c", "a", "b"], out.map { $0.id })
        XCTAssertEqual("new", out.last?.text)
    }

    func testMergeThreadOlderPageSlotsInWithoutDuplicates() {
        let page1 = (10...14).map { m("n\($0)", Int64($0)) }
        let older = (5...10).map { m("n\($0)", Int64($0)) }
        XCTAssertEqual((5...14).map { "n\($0)" }, Inbox.mergeThread(page1, older).map { $0.id })
    }

    func testMergeServerOptimisticReplacedByServerRow() {
        let opt = m("optimistic-1", 100, "Hello", dir: "outbound", sender: "human_agent")
        let server = [m("a", 1), m("srv-9", 101, "Hello", dir: "outbound", sender: "human_agent")]
        XCTAssertEqual(["a", "srv-9"], Inbox.mergeServer([m("a", 1), opt], server).map { $0.id })
    }

    func testMergeServerKeepsOptimisticUntilServerHasIt() {
        let opt = m("optimistic-1", 100, "Hello", dir: "outbound", sender: "human_agent")
        XCTAssertEqual(["a", "optimistic-1"], Inbox.mergeServer([opt], [m("a", 1)]).map { $0.id })
    }

    func testMergeServerLivePillDroppedWhenTheDbEventArrives() {
        let live = m("live-evt-1", 50, type: "system_event", kind: "intercept")
        XCTAssertEqual(["evt-x"], Inbox.mergeServer([live], [m("evt-x", 50, type: "system_event", kind: "intercept")]).map { $0.id })
    }

    func testAppendWsDedupeRules() {
        let base = [m("srv-1", 100, "ok", dir: "outbound", sender: "ai")]
        XCTAssertEqual(1, Inbox.appendWs(base, m("srv-1", 100, "ok")).count, "same id")
        let echo = m("ws-x", 101, "ok", dir: "outbound", sender: "ai")
        XCTAssertEqual(1, Inbox.appendWs(base, echo).count, "an id-less outbound echo of a server row within 120 s")
        let twice = Inbox.appendWs(Inbox.appendWs([], m("ws-a", 1, "ok", dir: "inbound", sender: "user")), m("ws-b", 1, "ok", dir: "inbound", sender: "user"))
        XCTAssertEqual(2, twice.count, "a customer's repeated 'ok' is never swallowed")
        let media = m("srv-2", 100, "", dir: "inbound", media: "https://m/1.jpg")
        XCTAssertEqual(1, Inbox.appendWs([media], m("ws-m", 105, "", dir: "inbound", media: "https://m/1.jpg")).count, "a media echo within 15 s")
        let opt = m("optimistic-9", 200, "Hi there", dir: "outbound", sender: "human_agent")
        XCTAssertEqual(1, Inbox.appendWs([opt], m("ws-h", 201, "Hi there ", dir: "outbound", sender: "human_agent")).count, "our own reply echoing while its optimistic bubble is up")
    }

    func testWsMessageFollowsTheSenderWhenTheDirectionIsMissing() {
        let inbound = Inbox.wsMessage(of: JSONValue.parse(#"{"type":"new_message","conversationId":"c1","sender":"user","text":"habari"}"#)!)!
        XCTAssertEqual("inbound", inbound.direction)
        XCTAssertTrue(inbound.id.hasPrefix("ws-"))
        let legacy = Inbox.wsMessage(of: JSONValue.parse(#"{"type":"message","conversationId":"c1","direction":"inbound","text":"x"}"#)!)!
        XCTAssertEqual("user", legacy.sender)
        let ai = Inbox.wsMessage(of: JSONValue.parse(#"{"type":"new_message","id":"m9","sender":"ai","text":"Karibu","replyTo":{"id":"m1","text":"q"}}"#)!)!
        XCTAssertEqual("m9", ai.id); XCTAssertEqual("outbound", ai.direction); XCTAssertEqual("m1", ai.replyTo?.id)
        XCTAssertNil(Inbox.wsMessage(of: JSONValue.parse(#"{"event":"notification","type":"new_message"}"#)!))
    }

    // ── Live pills (buildSystemEventFromWs) ──

    func testSystemEventFromWsLabels() {
        func ev(_ kind: String, agent: String? = nil, note: String? = nil) -> String {
            var o: [String: JSONValue] = ["type": "intercept_changed", "eventKind": .string(kind)]
            if let a = agent { o["eventAgentName"] = .string(a) }
            if let n = note { o["eventNote"] = .string(n) }
            return Inbox.systemEvent(fromWs: .object(o))!.text!
        }
        XCTAssertEqual("Escalated — needs human", ev("escalated"))
        XCTAssertEqual("Flagged: Needs Attention", ev("flag"))
        XCTAssertEqual("Picked up by Grace", ev("intercept", agent: "Grace"))
        XCTAssertEqual("Picked up by agent", ev("intercept"))
        XCTAssertEqual("Released to AI by Grace", ev("release", agent: "Grace"))
        XCTAssertEqual("Released to AI", ev("release"))
        XCTAssertEqual("Transferred — to sales", ev("transfer", note: "to sales"))
        XCTAssertEqual("Transferred", ev("transfer"))
        XCTAssertEqual("Paused by Grace — replies held", ev("pause", agent: "Grace"))
        XCTAssertEqual("Paused — replies held", ev("pause"))
        XCTAssertEqual("AI draft approved", ev("approve_draft"))
        XCTAssertNil(Inbox.systemEvent(fromWs: .object(["type": "intercept_changed"])))
        let e = Inbox.systemEvent(fromWs: .object(["eventKind": "escalated", "eventReason": "media"]))!
        XCTAssertTrue(e.id.hasPrefix("live-evt-")); XCTAssertEqual("system_event", e.type); XCTAssertEqual("media", e.eventReason)
    }

    func testLiveEventsHaveUniqueIdsEvenInOneMillisecond() {
        let ids = ["escalated", "intercept", "escalated"].map { Inbox.systemEvent(fromWs: .object(["type": "intercept_changed", "eventKind": .string($0)]))!.id }
        XCTAssertEqual(3, Set(ids).count)
        XCTAssertTrue(ids.allSatisfy { $0.hasPrefix("live-evt-") })
    }

    func testThreadRowsNeverRepeatAKey() {
        let list = ThreadRows.sort([m("u1", 1, "hi"), m("u1", 1, "hi"), m("u2", 2, "there")])
        let rows = ThreadRows.build(list, unreadSnap: 1)
        XCTAssertEqual(Array(Set(rows.map { $0.key })).count, rows.count)
        XCTAssertEqual(["u1", "new-divider", "u2"], rows.map { $0.key })
    }

    // ── Thread rows (the thread JSX) ──

    func testThreadRowsHandoffsHiddenFirstEscalationOnlyDividerAndAlbum() {
        let list = ThreadRows.sort([
            m("u1", 1, "hi"),
            m("esc1", 2, type: "system_event", kind: "escalated"),
            m("esc2", 3, type: "system_event", kind: "escalated"),
            m("rel", 4, type: "system_event", kind: "release"),
            m("pick", 5, type: "system_event", kind: "intercept", agent: "Moses"),
            m("p1", 6, "", dir: "inbound", media: "u/1"),
            m("p2", 7, "", dir: "inbound", media: "u/2"),
            m("u2", 8, "last"),
        ])
        let rows = ThreadRows.build(list, unreadSnap: 1)
        XCTAssertEqual(["u1", "esc1", "p1", "new-divider", "u2"], rows.map { $0.key })
        if case .bubble(_, let album) = rows[2] { XCTAssertEqual(2, album?.count) } else { XCTFail("expected a bubble with an album") }
    }

    func testThreadRowsMediaEscalationReason() {
        let list = ThreadRows.sort([
            m("img", 1, "", media: "u"),
            m("sys", 1, type: "system_event", kind: "intercept"),
        ])
        XCTAssertEqual(["img", "sys"], list.map { $0.id }, "the system intercept sorts just after the inbound it followed")
        let reasons = ThreadRows.build(list, unreadSnap: 0).compactMap { row -> String? in if case .escalated(_, let r) = row { return r } else { return nil } }
        XCTAssertEqual(["Media received — AI cannot process"], reasons)
    }

    func testThreadRowsPostCardOncePerRunOurRepliesDontBreakIt() {
        func c(_ id: String, _ sec: Int64, _ post: String?, reply: String? = nil) -> ThreadMsg {
            m(id, sec, "[comment] q", comment: PostContext(postId: post, title: "T", replyTo: reply))
        }
        let list = ThreadRows.sort([c("k1", 1, "p1"), c("r1", 2, "p1", reply: "k1"), c("k2", 3, "p1"), c("k3", 4, "p2")])
        let heads = ThreadRows.build(list, unreadSnap: 0).compactMap { row -> String? in if case .postHead = row { return row.key } else { return nil } }
        XCTAssertEqual(["post-k1", "post-k3"], heads)
    }

    // ── Keys and display ──

    func testFilterKeyDistinguishesEveryFilterAndTrimsSearch() {
        let base = Inbox.filterKey(of: InboxQuery())
        XCTAssertEqual(base, Inbox.DEFAULT_KEY)
        XCTAssertEqual(base, Inbox.filterKey(of: InboxQuery(q: "   ")))
        let keys = [InboxQuery(tab: "unread"), InboxQuery(channel: "whatsapp"), InboxQuery(mode: "ai"), InboxQuery(tag: "vip"), InboxQuery(q: "peter")].map(Inbox.filterKey(of:))
        XCTAssertEqual(keys.count, Set(keys + [base]).count - 1)
    }

    func testWebVisitorIsNeverShownAsAPhone() {
        var web = Conversation(id: "c", waId: "web_3fa9c1e20b7d4c5a9e11", channel: "whatsapp")
        XCTAssertEqual("Website visitor", Inbox.inboxName(web))
        XCTAssertEqual("Web chat", Inbox.inboxHandle(web))
        XCTAssertNil(Inbox.phoneDigits(web))
        web.name = "Amina"
        XCTAssertEqual("Amina", Inbox.inboxName(web))
        let wa = Conversation(id: "d", waId: "254712345678")
        XCTAssertEqual("+254 712 345 678", Inbox.inboxName(wa))
        XCTAssertEqual("254712345678", Inbox.phoneDigits(wa))
        XCTAssertNil(Inbox.phoneDigits(Conversation(id: "e", waId: "25898765432101234", channel: "facebook")))
    }

    func testNormalizedFallsBackLikeMapConversation() {
        let c = Inbox.normalized(Conversation(id: "x", waId: "2547", createdAt: "2026-01-01T00:00:00Z"))
        XCTAssertEqual("2547", c.externalId)
        XCTAssertEqual("2026-01-01T00:00:00Z", c.lastMessageAt)
    }

    func testUploadRules() {
        XCTAssertTrue(Inbox.uploadable(mime: "image/jpeg", name: "a.jpg"))
        XCTAssertTrue(Inbox.uploadable(mime: "application/octet-stream", name: "clip.MOV"))
        XCTAssertFalse(Inbox.uploadable(mime: "text/plain", name: "a.txt"))
        XCTAssertFalse(Inbox.uploadable(mime: "", name: "noext"))
        XCTAssertEqual("Image too large — max 5 MB.", Inbox.uploadError(of: ApiError(status: 413, method: "POST", path: "/x", body: #"{"detail":"Image too large — max 5 MB."}"#)))
        XCTAssertEqual("too large to upload", Inbox.uploadError(of: ApiError(status: 413, method: "POST", path: "/x", body: "<html>413</html>")))
        XCTAssertEqual("the server couldn't process this file", Inbox.uploadError(of: ApiError(status: 422, method: "POST", path: "/x", body: #"{"detail":[{"msg":"Field required"}]}"#)))
        XCTAssertEqual("upload timed out — check your connection and try again", Inbox.uploadError(of: ApiError(status: 0, method: "POST", path: "/x", body: "timed out after 10 min")))
        XCTAssertEqual("network error — try again", Inbox.uploadError(of: ApiError(status: 0, method: "POST", path: "/x", body: "Connection reset")))
        XCTAssertEqual("upload failed (500)", Inbox.uploadError(of: ApiError(status: 500, method: "POST", path: "/x", body: "")))
    }
}
