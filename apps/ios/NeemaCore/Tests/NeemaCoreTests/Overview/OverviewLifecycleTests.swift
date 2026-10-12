import Foundation
import XCTest
@testable import NeemaCore

/// The analytics poll across trips to the background and off the screen, and
/// the live figures (the overview rows of Android `InsightsLifecycleTest` and
/// `ScreenFreshnessTest`).
final class OverviewLifecycleTests: OverviewTestCase {
    func testPollPausesInTheBackgroundAndCatchesUpOnceOnReturn() async {
        let vm = await vm()
        let base = reads("/admin/stats")
        await advance(OverviewViewModel.POLL_MS + 1)
        XCTAssertEqual(reads("/admin/stats"), base + 1, "on screen: one read per 30 s")

        host.foreground.update(false)
        await advance(10 * OverviewViewModel.POLL_MS)
        XCTAssertEqual(reads("/admin/stats"), base + 1, "in the background: nothing")

        host.foreground.update(true)
        await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(reads("/admin/stats"), base + 2, "back in front: one catch-up, not the ten missed polls")

        // Off-screen (another view) the poll stops too.
        vm.life.shown.update(false)
        await advance(5 * OverviewViewModel.POLL_MS)
        XCTAssertEqual(reads("/admin/stats"), base + 2)
        vm.life.shown.update(true)
        await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(reads("/admin/stats"), base + 3, "a return to the screen reads the figures again")
    }

    func testPollsStatsAndInterceptsEveryThirtySecondsOnDisplay() async {
        let vm = await vm()
        XCTAssertEqual(reads("/admin/stats"), 1)
        XCTAssertEqual(reads("/admin/attribution"), 1)
        XCTAssertEqual(humanReads(), 1)
        await advance(30_001)
        XCTAssertEqual(reads("/admin/stats"), 2)
        XCTAssertEqual(humanReads(), 2)
        XCTAssertEqual(reads("/admin/attribution"), 1, "attribution is a mount-time read")

        vm.life.shown.update(false)
        await advance(5 * 60_000)
        XCTAssertEqual(reads("/admin/stats"), 2, "no polling off-screen")

        vm.life.shown.update(true)
        await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(reads("/admin/stats"), 3)
        XCTAssertEqual(reads("/admin/attribution"), 2)
    }

    func testCatchUpKeepsTheFiguresUpWithoutASpinner() async {
        let vm = await vm()
        let before = vm.ui.stats
        XCTAssertNotNil(before)
        fake.on("GET", "/admin/stats", code: 502, body: "{}")
        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(vm.ui.stats, before)
        XCTAssertFalse(vm.ui.statsLoading)
        XCTAssertNil(vm.ui.statsError)
    }

    func testAnInterceptChangeOrAnInterceptAlertMovesTheFigures() async {
        host.connectLive()
        await drain()
        _ = await vm()
        let before = reads("/admin/stats")
        host.sockets.last.frame(#"{"type":"intercept_changed","conversationId":"c1","mode":"human","eventKind":"intercept"}"#)
        host.sockets.last.frame(#"{"type":"intercept_changed","conversationId":"c2","mode":"ai","eventKind":"release"}"#)
        host.sockets.last.frame(#"{"event":"notification","type":"intercept","title":"🙋 Grace picked up"}"#)
        await advance(ScreenLife.EVENT_WINDOW_MS + 1)
        XCTAssertEqual(reads("/admin/stats"), before + 1, "one refetch for the three")
        // A plain message moves nothing on this screen.
        host.sockets.last.frame(#"{"type":"new_message","conversationId":"c1","sender":"user","text":"hi"}"#)
        await advance(5_000)
        XCTAssertEqual(reads("/admin/stats"), before + 1)
    }

    /// Off the screen, the events wait for the next visit (which reloads anyway).
    func testEventsOffScreenDoNotReload() async {
        host.connectLive()
        await drain()
        let vm = await vm()
        vm.life.shown.update(false)
        let before = reads("/admin/stats")
        host.sockets.last.frame(#"{"event":"notification","type":"order_update","title":"Order placed"}"#)
        await advance(ScreenLife.EVENT_WINDOW_MS + 1)
        XCTAssertEqual(reads("/admin/stats"), before)
    }

    /// The dashboard's orders poll found a change (the pending badge moved): the order figures follow.
    func testTheOrdersPollFindingAChangeRefreshesTheFigures() async {
        let h = TestHost(fake: fake, ordersFeed: true)
        hosts.append(h)
        await drain()
        _ = await eventually(timeout: 10) { !(h.feed?.reading ?? false) }
        await drain()
        XCTAssertFalse(h.orders.value.isEmpty)
        _ = await vm(h)
        XCTAssertEqual(reads("/admin/stats"), 1)
        // A pending order is confirmed server-side.
        let changed = ReportsFixtures.orders.map { $0.replacingOccurrences(of: "\"status\":\"pending\"", with: "\"status\":\"confirmed\"") }
        XCTAssertNotEqual(changed, ReportsFixtures.orders)
        fake.on("GET", "/admin/orders", body: "[\(changed.joined(separator: ","))]")
        await h.clock.advance(by: 90_001); await drain() // the dashboard's orders poll
        await h.clock.advance(by: ScreenLife.EVENT_WINDOW_MS + 1); await drain()
        // 30 s polls ×3 plus the one the orders change asked for.
        XCTAssertEqual(reads("/admin/stats"), 1 + 3 + 1)
    }
}
