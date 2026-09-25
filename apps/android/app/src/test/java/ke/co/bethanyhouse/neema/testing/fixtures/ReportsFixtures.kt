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
import java.util.TimeZone

/**
 * Data for Reports / Analytics / Catalog, pinned to a FIXED "now" (Friday
 * 25 Sep 2026, 12:00 in Nairobi) so per-day charts, weekday labels and
 * "3h ago" texts never change from one day's run to the next. Screens take
 * [clock]; call [pinTimeZone] so date formatting uses Nairobi too.
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

    /** ISO time [minutes] before [NOW]. */
    fun ago(minutes: Long): String = NOW.minusSeconds(minutes * 60).toString()
    private const val H = 60L
    private const val D = 24 * 60L

    fun conv(
        id: String, name: String?, waId: String, channel: String, mode: String, at: String?,
        agent: String? = null, status: String = "open", created: String = ago(90 * D),
    ) = """{"id":"$id","wa_id":"$waId","intercept_mode":"$mode","assigned_agent_id":${agent?.let { "\"$it\"" }},
        "last_message_at":${at?.let { "\"$it\"" }},"status":"$status","created_at":"$created","name":${name?.let { "\"$it\"" }},
        "channel":"$channel","unread":0,"tags":[]}"""

    /** Every thread (the un-paged list Reports asks for). */
    val conversations = listOf(
        conv("r1", "Fr. Peter Kamau", "254712345678", "whatsapp", "human", ago(2 * H), agent = Fixtures.ME_ID),
        conv("r2", "Rev. Mary Achieng", "254722000111", "messenger", "ai", ago(1 * D + 3 * H)),
        conv("r3", null, "255754333222", "whatsapp", "paused", ago(2 * D)),
        conv("r4", "Sr. Lucy Njeri", "17840000000000001", "instagram", "ai", ago(3 * D), status = "closed"),
        conv("r5", "Deacon James Mwangi", "254733444555", "whatsapp", "human", ago(5 * D), agent = Fixtures.AGENT2_ID),
        conv("r6", "Bishop Samuel Kariuki", "254700111222", "facebook", "human", ago(12 * D), agent = Fixtures.AGENT2_ID),
        conv("r7", "St. Mark's Parish Office", "254711000999", "whatsapp", "ai", ago(20 * D)),
        // Outside 30 days, inside 90.
        conv("r8", "Fr. Joseph Otieno", "254722333444", "whatsapp", "ai", ago(45 * D), agent = Fixtures.ME_ID),
        // No messages yet: dates from created_at (the web's mapConversation).
        conv("r9", "New Enquiry", "254799888777", "whatsapp", "ai", null, created = ago(4 * H)),
    )

    fun order(
        id: String, waId: String, name: String?, status: String, subtotal: Int, at: String,
        items: String = """[{"name":"Clergy Shirt","qty":1,"unit":$subtotal,"total":$subtotal}]""",
    ) = """{"id":"$id","wa_id":"$waId","items":$items,"subtotal":$subtotal,"currency":"KES","status":"$status",
        "payment_status":"pending","channel":"whatsapp","created_at":"$at","contact_name":${name?.let { "\"$it\"" }}}"""

    val orders = listOf(
        order("o1", "254712345678", "Fr. Peter Kamau", "confirmed", 8000, ago(1 * H),
            """[{"name":"Clergy Shirt — Black, 16 inch","qty":2,"unit":3500,"total":7000},{"name":"Roman Collar Tab","qty":4,"unit":250,"total":1000}]"""),
        order("o2", "254722000111", "Rev. Mary Achieng", "open", 12500, ago(1 * D + 2 * H),
            """[{"name":"Cassock — Purple, L","qty":1,"unit":12500,"total":12500}]"""),
        order("o3", "254733444555", "Deacon James Mwangi", "delivered", 18000, ago(3 * D),
            """[{"name":"Alb — White, M","qty":3,"unit":6000,"total":18000}]"""),
        order("o4", "254700111222", "Kariuki, Samuel", "cancelled", 9600, ago(4 * D),
            """[{"name":"Stole — Green","qty":2,"unit":4800,"total":9600}]"""),
        order("o5", "254711000999", null, "pending", 4800, ago(6 * D),
            """[{"name":"Stole — Green","qty":1,"unit":4800,"total":4800}]"""),
        order("o6", "254733444555", "Deacon James Mwangi", "delivered", 3500, ago(10 * D)),
        // Outside 30 days.
        order("o7", "254722333444", "Fr. Joseph Otieno", "delivered", 25000, ago(40 * D)),
    )

    val stats = Fixtures.stats

    /** An orders-heavy catalogue with images, fallbacks, variants and long names. */
    val catalog = """[
      {"hub_product_id":501,"sku":"CS-BLK","name":"Clergy Shirt","aliases":["clerical shirt","collar shirt","tab shirt","priest shirt"],"price":3500,
       "category":"Clergy Apparel","description":"Tab-collar clergy shirt, poly-cotton, long sleeve.","in_stock":true,"available_qty":1200,
       "price_kes":3500,"price_usd":27,"price_min_kes":3500,"price_max_kes":4200,"product_type":"variable",
       "variants":[{"variant_id":1,"sku":"CS-BLK-15","label":"Clergy Shirt — Black, 15 inch","attributes":{"Colour":"Black","Size":"15 inch"},"price_kes":3500,"price_usd":27},
                   {"variant_id":2,"sku":"CS-BLK-16","label":"Clergy Shirt — Black, 16 inch","attributes":{"Colour":"Black","Size":"16 inch"},"price_kes":3500,"price_usd":27},
                   {"variant_id":3,"sku":"CS-BLU-16","label":"Clergy Shirt — Blue, 16 inch","attributes":{"Colour":"Blue","Size":"16 inch"},"price_kes":4200,"price_usd":32.5}]},
      {"hub_product_id":502,"sku":"CAS-PUR","name":"Anglican Double-Breasted Cassock with Cincture and Matching Buttons","aliases":[],"price":12500,
       "category":"Clergy Vestments","description":"Anglican double-breasted cassock, wool blend, made to measure in any liturgical colour with a matching cincture.",
       "in_stock":true,"available_qty":6,"price_kes":12500,"price_usd":96,"variants":[]},
      {"hub_product_id":503,"sku":"OIL-50","name":"Anointing Oil 50ml","aliases":["holy oil"],"price":650,"category":"Anointing Oil",
       "description":"Frankincense-scented olive oil.","in_stock":false,"available_qty":0,"variants":[]},
      {"hub_product_id":504,"sku":"WAF-500","name":"Communion Wafers (500)","aliases":["hosts"],"price":1800,"category":"Communion Wafers",
       "description":"White unleavened wafers, 35mm.","in_stock":true,"image_url":"https://hub.test/img/broken.jpg","variants":[]},
      {"hub_product_id":505,"sku":"CUP-PF","name":"Prefilled Communion Cups","aliases":[],"price":45,"category":"Prefilled Cups",
       "in_stock":true,"available_qty":35000,"variants":[]},
      {"sku":"TRAY-1","name":"Communion Tray","aliases":[],"price":36000,"unit":"set","category":"Communion Trays",
       "description":"Brass tray set.","in_stock":true}
    ]"""

    val audit = """{"currency_gaps":[
        {"name":"Communion Tray","category":"Communion Trays","kes":36000,"usd":600,"usd_expected":276.92,"factor":2.17},
        {"name":"Communion Cup","category":"Communion Cups","kes":10,"usd":10,"usd_expected":0.08,"factor":129.9},
        {"name":"Cassock","category":"Clergy Vestments","kes":12500,"usd":90,"usd_expected":96.15,"factor":0.94}],
      "per_piece":[{"name":"Prefilled Communion Cups","category":"Prefilled Cups","kes":45},{"name":"Candle","category":null,"kes":null}],
      "checked":214,"rate":130}"""

    fun install(f: FakeNeema) {
        // Reports asks for EVERY thread: no `limit` → the legacy bare array. With `limit` → a page.
        f.on("GET", "/admin/conversations") { r, _ ->
            val rows = if (r.url.queryParameter("tab") == "human") conversations.filter { it.contains("\"human\"") } else conversations
            if (r.url.queryParameter("limit") == null) 200 to "[${rows.joinToString(",")}]"
            else 200 to """{"items":[${rows.joinToString(",")}],"next_cursor":null}"""
        }
        f.on("GET", "/admin/orders", body = "[${orders.joinToString(",")}]")
        f.on("GET", "/admin/catalog", body = catalog)
        f.on("GET", "/admin/catalog/audit", body = audit)
    }

    /** A backend with nothing in it (a fresh install). */
    fun installEmpty(f: FakeNeema) {
        f.on("GET", "/admin/conversations") { r, _ ->
            if (r.url.queryParameter("limit") == null) 200 to "[]" else 200 to """{"items":[],"next_cursor":null}"""
        }
        f.on("GET", "/admin/orders", body = "[]")
        f.on("GET", "/admin/catalog", body = "[]")
        f.on("GET", "/admin/catalog/audit", body = """{"currency_gaps":[],"per_piece":[],"checked":0,"rate":130}""")
        f.on("GET", "/admin/attribution", body = """{"sources":[],"unattributed":{"orders":0,"revenue":0,"paid_revenue":0},"totals":{"leads":0,"orders":0,"revenue":0}}""")
        f.on("GET", "/admin/stats", body = """{"open_conversations":0,"human_conversations":0,"ai_conversations":0,"active_agents":0,"total_agents":1,
          "total_revenue":0,"total_orders":0,"pending_orders":0,"delivered_orders":0,"confirmed_orders":0,"cancelled_orders":0,
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
