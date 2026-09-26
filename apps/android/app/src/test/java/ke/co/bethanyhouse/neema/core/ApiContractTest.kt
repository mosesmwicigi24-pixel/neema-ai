package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.util.AppClock

import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.api.UploadFile
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.InboxSummary
import ke.co.bethanyhouse.neema.core.model.OkResponse
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.net.TokenProvider
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.builtins.ListSerializer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.File

/**
 * Round 3: the core endpoints against what apps/api/app actually sends. Each
 * test names the handler it mirrors; the fixtures it decodes are built from
 * the same handlers (see [Fixtures]).
 */
class ApiContractTest {
    private class Tokens(var current: String?) : TokenProvider {
        var refreshes = 0
        override suspend fun validAccessToken() = current
        override suspend fun forceRefresh(): String? { refreshes++; return null }
        override fun onRejected(token: String?) {}
    }

    private val fake = FakeNeema.withFixtures()
    private val tokens = Tokens("tok-1")
    private val http = NeemaHttp("https://neema.test", tokens, fake, Dispatchers.Unconfined)
    private val api = NeemaApi(http)

    private fun <T> expectApi(block: suspend () -> T): ApiException = runBlocking {
        try { block(); fail("expected ApiException"); throw IllegalStateException() } catch (e: ApiException) { e }
    }

    // ── GET /admin/me — admin.py get_me (the ORM Agent row) ─────────────────

    @Test
    fun meDecodesTheOrmRowAndIgnoresThePasswordHash() = runBlocking {
        val me = api.profile.me()
        val c = fake.calls.single()
        assertEquals("GET", c.method); assertEquals("/admin/me", c.path); assertNull(c.query)
        assertEquals("Bearer tok-1", c.headers["Authorization"])

        assertEquals(Fixtures.ME_ID, me.id)
        assertEquals("Moses Mwicigi", me.name)
        assertEquals("admin", me.role)
        assertTrue(me.isSuperuser && me.isAvailable)
        assertEquals(4, me.activeConvs)
        // No custom-role columns on /me: permissions fall back to the role.
        assertNull(me.customRoleId); assertNull(me.rolePermissions)
        assertEquals(Perms.ALL, Perms.of(me))
        // "+00:00" with microseconds parses to the same instant as "Z".
        assertTrue(Fmt.millis(me.lastSeenAt)!! > AppClock.now() - 5 * 60_000)
        // What the app caches never carries the hash.
        assertFalse(NeemaJson.encodeToString(Agent.serializer(), me).contains("password"))
    }

    @Test
    fun meToleratesMissingOptionalColumnsAndNulls() = runBlocking {
        fake.on("GET", "/admin/me", body = """{"id":"a9","name":"Grace","email":"g@b.co","role":"agent","is_available":null,
            "is_superuser":false,"active_convs":null,"created_at":"2026-01-04T08:00:00"}""")
        val me = api.profile.me()
        assertFalse(me.isAvailable)
        assertEquals(0, me.activeConvs)
        assertNull(me.lastSeenAt)
        // A naive timestamp (datetime.utcnow before a refresh) is read as UTC.
        assertEquals(Fmt.millis("2026-01-04T08:00:00Z"), Fmt.millis(me.createdAt))
    }

    @Test
    fun meErrorsCarryTheServersDetail() {
        fake.on("GET", "/admin/me", code = 404, body = """{"detail":"Agent not found"}""")
        val e = expectApi { api.profile.me() }
        assertEquals(404, e.status)
        assertEquals("Agent not found", e.detail)
    }

    // ── GET /admin/agents — admin.py list_agents (raw SQL + custom_roles) ────

    @Test
    fun agentsDecodeTheJoinedRows() = runBlocking {
        val list = api.agents.list()
        assertEquals("/admin/agents", fake.calls.single().path)
        assertEquals(listOf(Fixtures.ME_ID, Fixtures.AGENT2_ID, Fixtures.AGENT3_ID), list.map { it.id })
        val grace = list[1]
        assertEquals("sales", grace.customRoleId)
        assertEquals("Sales", grace.roleName)
        assertEquals("#3b82f6", grace.roleColor)
        assertTrue(Perms.EDIT_CRM in Perms.of(grace))
        assertFalse(Perms.MANAGE_AGENTS in Perms.of(grace))
        val brian = list[2]
        assertEquals(Perms.effective("readonly", false, null), Perms.of(brian))
    }

