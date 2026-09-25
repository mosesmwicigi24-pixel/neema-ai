package ke.co.bethanyhouse.neema.app

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.InboxSummary
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * app/dashboard/page.tsx's state: who is signed in and what they may open,
 * the badges, live notifications (toast + refetch), session expiry and
 * re-auth, sign-out, deep links, and the polls' foreground behaviour.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class DashboardViewModelTest {
    // Only for a Context (layoutlib); nothing is rendered here.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)

    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    private fun agentJson(
        id: String, name: String, role: String, superuser: Boolean = false,
        custom: String = "null", rolePerms: String = "null",
    ) = """{"id":"$id","name":"$name","email":"${name.lowercase().replace(' ', '.')}@bethanyhouse.co.ke","role":"$role",
        "is_available":true,"is_superuser":$superuser,"active_convs":0,"avatar_url":null,"created_at":"${Fixtures.ago(9000)}",
        "last_seen_at":null,"custom_role_id":null,"custom_permissions":$custom,"role_name":null,"role_color":null,"role_permissions":$rolePerms}"""

    /** A dashboard signed in as [me] (who is also on the team list). */
    private fun signedInAs(me: String, role: String, fake: FakeNeema = FakeNeema.withFixtures()): DashboardViewModel {
        fake.on("GET", "/admin/me", body = me)
        fake.on("GET", "/admin/agents", body = "[$me]")
        return dashboard(paparazzi.context, fake, role = role, superuser = false)
    }

    private fun DashboardViewModel.ids() = navItems().map { it.id }

    // ── Nav gating ──────────────────────────────────────────────────────────

    @Test
    fun aSuperuserSeesEveryView() {
        val dash = dashboard(paparazzi.context)
        assertEquals(
            listOf(
                ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Reports, ViewId.Deals, ViewId.Leads,
                ViewId.Overview, ViewId.Catalog, ViewId.Agents, ViewId.Settings, ViewId.Profile,
            ),
            dash.ids(),
        )
        assertTrue(dash.isAdmin)
    }

    @Test
    fun aCustomRoleGetsExactlyItsPermissions() {
        // Grace's "Sales" role: conversations, orders, catalog, CRM, leads — no reports/analytics/team/settings.
        val sales = """["view_conversations","reply_conversations","view_orders","manage_orders","view_catalog","view_crm","edit_crm","view_leads"]"""
        val dash = signedInAs(agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "agent", rolePerms = sales), "agent")
        assertEquals(
            listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Deals, ViewId.Leads, ViewId.Catalog, ViewId.Profile),
            dash.ids(),
        )
        assertFalse(dash.isAdmin)
    }

    @Test
    fun perAgentOverridesBeatTheRole() {
        val dash = signedInAs(
            agentJson(
                Fixtures.AGENT2_ID, "Grace Wanjiru", "agent",
                custom = """["view_conversations","view_reports","manage_settings"]""",
                rolePerms = """["view_leads","view_catalog"]""",
            ),
            "agent",
        )
        assertEquals(listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Reports, ViewId.Settings, ViewId.Profile), dash.ids())
    }

    @Test
    fun legacyReadonlyFallsBackToTheSeededPermissions() {
        val dash = signedInAs(agentJson(Fixtures.AGENT3_ID, "Brian Otieno", "readonly"), "readonly")
        assertEquals(
            listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Deals, ViewId.Leads, ViewId.Overview, ViewId.Catalog, ViewId.Profile),
            dash.ids(),
        )
    }

    @Test
    fun anEmptyCustomListMeansTheLegacyRole() {
        val dash = signedInAs(agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "agent", custom = "[]"), "agent")
        assertEquals(
            listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Deals, ViewId.Leads, ViewId.Catalog, ViewId.Profile),
            dash.ids(),
        )
    }

    @Test
    fun anAdminRoleWithoutSuperuserStillSeesEverything() {
        val dash = signedInAs(agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "admin"), "admin")
        assertEquals(11, dash.ids().size)
        assertTrue(dash.isAdmin)
    }

    @Test
    fun manageAgentsAloneMakesAnAdmin() {
        val dash = signedInAs(agentJson(Fixtures.AGENT2_ID, "Grace Wanjiru", "agent", custom = """["manage_agents"]"""), "agent")
        assertTrue(dash.isAdmin)
        assertTrue(ViewId.Agents in dash.ids())
    }

    @Test
    fun beforeTheTeamLoadsTheSessionRoleDecides() {
        // Deliberate difference: the web hides every gated item until the team
        // list lands (can() is false with no agent row); the app uses the
        // signed-in role's defaults meanwhile so the nav doesn't jump.
        val fake = FakeNeema.withFixtures()
        fake.on("GET", "/admin/me", code = 500, body = "{}")
        fake.on("GET", "/admin/agents", code = 500, body = "{}")
        val dash = dashboard(paparazzi.context, fake, role = "agent", superuser = false)
        assertEquals(
            listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Deals, ViewId.Leads, ViewId.Catalog, ViewId.Profile),
            dash.ids(),
        )
    }

    @Test
    fun theMeRequestRetriesThreeTimes() {
        val fake = FakeNeema.withFixtures()
        fake.on("GET", "/admin/me", code = 503, body = "{}")
        dashboard(paparazzi.context, fake)
        advance(2_000)
        assertEquals(3, fake.callsTo("GET", "/admin/me").size)
    }

    // ── Badges ──────────────────────────────────────────────────────────────

    @Test
    fun badgesCountHumanChatsAndPendingOrders() {
        val dash = dashboard(paparazzi.context)
        dash.inboxSummary.value = InboxSummary(human = 2, unread = 5)
        val items = dash.navItems().associateBy { it.id }
        assertEquals(2, items.getValue(ViewId.Conversations).badge)
        // Fixture o2 is an "open" cart → shown (and counted) as pending, as mapOrder() does.
        assertEquals(1, items.getValue(ViewId.Orders).badge)
        assertEquals(0, items.getValue(ViewId.Calls).badge)
    }

    // ── Live notifications ──────────────────────────────────────────────────

    private fun live(fake: FakeNeema = FakeNeema.withFixtures()): Triple<DashboardViewModel, FakeSocketFactory, FakeNeema> {
        val ws = FakeSocketFactory()
        val dash = dashboard(paparazzi.context, fake, appDispatcher = Dispatchers.Unconfined, wsFactory = ws)
        dash.container.notifications.start(dash.container.foreground)
        dash.container.socket.connect(Fixtures.ME_ID)
        ws.last.open()
        return Triple(dash, ws, fake)
    }

    @Test
    fun aNotificationToastsAndLandsInTheBell() {
        val (dash, ws) = live()
        val toasts = mutableListOf<Toast>()
        CoroutineScope(main).launch { dash.toasts.collect { toasts += it } }

        ws.last.frame("""{"event":"notification","type":"intercept","title":"🙋 Grace picked up","body":"Conversation with 254712345678","conversationId":"c1"}""")

        assertEquals("🙋 Grace picked up: Conversation with 254712345678", toasts.single().message)
        assertEquals(ToastType.Info, toasts.single().type)
        val n = dash.container.notifications.items.value.single()
        assertEquals("c1", n.convKey)
        assertFalse(n.read)
    }

    @Test
    fun inboxEventsRefreshTheInboxShortlyAfter() {
        val (dash, ws) = live()
        var refreshes = 0
        CoroutineScope(main).launch { dash.inboxRefresh.collect { refreshes++ } }
        for (type in listOf("new_conversation", "human_transfer", "intercept", "transfer", "media_escalation")) {
            ws.last.frame("""{"event":"notification","type":"$type","title":"t","body":"b"}""")
        }
        advance(799)
        assertEquals(0, refreshes)
        advance(2)
        assertEquals(5, refreshes)
        ws.last.frame("""{"event":"notification","type":"system","title":"Released","body":"b"}""")
        advance(1_000)
        assertEquals("other types don't refetch the inbox", 5, refreshes)
    }

    @Test
    fun orderUpdatesRefetchOrders() {
        val (_, ws, fake) = live()
        val before = fake.callsTo("GET", "/admin/orders").size
        ws.last.frame("""{"event":"notification","type":"order_update","title":"Order paid","body":"BH-1042"}""")
        advance(801)
        assertEquals(before + 1, fake.callsTo("GET", "/admin/orders").size)
    }

    @Test
    fun otherFramesAreNotNotifications() {
        val (dash, ws) = live()
        ws.last.frame("""{"type":"new_message","conversationId":"c1","text":"hi"}""")
        assertTrue(dash.container.notifications.items.value.isEmpty())
    }

    // ── Session expiry, re-auth, sign-out ───────────────────────────────────

    @Test
    fun anUnrescuable401OpensTheSessionExpiredPrompt() {
        val fake = FakeNeema.withFixtures()
        fake.on("GET", "/admin/agents", code = 401, body = """{"detail":"Could not validate credentials"}""")
        fake.on("POST", "/agent-auth/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val dash = dashboard(paparazzi.context, fake)
        assertTrue(dash.sessionExpired.value)
        assertEquals("3 refresh attempts before giving up", 3, fake.callsTo("POST", "/agent-auth/refresh").size)

        // Re-auth: everything refetches, the prompt closes.
        fake.on("GET", "/admin/agents", body = Fixtures.agents)
        var refreshed = false
        CoroutineScope(main).launch { dash.inboxRefresh.collect { refreshed = true } }
        val n = fake.calls.size
        dash.onReauthenticated()
        assertFalse(dash.sessionExpired.value)
        val after = fake.calls.drop(n).map { it.path }
        assertTrue(after.toString(), listOf("/admin/me", "/admin/agents", "/admin/orders", "/admin/catalog").all { it in after })
        assertTrue(refreshed)
    }

    @Test
    fun aNextAuthSessionsRoleComesFromAdminMe() {
        // A NextAuth sign-in (route.ts) carries no role: the session starts as "agent".
        val c = ke.co.bethanyhouse.neema.testing.testContainer(paparazzi.context, FakeNeema.withFixtures(), role = "agent", superuser = false)
        c.sessionStore.save(c.sessionStore.current!!.copy(mode = "nextauth", refreshToken = null, name = "moses@bethanyhouse.co.ke"))
        val dash = DashboardViewModel(c)
        assertEquals("admin", dash.session.value!!.role)
        assertTrue(dash.session.value!!.isSuperuser)
        assertEquals("Moses Mwicigi", dash.session.value!!.name)
    }

    @Test
    fun aDirectSessionKeepsTheRoleItsTokensCameWith() {
        val dash = dashboard(paparazzi.context, FakeNeema.withFixtures(), role = "agent", superuser = false)
        assertEquals("agent", dash.session.value!!.role)
        assertFalse(dash.session.value!!.isSuperuser)
    }

    @Test
    fun aRescued401IsInvisible() {
        val fake = FakeNeema.withFixtures()
        var first = true
        fake.on("GET", "/admin/orders") { _, _ -> if (first) { first = false; 401 to "{}" } else 200 to Fixtures.orders }
        fake.on("POST", "/agent-auth/refresh", body = """{"access_token":"${ke.co.bethanyhouse.neema.testing.fakeJwt()}.x","refresh_token":"r2"}""")
        val dash = dashboard(paparazzi.context, fake)
        assertFalse(dash.sessionExpired.value)
        assertEquals(4, dash.orders.value.size)
    }

    @Test
    fun signingOutClearsEverything() {
        val (dash, _) = live()
        dash.container.notifications.markAllRead()
        dash.applyDeepLink(open = "254712345678", ref = null, view = null, caller = null)
        dash.navigate(ViewId.Orders)
        dash.logout()
        assertNull(dash.session.value)
        assertNull(dash.me.value)
        assertTrue(dash.agents.value.isEmpty() && dash.orders.value.isEmpty() && dash.catalog.value.isEmpty())
        assertTrue(dash.container.notifications.items.value.isEmpty())
        assertNull(dash.openConvKey.value)
        assertEquals(ViewId.Conversations, dash.view.value)
        assertEquals("the re-auth prompt remembers who it was", "moses@bethanyhouse.co.ke", dash.container.sessionStore.lastEmail)
    }

    @Test
    fun errorTextIsFriendly() {
        val dash = dashboard(paparazzi.context)
        assertEquals("Network problem — check your connection", dash.errorText(ApiException(0, "GET", "/x", "reset")))
        assertEquals("Order not found", dash.errorText(ApiException(404, "GET", "/x", """{"detail":"Order not found"}""")))
        assertEquals("boom", dash.errorText(IllegalStateException("boom")))
    }

    // ── Deep links (?open= / ?view= / ?caller=) ─────────────────────────────

    @Test
    fun deepLinksOpenChatsViewsAndTheCallConsole() {
        val dash = dashboard(paparazzi.context)
        dash.navigate(ViewId.Orders)
        dash.applyDeepLink(open = "254712345678", ref = "BH-1042", view = "calls", caller = "x")
        assertEquals("open wins over view", "254712345678|BH-1042", dash.openConvKey.value)
        assertEquals(ViewId.Conversations, dash.view.value)

        dash.applyDeepLink(open = null, ref = null, view = "calls", caller = "254722000111")
        assertEquals(ViewId.Calls, dash.view.value)
        assertEquals("254722000111", dash.callsFocusKey.value)

        dash.applyDeepLink(open = null, ref = null, view = "reports", caller = null)
        assertEquals(ViewId.Reports, dash.view.value)

        dash.applyDeepLink(open = null, ref = null, view = "nonsense", caller = null)
        assertEquals("unknown views are ignored", ViewId.Reports, dash.view.value)

        dash.applyDeepLink(open = "254700000000", ref = "", view = null, caller = null)
        assertEquals("254700000000", dash.openConvKey.value)
    }

    @Test
    fun webViewNamesMapToScreens() {
        val names = listOf("conversations", "calls", "orders", "deals", "leads", "reports", "agents", "catalog", "overview", "profile", "settings")
        assertEquals(
            listOf(
                ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Deals, ViewId.Leads, ViewId.Reports,
                ViewId.Agents, ViewId.Catalog, ViewId.Overview, ViewId.Profile, ViewId.Settings,
            ),
            names.map { ViewId.fromWeb(it) },
        )
        assertNull(ViewId.fromWeb(null))
    }

    // ── Polls ───────────────────────────────────────────────────────────────

    @Test
    fun pollsPauseInTheBackgroundAndRefetchOnReturn() {
        val fake = FakeNeema.withFixtures()
        val dash = dashboard(paparazzi.context, fake)
        fun orders() = fake.callsTo("GET", "/admin/orders").size
        assertEquals("fetched at once", 1, orders())
        advance(90_000)
        assertEquals("then every 90 s", 2, orders())

        dash.container.foreground.value = false
        advance(400_000)
        assertEquals("no ticks while backgrounded", 2, orders())

        dash.container.foreground.value = true
        assertEquals("coming back refetches at once", 3, orders())
        advance(89_000)
        assertEquals(3, orders())
    }

    @Test
    fun returningMidIntervalRefetchesImmediately() {
        val fake = FakeNeema.withFixtures()
        val dash = dashboard(paparazzi.context, fake)
        fun agents() = fake.callsTo("GET", "/admin/agents").size
        assertEquals(1, agents())
        dash.container.foreground.value = false
        advance(10_000)
        dash.container.foreground.value = true
        assertEquals("the web refetches on visibilitychange", 2, agents())
    }
}
