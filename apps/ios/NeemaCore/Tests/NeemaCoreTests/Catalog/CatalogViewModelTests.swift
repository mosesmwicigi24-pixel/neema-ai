import Foundation
import XCTest
@testable import NeemaCore

/// The catalog screen's behaviour against the fake API: the shared feed, the
/// audit, filters, the empty and error states, refresh, the five-minute poll
/// and the state a reclaim brings back.
@MainActor
final class CatalogViewModelTests: XCTestCase {
    var fake: FakeNeema!
    var host: TestHost!
    var hosts: [TestHost] = []
    var vms: [CatalogViewModel] = []

    override func setUp() async throws {
        try await super.setUp()
        ReportsFixtures.pinTimeZone()
        fake = Fixtures.withFixtures()
        ReportsFixtures.install(fake)
        host = await signedIn()
    }

    override func tearDown() async throws {
        for v in vms { v.close() }
        vms = []
        for h in hosts { h.logout() }
        hosts = []
        ReportsFixtures.restoreTimeZone()
        try await super.tearDown()
    }

    func signedIn(snapshots: SnapshotCache? = nil) async -> TestHost {
        let h = TestHost(fake: fake, snapshots: snapshots, catalogFeed: true)
        hosts.append(h)
        await drain()
        _ = await eventually(timeout: 10) { !(h.catalogFeed?.reading ?? false) }
        await drain()
        return h
    }

    func vm(_ h: TestHost? = nil) async -> CatalogViewModel {
        let on = h ?? host!
        let v = CatalogViewModel(host: on, sleep: on.clock.sleeper)
        vms.append(v)
        await drain()
        return v
    }

    func reads() -> (catalog: Int, audit: Int) { (fake.callsTo("GET", "/admin/catalog").count, fake.callsTo("GET", "/admin/catalog/audit").count) }

    func testFirstLoadComesFromTheFeedAndTheAuditLoads() async {
        XCTAssertEqual(host.catalog.value.count, 6)
        let vm = await vm()
        let v = vm.view
        XCTAssertEqual(v.total, 6)
        XCTAssertEqual(v.inStock, 5)
        XCTAssertEqual(v.outStock, 1)
        XCTAssertEqual(v.categories, ["Clergy Apparel", "Clergy Vestments", "Anointing Oil", "Communion Wafers", "Prefilled Cups"])
        XCTAssertEqual(vm.ui.audit?.currencyGaps.count, 3)
        XCTAssertEqual(vm.ui.audit?.perPiece.count, 2)
        XCTAssertEqual(vm.ui.audit?.rate, 130)
        XCTAssertNil(vm.ui.catalogError)
        // The screen's own model did not re-read a catalogue the feed already holds.
        XCTAssertEqual(reads().catalog, 1)
    }

    func testFilterAndSearchDriveTheView() async {
        let vm = await vm()
        vm.setFilter("Clergy Vestments")
        XCTAssertEqual(vm.view.filtered.map { $0.sku }, ["CAS-PUR"])
        vm.setFilter("all"); vm.setSearch("communion")
        XCTAssertEqual(vm.view.filtered.map { $0.sku }, ["WAF-500", "CUP-PF", "TRAY-1"])
        vm.setSearch("zzz")
        XCTAssertTrue(vm.view.filtered.isEmpty)
        XCTAssertEqual(vm.view.total, 6, "the header's counts are the whole catalogue's")
    }

