package ke.co.bethanyhouse.neema.reports

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.Attribution
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.CatalogVariant
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.model.PriceAudit
import ke.co.bethanyhouse.neema.core.model.Stats
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.catalog.CatalogViewModel
import ke.co.bethanyhouse.neema.feature.overview.OverviewViewModel
import ke.co.bethanyhouse.neema.feature.overview.activityFeed
import ke.co.bethanyhouse.neema.feature.overview.channelRows
import ke.co.bethanyhouse.neema.feature.overview.topProducts
import ke.co.bethanyhouse.neema.feature.reports.ReportRange
import ke.co.bethanyhouse.neema.feature.reports.ReportsViewModel
import ke.co.bethanyhouse.neema.feature.reports.buildReport
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Ignore
import org.junit.Rule
import org.junit.Test
import java.time.Instant

/**
 * The contract between Reports / Analytics / Catalog and the real API
 * handlers (apps/api/app/routers): the exact request each screen sends, and
 * that the responses those handlers actually produce — including their
 * awkward variants — decode into what the screens show. Handler named on
 * each test. (Paparazzi supplies a real Android Context; nothing is rendered.)
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ApiContractTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scope = CoroutineScope(Dispatchers.Unconfined)
    private val toasts = mutableListOf<Toast>()

    @Before fun setUp() = Dispatchers.setMain(UnconfinedTestDispatcher())
    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun fake() = FakeNeema.withFixtures().also(ReportsFixtures::install)

    private fun dash(f: FakeNeema): DashboardViewModel =
        dashboard(paparazzi.context, f).also { d -> scope.launch { d.toasts.collect { toasts += it } } }

    private fun FakeNeema.gets(path: String) = calls.filter { it.method == "GET" && it.path == path }
    private fun FakeNeema.nonGets() = calls.filter { it.method != "GET" }

    private val agents: List<Agent> = NeemaJson.decodeFromString(Fixtures.agents)

    // ── Requests ────────────────────────────────────────────────────────────

    /** admin.py list_conversations: no `limit` → the full legacy array. Nothing else is sent. */
    @Test fun reports_request_isOneBareGet() {
        val f = fake()
        ReportsViewModel(dash(f))
        val call = f.gets("/admin/conversations").single()
        assertNull(call.query)
        assertNull(call.body)
        assertTrue(call.headers["Authorization"]!!.startsWith("Bearer "))
    }

    /** Pull-to-refresh: the orders and every conversation again, the spinner down once all have landed. */
    @Test fun reports_refresh_reReadsOrdersAgentsAndEveryConversation() {
        val f = fake()
        val vm = ReportsViewModel(dash(f))
        val before = f.gets("/admin/orders").size
        vm.refresh()
        assertEquals(2, f.gets("/admin/conversations").size)
        assertTrue(f.gets("/admin/orders").size > before)
        assertFalse(vm.refreshing.value)
    }

    /** overview_stats, crm.attribution, list_conversations(tab=human, limit=10) — the web's three calls, exactly. */
    @Test fun overview_requests() {
        val f = fake()
        OverviewViewModel(dash(f))
        assertEquals(listOf<String?>(null), f.gets("/admin/stats").map { it.query })
        assertEquals(listOf<String?>(null), f.gets("/admin/attribution").map { it.query })
        assertEquals(listOf<String?>("limit=10&tab=human"), f.gets("/admin/conversations").map { it.query })
        assertTrue(f.nonGets().isEmpty())
    }

    /** list_catalog with no filters (the screen filters locally, like the web), and the audit. Read-only. */
    @Test fun catalog_requests() {
        val f = fake()
        CatalogViewModel(dash(f))
        assertTrue(f.gets("/admin/catalog").all { it.query == null })
        assertEquals(listOf<String?>(null), f.gets("/admin/catalog/audit").map { it.query })
        assertTrue(f.nonGets().isEmpty())
    }

    /** The dashboard lists these screens read: list_orders and list_agents, unfiltered. */
    @Test fun sharedLists_areUnfiltered() {
        val f = fake()
        dash(f)
        assertTrue(f.gets("/admin/orders").isNotEmpty() && f.gets("/admin/orders").all { it.query == null })
        assertTrue(f.gets("/admin/agents").isNotEmpty() && f.gets("/admin/agents").all { it.query == null })
    }

    // ── /admin/conversations (no limit) ─────────────────────────────────────

    /** Every key `_conversation_rows()` emits decodes; "+00:00" offsets with microseconds parse. */
    @Test fun reports_decodesTheRealRowShape() {
        val vm = ReportsViewModel(dash(fake()))
        val rows = vm.allConvs.value!!
        assertEquals(9, rows.size)
        val r1 = rows.first { it.id == "r1" }
        assertEquals("p0000001-0000-4000-8000-000000000001", r1.personId)
        assertEquals("Moses Mwicigi", r1.assignedAgentName)
        assertEquals(2, r1.ordersCount)
        assertEquals(listOf("clergy"), r1.tags)
        // "…T06:59:59.876544+00:00": offset and microseconds both honoured.
        assertEquals(NOW_MS - 2 * 3_600_000 - 124, Fmt.millis(r1.lastMessageAt))
        // A Messenger thread: no wa_id, the PSID is the handle.
        val r2 = rows.first { it.id == "r2" }
        assertNull(r2.waId)
        assertEquals("7012345678901234", r2.handle)
        // No messages yet: last_message_at is null, dated by created_at.
        assertNull(rows.first { it.id == "r9" }.lastMessageAt)
        assertTrue(toasts.isEmpty())
    }

    /** Should the server ever answer the paged envelope, Reports still reads every row (never an error for a 200). */
    @Test fun reports_acceptsThePagedEnvelope() {
        val f = fake()
        f.on("GET", "/admin/conversations", body = """{"items":[${ReportsFixtures.conversations.joinToString(",")}],"next_cursor":"eyJ4Ijoi"}""")
        val vm = ReportsViewModel(dash(f))
        assertEquals(9, vm.allConvs.value?.size)
        assertTrue(toasts.isEmpty())
    }

    /** Naive datetimes are UTC; nulls for defaulted fields and a missing optional key are tolerated. */
    @Test fun reports_naiveDatesNullsAndMissingKeys() {
        val f = fake()
        f.on(
            "GET", "/admin/conversations",
            body = """[{"id":"n1","wa_id":"254700000001","intercept_mode":"human","status":"open","channel":null,"unread":null,
                "tags":null,"last_message_at":"2026-09-25T06:00:00","created_at":"2026-09-01T06:00:00"}]""",
        )
        val vm = ReportsViewModel(dash(f))
        val row = vm.allConvs.value!!.single()
        assertEquals("whatsapp", row.channel)
        assertEquals(0, row.unread)
        assertEquals(emptyList<String>(), row.tags)
        assertEquals(Instant.parse("2026-09-25T06:00:00Z").toEpochMilli(), Fmt.millis(row.lastMessageAt))
        val r = buildReport(listOf(row), emptyList(), emptyList(), ReportRange.D7, null, null, NOW_MS, ReportsFixtures.NAIROBI)
        assertEquals(1, r.humanConvs)
    }

    /** A 500's FastAPI `{"detail": …}`, a proxy's HTML 502, and a network failure all read the same: empty + one toast. */
    @Test fun reports_errorBodies() {
        for ((code, body) in listOf(500 to """{"detail":"Internal Server Error"}""", 502 to "<html>Bad Gateway</html>")) {
            toasts.clear()
            val f = fake()
            f.on("GET", "/admin/conversations", code = code, body = body)
            val vm = ReportsViewModel(dash(f))
            assertEquals(emptyList<Any>(), vm.allConvs.value)
            assertEquals(listOf("Could not load conversations for this report."), toasts.filter { it.type == ToastType.Error }.map { it.message })
        }
    }

    // ── /admin/stats ────────────────────────────────────────────────────────

    /** overview_stats: ints and a float revenue; channel rows in the server's order, "web" kept for the panel to skip. */
    @Test fun stats_everyField() {
        val vm = OverviewViewModel(dash(fake()))
        val s = vm.stats.value!!
        assertEquals(
            listOf(128, 9, 119, 2, 3, 284, 21, 203, 48, 12, 187, 214),
            listOf(
                s.openConversations, s.humanConversations, s.aiConversations, s.activeAgents, s.totalAgents,
                s.totalOrders, s.pendingOrders, s.deliveredOrders, s.confirmedOrders, s.cancelledOrders, s.inStockItems, s.totalItems,
            ),
        )
        assertEquals(1_284_500.0, s.totalRevenue, 0.0)
        assertEquals(listOf("whatsapp", "messenger", "facebook", "instagram", "web"), s.channelBreakdown.map { it.channel })
    }

    /** A NULL channel group (never expected, but the column is only NOT NULL by convention) and missing keys don't sink the call. */
    @Test fun stats_nullChannelAndMissingKeys() {
        val s: Stats = NeemaJson.decodeFromString("""{"open_conversations":1,"channel_breakdown":[{"channel":null,"count":2,"open":1}]}""")
        assertEquals(1, s.openConversations)
        assertEquals(0.0, s.totalRevenue, 0.0)
        assertEquals("", channelRows(s, emptyList()).single().ch)
    }

    /** The stats query never touches the hub, so a hub outage can't fail it; a DB failure (500) takes the fallback path quietly. */
    @Test fun stats_failure_fallsBackWithoutAnErrorToast() {
        val f = fake()
        f.on("GET", "/admin/stats", code = 500, body = """{"detail":"Internal Server Error"}""")
        val vm = OverviewViewModel(dash(f))
        assertNull(vm.stats.value)
        assertEquals(9, vm.fallbackConvs.value.size)
        assertTrue(toasts.none { it.type == ToastType.Error })
    }

    // ── /admin/conversations?tab=human&limit=10 ─────────────────────────────

    /** The page carries every thread of each person on it: the feed keeps only the human-held ones. */
    @Test fun humanPage_siblingThreadsAreFilteredFromTheFeed() {
        val vm = OverviewViewModel(dash(fake()))
        val feed = activityFeed(emptyList(), vm.humanRows.value!!, agents)
        assertEquals(listOf("conv-r1", "conv-r5", "conv-r6"), feed.map { it.id })
        assertEquals("Moses Mwicigi", feed.first().user)
    }

    /** `limit` out of 1-200 is a 400 with a string detail: the feed falls back to the inbox's first page. */
    @Test fun humanPage_400_fallsBack() {
        val f = fake()
        f.on("GET", "/admin/conversations") { r, _ ->
            if (r.url.queryParameter("tab") == "human") 400 to """{"detail":"limit must be 1-200"}"""
            else 200 to """{"items":[${ReportsFixtures.conversations.joinToString(",")}],"next_cursor":null}"""
        }
        val vm = OverviewViewModel(dash(f))
        assertNull(vm.humanRows.value)
        assertEquals(9, vm.fallbackConvs.value.size)
    }

    // ── /admin/attribution ──────────────────────────────────────────────────

    @Test fun attribution_realShape() {
        val a: Attribution = NeemaJson.decodeFromString(ReportsFixtures.attribution)
        assertEquals(listOf("organic", "facebook", "instagram"), a.sources.map { it.source })
        assertEquals("Easter vestments sale", a.sources[1].postTitle)
        assertNull(a.sources[2].postTitle)
        assertEquals(137, a.totals.leads)
        assertEquals(64_000.0, a.unattributed.revenue, 0.0)
    }

    /** `source_post` comes out of JSONB: a bare number is read as its digits; a null source as "". */
    @Test fun attribution_numericPostIds_andNulls() {
        val a: Attribution = NeemaJson.decodeFromString(
            """{"sources":[{"source":"facebook","post":104882331001203,"leads":1,"orders":0,"revenue":0.0,"paid_revenue":0.0},
                {"source":null,"post":null,"post_title":null,"leads":2}],"unattributed":{"orders":0,"revenue":0,"paid_revenue":0},
                "totals":{"leads":3,"orders":0,"revenue":0}}""",
        )
        assertEquals("104882331001203", a.sources[0].post)
        assertEquals("", a.sources[1].source)
    }

    // ── /admin/orders ───────────────────────────────────────────────────────

    /** Bare OrderEvent rows: every column, no contact_name, both item shapes, the hub linkage. */
    @Test fun orders_realRows() {
        val d = dash(fake())
        val orders = d.orders.value
        assertEquals(7, orders.size)
        val o1 = orders.first { it.id == "o1" }
        assertNull(o1.contactName)
        assertEquals("254712345678", o1.customerName)
        assertEquals(listOf(2.0, 4.0), o1.items.map { it.qty })
        assertEquals(1000.0, o1.items[1].total, 0.0)
        // The agent's own order: pushed to the hub, cart lines with unit_price (no unit / total).
        val o2 = orders.first { it.id == "o2" }
        assertEquals(1042L, o2.hubOrderId)
        assertEquals("BH-1042", o2.hubOrderNumber)
        assertEquals("CAS-PUR-L", o2.items.single().sku)
        assertEquals(1.0, o2.items.single().qty, 0.0)
        assertEquals("pending", orders.first { it.id == "o5" }.status) // an "open" cart snapshot
        assertEquals(NOW_MS - 3_600_000 - 124, Fmt.millis(o1.createdAt))
    }

    /** Numeric(12,2) through jsonable_encoder is a float, but a Decimal serialised as a string must read the same. */
    @Test fun orders_decimalAsString_andNulls() {
        val o: Order = NeemaJson.decodeFromString(
            """{"id":"x","wa_id":"254700000002","subtotal":"8000.00","hub_total":"8000.00","status":null,"state":null,"items":null,
                "payment_status":null,"created_at":"2026-09-25T06:00:00"}""",
        )
        assertEquals(8000.0, o.subtotal, 0.0)
        assertEquals(emptyList<Any>(), o.items)
        val lines: Order = NeemaJson.decodeFromString("""{"id":"y","items":[{"name":"Alb","qty":"2","unit":"6000.00","total":"12000.00"},{"name":null,"qty":null}]}""")
        assertEquals(listOf(2.0, 0.0), lines.items.map { it.qty })
        assertEquals(12000.0, lines.items[0].total, 0.0)
        assertEquals("", lines.items[1].name)
    }

    // ── /admin/catalog ──────────────────────────────────────────────────────

    /** hub_client._map_product + variants: ranges, labels, attributes, "" category, null available_qty. */
    @Test fun catalog_hubRows() {
        val d = dash(fake())
        val items = d.catalog.value
        assertEquals(6, items.size)
        val shirt = items.first { it.sku == "CS-BLK" }
        assertTrue(shirt.isHub)
        assertEquals(3500.0 to 4200.0, shirt.priceMinKes to shirt.priceMaxKes)
        assertEquals("Clergy Shirt — Blue / 16 inch", shirt.variants[2].label)
        assertEquals(mapOf("Colour" to "Blue", "Size" to "16 inch"), shirt.variants[2].attributes)
        assertEquals(32.5, shirt.variants[2].priceUsd!!, 0.0)
        assertNull(items.first { it.sku == "WAF-500" }.availableQty)
        assertEquals("", items.first { it.sku == "TRAY-1" }.category)
        assertEquals("", items.first { it.sku == "TRAY-1" }.unit)
    }

    /** Hub down, no last-good copy: catalog_items() serves the local table — no ids, "" for missing text. */
    @Test fun catalog_localFallbackRows() {
        val f = fake()
        f.on("GET", "/admin/catalog", body = ReportsFixtures.localCatalog)
        val d = dash(f)
        val items = d.catalog.value
        assertEquals(listOf("CS-BLK", "TRAY-1"), items.map { it.id })
        assertTrue(items.none { it.isHub })
        assertEquals("piece", items[0].unit)
        assertTrue(items.all { it.variants.isEmpty() && it.priceMinKes == null })
    }

    /** Whatever the hub hands through: numbers as strings, numeric / boolean attribute values, an id as a string. */
    @Test fun catalog_tolerantNumbers() {
        val i: CatalogItem = NeemaJson.decodeFromString(
            """{"hub_product_id":"501","sku":"S","name":"N","price":"3500.00","price_kes":"3500.00","available_qty":"12.000",
                "category":null,"aliases":null,"variants":[{"variant_id":7,"attributes":{"Size":8,"Lined":true},"price_kes":null}]}""",
        )
        assertEquals(501L, i.hubProductId)
        assertEquals(3500.0, i.price, 0.0)
        assertEquals(12.0, i.availableQty!!, 0.0)
        assertEquals("General", i.category)
        assertEquals(mapOf("Size" to "8", "Lined" to "true"), i.variants.single().attributes)
    }

    // ── /admin/catalog/audit ────────────────────────────────────────────────

    @Test fun audit_realShape() {
        val vm = CatalogViewModel(dash(fake()))
        val a = vm.audit.value!!
        assertEquals(3, a.currencyGaps.size)
        assertEquals(130.0, a.rate, 0.0)
        assertEquals("", a.currencyGaps[0].category)
        assertNull(a.perPiece[1].kes)
        assertNull(a.perPiece[1].category)
    }

    /** name None (a hub row with no English name), factor None, an int rate. */
    @Test fun audit_nullsAndIntRate() {
        val a: PriceAudit = NeemaJson.decodeFromString(
            """{"currency_gaps":[{"name":null,"category":null,"kes":10.0,"usd":10.0,"usd_expected":0.1,"factor":null}],
                "per_piece":[{"name":null,"category":"","kes":null}],"checked":1,"rate":100}""",
        )
        assertEquals("", a.currencyGaps.single().name)
        assertNull(a.currencyGaps.single().factor)
        assertEquals(100.0, a.rate, 0.0)
    }

    /** The audit reads the hub too, but falls back like the list: a 500 is a DB fault. The banner just stays hidden. */
    @Test fun audit_failureStaysHidden_listUnaffected() {
        val f = fake()
        f.on("GET", "/admin/catalog/audit", code = 500, body = """{"detail":"Internal Server Error"}""")
        val d = dash(f)
        val vm = CatalogViewModel(d)
        assertNull(vm.audit.value)
        assertEquals(6, d.catalog.value.size)
        assertTrue(toasts.none { it.type == ToastType.Error })
    }

    // ── Known gaps, pending a core model change (see the round-3 report) ────

    /**
     * core/variants.variant_label() guards `attributes` that are not a dict and
     * values that are None — the hub can send both. The wire model's
     * `Map<String, String>` rejects them, and one such variant empties the
     * whole catalogue (and Analytics' fallback counts).
     */
    @Test fun catalog_oddVariantAttributes_doNotSinkTheCatalogue() {
        NeemaJson.decodeFromString<CatalogVariant>("""{"attributes":{"Size":null}}""")
        NeemaJson.decodeFromString<CatalogVariant>("""{"attributes":[{"name":"Size","value":"M"}]}""")
    }

    /** The agent's cart lines carry `unit_price` (agent/cart.py), which OrderItem drops. */
    @Test fun topProducts_countsAgentCartLines() {
        val orders: List<Order> = NeemaJson.decodeFromString("[${ReportsFixtures.orders.joinToString(",")}]")
        assertEquals(12_500.0, topProducts(orders).first { it.name == "Cassock — Purple, L" }.revenue, 0.0)
    }

    private companion object {
        val NOW_MS = ReportsFixtures.NOW.toEpochMilli()
    }
}
