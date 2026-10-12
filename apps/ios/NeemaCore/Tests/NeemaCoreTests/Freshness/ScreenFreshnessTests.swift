import Foundation
import XCTest
@testable import NeemaCore

/// How every non-inbox screen stays fresh (round 4, Android
/// `ScreenFreshnessTest`): the web views' polls, run only while the screen is
/// on display and the app in front; a reload on each return to the screen
/// (the web view's remount), to the app, and after the live socket
/// reconnects; and the live notifications that move a screen's figures. Time
/// is virtual: `advance` moves the polls along. (The analytics, catalog and
/// Coalescer rows live in `OverviewLifecycleTests`, `CatalogViewModelTests`
/// and `FlowsTests`.)
@MainActor
final class ScreenFreshnessTests: XCTestCase {
    var fake: FakeNeema!
    var hosts: [TestHost] = []
    var closers: [() -> Void] = []

    override func setUp() async throws {
        try await super.setUp()
        AppClock.pin(to: PINNED)
        ReportsFixtures.pinTimeZone()
        fake = Fixtures.withFixtures()
        SalesFixtures.install(fake)
    }

    override func tearDown() async throws {
        for c in closers { c() }
        closers = []
        for h in hosts { h.logout() }
        hosts = []
        ReportsFixtures.restoreTimeZone()
        AppClock.reset()
        try await super.tearDown()
    }

    /// A signed-in dashboard (its orders poll running) with its live socket open.
    func live() async -> TestHost {
        let h = TestHost(fake: fake, ordersFeed: true)
        hosts.append(h)
        await drain()
        _ = await eventually(timeout: 10) { !(h.feed?.reading ?? false) }
        h.connectLive()
        await drain()
        return h
    }

    func advance(_ h: TestHost, _ ms: Int64) async { await h.clock.advance(by: ms); await drain() }

    /// The socket drops (frames are lost from here) and comes back.
    func dropAndReconnect(_ h: TestHost) async {
        h.sockets.last.fail()
        h.socket.nudge()
        h.sockets.last.open()
        await drain()
    }

    func notify(_ h: TestHost, _ type: String, title: String = "Neema", body: String = "") {
        h.sockets.last.frame("{\"event\":\"notification\",\"type\":\"\(type)\",\"title\":\"\(title)\",\"body\":\"\(body)\"}")
    }

    func gets(_ path: String) -> Int { fake.callsTo("GET", path).count }
    func gets(_ path: String, _ query: String) -> Int { fake.callsTo("GET", path).filter { $0.query == query }.count }

    func deals(_ h: TestHost) async -> DealsViewModel {
        let v = DealsViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        return v
    }

