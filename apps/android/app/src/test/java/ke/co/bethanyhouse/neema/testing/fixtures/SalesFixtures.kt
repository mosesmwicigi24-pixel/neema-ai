package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures.ago
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * Orders, deals, planned actions and leads for the Orders / Deals / Leads
 * screens, shaped exactly like admin.py `list_orders` (bare OrderEvent rows)
 * and crm.py `list_deals` / `list_actions` / `list_leads`.
 *
 * Anything printed as an absolute date uses a fixed instant so snapshots are
 * stable day to day; "5m ago" / "in 3h" labels are relative to now.
 */
object SalesFixtures {
    /** A fixed creation time for the order detail (its "Date" cell prints the day). */
    const val FIXED_AT = "2026-03-14T09:30:00Z"

    fun inHours(h: Long, extraMin: Long = 20): String =
        Instant.now().plus(h * 60 + extraMin, ChronoUnit.MINUTES).toString()

    fun order(
        id: String,
        waId: String,
        name: String?,
        status: String,
        subtotal: Int,
        items: String = """[{"name":"Clergy Shirt — Black, 16 inch","qty":1,"unit":$subtotal,"total":$subtotal,"sku":"CS-BLK-16"}]""",
        channel: String = "whatsapp",
        createdAt: String = ago(60),
        hub: String = "",
        replyText: String? = null,
    ) = """{"id":"$id","wa_id":"$waId","session_id":null,"event_type":"order","items":$items,"subtotal":$subtotal,"currency":"KES",
        "status":"$status","payment_status":"pending","fulfillment_status":"unfulfilled","reply_text":${replyText?.let { "\"$it\"" }},
        "channel":"$channel","state":{},"created_at":"$createdAt","updated_at":"$createdAt","contact_name":${name?.let { "\"$it\"" }}$hub}"""

    /** The order detail's subject: pushed to the hub, three items, a note. */
    val linkedOrder = order(
        "2f6c1a90-0000-4000-8000-00000a1b2c3d", "254712345678", "Fr. Peter Kamau", "confirmed", 9800,
        items = """[{"name":"Clergy Shirt — Black, 16 inch","qty":2,"unit":3500,"total":7000,"sku":"CS-BLK-16"},
          {"name":"Roman Collar Tab","qty":4,"unit":250,"total":1000,"sku":"RC-TAB"},
          {"name":"Delivery — Nyeri","qty":1,"unit":1800,"total":1800}]""",
        createdAt = FIXED_AT,
        hub = ""","hub_order_id":1042,"hub_order_number":"BH-1042","hub_push_status":"pushed","hub_status":"processing",
          "hub_payment_status":"paid","hub_public_token":"tok1042","hub_public_url":"https://hub.bethanyhouse.co.ke/o/tok1042"""",
        replyText = "Asante Father! Your order BH-1042 is confirmed — we deliver to Nyeri on Friday.",
    )

    /** A cart that never reached the hub: the push failed with the hub's reason. */
    val failedOrder = order(
        "7d1e0b22-0000-4000-8000-0000000f41ed", "254722000111", "Rev. Mary Achieng", "open", 12500,
        items = """[{"name":"Cassock — Purple, L","qty":1,"unit":12500,"total":12500,"sku":"CAS-PUR-L"}]""",
        channel = "messenger", createdAt = FIXED_AT,
        hub = ""","hub_push_status":"failed","hub_last_error":"Variant CAS-PUR-L is out of stock in the hub (0 available)"""",
    )

