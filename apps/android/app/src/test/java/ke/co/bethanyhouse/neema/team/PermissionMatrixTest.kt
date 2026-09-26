package ke.co.bethanyhouse.neema.team

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.feature.agents.AgentsViewModel
import ke.co.bethanyhouse.neema.feature.agents.RoleForm
import ke.co.bethanyhouse.neema.feature.profile.ProfileViewModel
import ke.co.bethanyhouse.neema.feature.settings.SettingsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
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
 * Round 6 permission matrix for Team / Profile / Settings.
 *
 * What the web does (and so what this proves):
 *  - AgentsView.tsx, SettingsView.tsx and ProfileView.tsx test no permission
 *    at all. page.tsx only decides whether the nav lists Team
 *    (manage_agents) and Settings (manage_settings); the account menu's
 *    Settings entry and ?view= links open either screen for anyone.
 *  - The only gate inside Team is `role.protected` (no Edit / Delete).
 *  - ProfileView lists getAgentPermissions(agent) for the signed-in agent.
 *
 * What the server does: admin.py's agent routes (list / create / update /
 * delete / assign role) and roles.py's list / create check only that the
 * caller is signed in; roles.py refuses a protected role's edit / delete
 * (403); crm.py's settings PUTs refuse anyone whose DB role isn't admin
 * (or superuser) with 403 "Admin only" — manage_settings plays no part.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PermissionMatrixTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    @Before fun eager() { Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun reset() { Dispatchers.resetMain() }

    private val salesPerms = listOf("view_conversations", "reply_conversations", "view_orders", "manage_orders")
    private val sales = Triple("sales", "Sales", "#3b82f6")

    /** One signed-in persona: their /admin/agents row, session role, and whether crm.py treats them as admin. */
    data class Persona(
        val name: String, val role: String, val superuser: Boolean,
        val customRole: Triple<String, String, String>? = null, val rolePermissions: List<String>? = null,
        val customPermissions: List<String>? = null,
    ) {
        /** crm.py: `is_superuser or role == "admin"`. */
        val serverAdmin get() = superuser || role == "admin"
    }

    private val superuser = Persona("superuser", "admin", true)
    private val admin = Persona("admin role", "admin", false)
    private val agent = Persona("legacy agent", "agent", false)
    private val readonly = Persona("legacy readonly", "readonly", false)
    private val salesRole = Persona("custom Sales role", "agent", false, sales, salesPerms)
    private val override = Persona("per-agent override", "agent", false, sales, salesPerms,
        customPermissions = listOf("view_conversations", "manage_agents", "manage_settings"))
    private val emptyOverride = Persona("empty override []", "readonly", false, sales, salesPerms, customPermissions = emptyList())
    private val all = listOf(superuser, admin, agent, readonly, salesRole, override, emptyOverride)

    private fun rows(p: Persona) = TeamFixtures.agentsWithMe(p.role, p.superuser, p.customPermissions, p.customRole, p.rolePermissions)

    private fun fakeFor(p: Persona) = FakeNeema.withFixtures().also {
        TeamFixtures.install(it)
        TeamFixtures.settings(it, admin = p.serverAdmin)
        it.on("GET", "/admin/agents", body = rows(p))
        it.on("GET", "/admin/me", body = TeamFixtures.ormAgent(role = p.role, superuser = p.superuser))
    }

    private class Signed(val dash: DashboardViewModel, val fake: FakeNeema, val toasts: MutableList<Toast>)

    private fun signIn(p: Persona, fake: FakeNeema = fakeFor(p)): Signed {
        val d = dashboard(paparazzi.context, fake, p.role, p.superuser)
        val toasts = mutableListOf<Toast>()
        CoroutineScope(Dispatchers.Unconfined).launch { d.toasts.collect { toasts += it } }
        runBlocking { d.refreshAgents() }
        d.refetchMe()
        fake.calls.clear()
        return Signed(d, fake, toasts)
    }

    /** What ProfileView's "Your Permissions" ticks: getAgentPermissions(signed-in team row). */
    private fun Signed.profilePerms() = Perms.of(dash.currentAgent!!).filter { it in Perms.ALL }.toSet()

    // ── Effective permissions (Profile's list, and the nav core builds from them) ─

    @Test fun effectivePermissionsPerPersona() {
        val legacyAgent = setOf("view_conversations", "reply_conversations", "intercept_release", "close_conversations",
            "transfer_conversations", "add_notes", "view_orders", "manage_orders", "view_catalog", "view_crm", "view_leads")
        val legacyReadonly = setOf("view_conversations", "view_orders", "view_catalog", "view_crm", "view_leads", "view_analytics")
        val expected = mapOf(
            superuser to Perms.ALL.toSet(),
            admin to Perms.ALL.toSet(),
            agent to legacyAgent,
            readonly to legacyReadonly,
            salesRole to salesPerms.toSet(),
            override to setOf("view_conversations", "manage_agents", "manage_settings"),
            // custom_permissions [] is not null, so mapAgent keeps it; getAgentPermissions then
            // sees an empty list and falls back to the BASE role — not the Sales role, not nothing.
            emptyOverride to legacyReadonly,
        )
        all.forEach { p -> assertEquals(p.name, expected.getValue(p), signIn(p).profilePerms()) }
    }

    @Test fun navListsTeamAndSettingsExactlyLikePageTsx() {
        // page.tsx: Team with can(manage_agents); Settings with can(manage_settings); Profile always.
        val team = mapOf(superuser to true, admin to true, agent to false, readonly to false, salesRole to false, override to true, emptyOverride to false)
        all.forEach { p ->
            val nav = signIn(p).dash.navItems().map { it.id }
            assertEquals("${p.name}: Team", team.getValue(p), ViewId.Agents in nav)
            assertEquals("${p.name}: Settings", team.getValue(p), ViewId.Settings in nav)
            assertTrue("${p.name}: Profile", ViewId.Profile in nav)
        }
    }

    // ── Team: no client-side gate — every persona's request reaches the server ──

    @Test fun teamWritesAreNeverBlockedClientSide() {
        listOf(readonly, agent, emptyOverride).forEach { p ->
            val s = signIn(p)
            val vm = AgentsViewModel(s.dash)
            // The web's Roles tab loads for anyone who opens Team.
            assertTrue(p.name, vm.roles.value.isNotEmpty())
            s.fake.calls.clear()
            val grace = s.dash.agents.value.first { it.id == Fixtures.AGENT2_ID }
            vm.createAgent("Jane Doe", "jane@bethanyhouse.co.ke", "s3cretpass", "agent") {}
            vm.saveEdit(grace, "Grace W.", grace.email) {}
            vm.savePassword(grace, "newpassword", "newpassword") {}
            vm.toggleOnline(grace, grace.isAvailable)
            vm.saveAssign(grace, "support", null) {}
            vm.saveRole(null, RoleForm("Night shift", "", "#589b31", listOf("view_conversations"))) {}
            vm.deleteRole(vm.roles.value.first { it.id == "trainee" }) {}
            vm.deleteAgent(s.dash.agents.value.first { it.id == Fixtures.AGENT3_ID }) {}
            val sent = s.fake.calls.filter { it.method != "GET" }.map { "${it.method} ${it.path}" }
            assertEquals(
                p.name,
                listOf(
                    "POST /admin/agents", "PATCH /admin/agents/${Fixtures.AGENT2_ID}", "PATCH /admin/agents/${Fixtures.AGENT2_ID}",
                    "PATCH /admin/agents/${Fixtures.AGENT2_ID}", "PATCH /admin/agents/${Fixtures.AGENT2_ID}/role",
                    "POST /admin/roles", "DELETE /admin/roles/trainee", "DELETE /admin/agents/${Fixtures.AGENT3_ID}",
                ),
                sent,
            )
        }
    }

    @Test fun protectedRoleRefusalSaysWhyAndRereadsWhoIAm() {
        val s = signIn(admin)
        val vm = AgentsViewModel(s.dash)
        s.fake.calls.clear()
        // Hidden in the UI (web: !role.protected); a stale screen can still ask — the server's words come back.
        vm.saveRole(vm.roles.value.first { it.id == "super_admin" }, RoleForm("Super Admin", "x", "#7c3aed", emptyList())) {}
        assertEquals(ToastType.Error, s.toasts.last().type)
        assertEquals("Cannot modify a protected role", s.toasts.last().message)
        assertTrue("a 403 re-reads the team", s.fake.called("GET", "/admin/agents"))
        assertTrue("a 403 re-reads /me", s.fake.called("GET", "/admin/me"))
    }

    // ── Settings: loads for everyone, the server decides saves ──────────────────

    @Test fun settingsLoadsForEveryPersona() {
        all.forEach { p ->
            val s = signIn(p)
            val vm = SettingsViewModel(s.dash)
            listOf("directives", "translation", "offer", "pipeline-stages").forEach {
                assertTrue("${p.name} reads $it", s.fake.called("GET", "/admin/settings/$it"))
            }
            assertTrue(p.name, vm.directivesLoaded.value)
            assertTrue(p.name, vm.loadErrors.value.isEmpty())
        }
    }

    @Test fun settingsSavesSucceedOnlyForServerAdmins() {
        all.forEach { p ->
            val s = signIn(p)
            val vm = SettingsViewModel(s.dash)
            s.fake.calls.clear(); s.toasts.clear()
            vm.setDirectives("Push copes this week.")
            vm.saveDirectives()
            vm.toggleTranslation()
            vm.saveOffer(null)
            vm.addStage("Sampling")
            val puts = s.fake.calls.filter { it.method == "PUT" }.map { it.path }
            assertEquals(
                "${p.name}: every save is sent",
                listOf("/admin/settings/directives", "/admin/settings/translation", "/admin/settings/offer", "/admin/settings/pipeline-stages"),
                puts,
            )
            val errors = s.toasts.filter { it.type == ToastType.Error }.map { it.message }
            if (p.serverAdmin) {
                assertEquals(p.name, emptyList<String>(), errors)
            } else {
                // The web's own words for a refused save, card by card.
                assertEquals(
                    p.name,
                    listOf(
                        "Couldn't save (admin only)", "Couldn't change that (admin only)",
                        "Couldn't save that offer (admin only)", "Only an admin can change pipeline stages.",
                    ),
                    errors,
                )
                assertEquals("${p.name}: the switch goes back", true, vm.translation.value?.enabled)
                assertEquals("${p.name}: typing is kept", "Push copes this week.", vm.directives.value)
                assertTrue("${p.name}: a 403 re-reads the team", s.fake.called("GET", "/admin/agents"))
                assertTrue("${p.name}: a 403 re-reads /me", s.fake.called("GET", "/admin/me"))
            }
        }
    }

    // ── Profile: every persona edits their own account ──────────────────────────

    @Test fun profileWritesAreOpenToEveryone() {
        all.forEach { p ->
            val s = signIn(p)
            val vm = ProfileViewModel(s.dash)
            s.fake.calls.clear()
            vm.saveProfile("Moses M.", "moses@bethanyhouse.co.ke") {}
            vm.changePassword("newpassword", "newpassword") {}
            vm.setAvailable(Fixtures.ME_ID, false)
            val sent = s.fake.calls.filter { it.method != "GET" }.map { "${it.method} ${it.path}" }
            assertEquals(p.name, listOf("PATCH /admin/me", "PATCH /admin/me", "PATCH /admin/agents/${Fixtures.ME_ID}"), sent)
        }
    }

    // ── Persona 8: an admin changes my role while the app is open ───────────────

    @Test fun roleChangePicksUpOnThePollAndOnA403() {
        // Signed in on a custom role with manage_settings (so the nav lists Settings) but base role agent.
        val p = Persona("custom manage_settings", "agent", false, Triple("ops", "Ops", "#0f766e"), listOf("view_conversations", "manage_settings"))
        val s = signIn(p)
        assertTrue(s.dash.can(Perms.MANAGE_SETTINGS))
        assertTrue(ViewId.Settings in s.dash.navItems().map { it.id })

        // An admin moves them to Sales meanwhile. Nothing changes until the app re-reads the team…
        s.fake.on("GET", "/admin/agents", body = rows(salesRole.copy(role = "agent")))
        assertTrue(s.dash.can(Perms.MANAGE_SETTINGS))

        // …which a 403 now triggers at once (the web waits for its 3-minute agents poll).
        val vm = SettingsViewModel(s.dash)
        vm.saveDirectives()
        assertEquals("Couldn't save (admin only)", s.toasts.last().message)
        assertFalse("the refused save corrected the permissions", s.dash.can(Perms.MANAGE_SETTINGS))
        assertFalse(ViewId.Settings in s.dash.navItems().map { it.id })
        assertEquals(salesPerms.toSet(), s.profilePerms())

        // And a promotion arrives with the next poll / refresh.
        s.fake.on("GET", "/admin/agents", body = rows(admin))
        runBlocking { s.dash.refreshAgents() }
        assertTrue(s.dash.can(Perms.MANAGE_AGENTS))
        assertEquals(Perms.ALL.toSet(), s.profilePerms())
    }
}
