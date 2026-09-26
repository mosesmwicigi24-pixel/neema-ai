package ke.co.bethanyhouse.neema.settings

import ke.co.bethanyhouse.neema.core.util.AppClock

import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Campaign
import ke.co.bethanyhouse.neema.feature.settings.PIPELINE_LABEL_MAX
import ke.co.bethanyhouse.neema.feature.settings.SettingsViewModel
import ke.co.bethanyhouse.neema.feature.settings.isoDateToUtcMillis
import ke.co.bethanyhouse.neema.feature.settings.offerIsValid
import ke.co.bethanyhouse.neema.feature.settings.utcMillisToIsoDate
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

/** SettingsView.tsx's live cards (+ the pipeline stage list): endpoints, bodies, validation, failures. */
class SettingsViewModelTest : AreaTest() {
    /** crm.py's settings routes as the server answers them (max_chars 600, max_percent 70). */
    override fun install(f: FakeNeema) = TeamFixtures.settings(f)
    private val vm by lazy { SettingsViewModel(dash).also { fake.calls.clear() } }

    @Test fun loadsEveryCard() {
        val v = SettingsViewModel(dash)
        listOf("directives", "translation", "offer", "pipeline-stages").forEach {
            assertTrue(it, fake.called("GET", "/admin/settings/$it"))
        }
        assertEquals("Always offer free delivery within Nairobi on orders above KES 10,000.", v.directives.value)
        assertEquals(600, v.maxChars.value)
        assertTrue(v.directivesLoaded.value)
        assertEquals(true, v.translation.value?.enabled)
        assertEquals("Easter Sale", v.offer.value?.campaign?.name)
        assertEquals("Easter Sale", v.draft.value.name)
        assertEquals(listOf("measuring"), v.stages.value)
    }

    @Test fun oneCardFailingLeavesTheOthers() {
        fail("GET", "/admin/settings/directives", 500, "x")
        fail("GET", "/admin/settings/translation", 500, "x")
        val v = SettingsViewModel(dash)
        assertTrue("the box still unlocks, like the web", v.directivesLoaded.value)
        assertNull("translation stays loading", v.translation.value)
        assertEquals("Easter Sale", v.offer.value?.campaign?.name)
    }

    // ── Standing orders ──────────────────────────────────────────────────────

    @Test fun directivesAreCappedAtMaxChars() {
        vm.setDirectives("x".repeat(2500))
        assertEquals(600, vm.directives.value.length)
    }

    @Test fun saveDirectivesPutsTheText() {
        vm.setDirectives("Push copes this week.")
        vm.saveDirectives()
        val w = writes().single()
        assertEquals("PUT" to "/admin/settings/directives", w.method to w.path)
        assertEquals(el("""{"directives":"Push copes this week."}"""), w.json())
        assertEquals("Standing orders saved — Neema follows them within ~5 minutes", lastToast()?.message)
    }

    @Test fun saveDirectivesShowsWhatTheServerKept() {
        fake.on("PUT", "/admin/settings/directives", body = """{"ok":true,"directives":"Trimmed by server"}""")
        vm.setDirectives("  Trimmed by server  ")
        vm.saveDirectives()
        assertEquals("Trimmed by server", vm.directives.value)
    }

    @Test fun saveDirectivesFailure() {
        fail("PUT", "/admin/settings/directives")
        vm.saveDirectives()
        assertEquals("Couldn't save (admin only)", lastToast()?.message)
        assertFalse(vm.savingDirectives.value)
    }

    // ── Translation (optimistic) ─────────────────────────────────────────────

    @Test fun translationFlipsBeforeTheServerAnswers() {
        var seenDuringRequest: Boolean? = null
        fake.on("PUT", "/admin/settings/translation") { _, _ ->
            seenDuringRequest = vm.translation.value?.enabled
            200 to """{"ok":true,"enabled":false}"""
        }
        vm.toggleTranslation()
        assertEquals("switch moved before the reply", false, seenDuringRequest)
        assertEquals(el("""{"enabled":false}"""), writes().single().json())
        assertEquals(false, vm.translation.value?.enabled)
        assertEquals("Translation off — no new translations will be bought. Ones already saved stay visible.", lastToast()?.message)
    }

    @Test fun translationRevertsWhenTheSaveFails() {
        fail("PUT", "/admin/settings/translation")
        vm.toggleTranslation()
        assertEquals(true, vm.translation.value?.enabled)
        assertEquals("Couldn't change that (admin only)", lastToast()?.message)
        assertEquals(ToastType.Error, lastToast()?.type)
    }

    @Test fun translationOnToast() {
        fake.on("GET", "/admin/settings/translation", body = """{"enabled":false,"default":false,"spend_30d_usd":0,"calls_30d":0}""")
        vm.toggleTranslation()
        assertEquals(el("""{"enabled":true}"""), writes().single().json())
        assertEquals("Translation on — foreign messages get an English line from the next thread you open", lastToast()?.message)
    }