    @Test
    fun perAgentOverridesWinOverTheRolesPermissions() = runBlocking {
        fake.on("GET", "/admin/agents", body = "[" + Fixtures.agentRow(
            "a7", "Wanjiku", "w@b.co", "agent", true, false, 2, 100, null, customRole = "sales",
            rolePermissions = """["view_orders","manage_orders"]""", customPermissions = """["view_orders"]""",
        ) + "]")
        val a = api.agents.list().single()
        assertEquals(listOf("view_orders"), a.permissions)
        assertNull(a.lastSeenAt)
    }

    // ── GET /admin/orders — admin.py list_orders (ORM order_events rows) ─────

    @Test
    fun ordersSendTheHandlersQueryNames() = runBlocking {
        api.orders.list(status = "pending", waId = "254712345678")
        val c = fake.callsTo("GET", "/admin/orders").single()
        assertEquals(mapOf("status" to "pending", "wa_id" to "254712345678"), c.params)
        api.orders.list()
        assertNull("no filters, no query string", fake.callsTo("GET", "/admin/orders").last().query)
    }

    @Test
    fun ordersDecodeCartLinesLegacyLinesAndHubState() = runBlocking {
        val orders = api.orders.list()
        assertEquals(listOf("o1", "o2", "o3", "o4"), orders.map { it.id })

        val o1 = orders[0]
        // Neema's own orders store unit_price and no total: both are derived.
        assertEquals(listOf(3500.0 to 7000.0, 250.0 to 1000.0), o1.items.map { it.unit to it.total })
        assertEquals(listOf(2.0, 4.0), o1.items.map { it.qty })
        assertEquals("CS-BLK-16", o1.items[0].sku)
        assertEquals(8000.0, o1.subtotal, 0.0)
        assertEquals(1042L, o1.hubOrderId)
        assertEquals("processing", o1.hubStatus)
        assertEquals("https://hub.bethanyhouse.co.ke/order/tok1042", o1.hubPublicUrl)
        // There is no contact_name column: the customer is shown by wa_id.
        assertNull(o1.contactName)
        assertEquals("254712345678", o1.customerName)

        // An "open" cart snapshot reads as pending, like mapOrder().
        assertEquals("open", orders[1].rawStatus); assertEquals("pending", orders[1].status)
        assertEquals("Variant out of stock in hub", orders[1].hubLastError)

        // The hub bridge's older {unit,total} lines still read as they are.
        assertEquals(4800.0 to 4800.0, orders[2].items.single().let { it.unit to it.total })
    }

    @Test
    fun ordersTolerateDecimalStringsNullsAndMissingColumns() {
        val rows = """[
          {"id":"x1","wa_id":"254700000001","items":[{"name":"Alb","quantity":"2","price":"6000.00"},"garbage",null],
           "subtotal":"12000.00","currency":"KES","status":"confirmed","hub_total":"12000.00","hub_order_id":"77",
           "created_at":"2026-09-01T10:00:00.123456+00:00"},
          {"id":"x2","wa_id":"254700000002","items":null,"subtotal":null,"status":"open","channel":null,"state":null,
           "created_at":"2026-09-01T10:00:00"},
          {"id":"x3","wa_id":"254700000003"}
        ]"""
        val list = NeemaJson.decodeFromString(ListSerializer(Order.serializer()), rows)
        val alb = list[0].items.single()
        assertEquals(2.0, alb.qty, 0.0); assertEquals(6000.0, alb.unit, 0.0); assertEquals(12000.0, alb.total, 0.0)
        assertEquals(12000.0, list[0].subtotal, 0.0)
        assertEquals(77L, list[0].hubOrderId)
        assertTrue(list[1].items.isEmpty())
        assertEquals(0.0, list[1].subtotal, 0.0)
        assertEquals("whatsapp", list[1].channel)
        assertEquals("pending", list[2].status)
        assertEquals("KES", list[2].currency)
        assertEquals(Fmt.millis("2026-09-01T10:00:00Z"), Fmt.millis(list[1].createdAt))
    }

    @Test
    fun orderItemsSurviveTheSnapshotCacheRoundTrip() = runBlocking {
        val orders = api.orders.list()
        val ser = ListSerializer(Order.serializer())
        val again = NeemaJson.decodeFromString(ser, NeemaJson.encodeToString(ser, orders))
        assertEquals(orders, again)
    }

    @Test
    fun orderPatchSendsOnlyAllowedKeysAndDecodesTheRow() = runBlocking {
        fake.on("PATCH", "/admin/orders/o1", body = Fixtures.orderRow("o1", "254712345678", "[]", "8000.0", "delivered", "whatsapp", 5))
        val o = api.orders.updateStatus("o1", "delivered", fulfillmentStatus = "fulfilled")
        assertEquals("""{"status":"delivered","fulfillment_status":"fulfilled"}""", fake.callsTo("PATCH", "/admin/orders/o1").single().body)
        assertEquals("delivered", o.status)
    }

