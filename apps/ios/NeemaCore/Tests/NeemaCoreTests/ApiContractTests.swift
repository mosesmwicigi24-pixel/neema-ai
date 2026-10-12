import XCTest
@testable import NeemaCore

/// The core endpoints against what apps/api/app actually sends. Each test
/// names the handler it mirrors; the fixtures it decodes are built from the
/// same handlers (see `Fixtures`). The Swift twin of Android's ApiContractTest.
final class ApiContractTests: XCTestCase {
    private final class Tokens: TokenProvider {
        var current: String?
        var refreshes = 0
        init(_ c: String?) { current = c }
        func validAccessToken() async throws -> String? { current }
        func forceRefresh() async throws -> String? { refreshes += 1; return nil }
        func onRejected(_ token: String?) {}
    }

    private var fake: FakeNeema!
    private var tokens: Tokens!
    private var http: NeemaHTTP!
    private var api: NeemaApi!

    override func setUp() {
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        tokens = Tokens("tok-1")
        http = NeemaHTTP(baseUrl: "https://neema.test", tokens: tokens, transport: fake)
        api = NeemaApi(http: http)
    }

    override func tearDown() { AppClock.reset() }

    // ── GET /admin/me — admin.py get_me (the ORM Agent row) ─────────────────

    func testMeDecodesTheOrmRowAndIgnoresThePasswordHash() async throws {
        let me = try await api.profile.me()
        XCTAssertEqual(1, fake.calls.count)
        let c = fake.calls[0]
        XCTAssertEqual("GET", c.method); XCTAssertEqual("/admin/me", c.path); XCTAssertNil(c.query)
        XCTAssertEqual("Bearer tok-1", c.header("Authorization"))

        XCTAssertEqual(Fixtures.ME_ID, me.id)
        XCTAssertEqual("Moses Mwicigi", me.name)
        XCTAssertEqual("admin", me.role)
        XCTAssertTrue(me.isSuperuser && me.isAvailable)
        XCTAssertEqual(4, me.activeConvs)
        // No custom-role columns on /me: permissions fall back to the role.
        XCTAssertNil(me.customRoleId); XCTAssertNil(me.rolePermissions)
        XCTAssertEqual(Perms.ALL, Perms.of(me))
        // "+00:00" with microseconds parses to the same instant as "Z".
        XCTAssertTrue(Fmt.millis(me.lastSeenAt)! > AppClock.now() - 5 * 60_000)
    }