    @Test fun translationDoesNothingBeforeItLoads() {
        fail("GET", "/admin/settings/translation", 500, "x")
        vm.toggleTranslation()
        assertTrue(writes().isEmpty())
    }

    // ── Offer ────────────────────────────────────────────────────────────────

    @Test fun startOfferFromBlank() {
        TeamFixtures.noOffer(fake)
        fake.on("PUT", "/admin/settings/offer", body = """{"ok":true,"campaign":{"name":"Harvest Offer","percent":20,"scope":"all",
            "categories":[],"skus":[],"starts_on":null,"ends_on":"2026-10-25"},"running":true,"says":"Harvest Offer — 20% off everything"}""")
        // A new offer ends a month from today.
        assertEquals(AppClock.today().plusMonths(1).toString(), vm.draft.value.endsOn)
        assertEquals(10.0, vm.draft.value.percent, 0.0)
        vm.editDraft { it.copy(name = "Harvest Offer", percent = 20.0, endsOn = "2026-10-25") }
        vm.saveOffer(vm.draft.value)
        val w = writes().single()
        assertEquals("PUT" to "/admin/settings/offer", w.method to w.path)
        val c = w.json()["campaign"]!!.jsonObject
        assertEquals(el(""""Harvest Offer""""), c["name"])
        assertEquals(20.0, c["percent"].toString().toDouble(), 0.0)
        assertEquals(el(""""all""""), c["scope"])
        assertEquals(el(""""2026-10-25""""), c["ends_on"])
        assertTrue(vm.offer.value!!.running)
        assertEquals("Offer live — Neema will say: Harvest Offer — 20% off everything", lastToast()?.message)
    }

    @Test fun updateOfferSendsTheEditedCampaign() {
        vm.editDraft { it.copy(percent = 25.0, scope = "products", skus = listOf("CS-BLK-16"), startsOn = "2026-10-01") }
        vm.saveOffer(vm.draft.value)
        val c = writes().single().json()["campaign"]!!.jsonObject
        assertEquals(el(""""products""""), c["scope"])
        assertEquals(el("""["CS-BLK-16"]"""), c["skus"])
        assertEquals(el(""""2026-10-01""""), c["starts_on"])
        assertEquals(el(""""2099-04-30""""), c["ends_on"])
    }

    @Test fun endOfferSendsNull() {
        fake.on("PUT", "/admin/settings/offer", body = """{"ok":true,"campaign":null,"running":false,"says":""}""")
        vm.saveOffer(null)
        val w = writes().single()
        assertEquals(JsonNull, w.json()["campaign"])
        assertNull(vm.offer.value!!.campaign)
        assertEquals("", vm.draft.value.name)
        assertEquals("Offer ended — Neema stops mentioning it from her next reply", lastToast()?.message)
    }

    @Test fun offerTheServerWouldRefuseIsNotSent() {
        val pct = "The discount must be a whole number from 1 to 70%"
        vm.editDraft { it.copy(percent = 0.0) }
        vm.saveOffer(vm.draft.value)
        assertEquals(pct, lastToast()?.message)
        vm.editDraft { it.copy(percent = 71.0) } // promotions.MAX_PERCENT is 70
        vm.saveOffer(vm.draft.value)
        assertEquals(pct, lastToast()?.message)
        vm.editDraft { it.copy(percent = 12.5) } // the server would keep int(12.5) = 12
        vm.saveOffer(vm.draft.value)
        assertEquals(pct, lastToast()?.message)
        vm.editDraft { it.copy(percent = 70.0, name = " ") }
        vm.saveOffer(vm.draft.value)
        assertEquals("Give the offer a name", lastToast()?.message)
        vm.editDraft { it.copy(name = "Easter", endsOn = "") }
        vm.saveOffer(vm.draft.value)
        assertEquals("Pick the offer's last day", lastToast()?.message)
        vm.editDraft { it.copy(endsOn = "30/04/2099") } // not YYYY-MM-DD: date.fromisoformat refuses it
        vm.saveOffer(vm.draft.value)
        assertEquals("Pick the offer's last day", lastToast()?.message)
        vm.editDraft { it.copy(endsOn = "2099-04-30", scope = "category", categories = emptyList()) }
        vm.saveOffer(vm.draft.value)
        assertEquals("Pick at least one category for the offer", lastToast()?.message)
        vm.editDraft { it.copy(scope = "products", skus = listOf(" ")) }
        vm.saveOffer(vm.draft.value)
        assertEquals("Pick at least one product for the offer", lastToast()?.message)
        assertTrue(writes().isEmpty())
        assertTrue(toasts.all { it.type == ToastType.Error })
    }

    @Test fun offerRangeBoundaries() {
        val c = Campaign(name = "X", percent = 1.0, endsOn = "2026-12-01")
        assertTrue(offerIsValid(c, 30))
        assertTrue(offerIsValid(c.copy(percent = 30.0), 30))
        assertFalse(offerIsValid(c.copy(percent = 0.5), 30))
        assertFalse(offerIsValid(c.copy(percent = 30.5), 30))
        assertFalse("a whole number only", offerIsValid(c.copy(percent = 10.5), 30))
    }

    @Test fun offerServerRefusal() {
        fail("PUT", "/admin/settings/offer", 422, TeamFixtures.OFFER_422)
        vm.saveOffer(vm.draft.value)
        assertEquals("Couldn't save that offer — ${TeamFixtures.OFFER_422}", lastToast()?.message)
        assertFalse(vm.savingOffer.value)
        fail("PUT", "/admin/settings/offer", 403, "Admin only")
        vm.saveOffer(vm.draft.value)
        assertEquals("Couldn't save that offer (admin only)", lastToast()?.message)
        fake.on("PUT", "/admin/settings/offer", code = 500, body = "Internal Server Error")
        vm.saveOffer(vm.draft.value)
        assertEquals("Couldn't save that offer (admin only, and it needs a name, a percentage and an end date)", lastToast()?.message)
        assertEquals("Easter Sale", vm.offer.value?.campaign?.name)
    }

    @Test fun datePickerRoundTripsInUtc() {
        val ms = isoDateToUtcMillis("2026-04-30")!!
        assertEquals("2026-04-30", utcMillisToIsoDate(ms))
        assertNull(isoDateToUtcMillis(null))
        assertNull(isoDateToUtcMillis("not a date"))
    }

    // ── Pipeline stages ──────────────────────────────────────────────────────

    @Test fun addStagePutsTheWholeList() {
        fake.on("PUT", "/admin/settings/pipeline-stages", body = """{"ok":true,"stages":["measuring","Sampling"]}""")
        assertTrue(vm.addStage("  Sampling "))
        val w = writes().single()
        assertEquals("PUT" to "/admin/settings/pipeline-stages", w.method to w.path)
        assertEquals(el("""{"stages":["measuring","Sampling"]}"""), w.json())
        assertEquals(listOf("measuring", "Sampling"), vm.stages.value)
    }

    @Test fun stageLabelsAreCappedAt18() {
        vm.addStage("A very long stage label indeed")
        val sent = writes().single().json()["stages"].toString()
        assertTrue(sent, sent.contains("\"A very long stage\""))
        assertEquals(18, PIPELINE_LABEL_MAX)
    }

    @Test fun duplicateAndBuiltInStagesAreRefused() {
        assertFalse(vm.addStage("MEASURING"))
        assertEquals("“MEASURING” is already a stage", lastToast()?.message)
        assertFalse(vm.addStage("Won"))
        assertEquals("“Won” is already a built-in stage", lastToast()?.message)
        assertFalse(vm.addStage("   "))
        assertTrue(writes().isEmpty())
    }

    @Test fun atMostFourStages() {
        fake.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["a","b","c","d"]}""")
        assertFalse(vm.addStage("e"))
        assertEquals("At most 4 custom stages", lastToast()?.message)
        assertTrue(writes().isEmpty())
    }

    @Test fun removeStage() {
        fake.on("PUT", "/admin/settings/pipeline-stages", body = """{"ok":true,"stages":[]}""")
        vm.removeStage("measuring")
        assertEquals(el("""{"stages":[]}"""), writes().single().json())
        assertEquals(emptyList<String>(), vm.stages.value)
    }

    @Test fun stageErrors() {
        fail("PUT", "/admin/settings/pipeline-stages", 403)
        vm.addStage("Sampling")
        assertEquals("Only an admin can change pipeline stages.", lastToast()?.message)
        fail("PUT", "/admin/settings/pipeline-stages", 422, "At most 4 custom stages")
        vm.addStage("Sampling")
        assertEquals("At most 4 custom stages", lastToast()?.message)
        fail("PUT", "/admin/settings/pipeline-stages", 500, "x")
        vm.addStage("Sampling")
        assertEquals("Couldn't save pipeline stages.", lastToast()?.message)
        assertEquals(listOf("measuring"), vm.stages.value)
    }

    // ── Local-only cards (no API on the web either) ───────────────────────────

    @Test fun localCardsNeverCallTheApi() {
        vm.toggleIntegration("slack")
        assertEquals("Slack Notifications connected", lastToast()?.message)
        assertTrue(vm.integrations.value.first { it.key == "slack" }.connected)
        vm.toggleIntegration("whatsapp")
        assertEquals("WhatsApp Business API disconnected", lastToast()?.message)
        vm.setConfig("slack", "slack_channel", "#alerts")
        vm.saveIntegConfig("slack")
        assertEquals("Slack Notifications settings saved", lastToast()?.message)
        vm.dangerAction()
        assertEquals("Requires confirmation — coming soon", lastToast()?.message)
        assertEquals(ToastType.Warning, lastToast()?.type)
        assertTrue(writes().isEmpty())
    }
}
