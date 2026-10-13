import Foundation
import XCTest
@testable import NeemaCore

/// The Orders screen on a bad network (Android `OrdersNetworkTest`): the list
/// (first load, pull-to-refresh, cached data) and the status change from the
/// detail sheet, under offline, timeouts, lost answers, 401/404/5xx, HTML
/// pages, garbage and double taps.
final class OrdersNetworkTests: OrdersTestCase {
    // ── The list ────────────────────────────────────────────────────────────

    func testOfflineFirstLoadShowsWhyAndRetryLoadsIt() async {
        fake.failOffline("GET", "/admin/orders")
        let h = await signedIn()
        let vm = await vm(h)
        XCTAssertFalse(vm.ui.initialLoading)
        XCTAssertTrue(h.orders.value.isEmpty)
        XCTAssertEqual(vm.ui.loadError, "No connection — check your internet and try again")
        // Back online.
        SalesFixtures.install(fake)
        vm.retry()
        await drain()
        XCTAssertFalse(vm.ui.initialLoading)
        XCTAssertEqual(h.orders.value.count, 6)
        XCTAssertNil(vm.ui.loadError)
    }

    func testAFailedRefreshKeepsTheCachedListAndSaysWhy() async {
        let vm = await vm()
        let shown = orders
        fake.htmlPage("GET", "/admin/orders", code: 503)
        vm.refresh()
        await drain()
        XCTAssertFalse(vm.ui.refreshing)
        XCTAssertEqual(orders, shown)
        XCTAssertEqual(vm.ui.loadError, "The server is unavailable right now — try again shortly")
        // The next good read clears it.
        SalesFixtures.install(fake)
        vm.refresh()
        await drain()
        XCTAssertNil(vm.ui.loadError)
    }

