import Foundation
import XCTest
@testable import NeemaCore

/// Orders under a busy shop's load (Android `OrdersStressTest`): a thousand
/// orders through the real model and the pure functions the screen derives
/// its figures with, plus the read de-duplication every sales screen shares.
final class OrdersStressTests: OrdersTestCase {
    override func setUp() async throws {
        try await super.setUp()
        SalesStressFixtures.install(fake)
        host = await signedIn()
    }

    private func ms(_ block: () -> Void) -> Double {
        let t = DispatchTime.now().uptimeNanoseconds
        block()
        return Double(DispatchTime.now().uptimeNanoseconds - t) / 1e6
    }

    func testAThousandOrdersCountAndSumExactlyInOnePass() async {
        _ = await vm()
        XCTAssertEqual(orders.count, 1_000)
        let stats = OrderUi.orderStats(orders)
        // The web's per-card filters, done the slow way, must agree to the shilling.
        for s in OrderUi.ORDER_STATUSES {
            XCTAssertEqual(stats.counts[s], orders.filter { $0.status == s }.count, s)
            XCTAssertEqual(stats.revenueBy[s]!, orders.filter { $0.status == s }.reduce(0) { $0 + $1.amount }, accuracy: 0.001, s)
        }
        XCTAssertEqual(stats.counts["pending"], 250)
        XCTAssertEqual(stats.revenue, orders.filter { $0.status != "cancelled" }.reduce(0) { $0 + $1.amount }, accuracy: 0.001)
    }

    func testFilterSearchAndPagingHoldAtAThousand() async {
        XCTAssertEqual(OrderUi.filterOrders(orders, filter: "confirmed", search: "").count, 250)
        // A phone number finds its order among a thousand (and its id finds it too).
        let wa = SalesStressFixtures.waId(637)
        XCTAssertTrue(OrderUi.filterOrders(orders, filter: "all", search: wa).contains { $0.id == SalesStressFixtures.orderId(637) })
        XCTAssertEqual(OrderUi.filterOrders(orders, filter: "all", search: SalesStressFixtures.orderId(637)).map { $0.id }, [SalesStressFixtures.orderId(637)])
        // 1,000 rows are 67 pages of 15; the last holds 10; a page is never more than 15 rows.
        let pages = (orders.count + 14) / 15
        XCTAssertEqual(pages, 67)
        XCTAssertEqual(OrderUi.pageOf(orders, page: pages, size: 15).count, 10)
        XCTAssertEqual(OrderUi.pageOf(orders, page: 2, size: 15).map { $0.id }, orders[15..<30].map { $0.id })
        XCTAssertTrue((1...pages).allSatisfy { OrderUi.pageOf(orders, page: $0, size: 15).count <= 15 })
        XCTAssertTrue(OrderUi.pageOf(orders, page: pages + 3, size: 15).isEmpty, "past the end is empty, never a crash")
    }

    func testDerivingFiveThousandOrdersIsFast() async {
        let base = orders
        var many: [Order] = []
        for k in 0..<5 { for o in base { var c = o; c = Order(id: "\(o.id)-\(k)", waId: o.waId, items: o.items, subtotal: o.subtotal, rawStatus: o.rawStatus, channel: o.channel, createdAt: o.createdAt); many.append(c) } }
        XCTAssertEqual(many.count, 5_000)
        for _ in 0..<3 { _ = OrderUi.orderStats(many); _ = OrderUi.filterOrders(many, filter: "pending", search: "2547") } // warm up
        let t = ms {
            _ = OrderUi.orderStats(many)
            let f = OrderUi.filterOrders(many, filter: "all", search: "clergy")
            _ = OrderUi.pageOf(f, page: 3, size: 15)
            _ = OrderUi.filterOrders(many, filter: "delivered", search: "2547100")
        }
        // Android budgets 200 ms on the JVM; an unoptimised Linux debug build of Swift gets the same order of magnitude.
        XCTAssertLessThan(t, 400, "5,000 orders derived in \(t)ms (budget 400)")
    }

