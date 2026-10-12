import Foundation
import XCTest
@testable import NeemaCore

/// The analytics model against the fake backend (the overview rows of
/// Android `AreaViewModelTest`): which endpoints it calls with which
/// parameters, and what it does when a call fails.
final class OverviewViewModelTests: OverviewTestCase {
    func testLoadsStatsAttributionAndHumanThreads() async {
        let vm = await vm()
        XCTAssertEqual(vm.ui.stats?.openConversations, 128)
        XCTAssertFalse(vm.ui.statsLoading)
        XCTAssertEqual(vm.ui.attrib?.sources.count, 3)
        // The page holds every thread of each person on it — r1's AI-held Messenger sibling too;
        // the feed filters on intercept_mode, exactly as the web does.
        XCTAssertEqual(vm.ui.humanRows?.map { $0.id }, ["r1", "r5", "r6", "r1b"])
        // The human tab, 10 rows — exactly the web's conversationsApi.page({ tab: "human", limit: 10 }).
        XCTAssertEqual(gets("/admin/conversations"), ["limit=10&tab=human"])
        XCTAssertEqual(vm.ui.fallbackConvs, [])
        XCTAssertTrue(errors.isEmpty)
    }

    func testStatsFailureFallsBackToTheInboxFirstPage() async {
        fake.on("GET", "/admin/stats", code: 500, body: "{}")
        let vm = await vm()
        XCTAssertNil(vm.ui.stats)
        XCTAssertFalse(vm.ui.statsLoading) // skeletons give way to the fallback figures
        XCTAssertEqual(vm.ui.fallbackConvs.count, 9)
        XCTAssertTrue(gets("/admin/conversations").contains("limit=50"))
        XCTAssertEqual(vm.ui.statsError, "The server couldn't count them just now.")
        // Attribution and intercepts still load on their own.
        XCTAssertNotNil(vm.ui.attrib)
        XCTAssertEqual(vm.ui.humanRows?.count, 4)
    }

    /// The web's feed reads `humanRows ?? conversations`: no human tab → the inbox's first page.
    func testHumanTabFailureFallsBackToTheInboxFirstPage() async {
        let convs = ReportsFixtures.conversations
        fake.on("GET", "/admin/conversations") { r, _ in
            if r.param("tab") == "human" { return (500, "{}") }
            return (200, "{\"items\":[\(convs.joined(separator: ","))],\"next_cursor\":null}")
        }
        let vm = await vm()
        XCTAssertNil(vm.ui.humanRows)
        XCTAssertNotNil(vm.ui.stats)
        XCTAssertEqual(vm.ui.fallbackConvs.count, 9)
        XCTAssertEqual(gets("/admin/conversations"), ["limit=10&tab=human", "limit=50"])
    }

    func testAttributionFailureHidesThePanel() async {
        fake.on("GET", "/admin/attribution", code: 500, body: "{}")
        let vm = await vm()
        XCTAssertNil(vm.ui.attrib)
        XCTAssertNotNil(vm.ui.stats)
    }

    func testRefreshFailureKeepsTheFiguresOnScreen() async {
        let vm = await vm()
        fake.on("GET", "/admin/stats", code: 500, body: "{}")
        fake.on("GET", "/admin/attribution", code: 500, body: "{}")
        vm.refresh()
        XCTAssertTrue(vm.ui.refreshing)
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        await drain()
        XCTAssertEqual(vm.ui.stats?.openConversations, 128)
        XCTAssertNotNil(vm.ui.attrib)
        XCTAssertNil(vm.ui.statsError, "figures on screen: no estimate notice")
        XCTAssertFalse(vm.ui.refreshing)
        XCTAssertFalse(gets("/admin/conversations").contains("limit=50"))
        XCTAssertEqual(errors.count, 1)
        XCTAssertTrue(errors[0].hasPrefix("Couldn't refresh the figures. "), errors[0])
        // The pull also re-read what the fallbacks and the feed are built from.
        XCTAssertGreaterThanOrEqual(reads("/admin/orders"), 1)
        XCTAssertGreaterThanOrEqual(reads("/admin/agents"), 1)
        XCTAssertGreaterThanOrEqual(reads("/admin/catalog"), 1)
    }

    /// A pull while one is in flight joins it: one set of reads.
    func testASecondPullWhileRefreshingIsIgnored() async {
        let vm = await vm()
        let before = reads("/admin/stats")
        vm.refresh()
        vm.refresh()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        await drain()
        XCTAssertEqual(reads("/admin/stats"), before + 1)
    }
}
