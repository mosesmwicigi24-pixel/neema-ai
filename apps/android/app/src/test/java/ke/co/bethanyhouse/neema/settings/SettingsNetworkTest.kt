package ke.co.bethanyhouse.neema.settings

import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.agents.UNCERTAIN_SAVE
import ke.co.bethanyhouse.neema.feature.reports.BUSY_TEXT
import ke.co.bethanyhouse.neema.feature.reports.DOWN_TEXT
import ke.co.bethanyhouse.neema.feature.reports.EXPIRED_TEXT
import ke.co.bethanyhouse.neema.feature.reports.OFFLINE_TEXT
import ke.co.bethanyhouse.neema.feature.reports.TIMEOUT_TEXT
import ke.co.bethanyhouse.neema.feature.settings.SettingsViewModel
import ke.co.bethanyhouse.neema.team.AreaTest
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.fixtures.NetStressFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.TeamFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Standing orders, translation, the offer and pipeline stages on a bad phone network. */
class SettingsNetworkTest : AreaTest() {
    override fun install(f: FakeNeema) = TeamFixtures.settings(f)
    private val vm by lazy { SettingsViewModel(dash).also { fake.calls.clear(); toasts.clear() } }
    private fun puts(path: String) = fake.calls.count { it.method == "PUT" && it.path == "/admin/settings/$path" }

    // ── Loads ────────────────────────────────────────────────────────────────

    @Test fun everyCardOffline_saysWhy_noneLoadsForever_andEachRetriesAlone() {
        listOf("directives", "translation", "offer", "pipeline-stages").forEach { NetStressFixtures.offline(fake, "GET", "/admin/settings/$it") }
        val v = SettingsViewModel(dash)
        assertEquals(setOf("directives", "translation", "offer", "stages"), v.loadErrors.value.keys)
        assertTrue(v.loadErrors.value.values.all { it == OFFLINE_TEXT })
        assertFalse("standing orders stay locked: an empty box must not be saved over the real ones", v.directivesLoaded.value)
        assertNull("no stage list to add to", v.stages.value)
        // Adding a stage to a list that never arrived would replace the real one: refused.
        assertFalse(v.addStage("Sampling"))
        v.saveDirectives()
        assertEquals(0, fake.calls.count { it.method == "PUT" })

        // Back online: each card's Retry reads only that card.
        TeamFixtures.settings(fake)
        fake.calls.clear()
        v.retry("stages")
        assertEquals(listOf("/admin/settings/pipeline-stages"), fake.calls.map { it.path })
        assertEquals(listOf("measuring"), v.stages.value)
        v.retry("directives")
        assertTrue(v.directivesLoaded.value)
        v.retry("translation"); v.retry("offer")
        assertTrue(v.loadErrors.value.isEmpty())
    }

    @Test fun garbledBodies_noCrash_cardSaysWhy() {
        fake.on("GET", "/admin/settings/offer", body = "<html>captive portal</html>")
        fake.on("GET", "/admin/settings/pipeline-stages", body = """{"stages": 7}""")
        val v = SettingsViewModel(dash)
        assertEquals("The server sent an answer the app couldn't read — try again.", v.loadErrors.value["offer"])
        assertTrue(v.loadErrors.value.containsKey("stages"))
        assertEquals("the other cards load", "Always offer free delivery within Nairobi on orders above KES 10,000.", v.directives.value)
    }

    @Test fun pullToRefreshFailing_keepsEveryCardAsItWas() {
        vm
        listOf("directives", "translation", "offer", "pipeline-stages").forEach { NetStressFixtures.timeout(fake, "GET", "/admin/settings/$it") }
        vm.refresh()
        assertTrue(vm.directivesLoaded.value)
        assertEquals(listOf("measuring"), vm.stages.value)
        assertEquals("Easter Sale", vm.offer.value?.campaign?.name)
        assertTrue("no error over a card already showing", vm.loadErrors.value.isEmpty())
        assertFalse(vm.refreshing.value)
    }

    // ── Standing orders ──────────────────────────────────────────────────────

    @Test fun directivesTimeout_butLanded_countsAsSaved() {
        NetStressFixtures.landThenTimeout(fake, "PUT", "/admin/settings/directives") {
            fake.on("GET", "/admin/settings/directives", body = """{"directives":"Push copes this week.","max_chars":600}""")
        }
        vm.setDirectives("Push copes this week.")
        vm.saveDirectives()
        assertEquals("Standing orders saved — Neema follows them within ~5 minutes", lastToast()?.message)
    }

