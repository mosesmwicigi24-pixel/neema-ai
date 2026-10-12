import Foundation
import XCTest
@testable import NeemaCore

/// The call log's avatar maths against values computed with the web's own
/// expressions in Node (CallsView.tsx `avatarColor`, the initials line, `who`).
/// Android `calls/CallsParityTest.kt`.
final class CallsParityTests: XCTestCase {
    func testAvatarColourIndexMatchesTheWeb() {
        // node: [...(s||"?")].reduce((a,c)=>a+c.charCodeAt(0),0) % 6
        XCTAssertEqual(5, avatarIndex("Fr. Peter Kamau"))
        XCTAssertEqual(1, avatarIndex("+254712345678"))
        XCTAssertEqual(2, avatarIndex("Unknown"))
        XCTAssertEqual(0, avatarIndex("Mama 🌸 Njeri"), "an emoji counts its first UTF-16 unit once")
        XCTAssertEqual(3, avatarIndex(""), "empty hashes as \"?\"")
    }

    func testInitialsMatchTheWeb() {
        XCTAssertEqual("FP", initialsOf("Fr. Peter Kamau"))
        XCTAssertEqual("2", initialsOf("+254712345678"), "a bare number: its first digit")
        XCTAssertEqual("AC", initialsOf("a+b c"), "only the first + goes")
        XCTAssertEqual("U", initialsOf("Unknown"))
        XCTAssertEqual("M🌸", initialsOf("Mama 🌸 Njeri"), "the whole emoji, not half of it")
        XCTAssertEqual("", initialsOf("  "))
    }

    func testWhoFallsBackLikeTheWeb() {
        func call(_ name: String?, _ wa: String?) -> Call { Call(callId: "x", waId: wa, name: name) }
        XCTAssertEqual("Fr. Peter Kamau", rowWho(call("Fr. Peter Kamau", "254712345678")))
        XCTAssertEqual("+254712345678", rowWho(call(nil, "254712345678")))
        XCTAssertEqual("+254712345678", rowWho(call("", "254712345678")))
        XCTAssertEqual("Unknown caller", rowWho(call(nil, nil)))
        XCTAssertEqual("Unknown caller", rowWho(call(nil, "")))
    }
}
