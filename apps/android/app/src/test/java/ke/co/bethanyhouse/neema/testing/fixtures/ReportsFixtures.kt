package ke.co.bethanyhouse.neema.testing.fixtures

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.requiredHeight
import androidx.compose.foundation.layout.wrapContentHeight
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import java.time.Clock
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.TimeZone

/**
 * Data for Reports / Analytics / Catalog, pinned to a FIXED "now" (Friday
 * 25 Sep 2026, 12:00 in Nairobi) so per-day charts, weekday labels and
 * "3h ago" texts never change from one day's run to the next. Screens take
 * [clock]; call [pinTimeZone] so date formatting uses Nairobi too.
 *
 * Every body below is built from what the API handler actually returns
 * (cited above each one), not from what the client would like to read:
 * Python `isoformat()` datetimes ("…T07:00:00.123456+00:00"), Numeric
 * columns as floats, the exact keys each handler emits, and no keys it
 * doesn't (orders carry NO contact_name — the web's mapOrder falls back to
 * the phone, and so does the app).
 */
object ReportsFixtures {
    val NAIROBI: ZoneId = ZoneId.of("Africa/Nairobi")
    val NOW: Instant = Instant.parse("2026-09-25T09:00:00Z")
    val clock: Clock = Clock.fixed(NOW, NAIROBI)

    private var savedZone: TimeZone? = null

    /** Nairobi for date formatting; pair with [restoreTimeZone] so other suites keep the JVM's own. */
    fun pinTimeZone() {
        if (savedZone == null) savedZone = TimeZone.getDefault()
        TimeZone.setDefault(TimeZone.getTimeZone(NAIROBI))
    }

    fun restoreTimeZone() {
        savedZone?.let(TimeZone::setDefault)
        savedZone = null
    }

    /** Python's `datetime.isoformat()` of a timestamptz read by asyncpg: microseconds and "+00:00". */
    private val PY_ISO = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSSSSxxx")

    /**
     * The API's datetime [minutes] (and a fraction of a second) before [NOW] —
     * rows carry microseconds; landing just before the minute keeps "2h ago" reading 2h.
     */
    fun ago(minutes: Long): String = NOW.minusSeconds(minutes * 60).minusNanos(123_456_000).atOffset(ZoneOffset.UTC).format(PY_ISO)
    private const val H = 60L
    private const val D = 24 * 60L

    private fun q(s: String?) = s?.let { "\"$it\"" } ?: "null"

    /**
     * One inbox row — admin.py `_conversation_rows()`, the shape both the bare
     * list (no `limit`) and each page's `items` carry. Every key it emits.
     */
    fun conv(
        id: String, name: String?, waId: String?, channel: String, mode: String, at: String?,
        agent: String? = null, agentName: String? = null, status: String = "open", created: String = ago(90 * D),
        person: String? = null, externalId: String? = waId, preview: String = "Asante sana",
        country: String? = "KE", tags: List<String> = emptyList(), ordersCount: Int = 0, stage: String? = null,
    ) = """{"id":"$id","wa_id":${q(waId)},"person_id":${q(person)},"external_id":${q(externalId)},
        "intercept_mode":"$mode","assigned_agent_id":${q(agent)},"assigned_agent_name":${q(agentName)},
        "intercept_since":${if (mode == "human") q(at) else "null"},"last_message_at":${q(at)},
        "last_message":"$preview","last_message_preview":"$preview","status":"$status",
        "created_at":"$created","updated_at":"${at ?: created}","name":${q(name)},"avatar_url":null,
        "country_iso":${q(country)},"flag_url":${country?.let { "\"https://flagcdn.com/${it.lowercase()}.svg\"" } ?: "null"},
        "channel":"$channel","unread":0,"orders_count":$ordersCount,"lead_stage":${q(stage)},
        "tags":[${tags.joinToString(",") { "\"$it\"" }}]}"""

