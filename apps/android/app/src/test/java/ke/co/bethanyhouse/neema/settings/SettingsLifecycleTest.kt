package ke.co.bethanyhouse.neema.settings

import ke.co.bethanyhouse.neema.feature.settings.SettingsViewModel
import ke.co.bethanyhouse.neema.team.AreaTest
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Round 9 (lifecycle): unsaved standing orders, offer and local fields come
 * back after Android restarts the app — into the box once it has loaded,
 * still unsaved so a return to the screen doesn't overwrite them — and
 * secrets never go into saved state.
 */
class SettingsLifecycleTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.settings(f)

    @Test fun unsavedStandingOrdersSurviveARestart() {
        val vm = SettingsViewModel(dash)
        vm.setDirectives("Push copes this week — Easter is close.")
        val fresh = SettingsViewModel(dash).apply { restoreUi(vm.saveUi()) }
        assertEquals("Push copes this week — Easter is close.", fresh.directives.value)
        assertTrue(fresh.directivesLoaded.value)
        // Still unsaved: nothing was written for it.
        assertTrue(writes().isEmpty())
        // Still unsaved after the restart: saved again if Android closes the app a second time.
        assertTrue("Push copes this week" in fresh.saveUi())
    }

    /** The saved text arrives before the card has loaded (a slow network after the restart): it waits for the load. */
    @Test fun unsavedStandingOrdersWaitForTheCardToLoad() {
        val saved = SettingsViewModel(dash).apply { setDirectives("Quote 3-week lead times.") }.saveUi()
        fail("GET", "/admin/settings/directives", 500, "x")
        val fresh = SettingsViewModel(dash).apply { restoreUi(saved) }
        assertFalse(fresh.directivesLoaded.value)
        assertEquals("", fresh.directives.value)
        assertTrue("still waiting, it stays in saved state", "Quote 3-week lead times." in fresh.saveUi())
        TeamFixtures.settings(fake)
        fresh.retry("directives")
        assertTrue(fresh.directivesLoaded.value)
        assertEquals("the unsaved typing goes back in the box", "Quote 3-week lead times.", fresh.directives.value)
    }

    @Test fun aCleanCardSavesNothing() {
        val saved = SettingsViewModel(dash).saveUi()
        assertFalse("directives" in saved)
        assertFalse("offer" in saved)
    }

    @Test fun anUnsavedOfferSurvivesARestart() {
        val vm = SettingsViewModel(dash)
        vm.editDraft { it.copy(name = "Pentecost 15", percent = 15.0) }
        val fresh = SettingsViewModel(dash).apply { restoreUi(vm.saveUi()) }
        assertEquals("Pentecost 15", fresh.draft.value.name)
        assertEquals(15.0, fresh.draft.value.percent, 0.0)
        assertEquals("the stored offer is still the server's", "Easter Sale", fresh.offer.value?.campaign?.name)
    }

    @Test fun localFieldsSurviveButSecretsAreNeverSaved() {
        val vm = SettingsViewModel(dash)
        vm.biz.value = vm.biz.value.copy(businessName = "Bethany House Kenya")
        vm.ai.value = vm.ai.value.copy(draftApproval = false, escalationKeywords = "refund")
        vm.toggleIntegration("slack")
        vm.setConfig("slack", "slack_channel", "#alerts")
        vm.setConfig("whatsapp", "token", "EAAx-super-secret")
        vm.newStage.value = "Sampling"
        val saved = vm.saveUi()
        assertFalse("an access token never goes into saved state", "EAAx-super-secret" in saved)

        val fresh = SettingsViewModel(dash).apply { restoreUi(saved) }
        assertEquals("Bethany House Kenya", fresh.biz.value.businessName)
        assertEquals(false, fresh.ai.value.draftApproval)
        assertEquals("refund", fresh.ai.value.escalationKeywords)
        assertTrue(fresh.integrations.value.first { it.key == "slack" }.connected)
        assertEquals("#alerts", fresh.integConfig.value["slack"]?.get("slack_channel"))
        assertEquals(null, fresh.integConfig.value["whatsapp"]?.get("token"))
        assertEquals("Sampling", fresh.newStage.value)
    }

    /** The stage box lives in the ViewModel: a save that lands after the phone turned still clears it. */
    @Test fun anAddedStageClearsTheBoxEvenAcrossARotation() {
        val vm = SettingsViewModel(dash)
        vm.newStage.value = "Sampling"
        vm.addStage(vm.newStage.value) { if (vm.newStage.value == "Sampling") vm.newStage.value = "" }
        assertEquals("", vm.newStage.value)
        assertEquals(listOf("measuring", "Sampling"), vm.stages.value)
    }
}
