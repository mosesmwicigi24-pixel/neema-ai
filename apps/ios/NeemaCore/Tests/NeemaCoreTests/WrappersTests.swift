import XCTest
@testable import NeemaCore

/// The feature-level API wrappers: the inbox's thread shape, the CRM profile, leads and the team calls.
final class WrappersTests: XCTestCase {
    private final class Tokens: TokenProvider {
        func validAccessToken() async throws -> String? { "tok" }
        func forceRefresh() async throws -> String? { nil }
        func onRejected(_ token: String?) {}
    }

    private var fake: FakeNeema!
    private var http: NeemaHTTP!

    override func setUp() {
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        http = NeemaHTTP(baseUrl: "https://neema.test", tokens: Tokens(), transport: fake)
    }

    override func tearDown() { AppClock.reset() }

    func testThreadIsDecodedItemByItem() async throws {
        fake.on("GET", "/admin/conversations/c1/messages", body: #"[{"id":"m1","text":"hi","created_at":"2026-09-25T08:00:00Z"},"garbage",{"id":"m2","type":"system_event","event_kind":"call","call":{"id":"k","call_id":"wacid.1","status":"completed","duration":"61"}},{"id":"m3","comment_context":{"post_id":"p1","has_video":true},"reply_to":{"id":"m1","sender":"user"}}]"#)
        let api = InboxApi(http: http)
        let t = try await api.messages(id: "c1", before: "2026-09-25T09:00:00+00:00")
        XCTAssertEqual(["m1", "m2", "m3"], t.map { $0.id })
        XCTAssertEqual("limit=50&before=2026-09-25T09%3A00%3A00%2B00%3A00", fake.calls[0].query)
        XCTAssertEqual(61, t[1].call?.duration)
        XCTAssertEqual("p1", t[2].commentContext?.postId); XCTAssertEqual(true, t[2].commentContext?.hasVideo)
        XCTAssertEqual("m1", t[2].replyTo?.id)
        XCTAssertTrue(t[0].millis > 0)
        fake.on("GET", "/admin/conversations/c1/messages", body: "")
        let empty = try await api.messages(id: "c1")
        XCTAssertTrue(empty.isEmpty)
        fake.on("GET", "/admin/conversations/c1/messages", body: "<html>portal</html>")
        let e = await expectApi { try await api.messages(id: "c1") }
        XCTAssertEqual(true, e?.malformed)
    }

    func testInboxPageUsesFormEncodingAndTakesTheLegacyArray() async throws {
        let api = InboxApi(http: http)
        let page = try await api.page(InboxQuery(tab: "human", q: " Nyeri Friday "), limit: 50)
        XCTAssertEqual("limit=50&tab=human&q=Nyeri+Friday", fake.calls[0].query)
        XCTAssertEqual("cursor-2", page.nextCursor)
        XCTAssertEqual(7, page.items.count)
        fake.on("GET", "/admin/conversations", body: #"[{"id":"c9","wa_id":"2547","tags":"vip"},{"wa_id":"no-id"},{"id":"c10","tags":[1,null,"a"]}]"#)
        let legacy = try await api.page(InboxQuery(), limit: 50)
        XCTAssertNil(legacy.nextCursor)
        XCTAssertEqual(["c9", "c10"], legacy.items.map { $0.id }, "a row with no id is dropped")
        XCTAssertEqual(["vip"], legacy.items[0].tags)
        XCTAssertEqual(["1", "a"], legacy.items[1].tags)
    }

    func testReplyRefusedByDeliveryThrowsNotDelivered() async throws {
        let api = InboxApi(http: http)
        fake.on("POST", "/admin/conversations/c1/reply", body: #"{"ok":false,"error":"Outside the 24h window"}"#)
        do {
            try await api.reply(id: "c1", text: "hi", replyTo: "m1", originalText: nil, originalLang: nil, clientMsgId: "optimistic-1")
            XCTFail("expected NotDelivered")
        } catch let e as NotDelivered {
            XCTAssertEqual("Outside the 24h window", e.message)
        }
        XCTAssertEqual(#"{"client_msg_id":"optimistic-1","reply_to":"m1","text":"hi"}"#, fake.calls.last?.body)
        fake.on("POST", "/admin/conversations/c1/reply", body: #"{"id":"m5","text":"hi"}"#)
        try await api.reply(id: "c1", text: "hi", replyTo: nil, originalText: "hi", originalLang: "en")
        XCTAssertEqual(#"{"original_lang":"en","original_text":"hi","text":"hi"}"#, fake.calls.last?.body)
    }

    func testActivityDropsRowsWithoutLabelsAndRepeats() async throws {
        fake.on("GET", "/admin/conversations/c1/activity", body: #"{"events":[{"id":"e1","kind":"order","label":"Paid"},{"kind":"x"},{"label":"No id"},{"id":"e1","kind":"order","label":"Paid again"}]}"#)
        let a = try await InboxApi(http: http).activity(id: "c1")
        XCTAssertEqual(["e1", "ev-2"], a.map { $0.id })
    }

    func testUploadAnswersTheRowOrAnOptimisticOne() async throws {
        let api = InboxApi(http: http)
        fake.on("POST", "/admin/conversations/c1/upload-media", body: #"{"id":"m9","direction":"outbound","sender":"human_agent","text":"Front","media_type":"image"}"#)
        let item = PickedMedia(id: "p1", file: nil, name: "p.jpg", mime: "image/jpeg", size: 5, bytes: Data("jpeg".utf8), caption: " Front ")
        let m = try await api.upload(convId: "c1", item: item)
        XCTAssertEqual("m9", m.id)
        XCTAssertTrue(fake.calls.last!.body!.contains("name=\"caption\"\r\n\r\nFront"))
        fake.on("POST", "/admin/conversations/c1/upload-media", body: "")
        let fallback = try await api.upload(convId: "c1", item: item)
        XCTAssertTrue(fallback.id.hasPrefix("optimistic-up-"))
        XCTAssertEqual("human_agent", fallback.sender)
    }

    func testCustomerProfileDecodesLeniently() throws {
        let p = try NeemaJSON.decode(CustomerProfile.self, from: """
        {"id":"u1","wa_id":"254712345678","name":"Fr. Peter","name_confirmed":true,"age":"41","tags":["vip"],"lead_stage":"Proposal",
         "lead_score":72,"total_spent":0,"orders":[{"id":"h1","order_number":"BH-1","total":"2500.00","currency_code":"usd","source":"hub","created_at":"2026-09-20 08:15:30",
           "items":[{"name":"Alb","quantity":"2.00"},{"name":"Stole","qty":1,"total":"x"}]},{"id":"l1","subtotal":1200,"source":"whatsapp"}],
         "buying_rhythm":{"days_since_last":12,"avg_interval_days":30.5,"cadence_label":"monthly","overdue":false},
         "linked_identities":[{"channel":"instagram","external_id":"178","confidence":"high"}],"channels":[{"channel":"whatsapp","identifier":"254712345678","conversation_count":3}]}
        """)
        XCTAssertEqual(41, p.age)
        XCTAssertEqual(72, p.leadScore)
        XCTAssertEqual(2, p.orders?.count)
        let hub = p.orders![0]
        XCTAssertEqual(2500, hub.amount); XCTAssertEqual("USD", hub.displayCurrency); XCTAssertEqual("2026-09-20T08:15:30", hub.createdIso)
        XCTAssertEqual(2, hub.items[0].quantity); XCTAssertNil(hub.items[1].total)
        let local = p.orders![1]
        XCTAssertEqual(1200, local.amount); XCTAssertEqual("KES", local.displayCurrency)
        XCTAssertEqual(12, p.buyingRhythm?.daysSinceLast)
        XCTAssertEqual("high", p.linkedIdentities[0].confidence)
        let none = try NeemaJSON.decode(CustomerProfile.self, from: #"{"id":"u2","orders":null}"#)
        XCTAssertNil(none.orders, "null orders fall back to the dashboard's list")
    }

    func testStageRules() {
        XCTAssertEqual("negotiation", Crm.canonicalStage("Negotiating", customs: []))
        XCTAssertEqual("Sampling", Crm.canonicalStage("sampling", customs: ["Sampling"]), "the operator's spelling")
        XCTAssertEqual("new", Crm.canonicalStage("  ", customs: []))
        XCTAssertEqual("contacted", Crm.nextStage("new", customs: []))
        XCTAssertEqual("Sampling", Crm.nextStage("negotiation", customs: ["Sampling"]))
        XCTAssertEqual("won", Crm.nextStage("Sampling", customs: ["Sampling"]))
        XCTAssertEqual("won", Crm.nextStage("lost", customs: []))
        XCTAssertEqual("won", Crm.nextStage("gone-custom", customs: []), "a removed custom label advances from where customs sit")
        XCTAssertEqual("won", Crm.nextStage("won", customs: []))
        XCTAssertNil(Crm.realPhoneDigits("web_3fa9c1e20b7d4c5a9e11"))
        XCTAssertEqual("254712345678", Crm.realPhoneDigits("+254 712 345 678"))
        XCTAssertEqual("Web chat", Crm.channelLabel("whatsapp", identifier: "web_x"))
        XCTAssertEqual("SMS", Crm.channelLabel("sms"))
    }

    func testCrmApiPathsAreFormEncoded() async throws {
        let api = CrmApi(http: http)
        fake.on("GET", "/admin/customers/254712345678", body: #"{"id":"u1"}"#)
        _ = try await api.profile(key: "254712345678", channel: "whatsapp")
        XCTAssertEqual("channel=whatsapp", fake.calls.last?.query)
        fake.on("PATCH", "/admin/customers/.*", body: "{}")
        try await api.patch(key: "web x", channel: nil, body: .object(["notes": "n", "notes_base": "b"]))
        XCTAssertEqual("/admin/customers/web+x", fake.calls.last?.path)
        XCTAssertEqual(#"{"notes":"n","notes_base":"b"}"#, fake.calls.last?.body)
        fake.on("POST", "/admin/production/e1/push", body: #"{"hub_order_number":"BH-7","already":true}"#)
        let push = try await api.pushProduction(enquiryId: "e1")
        XCTAssertEqual("BH-7", push.hubOrderNumber); XCTAssertTrue(push.already)
    }

    func testLeadsDecodeWithLenientTagsAndNormalisedStage() async throws {
        fake.on("GET", "/admin/leads", body: #"[{"id":"u1","wa_id":"2547","lead_stage":"new","lead_score":87.4,"tags":"church, wholesale ,,repeat","total_spent":0},{"id":"u2","phone":"+1 415","tags":[1,null,"x"],"lead_score":140,"buying_rhythm":{"days_since_last":3.0,"overdue":true}},{"id":"u3","tags":{"a":1}}]"#)
        let api = LeadsApi(http: http)
        let leads = try await api.list(stage: " Negotiating ")
        XCTAssertEqual("stage=negotiation", fake.calls[0].query)
        XCTAssertEqual(["church", "wholesale", "repeat"], leads[0].tags)
        XCTAssertEqual(87, leads[0].leadScore)
        XCTAssertEqual("2547", leads[0].handle)
        XCTAssertEqual(["1", "x"], leads[1].tags)
        XCTAssertEqual(100, leads[1].leadScore)
        XCTAssertEqual("+1 415", leads[1].handle)
        XCTAssertEqual(true, leads[1].buyingRhythm?.overdue)
        XCTAssertEqual([], leads[2].tags)
        XCTAssertEqual("u3", leads[2].handle)
        fake.on("PATCH", "/admin/leads/u%201", body: #"{"ok":true}"#)
        _ = try await api.update(id: "u 1", body: .object(["lead_stage": "won"]))
        XCTAssertEqual("/admin/leads/u+1", fake.calls.last?.path)
    }

    func testTeamApiShapes() async throws {
        let api = TeamApi(http: http)
        _ = try await api.setAvailable(id: "a1", available: false)
        XCTAssertEqual(#"{"is_available":false}"#, fake.calls.last?.body)
        _ = try await api.assignRole(agentId: "a1", roleId: "sales", customPermissions: nil)
        XCTAssertEqual(#"{"custom_role_id":"sales"}"#, fake.calls.last?.body)
        _ = try await api.assignRole(agentId: "a1", roleId: "sales", customPermissions: [])
        XCTAssertEqual(#"{"custom_permissions":[],"custom_role_id":"sales"}"#, fake.calls.last?.body)
    }
}