    /** Every thread (the un-paged list Reports asks for), newest activity first as the handler sorts. */
    val conversations = listOf(
        conv("r1", "Fr. Peter Kamau", "254712345678", "whatsapp", "human", ago(2 * H), agent = Fixtures.ME_ID,
            agentName = "Moses Mwicigi", person = "p0000001-0000-4000-8000-000000000001", tags = listOf("clergy"), ordersCount = 2, stage = "negotiating"),
        conv("r2", "Rev. Mary Achieng", null, "messenger", "ai", ago(1 * D + 3 * H), externalId = "7012345678901234",
            person = "p0000002-0000-4000-8000-000000000002", country = null),
        conv("r3", null, "255754333222", "whatsapp", "paused", ago(2 * D), country = "TZ"),
        conv("r4", "Sr. Lucy Njeri", null, "instagram", "ai", ago(3 * D), status = "closed", externalId = "17840000000000001", country = null),
        conv("r5", "Deacon James Mwangi", "254733444555", "whatsapp", "human", ago(5 * D), agent = Fixtures.AGENT2_ID,
            agentName = "Grace Wanjiru", person = "p0000005-0000-4000-8000-000000000005"),
        // A Facebook comment thread: no wa_id, the PSID is the handle.
        conv("r6", "Bishop Samuel Kariuki", null, "facebook", "human", ago(12 * D), agent = Fixtures.AGENT2_ID,
            agentName = "Grace Wanjiru", externalId = "6123456789012345", country = null, preview = "How much is the cope?"),
        conv("r7", "St. Mark's Parish Office", "254711000999", "whatsapp", "ai", ago(20 * D)),
        // Outside 30 days, inside 90.
        conv("r8", "Fr. Joseph Otieno", "254722333444", "whatsapp", "ai", ago(45 * D), agent = Fixtures.ME_ID, agentName = "Moses Mwicigi"),
        // No messages yet: last_message_at is null and the preview empty; dates from created_at (the web's mapConversation).
        conv("r9", "New Enquiry", "254799888777", "whatsapp", "ai", null, created = ago(4 * H), preview = ""),
    )

    /**
     * admin.py `list_orders()` returns bare `OrderEvent` ORM rows through
     * FastAPI's jsonable_encoder: every column, Numeric → float, timestamptz →
     * isoformat, and nothing joined (no contact_name / contact_phone).
     * Two item shapes live in `items`:
     *  - n8n's `upsert_order_event` (services/n8n_bridge.py): {name, qty, unit, total, sku?}
     *  - the agent's create_order (agent/tools.py → agent/cart.py lines):
     *    {hub_product_id, name, sku, qty, unit_price, price_usd, prices, in_stock, made_to_order}
     */
    private fun order(
        id: String, waId: String, status: String, subtotal: Double, at: String, items: String,
        channel: String = "whatsapp", hub: Int? = null, payment: String = "unpaid",
    ) = """{"id":"$id","wa_id":"$waId","person_id":null,"session_id":${if (hub == null) "\"sess-$id\"" else "null"},
        "event_type":${if (hub == null) "\"order_snapshot\"" else "\"confirmed\""},"items":$items,"subtotal":$subtotal,
        "currency":"KES","status":"$status","payment_status":"$payment","fulfillment_status":"pending","reply_text":null,
        "channel":"$channel","state":{},"created_at":"$at","updated_at":"$at",
        "hub_order_id":${hub ?: "null"},"hub_order_number":${hub?.let { "\"BH-$it\"" } ?: "null"},
        "hub_push_status":${if (hub != null) "\"pushed\"" else "null"},"hub_payment_url":null,"hub_currency":${if (hub != null) "\"KES\"" else "null"},
        "hub_total":${if (hub != null) subtotal else "null"},"hub_last_error":null,"hub_pushed_at":${if (hub != null) "\"$at\"" else "null"},
        "hub_public_url":null,"hub_public_token":null,"short_ref":null,
        "hub_status":null,"hub_payment_status":null,"hub_fulfillment_status":null,"hub_status_at":null}"""

    private fun n8nLine(name: String, qty: Int, unit: Double) = """{"name":"$name","qty":$qty,"unit":$unit,"total":${unit * qty}}"""
    private fun cartLine(name: String, qty: Int, unit: Double, product: Int, sku: String) =
        """{"hub_product_id":$product,"name":"$name","sku":"$sku","qty":$qty,"unit_price":$unit,"price_usd":null,
            "prices":{"KES":$unit},"in_stock":true,"made_to_order":false}"""