    func testAnEmptyCatalogueAfterAFailedReadSaysWhyAndRetryLoadsIt() async {
        fake.on("GET", "/admin/catalog", code: 503, body: "{}")
        let h = await signedIn()
        XCTAssertTrue(h.catalog.value.isEmpty)
        let vm = await vm(h)
        XCTAssertEqual(vm.ui.catalogError, FriendlyErrors.DOWN_TEXT)
        ReportsFixtures.install(fake)
        vm.retry()
        // The spinner lasts until the catalogue AND the audit have landed; a slow runner needs more than one drain.
        await drain()
        _ = await eventually(timeout: 5) { !vm.ui.refreshing }
        XCTAssertNil(vm.ui.catalogError)
        XCTAssertEqual(vm.view.total, 6)
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testAServerErrorReadsTheCatalogueFallbackWords() async {
        fake.on("GET", "/admin/catalog", code: 500, body: "<html>500</html>")
        let h = await signedIn()
        let vm = await vm(h)
        XCTAssertEqual(vm.ui.catalogError, "The server couldn't send the catalogue just now.")
        fake.failOffline("GET", "/admin/catalog")
        vm.retry(); await drain()
        XCTAssertEqual(vm.ui.catalogError, FriendlyErrors.OFFLINE_TEXT)
    }

    func testARefreshThatFailsWithProductsOnScreenToastsAndKeepsThem() async {
        let vm = await vm()
        fake.htmlPage("GET", "/admin/catalog", code: 502)
        vm.refresh()
        await drain()
        XCTAssertEqual(host.catalog.value.count, 6)
        XCTAssertEqual(host.toasts.last?.type, .error)
        XCTAssertEqual(host.toasts.last?.message, "Couldn't refresh the catalogue. \(FriendlyErrors.DOWN_TEXT)")
        XCTAssertFalse(vm.ui.refreshing)
        // The next good read clears what it remembered.
        ReportsFixtures.install(fake)
        host.catalogFeed!.refetchCatalog()
        await drain()
        XCTAssertNil(vm.ui.catalogError)
    }

    func testARefreshWithNothingOnScreenSaysItInPlaceNotInAToast() async {
        fake.on("GET", "/admin/catalog", code: 503, body: "{}")
        let h = await signedIn()
        let vm = await vm(h)
        let before = h.toasts.count
        vm.refresh(); await drain()
        XCTAssertEqual(h.toasts.count, before)
        XCTAssertEqual(vm.ui.catalogError, FriendlyErrors.DOWN_TEXT)
    }

    func testAnAuditThatFailsStaysHidden() async {
        fake.on("GET", "/admin/catalog/audit", code: 500, body: "{}")
        let vm = await vm()
        XCTAssertNil(vm.ui.audit)
        XCTAssertTrue(host.toasts.isEmpty)
        XCTAssertEqual(vm.view.total, 6)
        // A later good audit shows up on the next refresh.
        fake.on("GET", "/admin/catalog/audit", body: ReportsFixtures.audit)
        vm.refresh(); await drain()
        XCTAssertEqual(vm.ui.audit?.checked, 6)
    }

    func testPullToRefreshReadsBothOnce() async {
        let vm = await vm()
        let before = reads()
        vm.refresh()
        vm.refresh() // a second pull while one runs is ignored
        await drain()
        XCTAssertEqual(reads().catalog, before.catalog + 1)
        XCTAssertEqual(reads().audit, before.audit + 1)
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testReturningToTheScreenRereadsTheAuditAndTheCatalogue() async {
        let vm = await vm()
        let before = reads()
        vm.life.catchUpNow()
        await host.clock.advance(by: ScreenLife.CATCH_UP_WINDOW_MS + 1)
        await drain()
        XCTAssertEqual(reads().catalog, before.catalog + 1)
        XCTAssertEqual(reads().audit, before.audit + 1)
    }

    func testTheFiveMinutePollRereadsOnlyWhileInFront() async {
        _ = await vm()
        let before = reads().catalog
        await host.clock.advance(by: CatalogFeed.POLL_MS + 1); await drain()
        XCTAssertEqual(reads().catalog, before + 1)
        host.foreground.update(false)
        await host.clock.advance(by: CatalogFeed.POLL_MS + 1); await drain()
        XCTAssertEqual(reads().catalog, before + 1, "nothing polls in the background")
        host.foreground.update(true)
        await drain()
        XCTAssertEqual(reads().catalog, before + 2, "a return refetches at once")
    }

    func testFilterSearchAndAuditOpenSurviveAReclaim() async {
        let a = await vm()
        a.setFilter("Clergy Apparel"); a.setSearch("shirt"); a.setAuditOpen(true)
        let saved = JSONValue.parse(JSONValue.object(a.saveUi()).text)!.objectValue!
        let b = await vm()
        XCTAssertTrue(b.restoreIfFresh(saved))
        XCTAssertEqual(b.ui.filter, "Clergy Apparel")
        XCTAssertEqual(b.ui.search, "shirt")
        XCTAssertTrue(b.ui.auditOpen)
        XCTAssertEqual(b.view.filtered.map { $0.sku }, ["CS-BLK"])
        // A model a frame has drawn keeps what was typed since.
        b.setSearch("typed later")
        XCTAssertFalse(b.restoreIfFresh(saved))
        XCTAssertEqual(b.ui.search, "typed later")
    }

    func testTheViewFollowsTheFeedsPoll() async {
        let vm = await vm()
        XCTAssertEqual(vm.view.total, 6)
        ReportsFixtures.installBig(fake)
        host.catalogFeed!.refetchCatalog()
        await drain()
        XCTAssertEqual(vm.view.total, 7)
        vm.setSearch("kasula")
        XCTAssertEqual(vm.view.filtered.map { $0.sku }, ["KAS-DHB-XL-HANDMADE-2026"])
    }

    func testHubDownTheLocalTableDecodesAndReadsAsNotHub() async {
        fake.on("GET", "/admin/catalog", body: ReportsFixtures.localCatalog)
        let h = await signedIn()
        let vm = await vm(h)
        XCTAssertEqual(vm.view.total, 2)
        XCTAssertEqual(vm.view.categories, ["Clergy Apparel"])
        XCTAssertFalse(vm.view.filtered[0].isHub)
        XCTAssertNil(vm.ui.catalogError)
    }

    func testTheSnapshotPaintsTheNextSignIn() async {
        let snaps = SnapshotCache.temporary()
        let h = await signedIn(snapshots: snaps)
        XCTAssertEqual(h.catalog.value.count, 6)
        h.logout()
        XCTAssertTrue(h.catalog.value.isEmpty)
        fake.on("GET", "/admin/catalog", code: 503, body: "{}")
        let again = TestHost(fake: fake, snapshots: snaps, catalogFeed: true)
        hosts.append(again)
        XCTAssertEqual(again.catalog.value.count, 6, "painted from the snapshot before any read")
        let vm = await vm(again)
        XCTAssertEqual(vm.view.total, 6)
        XCTAssertNil(vm.ui.catalogError, "the screen did not ask: the feed held a catalogue")
    }

    func testARefusedCatalogueRereadsWhoThisAgentIs() async {
        fake.on("GET", "/admin/catalog", code: 403, body: #"{"detail":"Forbidden"}"#)
        let h = await signedIn()
        let vm = await vm(h)
        XCTAssertEqual(vm.ui.catalogError, "You don't have permission to do that.")
        await h.clock.advance(by: TestHost.FORBIDDEN_WINDOW_MS + 1); await drain()
        XCTAssertEqual(h.accessRereads, 1)
    }
}
