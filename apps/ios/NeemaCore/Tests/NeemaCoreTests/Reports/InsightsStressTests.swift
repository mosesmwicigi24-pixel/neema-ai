import Foundation
import XCTest
@testable import NeemaCore

/// Analytics and the catalogue under a real shop's load (the rows of Android
/// `InsightsStressTest` not already in `ReportsStressTests`): 5,000 orders
/// through the analytics maths, 200 socket frames in a burst over the 30 s
/// poll, and a 2,000-product catalogue through the index, the screen and the
/// grid. Time bounds are generous (an unoptimised Linux debug build) so they
/// only catch an O(n^2) slip.
final class InsightsStressTests: OverviewTestCase {
    private static let NAIROBI = ReportsFixtures.NAIROBI
    private var catalogs: [CatalogViewModel] = []

    override func tearDown() async throws {
        for c in catalogs { c.close() }
        catalogs = []
        try await super.tearDown()
    }

    private func ms(_ block: () -> Void) -> Double {
        let t = DispatchTime.now().uptimeNanoseconds
        block()
        return Double(DispatchTime.now().uptimeNanoseconds - t) / 1e6
    }

    // ---- A 2,000-product catalogue (Android `InsightsStressFixtures.catalog`) ----

    private static let CATEGORIES = [
        "Anointing Oil", "Communion Wafers", "Communion Cups", "Prefilled Cups", "Communion Wine",
        "Communion Trays", "Communion Accessories", "Clergy Apparel", "Clergy Vestments", "",
    ]

    private static func catalog(_ n: Int = 2_000) -> [CatalogItem] {
        (0..<n).map { i in
            let cat = CATEGORIES[i % CATEGORIES.count]
            return CatalogItem(
                hubProductId: Int64(10_000 + i), availableQty: i % 9 != 0 ? Double(i % 300) : nil,
                sku: "SKU-" + String(format: "%05d", i), name: "Product \(i) \(cat)".trimmingCharacters(in: .whitespaces),
                aliases: i % 3 == 0 ? ["alias\(i)", "kitu \(i)"] : [],
                price: 100.0 * Double(1 + i % 90), rawCategory: cat.isEmpty ? nil : cat,
                inStock: i % 9 != 0, imageUrl: "https://hub.test/img/\(i).webp"
            )
        }
    }

    private let products: [CatalogItem] = InsightsStressTests.catalog()

    // ---- Analytics ----

    func testAnalyticsDerivationsOverFiveThousandOrdersAreExactAndFast() {
        let many = InsightsStressFixtures.orders(5_000)
        let convs = InsightsStressFixtures.conversations()
        let agents = InsightsStressFixtures.agents()
        let human = convs.filter { $0.interceptMode == "human" }
        let today = LocalDay(2026, 9, 25)
        for _ in 0..<2 {
            _ = OverviewRules.activityFeed(orders: many, human: human, agents: agents)
            _ = OverviewRules.sevenDayRevenue(many, today: today, zone: Self.NAIROBI)
            _ = OverviewRules.topProducts(many)
        }
        let t = ms {
            _ = OverviewRules.activityFeed(orders: many, human: human, agents: agents)
            _ = OverviewRules.sevenDayRevenue(many, today: today, zone: Self.NAIROBI)
            _ = OverviewRules.topProducts(many)
        }
        XCTAssertLessThan(t, 3_000, "analytics derivations took \(t)ms")
        // The newest four orders and three intercepts, newest first, as the web picks them.
        let feed = OverviewRules.activityFeed(orders: many, human: human, agents: agents)
        XCTAssertEqual(feed.count, 7)
        let newestOrders = many.map { ($0, Fmt.millis($0.createdAt) ?? 0) }.sorted { $0.1 > $1.1 }.prefix(4).map { "order-\($0.0.id)" }
        XCTAssertEqual(feed.filter { $0.id.hasPrefix("order-") }.map { $0.id }, newestOrders)
        let times = feed.map { Fmt.millis($0.at)! }
        XCTAssertEqual(times, times.sorted(by: >))
    }