    @Test fun directivesTimeout_notLanded_keepsTheText() {
        NetStressFixtures.timeout(fake, "PUT", "/admin/settings/directives")
        vm.setDirectives("Push copes this week.")
        vm.saveDirectives()
        assertEquals(UNCERTAIN_SAVE, lastToast()?.message)
        assertEquals("Push copes this week.", vm.directives.value)
        assertFalse(vm.savingDirectives.value)
    }

    @Test fun directivesStatuses() {
        vm.setDirectives("Push copes this week.")
        for ((code, body, want) in listOf(
            Triple(403, """{"detail":"Admin only"}""", "Couldn't save (admin only)"),
            Triple(429, "", BUSY_TEXT),
            Triple(500, "Internal Server Error", "Couldn't save the standing orders — try again."),
            Triple(502, NetStressFixtures.HTML_502, DOWN_TEXT),
        )) {
            fake.on("PUT", "/admin/settings/directives", code = code, body = body)
            vm.saveDirectives()
            assertEquals("$code", want, lastToast()?.message)
            assertEquals("Push copes this week.", vm.directives.value)
        }
    }

    @Test fun directivesDoubleTap_sendsOnce() {
        fake.on("PUT", "/admin/settings/directives") { _, _ ->
            vm.saveDirectives()
            200 to """{"ok":true,"directives":"x"}"""
        }
        vm.saveDirectives()
        assertEquals(1, puts("directives"))
    }

    @Test fun directivesWithAnExpiredSession_keepTheText() {
        NetStressFixtures.refreshRefused(fake)
        fake.on("PUT", "/admin/settings/directives", code = 401, body = """{"detail":"Could not validate credentials"}""")
        vm.setDirectives("Push copes this week.")
        vm.saveDirectives()
        assertTrue(dash.sessionExpired.value)
        assertEquals(EXPIRED_TEXT, lastToast()?.message)
        assertEquals("Push copes this week.", vm.directives.value)
    }

    // ── Translation ──────────────────────────────────────────────────────────

    @Test fun translationTimeout_showsWhatTheServerHas() {
        // It switched off on the server; only the answer was lost.
        NetStressFixtures.landThenTimeout(fake, "PUT", "/admin/settings/translation") {
            fake.on("GET", "/admin/settings/translation", body = """{"enabled":false,"default":false,"spend_30d_usd":0,"calls_30d":0}""")
        }
        vm.toggleTranslation()
        assertEquals(false, vm.translation.value?.enabled)
        assertTrue("no failure claimed for a change that happened", toasts.none { it.type == ToastType.Error })
    }

    @Test fun translationTimeout_notLanded_switchGoesBack_andSaysSo() {
        NetStressFixtures.timeout(fake, "PUT", "/admin/settings/translation")
        vm.toggleTranslation()
        assertEquals(true, vm.translation.value?.enabled)
        assertEquals("Couldn't reach the server — translation is still on", lastToast()?.message)
    }

    @Test fun translationOffline_switchGoesBack() {
        NetStressFixtures.offline(fake, "PUT", "/admin/settings/translation")
        vm.toggleTranslation()
        assertEquals(true, vm.translation.value?.enabled)
        assertEquals(OFFLINE_TEXT, lastToast()?.message)
    }

    @Test fun translationDoubleTap_sendsOnce() {
        fake.on("PUT", "/admin/settings/translation") { _, _ ->
            vm.toggleTranslation()
            200 to """{"ok":true,"enabled":false}"""
        }
        vm.toggleTranslation()
        assertEquals(1, puts("translation"))
        assertEquals(false, vm.translation.value?.enabled)
    }

    // ── Offer ────────────────────────────────────────────────────────────────

    @Test fun offerTimeout_butLanded_countsAsSaved() {
        NetStressFixtures.landThenTimeout(fake, "PUT", "/admin/settings/offer") {
            fake.on("GET", "/admin/settings/offer", body = """{"campaign":{"name":"Harvest","percent":15,"scope":"all","categories":[],"skus":[],"starts_on":null,"ends_on":"2099-01-31"},"running":true,"says":"Harvest — 15% off everything, until 31 January 2099","max_percent":70}""")
        }
        vm.editDraft { it.copy(name = "Harvest", percent = 15.0, scope = "all", categories = emptyList(), endsOn = "2099-01-31") }
        vm.saveOffer(vm.draft.value)
        assertEquals("Offer live — Neema will say: Harvest — 15% off everything, until 31 January 2099", lastToast()?.message)
        assertEquals("Harvest", vm.offer.value?.campaign?.name)
    }

