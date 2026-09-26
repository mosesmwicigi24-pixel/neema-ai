package ke.co.bethanyhouse.neema.team

import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.agents.AgentsViewModel
import ke.co.bethanyhouse.neema.feature.agents.RoleForm
import ke.co.bethanyhouse.neema.feature.agents.UNCERTAIN_SAVE
import ke.co.bethanyhouse.neema.feature.reports.BUSY_TEXT
import ke.co.bethanyhouse.neema.feature.reports.DOWN_TEXT
import ke.co.bethanyhouse.neema.feature.reports.EXPIRED_TEXT
import ke.co.bethanyhouse.neema.feature.reports.OFFLINE_TEXT
import ke.co.bethanyhouse.neema.feature.reports.TIMEOUT_TEXT
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.NetStressFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The Team screen on a bad phone network: every load and every write under
 * offline, timeout, 401, 403 / 404 / 422 / 429 / 5xx, HTML pages, garbled
 * bodies, double taps and sign-out mid-request.
 */
class TeamNetworkTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.install(f)

    private val vm by lazy { AgentsViewModel(dash).also { fake.calls.clear(); toasts.clear() } }
    private fun agent(id: String) = dash.agents.value.first { it.id == id }
    private var done = 0
    private val onDone: () -> Unit = { done++ }

    /** The team list the server would answer after [change]. */
    private fun agentsWith(change: (MutableList<JsonObject>) -> Unit): String {
        val rows = Json.parseToJsonElement(TeamFixtures.agents).jsonArray.map { it.jsonObject }.toMutableList()
        change(rows)
        return JsonArray(rows).toString()
    }
    private fun JsonObject.with(vararg kv: Pair<String, String?>) =
        JsonObject(this + kv.associate { (k, v) -> k to (v?.let { JsonPrimitive(it) } ?: kotlinx.serialization.json.JsonNull) })

    private fun writesTo(method: String, path: String) = fake.calls.count { it.method == method && it.path.matches(Regex(path)) }

    // ── Loads ────────────────────────────────────────────────────────────────

    @Test fun rolesOffline_tabSaysWhyWithRetry_thenRetryLoads() {
        NetStressFixtures.offline(fake, "GET", "/admin/roles")
        val v = AgentsViewModel(dash)
        assertEquals(OFFLINE_TEXT, v.rolesError.value)
        assertTrue(v.roles.value.isEmpty())
        assertFalse(v.rolesLoading.value)
        // Back online: Retry (the tab's button) reads them and clears the notice.
        fake.on("GET", "/admin/roles", body = TeamFixtures.roles)
        v.refresh()
        assertNull(v.rolesError.value)
        assertEquals(6, v.roles.value.size)
        assertFalse(v.refreshing.value)
    }

    @Test fun teamNeverLoaded_screenAsksAtOnce_andSaysWhy() {
        // Signed in offline: the dashboard's first read failed, the list is empty.
        val f = FakeNeema.withFixtures().also(TeamFixtures::install)
        NetStressFixtures.timeout(f, "GET", "/admin/agents")
        val d = ke.co.bethanyhouse.neema.testing.dashboard(paparazzi.context, f)
        val v = AgentsViewModel(d)
        assertTrue(d.agents.value.isEmpty())
        assertEquals(TIMEOUT_TEXT, v.agentsError.value)
        // The next successful read (any poller) clears it.
        f.on("GET", "/admin/agents", body = TeamFixtures.agents)
        v.refresh()
        assertNull(v.agentsError.value)
        assertEquals(4, d.agents.value.size)
    }

    @Test fun pullToRefreshFailing_keepsTheTeam_andSaysSo() {
        vm
        NetStressFixtures.html(fake, "GET", "/admin/agents", 503)
        vm.refresh()
        assertEquals(4, dash.agents.value.size)
        assertEquals("Couldn't refresh the team. $DOWN_TEXT", toasts.single { it.type == ToastType.Error }.message)
        assertFalse("the spinner stops", vm.refreshing.value)
    }

    @Test fun garbledRoles_noCrash_sensibleState() {
        fake.on("GET", "/admin/roles", body = """{"roles": "definitely not a list"""")
        val v = AgentsViewModel(dash)
        assertTrue(v.roles.value.isEmpty())
        assertEquals("The server sent an answer the app couldn't read — try again.", v.rolesError.value)
    }

    // ── Create: duplicate email, timeouts, double taps ──────────────────────

    @Test fun duplicateEmailRaceBecomesA500_saysWhyAndKeepsTheForm() {
        // Someone added this address after the list was read: the API's unhandled IntegrityError.
        fake.on("POST", "/admin/agents", code = 500, body = "Internal Server Error")
        vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals(0, done)
        assertEquals("Couldn't create the agent — that email may already be in use", lastToast()?.message)
        assertFalse(vm.saving.value)
    }

    @Test fun createTimesOut_butTheServerMadeThem_countsAsCreated() {
        NetStressFixtures.landThenTimeout(fake, "POST", "/admin/agents") {
            fake.on("GET", "/admin/agents", body = agentsWith { rows ->
                rows += rows[0].with("id" to TeamFixtures.NEW_AGENT_ID, "name" to "Jane", "email" to "jane@bethanyhouse.co.ke")
            })
        }
        vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals(1, done)
        assertEquals("Agent created", lastToast()?.message)
        assertEquals(1, writesTo("POST", "/admin/agents"))
    }

    @Test fun createTimesOut_andTheyAreNotThere_keepsTheFormAndSaysItMayNotHaveSaved() {
        NetStressFixtures.timeout(fake, "POST", "/admin/agents")
        vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals(0, done)
        assertEquals(UNCERTAIN_SAVE, lastToast()?.message)
        assertFalse(vm.saving.value)
    }

    @Test fun createOffline_saysOffline_neverClaimsItMightHaveSaved() {
        NetStressFixtures.offline(fake, "POST", "/admin/agents")
        vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals(0, done)
        assertEquals(OFFLINE_TEXT, lastToast()?.message)
    }

    @Test fun doubleTapOnCreate_sendsOnce() {
        // The second tap lands while the first request is on the wire.
        fake.on("POST", "/admin/agents") { _, _ ->
            vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
            200 to TeamFixtures.ormAgent(TeamFixtures.NEW_AGENT_ID, "Jane", "jane@bethanyhouse.co.ke", "agent")
        }
        vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "s3cretpass", "agent", onDone)
        assertEquals(1, writesTo("POST", "/admin/agents"))
        assertEquals(1, done)
    }

    @Test fun thePasswordIsNeverReadBack() {
        // A server that echoes the password in its error (a pydantic-style detail).
        NetStressFixtures.status(fake, "POST", "/admin/agents", 422, "Value 'hunter2hunter2' is not a valid password")
        vm.createAgent("Jane", "jane@bethanyhouse.co.ke", "hunter2hunter2", "agent", onDone)
        val msg = lastToast()!!.message
        assertFalse(msg, "hunter2hunter2" in msg)
        assertTrue(msg, "••••••" in msg)
        NetStressFixtures.status(fake, "PATCH", "/admin/agents/[^/]+", 422, "hunter2hunter2 is too common")
        vm.savePassword(agent(Fixtures.AGENT3_ID), "hunter2hunter2", "hunter2hunter2", onDone)
        assertFalse(lastToast()!!.message.contains("hunter2hunter2"))
    }

    // ── Edit / password / assign / remove ────────────────────────────────────

    @Test fun editTimesOut_butLanded_closesAsSaved() {
        NetStressFixtures.landThenTimeout(fake, "PATCH", "/admin/agents/[^/]+") {
            fake.on("GET", "/admin/agents", body = agentsWith { rows ->
                val i = rows.indexOfFirst { it["id"]!!.jsonPrimitive.content == Fixtures.AGENT2_ID }
                rows[i] = rows[i].with("name" to "Grace W.")
            })
        }
        vm.saveEdit(agent(Fixtures.AGENT2_ID), "Grace W.", "grace@bethanyhouse.co.ke", onDone)
        assertEquals(1, done)
        assertEquals("Agent updated", lastToast()?.message)
    }

    @Test fun editTimesOut_notLanded_keepsTheForm() {
        NetStressFixtures.timeout(fake, "PATCH", "/admin/agents/[^/]+")
        vm.saveEdit(agent(Fixtures.AGENT2_ID), "Grace W.", "grace@bethanyhouse.co.ke", onDone)
        assertEquals(0, done)
        assertEquals(UNCERTAIN_SAVE, lastToast()?.message)
    }

    @Test fun passwordTimeout_keepsBothFieldsForAnotherGo() {
        NetStressFixtures.timeout(fake, "PATCH", "/admin/agents/[^/]+")
        vm.savePassword(agent(Fixtures.AGENT3_ID), "n3wpassword", "n3wpassword", onDone)
        assertEquals(0, done)
        assertEquals(UNCERTAIN_SAVE, lastToast()?.message)
        // Setting it again is harmless: the retry goes out and succeeds.
        fake.on("PATCH", "/admin/agents/[^/]+", body = """{"ok":true}""")
        vm.savePassword(agent(Fixtures.AGENT3_ID), "n3wpassword", "n3wpassword", onDone)
        assertEquals(1, done)
    }

    @Test fun agentDeletedElsewhere_everyActionRemovesThemAndSaysSo() {
        vm
        // Brian is gone on the server: every write about him answers 404, and the list no longer has him.
        fake.on("GET", "/admin/agents", body = agentsWith { rows -> rows.removeAll { it["id"]!!.jsonPrimitive.content == Fixtures.AGENT3_ID } })
        val brian = agent(Fixtures.AGENT3_ID)
        NetStressFixtures.status(fake, "PATCH", "/admin/agents/[^/]+", 404, "Agent not found")
        NetStressFixtures.status(fake, "PATCH", "/admin/agents/[^/]+/role", 404, "Agent not found")
        vm.saveEdit(brian, "Brian O.", "brian@bethanyhouse.co.ke", onDone)
        assertEquals("Brian Otieno was removed by someone else", lastToast()?.message)
        assertTrue("the card goes", dash.agents.value.none { it.id == Fixtures.AGENT3_ID })
        vm.saveAssign(brian, "sales", null, onDone)
        assertEquals("Brian Otieno was removed by someone else", lastToast()?.message)
        vm.toggleOnline(brian, false)
        assertEquals("Brian Otieno was removed by someone else", lastToast()?.message)
        assertTrue("no optimistic switch left behind", vm.availability.value.isEmpty())
        assertEquals(2, done)
    }

    @Test fun removingSomeoneAlreadyRemoved_countsAsDone() {
        NetStressFixtures.status(fake, "DELETE", "/admin/agents/[^/]+", 404, "Agent not found")
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone)
        assertEquals(1, done)
        assertEquals("Brian Otieno was already removed", lastToast()?.message)
        assertEquals(ToastType.Success, lastToast()?.type)
    }

    @Test fun removeTimesOut_butTheyAreGone_countsAsRemoved() {
        NetStressFixtures.landThenTimeout(fake, "DELETE", "/admin/agents/[^/]+") {
            fake.on("GET", "/admin/agents", body = agentsWith { rows -> rows.removeAll { it["id"]!!.jsonPrimitive.content == Fixtures.AGENT3_ID } })
        }
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone)
        assertEquals(1, done)
        assertEquals("Agent removed", lastToast()?.message)
    }

    @Test fun removeOffline_saysOfflineNotTheWebsFixedWords() {
        NetStressFixtures.offline(fake, "DELETE", "/admin/agents/[^/]+")
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone)
        assertEquals(OFFLINE_TEXT, lastToast()?.message)
        assertEquals(0, done)
    }

    @Test fun doubleTapOnRemove_sendsOneDelete() {
        fake.on("DELETE", "/admin/agents/[^/]+") { _, _ ->
            vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone)
            200 to """{"ok":true}"""
        }
        vm.deleteAgent(agent(Fixtures.AGENT3_ID), onDone)
        assertEquals(1, writesTo("DELETE", "/admin/agents/.*"))
    }

    @Test fun availabilityDoubleTap_sendsOne_andATimeoutShowsTheServersValue() {
        var sent = 0
        fake.on("PATCH", "/admin/agents/[^/]+") { _, _ ->
            sent++
            vm.toggleOnline(agent(Fixtures.AGENT3_ID), true)   // impatient second tap
            200 to """{"ok":true}"""
        }
        vm.toggleOnline(agent(Fixtures.AGENT3_ID), false)
        assertEquals(1, sent)
        // No answer, and the server still says offline: the switch shows that, and says so.
        NetStressFixtures.timeout(fake, "PATCH", "/admin/agents/[^/]+")
        vm.toggleOnline(agent(Fixtures.AGENT3_ID), false)
        assertTrue(vm.availability.value.isEmpty())
        assertEquals("Couldn't reach the server — availability unchanged", lastToast()?.message)
    }

    @Test fun assignTimesOut_butLanded_closesAsAssigned() {
        NetStressFixtures.landThenTimeout(fake, "PATCH", "/admin/agents/[^/]+/role") {
            fake.on("GET", "/admin/agents", body = agentsWith { rows ->
                val i = rows.indexOfFirst { it["id"]!!.jsonPrimitive.content == Fixtures.AGENT3_ID }
                rows[i] = rows[i].with("custom_role_id" to "sales")
            })
        }
        vm.saveAssign(agent(Fixtures.AGENT3_ID), "sales", null, onDone)
        assertEquals(1, done)
        assertEquals("Role assigned", lastToast()?.message)
    }

    // ── Roles ────────────────────────────────────────────────────────────────

    @Test fun newRoleRetriedAfterATimeout_reusesItsId_soNoTwinIsMade() {
        NetStressFixtures.timeout(fake, "POST", "/admin/roles")
        val form = RoleForm("Delivery", "Riders", permissions = listOf("view_orders"), id = "role_1759000000000")
        vm.saveRole(null, form, onDone)
        assertEquals(UNCERTAIN_SAVE, lastToast()?.message)
        fake.on("POST", "/admin/roles") { _, b -> 200 to b!! }
        vm.saveRole(null, form, onDone)
        val ids = fake.calls.filter { it.method == "POST" && it.path == "/admin/roles" }
            .map { Json.parseToJsonElement(it.body!!).jsonObject["id"]!!.jsonPrimitive.content }
        assertEquals(listOf("role_1759000000000", "role_1759000000000"), ids)
        assertEquals(1, done)
    }

    @Test fun roleEditedAfterSomeoneDeletedIt_closesAndSaysSo() {
        NetStressFixtures.status(fake, "PATCH", "/admin/roles/[^/]+", 404, "Role not found")
        vm.saveRole(vm.roles.value.first { it.id == "sales" }, RoleForm("Sales 2"), onDone)
        assertEquals("That role was deleted by someone else", lastToast()?.message)
        assertEquals(1, done)
    }

    @Test fun roleDeleteTimesOut_butItIsGone_countsAsDeleted() {
        val remaining = Json.parseToJsonElement(TeamFixtures.roles).jsonArray.filter { it.jsonObject["id"]!!.jsonPrimitive.content != "trainee" }
        NetStressFixtures.landThenTimeout(fake, "DELETE", "/admin/roles/[^/]+") {
            fake.on("GET", "/admin/roles", body = JsonArray(remaining).toString())
        }
        vm.deleteRole(vm.roles.value.first { it.id == "trainee" }, onDone)
        assertEquals(1, done)
        assertEquals("Role deleted", lastToast()?.message)
        assertTrue(vm.roles.value.none { it.id == "trainee" })
    }

    // ── Status codes ─────────────────────────────────────────────────────────

    @Test fun everyStatusGetsPlainWords() {
        val cases = listOf(
            Triple(403, """{"detail":"Cannot modify a protected role"}""", "Cannot modify a protected role"),
            Triple(422, """{"detail":[{"loc":["body","name"],"msg":"Field required","type":"missing"}]}""", "Field required"),
            Triple(429, """{"detail":"Too Many Requests"}""", BUSY_TEXT),
            Triple(500, "Internal Server Error", "Something went wrong — please try again"),
            Triple(502, NetStressFixtures.HTML_502, DOWN_TEXT),
            Triple(503, "", DOWN_TEXT),
            Triple(418, "<html>teapot</html>", "Something went wrong — please try again"),
        )
        for ((code, body, want) in cases) {
            fake.on("PATCH", "/admin/roles/[^/]+", code = code, body = body)
            vm.saveRole(vm.roles.value.first { it.id == "sales" }, RoleForm("Sales"), onDone)
            val got = lastToast()!!.message
            assertEquals("$code", want, got)
            assertFalse("no markup for $code", got.contains("<"))
        }
        assertEquals(0, done)
    }

    // ── 401 mid-action ───────────────────────────────────────────────────────

    @Test fun staleToken_refreshesSilently_andTheSaveCompletes() {
        NetStressFixtures.unauthorizedOnce(fake, "PATCH", "/admin/agents/[^/]+") { _ -> 200 to """{"ok":true}""" }
        vm.saveEdit(agent(Fixtures.AGENT2_ID), "Grace W.", "grace@bethanyhouse.co.ke", onDone)
        assertEquals(1, done)
        assertEquals("Agent updated", lastToast()?.message)
        assertFalse(dash.sessionExpired.value)
        assertTrue(fake.called("POST", "/auth/refresh") || fake.called("POST", "/agent-auth/refresh"))
    }

    @Test fun sessionGone_dialogShows_formKept_andTheRetryWorksAfterSignIn() {
        NetStressFixtures.refreshRefused(fake)
        fake.on("PATCH", "/admin/agents/[^/]+", code = 401, body = """{"detail":"Could not validate credentials"}""")
        vm.saveEdit(agent(Fixtures.AGENT2_ID), "Grace W.", "grace@bethanyhouse.co.ke", onDone)
        assertTrue("the session-expired dialog", dash.sessionExpired.value)
        assertEquals(0, done)
        assertEquals(EXPIRED_TEXT, lastToast()?.message)
        assertFalse(vm.saving.value)
        // Signed back in: the same input, the same button, and it goes through.
        fake.on("PATCH", "/admin/agents/[^/]+", body = """{"ok":true}""")
        dash.onReauthenticated()
        vm.saveEdit(agent(Fixtures.AGENT2_ID), "Grace W.", "grace@bethanyhouse.co.ke", onDone)
        assertEquals(1, done)
    }

    // ── Leaving mid-request ──────────────────────────────────────────────────

    @Test fun signingOutMidSave_saysNothing_andClosesNothing() {
        val store = ViewModelStore()
        val v = ViewModelProvider(store, viewModelFactory { initializer { AgentsViewModel(dash) } })[AgentsViewModel::class.java]
        toasts.clear()
        // The agent signs out while the save is on the wire: the screen's store is cleared.
        fake.on("PATCH", "/admin/agents/[^/]+") { _, _ -> store.clear(); 500 to "Internal Server Error" }
        v.saveEdit(agent(Fixtures.AGENT2_ID), "Grace W.", "grace@bethanyhouse.co.ke", onDone)
        assertTrue("no toast for a screen that is gone: $toasts", toasts.none { it.type == ToastType.Error })
        assertEquals(0, done)
    }
}
