import Foundation
import XCTest
@testable import NeemaCore

/// GET /admin/orders carries no `contact_name`. The web's mapOrder makes the
/// name `contact_name ?? wa_id`, so the card and the sheet show the bare wa_id
/// with the formatted phone under it. `phoneLine` never repeats the name it
/// sits under. (Android `OrderPhoneLineTest`.)
final class OrderPhoneLineTests: XCTestCase {
    private func order(_ waId: String, name: String? = nil) -> Order {
        var row = try! NeemaJSON.decode(Order.self, from: Fixtures.orderRow("o1", waId, "[]", "100.0", "pending", "whatsapp", 5))
        row.contactName = name
        return row
    }

    func testTheApiShapeHasNoNameSoThePhoneLineIsHidden() {
        let o = order("254712345678")
        let name = Fmt.displayName(o.contactName, o.waId)
        XCTAssertEqual(name, Fmt.formatPhone("254712345678"))
        XCTAssertNil(OrderUi.phoneLine(o, displayedName: name))
    }

    func testARealNameKeepsThePhoneUnderIt() {
        let o = order("254712345678", name: "Fr. Peter Kamau")
        XCTAssertEqual(OrderUi.phoneLine(o, displayedName: Fmt.displayName(o.contactName, o.waId)), Fmt.formatPhone("254712345678"))
    }

    func testAWebsiteVisitorIsNotRepeatedEither() {
        let o = order("web_3f9a0c")
        XCTAssertNil(OrderUi.phoneLine(o, displayedName: Fmt.displayName(o.contactName, o.waId)))
    }

    func testABlankNameFallsBackToThePhoneAndHidesTheLine() {
        let o = order("255754333222", name: "   ")
        XCTAssertNil(OrderUi.phoneLine(o, displayedName: Fmt.displayName(o.contactName, o.waId)))
    }

    func testTheWebsNameIsTheBareWaIdWithTheFormattedPhoneUnderIt() {
        let o = order("254712345678")
        XCTAssertEqual(o.customerName, "254712345678")
        XCTAssertEqual(OrderUi.phoneLine(o, displayedName: o.customerName), Fmt.formatPhone("254712345678"))
    }

    /// The row's one-line summary and the detail's short id, as the web prints them.
    func testItemSummaryAndShortId() {
        var o = order("254712345678")
        o.items = [OrderItem(name: "Clergy Shirt", qty: 2, unit: 3500, total: 7000), OrderItem(name: "Collar", qty: 1, unit: 250, total: 250), OrderItem(name: "Stole", qty: 1)]
        let s = OrderUi.itemSummary(o)
        XCTAssertEqual(s.text, "Clergy Shirt ×2, Collar")
        XCTAssertEqual(s.more, 1)
        XCTAssertEqual(OrderUi.shortId(Order(id: "254712345678_1773480600000")), "80600000")
        XCTAssertEqual(OrderUi.qtyText(2), "2")
        XCTAssertEqual(OrderUi.qtyText(1.5), "1.5")
        XCTAssertEqual(OrderUi.money(1284750), "KES 1,284,750")
        XCTAssertEqual(OrderUi.money(nil, " "), "KES 0")
    }
}
