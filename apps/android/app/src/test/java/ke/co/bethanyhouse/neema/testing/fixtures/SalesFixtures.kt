package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.core.util.AppClock

import ke.co.bethanyhouse.neema.testing.FakeNeema
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit

/**
 * Orders, deals, planned actions and leads for the Orders / Deals / Leads
 * screens, built from what the backend handlers actually put on the wire
 * (round 3: API contract). Each builder cites its handler.
 *
 * Serialisation facts these fixtures reproduce:
 *  - Timestamps come from `timestamptz` columns, so Python's `isoformat()`
 *    prints `2026-03-14T09:30:00.123456+00:00` — an explicit offset, six
 *    fractional digits, and no fraction at all when the microseconds are 0.
 *  - A `Numeric(12,2)` column (`subtotal`, `hub_total`) reaches the client
 *    through FastAPI's `jsonable_encoder`, whose `decimal_encoder` turns
 *    `Decimal("9800.00")` into the float `9800.0`.
 *  - `list_orders` returns bare ORM rows: EVERY column is present (null when
 *    unset), and nothing that isn't a column (no `contact_name`).
 *
 * Anything printed as an absolute date uses a fixed instant so snapshots are
 * stable day to day; "5m ago" / "in 3h" labels are relative to now.
 */
object SalesFixtures {
    // ── wire helpers ────────────────────────────────────────────────────────

    private val PY_MICROS = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSSSS").withZone(ZoneOffset.UTC)
    private val PY_SECONDS = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss").withZone(ZoneOffset.UTC)

    /** Python `datetime.isoformat()` of an aware UTC datetime (asyncpg hands back tz=UTC). */
    fun pyIso(i: Instant): String =
        (if (i.nano / 1000 == 0) PY_SECONDS.format(i) else PY_MICROS.format(i)) + "+00:00"

    /** The same for a NAIVE datetime (`datetime.utcnow()`): no offset at all. */
    fun pyNaive(i: Instant): String = if (i.nano / 1000 == 0) PY_SECONDS.format(i) else PY_MICROS.format(i)

    /**
     * [minutes] ago, as the server prints it (with microseconds). The sub-second
     * part is taken OFF, never added: a stamp 123 ms in the future read "44m
     * ago" instead of "45m ago" whenever a screen rendered within 123 ms of
     * building it, so snapshots flipped with machine speed.
     */
    fun ago(minutes: Long): String = pyIso(AppClock.instant().minus(minutes, ChronoUnit.MINUTES).minusNanos(123_456_000))

    fun inHours(h: Long, extraMin: Long = 20): String =
        pyIso(AppClock.instant().plus(h * 60 + extraMin, ChronoUnit.MINUTES).plusNanos(654_321_000))

    /** A fixed creation time for the order detail (its "Date" cell prints the day); 0 µs → no fraction. */
    const val FIXED_AT = "2026-03-14T09:30:00+00:00"

    private fun el(v: Any?): JsonElement = when (v) {
        null -> JsonNull
        is JsonElement -> v
        is String -> JsonPrimitive(v)
        is Number -> JsonPrimitive(v)
        is Boolean -> JsonPrimitive(v)
        is Map<*, *> -> JsonObject(v.entries.associate { (k, x) -> k.toString() to el(x) })
        is List<*> -> JsonArray(v.map(::el))
        else -> error("unsupported $v")
    }

    fun obj(vararg pairs: Pair<String, Any?>): JsonObject = el(mapOf(*pairs)) as JsonObject

    // ── Orders ──────────────────────────────────────────────────────────────

    /**
     * An n8n (Tier 1) cart line — n8n_bridge.py `upsert_order_event` stores
     * `OrderEventDto.items` verbatim, in the `{name, qty, unit, total, sku}`
     * shape the web's `ApiOrder` was written against.
     */
    fun legacyLine(name: String, qty: Int, unit: Int, sku: String? = null) =
        obj("name" to name, "qty" to qty, "unit" to unit, "total" to qty * unit, "sku" to sku)

    /**
     * A Tier 2 cart line — agent/tools.py `_cart_update` rows, persisted as
     * `OrderEvent.items` by `create_order`: `unit_price`, no `unit`, no `total`.
     */
    fun agentLine(name: String, qty: Int, unitPrice: Double, sku: String = "", productId: Int = 412) =
        obj(
            "hub_product_id" to productId, "name" to name, "sku" to sku, "qty" to qty,
            "unit_price" to unitPrice, "price_usd" to unitPrice / 130.0,
            "prices" to mapOf("KES" to unitPrice, "USD" to unitPrice / 130.0),
            "in_stock" to true, "made_to_order" to false,
        )

