import Foundation
import XCTest
@testable import NeemaCore

/// Round 2: the edge paths of lib/utils.ts and the dashboard's nav (Android `CoreRound2Test`).
final class CoreRound2Tests: XCTestCase {
    override func setUp() {
        AppClock.pin(to: PINNED)
        Fmt.timeZone = TimeZone(identifier: "Africa/Nairobi")!
    }

    override func tearDown() {
        AppClock.reset()
        Fmt.timeZone = .current
    }

    func testDatesUseEnKeShortMonthsWithSept() {
        // node: new Date(...).toLocaleDateString("en-KE", {day:"numeric", month:"short", year:"numeric"})
        XCTAssertEqual("5 Sept 2026", Fmt.date("2026-09-05T12:00:00Z"))
        XCTAssertEqual("25 Sept 2026", Fmt.date("2026-09-25T08:00:00+03:00"))
        XCTAssertEqual("5 Jan 2026", Fmt.date("2026-01-05T12:00:00Z"))
        XCTAssertEqual("31 Dec 2025", Fmt.date("2025-12-31T12:00:00Z"))
        XCTAssertEqual("5 May 2026", Fmt.date("2026-05-05T12:00:00Z"))
        XCTAssertEqual("5 Jun 2026", Fmt.date("2026-06-05T12:00:00Z"))
        // Every other month is the same three letters Java uses.
        let expected = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec"]
        for (i, m) in expected.enumerated() {
            XCTAssertEqual("1 \(m) 2026", Fmt.date(String(format: "2026-%02d-01T12:00:00Z", i + 1)))
        }
    }

    func testDateTimeAndDayLabelShareTheWebMonths() {
        XCTAssertEqual("5 Sept 2026, 15:30", Fmt.dateTime("2026-09-05T12:30:00Z"))
        XCTAssertEqual("1 Sept 2025", Fmt.dayLabel("2025-09-01T12:00:00Z"))
        XCTAssertEqual("Today", Fmt.dayLabel(ISO8601DateFormatter().string(from: AppClock.date())))
    }

    func testMissingOrBrokenDatesReadAsADash() {
        XCTAssertEqual("—", Fmt.date(nil))
        XCTAssertEqual("—", Fmt.date(""))
        XCTAssertEqual("—", Fmt.date("not a date"))
        XCTAssertEqual("—", Fmt.dateTime(nil))
        XCTAssertEqual("", Fmt.time(nil))
    }

    func testWebsiteVisitorsGetThePersonGlyph() {
        XCTAssertEqual("Website visitor", Fmt.displayName(nil, "web_3f9a1c"))
        XCTAssertTrue(isPhoneLike(Fmt.displayName(nil, "web_3f9a1c")))
        XCTAssertTrue(isPhoneLike("website visitor"))
        XCTAssertTrue(isPhoneLike("web_3f9a1c"))
        // A real name that merely starts like it keeps its initials.
        XCTAssertFalse(isPhoneLike("Website Visitors Ltd"))
        XCTAssertFalse(isPhoneLike("Webster Ouma"))
    }

    func testBadgesArePassedThroughUncapped() {
        // Sidebar.tsx prints the count as is ("143"), never "99+".
        let items = ShellRules.navItems(can: { _ in true }, humanConvs: 143, pendingOrders: 0)
        XCTAssertEqual(143, items.first { $0.view == .conversations }?.badge)
        XCTAssertEqual(0, items.first { $0.view == .orders }?.badge)
    }

    func testNavOrderMatchesDesktopNavItems() {
        let all = ShellRules.navItems(can: { _ in true }, humanConvs: 0, pendingOrders: 0).map { $0.view }
        XCTAssertEqual(
            [.conversations, .calls, .orders, .reports, .deals, .leads, .overview, .catalog, .agents, .settings, .profile],
            all
        )
        // A legacy agent: view_leads and view_catalog, nothing admin.
        let agent = Perms.effective(role: "agent", isSuperuser: false, permissions: nil)
        XCTAssertEqual(
            [.conversations, .calls, .orders, .deals, .leads, .catalog, .profile],
            ShellRules.navItems(can: { agent.contains($0) }, humanConvs: 0, pendingOrders: 0).map { $0.view }
        )
    }
}
