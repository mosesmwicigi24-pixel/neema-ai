package ke.co.bethanyhouse.neema.app

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Persona
import ke.co.bethanyhouse.neema.testing.Personas
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
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 6's permission matrix for the shell: for each persona, what
 * lib/permissions.ts resolves, which nav items page.tsx shows, and isAdmin;
 * then a role edited while the app is open, picked up by the 180 s agents
 * poll (as the web) and by a 403 (the app's reread).
 *
 * The server (apps/api) checks none of these permissions: every /admin route
 * only needs a valid token (get_current_agent). Its only role checks are
 * legacy `role == "admin"` or is_superuser for clear-history and the CRM
 * settings writes, and protected roles can't be edited. The nav is the web's
 * convenience, not a wall.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PermissionMatrixTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)

    @Before fun setUp() = Dispatchers.setMain(main)
    @After fun tearDown() = Dispatchers.resetMain()

    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }

    private fun signIn(p: Persona, fake: FakeNeema = FakeNeema.withFixtures()) =
        dashboard(paparazzi.context, fake, persona = p).also { it.clock = { scheduler.currentTime } }

    private fun DashboardViewModel.ids() = navItems().map { it.id }

    private val all = listOf(
        ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Reports, ViewId.Deals, ViewId.Leads,
        ViewId.Overview, ViewId.Catalog, ViewId.Agents, ViewId.Settings, ViewId.Profile,
    )
    private val readonlyNav = listOf(
        ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Deals, ViewId.Leads, ViewId.Overview, ViewId.Catalog, ViewId.Profile,
    )

    /** persona → (nav, isAdmin), straight from page.tsx's baseNavItems/desktopNavItems and isAdmin. */
    private val matrix = mapOf(
        Persona.Superuser to (all to true),
        Persona.Admin to (all to true),
        Persona.Agent to (listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Deals, ViewId.Leads, ViewId.Catalog, ViewId.Profile) to false),
        Persona.Readonly to (readonlyNav to false),
        Persona.Sales to (listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Profile) to false),
        Persona.Override to (listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Reports, ViewId.Profile) to false),
        Persona.EmptyOverride to (readonlyNav to false),
    )

    @Test
    fun everyPersonaResolvesAsTheWebDoes() {
        Persona.entries.forEach { p ->
            val dash = signIn(p)
            assertEquals("$p permissions", p.expected.toSet(), dash.permissions().toSet())
            Perms.ALL.forEach { perm -> assertEquals("$p can($perm)", perm in p.expected, dash.can(perm)) }
            val (nav, admin) = matrix.getValue(p)
            assertEquals("$p nav", nav, dash.ids())
            assertEquals("$p isAdmin", admin, dash.isAdmin)
            assertEquals("$p access flow", p.expected.toSet(), dash.access.value.permissions)
            assertEquals("$p access.isAdmin", admin, dash.access.value.isAdmin)
        }
    }

    @Test
    fun anEmptyOverrideFallsBackToTheLegacyRoleNotTheCustomRole() {
        val dash = signIn(Persona.EmptyOverride)
        // Sales grants reply_conversations / manage_orders; readonly does not.
        assertFalse(dash.can(Perms.REPLY_CONVERSATIONS))
        assertFalse(dash.can(Perms.MANAGE_ORDERS))
        assertTrue(dash.can(Perms.VIEW_ANALYTICS))
    }

    @Test
    fun settingsIsInTheNavOnlyWithManageSettingsButOpensForAnyone() {
        val dash = signIn(Persona.Readonly)
        assertFalse(ViewId.Settings in dash.ids())
        // The web renders SettingsView for anyone who reaches it (the account
        // menu, ?view=settings); the server decides what they may change.
        dash.applyDeepLink(open = null, ref = null, view = "settings", caller = null)
        assertEquals(ViewId.Settings, dash.view.value)
        dash.navigate(ViewId.Agents)
        assertEquals("no view is refused by the shell", ViewId.Agents, dash.view.value)
    }

    @Test
    fun theSessionRoleAloneMakesAnAdminButGrantsNoPermissions() {
        // page.tsx: isAdmin checks session.user.role before any team row exists; can() does not.
        val fake = FakeNeema.withFixtures()
        fake.on("GET", "/admin/agents", code = 503, body = "{}")
        val dash = dashboard(paparazzi.context, fake, role = "admin", superuser = false)
        assertTrue(dash.isAdmin)
        assertFalse(dash.can(Perms.VIEW_REPORTS))
        assertEquals(listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Profile), dash.ids())
    }

    @Test
    fun aSessionSuperuserFlagIsNotEnoughWithoutTheTeamRow() {
        // page.tsx reads is_superuser from the team row only.
        val fake = FakeNeema.withFixtures()
        fake.on("GET", "/admin/agents", code = 503, body = "{}")
        val dash = dashboard(paparazzi.context, fake, role = "agent", superuser = true)
        assertFalse(dash.isAdmin)
    }

    // ── Persona 8: an admin edits this agent while the app is open ─────────

    @Test
    fun aRoleChangeArrivesWithTheNext180sAgentsPoll() {
        val fake = FakeNeema.withFixtures()
        val dash = signIn(Persona.Superuser, fake)
        assertEquals(all, dash.ids())

        Personas.become(fake, Persona.Sales)
        advance(179_000)
        assertEquals("nothing changes before the poll", all, dash.ids())
        advance(1_000)
        assertEquals(listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Profile), dash.ids())
        assertFalse(dash.can(Perms.MANAGE_AGENTS))
        assertEquals(Persona.Sales.expected.toSet(), dash.access.value.permissions)
        // page.tsx's isAdmin also trusts the session's role, which only a new
        // sign-in changes: signed in as admin, the web keeps isAdmin true too.
        assertTrue(dash.isAdmin)

        // …and back again when the admin restores it.
        Personas.become(fake, Persona.Admin)
        advance(180_000)
        assertEquals(all, dash.ids())
        assertTrue(dash.access.value.isAdmin)
    }

    @Test
    fun aDemotionDropsIsAdminForAnAgentWhoSignedInWithoutTheAdminRole() {
        val fake = FakeNeema.withFixtures()
        // Signed in as a legacy agent who was then given manage_agents by override.
        Personas.install(fake, Persona.Agent)
        fake.on("GET", "/admin/agents", body = Persona.Agent.agents.replace("\"custom_permissions\":null", "\"custom_permissions\":[\"manage_agents\"]"))
        val dash = dashboard(paparazzi.context, fake, role = "agent", superuser = false).also { it.clock = { scheduler.currentTime } }
        assertTrue(dash.isAdmin)
        assertTrue(dash.access.value.isAdmin)
        Personas.become(fake, Persona.Agent)
        advance(180_000)
        assertFalse(dash.isAdmin)
        assertFalse(dash.access.value.isAdmin)
        assertFalse(ViewId.Agents in dash.ids())
    }

    private fun DashboardViewModel.fire(path: String) = CoroutineScope(main).launch {
        runCatching { api.http.raw("POST", path) }
            .onFailure { assertEquals(403, (it as ApiException).status) }
    }

    @Test
    fun a403RereadsMeAndTheTeamOnceForABurst() {
        val fake = FakeNeema.withFixtures()
        val dash = signIn(Persona.Override, fake)
        assertTrue(ViewId.Reports in dash.ids())
        fun agents() = fake.callsTo("GET", "/admin/agents").size
        fun me() = fake.callsTo("GET", "/admin/me").size
        val (a0, m0) = agents() to me()

        // The admin took Reports away; the agent's next export is refused.
        Personas.become(fake, Persona.Sales)
        fake.on("POST", "/admin/reports/export", code = 403, body = """{"detail":"Not allowed"}""")
        repeat(3) { dash.fire("/admin/reports/export") }
        assertEquals("coalesced, not yet", a0, agents())
        advance(1_000)
        assertEquals("one reread of the team for three 403s", a0 + 1, agents())
        assertEquals("and of /admin/me", m0 + 1, me())
        assertEquals(listOf(ViewId.Conversations, ViewId.Calls, ViewId.Orders, ViewId.Profile), dash.ids())
        assertEquals(Persona.Sales.expected.toSet(), dash.access.value.permissions)
    }

    @Test
    fun repeated403sRereadAtMostOnceEvery15s() {
        val fake = FakeNeema.withFixtures()
        val dash = signIn(Persona.Sales, fake)
        fake.on("POST", "/admin/x", code = 403, body = """{"detail":"Forbidden"}""")
        fun agents() = fake.callsTo("GET", "/admin/agents").size
        val a0 = agents()
        dash.fire("/admin/x"); advance(1_000)
        assertEquals(a0 + 1, agents())
        dash.fire("/admin/x"); advance(1_000)
        assertEquals("cooling down", a0 + 1, agents())
        advance(14_000)
        dash.fire("/admin/x"); advance(1_000)
        assertEquals(a0 + 2, agents())
    }

    @Test
    fun a403OnTheTeamListItselfDoesNotLoop() {
        val fake = FakeNeema.withFixtures()
        val dash = signIn(Persona.Sales, fake)
        fake.on("GET", "/admin/agents", code = 403, body = "{}")
        dash.refetchAgents()
        val n = fake.callsTo("GET", "/admin/agents").size
        advance(10_000)
        assertEquals(n, fake.callsTo("GET", "/admin/agents").size)
        // The last good row still decides.
        assertEquals(Persona.Sales.expected.toSet(), dash.permissions().toSet())
    }

    @Test
    fun onForbiddenIsAHookFeaturesCanCallAndIsInertSignedOut() {
        val fake = FakeNeema.withFixtures()
        val dash = signIn(Persona.Readonly, fake)
        Personas.become(fake, Persona.Agent)
        dash.onForbidden(); dash.onForbidden()
        advance(1_000)
        assertTrue(dash.can(Perms.REPLY_CONVERSATIONS))

        dash.logout()
        val n = fake.callsTo("GET", "/admin/agents").size
        dash.onForbidden()
        advance(20_000)
        assertEquals(n, fake.callsTo("GET", "/admin/agents").size)
    }
}
