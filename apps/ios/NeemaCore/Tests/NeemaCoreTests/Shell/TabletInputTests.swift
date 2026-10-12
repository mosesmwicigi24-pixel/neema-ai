import XCTest
@testable import NeemaCore

/// Android `tablet/TabletInputTest`: a Tab S9 Ultra with its Book Cover
/// Keyboard (or DeX) - what each key does. Only the list walking has a core
/// twin (`stepThrough`); the key chords (`composerShortcut`, `appShortcut`),
/// Esc-is-back and drag-and-drop acceptance are Android-only.
final class TabletInputTests: XCTestCase {
    func testStepping() {
        let ids = ["a", "b", "c"]
        XCTAssertEqual("b", stepThrough(ids, current: "a", forward: true))
        XCTAssertEqual("c", stepThrough(ids, current: "c", forward: true))
        XCTAssertEqual("a", stepThrough(ids, current: "a", forward: false))
        XCTAssertEqual("a", stepThrough(ids, current: nil, forward: true))
        XCTAssertEqual("c", stepThrough(ids, current: "gone", forward: false))
        XCTAssertNil(stepThrough([], current: "a", forward: true))
    }
}
