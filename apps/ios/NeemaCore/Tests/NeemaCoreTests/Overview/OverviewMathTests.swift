import Foundation
import XCTest
@testable import NeemaCore

/// OverviewView.tsx's computations (Android `OverviewMathTest`): API-first headline, fallbacks, feed, charts.
final class OverviewMathTests: XCTestCase {
    private var convs: [Conversation] = []
    private var orders: [Order] = []
    private var agents: [Agent] = []
    private var catalog: [CatalogItem] = []
    private var stats: Stats!
    private let today = LocalDay(2026, 9, 25)
    private let nairobi = ReportsFixtures.NAIROBI

    override func setUpWithError() throws {
        try super.setUpWithError()
        convs = try NeemaJSON.decode([Conversation].self, from: "[" + ReportsFixtures.conversations.joined(separator: ",") + "]")
        orders = try NeemaJSON.decode([Order].self, from: "[" + ReportsFixtures.orders.joined(separator: ",") + "]")
        agents = try NeemaJSON.decode([Agent].self, from: Fixtures.agents)
        catalog = try NeemaJSON.decode([CatalogItem].self, from: ReportsFixtures.catalog)
        stats = try NeemaJSON.decode(Stats.self, from: ReportsFixtures.stats)
    }

    func testHeadlinePrefersServerStats() {
        let h = OverviewRules.headline(stats, convs: convs, agents: agents, orders: orders, catalog: catalog)
        XCTAssertEqual(h.openConvs, 128)
        XCTAssertEqual(h.humanConvs, 9)
        XCTAssertEqual(h.aiConvs, 119)
        XCTAssertEqual(h.activeAgents, 2)
        XCTAssertEqual(h.totalAgents, 3)
        XCTAssertEqual(h.revenue, 1_284_500.0, accuracy: 0.0)
        XCTAssertEqual(h.totalOrders, 284)
        XCTAssertEqual(h.pendingOrders, 21)
        XCTAssertEqual(h.inStockItems, 187)
        XCTAssertEqual(h.totalItems, 214)
    }

    func testHeadlineFallsBackToWhatTheAppHoldsWhenStatsFail() {
        let h = OverviewRules.headline(nil, convs: convs, agents: agents, orders: orders, catalog: catalog)
        XCTAssertEqual(h.openConvs, 8) // r4 is closed
        XCTAssertEqual(h.humanConvs, 3)
        XCTAssertEqual(h.aiConvs, 5)
        XCTAssertEqual(h.activeAgents, 2)
        XCTAssertEqual(h.totalAgents, 3)
        XCTAssertEqual(h.revenue, 71_800.0, accuracy: 0.0) // every order but the cancelled 9,600
        XCTAssertEqual(h.totalOrders, 7)
        XCTAssertEqual(h.pendingOrders, 2)
        XCTAssertEqual(h.deliveredOrders, 3)
        XCTAssertEqual(h.confirmedOrders, 1)
        XCTAssertEqual(h.cancelledOrders, 1)
        XCTAssertEqual(h.inStockItems, 5)
        XCTAssertEqual(h.totalItems, 6)
    }

    func testChannelsFromServerDropEmptyRows() {
        var s = stats!
        s.channelBreakdown.append(ChannelCount(channel: "sms", count: 0, open: 0))
        // In the server's order; "web" is kept here and skipped by the panel (not in CHANNEL_CONFIG).
        XCTAssertEqual(OverviewRules.channelRows(s, convs: convs), [
            ChannelRow("whatsapp", 96, 80), ChannelRow("messenger", 21, 15), ChannelRow("facebook", 70, 22),
            ChannelRow("instagram", 11, 9), ChannelRow("web", 3, 2),
        ])
    }

    func testChannelsFallbackCountsLocalRowsPerKnownChannel() {
        XCTAssertEqual(OverviewRules.channelRows(nil, convs: convs),
                       [ChannelRow("whatsapp", 6, 6), ChannelRow("messenger", 1, 1), ChannelRow("facebook", 1, 1), ChannelRow("instagram", 1, 0)])
        XCTAssertEqual(OverviewRules.channelRows(nil, convs: []), [])
    }

