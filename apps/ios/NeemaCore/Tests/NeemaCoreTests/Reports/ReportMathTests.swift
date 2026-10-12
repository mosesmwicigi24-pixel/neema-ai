import Foundation
import XCTest
@testable import NeemaCore

/// The aggregation maths of ReportsView.tsx, on a fixed clock (Android `ReportMathTest`).
final class ReportMathTests: XCTestCase {
    private var convs: [Conversation] = []
    private var orders: [Order] = []
    private var agents: [Agent] = []
    private let NOW_MS = Int64(ReportsFixtures.NOW.timeIntervalSince1970 * 1000)
    private let NAIROBI = ReportsFixtures.NAIROBI

    override func setUpWithError() throws {
        try super.setUpWithError()
        ReportsFixtures.pinTimeZone()
        convs = try NeemaJSON.decode([Conversation].self, from: "[" + ReportsFixtures.conversations.joined(separator: ",") + "]")
        orders = try NeemaJSON.decode([Order].self, from: "[" + ReportsFixtures.orders.joined(separator: ",") + "]")
        agents = try NeemaJSON.decode([Agent].self, from: Fixtures.agents)
    }

    override func tearDown() {
        ReportsFixtures.restoreTimeZone()
        super.tearDown()
    }

    private func report(_ range: ReportRange, _ from: LocalDay? = nil, _ to: LocalDay? = nil) -> Report {
        ReportsRules.buildReport(convs, orders: orders, agents: agents, range: range, customFrom: from, customTo: to, now: NOW_MS, zone: NAIROBI)
    }

    /// CSS `capitalize` (the web's channel, role and attribution source cells): every word, the rest untouched.
    func testCapitalizeWordsLikeCss() {
        XCTAssertEqual(OverviewRules.capitalizeWords("whatsapp"), "Whatsapp")
        XCTAssertEqual(OverviewRules.capitalizeWords("facebook ads"), "Facebook Ads")
        XCTAssertEqual(OverviewRules.capitalizeWords("click_to_whatsapp"), "Click_to_whatsapp")
        XCTAssertEqual(OverviewRules.capitalizeWords(""), "")
        XCTAssertEqual(OverviewRules.capitalizeWords("Admin"), "Admin")
    }

    func testLast30DaysCountsAndRevenueExcludeCancelled() {
        let r = report(.d30)
        // r8 is 45 days old; r9 has no messages and dates from its creation (4h ago).
        XCTAssertEqual(r.convs.map { $0.id }, ["r1", "r2", "r3", "r4", "r5", "r6", "r7", "r9"])
        XCTAssertEqual(r.humanConvs, 3)
        XCTAssertEqual(r.aiConvs, 4) // "paused" is neither
        XCTAssertEqual(r.orders.map { $0.id }, ["o1", "o2", "o3", "o4", "o5", "o6"])
        // 8000 + 12500 + 18000 + 4800 + 3500 — the cancelled 9600 is not revenue.
        XCTAssertEqual(r.revenue, 46_800.0, accuracy: 0.0)
        XCTAssertEqual(r.pending, 2) // an "open" cart reads as pending (mapOrder)
        XCTAssertEqual(r.confirmed, 1)
        XCTAssertEqual(r.delivered, 2)
        XCTAssertEqual(r.cancelled, 1)
    }

    func testLast7And90Days() {
        let w = report(.d7)
        XCTAssertEqual(w.convs.count, 6)
        XCTAssertEqual(w.orders.map { $0.id }, ["o1", "o2", "o3", "o4", "o5"])
        XCTAssertEqual(w.revenue, 43_300.0, accuracy: 0.0)
        let q = report(.d90)
        XCTAssertEqual(q.convs.count, 9)
        XCTAssertEqual(q.orders.count, 7)
        XCTAssertEqual(q.revenue, 71_800.0, accuracy: 0.0)
    }

    func testCustomRangeIsWholeLocalDaysToInclusive() {
        let r = report(.custom, LocalDay(2026, 9, 20), LocalDay(2026, 9, 22))
        // r4 is on the 22nd — the "to" day, which the web's UTC parse dropped.
        XCTAssertEqual(r.convs.map { $0.id }, ["r4", "r5"])
        XCTAssertEqual(r.orders.map { $0.id }, ["o3", "o4"])
        XCTAssertEqual(r.revenue, 18_000.0, accuracy: 0.0)
        // The chart still shows 14 bars ending on the "to" day.
        XCTAssertEqual(r.convByDay.count, 14)
        XCTAssertEqual(r.convByDay.last?.label, "Tue")
    }

    func testCustomRangeWithOneDateMissingFallsBackTo30Days() {
        XCTAssertEqual(report(.d30).convs, report(.custom, LocalDay(2026, 9, 20), nil).convs)
        XCTAssertEqual(report(.d30).orders, report(.custom, nil, nil).orders)
    }

    func testCustomRangeBackwardsIsEmpty() {
        let r = report(.custom, LocalDay(2026, 9, 22), LocalDay(2026, 9, 20))
        XCTAssertEqual(r.convs.count, 0)
        XCTAssertEqual(r.orders.count, 0)
    }

