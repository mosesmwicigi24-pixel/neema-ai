import Foundation
import XCTest
@testable import NeemaCore

/// lib/utils.ts, lib/permissions.ts and the api.ts mappers (Android `CoreLogicTest`).
final class CoreLogicTests: XCTestCase {
    func testPhoneLikeNamesGetAGlyphNotInitials() {
        // The bug: an unnamed contact's avatar read "+7" (initials of "+254 712 345 678").
        XCTAssertTrue(isPhoneLike(Fmt.displayName(nil, "254712345678")))
        XCTAssertTrue(isPhoneLike("+1 (202) 555-1234"))
        XCTAssertTrue(isPhoneLike("254712345678"))
        XCTAssertTrue(isPhoneLike(Fmt.displayName("", "25898765432101234"))) // "Messenger ID ..."
        XCTAssertFalse(isPhoneLike("Fr. Peter Kamau"))
        XCTAssertFalse(isPhoneLike("Room 101"))
        XCTAssertFalse(isPhoneLike("   "))
        XCTAssertFalse(isPhoneLike(nil))
    }

    func testInitialsMatchTheWeb() {
        XCTAssertEqual("FP", Fmt.initials("Fr. Peter Kamau"))
        XCTAssertEqual("MM", Fmt.initials("moses mwicigi"))
        XCTAssertEqual("G", Fmt.initials("Grace"))
        XCTAssertEqual("?", Fmt.initials(nil))
        XCTAssertEqual("?", Fmt.initials("  "))
    }

    func testPhonesFormatByCountryAsFormatPhoneDoes() {
        XCTAssertEqual("+254 712 345 678", Fmt.formatPhone("254712345678"))
        XCTAssertEqual("+254 712 345 678", Fmt.formatPhone("+254712345678"))
        XCTAssertEqual("+44 7911 123456", Fmt.formatPhone("447911123456"))
        XCTAssertEqual("+1 (202) 555-1234", Fmt.formatPhone("12025551234"))
        XCTAssertEqual("+33 6 12 34 56 78", Fmt.formatPhone("33612345678"))
        XCTAssertEqual("+49 301 2345 67", Fmt.formatPhone("49301234567"))
        XCTAssertEqual("+27 82 123 4567", Fmt.formatPhone("27821234567"))
        XCTAssertEqual("+91 98765 43210", Fmt.formatPhone("919876543210"))
        XCTAssertEqual("+255 754 333 222", Fmt.formatPhone("255754333222"))
        XCTAssertEqual("Messenger ID 25898765432101234", Fmt.formatPhone("25898765432101234"))
        XCTAssertEqual("", Fmt.formatPhone(nil))
        XCTAssertEqual("Unknown", Fmt.displayName(" ", ""))
        XCTAssertEqual("Mary", Fmt.displayName(" Mary ", "254"))
    }

    func testTimeAgoMatchesTheWeb() {
        let now: Int64 = 1_750_000_000_000
        func iso(_ msAgo: Int64) -> String { ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: Double(now - msAgo) / 1000)) }
        XCTAssertEqual("—", Fmt.timeAgo(nil, now: now))
        XCTAssertEqual("—", Fmt.timeAgo("garbage", now: now))
        XCTAssertEqual("just now", Fmt.timeAgo(iso(-5_000), now: now))
        XCTAssertEqual("42s ago", Fmt.timeAgo(iso(42_000), now: now))
        XCTAssertEqual("5m ago", Fmt.timeAgo(iso(5 * 60_000), now: now))
        XCTAssertEqual("3h ago", Fmt.timeAgo(iso(3 * 3_600_000), now: now))
        XCTAssertEqual("2d ago", Fmt.timeAgo(iso(49 * 3_600_000), now: now))
    }

    func testPermissionsResolveAsGetAgentPermissions() {
        XCTAssertEqual(Perms.ALL, Perms.effective(role: "readonly", isSuperuser: true, permissions: ["view_orders"]))
        XCTAssertEqual(["view_orders"], Perms.effective(role: "admin", isSuperuser: false, permissions: ["view_orders"]))
        XCTAssertEqual(Perms.ALL, Perms.effective(role: "admin", isSuperuser: false, permissions: []))
        XCTAssertEqual(11, Perms.effective(role: "agent", isSuperuser: false, permissions: nil).count)
        XCTAssertEqual(6, Perms.effective(role: "readonly", isSuperuser: false, permissions: nil).count)
        XCTAssertEqual([], Perms.effective(role: "supervisor", isSuperuser: false, permissions: nil))
        XCTAssertEqual(21, Perms.ALL.count)
        // mapAgent(): custom_permissions ?? role_permissions
        let a = Agent(id: "x", role: "agent", customPermissions: nil, rolePermissions: ["view_reports"])
        XCTAssertEqual(["view_reports"], Perms.of(a))
        var overridden = a
        overridden.customPermissions = ["add_notes"]
        XCTAssertEqual(["add_notes"], Perms.of(overridden))
    }

    func testMappersMatchApiTs() {
        // mapOrder(): an "open" cart shows as pending; the name falls back to the wa_id.
        let o = Order(id: "o1", waId: "254700000000", subtotal: 1200.0, rawStatus: "open")
        XCTAssertEqual("pending", o.status)
        XCTAssertEqual("254700000000", o.customerName)
        XCTAssertEqual(1200.0, o.total, accuracy: 0.0)
        var delivered = o
        delivered.rawStatus = "delivered"
        XCTAssertEqual("delivered", delivered.status)
        // mapCatalogItem(): hub rows get a synthetic id and "General" category.
        let hub = CatalogItem(hubProductId: 501, sku: "CS-BLK")
        XCTAssertEqual("501", hub.id)
        XCTAssertEqual("General", hub.category)
        XCTAssertTrue(hub.isHub)
        XCTAssertEqual("CS-BLK", CatalogItem(sku: "CS-BLK").id)
        XCTAssertFalse(CatalogItem(rawId: "c1", sku: "x").isHub)
    }
}
