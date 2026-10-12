import XCTest
@testable import NeemaCore

/// Android `app/ToastLifecycleTest` (round 10, core carry-over): page.tsx's
/// toast - one at a time, replaced by the next, gone after 3.5 s - held by
/// the presenter rather than the view, so a late reader sees the same state,
/// and the 3.5 s only count while the agent can see it. The saved-state
/// tests (a pending toast surviving process death) have no twin: the iOS
/// `AppModel` keeps the toast in memory only.
final class ToastLifecycleTests: XCTestCase {
    private var clock: VirtualClock!
    private var fg: Watched<Bool>!
    private var presenter: ToastPresenter!

    override func setUp() {
        clock = VirtualClock()
        fg = Watched<Bool>(true)
        presenter = ToastPresenter(foreground: fg, sleep: clock.sleeper, now: { self.clock.now })
    }

    override func tearDown() {
        presenter.cancel()
    }

    private func advance(_ ms: Int64) async { await clock.advance(by: ms) }
    private var shown: String? { presenter.current.value?.message }
    /// The toast is gone once its timer has run; the timer's task needs a moment to land.
    private func gone() async -> Bool { await eventually { self.presenter.current.value == nil } }

    func testAToastShowsForThreeAndAHalfSecondsInFront() async {
        presenter.show("Order updated")
        XCTAssertEqual("Order updated", shown)
        XCTAssertEqual(.success, presenter.current.value?.type)
        await advance(3_499); XCTAssertEqual("Order updated", shown)
        await advance(2)
        let cleared = await gone()
        XCTAssertTrue(cleared)
        XCTAssertNil(shown)
    }

    func testTheNextToastReplacesItAndGetsItsOwnFullTime() async {
        presenter.show("First")
        await advance(3_000)
        presenter.show("Second", .error)
        // The web's first timer would clear the second 500 ms in; each gets its 3.5 s here.
        await advance(1_000); XCTAssertEqual("Second", shown)
        await advance(2_499); XCTAssertEqual("Second", shown)
        await advance(2)
        let cleared = await gone()
        XCTAssertTrue(cleared)
        XCTAssertNil(shown)
    }

    func testAToastRaisedWithNoShellWatchingIsStillThereWhenItComesBack() async {
        // The old shell collected a SharedFlow in composition: a toast raised
        // while the activity was being recreated went nowhere. Here the
        // presenter holds the state: a reader arriving later gets it at once.
        presenter.show("Saved")
        await advance(100)
        let seen = Ref<String?>(nil)
        let sub = presenter.current.observe { seen.value = $0?.message }
        defer { sub.cancel() }
        XCTAssertEqual("Saved", presenter.current.value?.message, "the shell reads the same state after a rotation")
        XCTAssertEqual("Saved", seen.value)
    }

    func testAToastRaisedInTheBackgroundWaitsForTheAgent() async {
        fg.update(false)
        presenter.show("New message: Mama Njeri", .info)
        await advance(10 * 60_000)
        XCTAssertEqual("New message: Mama Njeri", shown, "ten minutes away: still waiting")
        fg.update(true)
        await advance(3_499); XCTAssertNotNil(shown, "its full time once back")
        await advance(2)
        let cleared = await gone()
        XCTAssertTrue(cleared)
        XCTAssertNil(shown)
    }

    func testLeavingMidwayKeepsWhatWasLeftAndAtLeastASecondAndAHalf() async {
        presenter.show("Saved")
        await advance(1_000)
        fg.update(false)
        await settle()
        await advance(60_000)
        fg.update(true)
        await advance(2_499); XCTAssertEqual("Saved", shown, "2.5 s were left")
        await advance(2)
        var cleared = await gone()
        XCTAssertTrue(cleared)
        XCTAssertNil(shown)

        presenter.show("Sent")
        await advance(3_400)
        fg.update(false); await settle(); await advance(5_000); fg.update(true)
        await advance(1_499); XCTAssertEqual("Sent", shown, "100 ms would be a flicker: 1.5 s")
        await advance(2)
        cleared = await gone()
        XCTAssertTrue(cleared)
        XCTAssertNil(shown)
    }

    func testSigningOutTakesTheLastAgentsToastWithIt() async {
        // AppModel.clearAgentState cancels the presenter on sign-out.
        presenter.show("Order BH-2001 marked paid")
        presenter.cancel()
        await advance(10)
        XCTAssertNil(shown)
        await advance(3_500)
        XCTAssertNil(shown, "and its timer is gone with it")
    }
}
