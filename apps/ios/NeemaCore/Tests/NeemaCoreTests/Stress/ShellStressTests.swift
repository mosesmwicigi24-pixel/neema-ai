import XCTest
@testable import NeemaCore

/// Round 5 / 8 (Android `ShellStressTest`, `DashboardStressTest`) — the
/// shell's shared feeds under a bad network and a busy shop: answers that
/// land after sign-out are dropped, a sign-out mid-poll abandons its
/// requests, and an alert storm costs one fetch. The app-layer rules (one
/// session-expired prompt, re-authenticating keeps the view, another agent
/// starts clean) live in `AppModel` and are exercised by the app's own tests
/// on macOS CI.
@MainActor
final class ShellStressTests: XCTestCase {
    private var fake: FakeNeema!
    private var host: TestHost!

    override func setUp() async throws {
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
        host = TestHost(fake: fake, ordersFeed: true)
    }

    override func tearDown() async throws {
        host.logout()
        AppClock.reset()
    }

    private func orders() -> Int { fake.callsTo("GET", "/admin/orders").count }

    func testAnAnswerThatLandsAfterSignOutIsDropped() async {
        await drain()
        XCTAssertFalse(host.orders.value.isEmpty, "the sign-in read landed")
        let hold = fake.hang("GET", "/admin/orders")
        host.feed?.refetchOrders()
        let waiting = await eventually { hold.waiting == 1 }
        XCTAssertTrue(waiting)
        host.logout()
        hold.release()
        await drain()
        XCTAssertTrue(host.orders.value.isEmpty, "no orders for a signed-out app")
    }

    func testSigningOutMidPollCancelsItQuietly() async {
        await drain()
        let hold = fake.hang("GET", "/admin/orders")
        host.foreground.value = false
        await drain()
        host.foreground.value = true   // the poll refetches on return
        let waiting = await eventually { hold.waiting > 0 }
        XCTAssertTrue(waiting)
        host.logout()
        let abandoned = await eventually { hold.waiting == 0 }
        XCTAssertTrue(abandoned, "the poll's held request was abandoned")
        hold.release()
        await drain()
        XCTAssertTrue(host.orders.value.isEmpty)
    }

    func testTwoHundredOrderAlertsCostOneOrdersFetch() async {
        await drain()
        host.connectLive()
        await drain()
        let before = orders()
        for i in 0..<200 {
            host.sockets.last.frame(#"{"event":"notification","type":"order_update","title":"Order paid","body":"BH-\#(i)"}"#)
        }
        await drain()
        XCTAssertEqual(before, orders(), "the web's 800 ms wait")
        await host.clock.advance(by: 801)
        await drain()
        XCTAssertEqual(before + 1, orders())
        await host.clock.advance(by: 10_000)
        await drain()
        XCTAssertEqual(before + 1, orders(), "and never again for the same burst")
    }

    func testABurstOfSocketFramesThatAreNotAlertsCostsNothing() async {
        await drain()
        host.connectLive()
        await drain()
        let before = fake.calls.count
        for i in 0..<200 {
            host.sockets.last.frame(#"{"type":"new_message","conversationId":"c\#(i % 9)","sender":"user","text":"m\#(i)"}"#)
        }
        await host.clock.advance(by: 5_000)
        await drain()
        XCTAssertEqual(before, fake.calls.count, "no requests")
    }
}
