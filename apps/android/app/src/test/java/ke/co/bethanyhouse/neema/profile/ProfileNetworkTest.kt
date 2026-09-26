package ke.co.bethanyhouse.neema.profile

import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.agents.UNCERTAIN_SAVE
import ke.co.bethanyhouse.neema.feature.profile.PASSWORD_UNCERTAIN
import ke.co.bethanyhouse.neema.feature.profile.ProfileViewModel
import ke.co.bethanyhouse.neema.feature.reports.BUSY_TEXT
import ke.co.bethanyhouse.neema.feature.reports.DOWN_TEXT
import ke.co.bethanyhouse.neema.feature.reports.EXPIRED_TEXT
import ke.co.bethanyhouse.neema.feature.reports.OFFLINE_TEXT
import ke.co.bethanyhouse.neema.feature.reports.TIMEOUT_TEXT
import ke.co.bethanyhouse.neema.team.AreaTest
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.NetStressFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The Profile screen's saves and loads on a bad phone network. */
class ProfileNetworkTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.install(f)

    private val vm by lazy { ProfileViewModel(dash).also { fake.calls.clear(); toasts.clear() } }
    private var done = 0
    private val onDone: () -> Unit = { done++ }
    private fun patches() = fake.calls.count { it.method == "PATCH" && it.path == "/admin/me" }

    // ── Load ─────────────────────────────────────────────────────────────────

    @Test fun signedInOffline_saysWhyInsteadOfLoadingForever_thenRetryLoads() {
        val f = FakeNeema.withFixtures().also(TeamFixtures::install)
        NetStressFixtures.offline(f, "GET", "/admin/me")
        NetStressFixtures.offline(f, "GET", "/admin/agents")
        val d = dashboard(paparazzi.context, f)
        val v = ProfileViewModel(d)
        assertNull(d.me.value)
        assertEquals(OFFLINE_TEXT, v.loadError.value)
        f.on("GET", "/admin/me", body = TeamFixtures.me)
        f.on("GET", "/admin/agents", body = TeamFixtures.agents)
        v.refresh()
        assertEquals("Moses Mwicigi", d.me.value?.name)
        assertNull(v.loadError.value)
        assertFalse(v.refreshing.value)
    }

    @Test fun pullToRefreshFailing_keepsTheProfile_andSaysSo() {
        vm
        NetStressFixtures.timeout(fake, "GET", "/admin/me")
        vm.refresh()
        assertEquals("Moses Mwicigi", dash.me.value?.name)
        assertEquals("Couldn't refresh your profile. $TIMEOUT_TEXT", lastToast()?.message)
    }

    // ── Save profile ─────────────────────────────────────────────────────────

    @Test fun saveTimesOut_butLanded_countsAsSaved() {
        NetStressFixtures.landThenTimeout(fake, "PATCH", "/admin/me") {
            fake.on("GET", "/admin/me", body = TeamFixtures.ormAgent(name = "Moses M."))
        }
        vm.saveProfile("Moses M.", "moses@bethanyhouse.co.ke", onDone)
        assertEquals(1, done)
        assertEquals("Profile updated", lastToast()?.message)
    }

    @Test fun saveTimesOut_notLanded_keepsTheForm() {
        NetStressFixtures.timeout(fake, "PATCH", "/admin/me")
        vm.saveProfile("Moses M.", "moses@bethanyhouse.co.ke", onDone)
        assertEquals(0, done)
        assertEquals(UNCERTAIN_SAVE, lastToast()?.message)
        assertFalse(vm.saving.value)
    }

    @Test fun duplicateEmailRace_500_saysWhy() {
        fake.on("PATCH", "/admin/me", code = 500, body = "Internal Server Error")
        vm.saveProfile("Moses", "someone.new@bethanyhouse.co.ke", onDone)
        assertEquals("Failed to update profile — that email may already be in use", lastToast()?.message)
        assertEquals(0, done)
    }

    @Test fun statusesGetPlainWords() {
        for ((code, body, want) in listOf(
            Triple(429, "{}", BUSY_TEXT),
            Triple(502, NetStressFixtures.HTML_502, DOWN_TEXT),
            Triple(422, """{"detail":[{"msg":"value is not a valid email address"}]}""", "value is not a valid email address"),
        )) {
            fake.on("PATCH", "/admin/me", code = code, body = body)
            vm.saveProfile("Moses", "moses@bethanyhouse.co.ke", onDone)
            assertEquals("$code", want, lastToast()?.message)
        }
        assertEquals(0, done)
    }

    @Test fun doubleTapOnSave_sendsOnce() {
        fake.on("PATCH", "/admin/me") { _, _ ->
            vm.saveProfile("Moses M.", "moses@bethanyhouse.co.ke", onDone)
            200 to TeamFixtures.ormAgent(name = "Moses M.")
        }
        vm.saveProfile("Moses M.", "moses@bethanyhouse.co.ke", onDone)
        assertEquals(1, patches())
        assertEquals(1, done)
    }

    // ── Password ─────────────────────────────────────────────────────────────

    @Test fun passwordTimeout_isNeverCalledAFailure_andKeepsWhatWasTyped() {
        NetStressFixtures.timeout(fake, "PATCH", "/admin/me")
        vm.changePassword("n3wpassword!", "n3wpassword!", onDone)
        assertEquals(0, done)
        assertEquals(PASSWORD_UNCERTAIN, lastToast()?.message)
        assertFalse(lastToast()!!.message.contains("n3wpassword!"))
        // The same entry, tapped again, goes through.
        fake.on("PATCH", "/admin/me", body = TeamFixtures.me)
        vm.changePassword("n3wpassword!", "n3wpassword!", onDone)
        assertEquals(1, done)
        assertEquals("Password changed successfully", lastToast()?.message)
    }

    @Test fun passwordErrorsNeverEchoThePassword() {
        NetStressFixtures.status(fake, "PATCH", "/admin/me", 422, "'correct-horse-9' is in a breach list")
        vm.changePassword("correct-horse-9", "correct-horse-9", onDone)
        val msg = lastToast()!!.message
        assertFalse(msg, msg.contains("correct-horse-9"))
        assertEquals(0, done)
    }

    @Test fun passwordOffline_saysOffline() {
        NetStressFixtures.offline(fake, "PATCH", "/admin/me")
        vm.changePassword("n3wpassword!", "n3wpassword!", onDone)
        assertEquals(OFFLINE_TEXT, lastToast()?.message)
        assertEquals(0, done)
    }

    @Test fun passwordWithAnExpiredSession_dialogShows_andTheEntryIsKeptForTheRetry() {
        NetStressFixtures.refreshRefused(fake)
        fake.on("PATCH", "/admin/me", code = 401, body = """{"detail":"Could not validate credentials"}""")
        vm.changePassword("n3wpassword!", "n3wpassword!", onDone)
        assertTrue(dash.sessionExpired.value)
        assertEquals(EXPIRED_TEXT, lastToast()?.message)
        assertEquals("the form stays open", 0, done)
    }

    // ── Availability ─────────────────────────────────────────────────────────

    @Test fun availabilityDoubleTap_sendsOnce() {
        var sent = 0
        fake.on("PATCH", "/admin/agents/[^/]+") { _, _ ->
            sent++
            vm.setAvailable(Fixtures.ME_ID, true)
            200 to """{"ok":true}"""
        }
        vm.setAvailable(Fixtures.ME_ID, false)
        assertEquals(1, sent)
    }

    @Test fun availabilityTimeout_showsTheServersValue() {
        NetStressFixtures.timeout(fake, "PATCH", "/admin/agents/[^/]+")
        vm.setAvailable(Fixtures.ME_ID, false)
        assertNull("no optimistic value left behind", vm.availableOverride.value)
        assertEquals("Couldn't reach the server — availability unchanged", lastToast()?.message)
        assertEquals(ToastType.Error, lastToast()?.type)
    }
}
