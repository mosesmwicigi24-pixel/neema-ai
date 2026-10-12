import XCTest
@testable import NeemaCore

/// Android `app/ShellLifecycleTest` (round 9, lifecycle and state), the parts
/// NeemaCore holds: the way back through the views (`NavHistory`), its saved
/// form, what sign-out clears in the shell's shared state (`TestHost.logout`),
/// and the orders reads that meet sharing one read. Deep links stashed at the
/// login screen, the sign-out hang-up and the shell's overlay back order live
/// in the app layer (`AppModel`, `DashboardShell`).
@MainActor
final class ShellLifecycleTests: XCTestCase {
    private var fake: FakeNeema!
    private var host: TestHost?

    override func setUp() async throws {
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
    }

    override func tearDown() async throws {
        host?.logout()
        host = nil
        AppClock.reset()
    }

    private func signedIn() -> TestHost {
        let h = TestHost(fake: fake, ordersFeed: true)
        host = h
        return h
    }

    // -- Back through the views --------------------------------------------------

    func testBackWalksThePreviousViewsThenTheInboxThenLeaves() async {
        var d = NavHistory()
        XCTAssertFalse(d.canGoBack, "the inbox with nowhere to go back to: the system leaves the app")
        d.navigate(.orders)
        d.navigate(.reports)
        XCTAssertTrue(d.canGoBack)
        XCTAssertTrue(d.back()); XCTAssertEqual(.orders, d.view)
        XCTAssertTrue(d.back()); XCTAssertEqual(.conversations, d.view)
        XCTAssertFalse(d.canGoBack)
        XCTAssertFalse(d.back())
        XCTAssertEqual(.conversations, d.view)
    }

    func testEachViewIsRememberedOnceSoBackNeverLoops() async {
        var d = NavHistory()
        // Inbox -> Orders -> Reports -> Orders -> Inbox -> Orders
        for v in [ViewId.orders, .reports, .orders, .conversations, .orders] { d.navigate(v) }
        var seen: [ViewId] = []
        while d.back() { seen.append(d.view) }
        XCTAssertEqual([.conversations, .reports, .conversations], seen, "then the inbox, and out")
    }

    func testNavigatingToTheSameViewIsNotAHistoryEntry() async {
        var d = NavHistory()
        d.navigate(.orders); d.navigate(.orders); d.navigate(.orders)
        XCTAssertTrue(d.back()); XCTAssertEqual(.conversations, d.view)
        XCTAssertFalse(d.back())
    }

    func testAViewReachedWithoutHistoryStillGoesBackToTheInbox() async {
        // A deep link straight into Calls (a cold start from a notification).
        var d = NavHistory(view: .calls, history: [])
        XCTAssertEqual(.calls, d.view)
        XCTAssertTrue(d.canGoBack)
        XCTAssertTrue(d.back()); XCTAssertEqual(.conversations, d.view)
        XCTAssertFalse(d.back())
    }

    func testCrossViewRequestsAreHistoryEntriesToo() async {
        // AppModel.openConversationFor / focusCalls set the key, then navigate: the history keeps where they came from.
        var d = NavHistory()
        d.navigate(.orders)
        d.navigate(.conversations)   // openConversationFor("254722000111")
        XCTAssertEqual(.conversations, d.view)
        XCTAssertTrue(d.back(), "back from the chat opened out of Orders returns to Orders")
        XCTAssertEqual(.orders, d.view)
        d.navigate(.calls)           // focusCalls("254722000111")
        XCTAssertTrue(d.back()); XCTAssertEqual(.orders, d.view)
    }

    // -- Process death -----------------------------------------------------------

    func testTheViewAndItsHistorySurviveProcessDeath() async throws {
        var before = NavHistory()
        before.navigate(.orders)
        before.navigate(.deals)
        // The saved form (NavHistory is Codable), read back by the next process.
        let saved = try NeemaJSON.encoder.encode(before)
        var after = try NeemaJSON.decoder.decode(NavHistory.self, from: saved)
        XCTAssertEqual(.deals, after.view, "the first frame is already the right view")
        XCTAssertTrue(after.canGoBack)
        XCTAssertTrue(after.back()); XCTAssertEqual(.orders, after.view)
        XCTAssertTrue(after.back()); XCTAssertEqual(.conversations, after.view)
        XCTAssertFalse(after.back())
    }

    // -- Sign-out ----------------------------------------------------------------

    func testSignOutWithNoCallIsImmediateAndForgetsTheAgent() async {
        let d = signedIn()
        await drain()
        XCTAssertFalse(d.orders.value.isEmpty)
        d.openConvKey.value = "254722000111"
        d.inboxSummary.value = InboxSummary(unread: 5, human: 2)
        d.logout()
        XCTAssertNil(d.session.value)
        XCTAssertTrue(d.orders.value.isEmpty)
        XCTAssertNil(d.openConvKey.value)
        XCTAssertNil(d.inboxSummary.value)
        XCTAssertFalse(d.sessionExpired.value)
        XCTAssertFalse(d.feed!.signedIn, "the next agent can't walk back into the last one's reads")
    }

    // -- Orders: one read on the wire --------------------------------------------

    func testOrdersRefetchesThatMeetShareOneRead() async {
        let d = signedIn()
        await drain()
        let before = fake.callsTo("GET", "/admin/orders").count
        let hold = fake.hang("GET", "/admin/orders")
        d.feed!.refetchOrders()          // on the wire (held)
        let waiting = await eventually { hold.waiting == 1 }
        XCTAssertTrue(waiting)
        d.feed!.refetchOrders()          // queued behind it
        d.feed!.refetchOrders()          // shares the queued one
        d.feed!.refetchOrders()          // and so does re-auth's (AppModel.onReauthenticated)
        await settle()
        hold.release()
        let done = await eventually { !d.feed!.reading }
        XCTAssertTrue(done)
        await drain()
        XCTAssertEqual(before + 2, fake.callsTo("GET", "/admin/orders").count, "the held read, then ONE more - not four")
    }
}