    // ── GET /admin/catalog — admin.py list_catalog → n8n_bridge.catalog_items ─

    @Test
    fun catalogSendsCategoryAndSearch() = runBlocking {
        api.catalog.list(category = "Vestments", search = "stole & alb")
        val c = fake.callsTo("GET", "/admin/catalog").single()
        assertEquals(mapOf("category" to "Vestments", "search" to "stole & alb"), c.params)
    }

    @Test
    fun hubProductsDecodeWithVariantsAndNoLocalId() = runBlocking {
        val items = api.catalog.list()
        assertEquals(4, items.size)
        val shirt = items[0]
        assertNull(shirt.rawId)
        assertEquals("501", shirt.id)
        assertTrue(shirt.isHub)
        assertEquals("", shirt.unit)
        assertEquals(3, shirt.variants.size)
        assertEquals(mapOf("Colour" to "Black", "Size" to "15 inch"), shirt.variants[0].attributes)
        assertEquals("Clergy Shirt — Black, 15 inch", shirt.variants[0].label)
        assertEquals(4200.0, shirt.priceMaxKes!!, 0.0)
        assertEquals("https://hub.test/p/CS-BLK-t.jpg", shirt.thumbnailUrl)
        assertNull("available_qty may be null", items[3].availableQty)
        assertFalse(items[2].inStock)
    }

    @Test
    fun theLocalFallbackCatalogDecodesToo() {
        val items = NeemaJson.decodeFromString(ListSerializer(CatalogItem.serializer()), Fixtures.localCatalog)
        assertEquals("RC-TAB", items[0].id)
        assertFalse(items[0].isHub)
        // The fallback maps a missing category to "" (not null), exactly as the web receives it.
        assertEquals("", items[1].category)
        assertEquals(1200.0, items[1].price, 0.0)
    }

    @Test
    fun variantAttributesTolerateEmptyListsNumbersAndNulls() {
        val json = """[{"hub_product_id":9,"sku":"T","name":"Thurible","price":"9000.00","available_qty":"3",
          "variants":[{"variant_id":1,"attributes":[]},{"variant_id":"2","attributes":{"Size":10,"Colour":null,"Chain":true}}]}]"""
        val t = NeemaJson.decodeFromString(ListSerializer(CatalogItem.serializer()), json).single()
        assertEquals(9000.0, t.price, 0.0)
        assertEquals(3.0, t.availableQty!!, 0.0)
        assertEquals(emptyMap<String, String>(), t.variants[0].attributes)
        assertEquals(mapOf("Size" to "10", "Chain" to "true"), t.variants[1].attributes)
        assertEquals(2L, t.variants[1].variantId)
    }

    // ── GET /admin/conversations/summary — admin.py conversations_summary ────

    @Test
    fun summaryDecodesAndMissingChannelsReadAsZero() = runBlocking {
        val s = api.conversations.summary()
        assertEquals("/admin/conversations/summary", fake.calls.single().path)
        assertEquals(3, s.unread); assertEquals(2, s.human); assertEquals(1, s.yours)
        assertEquals(4, s.unreadMessages["all"])
        assertNull("a channel with no unread messages is absent", s.unreadMessages["instagram"])
        assertEquals(listOf("bulk", "clergy", "vip"), s.tags)
        // An empty inbox: {"all": 0} and no tags.
        val empty = NeemaJson.decodeFromString(InboxSummary.serializer(), """{"unread":0,"human":0,"yours":0,"unread_messages":{"all":0},"tags":[]}""")
        assertEquals(0, empty.unreadMessages["all"])
    }

    @Test
    fun theBaseInboxHasAWebChatVisitorOnTheDefaultChannel() = runBlocking {
        val page = api.conversations.page(ke.co.bethanyhouse.neema.core.api.InboxQuery(), limit = 50)
        val web = page.items.single { it.waId!!.startsWith("web_") }
        assertEquals("whatsapp", web.channel)
        assertNull(web.name)
        assertEquals("Website visitor", Fmt.formatPhone(web.waId))
    }

    // ── Errors ──────────────────────────────────────────────────────────────

