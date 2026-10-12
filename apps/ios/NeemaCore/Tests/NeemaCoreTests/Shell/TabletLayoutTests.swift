import XCTest
@testable import NeemaCore

/// Android `tablet/TabletLayoutTest`: the Tab S9 Ultra's windows, as numbers -
/// what navigation each gets and how the inbox shares the room. The content
/// width is the window minus the navigation - 208 pt docked (270 at 130%
/// text), 60 pt rail, 0 drawer. (`AdaptiveTests` runs the same rules at an
/// iPad's sizes.)
final class TabletLayoutTests: XCTestCase {
    private func content(_ window: Int, fontScale: Float = 1) -> Int {
        switch navMode(for: window) {
        case .drawer: return window
        case .rail: return window - 60
        case .docked: return window - Int(208 * min(max(fontScale, 1), 1.3))
        }
    }

    // 1. On its side, default zoom: everything docked, the thread readable.
    func testFullLandscape() {
        XCTAssertEqual(.docked, navMode(for: 1480))
        let p = inboxPanes(contentWidth: content(1480))
        XCTAssertTrue(p.twoPane)
        XCTAssertEqual(.docked, p.customer)
        XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN, "thread \(p.threadWidth)")
        XCTAssertTrue((320...400).contains(p.listWidth))
    }

    // 2. One zoom step up (1393 x 870): still three panes, still a readable thread.
    func testZoomedLandscape() {
        let p = inboxPanes(contentWidth: content(1393))
        XCTAssertTrue(p.twoPane)
        XCTAssertEqual(.docked, p.customer)
        XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN, "thread \(p.threadWidth)")
    }

    // 3. Upright: the rail, two panes, the customer slides over a roomy thread.
    func testPortrait() {
        XCTAssertEqual(.rail, navMode(for: 924))
        let p = inboxPanes(contentWidth: content(924))
        XCTAssertTrue(p.twoPane)
        XCTAssertEqual(.overlay, p.customer)
        XCTAssertTrue(p.roomyThread, "thread \(p.threadWidth)")
    }

    // 4. Split screen 50/50: one pane at a time, the rail stays.
    func testHalfSplit() {
        XCTAssertEqual(.rail, navMode(for: 736))
        XCTAssertFalse(inboxPanes(contentWidth: content(736)).twoPane)
    }

    // 5. The 2/3 side: two panes, customer on demand.
    func testTwoThirds() {
        let p = inboxPanes(contentWidth: content(980))
        XCTAssertTrue(p.twoPane)
        XCTAssertEqual(.overlay, p.customer)
        XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN)
    }

    // 6. The 1/3 side: the phone layout (drawer, one pane).
    func testOneThird() {
        XCTAssertEqual(.drawer, navMode(for: 488))
        XCTAssertFalse(inboxPanes(contentWidth: content(488)).twoPane)
    }

    // 7. Upright split (top or bottom half): as wide as portrait, so two panes.
    func testPortraitSplit() {
        XCTAssertTrue(inboxPanes(contentWidth: content(924)).twoPane)
    }

    // 8. The pop-up window: one pane, the rail.
    func testPopup() {
        XCTAssertEqual(.rail, navMode(for: 640))
        XCTAssertFalse(inboxPanes(contentWidth: content(640)).twoPane)
    }

    // 9. DeX on a 1920-wide monitor: everything docked, the activity log opens beside.
    func testDexMonitor() {
        let p = inboxPanes(contentWidth: content(1920))
        XCTAssertEqual(.docked, p.customer)
        XCTAssertTrue(p.activityDocks)
        XCTAssertGreaterThanOrEqual(p.threadWidth - p.activityWidth, Adaptive.THREAD_MIN)
    }

    // 10. 130% text widens the docked sidebar: the thread still keeps its room.
    func testLargeTextLandscape() {
        let p = inboxPanes(contentWidth: content(1480, fontScale: 1.3))
        XCTAssertTrue(p.twoPane)
        XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN, "thread \(p.threadWidth)")
    }

    // 11. Every width from 720 to 2560: a two-pane thread is never squeezed,
    // and a docked side pane never pushes it under the minimum.
    func testSweepNeverSqueezesTheThread() {
        for w in Adaptive.TWO_PANE_MIN...2560 {
            let p = inboxPanes(contentWidth: w)
            XCTAssertTrue(p.twoPane, "\(w) two-pane")
            XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN, "\(w) thread \(p.threadWidth)")
            if p.activityDocks { XCTAssertGreaterThanOrEqual(p.threadWidth - p.activityWidth, Adaptive.THREAD_MIN, "\(w) activity") }
            let used = p.listWidth + p.threadWidth + (p.customer == .docked ? p.customerWidth + 33 : 0)
            XCTAssertLessThanOrEqual(used, w, "\(w) fits")
        }
    }

    // 12. Nav thresholds.
    func testNavThresholds() {
        XCTAssertEqual(.drawer, navMode(for: 599))
        XCTAssertEqual(.rail, navMode(for: 600))
        XCTAssertEqual(.rail, navMode(for: 1199))
        XCTAssertEqual(.docked, navMode(for: 1200))
    }

    // 14. A call docks beside the view on a Tab S9 Ultra on its side (and DeX),
    // covers the content on narrower windows, and is the top bar when minimised.
    func testCallDocking() {
        let live = CallPhase.inCall
        let ringing = CallPhase.ringing
        let idle = CallPhase.idle
        func docks(_ phase: CallPhase, _ window: Int, min: Bool = false) -> Bool {
            callDocks(phase: phase, minimised: min, contentWidth: CGFloat(content(window)))
        }
        XCTAssertTrue(docks(live, 1480))
        XCTAssertTrue(docks(ringing, 1393))
        XCTAssertTrue(docks(live, 1920))
        XCTAssertFalse(docks(live, 924), "upright")
        XCTAssertFalse(docks(live, 736), "split")
        XCTAssertFalse(docks(live, 412), "phone")
        XCTAssertFalse(docks(live, 1480, min: true), "minimised")
        XCTAssertFalse(docks(idle, 1480), "idle")
        // Docked, the view beside keeps a two-pane inbox.
        XCTAssertTrue(inboxPanes(contentWidth: content(1480) - Int(CALL_PANEL_WIDTH) - 1).twoPane)
    }

    // 13. Filter tabs share a row: all visible when they fit, equal when they can be.
    func testFitRowShares() {
        XCTAssertEqual([60, 60, 60], fitWidths([30, 40, 50], room: 180))
        XCTAssertEqual([40, 90, 50], fitWidths([30, 80, 40], room: 180))
        XCTAssertEqual([100, 100], fitWidths([100, 100], room: 150))
        XCTAssertEqual([], fitWidths([], room: 100))
    }
}