    val orders = listOf(
        order("o1", "254712345678", "confirmed", 8000.0, ago(1 * H),
            "[${n8nLine("Clergy Shirt — Black, 16 inch", 2, 3500.0)},${n8nLine("Roman Collar Tab", 4, 250.0)}]", payment = "paid"),
        // The agent's own order: pushed to the hub, cart lines priced by unit_price (no unit / total).
        order("o2", "254722000111", "pending", 12500.0, ago(1 * D + 2 * H),
            "[${cartLine("Cassock — Purple, L", 1, 12500.0, 502, "CAS-PUR-L")}]", channel = "messenger", hub = 1042),
        order("o3", "254733444555", "delivered", 18000.0, ago(3 * D), "[${n8nLine("Alb — White, M", 3, 6000.0)}]", payment = "paid"),
        order("o4", "254700111222", "cancelled", 9600.0, ago(4 * D), "[${n8nLine("Stole — Green", 2, 4800.0)}]"),
        // An n8n cart snapshot that never became an order: status "open" (shown as pending).
        order("o5", "254711000999", "open", 4800.0, ago(6 * D), "[${n8nLine("Stole — Green", 1, 4800.0)}]"),
        order("o6", "254733444555", "delivered", 3500.0, ago(10 * D), "[${n8nLine("Clergy Shirt", 1, 3500.0)}]", payment = "paid"),
        // Outside 30 days.
        order("o7", "254722333444", "delivered", 25000.0, ago(40 * D), "[${n8nLine("Clergy Shirt", 1, 25000.0)}]", payment = "paid"),
    )

    /**
     * admin.py `overview_stats()`: every count through int(), revenue through
     * float(), channel_breakdown grouped by whatever channels exist (facebook
     * included, and "web" — which the web's CHANNEL_CONFIG doesn't know and skips),
     * only rows with count > 0, known channels first.
     */
    val stats = """{"open_conversations":128,"human_conversations":9,"ai_conversations":119,"active_agents":2,"total_agents":3,
      "total_revenue":1284500.0,"total_orders":284,"pending_orders":21,"delivered_orders":203,"confirmed_orders":48,"cancelled_orders":12,
      "in_stock_items":187,"total_items":214,
      "channel_breakdown":[{"channel":"whatsapp","count":96,"open":80},{"channel":"messenger","count":21,"open":15},
        {"channel":"facebook","count":70,"open":22},{"channel":"instagram","count":11,"open":9},{"channel":"web","count":3,"open":2}]}"""

    /**
     * crm.py `attribution()`: buckets sorted by (revenue, leads) desc, every
     * bucket with a `post_title` key (None unless a comment carried the post's
     * caption), revenue as floats, totals summed over buckets + unattributed.
     */
    val attribution = """{"sources":[
        {"source":"organic","post":null,"leads":77,"orders":30,"revenue":402000.0,"paid_revenue":377500.0,"post_title":null},
        {"source":"facebook","post":"104882331_1203","leads":42,"orders":11,"revenue":186000.0,"paid_revenue":152000.0,"post_title":"Easter vestments sale"},
        {"source":"instagram","post":"17999123456789012","leads":18,"orders":4,"revenue":51000.0,"paid_revenue":51000.0,"post_title":null}],
      "unattributed":{"orders":9,"revenue":64000.0,"paid_revenue":60000.0},
      "totals":{"leads":137,"orders":54,"revenue":703000.0}}"""