    /**
     * One row of GET /admin/orders — admin.py `list_orders` returns
     * `select(OrderEvent)` rows through `jsonable_encoder`: every column of
     * models/order_event.py, in the model's defaults unless set.
     */
    fun order(
        id: String,
        waId: String,
        status: String,
        subtotal: Double,
        items: List<JsonObject> = listOf(legacyLine("Clergy Shirt — Black, 16 inch", 1, subtotal.toInt(), "CS-BLK-16")),
        channel: String = "whatsapp",
        createdAt: String = ago(60),
        eventType: String? = "confirmed",
        currency: String = "KES",
        paymentStatus: String = "unpaid",
        fulfillmentStatus: String = "pending",
        replyText: String? = null,
        sessionId: String? = null,
        hub: Map<String, Any?> = emptyMap(),
    ): String {
        val row = linkedMapOf<String, Any?>(
            "id" to id, "wa_id" to waId, "person_id" to "5b0e6a52-3c1d-4f7e-9a44-${waId.takeLast(12).padStart(12, '0')}",
            "session_id" to sessionId, "event_type" to eventType, "items" to items,
            "subtotal" to subtotal, "currency" to currency, "status" to status,
            "payment_status" to paymentStatus, "fulfillment_status" to fulfillmentStatus,
            "reply_text" to replyText, "channel" to channel, "state" to emptyMap<String, Any?>(),
            "created_at" to createdAt, "updated_at" to createdAt,
            "hub_order_id" to null, "hub_order_number" to null, "hub_push_status" to null,
            "hub_payment_url" to null, "hub_currency" to null, "hub_total" to null,
            "hub_last_error" to null, "hub_pushed_at" to null, "hub_public_url" to null,
            "hub_public_token" to null, "short_ref" to null, "hub_status" to null,
            "hub_payment_status" to null, "hub_fulfillment_status" to null, "hub_status_at" to null,
        )
        row.putAll(hub)
        return el(row).toString()
    }

    /** The hub columns agent/tools.py `create_order` sets on a pushed order. */
    fun pushed(number: Int, total: Double, at: String = FIXED_AT, withToken: Boolean = true) = buildMap<String, Any?> {
        put("hub_order_id", number); put("hub_order_number", "BH-$number"); put("hub_push_status", "pushed")
        put("hub_currency", "KES"); put("hub_total", total); put("hub_pushed_at", at)
        if (withToken) {
            put("hub_public_token", "tok$number"); put("hub_public_url", "https://hub.bethanyhouse.co.ke/order/tok$number")
            put("short_ref", "r$number")
        }
    }

    /**
     * What services/hub_events.py `_mirror_order_state` writes when the hub
     * reports: `hub_status` / `hub_payment_status` / `hub_fulfillment_status`
     * + `hub_status_at` (never our own `status`).
     */
    fun mirrored(status: String, payment: String? = null, fulfillment: String? = null, at: String = FIXED_AT) =
        mapOf("hub_status" to status, "hub_payment_status" to payment, "hub_fulfillment_status" to fulfillment, "hub_status_at" to at)

    /**
     * The order detail's subject: an n8n order pushed to the hub by
     * n8n_bridge.py `_maybe_push_order_to_hub` (legacy priced lines), then
     * mirrored as processing/paid by the hub, with the reply Neema sent.
     */
    val linkedOrder = order(
        "254712345678_1773480600000", "254712345678", "confirmed", 9800.0,
        items = listOf(
            legacyLine("Clergy Shirt — Black, 16 inch", 2, 3500, "CS-BLK-16"),
            legacyLine("Roman Collar Tab", 4, 250, "RC-TAB"),
            legacyLine("Delivery — Nyeri", 1, 1800),
        ),
        createdAt = FIXED_AT, sessionId = "254712345678_1773480000",
        hub = pushed(1042, 9800.0) + mirrored("processing", "paid", "unfulfilled"),
        replyText = "Asante Father! Your order BH-1042 is confirmed — we deliver to Nyeri on Friday.",
    )

    /**
     * An order the agent placed (agent/tools.py `create_order`): status
     * "pending", Tier 2 lines that carry `unit_price` only.
     */
    val agentOrder = order(
        "254799111222_1773484200000", "254799111222", "pending", 145000.0,
        items = listOf(
            agentLine("Mitre — Gold embroidered", 1, 85000.0, "MIT-GLD"),
            agentLine("Cope — Festal white", 1, 60000.0, "COP-WHT"),
        ),
        createdAt = FIXED_AT, hub = pushed(1050, 145000.0),
    )

