package ke.co.bethanyhouse.neema.team

import ke.co.bethanyhouse.neema.feature.agents.AgentsViewModel
import ke.co.bethanyhouse.neema.feature.agents.ROLE_COLORS
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Round 9 (lifecycle): the Team dialogs' typed input across a rotation (the
 * ViewModel survives; its save still closes the dialog of the NEW screen)
 * and across process death (a fresh ViewModel gets the saved state back —
 * never the passwords).
 */
class TeamLifecycleTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.install(f)

    private fun agent(id: String) = dash.agents.value.first { it.id == id }

    /** The dialogs to close that a save announced, drained without waiting. */
    private fun AgentsViewModel.announced(): List<String> {
        // Whatever is waiting is handed over at once; nothing here waits on a clock.
        val got = mutableListOf<String>()
        kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.Unconfined).launch { closed.collect { got += it } }.cancel()
        return got
    }

    @Test fun savedStateKeepsEveryFieldButThePasswords() {
        val vm = AgentsViewModel(dash)
        vm.forms.apply {
            createName = "Jane Doe"; createEmail = "jane@bethanyhouse.co.ke"; createPassword = "hunter22secret"; createRole = "admin"
            password = "newpass-xyz-1"; confirm = "newpass-xyz-1"
            roleName = "Night shift"; roleDescription = "After 6pm"; roleColor = ROLE_COLORS[3]
            rolePerms = listOf("view_conversations", "reply_conversations")
            assignRole = "sales"; assignOverride = true; assignPerms = listOf("view_orders")
            editName = "Grace W."; editEmail = "grace@bethanyhouse.co.ke"
        }
        val saved = vm.saveUi()
        assertFalse("no password is written to saved state", "hunter22secret" in saved || "newpass-xyz-1" in saved)

        // Android killed the app: a fresh ViewModel, the saved state handed back.
        val fresh = AgentsViewModel(dash).apply { restoreUi(saved) }
        fresh.forms.apply {
            assertEquals("Jane Doe" to "jane@bethanyhouse.co.ke", createName to createEmail)
            assertEquals("admin", createRole)
            assertEquals("", createPassword)
            assertEquals("" to "", password to confirm)
            assertEquals(listOf("Night shift", "After 6pm", ROLE_COLORS[3]), listOf(roleName, roleDescription, roleColor))
            assertEquals(listOf("view_conversations", "reply_conversations"), rolePerms)
            assertEquals(Triple("sales", true, listOf("view_orders")), Triple(assignRole, assignOverride, assignPerms))
            assertEquals("Grace W." to "grace@bethanyhouse.co.ke", editName to editEmail)
        }
    }

    @Test fun aNewRoleKeepsItsDraftIdAcrossARestart() {
        val vm = AgentsViewModel(dash)
        vm.forms.openRole(null)
        val id = vm.forms.roleDraftId
        val fresh = AgentsViewModel(dash).apply { restoreUi(vm.saveUi()) }
        assertEquals("a retry after the restart updates, never duplicates", id, fresh.forms.roleDraftId)
    }

    @Test fun garbageSavedStateIsIgnored() {
        val fresh = AgentsViewModel(dash).apply { restoreUi("not json") }
        assertEquals("", fresh.forms.createName)
        assertEquals("agent", fresh.forms.createRole)
    }

    /**
     * The phone turned while "Create Agent" was on the wire: the screen that
     * started it is gone. The success is announced by the ViewModel and the
     * new screen closes the dialog when it starts listening.
     */
    @Test fun aSaveThatLandsDuringARotationClosesTheNewScreensDialog() {
        val vm = AgentsViewModel(dash)
        vm.forms.apply { createName = "Jane Doe"; createEmail = "jane@bethanyhouse.co.ke"; createPassword = "s3cretpass" }
        // No screen is collecting (it is being recreated).
        vm.createAgent(vm.forms.createName, vm.forms.createEmail, vm.forms.createPassword, vm.forms.createRole) { vm.close("create") }
        assertEquals("Agent created", lastToast()?.message)
        assertEquals(listOf("create"), vm.announced())
        // The web clears createForm once the agent exists.
        assertEquals(listOf("", "", "", "agent"), vm.forms.run { listOf(createName, createEmail, createPassword, createRole) })
    }

    @Test fun aFailedSaveKeepsTheDialogAndEveryField() {
        fail("POST", "/admin/agents", 422, "Invalid email")
        val vm = AgentsViewModel(dash)
        vm.forms.apply { createName = "Jane"; createEmail = "jane@x"; createPassword = "s3cretpass" }
        vm.createAgent("Jane", "jane@x", "s3cretpass", "agent") { vm.close("create") }
        assertTrue(vm.announced().isEmpty())
        assertEquals(listOf("Jane", "jane@x", "s3cretpass"), vm.forms.run { listOf(createName, createEmail, createPassword) })
    }

    @Test fun aPasswordResetEmptiesTheBoxesOnceItLands() {
        val vm = AgentsViewModel(dash)
        vm.forms.apply { password = "brandnew99"; confirm = "brandnew99" }
        vm.savePassword(agent(Fixtures.AGENT2_ID), "brandnew99", "brandnew99") { vm.close("pw") }
        assertEquals(listOf("pw"), vm.announced())
        assertEquals("" to "", vm.forms.password to vm.forms.confirm)
    }

    /** Where the web resets a form on open (and where it doesn't: Add Agent keeps its text across Cancel). */
    @Test fun openingADialogStartsItsFormWhereTheWebDoes() {
        val vm = AgentsViewModel(dash)
        val a = agent(Fixtures.AGENT2_ID)
        vm.forms.apply { editName = "stale"; password = "stale"; confirm = "stale"; roleName = "stale" }
        vm.forms.openEdit(a)
        assertEquals(a.name to a.email, vm.forms.editName to vm.forms.editEmail)
        vm.forms.openPassword()
        assertEquals("" to "", vm.forms.password to vm.forms.confirm)
        val support = vm.roles.value.first { it.id == "support" }
        vm.forms.openRole(support)
        assertEquals(support.name to support.permissions, vm.forms.roleName to vm.forms.rolePerms)
        vm.forms.openRole(null)
        assertEquals("" to emptyList<String>(), vm.forms.roleName to vm.forms.rolePerms)
        vm.forms.openAssign(a, vm.roles.value)
        assertEquals(a.customRoleId ?: "", vm.forms.assignRole)
        assertEquals(a.customPermissions != null, vm.forms.assignOverride)
        assertNull("no dialog was closed by opening others", vm.announced().firstOrNull())
    }
}
