import Foundation
import XCTest
@testable import NeemaCore

/// The colour choices the Team / Profile screens make for legibility (Android `LegibilityTest`).
final class TeamLegibilityTests: XCTestCase {
    func testEveryRoleColourGetsReadableChipText() {
        for h in ROLE_COLORS {
            let fill = TeamColors.rgb(h)!
            let text: UInt32 = TeamColors.contentOn(fill) == .white ? 0xFFFFFF : TeamColors.INK
            XCTAssertGreaterThanOrEqual(TeamColors.contrast(text, fill), 3, "\(h): chip text at \(TeamColors.contrast(text, fill)):1")
        }
    }

    func testDarkRoleColoursKeepTheWebsWhiteText() {
        for h in ["#427425", "#2a48a2", "#1f367a", "#7c3aed", "#0f766e", "#b45309"] {
            XCTAssertEqual(TeamColors.contentOn(hex: h), .white, h)
        }
    }

    func testPaleFillsGetTheBrandText() {
        XCTAssertEqual(TeamColors.contentOn(0xF59E0B), .ink)
        XCTAssertEqual(TeamColors.contentOn(0xE6F3D8), .ink)
        XCTAssertEqual(TeamColors.contentOn(hex: "nonsense"), .white, "an unparseable fill reads as the brand green")
    }

    /// The secondary text the Team cards and Profile use ("faint") reads on their cards.
    func testSecondaryTextBeatsTheWebsPaleGreen() {
        let web = TeamColors.contrast(0x9CCD65, 0xFFFFFF) // the web's #9ccd65 on white
        let now = TeamColors.contrast(0x699A32, 0xFFFFFF) // textDim on white
        XCTAssertLessThan(web, 2, "web #9ccd65 on white is \(web):1")
        XCTAssertGreaterThanOrEqual(now, 3, "textDim on white is \(now):1")
        XCTAssertGreaterThanOrEqual(TeamColors.contrast(0x8A9E80, 0x0A1229), 4.5) // the dark theme's muted on its card
    }

    func testThePermissionCatalogueMatchesTheWeb() {
        XCTAssertEqual(PermissionCatalog.ALL.count, 20)
        XCTAssertEqual(PermissionCatalog.GROUPS, ["Conversations", "Orders", "Catalog", "CRM", "Reports", "Admin"])
        XCTAssertEqual(PermissionCatalog.inGroup("Admin").map { $0.key }, ["manage_agents", "manage_roles", "manage_settings"])
        XCTAssertEqual(PermissionCatalog.label("export_reports"), "Export reports")
        XCTAssertNil(PermissionCatalog.label("fly"))
        XCTAssertEqual(ROLE_COLORS.count, 12)
    }
}
