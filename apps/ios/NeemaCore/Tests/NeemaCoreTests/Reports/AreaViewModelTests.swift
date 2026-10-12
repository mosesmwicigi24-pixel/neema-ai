import Foundation
import XCTest
@testable import NeemaCore

/// The row of Android `AreaViewModelTest` not already in `ReportsViewModelTests`,
/// `OverviewViewModelTests` or `CatalogViewModelTests`: the catalogue screen
/// reads the audit and never writes.
@MainActor
final class AreaViewModelTests: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!

    override func setUp() async throws {
        try await super.setUp()
        ReportsFixtures.pinTimeZone()
        fake = Fixtures.withFixtures()
        ReportsFixtures.install(fake)
        host = TestHost(fake: fake, catalogFeed: true)
        await drain()
        _ = await eventually(timeout: 10) { !(self.host.catalogFeed?.reading ?? false) }
        await drain()
    }

    override func tearDown() async throws {
        host.logout()
        ReportsFixtures.restoreTimeZone()
        try await super.tearDown()
    }

    func testCatalogLoadsTheAuditAndNeverWrites() async {
        let vm = CatalogViewModel(host: host, sleep: host.clock.sleeper)
        await drain()
        _ = await eventually(timeout: 10) { vm.ui.audit != nil }
        XCTAssertEqual(vm.ui.audit?.currencyGaps.count, 3)
        XCTAssertEqual(host.catalog.value.count, 6)
        XCTAssertEqual(fake.callsTo("GET", "/admin/catalog").map { $0.query }, [nil])
        // Read-only, like the web: the hub is the single source of truth.
        XCTAssertTrue(fake.calls.allSatisfy { $0.method == "GET" || !$0.path.hasPrefix("/admin/catalog") })
        vm.close()
    }
}
