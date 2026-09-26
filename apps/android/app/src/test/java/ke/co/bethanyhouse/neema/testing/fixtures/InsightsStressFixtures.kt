package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.CustomRole
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.model.OrderItem
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.testing.FakeNeema
import kotlinx.serialization.builtins.ListSerializer
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * Round 8: a busy shop for Reports / Analytics / Catalog / Team — 10,000
 * conversations over 120 days, 1,000 orders, 200 agents in 50 roles and a
 * 2,000-product catalogue. Deterministic (no randomness: every field is a
 * function of the row's index), dated back from [ReportsFixtures.NOW], and
 * encoded with the app's own serializers so the fake answers exactly what
 * the client reads.
 */
object InsightsStressFixtures {
    private val NOW = ReportsFixtures.NOW
    private val PY_ISO = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSSSSSxxx")

    /** The API's datetime [minutes] before NOW. */
    fun iso(minutes: Long): String = NOW.minusSeconds(minutes * 60).atOffset(ZoneOffset.UTC).format(PY_ISO)

    private val CHANNELS = listOf("whatsapp", "messenger", "instagram", "facebook", "tiktok", "email", "web")
    private val MODES = listOf("ai", "ai", "ai", "human", "paused")
    private val STATUSES = listOf("pending", "confirmed", "delivered", "cancelled", "open")
    private val CATEGORIES = listOf(
        "Anointing Oil", "Communion Wafers", "Communion Cups", "Prefilled Cups", "Communion Wine",
        "Communion Trays", "Communion Accessories", "Clergy Apparel", "Clergy Vestments", "",
    )

    fun agentId(i: Int) = "stress-agent-$i"
    fun roleId(i: Int) = "stress-role-$i"
    /** Customers repeat: 3,000 phone numbers across the conversations and orders. */
    fun phone(i: Int) = "2547${"%08d".format(10_000_000 + i % 3_000)}"

    fun conversations(n: Int = 10_000, agents: Int = 200): List<Conversation> = (0 until n).map { i ->
        val mode = MODES[i % MODES.size]
        // Spread over ~120 days (13 minutes apart), newest first; every 50th has no message yet.
        val at = iso(i * 17L + 1)
        Conversation(
            id = "stress-conv-$i", waId = phone(i), interceptMode = mode,
            assignedAgentId = if (mode == "human" || i % 7 == 0) agentId(i % agents) else null,
            lastMessageAt = if (i % 50 == 0) null else at, createdAt = iso(i * 17L + 60),
            status = if (i % 3 == 0) "closed" else "open",
            name = if (i % 4 == 0) null else "Customer $i", channel = CHANNELS[i % CHANNELS.size],
        )
    }

    fun orders(n: Int = 1_000): List<Order> = (0 until n).map { i ->
        val unit = 250.0 * (1 + i % 40)
        val qty = 1 + i % 5
        Order(
            id = "stress-order-$i", waId = phone(i * 7), rawStatus = STATUSES[i % STATUSES.size],
            subtotal = unit * qty, createdAt = iso(i * 97L + 5),
            items = listOf(OrderItem(name = "Product ${i % 60}", qty = qty.toDouble(), unit = unit, total = unit * qty)),
        )
    }

    fun roles(n: Int = 50): List<CustomRole> = (0 until n).map { i ->
        CustomRole(
            id = roleId(i), name = "Role $i", description = if (i % 2 == 0) "Handles queue $i" else "",
            color = listOf("#589b31", "#2a48a2", "#7c3aed", "#b45309")[i % 4],
            permissions = listOf("view_conversations", "reply_conversations", "view_orders", "view_catalog", "view_reports").take(1 + i % 5),
        )
    }

    fun agents(n: Int = 200, roles: Int = 50): List<Agent> = (0 until n).map { i ->
        Agent(
            id = agentId(i), name = "Agent ${"%03d".format(i)} ${listOf("Wanjiku", "Otieno", "Achieng", "Kamau")[i % 4]}",
            email = "agent$i@bethanyhouse.co.ke", role = listOf("agent", "admin", "readonly")[i % 3],
            isAvailable = i % 3 == 0, activeConvs = i % 11, createdAt = iso(400L * 24 * 60 + i),
            lastSeenAt = iso((i % 90).toLong()), customRoleId = if (i % 4 == 3) null else roleId(i % roles),
        )
    }

    fun catalog(n: Int = 2_000): List<CatalogItem> = (0 until n).map { i ->
        CatalogItem(
            hubProductId = 10_000L + i, sku = "SKU-${"%05d".format(i)}", name = "Product $i ${CATEGORIES[i % CATEGORIES.size]}".trim(),
            aliases = if (i % 3 == 0) listOf("alias$i", "kitu $i") else emptyList(),
            price = 100.0 * (1 + i % 90), rawCategory = CATEGORIES[i % CATEGORIES.size].ifEmpty { null },
            inStock = i % 9 != 0, availableQty = if (i % 9 != 0) (i % 300).toDouble() else null,
            imageUrl = "https://hub.test/img/$i.webp",
        )
    }

    private fun <T> json(list: List<T>, s: kotlinx.serialization.KSerializer<T>) = NeemaJson.encodeToString(ListSerializer(s), list)

    /** The whole busy shop on [f] (over the base fixtures, which stay for /admin/me etc.). */
    fun install(
        f: FakeNeema, convs: Int = 10_000, orders: Int = 1_000, agents: Int = 200, roles: Int = 50, catalog: Int = 2_000,
    ) {
        val convRows = conversations(convs, agents)
        val convBody = json(convRows, Conversation.serializer())
        val humanBody = """{"items":${json(convRows.filter { it.interceptMode == "human" }.take(10), Conversation.serializer())},"next_cursor":null}"""
        val firstPage = """{"items":${json(convRows.take(50), Conversation.serializer())},"next_cursor":"c50"}"""
        f.on("GET", "/admin/conversations") { r, _ ->
            when {
                r.url.queryParameter("limit") == null -> 200 to convBody
                r.url.queryParameter("tab") == "human" -> 200 to humanBody
                else -> 200 to firstPage
            }
        }
        f.on("GET", "/admin/orders", body = json(orders(orders), Order.serializer()))
        f.on("GET", "/admin/agents", body = json(agents(agents, roles), Agent.serializer()))
        f.on("GET", "/admin/roles", body = json(roles(roles), CustomRole.serializer()))
        f.on("GET", "/admin/catalog", body = json(catalog(catalog), CatalogItem.serializer()))
    }
}
