import XCTest
@testable import NeemaCore

final class JSONValueTests: XCTestCase {
    func testParsesAndReadsLeniently() throws {
        let v = JSONValue.parse(#"{"a": "2 pcs", "b": 4500, "c": true, "d": null, "e": ["x", 1, null, {"k": 1}]}"#)!
        XCTAssertEqual(v["a"]?.lenientDouble, 2)
        XCTAssertEqual(v["b"]?.content, "4500")
        XCTAssertEqual(v["c"]?.boolValue, true)
        XCTAssertEqual(v["d"], .null)
        XCTAssertEqual(LenientKeyed<DummyKey>.lenientStrings(v["e"]!), ["x", "1"])
        XCTAssertEqual(JSONValue.leadingNumber(in: "-3.5kg"), -3.5)
        XCTAssertNil(JSONValue.leadingNumber(in: "pcs"))
    }

    enum DummyKey: String, CodingKey { case a }
}
