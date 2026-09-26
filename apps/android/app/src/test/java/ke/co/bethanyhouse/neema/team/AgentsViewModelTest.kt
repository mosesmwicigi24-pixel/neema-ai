package ke.co.bethanyhouse.neema.team

import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.agents.AgentsViewModel
import ke.co.bethanyhouse.neema.feature.agents.RoleForm
import ke.co.bethanyhouse.neema.feature.agents.toDbRole
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** AgentsView.tsx's handlers: every call's endpoint and body, validation, and failure handling. */
class AgentsViewModelTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.install(f)

    private val vm by lazy { AgentsViewModel(dash).also { fake.calls.clear() } }
    private fun agent(id: String) = dash.agents.value.first { it.id == id }
    private var done = 0
    private val onDone: () -> Unit = { done++ }

    @Test fun loadsRolesOnOpen() {
        val v = AgentsViewModel(dash)
        // roles.py list_roles: ORDER BY protected DESC, name.
        assertEquals(listOf("super_admin", "agent", "sales", "support", "trainee", "viewer"), v.roles.value.map { it.id })
        assertFalse(v.rolesLoading.value)
    }

    @Test fun rolesFailingToLoadToasts() {
        fail("GET", "/admin/roles", 500, "boom")
        AgentsViewModel(dash)
        assertEquals("Failed to load roles", lastToast()?.message)
        assertEquals(ToastType.Error, lastToast()?.type)
    }

    // ── Create ────────────────────────────────────────────────────────────────

    @Test fun createPostsTheAgentWithItsDbRole() {
        vm.createAgent("  Jane Doe ", "jane@bethanyhouse.co.ke", "s3cretpass", "admin", onDone)
        val w = writes().single()
        assertEquals("POST" to "/admin/agents", w.method to w.path)
        assertEquals(el("""{"name":"Jane Doe","email":"jane@bethanyhouse.co.ke","password":"s3cretpass","role":"admin"}"""), w.json())
        assertEquals(1, done)
        assertEquals("Agent created", lastToast()?.message)
        assertTrue("refetches the team", fake.calls.any { it.method == "GET" && it.path == "/admin/agents" })
    }

    @Test fun createNeedsNameEmailAndPassword() {
        vm.createAgent("", "jane@x.co", "s3cretpass", "agent", onDone)
        vm.createAgent("Jane", "", "s3cretpass", "agent", onDone)
        vm.createAgent("Jane", "jane@x.co", "", "agent", onDone)
        assertTrue(writes().isEmpty())
        assertEquals(0, done)
        assertTrue(toasts.all { it.message == "Name, email and password are required" && it.type == ToastType.Error })
        assertEquals(3, toasts.size)
    }

    @Test fun createNeedsEightCharacters() {
        vm.createAgent("Jane", "jane@x.co", "1234567", "agent", onDone)
        assertTrue(writes().isEmpty())
        assertEquals("Password must be ≥8 characters", lastToast()?.message)
    }

    @Test fun createFailureKeepsTheDialogOpen() {
        fail("POST", "/admin/agents", 422, "Missing required fields: email")
        vm.createAgent("Jane", "jane@x.co", "12345678", "readonly", onDone)
        assertEquals(0, done)
        assertEquals("Missing required fields: email", lastToast()?.message)
        assertFalse(vm.saving.value)
    }

    @Test fun dbRoleMapping() {
        assertEquals("admin", toDbRole("admin"))
        assertEquals("agent", toDbRole("agent"))
        assertEquals("readonly", toDbRole("readonly"))
        assertEquals("admin", toDbRole("super_admin"))
        assertEquals("readonly", toDbRole("viewer"))
        assertEquals("agent", toDbRole("role_17000"))
    }

    // ── Edit / password / remove ─────────────────────────────────────────────

    @Test fun editPatchesNameAndEmailOnly() {
        vm.saveEdit(agent(Fixtures.AGENT2_ID), "Grace W.", "gw@bethanyhouse.co.ke", onDone)
        val w = writes().single()
        assertEquals("PATCH" to "/admin/agents/${Fixtures.AGENT2_ID}", w.method to w.path)
        assertEquals(el("""{"name":"Grace W.","email":"gw@bethanyhouse.co.ke"}"""), w.json())
        assertEquals("Agent updated", lastToast()?.message)
        assertEquals(1, done)
    }

    @Test fun editNeedsNameAndEmail() {
        vm.saveEdit(agent(Fixtures.AGENT2_ID), " ", "gw@x.co", onDone)
        assertTrue(writes().isEmpty())
        assertEquals("Name and email required", lastToast()?.message)
    }

    @Test fun passwordLengthIsCheckedBeforeTheMatch() {
        vm.savePassword(agent(Fixtures.AGENT2_ID), "short", "different", onDone)
        assertEquals("Password must be ≥8 characters", lastToast()?.message)
        vm.savePassword(agent(Fixtures.AGENT2_ID), "longenough1", "longenough2", onDone)
        assertEquals("Passwords do not match", lastToast()?.message)
        assertTrue(writes().isEmpty())
    }

    @Test fun passwordResetSendsOnlyThePassword() {
        vm.savePassword(agent(Fixtures.AGENT3_ID), "n3wpassword", "n3wpassword", onDone)
        val w = writes().single()
        assertEquals("PATCH" to "/admin/agents/${Fixtures.AGENT3_ID}", w.method to w.path)
        assertEquals(el("""{"password":"n3wpassword"}"""), w.json())
        assertEquals("Password updated", lastToast()?.message)
    }

    @Test fun removeDeletesAndRefetches() {
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone)
        assertEquals("DELETE" to "/admin/agents/${Fixtures.AGENT3_ID}", writes().single().let { it.method to it.path })
        assertEquals("Agent removed", lastToast()?.message)
        assertTrue(fake.called("GET", "/admin/agents"))
    }

    @Test fun removeFailureUsesTheWebsWording() {
        fail("DELETE", "/admin/agents/.*", 500, "db down")
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone)
        assertEquals("Failed to remove", lastToast()?.message)
        assertEquals(0, done)
    }

    // ── Availability ─────────────────────────────────────────────────────────

    @Test fun availabilityPatchesTheFlippedValue() {
        vm.toggleOnline(agent(Fixtures.AGENT2_ID), current = true)
        val w = writes().single()
        assertEquals("PATCH" to "/admin/agents/${Fixtures.AGENT2_ID}", w.method to w.path)
        assertEquals(el("""{"is_available":false}"""), w.json())
        assertEquals(false, vm.availability.value[Fixtures.AGENT2_ID])
    }

    @Test fun availabilityRevertsOnFailure() {
        fail("PATCH", "/admin/agents/.*", 500, "x")
        vm.toggleOnline(agent(Fixtures.AGENT3_ID), current = false)
        assertTrue(vm.availability.value.isEmpty())
        assertEquals("Failed to update availability", lastToast()?.message)
    }

    @Test fun reconcileDropsValuesTheServerNowAgreesWith() {
        vm.toggleOnline(agent(Fixtures.AGENT2_ID), current = true)
        // The refetched list still says true (the fake doesn't store writes): the optimistic value stays.
        vm.reconcile(dash.agents.value)
        assertEquals(false, vm.availability.value[Fixtures.AGENT2_ID])
        vm.reconcile(dash.agents.value.map { if (it.id == Fixtures.AGENT2_ID) it.copy(isAvailable = false) else it })
        assertTrue(vm.availability.value.isEmpty())
    }

    // ── Role assignment ──────────────────────────────────────────────────────

    @Test fun assignSendsOnlyTheRoleLikeTheWeb() {
        vm.saveAssign(agent(Fixtures.AGENT3_ID), "sales", null, onDone)
        val w = writes().single()
        assertEquals("PATCH" to "/admin/agents/${Fixtures.AGENT3_ID}/role", w.method to w.path)
        assertEquals(el("""{"custom_role_id":"sales"}"""), w.json())
        assertEquals("Role assigned", lastToast()?.message)
        assertEquals(1, done)
    }

    @Test fun assignWithOverrideSendsThePermissions() {
        vm.saveAssign(agent(TeamFixtures.AGENT4_ID), "support", listOf("view_conversations", "add_notes"), onDone)
        val body = writes().single().json()
        assertEquals(JsonPrimitive("support"), body["custom_role_id"])
        assertEquals(JsonArray(listOf(JsonPrimitive("view_conversations"), JsonPrimitive("add_notes"))), body["custom_permissions"])
    }

    @Test fun assignNeedsARole() {
        vm.saveAssign(agent(Fixtures.AGENT3_ID), "", null, onDone)
        assertTrue(writes().isEmpty())
        assertEquals("Please select a role", lastToast()?.message)
    }

    @Test fun assigningYourselfRefreshesMe() {
        vm.saveAssign(agent(Fixtures.ME_ID), "super_admin", null, onDone)
        assertTrue(fake.called("GET", "/admin/me"))
    }

    // ── Roles ────────────────────────────────────────────────────────────────

    @Test fun newRolePostsAFreshIdAndTheForm() {
        vm.saveRole(null, RoleForm("Dispatch", "Ships orders", "#0891b2", listOf("view_orders", "manage_orders")), onDone)
        val w = writes().single()
        assertEquals("POST" to "/admin/roles", w.method to w.path)
        val body = w.json()
        assertTrue(body["id"]!!.jsonPrimitive.content.matches(Regex("role_\\d+")))
        assertEquals(el("""{"name":"Dispatch","description":"Ships orders","color":"#0891b2","permissions":["view_orders","manage_orders"]}"""),
            kotlinx.serialization.json.JsonObject(body - "id"))
        assertEquals("Role created", toasts.first().message)
        assertTrue("refetches roles", fake.calls.any { it.method == "GET" && it.path == "/admin/roles" })
        assertEquals(1, done)
    }

    @Test fun editRolePatchesEveryField() {
        val role = vm.roles.value.first { it.id == "sales" }
        vm.saveRole(role, RoleForm("Sales", "Closes deals", "#b45309", emptyList()), onDone)
        val w = writes().single()
        assertEquals("PATCH" to "/admin/roles/sales", w.method to w.path)
        assertEquals(el("""{"name":"Sales","description":"Closes deals","color":"#b45309","permissions":[]}"""), w.json())
        assertEquals("Role updated", toasts.first().message)
    }

    @Test fun roleNeedsAName() {
        vm.saveRole(null, RoleForm(name = "  "), onDone)
        assertTrue(writes().isEmpty())
        assertEquals("Role name required", lastToast()?.message)
    }

    @Test fun protectedRoleRefusalIsShown() {
        // The fixture answers as roles.py update_role does for a protected role.
        vm.saveRole(vm.roles.value.first { it.id == "super_admin" }, RoleForm("Admin"), onDone)
        assertEquals("Cannot modify a protected role", lastToast()?.message)
        assertEquals(0, done)
    }

    @Test fun deleteRoleDeletesThenRefetches() {
        vm.deleteRole(vm.roles.value.first { it.id == "trainee" }, onDone)
        assertEquals("DELETE" to "/admin/roles/trainee", writes().single().let { it.method to it.path })
        assertEquals("Role deleted", lastToast()?.message)
        assertTrue(fake.called("GET", "/admin/roles"))
        assertTrue(fake.called("GET", "/admin/agents"))
    }

    @Test fun oneSaveAtATime() {
        var inside = 0
        fake.on("POST", "/admin/roles") { _, _ ->
            inside++
            // A second tap while the first is in flight is ignored.
            vm.saveRole(null, RoleForm("Again"), onDone)
            200 to """{"id":"role_1","name":"x","description":"","color":"#589b31","permissions":[],"protected":false}"""
        }
        vm.saveRole(null, RoleForm("Once"), onDone)
        assertEquals(1, inside)
    }

    // ── Replies: POST /admin/agents answers with whatever object the server sends ──

    @Test fun createAcceptsTheFullAgentRow() {
        // admin.py create_agent returns the new agent (the TeamFixtures route answers that way).
        vm.createAgent("Jane Doe", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals(1, done)
        assertEquals("Agent created", lastToast()?.message)
        assertEquals(ToastType.Success, lastToast()?.type)
    }

    @Test fun createAcceptsABareOk() {
        // Any JSON object is a success; nothing in the reply is read.
        fake.on("POST", "/admin/agents", body = """{"ok":true}""")
        vm.createAgent("Jane Doe", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals(1, done)
        assertEquals("Agent created", lastToast()?.message)
    }

    @Test fun createAcceptsAnEmptyObject() {
        fake.on("POST", "/admin/agents", body = "{}")
        vm.createAgent("Jane Doe", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals(1, done)
    }
}
