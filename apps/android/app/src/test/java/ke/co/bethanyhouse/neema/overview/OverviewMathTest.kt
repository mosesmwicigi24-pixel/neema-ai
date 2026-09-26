package ke.co.bethanyhouse.neema.overview

import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.model.Stats
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.feature.overview.ChannelRow
import ke.co.bethanyhouse.neema.feature.overview.activityFeed
import ke.co.bethanyhouse.neema.feature.overview.channelRows
import ke.co.bethanyhouse.neema.feature.overview.headline
import ke.co.bethanyhouse.neema.feature.overview.sevenDayRevenue
import ke.co.bethanyhouse.neema.feature.overview.topProducts
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.ReportsFixtures.NAIROBI
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate

/** OverviewView.tsx's computations: API-first headline, fallbacks, feed, charts. */
class OverviewMathTest {
    private val convs: List<Conversation> = NeemaJson.decodeFromString("[${ReportsFixtures.conversations.joinToString(",")}]")
    private val orders: List<Order> = NeemaJson.decodeFromString("[${ReportsFixtures.orders.joinToString(",")}]")
    private val agents: List<Agent> = NeemaJson.decodeFromString(Fixtures.agents)
    private val catalog: List<CatalogItem> = NeemaJson.decodeFromString(ReportsFixtures.catalog)
    private val stats: Stats = NeemaJson.decodeFromString(ReportsFixtures.stats)
    private val today = LocalDate.of(2026, 9, 25)

    @Test fun headline_prefersServerStats() {
        val h = headline(stats, convs, agents, orders, catalog)
        assertEquals(128, h.openConvs)
        assertEquals(9, h.humanConvs)
        assertEquals(119, h.aiConvs)
        assertEquals(2, h.activeAgents)
        assertEquals(3, h.totalAgents)
        assertEquals(1_284_500.0, h.revenue, 0.0)
        assertEquals(284, h.totalOrders)
        assertEquals(21, h.pendingOrders)
        assertEquals(187, h.inStockItems)
        assertEquals(214, h.totalItems)
    }

    @Test fun headline_fallsBackToWhatTheAppHolds_whenStatsFail() {
        val h = headline(null, convs, agents, orders, catalog)
        assertEquals(8, h.openConvs) // r4 is closed
        assertEquals(3, h.humanConvs)
        assertEquals(5, h.aiConvs)
        assertEquals(2, h.activeAgents)
        assertEquals(3, h.totalAgents)
        assertEquals(71_800.0, h.revenue, 0.0) // every order but the cancelled 9,600
        assertEquals(7, h.totalOrders)
        assertEquals(2, h.pendingOrders)
        assertEquals(3, h.deliveredOrders)
        assertEquals(1, h.confirmedOrders)
        assertEquals(1, h.cancelledOrders)
        assertEquals(5, h.inStockItems)
        assertEquals(6, h.totalItems)
    }

    @Test fun channels_fromServer_dropEmptyRows() {
        val s = stats.copy(channelBreakdown = stats.channelBreakdown + ke.co.bethanyhouse.neema.core.model.ChannelCount("sms", 0, 0))
        assertEquals(
            // In the server's order; "web" is kept here and skipped by the panel (not in CHANNEL_CONFIG).
            listOf(
                ChannelRow("whatsapp", 96, 80), ChannelRow("messenger", 21, 15), ChannelRow("facebook", 70, 22),
                ChannelRow("instagram", 11, 9), ChannelRow("web", 3, 2),
            ),
            channelRows(s, convs),
        )
    }

    @Test fun channels_fallback_countsLocalRowsPerKnownChannel() {
        assertEquals(
            listOf(ChannelRow("whatsapp", 6, 6), ChannelRow("messenger", 1, 1), ChannelRow("facebook", 1, 1), ChannelRow("instagram", 1, 0)),
            channelRows(null, convs),
        )
        assertEquals(emptyList<ChannelRow>(), channelRows(null, emptyList()))
    }

    @Test fun activity_latestOrdersAndIntercepts_newestFirst() {
        val feed = activityFeed(orders, convs, agents)
        assertEquals(
            listOf("order-o1", "conv-r1", "order-o2", "order-o3", "order-o4", "conv-r5", "conv-r6"),
            feed.map { it.id },
        )
        // Orders carry no contact_name on the wire: the buyer reads as their number (mapOrder).
        assertEquals("+254 712 345 678", feed[0].user)
        assertEquals("KES 8,000", feed[0].target)
        assertEquals("Moses Mwicigi", feed[1].user)
        assertEquals("intercepted conversation with", feed[1].action)
        assertEquals("Fr. Peter Kamau", feed[1].target)
        assertEquals("Grace Wanjiru", feed[5].user)
    }