    func overview(_ h: TestHost) async -> OverviewViewModel {
        let v = OverviewViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.statsLoading }
        await drain()
        return v
    }

    func orders(_ h: TestHost) async -> OrdersViewModel {
        let v = OrdersViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        return v
    }

    func leads(_ h: TestHost) async -> LeadsViewModel {
        let v = LeadsViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.loading }
        await drain()
        return v
    }

    func reports(_ h: TestHost) async -> ReportsViewModel {
        _ = try? await h.refreshAgents()
        let v = ReportsViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        _ = await eventually(timeout: 30) { v.ui.allConvs != nil || v.ui.loadError != nil }
        if v.ui.allConvs != nil { _ = await eventually(timeout: 30) { v.ui.report != nil } }
        await drain()
        return v
    }

    func team(_ h: TestHost) async -> TeamViewModel {
        // The dashboard's team list, as `dashboard()` reads it at sign-in.
        _ = try? await h.refreshAgents()
        let v = TeamViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await drain()
        _ = await eventually(timeout: 10) { !v.ui.rolesLoading }
        await drain()
        return v
    }

    func settings(_ h: TestHost) async -> SettingsViewModel {
        let v = SettingsViewModel(host: h, sleep: h.clock.sleeper)
        closers.append { v.close() }
        await settled(v)
        return v
    }

    func settled(_ v: SettingsViewModel) async {
        await drain()
        _ = await eventually(timeout: 10) { !v.busy }
        await drain()
    }

    // ── Deals: 60 s poll, only on display ───────────────────────────────────

    func testDealsPollsEveryMinuteOnlyWhileOnDisplay() async {
        let h = await live()
        let vm = await deals(h)
        XCTAssertEqual(1, gets("/admin/actions"), "mount-time load")

        await advance(h, 60_001)
        XCTAssertEqual(2, gets("/admin/actions"), "the 60 s poll")

        // Off to another screen: the interval stops, as the web view's does when it unmounts.
        vm.life.shown.update(false)
        await advance(h, 10 * 60_000)
        XCTAssertEqual(2, gets("/admin/actions"))

        // Back to Deals: one reload (the remount), then the minute poll again.
        vm.life.shown.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(3, gets("/admin/actions"))
        await advance(h, 60_001)
        XCTAssertEqual(4, gets("/admin/actions"))
    }

    func testDealsPausesInTheBackgroundAndCatchesUpOnReturn() async {
        let h = await live()
        _ = await deals(h)
        h.foreground.update(false)
        await advance(h, 30 * 60_000)
        XCTAssertEqual(1, gets("/admin/actions"), "nothing while the app is in the background")

        h.foreground.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(2, gets("/admin/actions"), "the return reloads at once, not a minute later")
    }

    func testAPlannedActionReloadsTheQueueOnceForABurst() async {
        let h = await live()
        _ = await deals(h)
        // actions.py `_notify`: a follow-up moved into the approval queue — three at once.
        for _ in 0..<3 { notify(h, "planned_action", title: "⏳ Follow-up needs your approval", body: "outside the 24h messaging window") }
        await advance(h, ScreenLife.EVENT_WINDOW_MS - 1)
        XCTAssertEqual(1, gets("/admin/actions"), "the web's 800 ms")
        await advance(h, 2)
        XCTAssertEqual(2, gets("/admin/actions"), "one reload for the burst")
        XCTAssertEqual(2, gets("/admin/deals", "status=open"))
    }

    func testAHubEventReloadsTheBoardButOtherNotificationsDoNot() async {
        let h = await live()
        _ = await deals(h)
        notify(h, "new_conversation"); notify(h, "standup"); notify(h, "selfcheck")
        await advance(h, 1_000)
        XCTAssertEqual(1, gets("/admin/deals", "status=open"))
        // hub_events: an order.paid closes the conversation's open deal as won.
        notify(h, "hub_event", title: "🎉 Order paid")
        await advance(h, ScreenLife.EVENT_WINDOW_MS + 1)
        XCTAssertEqual(2, gets("/admin/deals", "status=open"))
        XCTAssertEqual(2, gets("/admin/deals", "status=won"))
    }

    func testAPlannedActionOffScreenWaitsForTheNextVisit() async {
        let h = await live()
        let vm = await deals(h)
        vm.life.shown.update(false)
        notify(h, "planned_action")
        await advance(h, 5_000)
        XCTAssertEqual(1, gets("/admin/actions"))
        vm.life.shown.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(2, gets("/admin/actions"))
    }

    func testDealsCatchesUpAfterTheSocketReconnects() async {
        let h = await live()
        _ = await deals(h)
        await dropAndReconnect(h)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(2, gets("/admin/actions"))
    }

    func testAReturnAndAReconnectTogetherCostOneReload() async {
        let h = await live()
        _ = await deals(h)
        h.foreground.update(false)
        h.foreground.update(true)
        await dropAndReconnect(h)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(2, gets("/admin/actions"))
    }

    // ── order_update: Orders, the Analytics figures, the pending badge ─────

    func testAnOrderUpdateRefreshesOrdersTheBadgeAndTheFigures() async {
        let h = await live()
        _ = await overview(h)
        func badge() -> Int { h.feed!.pendingOrders }
        let pendingBefore = badge()
        let statsBefore = gets("/admin/stats")

        // A new pending order lands server-side.
        let newRow = Fixtures.orderRow("o9", "254700000009", "[]", "1500.0", "pending", "whatsapp", 1)
        fake.on("GET", "/admin/orders", body: SalesFixtures.ordersJson([newRow] + SalesFixtures.orders))
        notify(h, "order_update", title: "Order placed", body: "254700000009")
        await advance(h, ScreenLife.EVENT_WINDOW_MS + 1)

        XCTAssertEqual(pendingBefore + 1, badge())
        XCTAssertTrue(h.orders.value.contains { $0.id == "o9" })
        // The figures follow the orders change through their own 800 ms window.
        await advance(h, ScreenLife.EVENT_WINDOW_MS + 1)
        XCTAssertTrue(gets("/admin/stats") > statsBefore, "the Analytics figures follow")
    }

    func testOrdersRereadOnReturnAndAfterAReconnect() async {
        let h = await live()
        let vm = await orders(h)
        let start = gets("/admin/orders")

        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(start + 1, gets("/admin/orders"))

        await dropAndReconnect(h)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(start + 2, gets("/admin/orders"))

        // The dashboard's poll owns the foreground return: no second fetch from the screen.
        h.foreground.update(false)
        h.foreground.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(start + 3, gets("/admin/orders"))
    }

    func testAReconnectOffScreenFetchesNothing() async {
        let h = await live()
        let vm = await orders(h)
        vm.life.shown.update(false)
        let start = gets("/admin/orders")
        await dropAndReconnect(h)
        await advance(h, 5_000)
        XCTAssertEqual(start, gets("/admin/orders"))
    }

    // ── Screens the web loads once per visit ────────────────────────────────

    func testLeadsRereadOnReturnQuietly() async {
        let h = await live()
        let vm = await leads(h)
        let shown = vm.ui.leads
        XCTAssertFalse(shown.isEmpty)
        fake.on("GET", "/admin/leads", code: 500, body: #"{"detail":"boom"}"#)
        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(2, gets("/admin/leads"))
        XCTAssertEqual(shown, vm.ui.leads, "a failed background re-read keeps the board")
        XCTAssertTrue(h.toasts.isEmpty, "and says nothing")
        XCTAssertFalse(vm.ui.loading)
    }

    func testLeadsRereadWhenTheAppComesBack() async {
        let h = await live()
        _ = await leads(h)
        h.foreground.update(false)
        await advance(h, 60 * 60_000)
        XCTAssertEqual(1, gets("/admin/leads"))
        h.foreground.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(2, gets("/admin/leads"))
    }

    func testReportsDownloadOncePerVisitNeverOnATimer() async {
        let h = await live()
        let vm = await reports(h)
        func full() -> Int { fake.callsTo("GET", "/admin/conversations").filter { $0.query == nil }.count }
        XCTAssertEqual(1, full())
        await advance(h, 30 * 60_000)
        h.foreground.update(false)
        h.foreground.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        XCTAssertEqual(1, full(), "no poll, no reload on returning to the app")
        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        _ = await eventually(timeout: 10) { full() == 2 }
        XCTAssertEqual(2, full(), "the next visit re-reads it")
    }

    func testTheTeamIsFreshEachTimeItOpens() async {
        let h = await live()
        let vm = await team(h)
        let agentsBefore = gets("/admin/agents")
        let offlineBefore = h.agents.value.filter { !$0.isAvailable }.count
        // A colleague went offline meanwhile.
        var changed = Fixtures.agents
        if let r = changed.range(of: "\"is_available\":true") { changed.replaceSubrange(r, with: "\"is_available\":false") }
        fake.on("GET", "/admin/agents", body: changed)
        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        _ = await eventually(timeout: 10) { !vm.ui.rolesLoading && self.gets("/admin/agents") == agentsBefore + 1 }
        await drain()
        XCTAssertEqual(agentsBefore + 1, gets("/admin/agents"))
        XCTAssertEqual(2, gets("/admin/roles"))
        XCTAssertEqual(offlineBefore + 1, h.agents.value.filter { !$0.isAvailable }.count, "the availability change shows")
    }

    func testTheTeamPullToRefreshWaitsForTheList() async {
        let h = await live()
        let vm = await team(h)
        let before = gets("/admin/agents")
        vm.refresh()
        await drain()
        _ = await eventually(timeout: 10) { !vm.ui.refreshing }
        XCTAssertEqual(before + 1, gets("/admin/agents"))
        XCTAssertFalse(vm.ui.refreshing)
    }

    func testSettingsRereadsOnReturnButKeepsUnsavedTyping() async {
        let h = await live()
        let vm = await settings(h)
        vm.setDirectives("Half-written standing order")
        fake.on("GET", "/admin/settings/translation", body: #"{"enabled":false,"default":false,"spend_30d_usd":0,"calls_30d":0}"#)
        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        await settled(vm)
        XCTAssertEqual("Half-written standing order", vm.ui.directives)
        XCTAssertEqual(1, gets("/admin/settings/directives"))
        XCTAssertEqual(false, vm.ui.translation?.enabled)
        XCTAssertEqual(2, gets("/admin/settings/offer"), "the untouched offer is re-read")
        XCTAssertEqual(2, gets("/admin/settings/pipeline-stages"))
    }

    func testSettingsRereadsUntouchedStandingOrders() async {
        let h = await live()
        let vm = await settings(h)
        fake.on("GET", "/admin/settings/directives", body: #"{"directives":"New orders from a colleague","max_chars":2000}"#)
        vm.life.shown.update(false)
        vm.life.shown.update(true)
        await advance(h, ScreenLife.CATCH_UP_WINDOW_MS + 1)
        await settled(vm)
        XCTAssertEqual("New orders from a colleague", vm.ui.directives)
    }
}
