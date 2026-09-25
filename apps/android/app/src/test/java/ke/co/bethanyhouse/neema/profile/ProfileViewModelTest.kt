package ke.co.bethanyhouse.neema.profile

import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.profile.NOTIF_PREFS
import ke.co.bethanyhouse.neema.feature.profile.ProfileViewModel
import ke.co.bethanyhouse.neema.team.AreaTest
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** ProfileView.tsx: PATCH /admin/me for name/email and password, plus the personal switches. */
class ProfileViewModelTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.writes(f)
    private val vm by lazy { ProfileViewModel(dash).also { fake.calls.clear() } }
    private var done = 0

    @Test fun saveProfilePatchesMeAndRefetches() {
        vm.saveProfile(" Moses M. ", "moses@bethanyhouse.co.ke") { done++ }
        val w = writes().single()
        assertEquals("PATCH" to "/admin/me", w.method to w.path)
        assertEquals(el("""{"name":"Moses M.","email":"moses@bethanyhouse.co.ke"}"""), w.json())
        assertEquals("Profile updated", lastToast()?.message)
        assertEquals(1, done)
        assertTrue(fake.called("GET", "/admin/me"))
        assertTrue(fake.called("GET", "/admin/agents"))
    }

    @Test fun blankNameIsNotSent() {
        // The web would PATCH an empty name; the server stores it. Caught here instead.
        vm.saveProfile("", "moses@bethanyhouse.co.ke") { done++ }
        assertTrue(writes().isEmpty())
        assertEquals("Name and email required", lastToast()?.message)
    }

    @Test fun saveProfileFailureKeepsEditing() {
        fail("PATCH", "/admin/me", 500, "Email already in use")
        vm.saveProfile("Moses", "grace@bethanyhouse.co.ke") { done++ }
        assertEquals(0, done)
        assertEquals("Email already in use", lastToast()?.message)
        assertEquals(ToastType.Error, lastToast()?.type)
    }

    @Test fun passwordMatchIsCheckedBeforeLength() {
        vm.changePassword("abc", "abd") { done++ }
        assertEquals("Passwords don't match", lastToast()?.message)
        vm.changePassword("abc", "abc") { done++ }
        assertEquals("Password must be at least 8 characters", lastToast()?.message)
        assertTrue(writes().isEmpty())
        assertEquals(0, done)
    }

    @Test fun passwordChangeSendsOnlyThePassword() {
        vm.changePassword("longpassword", "longpassword") { done++ }
        val w = writes().single()
        assertEquals("PATCH" to "/admin/me", w.method to w.path)
        assertEquals(el("""{"password":"longpassword"}"""), w.json())
        assertEquals("Password changed successfully", lastToast()?.message)
        assertEquals(1, done)
    }

    @Test fun availabilityPatchesYourOwnRow() {
        vm.setAvailable(Fixtures.ME_ID, false)
        val w = writes().single()
        assertEquals("PATCH" to "/admin/agents/${Fixtures.ME_ID}", w.method to w.path)
        assertEquals(el("""{"is_available":false}"""), w.json())
        assertEquals(false, vm.availableOverride.value)
        assertEquals("You're away", lastToast()?.message)
        vm.reconcile(false)
        assertNull(vm.availableOverride.value)
    }

    @Test fun availabilityFailureReverts() {
        fail("PATCH", "/admin/agents/.*", 500, "x")
        vm.setAvailable(Fixtures.ME_ID, false)
        assertNull(vm.availableOverride.value)
        assertEquals("Failed to update availability", lastToast()?.message)
    }

    @Test fun notificationSwitchesStartAtTheWebDefaultsAndPersist() {
        assertEquals(mapOf("new_conv" to true, "human_transfer" to true, "order_updates" to false, "daily_summary" to true), vm.notifs.value)
        vm.toggleNotif("order_updates")
        vm.toggleNotif("daily_summary")
        assertEquals(true, vm.notifs.value["order_updates"])
        assertEquals(false, vm.notifs.value["daily_summary"])
        // A fresh screen reads them back from the device.
        val again = ProfileViewModel(dash)
        assertEquals(true, again.notifs.value["order_updates"])
        assertEquals(false, again.notifs.value["daily_summary"])
        assertTrue("notification switches never touch the API", writes().isEmpty())
        assertEquals(4, NOTIF_PREFS.size)
    }

    @Test fun backgroundSwitchIsADevicePreference() {
        val prefs = dash.container.prefs
        val before = prefs.backgroundLive.value
        prefs.setBackgroundLive(!before)
        assertEquals(!before, prefs.backgroundLive.value)
        assertTrue(writes().isEmpty())
    }
}