    /** The list's first page: every status, hub states, channels, a long item list. */
    val orders get() = listOf(
        order("o1", "254712345678", "Fr. Peter Kamau", "confirmed", 8000,
            items = """[{"name":"Clergy Shirt — Black, 16 inch","qty":2,"unit":3500,"total":7000,"sku":"CS-BLK-16"},
              {"name":"Roman Collar Tab","qty":4,"unit":250,"total":1000},{"name":"Stole — Green","qty":1,"unit":0,"total":0}]""",
            createdAt = ago(45),
            hub = ""","hub_order_id":1042,"hub_order_number":"BH-1042","hub_push_status":"pushed","hub_status":"processing","hub_public_token":"tok1042""""),
        order("o2", "254722000111", "Rev. Mary Achieng", "open", 12500, channel = "messenger", createdAt = ago(180),
            items = """[{"name":"Cassock — Purple, L","qty":1,"unit":12500,"total":12500}]""",
            hub = ""","hub_push_status":"failed","hub_last_error":"Variant out of stock in hub""""),
        order("o3", "255754333222", "Deacon John Mushi", "delivered", 4800, createdAt = ago(60 * 30),
            items = """[{"name":"Stole — Green","qty":1,"unit":4800,"total":4800}]""",
            hub = ""","hub_order_id":1031,"hub_order_number":"BH-1031","hub_status":"completed""""),
        order("o4", "254700999888", "Sr. Lucy Njeri", "cancelled", 18000, channel = "instagram", createdAt = ago(60 * 72),
            items = """[{"name":"Alb — White, M","qty":3,"unit":6000,"total":18000}]"""),
        order("o5", "254733444555", null, "pending", 3500, channel = "facebook", createdAt = ago(60 * 5)),
        order("o6", "254799111222", "Bishop Samuel Kariuki of the Anglican Diocese of Mount Kenya West", "confirmed", 145000,
            createdAt = ago(60 * 8), channel = "whatsapp",
            items = """[{"name":"Mitre — Gold embroidered","qty":1,"unit":85000,"total":85000},{"name":"Cope — Festal white","qty":1,"unit":60000,"total":60000}]""",
            hub = ""","hub_order_id":1050,"hub_order_number":"BH-1050","hub_status":"shipped""""),
    )

    /** 100 orders: seven pages of fifteen, so the pager windows. */
    val manyOrders get() = (1..100).map { i ->
        val st = listOf("open", "confirmed", "delivered", "cancelled")[i % 4]
        order("m$i", "2547${(10000000 + i * 7919).toString().take(8)}", "Customer $i", st, 1000 * i, createdAt = ago(i * 37L))
    }

    fun ordersJson(list: List<String>) = list.joinToString(",", "[", "]")

    val deals get() = """{"deals":[
      {"id":"d1","conversation_id":"c1","customer":"Fr. Peter Kamau","wa_id":"254712345678","channel":"whatsapp","title":"2× Clergy Shirt (Black 16\")",
       "items":[{"name":"Clergy Shirt","qty":2,"price":3500}],"stage":"proposal","blocking":"Needs delivery date confirmed",
       "next_action":{"kind":"follow_up","owner":"ai","due_at":"${inHours(3)}","note":"Confirm Nyeri delivery"},"guidance":"Offer free delivery to Nyeri","status":"open","updated_at":"${ago(12)}"},
      {"id":"d2","conversation_id":"c2","customer":"Rev. Mary Achieng","wa_id":"254722000111","channel":"messenger","title":"Purple cassock",
       "items":[],"stage":"qualified","blocking":null,"next_action":null,"guidance":null,"status":"open","updated_at":"${ago(90)}"},
      {"id":"d3","conversation_id":"c6","customer":"Deacon James Mwangi","wa_id":"254733444555","channel":"whatsapp","title":"Made-to-measure alb for the ordination on the 12th — needs chest, sleeve and length",
       "items":[],"stage":"new","blocking":"Waiting for measurements — he promised to send them tonight after choir practice","next_action":{"kind":"customer_promise","owner":"human","due_at":"${inHours(20)}"},"guidance":null,"status":"open","updated_at":"${ago(300)}"},
      {"id":"d4","conversation_id":null,"customer":"Unknown","wa_id":null,"channel":null,"title":"Choir robes ×24",
       "items":[],"stage":"negotiation","blocking":null,"next_action":{"kind":"follow_up","owner":"ai","due_at":"${ago(30)}"},"guidance":null,"status":"open","updated_at":"${ago(60 * 26)}"}
    ]}"""

    val wonDeals = """{"deals":[{"id":"w1","customer":"St. Mark's","stage":"won","status":"won"},{"id":"w2","customer":"Fr. Otieno","stage":"won","status":"won"}]}"""

    val actions get() = """{"actions":[
      {"id":"x1","deal_id":"d1","conversation_id":"c1","due_at":null,"kind":"follow_up","reason":"Father asked about Friday delivery 2h ago and hasn't had an answer",
       "draft":"Hello Father Peter 🙏 Just confirming — we can deliver both shirts to Nyeri by Friday. Shall I send the M-Pesa details?","status":"needs_approval","created_by":"neema"},
      {"id":"x2","deal_id":"d3","conversation_id":"c6","due_at":"${inHours(5)}","kind":"customer_promise","reason":"He said he'd send measurements tonight",
       "draft":null,"status":"planned","created_by":"neema"}
    ]}"""

    fun lead(
        id: String, waId: String?, name: String?, stage: String, score: Int, spent: Int = 0, orders: Int = 0,
        channels: String = """["whatsapp"]""", tags: String = "[]", seen: String? = ago(30), notes: String? = null,
        email: String? = null, location: String? = null,
    ) = """{"id":"$id","wa_id":${waId?.let { "\"$it\"" }},"name":${name?.let { "\"$it\"" }},"phone":${waId?.let { "\"$it\"" }},
        "email":${email?.let { "\"$it\"" }},"location":${location?.let { "\"$it\"" }},"lead_stage":"$stage","lead_score":$score,
        "tier":"regular","tier_label":"Regular","tags":$tags,"channels":$channels,"total_orders":$orders,"total_spent":$spent,
        "buying_rhythm":{"days_since_last":12,"avg_interval_days":30,"cadence_label":"monthly","overdue":false},
        "last_seen_at":${seen?.let { "\"$it\"" }},"notes":${notes?.let { "\"$it\"" }}}"""

    val leads get() = listOf(
        lead("u1", "254712345678", "Fr. Peter Kamau", "proposal", 86, spent = 24500, orders = 3,
            channels = """["whatsapp","facebook"]""", tags = """["vip","clergy","repeat-buyer","nyeri"]""",
            notes = "Buys for the whole parish. Prefers delivery on Fridays.", email = "peter@acknyeri.org", location = "Nyeri"),
        lead("u2", "254722000111", "Rev. Mary Achieng", "qualified", 55, spent = 0, channels = """["messenger"]""", seen = ago(9)),
        lead("u3", "255754333222", null, "new", 12, channels = """["whatsapp"]""", seen = ago(34)),
        lead("u4", "17840000000000001", "Sr. Lucy Njeri", "contacted", 38, channels = """["instagram"]""", tags = """["convent"]"""),
        lead("u5", "254733444555", "Deacon James Mwangi", "negotiation", 71, spent = 18000, orders = 1,
            channels = """["whatsapp","sms","email"]""", seen = ago(60 * 5)),
        lead("u6", "254700111222", "St. Mark's Cathedral Choir", "measuring", 64, spent = 52000, orders = 2),
        lead("u7", "254799111222", "Bishop Samuel Kariuki", "won", 97, spent = 145000, orders = 6, tags = """["vip"]"""),
        lead("u8", "254700999888", "Mr. Otieno", "lost", 20, seen = null),
    )

    fun leadsJson(list: List<String> = leads) = list.joinToString(",", "[", "]")

    /** Registers every route these screens call, over [FakeNeema.withFixtures]'s base set. */
    fun install(f: FakeNeema, orderList: List<String> = orders) {
        f.on("GET", "/admin/orders", body = ordersJson(orderList))
        // admin.py update_order answers with the updated OrderEvent row.
        f.on("PATCH", "/admin/orders/[^/]+") { r, body ->
            val id = r.url.pathSegments.last()
            val status = Regex("\"status\":\"([a-z]+)\"").find(body.orEmpty())?.groupValues?.get(1) ?: "open"
            200 to order(id, "254700000000", "Customer", status, 1000)
        }
        f.on("GET", "/admin/deals") { r, _ ->
            200 to (if (r.url.queryParameter("status") == "won") wonDeals else deals)
        }
        f.on("GET", "/admin/actions", body = actions)
        f.on("GET", "/admin/leads", body = leadsJson())
        f.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["measuring"]}""")
    }

    /** A signed-in agent whose role grants [perms] only (read-only variants). */
    fun agentsWithRole(perms: List<String>) = """[{"id":"${ke.co.bethanyhouse.neema.testing.Fixtures.ME_ID}","name":"Moses Mwicigi",
        "email":"moses@bethanyhouse.co.ke","role":"agent","is_available":true,"is_superuser":false,"active_convs":0,"avatar_url":null,
        "created_at":"${ago(1000)}","last_seen_at":"${ago(1)}","custom_role_id":"viewer","custom_permissions":null,"role_name":"Viewer",
        "role_color":"#94a3b8","role_permissions":[${perms.joinToString(",") { "\"$it\"" }}]}]"""

    fun installReadOnly(f: FakeNeema, perms: List<String>) {
        val agents = agentsWithRole(perms)
        f.on("GET", "/admin/agents", body = agents)
        f.on("GET", "/admin/me", body = agents.trim().removePrefix("[").removeSuffix("]"))
    }
}
