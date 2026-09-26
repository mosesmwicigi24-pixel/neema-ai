package ke.co.bethanyhouse.neema.customer

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerProfile
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerViewModel
import ke.co.bethanyhouse.neema.feature.conversations.customer.EnquiryResponse
import ke.co.bethanyhouse.neema.feature.conversations.customer.MergeSuggestionsResponse
import ke.co.bethanyhouse.neema.feature.conversations.customer.PanelCtx
import ke.co.bethanyhouse.neema.feature.conversations.customer.PanelOrder
import ke.co.bethanyhouse.neema.feature.conversations.customer.PushResponse
import ke.co.bethanyhouse.neema.feature.conversations.customer.StageCache
import ke.co.bethanyhouse.neema.feature.conversations.customer.canonicalStage
import ke.co.bethanyhouse.neema.feature.conversations.customer.display
import ke.co.bethanyhouse.neema.feature.conversations.customer.isoOf
import ke.co.bethanyhouse.neema.feature.conversations.customer.nextStage
import ke.co.bethanyhouse.neema.feature.conversations.customer.sourceMeta
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CustomerFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The CRM panel against the REAL server contract (apps/api/app/routers/crm.py and
 * the admin.py routes it borrows): each request's method, path, query and body,
 * and each response decoded in the shapes — and the odd variants — the
 * handlers can actually produce.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CustomerContractTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private lateinit var fake: FakeNeema
    private lateinit var dash: DashboardViewModel
    private val toasts = mutableListOf<Toast>()
    private val scope = CoroutineScope(UnconfinedTestDispatcher())

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher())
        StageCache.stages = null
        fake = FakeNeema.withFixtures().also(CustomerFixtures::install)
        dash = dashboard(paparazzi.context, fake, "admin", true)
        scope.launch { dash.toasts.collect { toasts += it } }
    }

    @After fun tearDown() {
        scope.cancel()
        Dispatchers.resetMain()
        StageCache.stages = null
    }

    private fun vm(conv: String = "c1") = CustomerViewModel(dash, CustomerFixtures.conversation(conv)) { _, _ -> Result.success(Unit) }
    private fun calls(method: String, path: String) = fake.calls.filter { it.method == method && it.path == path }
    private fun profile(json: String) = NeemaJson.decodeFromString(CustomerProfile.serializer(), json)
    private fun order(json: String) = NeemaJson.decodeFromString(PanelOrder.serializer(), json)
    private val peterPath = "/admin/customers/${CustomerFixtures.PETER}"

    // ── GET /admin/customers/{wa_id} (get_customer → _build_profile) ────────

    @Test fun theProfileIsFetchedByHandleWithTheChannelAndDecodesTheServersNumbers() {
        val p = vm().profile.value!!
        val get = calls("GET", peterPath).single()
        assertEquals("channel=whatsapp", get.query)
        assertNull(get.body)
        assertEquals(95.0, p.leadScore, 0.0)
        assertEquals(9, p.leadScoreBreakdown.size)
        assertEquals(120.0, p.leadScoreBreakdown.sumOf { it.max }, 0.0)
        assertEquals(95.0, p.leadScoreBreakdown.sumOf { it.pts }, 0.0)
        assertEquals(24, p.totalOrders)
        assertEquals(486500.0, p.totalSpent, 0.0)
        assertEquals(20270.83, p.avgOrderValue!!, 0.0)
        assertEquals(70, p.buyingRhythm!!.daysSinceLast)
        assertEquals(30.0, p.buyingRhythm!!.avgIntervalDays!!, 0.0)
        assertEquals("about every 4 weeks", p.buyingRhythm!!.cadenceLabel)
        assertTrue(p.buyingRhythm!!.overdue)
        assertEquals("vip", p.tier)
        assertTrue(p.hubLinked)
        assertEquals("311", p.hubCustomerId.toString())
        // Hub order lines: qty and quantity both carry the hub's raw quantity.
        val first = p.orders!!.first()
        assertEquals("hub", first.source)
        assertEquals(2.0, first.items.first().qty!!, 0.0)
        assertEquals(7000.0, first.items.first().total!!, 0.0)
        // Python's tz-aware isoformat ("+00:00") parses.
        assertNotNull(Fmt.millis(p.lastOrderAt))
        assertNotNull(Fmt.millis(p.channels.first().lastSeen))
    }

    @Test fun theNoHubFallbackSendsIntegerZerosAndAnAlwaysPresentRhythm() {
        val p = vm("c2").profile.value!!
        assertEquals(0.0, p.totalSpent, 0.0)
        assertEquals(0.0, p.avgOrderValue!!, 0.0)
        assertEquals(emptyList<PanelOrder>(), p.orders)
        // _buying_rhythm([]) is an object of nulls, never null itself.
        val r = p.buyingRhythm!!
        assertNull(r.daysSinceLast); assertNull(r.avgIntervalDays); assertNull(r.cadenceLabel); assertFalse(r.overdue)
        assertNull("a Messenger conversation has no wa_id", p.channels.single().identifier)
    }

    @Test fun decimalStringsAndQuotedIntsDecodeAsNumbers() {
        // jsonable_encoder turns Decimal into a number today; a Decimal-as-string must not break the panel.
        val p = profile(
            """{"id":"u","wa_id":"254700000001","lead_score":"95","total_orders":"3","total_spent":"486500.00",
               "avg_order_value":"162166.67","age":"47",
               "buying_rhythm":{"days_since_last":"12","avg_interval_days":"30.5","cadence_label":"about every 4 weeks","overdue":false},
               "lead_score_breakdown":[{"label":"Orders","pts":"25","max":"25"}],
               "orders":[{"id":90412,"order_number":1042,"total":"8000.00","subtotal":"8000.00","items":[]}]}""",
        )
        assertEquals(95.0, p.leadScore, 0.0)
        assertEquals(3, p.totalOrders)
        assertEquals(486500.0, p.totalSpent, 0.0)
        assertEquals(162166.67, p.avgOrderValue!!, 0.0)
        assertEquals(47, p.age)
        assertEquals(12, p.buyingRhythm!!.daysSinceLast)
        assertEquals(30.5, p.buyingRhythm!!.avgIntervalDays!!, 0.0)
        assertEquals(25.0, p.leadScoreBreakdown.single().pts, 0.0)
        // A numeric id / order_number (hub passes order_number through raw) still reads as text.
        assertEquals("90412", p.orders!!.single().id)
        assertEquals("1042", p.orders!!.single().orderNumber)
        assertEquals(8000.0, p.orders!!.single().amount, 0.0)
    }

    @Test fun missingOptionalFieldsAndNullsForDefaultedOnesDecode() {
        // A bare profile: every optional field missing.
        val bare = profile("""{"id":"u","wa_id":"254700000001"}""")
        assertEquals("new", bare.leadStage)
        assertEquals(emptyList<String>(), bare.tags)
        assertNull(bare.orders)
        assertNull(bare.buyingRhythm)
        assertEquals(0.0, bare.leadScore, 0.0)
        // Explicit nulls where the model has a default (a legacy User row: name_confirmed NULL, no state).
        val nulls = profile(
            """{"id":"u","wa_id":"254700000001","name_confirmed":null,"tags":null,"lead_stage":null,"merged_ids":null,
               "linked_identities":null,"channels":null,"lead_score_breakdown":null,"hub_linked":null,"phone_verified":null,
               "cart_items":null,"total_orders":null,"total_spent":null,"lead_score":null,"orders":null,
               "measurements":{},"parish":null,"ad_ref":null,"hub_customer_id":null}""",
        )
        assertFalse(nulls.nameConfirmed)
        assertEquals("new", nulls.leadStage)
        assertEquals(emptyList<String>(), nulls.tags)
        assertEquals(0, nulls.totalOrders)
        assertEquals(0.0, nulls.totalSpent, 0.0)
    }

    @Test fun hubOrderQuirksDecodeWithoutSinkingTheProfile() {
        // _map_hub_order: quantity passes through raw (a Laravel decimal string, even junk);
        // total may be null (`_f` of a blank); created_at is the hub's own string.
        val o = order(
            """{"id":"1","order_number":"BH-1","status":"completed","payment_status":null,"order_type":"pos",
               "total":null,"subtotal":4800.0,"currency_code":"USD","created_at":"2026-09-20 08:15:30",
               "items":[{"name":"Stole — Green","qty":"2.00","quantity":"2.00","unit_price":2400.0,"total":4800.0},
                        {"name":"Gift wrap","qty":"n/a","quantity":"n/a","unit_price":0,"total":0}],
               "source":"hub"}""",
        )
        assertEquals(2.0, o.items[0].qty!!, 0.0)
        assertNull("junk is no number", o.items[1].qty)
        assertEquals(4800.0, o.amount, 0.0)
        assertEquals("2026-09-20T08:15:30", o.createdIso)
        assertEquals(java.time.Instant.parse("2026-09-20T08:15:30Z").toEpochMilli(), Fmt.millis(o.createdIso))
        assertEquals("a hub order keeps its own currency", "USD", o.displayCurrency)
    }

    @Test fun aLocalWhatsAppOrderIsTheCartsShapeAndStaysInShillings() {
        // crm.py _map_local_order: subtotal is the cart's KES total; `currency` is whatever the hub said.
        val o = order(
            """{"id":"254712345678_1758790000000","order_number":"BH-2001","status":"pending","payment_status":"unpaid",
               "total":3500.0,"subtotal":3500.0,"currency_code":"USD","created_at":"2026-09-20T08:15:30.123456+00:00",
               "items":[{"name":"Clergy Shirt","sku":"CS-16","qty":1,"unit_price":3500.0,"price_usd":27.0,
                         "prices":{"ZMW":720},"in_stock":true,"made_to_order":false}],
               "source":"whatsapp"}""",
        )
        assertEquals(1.0, o.items.single().qty!!, 0.0)
        assertNull("cart lines carry no total", o.items.single().total)
        assertEquals("KES", o.displayCurrency)
        assertNotNull(Fmt.millis(o.createdIso))
    }

    @Test fun theWebhooksAdSourcesReadAsAds() {
        assertEquals("Facebook ad" to "📘", sourceMeta("facebook_ad"))
        assertEquals("Instagram ad" to "📸", sourceMeta("instagram_ad"))
        assertEquals("Facebook" to "📘", sourceMeta("facebook"))
        assertEquals("Walk-in" to "🚶", sourceMeta("walk_in"))
        assertNull("unknown: the row prints the raw value with the • icon", sourceMeta("billboard"))
        assertNull(sourceMeta("billboard_ad"))
    }

    @Test fun timestampsAreNormalisedOnlyWhenTheyNeedIt() {
        assertNull(isoOf(null)); assertNull(isoOf("  "))
        assertEquals("2026-09-20T08:15:30.000000Z", isoOf("2026-09-20T08:15:30.000000Z"))
        assertEquals("2026-09-20T08:15:30+03:00", isoOf("2026-09-20 08:15:30+03:00"))
        assertEquals("2026-09-20", isoOf("2026-09-20"))
        assertNotNull(Fmt.millis(isoOf("2026-09-20 08:15:30+03:00")))
    }

    // ── lead_stage: normalise_stage lower-cases what's stored ───────────────

    @Test fun aCustomStageComesBackLowerCasedAndStillLightsItsNode() {
        StageCache.stages = listOf("Sampling", "Fitting")
        val vm = vm()
        vm.setStage("Sampling")
        assertEquals("""{"lead_stage":"Sampling"}""", calls("PATCH", peterPath).last().body)
        // The reload answers as crm.py does: normalise_stage("Sampling") == "sampling".
        fake.on("GET", peterPath, body = CustomerFixtures.peter.replace("\"lead_stage\":\"proposal\"", "\"lead_stage\":\"sampling\""))
        vm.load(showSpinner = false)
        val p = vm.profile.value!!
        assertEquals("sampling", p.leadStage)
        val ctx = PanelCtx(p, p.orders!!, p.totalSpent, null, listOf("Sampling", "Fitting"), true, true, true)
        assertEquals("Sampling", ctx.stage)
        assertEquals("Advance moves on to the next custom stage, not back to New", "Fitting", nextStage(ctx.stage, ctx.customStages))
    }

    @Test fun stagesCanonicaliseAndAdvanceAlongTheForwardPath() {
        val customs = listOf("Sampling")
        assertEquals("negotiation", canonicalStage("negotiating", customs))
        assertEquals("won", canonicalStage("Won", customs))
        assertEquals("new", canonicalStage(null, customs))
        assertEquals("Sampling", canonicalStage("SAMPLING", customs))
        assertEquals("a removed custom keeps its own name", "fitting", canonicalStage("fitting", customs))
        assertEquals("contacted", nextStage("new", customs))
        assertEquals("negotiation", nextStage("proposal", customs))
        assertEquals("Sampling", nextStage("negotiation", customs))
        assertEquals("won", nextStage("Sampling", customs))
        assertEquals("won", nextStage("won", customs))
        assertEquals("won", nextStage("lost", customs))
        assertEquals("a removed custom advances from where customs sit", "Sampling", nextStage("fitting", customs))
        assertEquals("won", nextStage("fitting", emptyList()))
    }

    // ── PATCH /admin/customers/{wa_id} (update_customer → {"ok": true}) ─────

    @Test fun aPatchTheServerCannotPlaceRollsBack() {
        val vm = vm()
        fake.on("PATCH", "/admin/customers/[^/]+", code = 404, body = """{"detail":"Customer not found"}""")
        vm.saveField("email", "new@x.org") { it.copy(email = "new@x.org") }
        assertEquals("channel=whatsapp", calls("PATCH", peterPath).last().query)
        assertEquals("""{"email":"new@x.org"}""", calls("PATCH", peterPath).last().body)
        assertEquals("peter.kamau@stmarks.or.ke", vm.profile.value!!.email)
        // crm.py's only 404 here: no user and no conversation for the key — merged or removed meanwhile.
        assertEquals("Failed to save — this customer's profile is gone (it may have been merged into another). Refreshing.", toasts.last().message)
        assertEquals(ToastType.Error, toasts.last().type)
    }

    @Test fun notesSendTheirBaseSoTheServersThreeWayMergeKeepsACallSummary() {
        val vm = vm()
        vm.saveNotes("Prefers delivery to the parish office.")
        val body = NeemaJson.parseToJsonElement(calls("PATCH", peterPath).last().body!!).jsonObject
        assertEquals(setOf("notes", "notes_base"), body.keys)
        assertEquals("\"Prefers delivery to the parish office.\\n\\nAsk about the Easter order in March.\"", body["notes_base"].toString())
    }

    // ── Merge suggestions / merge / unmerge ─────────────────────────────────

    @Test fun mergeSuggestionsAreAskedForOnTheProfileKeyWithTheChannel() {
        val vm = vm()
        vm.toggleMerge(true)
        val get = calls("GET", "$peterPath/merge_suggestions").single()
        assertEquals("channel=whatsapp", get.query)
        val s = vm.mergeSugs.value!!
        assertEquals(listOf("strong", "possible"), s.map { it.strength })
        assertNull(s[1].phone)
        assertEquals("social", s[1].channelHint)
        // A 404 (no such customer) reads as "nothing found", not a spinner.
        fake.on("GET", "/admin/customers/[^/]+/merge_suggestions", code = 404, body = """{"detail":"Customer not found"}""")
        vm.toggleMerge(false); vm.toggleMerge(true)
        assertEquals(emptyList<Any>(), vm.mergeSugs.value)
    }

    @Test fun mergeAndUnmergePostTheirTargetAsMergeWith() {
        val vm = vm()
        vm.merge(" 254799000222 ")
        val m = calls("POST", "$peterPath/merge").single()
        assertEquals("channel=whatsapp", m.query)
        assertEquals("""{"merge_with":"254799000222"}""", m.body)
        assertEquals("Profiles merged successfully", toasts.last().message)
        vm.unmerge("254799000111")
        val u = calls("POST", "$peterPath/unmerge").single()
        assertEquals("channel=whatsapp", u.query)
        assertEquals("""{"merge_with":"254799000111"}""", u.body)
        fake.on("POST", "/admin/customers/[^/]+/unmerge", code = 404, body = """{"detail":"No active merge to undo for this pair"}""")
        vm.unmerge("254799000111")
        // Nothing left to undo: a colleague already unmerged it — not a failure.
        assertEquals("Already unmerged — refreshed to show where it stands.", toasts.last().message)
    }

    // ── Production enquiry (get_conversation_enquiry / push / decline) ──────

    @Test fun theEnquiryDecodesMeasurementsOfAnyJsonType() {
        val r = NeemaJson.decodeFromString(
            EnquiryResponse.serializer(),
            """{"enquiry":{"id":"${CustomerFixtures.ENQUIRY_ID}","created_at":null,"product_name":null,"product_slug":null,
               "customer_name":null,"phone":null,"measurements":{"Chest":104,"Sleeve":"63 cm","Tall":true},"notes":null,
               "location":null,"status":"new","hub_order_id":null,"hub_order_number":null,"pushable":false}}""",
        ).enquiry!!
        assertEquals(listOf("104", "63 cm", "true"), r.measurements.values.map { it.display() })
        assertNull(NeemaJson.decodeFromString(EnquiryResponse.serializer(), """{"enquiry":null}""").enquiry)
        val vm = vm()
        assertTrue(calls("GET", "/admin/production/conversation/c1").single().query.isNullOrEmpty())
        assertEquals(CustomerFixtures.ENQUIRY_ID, vm.enquiry.value!!.id)
    }

    @Test fun pushingDecodesBothTheFirstAndTheRepeatedPushReplies() {
        val first = NeemaJson.decodeFromString(PushResponse.serializer(), CustomerFixtures.pushed)
        assertEquals("BH-2001", first.hubOrderNumber)
        val again = NeemaJson.decodeFromString(PushResponse.serializer(), CustomerFixtures.alreadyPushed)
        assertEquals("BH-2001", again.hubOrderNumber)

        val path = "/admin/production/${CustomerFixtures.ENQUIRY_ID}/push"
        fake.on("POST", path, body = CustomerFixtures.pushed)
        val vm = vm()
        vm.pushProduction()
        assertEquals("{}", calls("POST", path).single().body)
        assertEquals("pushed", vm.enquiry.value!!.status)
        assertEquals("Sent to production · BH-2001", toasts.last().message)
    }

    @Test fun aPushWithNoLinkedHubProductSaysWhatToDoInstead() {
        val path = "/admin/production/${CustomerFixtures.ENQUIRY_ID}/push"
        fake.on("POST", path, code = 422,
            body = """{"detail":"This enquiry has no linked hub product — create the order in the hub manually."}""")
        val vm = vm()
        vm.pushProduction()
        assertEquals("This enquiry has no linked hub product — create the order in the hub manually.", toasts.last().message)
        assertEquals("new", vm.enquiry.value!!.status)
        fake.on("POST", path, code = 502, body = """{"detail":"Hub rejected the order: 500 Server Error"}""")
        vm.pushProduction()
        // The hub's exception text is not for people.
        assertEquals("Couldn't send to production — the hub didn't accept it. Try again in a moment.", toasts.last().message)
        fake.on("POST", path, code = 404, body = """{"detail":"Enquiry not found"}""")
        vm.pushProduction()
        assertEquals("This made-to-order request no longer exists — someone may have removed it.", toasts.last().message)
        assertNull(vm.enquiry.value)
        assertFalse(vm.pushing.value)
    }

    @Test fun decliningPostsAnEmptyObjectAndTrustsTheOkReply() {
        val vm = vm()
        vm.declineProduction()
        assertEquals("{}", calls("POST", "/admin/production/${CustomerFixtures.ENQUIRY_ID}/decline").single().body)
        assertEquals("declined", vm.enquiry.value!!.status)
    }

    // ── Pipeline stages GET / PUT ───────────────────────────────────────────

    @Test fun pipelineStagesAreReadOnceAndPutAsAStagesList() {
        val vm = vm()
        assertEquals(1, calls("GET", "/admin/settings/pipeline-stages").size)
        assertEquals(listOf("measuring"), vm.customStages.value)
        fake.on("PUT", "/admin/settings/pipeline-stages", body = """{"ok":true,"stages":["measuring","Sampling"]}""")
        vm.saveCustomStages(listOf("measuring", "Sampling", "won"))
        assertEquals("""{"stages":["measuring","Sampling","won"]}""", calls("PUT", "/admin/settings/pipeline-stages").single().body)
        assertEquals(listOf("measuring", "Sampling"), vm.customStages.value)
    }

    // ── Invite / call permission / ask / answer ─────────────────────────────

    @Test fun theInviteAndThePermissionRequestSendTheServersFieldNames() {
        fake.on("POST", "/admin/whatsapp-invite", body = """{"ok":true,"wa_id":"254712345678"}""")
        val vm = CustomerViewModel(dash, CustomerFixtures.conversation("c1")) { _, _ ->
            Result.failure(IllegalStateException("This customer hasn't granted call permission yet. Send the WhatsApp template first, or wait until they message/call us."))
        }
        vm.sendTemplate(CustomerFixtures.PETER)
        assertEquals("""{"phone":"+254712345678","name":"Fr. Peter Kamau"}""", calls("POST", "/admin/whatsapp-invite").single().body)
        vm.call(CustomerFixtures.PETER)
        assertEquals("""{"to":"254712345678"}""", calls("POST", "/admin/calls/request-permission").single().body)
        fake.on("POST", "/admin/calls/request-permission", code = 400, body = """{"detail":"A valid phone number is required."}""")
        vm.call(CustomerFixtures.PETER)
        assertEquals("Couldn't send the call request — a valid phone number is required.", toasts.last().message)
    }

    @Test fun answerViaNeemaReadsTheServersErrors() {
        val vm = vm()
        fake.on("POST", "/admin/conversations/c1/answer", code = 409,
            body = """{"detail":"outside the messaging window — send it as a template, or reply yourself when they next write"}""")
        vm.answerViaNeema("yes, KES 3,500") {}
        assertEquals("Outside the messaging window — reply yourself when they next write.", vm.answerStatus.value)
        fake.on("POST", "/admin/conversations/c1/answer", code = 502, body = """{"detail":"Neema could not compose the answer"}""")
        vm.answerViaNeema("yes, KES 3,500") {}
        assertEquals("Couldn't send right now — try again.", vm.answerStatus.value)
        fake.on("POST", "/admin/conversations/c1/ask", body = """{"answer":"I couldn't find that in what we have on file."}""")
        vm.ask("sizes?")
        assertEquals("I couldn't find that in what we have on file.", vm.askAnswer.value)
    }
}