    func testTimeoutAndGarbageEachSayTheirOwnThing() async {
        let vm = await vm()
        fake.failTimeout("GET", "/admin/orders")
        vm.refresh(); await drain()
        XCTAssertEqual(vm.ui.loadError, "The server took too long to answer — try again")
        fake.on("GET", "/admin/orders", body: #"[{"id":"o1","wa_id":""#)
        vm.refresh(); await drain()
        XCTAssertEqual(vm.ui.loadError, "The server sent an answer the app couldn't read")
        fake.on("GET", "/admin/orders", code: 429, body: #"{"detail":"Too Many Requests"}"#)
        vm.refresh(); await drain()
        XCTAssertEqual(vm.ui.loadError, "Too many requests — wait a moment and try again")
    }

    /// A good read by the feed itself (its poll, an order alert) clears the banner too.
    func testTheFeedsOwnGoodReadClearsTheError() async {
        let vm = await vm()
        fake.on("GET", "/admin/orders", code: 500, body: "{}")
        vm.refresh(); await drain()
        XCTAssertNotNil(vm.ui.loadError)
        SalesFixtures.install(fake)
        host.feed!.refetchOrders()
        await drain()
        XCTAssertNil(vm.ui.loadError)
    }

    // ── Status change ───────────────────────────────────────────────────────

    func testATimeoutThatLandedIsReportedAsDone() async {
        let fake = self.fake!
        let landed = listWith("o2", "confirmed")
        fake.failTimeout("PATCH", "/admin/orders/o2") { _ in fake.on("GET", "/admin/orders", body: landed) }
        let vm = await vm()
        vm.select(order("o2"))
        vm.updateStatus(id: "o2", status: "confirmed")
        await finishUpdate(vm)
        XCTAssertEqual(lastToast()?.message, "Order marked as confirmed")
        XCTAssertTrue(errors.isEmpty)
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertEqual(order("o2").status, "confirmed")
    }

    func testATimeoutThatDidNotLandSaysNotUpdatedAndKeepsTheSheet() async {
        fake.failTimeout("PATCH", "/admin/orders/o2")
        let vm = await vm()
        vm.select(order("o2"))
        vm.updateStatus(id: "o2", status: "confirmed")
        await finishUpdate(vm)
        XCTAssertEqual(errors.last, "Order not updated — the server took too long to answer — try again")
        XCTAssertEqual(vm.ui.selectedId, "o2")
        XCTAssertNil(vm.ui.updating)
    }

    func testWhenNothingCanBeReadItSaysItMayNotHaveUpdated() async {
        let vm = await vm()
        vm.select(order("o2"))
        fake.failDropped("PATCH", "/admin/orders/o2")
        fake.failOffline("GET", "/admin/orders")
        vm.updateStatus(id: "o2", status: "confirmed")
        await finishUpdate(vm)
        XCTAssertEqual(errors.last, "No answer from the server — the order may not have updated. Pull down to check.")
        XCTAssertEqual(vm.ui.selectedId, "o2")
    }

    func testOfflineIsPlainlyNotUpdated() async {
        fake.failOffline("PATCH", "/admin/orders/.*")
        let vm = await vm()
        vm.select(order("o1"))
        let reads = gets()
        vm.updateStatus(id: "o1", status: "delivered")
        await finishUpdate(vm)
        XCTAssertEqual(errors.last, "Failed to update order — no connection — check your internet and try again")
        XCTAssertEqual(gets(), reads, "nothing reached the server: no reconcile read")
        XCTAssertEqual(vm.ui.selectedId, "o1")
    }

    func testADeletedOrderLeavesTheListAndTheSheetCloses() async {
        fake.on("PATCH", "/admin/orders/o2", code: 404, body: #"{"detail":"Order not found"}"#)
        let vm = await vm()
        vm.select(order("o2"))
        fake.on("GET", "/admin/orders", body: SalesFixtures.ordersJson(SalesFixtures.orders.filter { !$0.contains("\"id\":\"o2\"") }))
        vm.updateStatus(id: "o2", status: "confirmed")
        await finishUpdate(vm)
        XCTAssertEqual(errors.last, "This order no longer exists — it may have been deleted")
        XCTAssertNil(vm.ui.selectedId)
        XCTAssertFalse(orders.contains { $0.id == "o2" })
    }

    func testServerErrorsNeverShowHtml() async {
        let vm = await vm()
        vm.select(order("o1"))
        fake.on("PATCH", "/admin/orders/o1", code: 500, body: "<!doctype html><title>500</title><h1>Internal Server Error</h1>")
        vm.updateStatus(id: "o1", status: "delivered")
        await finishUpdate(vm)
        XCTAssertEqual(errors.last, "Failed to update order — the server hit an error — try again")
        fake.on("PATCH", "/admin/orders/o1", code: 403, body: #"{"detail":"Not enough permissions"}"#)
        vm.updateStatus(id: "o1", status: "delivered")
        await finishUpdate(vm)
        XCTAssertEqual(errors.last, "Failed to update order — not enough permissions")
    }

    func testAnExpiredTokenIsRefreshedAndTheChangeLands() async {
        fake.expiredOnce("PATCH", "/admin/orders/o2") { (200, #"{"id":"o2","status":"confirmed"}"#) }
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ in (200, Fixtures.tokenResponse(access: fakeJwt() + "r")) }
        let vm = await vm()
        vm.updateStatus(id: "o2", status: "confirmed")
        await finishUpdate(vm)
        XCTAssertEqual(lastToast()?.message, "Order marked as confirmed")
        XCTAssertFalse(host.sessionExpired.value)
    }

    func testADeadSessionKeepsTheSheetOpenWithoutAnExtraToast() async {
        fake.on("PATCH", "/admin/orders/o2", code: 401, body: #"{"detail":"Could not validate credentials"}"#)
        fake.on("POST", "/(agent-auth|auth)/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let vm = await vm()
        vm.select(order("o2"))
        vm.updateStatus(id: "o2", status: "confirmed")
        await finishUpdate(vm)
        XCTAssertTrue(host.sessionExpired.value)
        XCTAssertEqual(vm.ui.selectedId, "o2")
        XCTAssertTrue(errors.isEmpty)
        XCTAssertNil(vm.ui.updating)
    }

    func testDoubleTapsPatchOnce() async {
        let box = Ref<OrdersViewModel?>(nil)
        fake.on("PATCH", "/admin/orders/o2") { _, _ in
            onMainSync {
                box.value?.updateStatus(id: "o2", status: "confirmed")
                box.value?.updateStatus(id: "o2", status: "cancelled")
                box.value?.updateStatus(id: "o1", status: "delivered")
            }
            return (200, #"{"id":"o2","status":"confirmed"}"#)
        }
        let vm = await vm()
        box.value = vm
        vm.updateStatus(id: "o2", status: "confirmed")
        await finishUpdate(vm)
        XCTAssertEqual(fake.calls.filter { $0.method == "PATCH" }.count, 1)
    }

    func testAnUnreadableSuccessIsSettledByTheList() async {
        // A 200 whose body a proxy mangled: the list, re-read, says it went.
        let fake = self.fake!
        let landed = listWith("o2", "cancelled")
        fake.on("PATCH", "/admin/orders/o2") { _, _ in
            fake.on("GET", "/admin/orders", body: landed)
            return (200, "<html>OK</html>")
        }
        let vm = await vm()
        vm.updateStatus(id: "o2", status: "cancelled")
        await finishUpdate(vm)
        XCTAssertEqual(lastToast()?.message, "Order marked as cancelled")
    }

    func testSigningOutMidUpdateIsQuiet() async {
        let box = Ref<OrdersViewModel?>(nil)
        fake.on("PATCH", "/admin/orders/o2") { _, _ in
            onMainSync { box.value?.close() }
            return (200, "{}")
        }
        let vm = await vm()
        box.value = vm
        let before = host.toasts.count
        vm.updateStatus(id: "o2", status: "confirmed")
        await finishUpdate(vm)
        XCTAssertEqual(host.toasts.count, before)
    }
}