    /**
     * `GET /admin/catalog` with catalog_source=hub: hub_client `_map_product()`
     * for every product, then `_fetch_variants()` → `_map_variant()`,
     * `_apply_variant_pricing()` and core/variants `label_variants()` for
     * variable ones. Floats for money, `unit` "", `category` "" when the hub
     * has none, images / prices / measurements carried along (the app ignores
     * them). No `id`: hub rows are keyed by hub_product_id.
     */
    val catalog = """[
      {"hub_product_id":501,"uuid":"9b1c7f10-0000-4000-8000-000000000501","sku":"CS-BLK","slug":"clergy-shirt","name":"Clergy Shirt",
       "category":"Clergy Apparel","price":3500.0,"price_kes":3500.0,"price_usd":27.0,"prices":{"KES":3500.0,"USD":27.0},"unit":"",
       "description":"Tab-collar clergy shirt, poly-cotton, long sleeve.","aliases":["clerical shirt","collar shirt","tab shirt","priest shirt"],
       "in_stock":true,"available_qty":1200,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"variable","is_producible":false,
       "measurements":[],"price_min_kes":3500.0,"price_max_kes":4200.0,"price_min_usd":27.0,"price_max_usd":32.5,
       "variants":[
         {"variant_id":1,"sku":"CS-BLK-15","name":"Black","attributes":{"Colour":"Black","Size":"15 inch"},"price_kes":3500.0,"price_usd":27.0,
          "prices":{"KES":3500.0,"USD":27.0},"is_default":true,"in_stock":true,"label":"Clergy Shirt — Black / 15 inch"},
         {"variant_id":2,"sku":"CS-BLK-16","name":"Black","attributes":{"Colour":"Black","Size":"16 inch"},"price_kes":3500.0,"price_usd":27.0,
          "prices":{"KES":3500.0,"USD":27.0},"is_default":false,"in_stock":true,"label":"Clergy Shirt — Black / 16 inch"},
         {"variant_id":3,"sku":"CS-BLU-16","name":"Blue Clergy Shirt","attributes":{"Colour":"Blue","Size":"16 inch"},"price_kes":4200.0,"price_usd":32.5,
          "prices":{"KES":4200.0,"USD":32.5},"is_default":false,"in_stock":true,"label":"Clergy Shirt — Blue / 16 inch"}]},
      {"hub_product_id":502,"uuid":"9b1c7f10-0000-4000-8000-000000000502","sku":"CAS-PUR","slug":"anglican-cassock",
       "name":"Anglican Double-Breasted Cassock with Cincture and Matching Buttons","category":"Clergy Vestments",
       "price":12500.0,"price_kes":12500.0,"price_usd":96.0,"prices":{"KES":12500.0,"USD":96.0},"unit":"",
       "description":"Anglican double-breasted cassock, wool blend, made to measure in any liturgical colour with a matching cincture.",
       "aliases":[],"in_stock":true,"available_qty":6,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"simple",
       "is_producible":true,"measurements":[{"name":"Chest","unit":"cm","required":true}],"variants":[]},
      {"hub_product_id":503,"uuid":null,"sku":"OIL-50","slug":"anointing-oil-50ml","name":"Anointing Oil 50ml","category":"Anointing Oil",
       "price":650.0,"price_kes":650.0,"price_usd":null,"prices":{"KES":650.0},"unit":"","description":"Frankincense-scented olive oil.",
       "aliases":["holy oil"],"in_stock":false,"available_qty":0,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"simple",
       "is_producible":false,"measurements":[],"variants":[]},
      {"hub_product_id":504,"uuid":null,"sku":"WAF-500","slug":"communion-wafers-500","name":"Communion Wafers (500)","category":"Communion Wafers",
       "price":1800.0,"price_kes":1800.0,"price_usd":13.85,"prices":{"KES":1800.0,"USD":13.85},"unit":"","description":"White unleavened wafers, 35mm.",
       "aliases":["hosts"],"in_stock":true,"available_qty":null,
       "images":[{"url":"https://hub.test/img/broken.jpg","thumb":"https://hub.test/img/broken_thumb.webp","alt":"","primary":true,"sort":0}],
       "image_url":"https://hub.test/img/broken.jpg","thumbnail_url":"https://hub.test/img/broken_thumb.webp","product_type":"simple",
       "is_producible":false,"measurements":[],"variants":[]},
      {"hub_product_id":505,"uuid":null,"sku":"CUP-PF","slug":"prefilled-cups","name":"Prefilled Communion Cups","category":"Prefilled Cups",
       "price":45.0,"price_kes":45.0,"price_usd":null,"prices":{"KES":45.0},"unit":"","description":"",
       "aliases":[],"in_stock":true,"available_qty":35000,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"simple",
       "is_producible":false,"measurements":[],"variants":[]},
      {"hub_product_id":506,"uuid":null,"sku":"TRAY-1","slug":"communion-tray","name":"Communion Tray","category":"",
       "price":36000.0,"price_kes":36000.0,"price_usd":600.0,"prices":{"KES":36000.0,"USD":600.0},"unit":"","description":"Brass tray set.",
       "aliases":[],"in_stock":true,"available_qty":null,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"simple",
       "is_producible":false,"measurements":[],"variants":[]}
    ]"""

    /**
     * `GET /admin/catalog` when the hub is unreachable and no last-good copy
     * exists: n8n_bridge `catalog_items()` reads Neema's local table — IN-STOCK
     * rows only, no id, no hub_product_id, and `category` / `unit` /
     * `description` coerced to "" (str(x or "")).
     */
    val localCatalog = """[
      {"sku":"CS-BLK","name":"Clergy Shirt","category":"Clergy Apparel","price":3500.0,"unit":"piece",
       "description":"Tab-collar clergy shirt.","aliases":["clerical shirt"],"in_stock":true},
      {"sku":"TRAY-1","name":"Communion Tray","category":"","price":36000.0,"unit":"",
       "description":"","aliases":[],"in_stock":true}
    ]"""