    @Test fun activity_unnamedBuyerShowsTheirNumber_unknownAgentReadsAnAgent() {
        val o = orders.first { it.id == "o5" }.copy(createdAt = ReportsFixtures.ago(1))
        val c = convs.first { it.id == "r1" }.copy(assignedAgentId = "gone")
        val feed = activityFeed(listOf(o), listOf(c), agents)
        assertEquals("+254 711 000 999", feed.first { it.id == "order-o5" }.user)
        assertEquals("An agent", feed.first { it.id == "conv-r1" }.user)
    }

    /** mapConversation() gives a messageless thread its created_at, so the web's feed keeps it. */
    @Test fun activity_messagelessHumanThread_datesFromCreation() {
        val c = convs.first { it.id == "r1" }.copy(lastMessageAt = null, createdAt = ReportsFixtures.ago(30))
        val feed = activityFeed(emptyList(), listOf(c), agents)
        assertEquals(listOf("conv-r1"), feed.map { it.id })
        assertEquals(c.createdAt, feed.single().at)
        // Neither date: dropped, as `c.last_message_at` is then undefined on the web.
        assertEquals(emptyList<Any>(), activityFeed(emptyList(), listOf(c.copy(createdAt = null)), agents))
    }

    /** `item.qty || item.quantity || 1`: only a zero (missing) quantity counts as one. */
    @Test fun topProducts_onlyZeroQtyCountsAsOne() {
        val o: Order = NeemaJson.decodeFromString(
            """{"id":"z","status":"confirmed","created_at":"2026-09-25T08:00:00Z","subtotal":0,
                "items":[{"name":"Refund line","qty":-2,"unit":100,"total":0}]}""",
        )
        assertEquals(-2.0, topProducts(listOf(o)).single().qty, 0.0)
    }

    @Test fun activity_isAtMostFourOrdersAndThreeIntercepts() {
        val many = (1..10).map { orders[0].copy(id = "x$it") }
        assertEquals(4 + 3, activityFeed(many, convs, agents).size)
    }

    @Test fun sevenDayRevenue_excludesCancelled_marksToday() {
        val bars = sevenDayRevenue(orders, today, NAIROBI)
        assertEquals(listOf("Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"), bars.map { it.label })
        assertEquals(listOf(4800.0, 0.0, 0.0, 18000.0, 0.0, 12500.0, 8000.0), bars.map { it.value })
        assertEquals(listOf(false, false, false, false, false, false, true), bars.map { it.isToday })
        assertEquals(true, sevenDayRevenue(emptyList(), today, NAIROBI).all { it.value == 0.0 })
    }

    @Test fun topProducts_byRevenue_excludingCancelled() {
        val top = topProducts(orders)
        assertEquals(
            listOf("Clergy Shirt", "Alb — White, M", "Cassock — Purple, L", "Clergy Shirt — Black, 16 inch", "Stole — Green"),
            top.map { it.name },
        )
        // "Clergy Shirt" is two orders (3,500 + 25,000) merged by name. The agent's own order (o2)
        // stores cart lines priced by `unit_price` only; the web counts those as 0, but the core
        // OrderItemsSerializer normalises them, so the cassock (12,500) now ranks third.
        assertEquals(listOf(28500.0, 18000.0, 12500.0, 7000.0, 4800.0), top.map { it.revenue })
        // Stole: the cancelled pair is not counted, the single pending one is.
        assertEquals(1.0, top.first { it.name == "Stole — Green" }.qty, 0.0)
        assertEquals(4800.0, top.first { it.name == "Stole — Green" }.revenue, 0.0)
    }

    @Test fun topProducts_itemWithoutTotal_usesUnitTimesQty_andMissingQtyCountsOne() {
        val o: Order = NeemaJson.decodeFromString(
            """{"id":"z","status":"confirmed","created_at":"2026-09-25T08:00:00Z","subtotal":0,
                "items":[{"name":"Candle","qty":3,"unit":200,"total":0},{"name":"Wick","unit":50,"total":0}]}""",
        )
        val top = topProducts(listOf(o))
        assertEquals(600.0, top.first { it.name == "Candle" }.revenue, 0.0)
        assertEquals(1.0, top.first { it.name == "Wick" }.qty, 0.0)
        assertEquals(50.0, top.first { it.name == "Wick" }.revenue, 0.0)
    }
}