    @Test fun offerTimeout_notLanded_keepsTheDraft() {
        NetStressFixtures.timeout(fake, "PUT", "/admin/settings/offer")
        vm.editDraft { it.copy(name = "Harvest", percent = 15.0) }
        vm.saveOffer(vm.draft.value)
        assertEquals(UNCERTAIN_SAVE, lastToast()?.message)
        assertEquals("Harvest", vm.draft.value.name)
        assertEquals("Easter Sale", vm.offer.value?.campaign?.name)
    }

    @Test fun endingTheOfferTimesOut_butItEnded_countsAsEnded() {
        NetStressFixtures.landThenTimeout(fake, "PUT", "/admin/settings/offer") { TeamFixtures.noOffer(fake) }
        vm.saveOffer(null)
        assertEquals("Offer ended — Neema stops mentioning it from her next reply", lastToast()?.message)
        assertNull(vm.offer.value?.campaign)
    }

    @Test fun offerStatuses() {
        vm.editDraft { it.copy(name = "Harvest") }
        for ((code, body, want) in listOf(
            Triple(403, """{"detail":"Admin only"}""", "Couldn't save that offer (admin only)"),
            Triple(422, """{"detail":"${TeamFixtures.OFFER_422}"}""", "Couldn't save that offer — ${TeamFixtures.OFFER_422}"),
            Triple(429, "", BUSY_TEXT),
            Triple(503, NetStressFixtures.HTML_502, DOWN_TEXT),
        )) {
            fake.on("PUT", "/admin/settings/offer", code = code, body = body)
            vm.saveOffer(vm.draft.value)
            assertEquals("$code", want, lastToast()?.message)
            assertEquals("Harvest", vm.draft.value.name)
        }
    }

    @Test fun offerDoubleTap_sendsOnce() {
        fake.on("PUT", "/admin/settings/offer") { _, _ ->
            vm.saveOffer(null)
            200 to """{"ok":true,"campaign":null,"running":false,"says":""}"""
        }
        vm.saveOffer(null)
        assertEquals(1, puts("offer"))
    }

    // ── Pipeline stages ──────────────────────────────────────────────────────

    @Test fun addStageFailing_keepsTheTypedLabel() {
        NetStressFixtures.offline(fake, "PUT", "/admin/settings/pipeline-stages")
        var cleared = false
        assertTrue(vm.addStage("Sampling") { cleared = true })
        assertFalse("the label stays in the box", cleared)
        assertEquals(OFFLINE_TEXT, lastToast()?.message)
        assertEquals(listOf("measuring"), vm.stages.value)
        // Online again: the same label, and now it clears.
        TeamFixtures.settings(fake)
        vm.addStage("Sampling") { cleared = true }
        assertTrue(cleared)
        assertEquals(listOf("measuring", "Sampling"), vm.stages.value)
    }

    @Test fun addStageTimeout_butLanded_countsAsAdded() {
        NetStressFixtures.landThenTimeout(fake, "PUT", "/admin/settings/pipeline-stages") {
            fake.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":["measuring","Sampling"]}""")
        }
        var cleared = false
        vm.addStage("Sampling") { cleared = true }
        assertTrue(cleared)
        assertEquals(listOf("measuring", "Sampling"), vm.stages.value)
        assertTrue(toasts.none { it.type == ToastType.Error })
    }

    @Test fun addStageTimeout_notLanded_saysSo_andShowsTheServersList() {
        NetStressFixtures.timeout(fake, "PUT", "/admin/settings/pipeline-stages")
        var cleared = false
        vm.addStage("Sampling") { cleared = true }
        assertFalse(cleared)
        assertEquals(UNCERTAIN_SAVE, lastToast()?.message)
        assertEquals(listOf("measuring"), vm.stages.value)
    }

    @Test fun stageDoubleTap_sendsOnce() {
        fake.on("PUT", "/admin/settings/pipeline-stages") { _, _ ->
            assertFalse("a second add while one is on the wire is refused", vm.addStage("Fitting"))
            200 to """{"ok":true,"stages":["measuring","Sampling"]}"""
        }
        vm.addStage("Sampling")
        assertEquals(1, puts("pipeline-stages"))
    }

    @Test fun stageTimeoutMessageIsNotTheGenericOne() {
        NetStressFixtures.timeout(fake, "GET", "/admin/settings/pipeline-stages")
        val v = SettingsViewModel(dash)
        assertEquals(TIMEOUT_TEXT, v.loadErrors.value["stages"])
    }
}
