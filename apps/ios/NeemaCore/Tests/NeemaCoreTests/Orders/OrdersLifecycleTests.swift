import Foundation
import XCTest
@testable import NeemaCore

/// Lifecycle and state (the orders part of Android `SalesLifecycleTest`):
/// what a phone does to Orders — a rotation (the model survives; nothing may
/// be replayed over it), the app reclaimed (a fresh model gets the saved
/// state back through the scene), and a restored open row that must wait
/// for the first read instead of closing.
final class OrdersLifecycleTests: OrdersTestCase {
    /// What the scene would keep: only JSON values, through the text a scene store holds.
    private func sceneRoundTrip(_ saved: [String: JSONValue]) -> [String: JSONValue] {
        for (k, v) in saved {
            switch v {
            case .string, .number, .bool, .null: break
            default: XCTFail("\(k)=\(v) can't go in the scene store")
            }
        }
        return JSONValue.parse(JSONValue.object(saved).text)!.objectValue!
    }

    func testOrdersFilterSearchPageAndOpenOrderSurviveTheAppBeingReclaimed() async {
        let a = await vm()
        a.setFilter("confirmed"); a.setSearch("peter"); a.setPage(2)
        a.select(orders.first)
        let saved = sceneRoundTrip(a.saveUi())
        let b = await vm(await signedIn())
        XCTAssertTrue(b.restoreIfFresh(saved))
        XCTAssertEqual(b.ui.filter, "confirmed")
        XCTAssertEqual(b.ui.search, "peter")
        XCTAssertEqual(b.ui.page, 2)
        XCTAssertEqual(b.ui.selectedId, a.ui.selectedId)
    }

    /// Where the list was scrolled comes back too.
    func testOrdersScrollSurvivesTheReclaimUntilApplied() async {
        let a = await vm()
        a.scroll = ScrollPos(9, 42)
        let saved = sceneRoundTrip(a.saveUi())
        let b = await vm(await signedIn())
        b.restoreUi(saved)
        XCTAssertEqual(b.ui.pendingScroll, ScrollPos(9, 42))
        // A second reclaim before the orders came in still remembers it.
        b.scroll = ScrollPos(0, 0)
        XCTAssertEqual(b.saveUi()["scrollIndex"], .number(9)); XCTAssertEqual(b.saveUi()["scrollOffset"], .number(42))
        b.scrollRestored()
        XCTAssertNil(b.ui.pendingScroll)
        // Never scrolled: nothing to apply.
        let c = await self.vm()
        let d = await self.vm()
        c.restoreUi(d.saveUi())
        XCTAssertNil(c.ui.pendingScroll)
    }

    func testRotationNeverReplaysAnOlderCopyOverTheLiveModel() async {
        // The screen was drawn on this model before the rotation, and the agent
        // typed on after the scene saved: the restore must not win.
        let stale = await vm(); stale.setSearch("stale")
        let live = await vm(); live.setSearch("typed after the save"); live.uiAttached = true
        XCTAssertFalse(live.restoreIfFresh(stale.saveUi()))
        XCTAssertEqual(live.ui.search, "typed after the save")
        // A fresh model takes it once, and never again after that.
        let fresh = await vm()
        XCTAssertTrue(fresh.restoreIfFresh(stale.saveUi()))
        XCTAssertEqual(fresh.ui.search, "stale")
        fresh.setSearch("typed")
        XCTAssertFalse(fresh.restoreIfFresh(stale.saveUi()))
        XCTAssertEqual(fresh.ui.search, "typed")
    }

    func testASavedFilterThatIsNoLongerAStatusIsIgnored() async {
        let vm = await vm()
        vm.restoreUi(["filter": .string("shipped"), "page": .number(-3)])
        XCTAssertEqual(vm.ui.filter, "all")
        XCTAssertEqual(vm.ui.page, 1)
    }

    /// Restored after the app was reclaimed, the open order is kept until the
    /// list has really been read: a first read that failed proves nothing, a
    /// good read without the row does.
    func testRestoredOpenOrderWaitsForAGoodReadBeforeClosing() async {
        fake.on("GET", "/admin/orders", code: 500, body: "{}")
        let h = await signedIn()
        let vm = await vm(h)
        vm.restoreUi(["selected": .string("o1")])
        XCTAssertTrue(h.orders.value.isEmpty)
        XCTAssertFalse(vm.loaded, "never read: the missing row is not proof it is gone")
        XCTAssertNil(vm.selected)

        SalesFixtures.install(fake, orderList: [])
        let ok = await self.vm(await signedIn())
        XCTAssertTrue(ok.loaded, "read, and empty: an open order missing from it is gone")
    }

    /// The open order is the LIVE row: a refetch that changes it shows through the sheet.
    func testTheOpenOrderFollowsTheList() async {
        let vm = await vm()
        vm.select(order("o2"))
        XCTAssertEqual(vm.selected?.status, "pending")
        fake.on("GET", "/admin/orders", body: listWith("o2", "confirmed"))
        vm.refresh(); await drain()
        XCTAssertEqual(vm.selected?.status, "confirmed")
    }

    /// Sign-out: the feed's list goes and a new sign-in paints from that agent's own snapshot.
    func testSignOutClearsTheListAndTheSnapshotPaintsTheNextSignIn() async {
        let snaps = SnapshotCache.temporary()
        let h = await signedIn(snapshots: snaps)
        XCTAssertEqual(h.orders.value.count, 6)
        h.logout()
        XCTAssertTrue(h.orders.value.isEmpty)
        // The server is down for the next sign-in: the snapshot paints at once.
        fake.on("GET", "/admin/orders", code: 503, body: "{}")
        let again = TestHost(fake: fake, snapshots: snaps, ordersFeed: true)
        hosts.append(again)
        XCTAssertEqual(again.orders.value.count, 6, "painted from the snapshot before any read")
        let vm = await vm(again)
        XCTAssertFalse(vm.ui.initialLoading)
        XCTAssertEqual(again.orders.value.count, 6)
    }
}
