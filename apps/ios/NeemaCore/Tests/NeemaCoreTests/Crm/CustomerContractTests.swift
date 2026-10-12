import XCTest
@testable import NeemaCore

/// The CRM panel against the REAL server contract (apps/api/app/routers/crm.py
/// and the admin.py routes it borrows): each request's method, path, query and
/// body, and each response decoded in the shapes the handlers can produce
/// (Android `CustomerContractTest`).
final class CustomerContractTests: CustomerTestCase {
    private func profile(_ json: String) throws -> CustomerProfile { try NeemaJSON.decode(CustomerProfile.self, from: json) }
    private func order(_ json: String) throws -> PanelOrder { try NeemaJSON.decode(PanelOrder.self, from: json) }

    // ── GET /admin/customers/{wa_id} (get_customer → _build_profile) ────────

    func testTheProfileIsFetchedByHandleWithTheChannelAndDecodesTheServersNumbers() async {
        let p = await vm().profile!
        let get = calls("GET", peterPath)
        XCTAssertEqual(get.count, 1)
        XCTAssertEqual(get.first?.query, "channel=whatsapp")
        XCTAssertNil(get.first?.body)
        XCTAssertEqual(p.leadScore, 95)
        XCTAssertEqual(p.leadScoreBreakdown.count, 9)
        XCTAssertEqual(p.leadScoreBreakdown.reduce(0) { $0 + $1.max }, 120)
        XCTAssertEqual(p.leadScoreBreakdown.reduce(0) { $0 + $1.pts }, 95)
        XCTAssertEqual(p.totalOrders, 24)
        XCTAssertEqual(p.totalSpent, 486500)
        XCTAssertEqual(p.avgOrderValue, 20270.83)
        XCTAssertEqual(p.buyingRhythm?.daysSinceLast, 70)
        XCTAssertEqual(p.buyingRhythm?.avgIntervalDays, 30)
        XCTAssertEqual(p.buyingRhythm?.cadenceLabel, "about every 4 weeks")
        XCTAssertEqual(p.buyingRhythm?.overdue, true)
        XCTAssertEqual(p.tier, "vip")
        XCTAssertTrue(p.hubLinked)
        XCTAssertEqual(p.hubCustomerId?.content, "311")
        // Hub order lines: qty and quantity both carry the hub's raw quantity.
        let first = p.orders!.first!
        XCTAssertEqual(first.source, "hub")
        XCTAssertEqual(first.items.first?.qty, 2)
        XCTAssertEqual(first.items.first?.total, 7000)
        // Python's tz-aware isoformat ("+00:00") parses.
        XCTAssertNotNil(Fmt.millis(p.lastOrderAt))
        XCTAssertNotNil(Fmt.millis(p.channels.first?.lastSeen))
    }

    func testTheNoHubFallbackSendsIntegerZerosAndAnAlwaysPresentRhythm() async {
        let p = await vm("c2").profile!
        XCTAssertEqual(p.totalSpent, 0)
        XCTAssertEqual(p.avgOrderValue, 0)
        XCTAssertEqual(p.orders, [])
        // _buying_rhythm([]) is an object of nulls, never null itself.
        let r = p.buyingRhythm!
        XCTAssertNil(r.daysSinceLast); XCTAssertNil(r.avgIntervalDays); XCTAssertNil(r.cadenceLabel); XCTAssertFalse(r.overdue)
        XCTAssertNil(p.channels.first?.identifier, "a Messenger conversation has no wa_id")
    }