    /**
     * admin.py `catalog_price_audit()` → services/price_audit `audit()`:
     * gaps sorted by |usd − expected| desc (variants included, named
     * "<product> — <variant name>"), `factor` null only when expected is 0,
     * per-piece `kes` null when the price isn't positive, `rate` the
     * configured float.
     */
    val audit = """{"currency_gaps":[
        {"name":"Communion Tray","category":"","kes":36000.0,"usd":600.0,"usd_expected":276.92,"factor":2.17},
        {"name":"Anglican Double-Breasted Cassock with Cincture and Matching Buttons","category":"Clergy Vestments","kes":12500.0,"usd":90.0,"usd_expected":96.15,"factor":0.94},
        {"name":"Communion Cup","category":"Communion Cups","kes":10.0,"usd":10.0,"usd_expected":0.08,"factor":129.87}],
      "per_piece":[{"name":"Prefilled Communion Cups","category":"Prefilled Cups","kes":45.0},{"name":"Communion Hosts","category":null,"kes":null}],
      "checked":6,"rate":130.0}"""

    /** A human-tab page as admin.py `list_conversations()` builds it: ALL threads of each person on the page. */
    private fun humanPage(rows: List<String>) = """{"items":[${rows.joinToString(",")}],"next_cursor":null}"""

    /**
     * Fr. Peter's second, AI-held (Messenger) thread shares r1's person: the paged endpoint
     * returns every thread of each person on the page, so a human-tab page
     * carries it too and the feed must filter it out.
     */
    private val siblingOfR1 = conv("r1b", "Fr. Peter Kamau", null, "messenger", "ai", ago(30), externalId = "7098765432109876",
        person = "p0000001-0000-4000-8000-000000000001", country = null)

    fun install(f: FakeNeema) {
        // admin.py list_conversations(): no `limit` → the legacy bare array (Reports);
        // with `limit` → {items, next_cursor}.
        f.on("GET", "/admin/conversations") { r, _ ->
            val limit = r.url.queryParameter("limit")
            when {
                limit == null -> 200 to "[${conversations.joinToString(",")}]"
                r.url.queryParameter("tab") == "human" ->
                    200 to humanPage(conversations.filter { it.contains("\"intercept_mode\":\"human\"") } + siblingOfR1)
                else -> 200 to """{"items":[${conversations.joinToString(",")}],"next_cursor":null}"""
            }
        }
        f.on("GET", "/admin/orders", body = "[${orders.joinToString(",")}]")
        f.on("GET", "/admin/catalog", body = catalog)
        f.on("GET", "/admin/catalog/audit", body = audit)
        f.on("GET", "/admin/stats", body = stats)
        f.on("GET", "/admin/attribution", body = attribution)
    }