    func testPerDayBuckets7Days() {
        let r = report(.d7)
        XCTAssertEqual(r.convByDay.map { $0.label }, ["Sat", "Sun", "Mon", "Tue", "Wed", "Thu", "Fri"])
        // Fri: r1 + r9 (created today); Thu r2; Wed r3; Tue r4; Sun r5.
        XCTAssertEqual(r.convByDay.map { $0.value }, [0.0, 1.0, 0.0, 1.0, 1.0, 1.0, 2.0])
        // Revenue per day includes the cancelled order, exactly like the web's orderByDay.
        XCTAssertEqual(r.orderByDay.map { $0.value }, [4800.0, 0.0, 9600.0, 18000.0, 0.0, 12500.0, 8000.0])
    }

    func testPerDayBucketsCountIsCappedAt14() {
        XCTAssertEqual(report(.d30).convByDay.count, 14)
        XCTAssertEqual(report(.d90).orderByDay.count, 14)
        XCTAssertEqual(report(.d90).orderByDay.last?.label, "Fri")
    }

    func testAgentPerformance() {
        let stats = report(.d30).agentStats
        XCTAssertEqual(stats.map { $0.agent.name }, ["Grace Wanjiru", "Moses Mwicigi", "Brian Otieno"])
        XCTAssertEqual(stats.map { $0.handled }, [2, 1, 0])
        // Grace holds James (o3 18000, o6 3500). Her other thread, Samuel's, is a Facebook comment
        // thread with no wa_id — the web's `c.wa_id === o.wa_id` can never tie an order to it.
        XCTAssertEqual(stats.map { $0.revenue }, [21_500.0, 8_000.0, 0.0])
    }

    func testEmptyData() {
        let r = ReportsRules.buildReport([], orders: [], agents: [], range: .d30, customFrom: nil, customTo: nil, now: NOW_MS, zone: NAIROBI)
        XCTAssertEqual(r.revenue, 0.0, accuracy: 0.0)
        XCTAssertEqual(r.convByDay.count, 14)
        XCTAssertTrue(r.convByDay.allSatisfy { $0.value == 0.0 })
        XCTAssertEqual(r.agentStats, [])
    }

    func testCsvHeaderRowsAndQuoting() {
        let csv = ReportsRules.reportCsv(report(.d30).orders)
        XCTAssertEqual(csv, """
            Date,Customer,Amount,Status
            25 Sept 2026,254712345678,8000,confirmed
            24 Sept 2026,254722000111,12500,pending
            22 Sept 2026,254733444555,18000,delivered
            21 Sept 2026,254700111222,9600,cancelled
            19 Sept 2026,254711000999,4800,pending
            15 Sept 2026,254733444555,3500,delivered
            """)
        // GET /admin/orders sends no contact_name (bare OrderEvent rows), so the customer is the
        // bare wa_id, as the web's mapOrder makes it (contact_name ?? wa_id). Should a name ever arrive, a comma in it is quoted.
        var named = report(.d30).orders.first { $0.id == "o4" }!
        named.contactName = "Kariuki, Samuel"
        XCTAssertEqual(ReportsRules.reportCsv([named]), "Date,Customer,Amount,Status\n21 Sept 2026,\"Kariuki, Samuel\",9600,cancelled")
        XCTAssertEqual(ReportsRules.reportCsv([]), "Date,Customer,Amount,Status\n")
        XCTAssertEqual(ReportsRules.csvFileName(.custom), "neema-report-custom.csv")
    }

    func testCsvFieldQuotesOnlyWhenNeeded() {
        XCTAssertEqual(ReportsRules.csvField("plain"), "plain")
        XCTAssertEqual(ReportsRules.csvField("a,b"), "\"a,b\"")
        XCTAssertEqual(ReportsRules.csvField("say \"hi\""), "\"say \"\"hi\"\"\"")
        XCTAssertEqual(ReportsRules.csvField("two\nlines"), "\"two\nlines\"")
    }

    /// The web's mapOrder: contact_name ?? wa_id, so an unnamed buyer reads as the bare number.
    func testUnnamedBuyerIsTheirBareNumberLikeTheWeb() {
        XCTAssertEqual(ReportsRules.reportCustomer(Order(id: "x", waId: "254712345678")), "254712345678")
        XCTAssertEqual(ReportsRules.reportCustomer(Order(id: "x", waId: "254712345678", contactName: "  Kariuki ")), "Kariuki")
        // An empty name is kept by `??`, so displayName falls back to the formatted number.
        XCTAssertEqual(ReportsRules.reportCustomer(Order(id: "x", waId: "254712345678", contactName: "")), "+254 712 345 678")
        XCTAssertEqual(ReportsRules.reportCustomer(Order(id: "x", waId: "")), "Unknown")
    }

    func testPlainNumbersAndRangeKeys() {
        XCTAssertEqual(ReportsRules.plain(1500), "1500")
        XCTAssertEqual(ReportsRules.plain(1500.5), "1500.5")
        XCTAssertEqual(ReportRange.allCases.map { $0.key }, ["7d", "30d", "90d", "custom"])
        XCTAssertEqual(ReportRange.d30.label, "Last 30 days")
        XCTAssertEqual(ReportTab.allCases.map { $0.label }, ["Overview", "Conversations", "Orders", "Agents"])
    }
}