    func testActivityLatestOrdersAndInterceptsNewestFirst() {
        let feed = OverviewRules.activityFeed(orders: orders, human: convs, agents: agents)
        XCTAssertEqual(feed.map { $0.id }, ["order-o1", "conv-r1", "order-o2", "order-o3", "order-o4", "conv-r5", "conv-r6"])
        // Orders carry no contact_name on the wire: mapOrder makes it the wa_id, so the buyer reads as the bare number.
        XCTAssertEqual(feed[0].user, "254712345678")
        XCTAssertEqual(feed[0].target, "KES 8,000")
        XCTAssertEqual(feed[1].user, "Moses Mwicigi")
        XCTAssertEqual(feed[1].action, "intercepted conversation with")
        XCTAssertEqual(feed[1].target, "Fr. Peter Kamau")
        XCTAssertEqual(feed[5].user, "Grace Wanjiru")
    }

    func testActivityUnnamedBuyerShowsTheirNumberAndAnUnknownAgentReadsAnAgent() {
        var o = orders.first { $0.id == "o5" }!
        o.createdAt = ReportsFixtures.ago(1)
        var c = convs.first { $0.id == "r1" }!
        c.assignedAgentId = "gone"
        let feed = OverviewRules.activityFeed(orders: [o], human: [c], agents: agents)
        XCTAssertEqual(feed.first { $0.id == "order-o5" }?.user, "254711000999")
        XCTAssertEqual(feed.first { $0.id == "conv-r1" }?.user, "An agent")
    }

    /// mapConversation() gives a messageless thread its created_at, so the web's feed keeps it.
    func testActivityMessagelessHumanThreadDatesFromCreation() {
        var c = convs.first { $0.id == "r1" }!
        c.lastMessageAt = nil
        c.createdAt = ReportsFixtures.ago(30)
        let feed = OverviewRules.activityFeed(orders: [], human: [c], agents: agents)
        XCTAssertEqual(feed.map { $0.id }, ["conv-r1"])
        XCTAssertEqual(feed.first?.at, c.createdAt)
        // Neither date: dropped, as `c.last_message_at` is then undefined on the web.
        var none = c
        none.createdAt = nil
        XCTAssertEqual(OverviewRules.activityFeed(orders: [], human: [none], agents: agents), [])
    }

    /// `item.qty || item.quantity || 1`: only a zero (missing) quantity counts as one.
    func testTopProductsOnlyZeroQtyCountsAsOne() throws {
        let o = try NeemaJSON.decode(Order.self, from: """
            {"id":"z","status":"confirmed","created_at":"2026-09-25T08:00:00Z","subtotal":0,
             "items":[{"name":"Refund line","qty":-2,"unit":100,"total":0}]}
            """)
        let top = OverviewRules.topProducts([o])
        XCTAssertEqual(top.count, 1)
        XCTAssertEqual(top.first?.qty ?? 0, -2.0, accuracy: 0.0)
    }

