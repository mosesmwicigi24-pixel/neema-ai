package ke.co.bethanyhouse.neema.settings

import ke.co.bethanyhouse.neema.core.util.AppClock

import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.settings.SettingsViewModel
import ke.co.bethanyhouse.neema.team.AreaTest
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/**
 * Settings against crm.py's real handlers (TeamFixtures.settings re-implements
 * each one): exact requests, the server's cleaning echoed back, every error.
 */
class SettingsContractTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.settings(f)
    private val vm by lazy { SettingsViewModel(dash).also { fake.calls.clear() } }

    // ── /admin/settings/directives ───────────────────────────────────────────

    @Test fun directivesRoundTrip() {
        assertEquals(TeamFixtures.DIRECTIVES_MAX, vm.maxChars.value)
        vm.setDirectives("  Push copes this week.\n")
        vm.saveDirectives()
        val w = writes().single()
        assertEquals("PUT" to "/admin/settings/directives", w.method to w.path)
        assertEquals(el("""{"directives":"  Push copes this week.\n"}"""), w.json())
        assertEquals("set_directives strips; the box shows what was stored", "Push copes this week.", vm.directives.value)
    }

    @Test fun directivesNeverExceedTheServersCap() {
        vm.setDirectives("y".repeat(900))
        vm.saveDirectives()
        assertEquals(600, writes().single().json()["directives"].toString().trim('"').length)
    }

    @Test fun directivesTolerateAMissingMaxChars() {
        fake.on("GET", "/admin/settings/directives", body = """{"directives":null}""")
        val v = SettingsViewModel(dash)
        assertEquals("", v.directives.value)
        assertEquals(600, v.maxChars.value)
        assertTrue(v.directivesLoaded.value)
    }

    @Test fun directivesRefusedForANonAdmin() {
        TeamFixtures.settings(fake, admin = false)
        vm.saveDirectives()
        assertEquals("Couldn't save (admin only)", lastToast()?.message)
    }

    /** No answer and the server still holds the old text: say it may not have saved, and keep what was typed. */
    @Test fun directivesOfflineSaysSo() {
        fake.on("PUT", "/admin/settings/directives") { _, _ -> throw java.io.IOException("reset") }
        vm.setDirectives("Push copes this week.")
        vm.saveDirectives()
        assertEquals(ke.co.bethanyhouse.neema.feature.agents.UNCERTAIN_SAVE, lastToast()?.message)
        assertEquals("Push copes this week.", vm.directives.value)
    }

    // ── /admin/settings/pipeline-stages ──────────────────────────────────────

    @Test fun stagesShowWhatTheServerKept() {
        // The server trims and cuts to 18; the list shows its answer, not what was typed.
        vm.addStage("  Awaiting the deposit money ")
        assertEquals(el("""{"stages":["measuring","Awaiting the depos"]}"""), writes().single().json())
        assertEquals(listOf("measuring", "Awaiting the depos"), vm.stages.value)
    }

    @Test fun stagesRefusedForANonAdmin() {
        TeamFixtures.settings(fake, admin = false)
        vm.addStage("Sampling")
        assertEquals("Only an admin can change pipeline stages.", lastToast()?.message)
        assertEquals(listOf("measuring"), vm.stages.value)
    }

    @Test fun theServersFourStageLimitIsShownVerbatim() {
        // Another admin filled the list meanwhile: the local count said 1, the server says no.
        fake.on("PUT", "/admin/settings/pipeline-stages", code = 422, body = """{"detail":"At most 4 custom stages"}""")
        vm.addStage("Sampling")
        assertEquals("At most 4 custom stages", lastToast()?.message)
    }

    // ── /admin/settings/translation ──────────────────────────────────────────

    @Test fun translationDecodesTheSpendAsANumber() {
        assertEquals(3.4187, vm.translation.value!!.spend30dUsd, 0.0)
        assertEquals(812, vm.translation.value!!.calls30d)
        vm.toggleTranslation()
        assertEquals(el("""{"enabled":false}"""), writes().single().json())
        assertEquals(false, vm.translation.value?.enabled)
    }

    @Test fun translationToleratesAStringSpendAndMissingKeys() {
        fake.on("GET", "/admin/settings/translation", body = """{"enabled":true,"spend_30d_usd":"0.0042"}""")
        val v = SettingsViewModel(dash)
        assertEquals(0.0042, v.translation.value!!.spend30dUsd, 0.0)
        assertEquals(0, v.translation.value!!.calls30d)
    }

    @Test fun translationRefusedForANonAdminRevertsTheSwitch() {
        TeamFixtures.settings(fake, admin = false)
        vm.toggleTranslation()
        assertEquals(true, vm.translation.value?.enabled)
        assertEquals("Couldn't change that (admin only)", lastToast()?.message)
    }

    // ── /admin/settings/offer ────────────────────────────────────────────────

    @Test fun offerDecodesTheStoredCampaign() {
        val o = vm.offer.value!!
        assertEquals(70.0, o.maxPercent, 0.0)
        assertTrue(o.running)
        assertEquals(TeamFixtures.EASTER_SAYS, o.says)
        assertEquals(10.0, o.campaign!!.percent, 0.0)
        assertNull(o.campaign!!.startsOn)
        assertEquals(listOf("Vestments"), o.campaign!!.categories)
    }

    @Test fun offerToleratesMissingOptionalKeys() {
        fake.on("GET", "/admin/settings/offer", body = """{"campaign":{"name":"X","percent":5,"ends_on":"2099-01-01"},"running":true}""")
        val v = SettingsViewModel(dash)
        assertEquals("all", v.offer.value!!.campaign!!.scope)
        assertEquals(emptyList<String>(), v.offer.value!!.campaign!!.skus)
        assertEquals("", v.offer.value!!.says)
    }

    @Test fun offerPutSendsTheWholeCampaignAndShowsTheServersVersion() {
        vm.editDraft { it.copy(name = "  Harvest Offer  ", percent = 20.0, scope = "all", categories = emptyList(), endsOn = "2099-10-25") }
        vm.saveOffer(vm.draft.value)
        val w = writes().single()
        assertEquals("PUT" to "/admin/settings/offer", w.method to w.path)
        val c = w.json()["campaign"]!!.jsonObject
        assertEquals(setOf("name", "percent", "scope", "categories", "skus", "ends_on"), c.keys - "starts_on")
        // NeemaJson drops nulls (explicitNulls = false); parse() reads c.get("starts_on") → None either way.
        assertTrue(c["starts_on"] == null || c["starts_on"] == JsonNull)
        // parse() trims the name and stores percent as an int.
        assertEquals("Harvest Offer", vm.offer.value!!.campaign!!.name)
        assertEquals("Harvest Offer", vm.draft.value.name)
        assertTrue(vm.offer.value!!.running)
        assertEquals("Offer live — Neema will say: Harvest Offer — 20% off everything in the catalogue, until 25 October 2099", lastToast()?.message)
    }

    @Test fun anOfferThatStartsLaterIsSavedNotLive() {
        val start = AppClock.today().plusDays(10).toString()
        vm.editDraft { it.copy(startsOn = start) }
        vm.saveOffer(vm.draft.value)
        assertFalse(vm.offer.value!!.running)
        assertEquals("", vm.offer.value!!.says)
        assertEquals("Offer saved — Neema starts mentioning it on ${Fmt.date(start)}", lastToast()?.message)
        assertEquals(ToastType.Success, lastToast()?.type)
    }

    @Test fun anOfferWhoseLastDayHasPassedIsSavedNotLive() {
        vm.editDraft { it.copy(endsOn = "2026-01-31") }
        vm.saveOffer(vm.draft.value)
        assertFalse(vm.offer.value!!.running)
        assertEquals("Offer saved, but its last day has passed — Neema won't mention it", lastToast()?.message)
    }

    @Test fun endingTheOfferSendsNull() {
        vm.saveOffer(null)
        assertEquals(el("""{"campaign":null}"""), writes().single().json())
        assertNull(vm.offer.value!!.campaign)
        assertEquals("Offer ended — Neema stops mentioning it from her next reply", lastToast()?.message)
    }

    @Test fun offerRefusedForANonAdmin() {
        TeamFixtures.settings(fake, admin = false)
        vm.saveOffer(vm.draft.value)
        assertEquals("Couldn't save that offer (admin only)", lastToast()?.message)
        assertEquals("Easter Sale", vm.offer.value!!.campaign!!.name)
    }

    @Test fun whatTheClientLetsThroughTheServerAccepts() {
        // Every campaign offerProblem() passes, parse() must accept (no surprise 422s).
        listOf(
            vm.draft.value,
            vm.draft.value.copy(scope = "products", skus = listOf("CS-BLK-16"), categories = emptyList()),
            vm.draft.value.copy(scope = "all", percent = 70.0, startsOn = "2099-01-01"),
            vm.draft.value.copy(percent = 1.0),
        ).forEach { c ->
            toasts.clear()
            vm.saveOffer(c)
            assertTrue(c.toString(), lastToast()?.type == ToastType.Success)
        }
    }
}