    func testTheThirtySecondPollNeverStacksAndStopsInTheBackground() async {
        host.connectLive()
        await drain()
        _ = await vm()
        func stats() -> Int { reads("/admin/stats") }
        XCTAssertEqual(stats(), 1)

        // Ten minutes on screen: exactly one read per 30 s tick.
        await advance(10 * 60_000 + 1)
        XCTAssertEqual(stats(), 1 + 20)

        // A burst of 200 frames (intercepts and alerts) is ONE refetch, not 200.
        for i in 0..<100 {
            host.sockets.last.frame("{\"type\":\"intercept_changed\",\"conversationId\":\"c\(i)\",\"mode\":\"human\",\"eventKind\":\"intercept\"}")
            host.sockets.last.frame("{\"event\":\"notification\",\"type\":\"intercept\",\"title\":\"Picked up \(i)\",\"body\":\"\"}")
        }
        await advance(ScreenLife.EVENT_WINDOW_MS + 1)
        XCTAssertEqual(stats(), 1 + 20 + 1)

        // The app goes to the background: nothing polls, however long.
        host.foreground.update(false)
        await advance(30 * 60_000)
        XCTAssertEqual(stats(), 1 + 20 + 1)

        // Back in front: one catch-up, then the 30 s rhythm again.
        host.foreground.update(true)
        await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(stats(), 1 + 20 + 1 + 1)
        await advance(30_000)
        XCTAssertEqual(stats(), 1 + 20 + 1 + 2)
    }

    // ---- Catalog ----

    func testTheIndexedSearchAnswersExactlyTheWebFilterOverTwoThousandProducts() {
        let ix = CatalogIndex(products)
        for filter in ["all", "Clergy Apparel", "General", "Communion Wine"] {
            for q in ["", "product 1", "SKU-0199", "KITU", "alias33", "zzz", "wine", "1"] {
                XCTAssertEqual(ix.filter(filter, q).map { $0.id }, CatalogRules.filter(products, filter: filter, search: q).map { $0.id }, "\(filter) / \(q)")
            }
        }
        var seen: Set<String> = []
        let distinct = products.map { $0.category }.filter { !$0.isEmpty && seen.insert($0).inserted }
        XCTAssertEqual(ix.categories, distinct)
    }

    func testTypingIntoTheSearchOverTwoThousandProductsStaysFast() {
        let ix = CatalogIndex(products)
        let typed = Array("product 19 clergy")
        func sweep() { for i in typed.indices { _ = ix.filter("all", String(typed[0...i])) } }
        for _ in 0..<3 { sweep() }
        let t = ms { for _ in 0..<5 { sweep() } }
        // 85 keystrokes' worth of filtering over 2,000 products.
        XCTAssertLessThan(t, 4_000, "search took \(t)ms")
    }

    func testTheCatalogViewModelFiltersTheLiveCatalogue() async {
        host.catalog.value = products
        let vm = CatalogViewModel(host: host, sleep: host.clock.sleeper)
        catalogs.append(vm)
        await drain()
        XCTAssertEqual(vm.view.filtered.count, 2_000)
        XCTAssertEqual(vm.view.inStock, products.filter { $0.inStock }.count)
        XCTAssertEqual(vm.view.outStock, products.filter { !$0.inStock }.count)
        vm.setSearch("sku-0019")
        XCTAssertEqual(vm.view.filtered.map { $0.id }, CatalogRules.filter(products, filter: "all", search: "sku-0019").map { $0.id })
        vm.setFilter("Clergy Apparel"); vm.setSearch("")
        XCTAssertEqual(vm.view.filtered.count, products.filter { $0.category == "Clergy Apparel" }.count)
    }

    func testGridRowKeysAreUniqueAndStableAcrossAPoll() {
        let grid = CatalogRules.gridRows(products, cols: 3)
        XCTAssertEqual(grid.rows.count, 667)
        XCTAssertEqual(Set(grid.keys).count, grid.rows.count)
        // One product's stock changes on the next poll: every row keeps its key.
        let polled = products.enumerated().map { i, p -> CatalogItem in
            guard i == 700 else { return p }
            var c = p; c.inStock.toggle(); return c
        }
        XCTAssertEqual(CatalogRules.gridRows(polled, cols: 3).keys, grid.keys)
        // A hub row and a local row sharing an id still get distinct keys.
        var twin = products[0]; twin.name = "local twin"
        let dup = [products[0], twin] + products.dropFirst().prefix(4)
        let g = CatalogRules.gridRows(dup, cols: 1)
        XCTAssertEqual(Set(g.keys).count, g.rows.count)
    }
}
