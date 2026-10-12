import Foundation
import XCTest
@testable import NeemaCore

/// Analytics and the catalogue on a bad phone network (the rows of Android
/// `InsightsNetworkTest` not already in `ReportsViewModelTests`,
/// `CatalogViewModelTests` or `FriendlyErrorsTests`): partial failures on the
/// Analytics screen, its poll and pull failing, a garbled answer, and the
/// audit's refresh failing with a banner already shown.
final class InsightsNetworkTests: OverviewTestCase {
    private var catalogs: [CatalogViewModel] = []

    override func tearDown() async throws {
        for c in catalogs { c.close() }
        catalogs = []
        try await super.tearDown()
    }

    // ---- Analytics: partial failures ----

    func testOverviewStatsDownOtherPanelsStillLoadAndTheCardsSayTheyAreAnEstimate() async {
        fake.htmlPage("GET", "/admin/stats", code: 502)
        let vm = await vm()
        XCTAssertNil(vm.ui.stats)
        XCTAssertEqual(vm.ui.statsError, FriendlyErrors.DOWN_TEXT)
        XCTAssertNotNil(vm.ui.attrib, "attribution loaded on its own")
        XCTAssertNotNil(vm.ui.humanRows, "the intercept feed loaded on its own")
        XCTAssertFalse(vm.ui.statsLoading)
        // Retry once the server is back: the notice goes.
        fake.on("GET", "/admin/stats", body: ReportsFixtures.stats)
        vm.refresh()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        await drain()
        XCTAssertNotNil(vm.ui.stats)
        XCTAssertNil(vm.ui.statsError)
    }

    func testOverviewAttributionAndInterceptsDownStatsStillShow() async {
        fake.timeout("GET", "/admin/attribution")
        fake.on("GET", "/admin/conversations") { _, _ in throw TransportError.timedOut }
        let vm = await vm()
        XCTAssertNotNil(vm.ui.stats)
        XCTAssertNil(vm.ui.statsError)
        XCTAssertNil(vm.ui.attrib)
        XCTAssertTrue(errors.isEmpty)
    }

    func testOverviewPollFailingKeepsTheFiguresQuietly() async {
        let vm = await vm()
        let before = vm.ui.stats
        XCTAssertNotNil(before)
        fake.failOffline("GET", "/admin/stats")
        vm.life.catchUpNow()
        await advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(vm.ui.stats, before)
        XCTAssertNil(vm.ui.statsError)
    }

    func testOverviewPullToRefreshFailingKeepsTheFiguresAndSaysSo() async {
        let vm = await vm()
        fake.failOffline("GET", "/admin/stats")
        vm.refresh()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        await drain()
        XCTAssertNotNil(vm.ui.stats)
        XCTAssertEqual(errors, ["Couldn't refresh the figures. \(FriendlyErrors.OFFLINE_TEXT)"])
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testOverviewGarbledStatsNoCrash() async {
        fake.on("GET", "/admin/stats", body: #"{"open_conversations": "lots", "channel_breakdown": 3"#)
        let vm = await vm()
        XCTAssertNil(vm.ui.stats)
        XCTAssertEqual(vm.ui.statsError, FriendlyErrors.GARBLED_TEXT)
    }

    // ---- Catalog ----

    func testCatalogAuditRefreshFailingKeepsTheBannerAlreadyShown() async {
        let vm = CatalogViewModel(host: host, sleep: host.clock.sleeper)
        catalogs.append(vm)
        await drain()
        _ = await eventually(timeout: 10) { vm.ui.audit != nil }
        let shown = vm.ui.audit
        XCTAssertNotNil(shown)
        fake.timeout("GET", "/admin/catalog/audit")
        vm.refresh()
        await drain()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        XCTAssertEqual(vm.ui.audit, shown)
    }
}