    func testMeToleratesMissingOptionalColumnsAndNulls() async throws {
        fake.on("GET", "/admin/me", body: #"{"id":"a9","name":"Grace","email":"g@b.co","role":"agent","is_available":null,"is_superuser":false,"active_convs":null,"created_at":"2026-01-04T08:00:00"}"#)
        let me = try await api.profile.me()
        XCTAssertFalse(me.isAvailable)
        XCTAssertEqual(0, me.activeConvs)
        XCTAssertNil(me.lastSeenAt)
        // A naive timestamp (datetime.utcnow before a refresh) is read as UTC.
        XCTAssertEqual(Fmt.millis("2026-01-04T08:00:00Z"), Fmt.millis(me.createdAt))
    }

    func testMeErrorsCarryTheServersDetail() async {
        fake.on("GET", "/admin/me", code: 404, body: #"{"detail":"Agent not found"}"#)
        let e = await expectApi { try await self.api.profile.me() }
        XCTAssertEqual(404, e?.status)
        XCTAssertEqual("Agent not found", e?.detail)
    }

    // ── GET /admin/agents — admin.py list_agents (raw SQL + custom_roles) ────

    func testAgentsDecodeTheJoinedRows() async throws {
        let list = try await api.agents.list()
        XCTAssertEqual("/admin/agents", fake.calls[0].path)
        XCTAssertEqual([Fixtures.ME_ID, Fixtures.AGENT2_ID, Fixtures.AGENT3_ID], list.map { $0.id })
        let grace = list[1]
        XCTAssertEqual("sales", grace.customRoleId)
        XCTAssertEqual("Sales", grace.roleName)
        XCTAssertEqual("#3b82f6", grace.roleColor)
        XCTAssertTrue(Perms.of(grace).contains(Perms.EDIT_CRM))
        XCTAssertFalse(Perms.of(grace).contains(Perms.MANAGE_AGENTS))
        let brian = list[2]
        XCTAssertEqual(Perms.effective(role: "readonly", isSuperuser: false, permissions: nil), Perms.of(brian))
    }

    func testPerAgentOverridesWinOverTheRolesPermissions() async throws {
        fake.on("GET", "/admin/agents", body: "[" + Fixtures.agentRow(
            "a7", "Wanjiku", "w@b.co", "agent", true, false, 2, 100, nil, customRole: "sales",
            rolePermissions: #"["view_orders","manage_orders"]"#, customPermissions: #"["view_orders"]"#
        ) + "]")
        let list = try await api.agents.list()
        XCTAssertEqual(1, list.count)
        XCTAssertEqual(["view_orders"], list[0].permissions)
        XCTAssertNil(list[0].lastSeenAt)
    }

    // ── GET /admin/orders — admin.py list_orders (ORM order_events rows) ─────

    func testOrdersSendTheHandlersQueryNames() async throws {
        _ = try await api.orders.list(status: "pending", waId: "254712345678")
        let c = fake.callsTo("GET", "/admin/orders")[0]
        XCTAssertEqual(["status": "pending", "wa_id": "254712345678"], c.params)
        _ = try await api.orders.list()
        XCTAssertNil(fake.callsTo("GET", "/admin/orders").last!.query, "no filters, no query string")
    }

    func testOrdersDecodeCartLinesLegacyLinesAndHubState() async throws {
        let orders = try await api.orders.list()
        XCTAssertEqual(["o1", "o2", "o3", "o4"], orders.map { $0.id })

        let o1 = orders[0]
        // Neema's own orders store unit_price and no total: both are derived.
        XCTAssertEqual([3500.0, 250.0], o1.items.map { $0.unit })
        XCTAssertEqual([7000.0, 1000.0], o1.items.map { $0.total })
        XCTAssertEqual([2.0, 4.0], o1.items.map { $0.qty })
        XCTAssertEqual("CS-BLK-16", o1.items[0].sku)
        XCTAssertEqual(8000.0, o1.subtotal)
        XCTAssertEqual(1042, o1.hubOrderId)
        XCTAssertEqual("processing", o1.hubStatus)
        XCTAssertEqual("https://hub.bethanyhouse.co.ke/order/tok1042", o1.hubPublicUrl)
        // There is no contact_name column: the customer is shown by wa_id.
        XCTAssertNil(o1.contactName)
        XCTAssertEqual("254712345678", o1.customerName)

        // An "open" cart snapshot reads as pending, like mapOrder().
        XCTAssertEqual("open", orders[1].rawStatus); XCTAssertEqual("pending", orders[1].status)
        XCTAssertEqual("Variant out of stock in hub", orders[1].hubLastError)

        // The hub bridge's older {unit,total} lines still read as they are.
        XCTAssertEqual(1, orders[2].items.count)
        XCTAssertEqual(4800.0, orders[2].items[0].unit); XCTAssertEqual(4800.0, orders[2].items[0].total)
    }

    func testOrdersTolerateDecimalStringsNullsAndMissingColumns() throws {
        let rows = """
        [{"id":"x1","wa_id":"254700000001","items":[{"name":"Alb","quantity":"2","price":"6000.00"},"garbage",null],
          "subtotal":"12000.00","currency":"KES","status":"confirmed","hub_total":"12000.00","hub_order_id":"77",
          "created_at":"2026-09-01T10:00:00.123456+00:00"},
         {"id":"x2","wa_id":"254700000002","items":null,"subtotal":null,"status":"open","channel":null,"state":null,
          "created_at":"2026-09-01T10:00:00"},
         {"id":"x3","wa_id":"254700000003"}]
        """
        let list = try NeemaJSON.decode([Order].self, from: rows)
        XCTAssertEqual(1, list[0].items.count)
        let alb = list[0].items[0]
        XCTAssertEqual(2.0, alb.qty); XCTAssertEqual(6000.0, alb.unit); XCTAssertEqual(12000.0, alb.total)
        XCTAssertEqual(12000.0, list[0].subtotal)
        XCTAssertEqual(77, list[0].hubOrderId)
        XCTAssertTrue(list[1].items.isEmpty)
        XCTAssertEqual(0.0, list[1].subtotal)
        XCTAssertEqual("whatsapp", list[1].channel)
        XCTAssertEqual("pending", list[2].status)
        XCTAssertEqual("KES", list[2].currency)
        XCTAssertEqual(Fmt.millis("2026-09-01T10:00:00Z"), Fmt.millis(list[1].createdAt))
    }

    func testOrderPatchSendsOnlyAllowedKeysAndDecodesTheRow() async throws {
        fake.on("PATCH", "/admin/orders/o1", body: Fixtures.orderRow("o1", "254712345678", "[]", "8000.0", "delivered", "whatsapp", 5))
        let o = try await api.orders.updateStatus(id: "o1", status: "delivered", fulfillmentStatus: "fulfilled")
        XCTAssertEqual(#"{"fulfillment_status":"fulfilled","status":"delivered"}"#, fake.callsTo("PATCH", "/admin/orders/o1")[0].body)
        XCTAssertEqual("delivered", o.status)
    }

    // ── GET /admin/catalog — admin.py list_catalog → n8n_bridge.catalog_items ─

    func testCatalogSendsCategoryAndSearch() async throws {
        _ = try await api.catalog.list(category: "Vestments", search: "stole & alb")
        let c = fake.callsTo("GET", "/admin/catalog")[0]
        XCTAssertEqual(["category": "Vestments", "search": "stole & alb"], c.params)
        XCTAssertTrue(c.query!.contains("stole%20%26%20alb"), "spaces are %20, never +, in a query NeemaApi builds")
    }

    func testHubProductsDecodeWithVariantsAndNoLocalId() async throws {
        let items = try await api.catalog.list()
        XCTAssertEqual(4, items.count)
        let shirt = items[0]
        XCTAssertNil(shirt.rawId)
        XCTAssertEqual("501", shirt.id)
        XCTAssertTrue(shirt.isHub)
        XCTAssertEqual("", shirt.unit)
        XCTAssertEqual(3, shirt.variants.count)
        XCTAssertEqual(["Colour": "Black", "Size": "15 inch"], shirt.variants[0].attributes)
        XCTAssertEqual("Clergy Shirt — Black, 15 inch", shirt.variants[0].label)
        XCTAssertEqual(4200.0, shirt.priceMaxKes)
        XCTAssertEqual("https://hub.test/p/CS-BLK-t.jpg", shirt.thumbnailUrl)
        XCTAssertNil(items[3].availableQty, "available_qty may be null")
        XCTAssertFalse(items[2].inStock)
        XCTAssertEqual("Shirts", shirt.category)
    }

    func testTheLocalFallbackCatalogDecodesToo() throws {
        let items = try NeemaJSON.decode([CatalogItem].self, from: Fixtures.localCatalog)
        XCTAssertEqual("RC-TAB", items[0].id)
        XCTAssertFalse(items[0].isHub)
        // The fallback maps a missing category to "" (not null), exactly as the web receives it.
        XCTAssertEqual("", items[1].category)
        XCTAssertEqual(1200.0, items[1].price)
        XCTAssertEqual("General", CatalogItem(sku: "X", name: "X").category)
    }

    func testVariantAttributesTolerateEmptyListsNumbersAndNulls() throws {
        let json = """
        [{"hub_product_id":9,"sku":"T","name":"Thurible","price":"9000.00","available_qty":"3",
          "variants":[{"variant_id":1,"attributes":[]},{"variant_id":"2","attributes":{"Size":10,"Colour":null,"Chain":true}}]}]
        """
        let t = try NeemaJSON.decode([CatalogItem].self, from: json)[0]
        XCTAssertEqual(9000.0, t.price)
        XCTAssertEqual(3.0, t.availableQty)
        XCTAssertEqual([:], t.variants[0].attributes)
        XCTAssertEqual(["Size": "10", "Chain": "true"], t.variants[1].attributes)
        XCTAssertEqual(2, t.variants[1].variantId)
    }

    // ── GET /admin/conversations/summary — admin.py conversations_summary ────

    func testSummaryDecodesAndMissingChannelsReadAsZero() async throws {
        let s = try await api.conversations.summary()
        XCTAssertEqual("/admin/conversations/summary", fake.calls[0].path)
        XCTAssertEqual(3, s.unread); XCTAssertEqual(2, s.human); XCTAssertEqual(1, s.yours)
        XCTAssertEqual(4, s.unreadMessages["all"])
        XCTAssertNil(s.unreadMessages["instagram"], "a channel with no unread messages is absent")
        XCTAssertEqual(["bulk", "clergy", "vip"], s.tags)
        let empty = try NeemaJSON.decode(InboxSummary.self, from: #"{"unread":0,"human":0,"yours":0,"unread_messages":{"all":0},"tags":[]}"#)
        XCTAssertEqual(0, empty.unreadMessages["all"])
    }

    func testTheBaseInboxHasAWebChatVisitorOnTheDefaultChannel() async throws {
        let page = try await api.conversations.page(InboxQuery(), limit: 50)
        XCTAssertEqual("cursor-2", page.nextCursor)
        XCTAssertEqual(7, page.items.count)
        let web = page.items.filter { $0.waId?.hasPrefix("web_") == true }
        XCTAssertEqual(1, web.count)
        XCTAssertEqual("whatsapp", web[0].channel)
        XCTAssertNil(web[0].name)
        XCTAssertEqual("Website visitor", Fmt.formatPhone(web[0].waId))
        XCTAssertEqual(["vip", "clergy"], page.items[0].tags)
        XCTAssertEqual("limit=50", fake.calls[0].query)
    }

    func testALegacyBareArrayIsOneFinalPage() async throws {
        fake.on("GET", "/admin/conversations") { _, _ in (200, "[\(Fixtures.inbox.joined(separator: ","))]") }
        let page = try await api.conversations.page(InboxQuery(tab: "human", channel: "whatsapp", q: " Nyeri Friday "), limit: 50, cursor: "c2")
        XCTAssertNil(page.nextCursor)
        XCTAssertEqual(7, page.items.count)
        XCTAssertEqual(["limit": "50", "cursor": "c2", "tab": "human", "channel": "whatsapp", "q": "Nyeri Friday"], fake.calls[0].params)
    }

    func testMessagesDecodeNotesMediaAndQuotes() async throws {
        let m = try await api.conversations.messages(id: "c1")
        XCTAssertEqual(8, m.count)
        XCTAssertTrue(m[3].isSystemEvent); XCTAssertEqual("intercept", m[3].eventKind)
        XCTAssertEqual("image", m[4].mediaType); XCTAssertEqual("Like this collar", m[4].mediaCaption)
        XCTAssertTrue(m[6].isNote)
        XCTAssertEqual("m5", m[7].replyTo?.id); XCTAssertEqual("human_agent", m[7].replyTo?.sender)
        XCTAssertTrue(m[7].isInbound)
    }

    func testCallsDealsActionsAndAttributionDecode() async throws {
        let calls = try await api.calls.list()
        XCTAssertEqual(["wacid.1", "wacid.2", "wacid.3"], calls.map { $0.callId })
        XCTAssertNil(calls[1].duration); XCTAssertEqual("missed", calls[1].status)
        XCTAssertTrue(calls[0].hasRecording); XCTAssertEqual("done", calls[0].transcriptStatus)
        let deals = try await api.deals.list()
        XCTAssertEqual(3, deals.count)
        XCTAssertEqual(3500, deals[0].items[0].price); XCTAssertEqual("ai", deals[0].nextAction?.owner)
        XCTAssertNil(deals[1].nextAction)
        let actions = try await api.actions.list()
        XCTAssertEqual("x1", actions[0].id); XCTAssertNil(actions[0].dueAt); XCTAssertEqual("neema", actions[0].createdBy)
        XCTAssertEqual("status=open", fake.callsTo("GET", "/admin/deals")[0].query)
        XCTAssertEqual("status=pending", fake.callsTo("GET", "/admin/actions")[0].query)
        let a = try await api.attribution()
        XCTAssertEqual(3, a.sources.count); XCTAssertEqual(703000, a.totals.revenue); XCTAssertEqual(9, a.unattributed.orders)
        let stats = try await api.stats.overview()
        XCTAssertEqual(128, stats.openConversations); XCTAssertEqual(3, stats.channelBreakdown.count)
    }

    func testSettingsDecode() async throws {
        let d = try await api.settings.getDirectives()
        XCTAssertEqual(2000, d.maxChars)
        let t = try await api.settings.getTranslation()
        XCTAssertTrue(t.enabled); XCTAssertEqual(812, t.calls30d); XCTAssertEqual(3.42, t.spend30dUsd)
        let o = try await api.settings.getOffer()
        XCTAssertEqual("Easter Sale", o.campaign?.name); XCTAssertEqual(10, o.campaign?.percent); XCTAssertEqual(["Vestments"], o.campaign?.categories)
        XCTAssertNil(o.campaign?.startsOn); XCTAssertEqual(30, o.maxPercent)
        let stages = try await api.settings.getPipelineStages()
        XCTAssertEqual(["measuring"], stages)
        _ = try await api.settings.putOffer(o.campaign)
        let body = fake.callsTo("PUT", "/admin/settings/offer")[0].body!
        XCTAssertTrue(body.contains(#""campaign":{"#) && body.contains(#""ends_on":"2099-04-30""#) && body.contains(#""percent":10"#), body)
        _ = try await api.settings.putOffer(nil)
        XCTAssertEqual(#"{"campaign":null}"#, fake.callsTo("PUT", "/admin/settings/offer")[1].body)
    }

    // ── Errors ──────────────────────────────────────────────────────────────

    func testAPydanticValidationListReadsAsItsMessages() async {
        fake.on("POST", "/admin/agents", code: 422, body: #"{"detail":[{"type":"missing","loc":["body","email"],"msg":"Field required","input":null},{"type":"string_too_short","loc":["body","password"],"msg":"String should have at least 8 characters"}]}"#)
        let e = await expectApi { try await self.api.agents.create(name: "Grace", email: "", password: "pw") }
        XCTAssertEqual(422, e?.status)
        XCTAssertEqual("Field required; String should have at least 8 characters", e?.detail)
    }

    func testPlainTextAndHtmlErrorsAreShownTrimmed() async {
        fake.on("GET", "/admin/agents", code: 500, body: "Internal Server Error")
        let a = await expectApi { try await self.api.agents.list() }
        XCTAssertEqual("Internal Server Error", a?.detail)
        fake.on("GET", "/admin/agents", code: 502, body: "  <html><body>502 Bad Gateway</body></html>\n")
        let b = await expectApi { try await self.api.agents.list() }
        XCTAssertEqual("", b?.detail, "a proxy page is never shown as a detail")
    }

    func testANoTokenForbiddenIsTheSameDeadSession() async {
        tokens.current = nil
        fake.on("GET", "/admin/me", code: 403, body: #"{"detail":"Not authenticated"}"#)
        var expired = false
        let sub = http.sessionExpired.observe { expired = true }
        defer { sub.cancel() }
        let e = await expectApi { try await self.api.profile.me() }
        XCTAssertEqual(401, e?.status)
        XCTAssertEqual(1, tokens.refreshes, "one rescue attempt, as for a 401")
        XCTAssertTrue(expired, "the re-auth prompt opens")
    }

    func testAForbiddenWithATokenIsAPlainError() async {
        fake.on("DELETE", "/admin/roles/admin", code: 403, body: #"{"detail":"Protected role"}"#)
        let e = await expectApi { try await self.api.roles.delete(id: "admin") }
        XCTAssertEqual(403, e?.status)
        XCTAssertEqual("Protected role", e?.detail)
        XCTAssertEqual(0, tokens.refreshes)
    }

    func testAnEmptySuccessIsASuccess() async throws {
        fake.on("DELETE", "/admin/agents/a3", code: 204, body: "")
        let ok = try await api.agents.delete(id: "a3")
        XCTAssertEqual(OkResponse(), ok)
        fake.on("GET", "/admin/agents", body: "")
        let list = try await api.agents.list()
        XCTAssertEqual([], list)
    }

    // ── Uploads ─────────────────────────────────────────────────────────────

    func testAFileBackedUploadIsStreamedAndSentWhole() async throws {
        let f = FileManager.default.temporaryDirectory.appendingPathComponent("call-\(UUID().uuidString).m4a")
        let bytes = Data((0..<(256 * 1024)).map { UInt8($0 % 251) })
        try bytes.write(to: f)
        defer { try? FileManager.default.removeItem(at: f) }
        fake.on("POST", "/admin/calls/wacid.1/recording", body: #"{"ok":true,"will_transcribe":true}"#)
        let up = UploadFile.of(file: f, filename: "wacid.1.m4a", mimeType: "audio/mp4")
        if case .data = up.source { XCTFail("nothing should be read into memory") }

        let res = try await api.calls.uploadRecording(callId: "wacid.1", file: up)

        XCTAssertEqual(true, res.willTranscribe)
        let body = fake.callsTo("POST", "/admin/calls/wacid.1/recording")[0].body!
        XCTAssertTrue(body.contains("name=\"file\"; filename=\"wacid.1.m4a\""))
        XCTAssertTrue(body.contains("Content-Type: audio/mp4"))
        // Every byte arrived, and a second write (the retry after a refresh) re-reads the file.
        var parts = MultipartBody(boundary: "b")
        parts.add(up, named: "file")
        let a = try parts.encoded(), b = try parts.encoded()
        XCTAssertEqual(a, b)
        XCTAssertNotNil(a.range(of: bytes))
    }

    func testAByteArrayUploadStillWorks() async throws {
        fake.on("POST", "/admin/conversations/c1/upload-media", body: #"{"id":"m9","type":"message","direction":"outbound","sender":"human_agent","text":"","created_at":"2026-09-25T10:00:00+00:00","media_type":"image","media_url":"https://neema.test/m.jpg"}"#)
        let m = try await api.conversations.uploadMedia(convId: "c1", file: UploadFile(bytes: Data("jpeg!".utf8), filename: "p.jpg", mimeType: "image/jpeg"), caption: "Front")
        XCTAssertEqual("m9", m.id)
        let body = fake.calls.last!.body!
        XCTAssertTrue(body.contains("jpeg!") && body.contains("name=\"caption\"") && body.contains("Front"))
    }

    // ── Call shapes the softphone depends on ───────────────────────────────

    func testCallShapesDecodeLeniently() throws {
        let sdp = try NeemaJSON.decode(CallSdpResponse.self, from: #"{"ok":true,"call_id":"wacid.9","channel":"messenger","sdp":"v=0","sdp_type":"answer","renegotiation":{"sdp_type":"offer","sdp":"v=1"}}"#)
        XCTAssertEqual("v=1", sdp.renegotiationSdp)
        let sdp2 = try NeemaJSON.decode(CallSdpResponse.self, from: #"{"ok":true,"call_id":"x","renegotiation":"v=2"}"#)
        XCTAssertEqual("v=2", sdp2.renegotiationSdp)
        let ice = try NeemaJSON.decode(IceConfig.self, from: #"{"ice_servers":[{"urls":"stun:stun.l.google.com:19302"},{"urls":["turn:a","turn:b"],"username":"u","credential":"c"},{"username":"x"}],"record":true,"channels":{"messenger":{"inbound":true,"outbound":true,"video":false,"sdp":"offer"}}}"#)
        XCTAssertEqual([["stun:stun.l.google.com:19302"], ["turn:a", "turn:b"], []], ice.iceServers.map { $0.urlList })
        XCTAssertEqual(true, ice.record)
        XCTAssertEqual(true, ice.channels?.messenger.outbound)
        XCTAssertTrue(CallChannels().whatsapp.inbound && CallChannels().whatsapp.outbound)
        XCTAssertEqual("answer", CallChannels().whatsapp.sdp)
        let call = try NeemaJSON.decode(Call.self, from: #"{"id":"k","call_id":"wacid.1","status":"completed","insights":{"intent":"buy","products":["Alb",2,null],"objections":"price","next_action":"call back"}}"#)
        XCTAssertEqual("buy", call.insights?.intent)
        XCTAssertEqual(["Alb", "2"], call.insights?.products)
        XCTAssertEqual(["price"], call.insights?.objections)
        let perm = try NeemaJSON.decode(CallPermission.self, from: #"{"status":"requested","can_call":false,"request_available_at":"2026-10-12T10:00:00Z","unanswered_streak":"2"}"#)
        XCTAssertEqual(false, perm.canCall); XCTAssertEqual(2, perm.unansweredStreak); XCTAssertNil(perm.canRequest)
    }
}