    /** A cart the hub refused: n8n_bridge.py `_save(hub_push_status="failed", hub_last_error=str(exc)[:500])`. */
    val failedOrder = order(
        "254722000111_1773480600000", "254722000111", "open", 12500.0,
        items = listOf(legacyLine("Cassock — Purple, L", 1, 12500, "CAS-PUR-L")),
        createdAt = FIXED_AT,
        hub = mapOf("hub_push_status" to "failed", "hub_last_error" to "Variant CAS-PUR-L is out of stock in the hub (0 available)"),
    )

    /** The list's first page: every status, hub states, channels, both line shapes, a cart snapshot. */
    val orders get() = listOf(
        order("o1", "254712345678", "confirmed", 8000.0,
            items = listOf(legacyLine("Clergy Shirt — Black, 16 inch", 2, 3500, "CS-BLK-16"),
                legacyLine("Roman Collar Tab", 4, 250), legacyLine("Stole — Green", 1, 0)),
            createdAt = ago(45), hub = pushed(1042, 8000.0) + mirrored("processing")),
        order("o2", "254722000111", "open", 12500.0, createdAt = ago(180),
            items = listOf(legacyLine("Cassock — Purple, L", 1, 12500)),
            hub = mapOf("hub_push_status" to "failed", "hub_last_error" to "Variant out of stock in hub")),
        order("o3", "255754333222", "delivered", 4800.0, createdAt = ago(60 * 30),
            items = listOf(legacyLine("Stole — Green", 1, 4800)),
            hub = pushed(1031, 4800.0, withToken = false) + mirrored("completed", "paid", "fulfilled")),
        order("o4", "254700999888", "cancelled", 18000.0, channel = "instagram", createdAt = ago(60 * 72),
            items = listOf(agentLine("Alb — White, M", 3, 6000.0))),
        // An n8n cart snapshot: no lines, status "open", event_type "cart".
        order("o5", "254733444555", "open", 3500.0, channel = "whatsapp", createdAt = ago(60 * 5),
            items = emptyList(), eventType = "cart"),
        order("o6", "260977123456", "pending", 1450.0, currency = "ZMW",
            createdAt = ago(60 * 8), channel = "messenger",
            items = listOf(agentLine("Mitre — Gold embroidered", 1, 850.0), agentLine("Cope — Festal white", 1, 600.0)),
            hub = pushed(1050, 1450.0) + mapOf("hub_currency" to "ZMW") + mirrored("shipped")),
    )

    /** 100 orders: seven pages of fifteen, so the pager windows. */
    val manyOrders get() = (1..100).map { i ->
        val st = listOf("open", "confirmed", "delivered", "cancelled")[i % 4]
        order("m$i", "2547${(10000000 + i * 7919).toString().take(8)}", st, 1000.0 * i, createdAt = ago(i * 37L))
    }

    fun ordersJson(list: List<String>) = list.joinToString(",", "[", "]")

    /**
     * PATCH /admin/orders/{id} — admin.py `update_order` sets the allowed
     * keys and returns the same ORM row. `updated_at`'s Python-side
     * `onupdate=datetime.utcnow` is what the instance holds after the flush,
     * so it comes back NAIVE (no offset), unlike every other timestamp.
     */
    fun patchedOrder(id: String, status: String): String =
        order(id, "254700000000", status, 1000.0, createdAt = FIXED_AT,
            hub = mapOf("updated_at" to pyNaive(AppClock.instant().plusNanos(250_000_000))))

    // ── Deals & planned actions ─────────────────────────────────────────────