    /**
     * The stress case for layout: a busy shop. Six- and seven-digit KES
     * amounts, long Swahili / emoji names, a product title that runs three
     * lines, and 40+ orders — the same handler shapes as [install].
     */
    fun installBig(f: FakeNeema) {
        install(f)
        val longName = "Wanjiku Nyambura-Kariuki wa Parokia ya Mtakatifu Yohana 🙏"
        val bigOrders = orders + listOf(
            order("b1", "254700999888", "delivered", 845_000.0, ago(2 * H),
                "[${n8nLine("Kasula ya Kiaskofu — Dhahabu na Nyeupe, Imeshonwa kwa Mkono ✝️", 5, 169_000.0)}]", payment = "paid"),
            order("b2", "254700999887", "confirmed", 1_250_000.0, ago(1 * D + 5 * H),
                "[${n8nLine("Kengele ya Kanisa ya Shaba — Kubwa Sana", 1, 1_250_000.0)}]", payment = "paid"),
            order("b3", "254700999886", "pending", 386_500.0, ago(2 * D + 1 * H),
                "[${n8nLine("Viti vya Madhabahu (Seti ya 12)", 1, 386_500.0)}]"),
        ) + (1..40).map { i ->
            order("m$i", "2547001${"%05d".format(i)}", listOf("delivered", "confirmed", "pending", "cancelled")[i % 4],
                (i * 7_350).toDouble(), ago((i % 13) * D + i * 17L), "[${n8nLine("Clergy Shirt", 1, (i * 7_350).toDouble())}]")
        }
        f.on("GET", "/admin/orders", body = "[${bigOrders.joinToString(",")}]")
        f.on("GET", "/admin/conversations") { r, _ ->
            val rows = listOf(conv("b1", longName, "254700999888", "whatsapp", "human", ago(2 * H), agent = Fixtures.ME_ID,
                agentName = "Moses Mwicigi")) + conversations
            if (r.url.queryParameter("limit") == null) 200 to "[${rows.joinToString(",")}]"
            else 200 to """{"items":[${rows.joinToString(",")}],"next_cursor":null}"""
        }
        f.on("GET", "/admin/stats", body = """{"open_conversations":128450,"human_conversations":9312,"ai_conversations":119138,"active_agents":12,"total_agents":148,
          "total_revenue":98765432.0,"total_orders":284310,"pending_orders":21044,"delivered_orders":203119,"confirmed_orders":48007,"cancelled_orders":12140,
          "in_stock_items":187,"total_items":214,
          "channel_breakdown":[{"channel":"whatsapp","count":96000,"open":80000},{"channel":"messenger","count":21000,"open":15000},
            {"channel":"facebook","count":7000,"open":2200},{"channel":"instagram","count":1100,"open":900}]}""")
        f.on("GET", "/admin/catalog", body = catalog.trimEnd().removeSuffix("]") + """,
          {"hub_product_id":599,"uuid":null,"sku":"KAS-DHB-XL-HANDMADE-2026","slug":"kasula","name":"Kasula ya Kiaskofu — Dhahabu na Nyeupe, Imeshonwa kwa Mkono na Mafundi wa Nyeri ✝️🙏",
           "category":"Clergy Vestments","price":169000.0,"price_kes":169000.0,"price_usd":1300.0,"prices":{"KES":169000.0,"USD":1300.0},"unit":"",
           "description":"Vazi la sherehe kuu, lenye nakshi za dhahabu na bitana ya hariri.","aliases":["chasuble","kasula","vazi la askofu"],
           "in_stock":true,"available_qty":3,"images":[],"image_url":null,"thumbnail_url":null,"product_type":"variable","is_producible":true,
           "measurements":[],"price_min_kes":169000.0,"price_max_kes":245000.0,"price_min_usd":1300.0,"price_max_usd":1884.6,"variants":[]}
        ]""")
    }

    /** A backend with nothing in it (a fresh install) — the same handlers over empty tables. */
    fun installEmpty(f: FakeNeema) {
        f.on("GET", "/admin/conversations") { r, _ ->
            if (r.url.queryParameter("limit") == null) 200 to "[]" else 200 to """{"items":[],"next_cursor":null}"""
        }
        f.on("GET", "/admin/orders", body = "[]")
        f.on("GET", "/admin/catalog", body = "[]")
        f.on("GET", "/admin/catalog/audit", body = """{"currency_gaps":[],"per_piece":[],"checked":0,"rate":130.0}""")
        f.on("GET", "/admin/attribution", body = """{"sources":[],"unattributed":{"orders":0,"revenue":0.0,"paid_revenue":0.0},"totals":{"leads":0,"orders":0,"revenue":0}}""")
        f.on("GET", "/admin/stats", body = """{"open_conversations":0,"human_conversations":0,"ai_conversations":0,"active_agents":0,"total_agents":1,
          "total_revenue":0.0,"total_orders":0,"pending_orders":0,"delivered_orders":0,"confirmed_orders":0,"cancelled_orders":0,
          "in_stock_items":0,"total_items":0,"channel_breakdown":[]}""")
    }
}

/**
 * Paparazzi scales any snapshot down to 1000px on its long side, so a tall
 * scrolling page shrinks to an unreadable strip. Instead: lay [content] out
 * [totalHeight] tall and show the window that starts [page] screens down, at
 * full resolution.
 */
@Composable
fun PageSlice(page: Int, totalHeight: Dp = 4000.dp, step: Dp = 860.dp, content: @Composable () -> Unit) {
    if (page == 0) { content(); return }
    Box(Modifier.fillMaxSize().clipToBounds()) {
        Box(
            Modifier.wrapContentHeight(Alignment.Top, unbounded = true)
                .requiredHeight(totalHeight)
                .offset(y = -step * page),
        ) { content() }
    }
}
