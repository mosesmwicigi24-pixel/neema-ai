package ke.co.bethanyhouse.neema.team

import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.agents.AgentsViewModel
import ke.co.bethanyhouse.neema.feature.agents.RoleForm
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Team screen and /me against the API's real contract (admin.py agents +
 * me, roles.py): exact requests, the shapes the handlers really return, and
 * each error they raise. TeamFixtures re-implements every handler's checks.
 */
class TeamContractTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.install(f)

    private val vm by lazy { AgentsViewModel(dash).also { fake.calls.clear() } }
    private fun agent(id: String) = dash.agents.value.first { it.id == id }
    private var done = 0
    private val onDone: () -> Unit = { done++ }

    // ── GET /admin/agents (list_agents) ──────────────────────────────────────

    @Test fun listDecodesTheJoinedRows() {
        val list = dash.agents.value
        assertEquals("ORDER BY name", listOf("Brian Otieno", "Grace Wanjiru", "Moses Mwicigi", "Wanjiku Kamau-Ochieng Nyambura"), list.map { it.name })
        val grace = agent(Fixtures.AGENT2_ID)
        assertEquals("sales", grace.customRoleId)
        assertEquals("Sales", grace.roleName)
        assertEquals("#3b82f6", grace.roleColor)
        assertNull(grace.customPermissions)
        assertEquals("no override: the role's permissions", grace.rolePermissions, grace.permissions)
        val wanjiku = agent(TeamFixtures.AGENT4_ID)
        assertEquals("an override wins over the role", listOf("view_conversations", "reply_conversations", "add_notes"), wanjiku.permissions)
        assertNull(wanjiku.lastSeenAt)
        val brian = agent(Fixtures.AGENT3_ID)
        assertNull(brian.customRoleId)
        assertTrue(brian.permissions.isEmpty())
        // Python isoformat: microseconds and "+00:00".
        assertTrue(grace.createdAt!!, grace.createdAt!!.matches(Regex("""\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}\+00:00""")))
        assertNotNull(Fmt.millis(grace.createdAt))
        assertTrue(Fmt.timeAgo(grace.lastSeenAt).endsWith("ago"))
    }

    @Test fun listToleratesMissingAndNullKeys() {
        // A row from before the custom-role migration: no role_* / custom_* keys, active_convs null.
        fake.on("GET", "/admin/agents", body = """[{"id":"x1","name":"Old Row","email":"old@b.co","role":"agent","is_available":null,
            "is_superuser":false,"avatar_url":null,"created_at":"2025-01-01T08:00:00+00:00","last_seen_at":null,"active_convs":null}]""")
        dash.refetchAgents()
        val a = dash.agents.value.single()
        assertEquals("Old Row", a.name)
        assertFalse(a.isAvailable)
        assertEquals(0, a.activeConvs)
        assertTrue(a.permissions.isEmpty())
    }

    // ── GET /admin/me (get_me: the bare ORM row) ─────────────────────────────

    @Test fun meIsTheBareOrmRowAndPermissionsComeFromTheTeamList() {
        dash.refetchMe()
        val me = dash.me.value!!
        assertEquals(Fixtures.ME_ID, me.id)
        assertEquals("admin", me.role)
        assertTrue(me.isSuperuser)
        assertNull("get_me has no custom-role columns", me.customRoleId)
        assertNull(me.rolePermissions)
        // An agent whose power comes from a custom role keeps it although /me omits it.
        fake.on("GET", "/admin/me", body = TeamFixtures.ormAgent(TeamFixtures.AGENT4_ID, "Wanjiku", "wanjiku.kamau-ochieng.nyambura@bethanyhouse.co.ke",
            role = "agent", superuser = false))
        dash.refetchMe()
        assertEquals(TeamFixtures.AGENT4_ID, dash.me.value?.id)
    }

    // ── POST /admin/agents (create_agent) ────────────────────────────────────

    @Test fun createSendsExactlyTheWebsBodyAndAcceptsTheOrmRow() {
        vm.createAgent("Jane Doe", "jane@bethanyhouse.co.ke", "s3cretpass", "viewer", onDone)
        val w = writes().single()
        assertEquals("POST" to "/admin/agents", w.method to w.path)
        assertNull(w.query)
        assertEquals(el("""{"name":"Jane Doe","email":"jane@bethanyhouse.co.ke","password":"s3cretpass","role":"readonly"}"""), w.json())
        assertEquals(1, done)
        assertEquals("Agent created", lastToast()?.message)
    }

    @Test fun aTakenEmailIsCaughtBeforeTheServer500s() {
        vm.createAgent("Grace Again", " GRACE@bethanyhouse.co.ke ", "s3cretpass", "agent", onDone)
        assertTrue(writes().isEmpty())
        assertEquals("An agent with that email already exists", lastToast()?.message)
        assertEquals(0, done)
    }

    @Test fun aServer500SaysWhatUsuallyCausesIt() {
        // Someone else took the email since the list loaded: agents.email UNIQUE → unhandled IntegrityError.
        fake.on("POST", "/admin/agents", code = 500, body = TeamFixtures.SERVER_ERROR)
        vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals("Couldn't create the agent — that email may already be in use", lastToast()?.message)
        assertEquals(0, done)
        // A 409 (a proxy or a future handler) reads the same way.
        fake.on("POST", "/admin/agents", code = 409, body = """{"detail":"Email already registered"}""")
        vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals("An agent with that email already exists", lastToast()?.message)
    }

    // ── PATCH /admin/agents/{id} (update_agent → {"ok": true}) ───────────────

    @Test fun editRefusesAnotherAgentsEmail() {
        vm.saveEdit(agent(Fixtures.AGENT3_ID), "Brian", "grace@bethanyhouse.co.ke", onDone)
        assertTrue(writes().isEmpty())
        assertEquals("An agent with that email already exists", lastToast()?.message)
        // Keeping your own email is fine.
        vm.saveEdit(agent(Fixtures.AGENT3_ID), "Brian O.", "brian@bethanyhouse.co.ke", onDone)
        assertEquals(el("""{"name":"Brian O.","email":"brian@bethanyhouse.co.ke"}"""), writes().single().json())
        assertEquals(1, done)
    }

    @Test fun editOfAnAgentSomeoneElseRemovedShowsTheServersReason() {
        fake.on("PATCH", "/admin/agents/[^/]+", code = 404, body = """{"detail":"Agent not found"}""")
        vm.savePassword(agent(Fixtures.AGENT3_ID), "n3wpassword", "n3wpassword", onDone)
        assertEquals("Agent not found", lastToast()?.message)
        assertEquals(0, done)
    }

    // ── DELETE /admin/agents/{id}: the server guards nothing ─────────────────

    @Test fun youCannotRemoveYourself() {
        assertFalse(vm.requestRemove(agent(Fixtures.ME_ID)))
        assertEquals("You can't remove your own account — ask another admin", lastToast()?.message)
        vm.deleteAgent(agent(Fixtures.ME_ID), onDone)
        assertTrue("never sent: every later call would 404 \"Agent not found\"", writes().isEmpty())
        assertEquals(0, done)
    }

    @Test fun youCannotRemoveTheLastAdmin() {
        // A manage_agents holder who isn't an admin; Brian is the only admin left.
        fake.on("GET", "/admin/agents", body = TeamFixtures.agentsWithMe("agent", false, listOf("view_conversations", "manage_agents"))
            .replace("\"role\":\"readonly\"", "\"role\":\"admin\""))
        dash.refetchAgents()
        assertEquals(1, dash.agents.value.count { it.role == "admin" || it.isSuperuser })
        assertFalse(vm.requestRemove(agent(Fixtures.AGENT3_ID)))
        assertEquals("You can't remove the last admin", lastToast()?.message)
        assertTrue(vm.requestRemove(agent(Fixtures.AGENT2_ID)))
    }

    @Test fun removeSendsTheDeleteAndReadsOk() {
        assertTrue(vm.requestRemove(agent(Fixtures.AGENT2_ID)))
        vm.deleteAgent(agent(Fixtures.AGENT2_ID), onDone)
        val w = writes().single()
        assertEquals("DELETE" to "/admin/agents/${Fixtures.AGENT2_ID}", w.method to w.path)
        assertNull(w.body?.takeIf { it.isNotEmpty() })
        assertEquals(1, done)
    }

    // ── PATCH /admin/agents/{id}/role (assign_agent_role) ────────────────────

    @Test fun assignAcceptsTheJoinedRowReply() {
        // The reply is the agent's joined row — no "ok", no "permissions" (the web's type is wrong).
        vm.saveAssign(agent(Fixtures.AGENT3_ID), "sales", null, onDone)
        assertEquals(el("""{"custom_role_id":"sales"}"""), writes().single().json())
        assertEquals("Role assigned", lastToast()?.message)
        assertEquals(ToastType.Success, lastToast()?.type)
        assertEquals(1, done)
    }

    @Test fun anEmptyOverrideIsSentAsAnEmptyList() {
        // [] is a real override (no permissions at all); only null means "use the role's".
        vm.saveAssign(agent(TeamFixtures.AGENT4_ID), "support", emptyList(), onDone)
        assertEquals(el("""{"custom_role_id":"support","custom_permissions":[]}"""), writes().single().json())
        assertEquals(1, done)
    }

    @Test fun assigningARoleSomeoneJustDeletedShowsNotFound() {
        vm.saveAssign(agent(Fixtures.AGENT3_ID), "role_gone", null, onDone)
        assertEquals("Role not found", lastToast()?.message)
        assertEquals(0, done)
    }

    // ── /admin/roles ─────────────────────────────────────────────────────────

    @Test fun rolesDecodeWithTheirTimestamps() {
        val r = vm.roles.value.first { it.id == "super_admin" }
        assertTrue(r.protected)
        assertEquals(20, r.permissions.size)
        assertTrue(r.createdAt!!.endsWith("+00:00"))
        assertEquals("", vm.roles.value.first { it.id == "trainee" }.description)
    }

    @Test fun createRoleSendsAnIdTheUpsertCannotCollideWith() {
        // create_role upserts ON CONFLICT (id) — even over a protected role — so the id must be fresh.
        vm.saveRole(null, RoleForm("Dispatch", "", "#0891b2", listOf("view_orders")), onDone)
        val body = writes().single().json()
        val id = body["id"]!!.jsonPrimitive.content
        assertTrue(id, id.matches(Regex("role_\\d{13}")))
        assertFalse(id in vm.roles.value.map { it.id })
        assertEquals(1, done)
    }

    @Test fun protectedRoleRefusalsAreShown() {
        vm.deleteRole(vm.roles.value.first { it.id == "super_admin" }, onDone)
        assertEquals("Cannot delete a protected role", lastToast()?.message)
        vm.saveRole(vm.roles.value.first { it.id == "super_admin" }, RoleForm("X"), onDone)
        assertEquals("Cannot modify a protected role", lastToast()?.message)
        assertEquals(0, done)
    }

    @Test fun deletingARoleAlreadyGoneShowsNotFound() {
        fake.on("DELETE", "/admin/roles/[^/]+", code = 404, body = """{"detail":"Role not found"}""")
        vm.deleteRole(vm.roles.value.first { it.id == "trainee" }, onDone)
        assertEquals("Role not found", lastToast()?.message)
    }

    @Test fun aNetworkDropSaysSo() {
        fake.on("PATCH", "/admin/roles/[^/]+") { _, _ -> throw java.io.IOException("reset") }
        vm.saveRole(vm.roles.value.first { it.id == "sales" }, RoleForm("Sales"), onDone)
        assertEquals("Network problem — check your connection", lastToast()?.message)
    }

    @Test fun canStillManageTheTeamFromTheListRow() {
        assertTrue(dash.can(Perms.MANAGE_AGENTS))
    }
}