    /**
     * GET /admin/deals — crm.py `list_deals`: `{"deals": [...]}`. `items` is
     * services/deals.py's `items_snapshot` (`{name, qty, price}`, where `price`
     * is the cart line's `price` — absent on Tier 2 lines, so null);
     * `next_action` is the scribe's dict (owner "ai") or null.
     */
    val deals get() = """{"deals":[
      {"id":"d1","conversation_id":"c1","customer":"Fr. Peter Kamau","wa_id":"254712345678","channel":"whatsapp","title":"Clergy Shirt — Black, 16 inch",
       "items":[{"name":"Clergy Shirt — Black, 16 inch","qty":2,"price":null}],"stage":"proposal","blocking":"Neema owes the customer: confirm the Nyeri delivery date",
       "next_action":{"kind":"follow_up","owner":"ai","due_at":"${inHours(3)}","note":"confirm the Nyeri delivery date"},"guidance":"Offer free delivery to Nyeri","status":"open","updated_at":"${ago(12)}"},
      {"id":"d2","conversation_id":"c2","customer":"Rev. Mary Achieng","wa_id":"254722000111","channel":"messenger","title":"Cassock — Purple, L",
       "items":[],"stage":"qualified","blocking":null,"next_action":null,"guidance":null,"status":"open","updated_at":"${ago(90)}"},
      {"id":"d3","conversation_id":"c6","customer":"Deacon James Mwangi","wa_id":"254733444555","channel":"whatsapp","title":"Made-to-measure alb for the ordination on the 12th — needs chest, sleeve and length",
       "items":[],"stage":"new","blocking":"Waiting on the customer (tonight) — he promised to send the measurements after choir practice","next_action":{"kind":"customer_promise","owner":"ai","due_at":"${inHours(20)}","note":"they said: tonight"},"guidance":null,"status":"open","updated_at":"${ago(300)}"},
      {"id":"d4","conversation_id":null,"customer":"Unknown","wa_id":null,"channel":null,"title":"Choir robes ×24",
       "items":[],"stage":"negotiation","blocking":null,"next_action":{"kind":"follow_up","owner":"ai","due_at":"${ago(30)}","note":"send the robe quote"},"guidance":null,"status":"open","updated_at":"${ago(60 * 26)}"}
    ]}"""

    /** GET /admin/deals?status=won — the same row shape. */
    val wonDeals get() = """{"deals":[
      {"id":"w1","conversation_id":"c7","customer":"St. Mark's","wa_id":"254700111222","channel":"whatsapp","title":"Choir robes","items":[],"stage":"won","blocking":null,"next_action":null,"guidance":null,"status":"won","updated_at":"${ago(600)}"},
      {"id":"w2","conversation_id":null,"customer":"Unknown","wa_id":null,"channel":null,"title":null,"items":[],"stage":"won","blocking":null,"next_action":null,"guidance":null,"status":"won","updated_at":null}
    ]}"""

    /**
     * GET /admin/actions — crm.py `list_actions`: `{"actions": [...]}`,
     * `due_at` is never null (a NOT NULL column), `created_by` is the model
     * default "ai".
     */
    val actions get() = """{"actions":[
      {"id":"x1","deal_id":"d1","conversation_id":"c1","due_at":"${ago(20)}","kind":"follow_up","reason":"Neema promised: confirm Friday delivery to Nyeri",
       "draft":"Hello Father Peter 🙏 Just confirming — we can deliver both shirts to Nyeri by Friday. Shall I send the M-Pesa details?","status":"needs_approval","created_by":"ai"},
      {"id":"x2","deal_id":"d3","conversation_id":"c6","due_at":"${inHours(5)}","kind":"customer_promise","reason":"Customer said they'd respond (tonight) — warm check-in if they haven't",
       "draft":null,"status":"planned","created_by":"ai"}
    ]}"""

    // ── Leads ───────────────────────────────────────────────────────────────

    /** crm.py `_customer_tier`. */
    private fun tier(orders: Int, spent: Double, daysSinceLast: Int?): Pair<String, String> {
        val dsl = daysSinceLast ?: 0
        val t = when {
            orders == 0 -> "prospect"
            orders >= 3 && dsl > 120 -> "at_risk"
            spent >= 500_000 || orders >= 20 -> "vip"
            orders >= 5 -> "loyal"
            orders <= 1 -> "new"
            else -> "regular"
        }
        return t to mapOf("prospect" to "Prospect", "new" to "New", "regular" to "Regular", "loyal" to "Loyal", "vip" to "VIP", "at_risk" to "At risk").getValue(t)
    }