/// The Calls view's details pane through rotations, splits and filters
/// (Android `CallsDetailsPickTest`; `detailsPick` lives in the core since cycle 8).
final class CallsDetailsPickTests: XCTestCase {
    private func p(_ wide: Bool, _ shown: [String], _ sel: String?, _ auto: String?) -> DetailsPick {
        detailsPick(wide: wide, shownIds: shown, selected: sel, autoPicked: auto)
    }

    func testTabletOpensTheNewest() { XCTAssertEqual(p(true, ["a", "b"], nil, nil).select, "a") }

    func testTheAgentsPickStays() {
        let r = p(true, ["a", "b"], "b", "a")
        XCTAssertEqual(r.select, "b")
        XCTAssertNil(r.autoPicked)
    }

    func testAFilteredAwayCallMovesToTheFirstShown() { XCTAssertEqual(p(true, ["c"], "a", nil).select, "c") }

    func testShrinkingDropsOnlyTheAppsPick() {
        XCTAssertNil(p(false, ["a"], "a", "a").select)
        XCTAssertEqual(p(false, ["a", "b"], "b", nil).select, "b")
    }

    func testAnEmptyLogKeepsWhatIsOpen() { XCTAssertEqual(p(true, [], "x", nil).select, "x") }

    func testGrowingBackOpensTheNewestAgain() { XCTAssertEqual(p(true, ["a"], nil, nil).autoPicked, "a") }
}