    func testDecimalStringsAndQuotedIntsDecodeAsNumbers() throws {
        // jsonable_encoder turns Decimal into a number today; a Decimal-as-string must not break the panel.
        let p = try profile("""
            {"id":"u","wa_id":"254700000001","lead_score":"95","total_orders":"3","total_spent":"486500.00",
             "avg_order_value":"162166.67","age":"47",
             "buying_rhythm":{"days_since_last":"12","avg_interval_days":"30.5","cadence_label":"about every 4 weeks","overdue":false},
             "lead_score_breakdown":[{"label":"Orders","pts":"25","max":"25"}],
             "orders":[{"id":90412,"order_number":1042,"total":"8000.00","subtotal":"8000.00","items":[]}]}
            """)
        XCTAssertEqual(p.leadScore, 95)
        XCTAssertEqual(p.totalOrders, 3)
        XCTAssertEqual(p.totalSpent, 486500)
        XCTAssertEqual(p.avgOrderValue, 162166.67)
        XCTAssertEqual(p.age, 47)
        XCTAssertEqual(p.buyingRhythm?.daysSinceLast, 12)
        XCTAssertEqual(p.buyingRhythm?.avgIntervalDays, 30.5)
        XCTAssertEqual(p.leadScoreBreakdown.first?.pts, 25)
        // A numeric id / order_number (hub passes order_number through raw) still reads as text.
        XCTAssertEqual(p.orders?.first?.id, "90412")
        XCTAssertEqual(p.orders?.first?.orderNumber, "1042")
        XCTAssertEqual(p.orders?.first?.amount, 8000)
    }

