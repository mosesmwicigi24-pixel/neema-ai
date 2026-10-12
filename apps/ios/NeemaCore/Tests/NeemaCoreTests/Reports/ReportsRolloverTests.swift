import Foundation
import XCTest
@testable import NeemaCore

/// The rest of Android `ReportsRolloverTest`: the two overnight roll-overs
/// live in `ReportsLifecycleTests` and the web's customer naming in
/// `ReportMathTests`; what is left is the catalogue's column count on a
/// degenerate width.
final class ReportsRolloverTests: XCTestCase {
    func testCatalogColumnsNeverFewerThanOne() {
        XCTAssertEqual(CatalogRules.columns(width: 0), 1)
        XCTAssertEqual(CatalogRules.columns(width: -20), 1)
        XCTAssertEqual(CatalogRules.columns(width: 360), 2)
        XCTAssertEqual(CatalogRules.columns(width: 360, fontScale: 2), 1)
        XCTAssertEqual(CatalogRules.columns(width: 1200), 6)
    }
}
