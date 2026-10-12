import XCTest
@testable import NeemaCore

/// Android `app/DashboardViewModelTest`, `app/DashboardRealtimeTest` and
/// `app/DashboardStressTest`, the parts NeemaCore holds: who may open what
/// (`ShellRules` over the team row), the badges, the live feed's routing
/// (an `order_update` refetches orders, a notification lands in the bell,
/// other frames do nothing), session expiry and the rescued 401, sign-out,
/// deep links as actions, and the orders poll's foreground behaviour. The
/// replays of a deep link or a notification tap stashed while signed out,
/// /admin/me's retries and the agents poll live in the app's `AppModel`.
@MainActor
final class DashboardRulesTests: XCTestCase {
    private var fake: FakeNeema!
    private var host: TestHost?
    private var centers: [AgentNotifications] = []

    override func setUp() async throws {
        AppClock.pin(to: PINNED)
        fake = Fixtures.withFixtures()
    }

    override func tearDown() async throws {
        for c in centers { c.stop() }
        centers = []
        host?.logout()
        host = nil
        AppClock.reset()
    }

    private func signedIn(role: String = "admin", superuser: Bool = true) -> TestHost {
        let h = TestHost(fake: fake, role: role, superuser: superuser, ordersFeed: true)
        host = h
        return h
    }

    /// A signed-in host with the live socket open (Android's `live()`).
    private func live() async -> TestHost {
        let h = signedIn()
        await drain()
        h.connectLive()
        await drain()
        return h
    }

    /// The bell over the host's socket (`AppModel.notifications`).
    private func bell(_ h: TestHost) -> AgentNotifications {
        let nc = AgentNotifications(events: h.socket.events, appPrefs: AppPrefs(store: MemoryPrefs()), store: MemoryPrefs(), sink: RecordingTray())
        nc.start(foreground: h.foreground)
        centers.append(nc)
        return nc
    }

    private func orders() -> Int { fake.callsTo("GET", "/admin/orders").count }

    private func agentJson(_ id: String, _ name: String, _ role: String, superuser: Bool = false,
                           custom: String = "null", rolePerms: String = "null") -> String {
        let email = name.lowercased().replacingOccurrences(of: " ", with: ".") + "@bethanyhouse.co.ke"
        return """
        {"id":"\(id)","name":"\(name)","email":"\(email)","role":"\(role)",
        "is_available":true,"is_superuser":\(superuser),"active_convs":0,"avatar_url":null,"created_at":"\(Fixtures.ago(9000))",
        "last_seen_at":null,"custom_role_id":null,"custom_permissions":\(custom),"role_name":null,"role_color":null,"role_permissions":\(rolePerms)}
        """
    }

    private func session(_ id: String = Fixtures.ME_ID, role: String, superuser: Bool = false) -> Session {
        Session(accessToken: "t", refreshToken: nil, agentId: id, email: "moses@bethanyhouse.co.ke", name: "", role: role, isSuperuser: superuser, mode: "direct")
    }

    /// The access of a dashboard signed in as `me` (who is also on the team list) - `AppModel.republishAccess`.
    private func signedInAs(_ me: String, _ role: String) throws -> Access {
        let row = try NeemaJSON.decode(Agent.self, from: me)
        return ShellRules.access(agents: [row], me: row, session: session(row.id, role: role))
    }

    private func ids(_ a: Access, humanConvs: Int = 0, pendingOrders: Int = 0) -> [ViewId] {
        ShellRules.navItems(can: { a.can($0) }, humanConvs: humanConvs, pendingOrders: pendingOrders).map { $0.view }
    }

    private let all: [ViewId] = [.conversations, .calls, .orders, .reports, .deals, .leads, .overview, .catalog, .agents, .settings, .profile]

    // -- Nav gating --------------------------------------------------------------

    func testASuperuserSeesEveryView() async throws {
        let team = try NeemaJSON.decode([Agent].self, from: Fixtures.agents)
        let a = ShellRules.access(agents: team, me: nil, session: session(role: "admin", superuser: true))
        XCTAssertEqual(all, ids(a))
        XCTAssertTrue(a.isAdmin)
    }

