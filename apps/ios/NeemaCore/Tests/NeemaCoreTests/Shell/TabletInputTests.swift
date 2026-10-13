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

/// A Tab S9 Ultra with its Book Cover Keyboard, or an iPad with a Magic
/// Keyboard: what each key does (Android `TabletInputTest`, the keyboard and
/// drop rules; `stepping` is in `TabletInputTests` above).
final class KeyboardRulesTests: XCTestCase {
    // The reply box.
    func testEnterSendsWithAHardwareKeyboard() {
        XCTAssertEqual(composerShortcut(key: .enter, down: true, shift: false, ctrl: false, hardwareKeyboard: true), .send)
    }

    func testShiftEnterIsANewLine() {
        XCTAssertNil(composerShortcut(key: .enter, down: true, shift: true, ctrl: false, hardwareKeyboard: true))
    }

    func testOnScreenKeyboardEnterIsANewLine() {
        XCTAssertNil(composerShortcut(key: .enter, down: true, shift: false, ctrl: false, hardwareKeyboard: false))
    }

    func testCtrlEnterAlwaysSends() {
        XCTAssertEqual(composerShortcut(key: .enter, down: true, shift: false, ctrl: true, hardwareKeyboard: false), .send)
        XCTAssertEqual(composerShortcut(key: .numPadEnter, down: true, shift: false, ctrl: true, hardwareKeyboard: true), .send)
    }

    func testKeyUpAndOtherKeysNeverSend() {
        XCTAssertNil(composerShortcut(key: .enter, down: false, shift: false, ctrl: false, hardwareKeyboard: true))
        XCTAssertNil(composerShortcut(key: .character("a"), down: true, shift: false, ctrl: true, hardwareKeyboard: true))
    }

    // App-wide.
    func testCtrlDigitsOpenViews() {
        XCTAssertEqual(appShortcut(key: .digit(1), down: true, ctrl: true, alt: false, shift: false), .view(0))
        XCTAssertEqual(appShortcut(key: .digit(9), down: true, ctrl: true, alt: false, shift: false), .view(8))
    }

    func testConversationWalking() {
        XCTAssertEqual(appShortcut(key: .down, down: true, ctrl: false, alt: true, shift: false), .nextConversation)
        XCTAssertEqual(appShortcut(key: .up, down: true, ctrl: false, alt: true, shift: false), .previousConversation)
        XCTAssertEqual(appShortcut(key: .rightBracket, down: true, ctrl: true, alt: false, shift: false), .nextConversation)
        XCTAssertEqual(appShortcut(key: .leftBracket, down: true, ctrl: true, alt: false, shift: false), .previousConversation)
    }

    func testSearchAndSidebar() {
        XCTAssertEqual(appShortcut(key: .character("f"), down: true, ctrl: true, alt: false, shift: false), .search)
        XCTAssertEqual(appShortcut(key: .character("k"), down: true, ctrl: true, alt: false, shift: false), .search)
        XCTAssertEqual(appShortcut(key: .character("b"), down: true, ctrl: true, alt: false, shift: false), .toggleNav)
    }

    // Plain typing, text editing chords and arrows without a modifier stay the field's.
    func testTypingAndEditingAreNeverTaken() {
        for k in [KeyName.character("a"), .character("f"), .digit(1), .down, .enter, .escape] {
            XCTAssertNil(appShortcut(key: k, down: true, ctrl: false, alt: false, shift: false), "\(k)")
        }
        for k in ["c", "v", "x", "z", "a"] {
            XCTAssertNil(appShortcut(key: .character(Character(k)), down: true, ctrl: true, alt: false, shift: false), "ctrl+\(k)")
        }
        XCTAssertNil(appShortcut(key: .character("f"), down: true, ctrl: true, alt: false, shift: true), "ctrl+shift+F")
        XCTAssertNil(appShortcut(key: .right, down: true, ctrl: false, alt: true, shift: false), "alt+right")
        XCTAssertNil(appShortcut(key: .digit(1), down: false, ctrl: true, alt: false, shift: false), "key up")
        XCTAssertNil(appShortcut(key: .digit(0), down: true, ctrl: true, alt: false, shift: false), "ctrl+0")
    }

    // Drag and drop from another app (Split View, Stage Manager).
    func testDropsNeemaCanAttach() {
        XCTAssertTrue(acceptsDrop(["image/jpeg"]))
        XCTAssertTrue(acceptsDrop(["text/plain", "video/mp4"]))
        XCTAssertTrue(acceptsDrop(["application/pdf"]))
        XCTAssertTrue(acceptsDrop(["APPLICATION/VND.OPENXMLFORMATS-OFFICEDOCUMENT.SPREADSHEETML.SHEET"]))
    }

    func testTextAndLinksAreNotAttachments() {
        XCTAssertFalse(acceptsDrop(["text/plain"]))
        XCTAssertFalse(acceptsDrop(["text/uri-list", "text/html"]))
        XCTAssertFalse(acceptsDrop([]))
    }
}

/// Esc on a hardware keyboard (Android `EscapeKeyTest`).
final class EscapeKeyTests: XCTestCase {
    func testEscClosesWhatIsOpen() { XCTAssertTrue(escapeIsBack(key: .escape, modified: false, somethingOpen: true)) }

    func testEscAtTheRootNeverLeavesTheApp() { XCTAssertFalse(escapeIsBack(key: .escape, modified: false, somethingOpen: false)) }

    func testModifiedEscAndOtherKeysAreLeftAlone() {
        XCTAssertFalse(escapeIsBack(key: .escape, modified: true, somethingOpen: true))
        XCTAssertFalse(escapeIsBack(key: .enter, modified: false, somethingOpen: true))
    }
}
