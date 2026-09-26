package ke.co.bethanyhouse.neema.profile

import ke.co.bethanyhouse.neema.feature.profile.ProfileViewModel
import ke.co.bethanyhouse.neema.team.AreaTest
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import kotlinx.coroutines.launch
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

/** Round 9 (lifecycle): the Profile forms across a rotation, a restart, and a save on the wire. */
class ProfileLifecycleTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.writes(f)

    private fun ProfileViewModel.announced(): List<String> {
        // Whatever is waiting is handed over at once; nothing here waits on a clock.
        val got = mutableListOf<String>()
        kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.Unconfined).launch { closed.collect { got += it } }.cancel()
        return got
    }
    private fun me() = dash.me.value ?: dash.agents.value.first { it.id == dash.session.value?.agentId }

    @Test fun theEditFormSurvivesARestartButThePasswordsDoNot() {
        val vm = ProfileViewModel(dash)
        vm.fillForm(me())
        vm.name = "Moses M."; vm.department = "Sales"
        vm.password = "brandnew-pass-9"; vm.confirm = "brandnew-pass-9"
        val saved = vm.saveUi()!!
        assertFalse("passwords never go into saved state", "brandnew-pass-9" in saved)

        val fresh = ProfileViewModel(dash).apply { restoreUi(saved) }
        // The screen fills the form from /me on its first frame: the restored typing wins.
        fresh.fillForm(me())
        assertEquals("Moses M." to "Sales", fresh.name to fresh.department)
        assertEquals(me().email, fresh.email)
        assertEquals("" to "", fresh.password to fresh.confirm)
    }

    @Test fun nothingIsSavedBeforeTheFormIsFilled() {
        assertNull(ProfileViewModel(dash).saveUi())
    }

    /** Like the web's `form`: filled once per agent, never refilled over the typing. */
    @Test fun theFormIsFilledOncePerAgent() {
        val vm = ProfileViewModel(dash)
        vm.fillForm(me())
        vm.name = "typed"
        vm.fillForm(me())
        assertEquals("typed", vm.name)
    }

    @Test fun aPasswordChangeThatLandsDuringARotationFoldsTheNewScreensForm() {
        val vm = ProfileViewModel(dash)
        vm.password = "brandnew-pass-9"; vm.confirm = "brandnew-pass-9"
        vm.changePassword(vm.password, vm.confirm) { vm.close("password") }
        assertEquals("Password changed successfully", lastToast()?.message)
        assertEquals(listOf("password"), vm.announced())
        assertEquals("" to "", vm.password to vm.confirm)
    }

    @Test fun aFailedPasswordChangeKeepsTheBoxes() {
        fail("PATCH", "/admin/me", 400, "Nope")
        val vm = ProfileViewModel(dash)
        vm.password = "brandnew-pass-9"; vm.confirm = "brandnew-pass-9"
        vm.changePassword(vm.password, vm.confirm) { vm.close("password") }
        assertEquals(emptyList<String>(), vm.announced())
        assertEquals("brandnew-pass-9", vm.password)
    }
}
