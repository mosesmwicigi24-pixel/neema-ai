import Foundation
import XCTest
@testable import NeemaCore

/// OrdersView's behaviour against the fake API: status moves, filters, paging, hub linkage (Android `OrdersBehaviourTest`).
final class OrdersBehaviourTests: OrdersTestCase {
    private func make(_ id: String, _ status: String = "open", name: String? = "Fr. Peter Kamau", waId: String = "254712345678") -> Order {
        Order(id: id, waId: waId, rawStatus: status, contactName: name)
    }

    func testStatusMovePatchesOnlyTheStatusThenRefetchesAndClosesTheSheet() async {
        let vm = await vm()
        vm.select(order("o2"))
        let getsBefore = gets()
        vm.updateStatus(id: "o2", status: "confirmed")
        await drain()
        // JSON.stringify drops the web's undefined payment/fulfilment fields: only status goes.
        XCTAssertEqual(fake.bodies("PATCH", "/admin/orders/o2"), [["status": .string("confirmed")]])
        XCTAssertGreaterThan(gets(), getsBefore)
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertNil(vm.ui.updating)
        XCTAssertEqual(lastToast()?.message, "Order marked as confirmed")
    }

    func testFailedStatusMoveToastsAndKeepsTheSheetOpen() async {
        fake.on("PATCH", "/admin/orders/.*", code: 500, body: #"{"detail":"hub unreachable"}"#)
        let vm = await vm()
        vm.select(order("o1"))
        vm.updateStatus(id: "o1", status: "delivered")
        await drain()
        XCTAssertEqual(vm.ui.selectedId, "o1")
        XCTAssertNil(vm.ui.updating)
        let t = lastToast()
        XCTAssertEqual(t?.type, .error)
        // The web's copy, plus the server's reason.
        XCTAssertEqual(t?.message, "Failed to update order — hub unreachable")
    }

    func testAllowedTransitionsMatchTheWeb() {
        XCTAssertEqual(OrderUi.STATUS_ACTIONS[make("a", "open").status], ["confirmed", "cancelled"])
        XCTAssertEqual(OrderUi.STATUS_ACTIONS["pending"], ["confirmed", "cancelled"])
        XCTAssertEqual(OrderUi.STATUS_ACTIONS["confirmed"], ["delivered", "cancelled"])
        XCTAssertEqual(OrderUi.STATUS_ACTIONS["delivered"], [])
        XCTAssertEqual(OrderUi.STATUS_ACTIONS["cancelled"], [])
        XCTAssertEqual(OrderUi.actions(from: "shipped"), [])
    }

    func testOpenCartsCountAsPending() { XCTAssertEqual(make("a", "open").status, "pending") }

    func testFilterBySearchAndStatus() {
        let list = [
            make("ORD-1", "open", name: "Fr. Peter Kamau", waId: "254712345678"),
            make("ORD-2", "confirmed", name: "Rev. Mary Achieng", waId: "254722000111"),
            make("abc-3", "delivered", name: nil, waId: "255754333222"),
        ]
        XCTAssertEqual(OrderUi.filterOrders(list, filter: "pending", search: "").map { $0.id }, ["ORD-1"])
        XCTAssertEqual(OrderUi.filterOrders(list, filter: "all", search: "MARY").map { $0.id }, ["ORD-2"])
        XCTAssertEqual(OrderUi.filterOrders(list, filter: "all", search: "722000").map { $0.id }, ["ORD-2"])
        XCTAssertEqual(OrderUi.filterOrders(list, filter: "all", search: "ord-").map { $0.id }, ["ORD-1", "ORD-2"])
        // A nameless order is searched by its wa_id, as contact_name falls back to it.
        XCTAssertEqual(OrderUi.filterOrders(list, filter: "all", search: "2557543").map { $0.id }, ["abc-3"])
        XCTAssertEqual(OrderUi.filterOrders(list, filter: "confirmed", search: "peter").map { $0.id }, [])
    }

    func testFilterAndSearchResetThePage() async {
        let vm = await vm()
        vm.setPage(3); vm.setFilter("confirmed"); XCTAssertEqual(vm.ui.page, 1)
        vm.setPage(2); vm.setSearch("x"); XCTAssertEqual(vm.ui.page, 1)
        vm.toggleFilter("confirmed"); XCTAssertEqual(vm.ui.filter, "all")
        vm.toggleFilter("pending"); XCTAssertEqual(vm.ui.filter, "pending")
    }

    func testPagerWindowsFiveAroundTheCurrentPage() {
        XCTAssertEqual(OrderUi.pageWindow(page: 2, totalPages: 3), [1, 2, 3])
        XCTAssertEqual(OrderUi.pageWindow(page: 1, totalPages: 7), [1, 2, 3, 4, 5])
        XCTAssertEqual(OrderUi.pageWindow(page: 3, totalPages: 7), [1, 2, 3, 4, 5])
        XCTAssertEqual(OrderUi.pageWindow(page: 4, totalPages: 7), [2, 3, 4, 5, 6])
        XCTAssertEqual(OrderUi.pageWindow(page: 6, totalPages: 7), [3, 4, 5, 6, 7])
        XCTAssertEqual(OrderUi.pageWindow(page: 7, totalPages: 7), [3, 4, 5, 6, 7])
    }

    func testHubLinkageFollowsTheHubsOwnState() {
        var linked = make("a")
        linked.hubOrderId = 1042; linked.hubPublicToken = "tok"; linked.hubStatus = "processing"
        XCTAssertEqual(OrderUi.hubOrderHref(linked), "https://hub.bethanyhouse.co.ke/handoff/orders/1042#v=tok")
        var noToken = linked; noToken.hubPublicToken = nil
        XCTAssertEqual(OrderUi.hubOrderHref(noToken), "https://hub.bethanyhouse.co.ke/handoff/orders/1042")
        XCTAssertNil(OrderUi.hubOrderHref(make("b")))
        XCTAssertEqual(OrderUi.hubMeta(linked)?.label, "Confirmed")
        var shipped = linked; shipped.hubStatus = "SHIPPED"
        XCTAssertEqual(OrderUi.hubMeta(shipped)?.label, "Shipped")
        var delivered = linked; delivered.hubStatus = "delivered"
        XCTAssertEqual(OrderUi.hubMeta(delivered)?.label, "Completed")
        var voided = linked; voided.hubStatus = "voided"
        XCTAssertEqual(OrderUi.hubMeta(voided)?.label, "Cancelled")
        var hold = linked; hold.hubStatus = "on-hold"
        XCTAssertNil(OrderUi.hubMeta(hold))
        // Never pushed: the hub has no say, whatever the row carries.
        var unpushed = make("c"); unpushed.hubStatus = "completed"
        XCTAssertNil(OrderUi.hubMeta(unpushed))
    }

    func testQuietRefreshEndsAtOnceWithOneRequest() async {
        let vm = await vm()
        let before = gets()
        vm.refresh()
        await drain()
        XCTAssertFalse(vm.ui.refreshing, "the spinner must stop when nothing changed")
        XCTAssertEqual(gets(), before + 1)
    }

    func testRefreshThatFindsNewOrdersHandsThemToTheDashboard() async {
        let vm = await vm()
        fake.on("GET", "/admin/orders", body: SalesFixtures.ordersJson(Array(SalesFixtures.orders.prefix(2))))
        vm.refresh()
        await drain()
        XCTAssertFalse(vm.ui.refreshing)
        XCTAssertEqual(orders.map { $0.id }, ["o1", "o2"])
    }

    func testEmptyShopFinishesLoading() async {
        fake.on("GET", "/admin/orders", body: "[]")
        // No cached snapshot to paint from: this is a genuinely empty first load.
        let h = await signedIn()
        XCTAssertTrue(h.orders.value.isEmpty)
        let vm = await vm(h)
        XCTAssertFalse(vm.ui.initialLoading, "an empty list must read 'No orders found', not spin")
        XCTAssertNil(vm.ui.loadError)
    }

    func testRefreshThatChangesTheListStillCostsOneRequest() async {
        let vm = await vm()
        fake.on("GET", "/admin/orders", body: SalesFixtures.ordersJson(Array(SalesFixtures.orders.prefix(1))))
        let before = gets()
        vm.refresh()
        await drain()
        // The host's refreshOrders() is the one fetch — no second request to hand the list over.
        XCTAssertEqual(gets(), before + 1)
        XCTAssertEqual(orders.map { $0.id }, ["o1"])
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testFailedRefreshStopsTheSpinnerAndKeepsTheList() async {
        let vm = await vm()
        let shown = orders
        fake.on("GET", "/admin/orders", code: 503, body: #"{"detail":"down"}"#)
        vm.refresh()
        await drain()
        XCTAssertFalse(vm.ui.refreshing)
        XCTAssertEqual(orders, shown)
    }

    func testFailedFirstLoadStillEndsTheLoadingState() async {
        fake.on("GET", "/admin/orders", code: 500, body: #"{"detail":"boom"}"#)
        let h = await signedIn()
        let vm = await vm(h)
        XCTAssertFalse(vm.ui.initialLoading)
        XCTAssertNotNil(vm.ui.loadError)
    }

    /// The nav badge counts what is still pending (open carts included).
    func testPendingBadgeCountsOpenCartsToo() {
        XCTAssertEqual(host.feed?.pendingOrders, 3) // o2 (open), o5 (open cart), o6 (pending)
    }
}