    func testMissingOptionalFieldsAndNullsForDefaultedOnesDecode() throws {
        // A bare profile: every optional field missing.
        let bare = try profile(#"{"id":"u","wa_id":"254700000001"}"#)
        XCTAssertEqual(bare.leadStage, "new")
        XCTAssertEqual(bare.tags, [])
        XCTAssertNil(bare.orders)
        XCTAssertNil(bare.buyingRhythm)
        XCTAssertEqual(bare.leadScore, 0)
        // Explicit nulls where the model has a default (a legacy User row: name_confirmed NULL, no state).
        let nulls = try profile("""
            {"id":"u","wa_id":"254700000001","name_confirmed":null,"tags":null,"lead_stage":null,"merged_ids":null,
             "linked_identities":null,"channels":null,"lead_score_breakdown":null,"hub_linked":null,"phone_verified":null,
             "cart_items":null,"total_orders":null,"total_spent":null,"lead_score":null,"orders":null,
             "measurements":{},"parish":null,"ad_ref":null,"hub_customer_id":null}
            """)
        XCTAssertFalse(nulls.nameConfirmed)
        XCTAssertEqual(nulls.leadStage, "new")
        XCTAssertEqual(nulls.tags, [])
        XCTAssertEqual(nulls.totalOrders, 0)
        XCTAssertEqual(nulls.totalSpent, 0)
        XCTAssertNil(nulls.orders)
    }

    func testHubOrderQuirksDecodeWithoutSinkingTheProfile() throws {
        // _map_hub_order: quantity passes through raw (a Laravel decimal string, even junk);
        // total may be null (`_f` of a blank); created_at is the hub's own string.
        let o = try order("""
            {"id":"1","order_number":"BH-1","status":"completed","payment_status":null,"order_type":"pos",
             "total":null,"subtotal":4800.0,"currency_code":"USD","created_at":"2026-09-20 08:15:30",
             "items":[{"name":"Stole — Green","qty":"2.00","quantity":"2.00","unit_price":2400.0,"total":4800.0},
                      {"name":"Gift wrap","qty":"n/a","quantity":"n/a","unit_price":0,"total":0}],
             "source":"hub"}
            """)
        XCTAssertEqual(o.items[0].qty, 2)
        XCTAssertNil(o.items[1].qty, "junk is no number")
        XCTAssertEqual(o.amount, 4800)
        XCTAssertEqual(o.createdIso, "2026-09-20T08:15:30")
        XCTAssertEqual(Fmt.millis(o.createdIso), Fmt.millis("2026-09-20T08:15:30Z"))
        XCTAssertEqual(o.displayCurrency, "USD", "a hub order keeps its own currency")
    }

    func testALocalWhatsAppOrderIsTheCartsShapeAndStaysInShillings() throws {
        // crm.py _map_local_order: subtotal is the cart's KES total; `currency` is whatever the hub said.
        let o = try order("""
            {"id":"254712345678_1758790000000","order_number":"BH-2001","status":"pending","payment_status":"unpaid",
             "total":3500.0,"subtotal":3500.0,"currency_code":"USD","created_at":"2026-09-20T08:15:30.123456+00:00",
             "items":[{"name":"Clergy Shirt","sku":"CS-16","qty":1,"unit_price":3500.0,"price_usd":27.0,
                       "prices":{"ZMW":720},"in_stock":true,"made_to_order":false}],
             "source":"whatsapp"}
            """)
        XCTAssertEqual(o.items.first?.qty, 1)
        XCTAssertNil(o.items.first?.total, "cart lines carry no total")
        XCTAssertEqual(o.displayCurrency, "KES")
        XCTAssertNotNil(Fmt.millis(o.createdIso))
    }

    func testTheWebhooksAdSourcesReadAsAds() {
        XCTAssertEqual(CustomerWords.sourceMeta("facebook_ad")?.label, "Facebook ad")
        XCTAssertEqual(CustomerWords.sourceMeta("facebook_ad")?.icon, "📘")
        XCTAssertEqual(CustomerWords.sourceMeta("instagram_ad")?.label, "Instagram ad")
        XCTAssertEqual(CustomerWords.sourceMeta("facebook")?.label, "Facebook")
        XCTAssertEqual(CustomerWords.sourceMeta("walk_in")?.label, "Walk-in")
        XCTAssertNil(CustomerWords.sourceMeta("billboard"), "unknown: the row prints the raw value with the • icon")
        XCTAssertNil(CustomerWords.sourceMeta("billboard_ad"))
    }

    func testTimestampsAreNormalisedOnlyWhenTheyNeedIt() {
        XCTAssertNil(Crm.isoOf(nil)); XCTAssertNil(Crm.isoOf("  "))
        XCTAssertEqual(Crm.isoOf("2026-09-20T08:15:30.000000Z"), "2026-09-20T08:15:30.000000Z")
        XCTAssertEqual(Crm.isoOf("2026-09-20 08:15:30+03:00"), "2026-09-20T08:15:30+03:00")
        XCTAssertEqual(Crm.isoOf("2026-09-20"), "2026-09-20")
        XCTAssertNotNil(Fmt.millis(Crm.isoOf("2026-09-20 08:15:30+03:00")))
    }

    // ── lead_stage: normalise_stage lower-cases what's stored ───────────────

    func testACustomStageComesBackLowerCasedAndStillLightsItsNode() async {
        StageCache.stages = ["Sampling", "Fitting"]
        let vm = await vm()
        vm.setStage("Sampling"); await drain()
        XCTAssertEqual(calls("PATCH", peterPath).last?.body, #"{"lead_stage":"Sampling"}"#)
        // The reload answers as crm.py does: normalise_stage("Sampling") == "sampling".
        fake.on("GET", peterPath, body: peterWith("\"lead_stage\":\"proposal\"", "\"lead_stage\":\"sampling\""))
        vm.load(showSpinner: false); await drain()
        let p = vm.profile!
        XCTAssertEqual(p.leadStage, "sampling")
        let ctx = PanelCtx(profile: p, orders: p.orders!, totalSpent: p.totalSpent, lastOrder: nil, customStages: ["Sampling", "Fitting"], canEdit: true, canReply: true, isAdmin: true)
        XCTAssertEqual(ctx.stage, "Sampling")
        XCTAssertEqual(Crm.nextStage(ctx.stage, customs: ctx.customStages), "Fitting", "Advance moves on to the next custom stage, not back to New")
    }

    func testStagesCanonicaliseAndAdvanceAlongTheForwardPath() {
        let customs = ["Sampling"]
        XCTAssertEqual(Crm.canonicalStage("negotiating", customs: customs), "negotiation")
        XCTAssertEqual(Crm.canonicalStage("Won", customs: customs), "won")
        XCTAssertEqual(Crm.canonicalStage(nil, customs: customs), "new")
        XCTAssertEqual(Crm.canonicalStage("SAMPLING", customs: customs), "Sampling")
        XCTAssertEqual(Crm.canonicalStage("fitting", customs: customs), "fitting", "a removed custom keeps its own name")
        XCTAssertEqual(Crm.nextStage("new", customs: customs), "contacted")
        XCTAssertEqual(Crm.nextStage("proposal", customs: customs), "negotiation")
        XCTAssertEqual(Crm.nextStage("negotiation", customs: customs), "Sampling")
        XCTAssertEqual(Crm.nextStage("Sampling", customs: customs), "won")
        XCTAssertEqual(Crm.nextStage("won", customs: customs), "won")
        XCTAssertEqual(Crm.nextStage("lost", customs: customs), "won")
        XCTAssertEqual(Crm.nextStage("fitting", customs: customs), "Sampling", "a removed custom advances from where customs sit")
        XCTAssertEqual(Crm.nextStage("fitting", customs: []), "won")
    }

    // ── PATCH /admin/customers/{wa_id} (update_customer → {"ok": true}) ─────

    func testAPatchTheServerCannotPlaceRollsBack() async {
        let vm = await vm()
        fake.on("PATCH", "/admin/customers/[^/]+", code: 404, body: #"{"detail":"Customer not found"}"#)
        vm.saveContactField("email", "new@x.org"); await drain()
        XCTAssertEqual(calls("PATCH", peterPath).last?.query, "channel=whatsapp")
        XCTAssertEqual(calls("PATCH", peterPath).last?.body, #"{"email":"new@x.org"}"#)
        XCTAssertEqual(vm.profile?.email, "peter.kamau@stmarks.or.ke")
        // crm.py's only 404 here: no user and no conversation for the key — merged or removed meanwhile.
        XCTAssertEqual(lastToast()?.message, "Failed to save — this customer's profile is gone (it may have been merged into another). Refreshing.")
        XCTAssertEqual(lastToast()?.type, .error)
    }

    func testNotesSendTheirBaseSoTheServersThreeWayMergeKeepsACallSummary() async {
        let vm = await vm()
        vm.saveNotes("Prefers delivery to the parish office."); await drain()
        let body = lastBody("PATCH", peterPath)
        XCTAssertEqual(Set(body.keys), ["notes", "notes_base"])
        XCTAssertEqual(body["notes_base"]?.content, "Prefers delivery to the parish office.\n\nAsk about the Easter order in March.")
    }

    // ── Merge suggestions / merge / unmerge ─────────────────────────────────

    func testMergeSuggestionsAreAskedForOnTheProfileKeyWithTheChannel() async {
        let vm = await vm()
        vm.toggleMerge(true); await drain()
        let get = calls("GET", "\(peterPath)/merge_suggestions")
        XCTAssertEqual(get.count, 1)
        XCTAssertEqual(get.first?.query, "channel=whatsapp")
        let s = vm.ui.mergeSugs!
        XCTAssertEqual(s.map { $0.strength }, ["strong", "possible"])
        XCTAssertNil(s[1].phone)
        XCTAssertEqual(s[1].channelHint, "social")
        // A 404 (no such customer) reads as "nothing found", not a spinner.
        fake.on("GET", "/admin/customers/[^/]+/merge_suggestions", code: 404, body: #"{"detail":"Customer not found"}"#)
        vm.toggleMerge(false); vm.toggleMerge(true); await drain()
        XCTAssertEqual(vm.ui.mergeSugs, [])
    }

    func testMergeAndUnmergePostTheirTargetAsMergeWith() async {
        let vm = await vm()
        vm.merge(" 254799000222 "); await drain()
        let m = calls("POST", "\(peterPath)/merge")
        XCTAssertEqual(m.count, 1)
        XCTAssertEqual(m.first?.query, "channel=whatsapp")
        XCTAssertEqual(m.first?.body, #"{"merge_with":"254799000222"}"#)
        XCTAssertEqual(lastToast()?.message, "Profiles merged successfully")
        vm.unmerge("254799000111"); await drain()
        let u = calls("POST", "\(peterPath)/unmerge")
        XCTAssertEqual(u.count, 1)
        XCTAssertEqual(u.first?.query, "channel=whatsapp")
        XCTAssertEqual(u.first?.body, #"{"merge_with":"254799000111"}"#)
        fake.on("POST", "/admin/customers/[^/]+/unmerge", code: 404, body: #"{"detail":"No active merge to undo for this pair"}"#)
        vm.unmerge("254799000111"); await drain()
        // Nothing left to undo: a colleague already unmerged it — not a failure.
        XCTAssertEqual(lastToast()?.message, "Already unmerged — refreshed to show where it stands.")
    }

    // ── Production enquiry (get_conversation_enquiry / push / decline) ──────

    func testTheEnquiryDecodesMeasurementsOfAnyJsonType() async throws {
        let r = try NeemaJSON.decode(EnquiryResponse.self, from: """
            {"enquiry":{"id":"\(CustomerFixtures.ENQUIRY_ID)","created_at":null,"product_name":null,"product_slug":null,
             "customer_name":null,"phone":null,"measurements":{"Chest":104,"Sleeve":"63 cm","Tall":true},"notes":null,
             "location":null,"status":"new","hub_order_id":null,"hub_order_number":null,"pushable":false}}
            """).enquiry!
        XCTAssertEqual(Set(r.measurements.values.map { CustomerWords.display($0) }), ["104", "63 cm", "true"])
        XCTAssertNil(try NeemaJSON.decode(EnquiryResponse.self, from: #"{"enquiry":null}"#).enquiry)
        let vm = await vm()
        XCTAssertTrue((calls("GET", "/admin/production/conversation/c1").first?.query ?? "").isEmpty)
        XCTAssertEqual(vm.ui.enquiry?.id, CustomerFixtures.ENQUIRY_ID)
    }

    func testPushingDecodesBothTheFirstAndTheRepeatedPushReplies() async throws {
        let first = try NeemaJSON.decode(PushResponse.self, from: CustomerFixtures.pushed)
        XCTAssertEqual(first.hubOrderNumber, "BH-2001")
        let again = try NeemaJSON.decode(PushResponse.self, from: CustomerFixtures.alreadyPushed)
        XCTAssertEqual(again.hubOrderNumber, "BH-2001")
        XCTAssertTrue(again.already)

        let path = "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/push"
        fake.on("POST", path, body: CustomerFixtures.pushed)
        let vm = await vm()
        vm.pushProduction(); await drain()
        XCTAssertEqual(calls("POST", path).first?.body, "{}")
        XCTAssertEqual(vm.ui.enquiry?.status, "pushed")
        XCTAssertEqual(lastToast()?.message, "Sent to production · BH-2001")
    }

    func testAPushWithNoLinkedHubProductSaysWhatToDoInstead() async {
        let path = "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/push"
        fake.on("POST", path, code: 422, body: #"{"detail":"This enquiry has no linked hub product — create the order in the hub manually."}"#)
        let vm = await vm()
        vm.pushProduction(); await drain()
        XCTAssertEqual(lastToast()?.message, "This enquiry has no linked hub product — create the order in the hub manually.")
        XCTAssertEqual(vm.ui.enquiry?.status, "new")
        fake.on("POST", path, code: 502, body: #"{"detail":"Hub rejected the order: 500 Server Error"}"#)
        vm.pushProduction(); await drain()
        // The hub's exception text is not for people.
        XCTAssertEqual(lastToast()?.message, "Couldn't send to production — the hub didn't accept it. Try again in a moment.")
        fake.on("POST", path, code: 404, body: #"{"detail":"Enquiry not found"}"#)
        vm.pushProduction(); await drain()
        XCTAssertEqual(lastToast()?.message, "This made-to-order request no longer exists — someone may have removed it.")
        XCTAssertNil(vm.ui.enquiry)
        XCTAssertFalse(vm.ui.pushing)
    }

    func testDecliningPostsAnEmptyObjectAndTrustsTheOkReply() async {
        let vm = await vm()
        vm.declineProduction(); await drain()
        XCTAssertEqual(calls("POST", "/admin/production/\(CustomerFixtures.ENQUIRY_ID)/decline").first?.body, "{}")
        XCTAssertEqual(vm.ui.enquiry?.status, "declined")
    }

    // ── Pipeline stages GET / PUT ───────────────────────────────────────────

    func testPipelineStagesAreReadOnceAndPutAsAStagesList() async {
        let vm = await vm()
        XCTAssertEqual(calls("GET", "/admin/settings/pipeline-stages").count, 1)
        XCTAssertEqual(vm.ui.customStages, ["measuring"])
        fake.on("PUT", "/admin/settings/pipeline-stages", body: #"{"ok":true,"stages":["measuring","Sampling"]}"#)
        vm.saveCustomStages(["measuring", "Sampling", "won"]); await drain()
        XCTAssertEqual(calls("PUT", "/admin/settings/pipeline-stages").first?.body, #"{"stages":["measuring","Sampling","won"]}"#)
        XCTAssertEqual(vm.ui.customStages, ["measuring", "Sampling"])
    }

    // ── Invite / call permission / ask / answer ─────────────────────────────

    func testTheInviteSendsTheServersFieldNamesAndACallNeverAsksForPermission() async {
        fake.on("POST", "/admin/whatsapp-invite", body: #"{"ok":true,"wa_id":"254712345678"}"#)
        host.callOutcome = .shown
        let vm = await vm()
        vm.sendTemplate(CustomerFixtures.PETER); await drain()
        let body = lastBody("POST", "/admin/whatsapp-invite")
        XCTAssertEqual(body["phone"]?.content, "+254712345678")
        XCTAssertEqual(body["name"]?.content, "Fr. Peter Kamau")
        // The call request is the agent's own tap on the call screen: never sent from here.
        vm.call(CustomerFixtures.PETER); await drain()
        XCTAssertTrue(calls("POST", "/admin/calls/request-permission").isEmpty)
    }

    func testAnswerViaNeemaReadsTheServersErrors() async {
        let vm = await vm()
        fake.on("POST", "/admin/conversations/c1/answer", code: 409,
                body: #"{"detail":"outside the messaging window — send it as a template, or reply yourself when they next write"}"#)
        vm.answerViaNeema("yes, KES 3,500"); await drain()
        XCTAssertEqual(vm.ui.answerStatus, "Outside the messaging window — reply yourself when they next write.")
        fake.on("POST", "/admin/conversations/c1/answer", code: 502, body: #"{"detail":"Neema could not compose the answer"}"#)
        vm.answerViaNeema("yes, KES 3,500"); await drain()
        XCTAssertEqual(vm.ui.answerStatus, "Couldn't send right now — try again.")
        fake.on("POST", "/admin/conversations/c1/ask", body: #"{"answer":"I couldn't find that in what we have on file."}"#)
        vm.ask("sizes?"); await drain()
        XCTAssertEqual(vm.ui.askAnswer, "I couldn't find that in what we have on file.")
    }

    /// The panel's orders: the profile's hub history first, the local WhatsApp orders only without it.
    func testThePanelContextPrefersHubHistoryAndFallsBackToLocalOrders() async throws {
        let p = await vm().profile!
        let local = try NeemaJSON.decode([Order].self, from: Fixtures.orders)
        let ctx = PanelCtx.make(profile: p, allOrders: local, waId: CustomerFixtures.PETER, customStages: ["measuring"], isAdmin: true)
        XCTAssertEqual(ctx.orders.count, 4)
        XCTAssertEqual(ctx.orderCount, 24)
        XCTAssertEqual(ctx.totalSpent, 486500)
        XCTAssertEqual(ctx.lastOrder?.orderNumber, "BH-1042")
        XCTAssertEqual(ctx.stage, "proposal")
        var bare = p; bare.orders = nil; bare.totalSpent = 0; bare.totalOrders = 0
        let fallback = PanelCtx.make(profile: bare, allOrders: local, waId: CustomerFixtures.PETER, customStages: [], isAdmin: false)
        XCTAssertEqual(fallback.orders.map { $0.source }, Array(repeating: "whatsapp", count: fallback.orders.count))
        XCTAssertFalse(fallback.orders.isEmpty)
        XCTAssertEqual(fallback.orderCount, fallback.orders.count)
        XCTAssertEqual(fallback.totalSpent, fallback.orders.reduce(0) { $0 + $1.amount })
    }
}