    @Test
    fun aPydanticValidationListReadsAsItsMessages() {
        fake.on("POST", "/admin/agents", code = 422, body = """{"detail":[{"type":"missing","loc":["body","email"],"msg":"Field required","input":null},
            {"type":"string_too_short","loc":["body","password"],"msg":"String should have at least 8 characters"}]}""")
        val e = expectApi { api.agents.create("Grace", "", "pw") }
        assertEquals(422, e.status)
        assertEquals("Field required; String should have at least 8 characters", e.detail)
    }

    @Test
    fun plainTextAndHtmlErrorsAreShownTrimmed() {
        fake.on("GET", "/admin/agents", code = 500, body = "Internal Server Error")
        assertEquals("Internal Server Error", expectApi { api.agents.list() }.detail)
        fake.on("GET", "/admin/agents", code = 502, body = "  <html><body>502 Bad Gateway</body></html>\n")
        assertEquals("<html><body>502 Bad Gateway</body></html>", expectApi { api.agents.list() }.detail)
    }

    @Test
    fun aNoTokenForbiddenIsTheSameDeadSession() = runBlocking {
        // FastAPI 0.115 HTTPBearer: no Authorization header → 403 "Not authenticated".
        tokens.current = null
        fake.on("GET", "/admin/me", code = 403, body = """{"detail":"Not authenticated"}""")
        var expired = false
        val watch = kotlinx.coroutines.CoroutineScope(Dispatchers.Unconfined).launch { http.sessionExpired.collect { expired = true } }
        val e = runCatching { api.profile.me() }.exceptionOrNull() as ApiException
        watch.cancel()
        assertEquals(401, e.status)
        assertEquals("one rescue attempt, as for a 401", 1, tokens.refreshes)
        assertTrue("the re-auth prompt opens", expired)
    }

    @Test
    fun aForbiddenWithATokenIsAPlainError() {
        fake.on("DELETE", "/admin/roles/admin", code = 403, body = """{"detail":"Protected role"}""")
        val e = expectApi { api.roles.delete("admin") }
        assertEquals(403, e.status)
        assertEquals("Protected role", e.detail)
        assertEquals(0, tokens.refreshes)
    }

    @Test
    fun anEmptySuccessIsASuccess() = runBlocking {
        fake.on("DELETE", "/admin/agents/a3", code = 204, body = "")
        assertEquals(OkResponse(), api.agents.delete("a3"))
        fake.on("GET", "/admin/agents", body = "")
        assertEquals(emptyList<Agent>(), api.agents.list())
    }

    // ── Uploads ─────────────────────────────────────────────────────────────

    @Test
    fun aFileBackedUploadIsStreamedAndSentWhole() = runBlocking {
        val f = File.createTempFile("call", ".m4a").apply {
            deleteOnExit(); writeBytes(ByteArray(256 * 1024) { (it % 251).toByte() })
        }
        fake.on("POST", "/admin/calls/wacid.1/recording", body = """{"ok":true,"will_transcribe":true}""")
        val up = UploadFile.of(f, "wacid.1.m4a", "audio/mp4")
        assertNull("nothing read into memory", up.bytes)
        assertEquals(f.length(), up.length)
        assertEquals(f.length(), up.requestBody().contentLength())

        val res = api.calls.uploadRecording("wacid.1", up)

        assertEquals(true, res.willTranscribe)
        val body = fake.callsTo("POST", "/admin/calls/wacid.1/recording").single().body!!
        assertTrue(body.contains("name=\"file\"; filename=\"wacid.1.m4a\""))
        assertTrue(body.contains("Content-Type: audio/mp4"))
        // Every byte arrived, and a second write (the retry after a refresh) re-reads the file.
        val a = okio.Buffer().also { up.requestBody().writeTo(it) }.readByteArray()
        val b = okio.Buffer().also { up.requestBody().writeTo(it) }.readByteArray()
        assertTrue(a.contentEquals(f.readBytes()) && b.contentEquals(a))
    }

    @Test
    fun aByteArrayUploadStillWorks() = runBlocking {
        fake.on("POST", "/admin/conversations/c1/upload-media", body = """{"id":"m9","type":"message","direction":"outbound","sender":"human_agent","text":"","created_at":"2026-09-25T10:00:00+00:00","media_type":"image","media_url":"https://neema.test/m.jpg"}""")
        val m = api.conversations.uploadMedia("c1", UploadFile("jpeg!".toByteArray(), "p.jpg", "image/jpeg"), caption = "Front")
        assertEquals("m9", m.id)
        val body = fake.calls.last().body!!
        assertTrue(body.contains("jpeg!") && body.contains("name=\"caption\"") && body.contains("Front"))
    }
}