    /// A pull, a catch-up (the socket came back) and a second pull pile up
    /// while the list is still on the wire (a slow 3G link): one read runs,
    /// the catch-up follows it — never two at once, never three.
    func testPilingRefreshesShareOneReadOnTheWire() async {
        let vm = await vm()
        let before = gets()
        let hold = fake.hang("GET", "/admin/orders")
        vm.refresh()
        await drain()
        XCTAssertTrue(vm.ui.refreshing)
        vm.life.catchUpNow(); await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        vm.refresh() // ignored: already refreshing
        await drain()
        XCTAssertEqual(hold.waiting, 1, "only the first read is on the wire")
        hold.release()
        // Two thousand-order answers decode one after the other: wait for both, not a fixed moment.
        _ = await eventually(timeout: 15) { !vm.ui.refreshing && !self.host.feed!.reading }
        await drain()
        XCTAssertFalse(vm.ui.refreshing)
        XCTAssertEqual(gets(), before + 2, "the running read plus one that follows it")
        XCTAssertEqual(orders.count, 1_000)
    }

    /// Catch-ups kicked again and again during a slow read queue behind it one at a time — they never stack up on the wire.
    func testRepeatedCatchUpsNeverOverlap() async {
        let vm = await vm()
        let before = gets()
        let hold = fake.hang("GET", "/admin/orders")
        vm.refresh()
        await drain()
        for _ in 0..<5 { vm.life.catchUpNow(); await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1) }
        XCTAssertEqual(hold.waiting, 1, "one read on the wire, whatever piles up")
        hold.release()
        // Two thousand-order answers decode one after the other: wait for both, not a fixed moment.
        _ = await eventually(timeout: 15) { !vm.ui.refreshing && !self.host.feed!.reading }
        await drain()
        // The Coalescer queues each kick that lands during a run behind it (one at a time), so these follow one by one.
        XCTAssertLessThanOrEqual(gets() - before, 6)
        XCTAssertFalse(vm.ui.refreshing)
    }

    // The 4-up status cards break words at large text: 2-up (or 1-up) instead.
    func testStatusCardsGoTwoUpAtLargeTextOnATablet() {
        XCTAssertEqual(OrderUi.statusColumns(width: 900, gutter: 24, fontScale: 1), 4, "tablet portrait, default text")
        XCTAssertEqual(OrderUi.statusColumns(width: 900, gutter: 24, fontScale: 1.3), 4, "tablet portrait at 130%")
        XCTAssertEqual(OrderUi.statusColumns(width: 900, gutter: 24, fontScale: 2), 2, "tablet portrait at 200%: \"Confirmed\" would break")
        XCTAssertEqual(OrderUi.statusColumns(width: 1280, gutter: 24, fontScale: 2), 4, "tablet landscape at 200%")
        XCTAssertEqual(OrderUi.statusColumns(width: 600, gutter: 24, fontScale: 1), 4, "foldable")
        XCTAssertEqual(OrderUi.statusColumns(width: 600, gutter: 24, fontScale: 1.3), 2, "foldable at 130%")
        XCTAssertEqual(OrderUi.statusColumns(width: 411, gutter: 16, fontScale: 1), 2, "phone")
        XCTAssertEqual(OrderUi.statusColumns(width: 411, gutter: 16, fontScale: 2), 1, "phone at 200%")
    }
}

/// `SingleFlight` on its own: the contract every sales read relies on (Android `SingleFlightTest`; the sharing case is in FlowsTests).
final class SingleFlightSalesTests: XCTestCase {
    func testAFailedReadFailsItsCallersButNotTheNextRead() async {
        let n = Ref(0)
        let flight = SingleFlight<Int> {
            n.mutate { $0 += 1 }
            if n.value == 1 { throw PlainError("offline") }
            return n.value
        }
        do { _ = try await flight.run(); XCTFail("the first read fails") } catch { XCTAssertEqual((error as? PlainError)?.message, "offline") }
        let second = try? await flight.run()
        XCTAssertEqual(second, 2)
        XCTAssertFalse(flight.inFlight)
    }
}
