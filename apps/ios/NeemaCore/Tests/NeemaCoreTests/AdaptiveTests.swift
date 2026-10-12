import XCTest
@testable import NeemaCore

/// Android's `TabletLayoutTest`, for an iPad's windows: what navigation each
/// gets and how the inbox shares the room. The content width is the window
/// minus the navigation — 208 pt docked (270 at 130% text), 60 pt rail, 0 drawer.
final class AdaptiveTests: XCTestCase {
    private func content(_ window: Int, fontScale: Float = 1) -> Int {
        switch navMode(for: window) {
        case .drawer: return window
        case .rail: return window - 60
        case .docked: return window - Int(208 * min(max(fontScale, 1), 1.3))
        }
    }

    // 1. A 13" iPad on its side (1376 wide): everything docked, the thread readable.
    func testFullLandscape() {
        XCTAssertEqual(navMode(for: 1376), .docked)
        let p = inboxPanes(contentWidth: content(1376))
        XCTAssertTrue(p.twoPane)
        XCTAssertEqual(p.customer, .docked)
        XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN, "thread \(p.threadWidth)")
        XCTAssertTrue((320...400).contains(p.listWidth))
    }

    // 2. An 11" iPad on its side (1194 wide): the rail, two panes, a roomy thread;
    // the customer panel would squeeze it under THREAD_MIN, so it slides over.
    func testElevenInchLandscape() {
        XCTAssertEqual(navMode(for: 1194), .rail)
        let p = inboxPanes(contentWidth: content(1194))
        XCTAssertTrue(p.twoPane)
        XCTAssertEqual(p.customer, .overlay)
        XCTAssertTrue(p.roomyThread, "thread \(p.threadWidth)")
        XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN, "thread \(p.threadWidth)")
    }

    // 3. Upright (1032 wide): the rail, two panes, the customer slides over a roomy thread.
    func testPortrait() {
        XCTAssertEqual(navMode(for: 1032), .rail)
        let p = inboxPanes(contentWidth: content(1032))
        XCTAssertTrue(p.twoPane)
        XCTAssertEqual(p.customer, .overlay)
        XCTAssertTrue(p.roomyThread, "thread \(p.threadWidth)")
    }

    // 4. Split View 50/50 on a 13" (678 wide): one pane at a time, the rail stays.
    func testHalfSplit() {
        XCTAssertEqual(navMode(for: 678), .rail)
        XCTAssertFalse(inboxPanes(contentWidth: content(678)).twoPane)
    }

    // 5. The ⅔ side (around 981): two panes, customer on demand.
    func testTwoThirds() {
        let p = inboxPanes(contentWidth: content(981))
        XCTAssertTrue(p.twoPane)
        XCTAssertEqual(p.customer, .overlay)
        XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN)
    }

    // 6. The ⅓ side / Slide Over (375–414 wide): the phone layout (drawer, one pane).
    func testOneThird() {
        XCTAssertEqual(navMode(for: 414), .drawer)
        XCTAssertFalse(inboxPanes(contentWidth: content(414)).twoPane)
        XCTAssertFalse(inboxPanes(contentWidth: content(375)).twoPane)
    }

    // 7. Upright split (top or bottom in Stage Manager): as wide as portrait, so two panes.
    func testPortraitSplit() {
        XCTAssertTrue(inboxPanes(contentWidth: content(1032)).twoPane)
    }

    // 8. A small Stage Manager window (640): one pane, the rail.
    func testSmallWindow() {
        XCTAssertEqual(navMode(for: 640), .rail)
        XCTAssertFalse(inboxPanes(contentWidth: content(640)).twoPane)
    }

    // 9. An external 1920-wide display: everything docked, the activity log opens beside.
    func testExternalMonitor() {
        let p = inboxPanes(contentWidth: content(1920))
        XCTAssertEqual(p.customer, .docked)
        XCTAssertTrue(p.activityDocks)
        XCTAssertGreaterThanOrEqual(p.threadWidth - p.activityWidth, Adaptive.THREAD_MIN)
    }

    // 10. 130% text widens the docked sidebar: the thread still keeps its room.
    func testLargeTextLandscape() {
        let p = inboxPanes(contentWidth: content(1376, fontScale: 1.3))
        XCTAssertTrue(p.twoPane)
        XCTAssertGreaterThanOrEqual(p.threadWidth, Adaptive.THREAD_MIN, "thread \(p.threadWidth)")
    }

    // 11. Every width from 801 to 2560: a two-pane thread is never squeezed,
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
        XCTAssertEqual(navMode(for: 599), .drawer)
        XCTAssertEqual(navMode(for: 600), .rail)
        XCTAssertEqual(navMode(for: 1199), .rail)
        XCTAssertEqual(navMode(for: 1200), .docked)
    }

    // 13. Filter tabs share a row: all visible when they fit, equal when they can be.
    func testFitRowShares() {
        XCTAssertEqual(fitWidths([30, 40, 50], room: 180), [60, 60, 60])
        XCTAssertEqual(fitWidths([30, 80, 40], room: 180), [40, 90, 50])
        XCTAssertEqual(fitWidths([100, 100], room: 150), [100, 100])
        XCTAssertEqual(fitWidths([], room: 100), [])
    }

    // 14. ⌥↓ / ⌥↑ through the list: clamped to the ends, none selected → an end.
    func testStepThrough() {
        XCTAssertEqual(stepThrough(["a", "b", "c"], current: "a", forward: true), "b")
        XCTAssertEqual(stepThrough(["a", "b", "c"], current: "c", forward: true), "c")
        XCTAssertEqual(stepThrough(["a", "b", "c"], current: "a", forward: false), "a")
        XCTAssertEqual(stepThrough(["a", "b", "c"], current: nil, forward: true), "a")
        XCTAssertEqual(stepThrough(["a", "b", "c"], current: nil, forward: false), "c")
        XCTAssertEqual(stepThrough(["a", "b", "c"], current: "zz", forward: true), "a")
        XCTAssertNil(stepThrough([], current: "a", forward: true))
    }
}