    /**
     * One row of GET /admin/leads — crm.py `list_leads` (a bare array):
     * `lead_score` an int, `total_spent` the float sum of subtotals (the int
     * `0` when there are no orders — Python's `sum([])`), `phone` null when
     * the wa_id isn't a plausible phone, `buying_rhythm` from `_buying_rhythm`
     * (nulls under two orders), `notes` = `state["crm_notes"]`.
     */
    fun lead(
        id: String, waId: String, name: String?, stage: String, score: Int, spent: Double = 0.0, orders: Int = 0,
        channels: List<String> = listOf("whatsapp"), tags: Any? = emptyList<String>(), seen: String? = ago(30),
        notes: String? = null, email: String? = null, location: String? = null, phone: String? = waId,
        daysSinceLast: Int? = if (orders > 0) 12 else null, avgInterval: Double? = if (orders >= 2) 30.5 else null,
    ): String {
        val (t, label) = tier(orders, spent, daysSinceLast)
        return el(linkedMapOf(
            "id" to id, "wa_id" to waId, "name" to name, "phone" to phone, "email" to email, "location" to location,
            "lead_stage" to stage, "lead_score" to score, "tier" to t, "tier_label" to label,
            "tags" to tags, "channels" to channels, "total_orders" to orders,
            "total_spent" to (if (orders == 0) 0 else spent),
            "buying_rhythm" to mapOf(
                "days_since_last" to daysSinceLast, "avg_interval_days" to avgInterval,
                "cadence_label" to avgInterval?.let { "about every ${Math.round(it / 7).coerceAtLeast(1)} weeks" },
                "overdue" to false,
            ),
            "last_seen_at" to seen, "notes" to notes,
        )).toString()
    }

    val leads get() = listOf(
        lead("u1", "254712345678", "Fr. Peter Kamau", "proposal", 86, spent = 24500.0, orders = 3,
            channels = listOf("whatsapp", "facebook"), tags = listOf("vip", "clergy", "repeat-buyer", "nyeri"),
            notes = "Buys for the whole parish. Prefers delivery on Fridays.", email = "peter@acknyeri.org", location = "Nyeri"),
        lead("u2", "254722000111", "Rev. Mary Achieng", "qualified", 55, channels = listOf("messenger"), seen = ago(9)),
        lead("u3", "255754333222", null, "new", 12, seen = ago(34)),
        // An Instagram handle: not a plausible phone, so `phone` is null.
        lead("u4", "17840000000000001", "Sr. Lucy Njeri", "contacted", 38, channels = listOf("instagram"),
            tags = listOf("convent"), phone = null),
        lead("u5", "254733444555", "Deacon James Mwangi", "negotiation", 71, spent = 18000.0, orders = 1,
            channels = listOf("whatsapp", "sms", "email"), seen = ago(60 * 5)),
        // A custom stage: stored as the operator typed it, read back lower-cased by normalise_stage.
        lead("u6", "254700111222", "St. Mark's Cathedral Choir", "measuring", 64, spent = 52000.0, orders = 2),
        lead("u7", "254799111222", "Bishop Samuel Kariuki", "won", 97, spent = 145000.0, orders = 6, tags = listOf("vip")),
        lead("u8", "254700999888", "Mr. Otieno", "lost", 20, seen = null),
    )

    fun leadsJson(list: List<String> = leads) = list.joinToString(",", "[", "]")

    /** Registers every route these screens call, over [FakeNeema.withFixtures]'s base set. */
    fun install(f: FakeNeema, orderList: List<String> = orders) {
        // admin.py list_orders
        f.on("GET", "/admin/orders", body = ordersJson(orderList))
        // admin.py update_order — the updated OrderEvent row (naive updated_at).
        f.on("PATCH", "/admin/orders/[^/]+") { r, body ->
            val id = r.url.pathSegments.last()
            val status = Regex("\"status\":\"([a-z]+)\"").find(body.orEmpty())?.groupValues?.get(1) ?: "open"
            200 to patchedOrder(id, status)
        }
        // crm.py list_deals / update_deal
        f.on("GET", "/admin/deals") { r, _ ->
            200 to (if (r.url.queryParameter("status") == "won") wonDeals else deals)
        }
        f.on("PATCH", "/admin/deals/[^/]+", body = """{"ok":true}""")
        // crm.py list_actions / approve_action / veto_action
        f.on("GET", "/admin/actions", body = actions)
        f.on("POST", "/admin/actions/[^/]+/approve") { _, body ->
            val draft = Regex("\"draft\":\"((?:[^\"\\\\]|\\\\.)*)\"").find(body.orEmpty())?.groupValues?.get(1) ?: "Hello 🙏"
            200 to """{"ok":true,"sent":"$draft"}"""
        }
        f.on("POST", "/admin/actions/[^/]+/veto", body = """{"ok":true}""")
        // crm.py list_leads / update_lead
        f.on("GET", "/admin/leads", body = leadsJson())
        f.on("PATCH", "/admin/leads/[^/]+", body = """{"ok":true}""")
        // crm.py get_pipeline_stages — labels as the operator typed them.
        f.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["Measuring"]}""")
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