    func testACustomRoleGetsExactlyItsPermissions() async throws {
        // Grace's "Sales" role: conversations, orders, catalog, CRM, leads - no reports/analytics/team/settings.
        let sales = #"["view_conversations","reply_conversations","view_orders","manage_orders","view_catalog","view_crm","edit_crm","view_leads"]"#
        let a = try signedInAs(agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "agent", rolePerms: sales), "agent")
        XCTAssertEqual([.conversations, .calls, .orders, .deals, .leads, .catalog, .profile], ids(a))
        XCTAssertFalse(a.isAdmin)
    }

    func testPerAgentOverridesBeatTheRole() async throws {
        let a = try signedInAs(
            agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "agent",
                      custom: #"["view_conversations","view_reports","manage_settings"]"#,
                      rolePerms: #"["view_leads","view_catalog"]"#),
            "agent"
        )
        XCTAssertEqual([.conversations, .calls, .orders, .reports, .settings, .profile], ids(a))
    }

    func testLegacyReadonlyFallsBackToTheSeededPermissions() async throws {
        let a = try signedInAs(agentJson(Fixtures.AGENT3_ID, "Brian Otieno", "readonly"), "readonly")
        XCTAssertEqual([.conversations, .calls, .orders, .deals, .leads, .overview, .catalog, .profile], ids(a))
    }

    func testAnEmptyCustomListMeansTheLegacyRole() async throws {
        let a = try signedInAs(agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "agent", custom: "[]"), "agent")
        XCTAssertEqual([.conversations, .calls, .orders, .deals, .leads, .catalog, .profile], ids(a))
    }

    func testAnAdminRoleWithoutSuperuserStillSeesEverything() async throws {
        let a = try signedInAs(agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "admin"), "admin")
        XCTAssertEqual(11, ids(a).count)
        XCTAssertTrue(a.isAdmin)
    }

    func testManageAgentsAloneMakesAnAdmin() async throws {
        let a = try signedInAs(agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "agent", custom: #"["manage_agents"]"#), "agent")
        XCTAssertTrue(a.isAdmin)
        XCTAssertTrue(ids(a).contains(.agents))
    }

    func testBeforeTheTeamLoadsNothingGatedShows() async {
        // As page.tsx: can() is false while there is no team row, whatever
        // the session's role - gated items appear once the team list lands.
        let a = ShellRules.access(agents: [], me: nil, session: session(role: "agent"))
        XCTAssertEqual([.conversations, .calls, .orders, .profile], ids(a))
        XCTAssertTrue(a.permissions.isEmpty)
    }

    // -- Badges ------------------------------------------------------------------

    func testBadgesCountHumanChatsAndPendingOrders() async {
        let d = signedIn()
        await drain()
        let summary = InboxSummary(unread: 5, human: 2)
        let items = ShellRules.navItems(can: { _ in true }, humanConvs: summary.human, pendingOrders: d.feed!.pendingOrders)
        func badge(_ v: ViewId) -> Int { items.first { $0.view == v }!.badge }
        XCTAssertEqual(2, badge(.conversations))
        // Fixture o2 is an "open" cart -> shown (and counted) as pending, as mapOrder() does.
        let open = d.orders.value.filter { $0.rawStatus == "open" }
        XCTAssertEqual(["o2"], open.map { $0.id })
        XCTAssertTrue(open.allSatisfy { $0.status == "pending" })
        XCTAssertEqual(1, badge(.orders))
        XCTAssertEqual(d.orders.value.filter { $0.status == "pending" }.count, badge(.orders))
        XCTAssertEqual(0, badge(.calls))
    }

    // -- Live notifications ------------------------------------------------------

    func testANotificationLandsInTheBell() async {
        // Android also toasts "title: body" (Info); the iOS shell has no toast for a bell entry.
        let d = await live()
        let nc = bell(d)
        let seen = Ref<[AppNotification]>([])
        let sub = nc.incoming.observe { n in seen.mutate { $0.append(n) } }
        defer { sub.cancel() }
        d.sockets.last.frame(#"{"event":"notification","type":"intercept","title":"Grace picked up","body":"Conversation with 254712345678","conversationId":"c1"}"#)
        await drain()
        XCTAssertEqual(1, seen.value.count)
        XCTAssertEqual("Grace picked up", seen.value.first?.title)
        XCTAssertEqual("Conversation with 254712345678", seen.value.first?.body)
        XCTAssertEqual(1, nc.items.value.count)
        let n = nc.items.value[0]
        XCTAssertEqual("c1", n.convKey)
        XCTAssertFalse(n.read)
    }

    func testOrderUpdatesRefetchOrders() async {
        let d = await live()
        let before = orders()
        d.sockets.last.frame(#"{"event":"notification","type":"order_update","title":"Order paid","body":"BH-1042"}"#)
        await d.clock.advance(by: 801)
        await drain()
        XCTAssertEqual(before + 1, orders())
    }

    func testOtherFramesAreNotNotifications() async {
        let d = await live()
        let nc = bell(d)
        d.sockets.last.frame(#"{"type":"new_message","conversationId":"c1","text":"hi"}"#)
        await drain()
        XCTAssertTrue(nc.items.value.isEmpty)
    }

    // -- Session expiry, re-auth, sign-out ---------------------------------------

    func testAnUnrescuable401OpensTheSessionExpiredPrompt() async {
        fake.on("GET", "/admin/agents", code: 401, body: #"{"detail":"Could not validate credentials"}"#)
        fake.on("POST", "/agent-auth/refresh", code: 401, body: #"{"detail":"Invalid refresh token"}"#)
        let d = signedIn()
        _ = await expectApi { try await d.refreshAgents() }
        let expired = await eventually { d.sessionExpired.value }
        XCTAssertTrue(expired)
        XCTAssertEqual(1, fake.callsTo("POST", "/agent-auth/refresh").count, "a refusal is final at once (no retries of a verdict)")

        // Re-auth: the prompt closes (AppModel.onReauthenticated then refetches everything).
        fake.on("GET", "/admin/agents", body: Fixtures.agents)
        d.onReauthenticated()
        XCTAssertFalse(d.sessionExpired.value)
        _ = try? await d.refreshAgents()
        XCTAssertFalse(d.agents.value.isEmpty)
    }

    func testARescued401IsInvisible() async {
        let first = Ref(true)
        fake.on("GET", "/admin/orders") { _, _ in
            if first.value { first.value = false; return (401, "{}") }
            return (200, Fixtures.orders)
        }
        fake.on("POST", "/agent-auth/refresh", body: #"{"access_token":"\#(fakeJwt()).x","refresh_token":"r2"}"#)
        let d = signedIn()
        let landed = await eventually { !d.orders.value.isEmpty }
        XCTAssertTrue(landed)
        XCTAssertFalse(d.sessionExpired.value)
        XCTAssertEqual(JSONValue.parse(Fixtures.orders)?.arrayValue?.count, d.orders.value.count)
        XCTAssertEqual(1, fake.callsTo("POST", "/agent-auth/refresh").count)
    }

    func testSigningOutClearsEverything() async {
        let d = await live()
        let nc = bell(d)
        d.sockets.last.frame(#"{"event":"notification","type":"intercept","title":"a","body":"b","conversationId":"c1"}"#)
        await drain()
        nc.markAllRead()
        d.openConvKey.value = "254712345678"
        d.inboxSummary.value = InboxSummary(unread: 1, human: 1)
        d.logout()
        nc.clear()  // AppModel.finishLogout: the bell empties with the session
        XCTAssertNil(d.session.value)
        XCTAssertTrue(d.orders.value.isEmpty)
        XCTAssertTrue(nc.items.value.isEmpty)
        XCTAssertNil(d.openConvKey.value)
        XCTAssertNil(d.inboxSummary.value)
        XCTAssertEqual(1000, d.sockets.last.closedWith)
        XCTAssertEqual("moses@bethanyhouse.co.ke", d.sessionStore.lastEmail, "the re-auth prompt remembers who it was")
    }

    func testErrorTextIsFriendly() async {
        XCTAssertEqual(ErrorText.OFFLINE, ErrorText.of(ApiError(status: 0, method: "GET", path: "/x", body: "reset")))
        XCTAssertEqual("Order not found", ErrorText.of(ApiError(status: 404, method: "GET", path: "/x", body: #"{"detail":"Order not found"}"#)))
        XCTAssertEqual("boom", ErrorText.of(PlainError("boom")))
    }

    // -- Deep links (?open= / ?view= / ?caller=) ---------------------------------

    func testDeepLinksOpenChatsViewsAndTheCallConsole() async {
        XCTAssertEqual(.openConversation(key: "254712345678|BH-1042"),
                       DeepLink(open: "254712345678", ref: "BH-1042", view: "calls", caller: "x").action, "open wins over view")
        XCTAssertEqual(.focusCalls(waId: "254722000111"), DeepLink(view: "calls", caller: "254722000111").action)
        XCTAssertEqual(.navigate(.reports), DeepLink(view: "reports").action)
        XCTAssertNil(DeepLink(view: "nonsense").action, "unknown views are ignored")
        XCTAssertEqual(.openConversation(key: "254700000000"), DeepLink(open: "254700000000", ref: "").action)
    }

    func testWebViewNamesMapToScreens() async {
        let names = ["conversations", "calls", "orders", "deals", "leads", "reports", "agents", "catalog", "overview", "profile", "settings"]
        XCTAssertEqual([.conversations, .calls, .orders, .deals, .leads, .reports, .agents, .catalog, .overview, .profile, .settings],
                       names.map { ViewId.fromWeb($0) })
        XCTAssertNil(ViewId.fromWeb(nil))
    }

    func testALinkWhileRunningAppliesAtOnce() async {
        // AppModel.applyDeepLink acts on the link's action straight away while signed in.
        let open = DeepLink.of { ["open": "254700000000"][$0] }
        XCTAssertEqual(.openConversation(key: "254700000000"), open.action)
        let analytics = DeepLink.of { ["view": "analytics"][$0] }
        XCTAssertEqual(.navigate(.overview), analytics.action)
    }

    func testAnEmptyLinkChangesNothing() async {
        XCTAssertTrue(DeepLink.of { _ in nil }.isEmpty)
        let refOnly = DeepLink(open: nil, ref: "BH-1", view: nil, caller: "x")
        XCTAssertTrue(refOnly.isEmpty)
        XCTAssertNil(refOnly.action)
    }

    // -- Notification taps -------------------------------------------------------

    func testTappingAnAlertOpensItsThreadAndMarksItRead() async {
        let d = await live()
        let nc = bell(d)
        d.sockets.last.frame(#"{"event":"notification","type":"intercept","title":"AI Escalation","body":"x","conversationId":"c-77"}"#)
        await drain()
        let n = nc.items.value[0]
        // AppModel.openNotification: read, then the conversation it names (no view of its own).
        nc.markRead(n.id)
        XCTAssertEqual("c-77", n.convKey)
        XCTAssertNil(AgentNotifications.viewFor(n))
        XCTAssertTrue(nc.items.value[0].read)
    }

    func testTappingAnOrderAlertOpensOrders() async {
        let n = AppNotification(id: "n1", type: "order_update", title: "Order paid", body: "BH-1042", at: 1)
        XCTAssertEqual("orders", AgentNotifications.viewFor(n))
        XCTAssertEqual(.orders, ViewId.fromWeb(AgentNotifications.viewFor(n)))
    }

    // -- Polls -------------------------------------------------------------------

    func testPollsPauseInTheBackgroundAndRefetchOnReturn() async {
        let d = signedIn()
        await drain()
        XCTAssertEqual(1, orders(), "fetched at once")
        await d.clock.advance(by: 90_000)
        await drain()
        XCTAssertEqual(2, orders(), "then every 90 s")

        d.foreground.value = false
        await d.clock.advance(by: 400_000)
        await drain()
        XCTAssertEqual(2, orders(), "no ticks while backgrounded")

        d.foreground.value = true
        let back = await eventually { self.orders() == 3 }
        XCTAssertTrue(back, "coming back refetches at once")
        await d.clock.advance(by: 89_000)
        await drain()
        XCTAssertEqual(3, orders())
    }

    func testReturningMidIntervalRefetchesImmediately() async {
        // Android proves this on the agents poll (AppModel's here); the orders poll follows the same rule.
        let d = signedIn()
        await drain()
        XCTAssertEqual(1, orders())
        d.foreground.value = false
        await d.clock.advance(by: 10_000)
        d.foreground.value = true
        let back = await eventually { self.orders() == 2 }
        XCTAssertTrue(back, "the web refetches on visibilitychange")
    }

    // -- Missed frames (DashboardRealtimeTest) -----------------------------------

    func testAReconnectCatchesUpTheInboxAndOrders() async {
        let d = await live()
        let refreshes = Ref(0)
        let sub = d.inboxRefresh.observe { refreshes.mutate { $0 += 1 } }
        defer { sub.cancel() }
        let before = orders()
        await d.clock.advance(by: 60_000)

        d.sockets.last.fail()          // the network drops; frames are lost from here
        await d.clock.advance(by: 2_001)
        let retried = await eventually { d.sockets.count == 2 }
        XCTAssertTrue(retried)
        XCTAssertEqual(0, refreshes.value, "nothing until the socket is really back")
        XCTAssertEqual(before, orders())
        d.sockets.last.open()
        let caughtUp = await eventually { self.orders() == before + 1 }
        XCTAssertTrue(caughtUp)
        // The inbox catches itself up on reconnect; the shell must not ping it as well.
        XCTAssertEqual(0, refreshes.value)
    }

    func testTheFirstConnectAfterSignInIsNotACatchUp() async {
        let d = await live()
        let refreshes = Ref(0)
        let sub = d.inboxRefresh.observe { refreshes.mutate { $0 += 1 } }
        defer { sub.cancel() }
        XCTAssertEqual(0, refreshes.value)
        XCTAssertEqual(1, orders(), "only the poll's own first fetch")
    }

    func testOrdersJustFetchedAreNotFetchedAgainOnReconnect() async {
        let d = await live()
        let before = orders()
        await d.clock.advance(by: 1_000) // the poll ran a second ago (e.g. the app just came to the front)
        d.sockets.last.fail()
        await d.clock.advance(by: 2_001)
        let retried = await eventually { d.sockets.count == 2 }
        XCTAssertTrue(retried)
        d.sockets.last.open()
        await drain()
        XCTAssertEqual(before, orders(), "no refetch storm")
    }

    func testComingBackWithoutLiveModeCatchesUpToo() async {
        let d = await live()
        await d.clock.advance(by: 600_000)
        await drain()
        let before = orders()
        d.socket.disconnect() // backgrounded, live mode off
        d.connectLive()
        let caughtUp = await eventually { self.orders() == before + 1 }
        XCTAssertTrue(caughtUp)
        XCTAssertGreaterThanOrEqual(orders(), 2)
    }

    func testABurstOfAlertsIsOneRefreshAndNeverDuplicates() async {
        let d = await live()
        let nc = bell(d)
        for i in 0..<10 {
            d.sockets.last.frame(#"{"event":"notification","type":"new_conversation","title":"New chat \#(i)","body":"hi","wa_id":"2547\#(i)"}"#)
        }
        // The same frame twice (a double publish) is one alert.
        d.sockets.last.frame(#"{"event":"notification","type":"new_conversation","title":"New chat 9","body":"hi","wa_id":"25479"}"#)
        await drain()
        XCTAssertEqual(10, nc.items.value.count)
    }

    // -- A busy shop (DashboardStressTest) ---------------------------------------

    func testTwoHundredInboxAlertsInABurstKeepTheBellBounded() async {
        let d = await live()
        let nc = bell(d)
        for i in 0..<200 {
            d.sockets.last.frame(#"{"event":"notification","type":"new_conversation","title":"New chat \#(i)","body":"hi","wa_id":"2547\#(i)"}"#)
        }
        await drain()
        XCTAssertEqual(60, nc.items.value.count, "the bell stays bounded")
        XCTAssertEqual("New chat 199", nc.items.value[0].title, "newest first")
    }

    func testPollsSleepInTheBackgroundAndCatchUpOnceOnReturn() async {
        let d = await live()
        let start = orders()
        d.foreground.value = false
        await d.clock.advance(by: 30 * 60_000) // half an hour in a pocket
        await drain()
        XCTAssertEqual(start, orders(), "nothing polls in the background")
        d.foreground.value = true
        let back = await eventually { self.orders() == start + 1 }
        XCTAssertTrue(back, "one fetch on return")
        await d.clock.advance(by: 89_000)
        await drain()
        XCTAssertEqual(start + 1, orders())
        await d.clock.advance(by: 2_000)
        await drain()
        XCTAssertEqual(start + 2, orders(), "then the 90 s rhythm")
    }

    func testManyTokenRefreshesAndReturnsNeverStackPolls() async {
        let d = await live()
        // A token refresh saves a new Session for the same agent 50 times; the feed is started per agent, not per token.
        let s = d.session.value!
        for _ in 0..<50 {
            d.sessionStore.save(Session(accessToken: fakeJwt(), refreshToken: s.refreshToken, agentId: s.agentId, email: s.email, name: s.name,
                                        role: s.role, isSuperuser: s.isSuperuser, mode: s.mode))
            d.feed!.start(agentId: s.agentId)
        }
        await drain()
        let afterRefreshes = orders()
        await d.clock.advance(by: 91_000)
        await drain()
        XCTAssertEqual(afterRefreshes + 1, orders(), "one poller, one tick")
        await d.clock.advance(by: 90_000)
        await drain()
        XCTAssertEqual(afterRefreshes + 2, orders())
    }
}