    func testActivityIsAtMostFourOrdersAndThreeIntercepts() throws {
        let row = ReportsFixtures.orders[0]
        let many = try (1...10).map { i -> Order in
            let text = row.replacingOccurrences(of: #""id":"o\d+""#, with: "\"id\":\"x\(i)\"", options: .regularExpression)
            XCTAssertNotEqual(text, row)
            return try NeemaJSON.decode(Order.self, from: text)
        }
        XCTAssertEqual(OverviewRules.activityFeed(orders: many, human: convs, agents: agents).count, 4 + 3)
    }

    func testSevenDayRevenueExcludesCancelledAndMarksToday() {
        let bars = OverviewRules.sevenDayRevenue(orders, today: today, zone: nairobi)
        XCTAssertEqual(bars.map { $0.label }, ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"])
        XCTAssertEqual(bars.map { $0.value }, [4800.0, 0.0, 0.0, 18000.0, 0.0, 12500.0, 8000.0])
        XCTAssertEqual(bars.map { $0.isToday }, [false, false, false, false, false, false, true])
        XCTAssertTrue(OverviewRules.sevenDayRevenue([], today: today, zone: nairobi).allSatisfy { $0.value == 0.0 })
    }

    func testTopProductsByRevenueExcludingCancelled() {
        let top = OverviewRules.topProducts(orders)
        XCTAssertEqual(top.map { $0.name }, ["Clergy Shirt", "Alb — White, M", "Cassock — Purple, L", "Clergy Shirt — Black, 16 inch", "Stole — Green"])
        // "Clergy Shirt" is two orders (3,500 + 25,000) merged by name. The agent's own order (o2)
        // stores cart lines priced by `unit_price` only; the web counts those as 0, but the core
        // OrderItemsSerializer normalises them, so the cassock (12,500) now ranks third.
        XCTAssertEqual(top.map { $0.revenue }, [28500.0, 18000.0, 12500.0, 7000.0, 4800.0])
        // Stole: the cancelled pair is not counted, the single pending one is.
        XCTAssertEqual(top.first { $0.name == "Stole — Green" }?.qty ?? 0, 1.0, accuracy: 0.0)
        XCTAssertEqual(top.first { $0.name == "Stole — Green" }?.revenue ?? 0, 4800.0, accuracy: 0.0)
    }

    func testTopProductsItemWithoutTotalUsesUnitTimesQtyAndMissingQtyCountsOne() throws {
        let o = try NeemaJSON.decode(Order.self, from: """
            {"id":"z","status":"confirmed","created_at":"2026-09-25T08:00:00Z","subtotal":0,
             "items":[{"name":"Candle","qty":3,"unit":200,"total":0},{"name":"Wick","unit":50,"total":0}]}
            """)
        let top = OverviewRules.topProducts([o])
        XCTAssertEqual(top.first { $0.name == "Candle" }?.revenue ?? 0, 600.0, accuracy: 0.0)
        XCTAssertEqual(top.first { $0.name == "Wick" }?.qty ?? 0, 1.0, accuracy: 0.0)
        XCTAssertEqual(top.first { $0.name == "Wick" }?.revenue ?? 0, 50.0, accuracy: 0.0)
    }

    func testCapitalizeWordsLikeCss() {
        XCTAssertEqual(OverviewRules.capitalizeWords("facebook post"), "Facebook Post")
        XCTAssertEqual(OverviewRules.capitalizeWords("tikTok ad"), "TikTok Ad")
        XCTAssertEqual(OverviewRules.capitalizeWords(""), "")
    }

    func testLocalDayArithmeticAndLabels() {
        XCTAssertEqual(LocalDay(2026, 9, 25).weekdayShort, "Fri")
        XCTAssertEqual(LocalDay(2026, 9, 25).minusDays(6), LocalDay(2026, 9, 19))
        XCTAssertEqual(LocalDay(2026, 1, 1).minusDays(1), LocalDay(2025, 12, 31))
        XCTAssertEqual(LocalDay(2026, 9, 25).daysSince(LocalDay(2026, 9, 1)), 24)
        XCTAssertEqual(LocalDay.parse("2026-09-25"), LocalDay(2026, 9, 25))
        XCTAssertNil(LocalDay.parse("2026-02-30"))
        XCTAssertNil(LocalDay.parse("yesterday"))
        XCTAssertEqual(LocalDay(2026, 9, 5).description, "2026-09-05")
        // 23:30 UTC on the 24th is already the 25th in Nairobi (UTC+3).
        XCTAssertEqual(LocalDay.of("2026-09-24T23:30:00Z", zone: nairobi), LocalDay(2026, 9, 25))
        XCTAssertEqual(LocalDay.of("2026-09-24T23:30:00Z", zone: TimeZone(identifier: "UTC")!), LocalDay(2026, 9, 24))
        XCTAssertTrue(LocalDay(2026, 9, 24) < LocalDay(2026, 9, 25))
    }
}
