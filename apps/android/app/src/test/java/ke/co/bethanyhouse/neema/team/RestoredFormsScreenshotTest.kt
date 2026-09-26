package ke.co.bethanyhouse.neema.team

import androidx.compose.runtime.CompositionLocalProvider
import ke.co.bethanyhouse.neema.feature.agents.AgentsScreen
import ke.co.bethanyhouse.neema.feature.agents.LocalTeamPreview
import ke.co.bethanyhouse.neema.feature.agents.TeamPreview
import ke.co.bethanyhouse.neema.feature.profile.LocalProfilePreview
import ke.co.bethanyhouse.neema.feature.profile.ProfilePreview
import ke.co.bethanyhouse.neema.feature.profile.ProfileScreen
import ke.co.bethanyhouse.neema.feature.settings.SettingsScreen
import ke.co.bethanyhouse.neema.feature.settings.SettingsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/**
 * Round 9: Team, Profile and Settings as the agent left them, and as they
 * come back after Android killed the app in the background — every half-typed
 * field and ticked box restored, every password box empty (passwords are
 * never written to saved state).
 */
class RestoredFormsScreenshotTest : AreaShots() {
    @Test fun addAgentAfterRestart() {
        val d = dash(FakeNeema.withFixtures().also(TeamFixtures::install))
        var preview = TeamPreview(
            dialog = "create",
            typed = mapOf("name" to "Jane Wanjiru", "email" to "jane@bethanyhouse.co.ke", "password" to "hunter22secret", "role" to "admin"),
        )
        val saved = paparazzi.beforeAndRestored(Store(), Store(), between = { preview = TeamPreview() }) {
            CompositionLocalProvider(LocalTeamPreview provides preview) { AgentsScreen(d) }
        }
        assertFalse("the password is not in saved state", saved.savedMentions("hunter22secret"))
        assertEquals("the dialog is open again", true, saved.restoredValue("team.create"))
    }

    @Test fun roleEditorAfterRestart() {
        val d = dash(FakeNeema.withFixtures().also(TeamFixtures::install))
        var preview = TeamPreview(
            tab = "roles", dialog = "role:support",
            typed = mapOf("name" to "Support (nights)", "perms" to "view_conversations,reply_conversations,view_orders,view_catalog"),
        )
        val r = paparazzi.beforeAndRestored(Store(), Store(), between = { preview = TeamPreview() }) {
            CompositionLocalProvider(LocalTeamPreview provides preview) { AgentsScreen(d) }
        }
        assertEquals("roles", r.restoredValue("team.tab"))
        assertEquals("support", r.restoredValue("team.role"))
    }

    @Test fun profileFormsAfterRestart() {
        paparazzi.unsafeUpdateConfig(deviceConfig = Devices.tallPhone(3400))
        val d = dash(FakeNeema.withFixtures().also(TeamFixtures::writes))
        var preview = ProfilePreview(
            editMode = true, changingPassword = true,
            typed = mapOf("name" to "Moses M. Mwicigi", "password" to "brandnew-pass-9", "confirm" to "brandnew-pass-9"),
        )
        val saved = paparazzi.beforeAndRestored(Store(), Store(), between = { preview = ProfilePreview() }) {
            CompositionLocalProvider(LocalProfilePreview provides preview) { ProfileScreen(d) }
        }
        assertFalse("the password is not in saved state", saved.savedMentions("brandnew-pass-9"))
        assertEquals(true, saved.restoredValue("profile.edit"))
        assertEquals(true, saved.restoredValue("profile.password"))
    }

    @Test fun unsavedStandingOrdersAfterRestart() {
        val d = dash(FakeNeema.withFixtures().also { TeamFixtures.settings(it) })
        val before = Store()
        before.put(SettingsViewModel(d)).apply {
            setDirectives("Push copes this week — Easter is close. Quote 3-week lead times on made-to-order.")
            newStage.value = "Sampling"
        }
        paparazzi.beforeAndRestored(before, Store()) { SettingsScreen(d) }
    }
}
