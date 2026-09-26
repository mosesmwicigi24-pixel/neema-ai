package ke.co.bethanyhouse.neema.leads

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.leads.Lead
import ke.co.bethanyhouse.neema.feature.leads.LeadEdit
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.leads.diffLead
import ke.co.bethanyhouse.neema.feature.leads.editLanded
import ke.co.bethanyhouse.neema.orders.ClockedMainRule
import ke.co.bethanyhouse.neema.orders.ToastLog
import ke.co.bethanyhouse.neema.orders.dropped
import ke.co.bethanyhouse.neema.orders.expiredOnce
import ke.co.bethanyhouse.neema.orders.htmlPage
import ke.co.bethanyhouse.neema.orders.offline
import ke.co.bethanyhouse.neema.orders.timeout
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fakeJwt
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * The Leads pipeline on a bad network: the board's loads, the optimistic
 * stage move and its rollback, and the detail sheet's save (with
 * `notes_base`) — whose typed text must survive every failure.
 */
class LeadsNetworkTest {
    @get:Rule val main = ClockedMainRule()
    @get:Rule val paparazzi = Paparazzi()

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private lateinit var toasts: ToastLog
    private lateinit var dash: DashboardViewModel

    private fun vm(): LeadsViewModel {
        dash = dashboard(paparazzi.context, fake)
        toasts = ToastLog(dash)
        return LeadsViewModel(dash)
    }

    @After fun tearDown() { if (::toasts.isInitialized) toasts.close() }

    private val errors get() = toasts.all.filter { it.type == ToastType.Error }.map { it.message }
    private fun LeadsViewModel.lead(id: String) = leads.value.first { it.id == id }
    private fun gets() = fake.callsTo("GET", "/admin/leads").size

    /** The server's board with lead [id] changed by [edit] (a JSON-text rewrite of its row). */
    private fun boardWith(id: String, edit: (String) -> String) =
        SalesFixtures.leadsJson(SalesFixtures.leads.map { if (it.contains("\"id\":\"$id\"")) edit(it) else it })

    // ── The board ───────────────────────────────────────────────────────────

    @Test fun offlineFirstLoadShowsWhyNotAnEmptyPipeline() {
        fake.offline("GET", "/admin/leads")
        val vm = vm()
        assertFalse(vm.loading.value)
        assertTrue(vm.leads.value.isEmpty())
        assertEquals("No connection — check your internet and try again", vm.loadError.value)
        assertTrue("the banner/error state says it, no toast", errors.isEmpty())
        SalesFixtures.install(fake)
        vm.load()
        assertEquals(8, vm.leads.value.size)
        assertNull(vm.loadError.value)
    }

    @Test fun aFailedRefreshKeepsTheBoard() {
        val vm = vm()
        fake.timeout("GET", "/admin/leads")
        vm.refresh()
        assertFalse(vm.refreshing.value)
        assertEquals(8, vm.leads.value.size)
        assertEquals("The server took too long to answer — try again", vm.loadError.value)
        fake.htmlPage("GET", "/admin/leads", 502)
        vm.refresh()
        assertEquals("The server is unavailable right now — try again shortly", vm.loadError.value)
        fake.on("GET", "/admin/leads", body = "[{\"id\":")
        vm.refresh()
        assertEquals("The server sent an answer the app couldn't read", vm.loadError.value)
        assertEquals(8, vm.leads.value.size)
    }

    @Test fun aQuietCatchUpThatFailsKeepsTheBoard() {
        val vm = vm()
        fake.offline("GET", "/admin/leads")
        vm.life.shown.value = false
        vm.life.shown.value = true
        main.advance(5_000)
        assertEquals(8, vm.leads.value.size)
    }

    // ── Stage move: optimistic, rolled back ─────────────────────────────────

    @Test fun offlineMoveRollsBackOnlyThatLead() {
        val vm = vm()
        val other = vm.lead("u1")
        fake.offline("PATCH", "/admin/leads/u3")
        val reads = gets()
        vm.moveTo(vm.lead("u3"), "contacted")
        assertEquals("new", vm.lead("u3").leadStage)
        assertEquals(other, vm.lead("u1"))
        assertEquals("Failed to update lead — no connection — check your internet and try again", errors.last())
        assertEquals("nothing reached the server: no reload", reads, gets())
        assertTrue(vm.saving.value.isEmpty())
    }

    @Test fun anHtmlErrorIsNeverShownRaw() {
        val vm = vm()
        fake.on("PATCH", "/admin/leads/u3", code = 500, body = "<html><body><h1>500 Internal Server Error</h1></body></html>")
        vm.moveTo(vm.lead("u3"), "contacted")
        assertEquals("Failed to update lead — the server hit an error — try again", errors.last())
        assertEquals("new", vm.lead("u3").leadStage)
    }

    @Test fun aTimedOutMoveThatLandedStays() {
        val vm = vm()
        fake.timeout("PATCH", "/admin/leads/u3") {
            fake.on("GET", "/admin/leads", body = boardWith("u3") { it.replace("\"lead_stage\":\"new\"", "\"lead_stage\":\"contacted\"") })
        }
        vm.moveTo(vm.lead("u3"), "contacted")
        assertEquals("contacted", vm.lead("u3").leadStage)
        assertEquals("Lead updated", toasts.all.last().message)
        assertTrue(errors.isEmpty())
    }

    @Test fun aTimedOutMoveThatDidNotLandShowsTheTruth() {
        val vm = vm()
        fake.timeout("PATCH", "/admin/leads/u3")
        vm.moveTo(vm.lead("u3"), "contacted")
        assertEquals("new", vm.lead("u3").leadStage)
        assertEquals("Lead not updated — the server took too long to answer — try again", errors.last())
    }

    @Test fun aLostAnswerWithNoWayToCheckRollsBackAndSaysSo() {
        val vm = vm()
        fake.dropped("PATCH", "/admin/leads/u3")
        fake.offline("GET", "/admin/leads")
        vm.moveTo(vm.lead("u3"), "contacted")
        assertEquals("new", vm.lead("u3").leadStage)
        assertEquals("No answer from the server — the lead may not have changed. Pull down to check.", errors.last())
    }

    @Test fun aDeletedLeadLeavesTheBoard() {
        val vm = vm()
        fake.on("PATCH", "/admin/leads/u3", code = 404, body = """{"detail":"Lead not found"}""")
        vm.moveTo(vm.lead("u3"), "contacted")
        assertTrue(vm.leads.value.none { it.id == "u3" })
        assertEquals("This lead no longer exists — someone may have deleted or merged it", errors.last())
    }

    @Test fun aSecondMoveWhileTheFirstIsInFlightIsIgnored() {
        lateinit var vm: LeadsViewModel
        fake.on("PATCH", "/admin/leads/u3") { _, _ ->
            vm.moveTo(vm.lead("u3"), "qualified")
            200 to """{"ok":true}"""
        }
        vm = vm()
        vm.moveTo(vm.lead("u3"), "contacted")
        assertEquals(1, fake.callsTo("PATCH", "/admin/leads/u3").size)
        assertEquals("contacted", vm.lead("u3").leadStage)
    }

    @Test fun aDeadSessionRollsBackQuietly() {
        val vm = vm()
        fake.on("PATCH", "/admin/leads/u3", code = 401, body = "{}")
        fake.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        vm.moveTo(vm.lead("u3"), "contacted")
        assertTrue(dash.sessionExpired.value)
        assertEquals("new", vm.lead("u3").leadStage)
        assertTrue(errors.isEmpty())
    }

    // ── The detail sheet ────────────────────────────────────────────────────

    private fun typed(vm: LeadsViewModel): Pair<Lead, LeadEdit> {
        val u1 = vm.lead("u1")
        vm.select("u1")
        return u1 to diffLead(u1, "negotiation", "vip, clergy", "Buys for the whole parish. Prefers delivery on Fridays.\n\nWants 40 stoles by Easter.")
    }

    @Test fun anOfflineSaveKeepsTheSheetOpenWithTheReason() {
        val vm = vm()
        val (u1, edit) = typed(vm)
        fake.offline("PATCH", "/admin/leads/u1")
        vm.save(u1, edit)
        assertEquals("the sheet stays open — its fields keep what was typed", "u1", vm.selectedId.value)
        assertEquals("Couldn't save — no connection — check your internet and try again", vm.sheetError.value)
        assertEquals("the board didn't pretend", u1, vm.lead("u1"))
        assertTrue(vm.saving.value.isEmpty())
        // Back online: the same edit saves and the sheet closes.
        SalesFixtures.install(fake)
        vm.save(u1, edit)
        assertNull(vm.selectedId.value)
        assertNull(vm.sheetError.value)
        assertEquals("Lead updated", toasts.all.last().message)
        assertEquals(
            """{"lead_stage":"negotiation","tags":["vip","clergy"],"notes":"Buys for the whole parish. Prefers delivery on Fridays.\n\nWants 40 stoles by Easter.","notes_base":"Buys for the whole parish. Prefers delivery on Fridays."}""",
            fake.callsTo("PATCH", "/admin/leads/u1").last().body,
        )
    }

    @Test fun aSaveThatTimedOutButLandedClosesTheSheet() {
        val vm = vm()
        val (u1, edit) = typed(vm)
        fake.timeout("PATCH", "/admin/leads/u1") {
            // The server merged: our paragraphs plus a call summary appended meanwhile.
            fake.on("GET", "/admin/leads", body = boardWith("u1") {
                it.replace("\"lead_stage\":\"proposal\"", "\"lead_stage\":\"negotiation\"")
                    .replace(Regex("\"tags\":\\[[^\\]]*\\]"), "\"tags\":[\"vip\",\"clergy\"]")
                    .replace("Prefers delivery on Fridays.\"", "Prefers delivery on Fridays.\\n\\nWants 40 stoles by Easter.\\n\\nCall: confirmed Nyeri address.\"")
            })
        }
        vm.save(u1, edit)
        assertNull(vm.selectedId.value)
        assertEquals("Lead updated", toasts.all.last().message)
        assertTrue(vm.lead("u1").notes!!.endsWith("Call: confirmed Nyeri address."))
    }

    @Test fun aSaveThatTimedOutAndDidNotLandStaysOpen() {
        val vm = vm()
        val (u1, edit) = typed(vm)
        fake.timeout("PATCH", "/admin/leads/u1")
        vm.save(u1, edit)
        assertEquals("u1", vm.selectedId.value)
        assertEquals("Not saved — the server took too long to answer — try again", vm.sheetError.value)
    }

    @Test fun aSaveWithNoWayToCheckSaysSaveAgain() {
        val vm = vm()
        val (u1, edit) = typed(vm)
        fake.dropped("PATCH", "/admin/leads/u1")
        fake.offline("GET", "/admin/leads")
        vm.save(u1, edit)
        assertEquals("u1", vm.selectedId.value)
        assertEquals("No answer from the server — your changes may not have saved. Save again to be sure.", vm.sheetError.value)
    }

    @Test fun aSaveForADeletedLeadClosesTheSheetAndSaysSo() {
        val vm = vm()
        val (u1, edit) = typed(vm)
        fake.on("PATCH", "/admin/leads/u1", code = 404, body = """{"detail":"Lead not found"}""")
        vm.save(u1, edit)
        assertNull(vm.selectedId.value)
        assertTrue(vm.leads.value.none { it.id == "u1" })
        assertEquals("This lead no longer exists — someone may have deleted or merged it", errors.last())
    }

    @Test fun aSaveWhenTheSessionDiedKeepsTheSheetForAfterSignIn() {
        val vm = vm()
        val (u1, edit) = typed(vm)
        fake.on("PATCH", "/admin/leads/u1", code = 401, body = "{}")
        fake.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        vm.save(u1, edit)
        assertTrue(dash.sessionExpired.value)
        assertEquals("u1", vm.selectedId.value)
        assertEquals("Your session expired — sign in again, then save.", vm.sheetError.value)
    }

    @Test fun aSaveRescuedByATokenRefreshJustSaves() {
        val vm = vm()
        val (u1, edit) = typed(vm)
        fake.expiredOnce("PATCH", "/admin/leads/u1") { 200 to """{"ok":true}""" }
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ -> 200 to Fixtures.tokenResponse(access = fakeJwt() + "r") }
        vm.save(u1, edit)
        assertNull(vm.selectedId.value)
        assertEquals("Lead updated", toasts.all.last().message)
        assertFalse(dash.sessionExpired.value)
    }

    @Test fun aSecondSaveTapWhileSavingSendsNothing() {
        lateinit var vm: LeadsViewModel
        lateinit var u1: Lead
        lateinit var edit: LeadEdit
        fake.on("PATCH", "/admin/leads/u1") { _, _ -> vm.save(u1, edit); vm.moveTo(u1, "won"); 200 to """{"ok":true}""" }
        vm = vm()
        typed(vm).let { u1 = it.first; edit = it.second }
        vm.save(u1, edit)
        assertEquals(1, fake.callsTo("PATCH", "/admin/leads/u1").size)
    }

    @Test fun anUntouchedSheetClosesWithoutARequest() {
        val vm = vm()
        vm.select("u2")
        vm.save(vm.lead("u2"), LeadEdit())
        assertNull(vm.selectedId.value)
        assertTrue(fake.callsTo("PATCH", "/admin/leads/u2").isEmpty())
    }

    // ── editLanded ──────────────────────────────────────────────────────────

    @Test fun editLandedReadsTheMergedNotes() {
        val base = Lead(id = "u", leadStage = "new", notes = "A\n\nB", tags = listOf("x"))
        val edit = LeadEdit(stage = "qualified", notes = "A\n\nC", notesBase = "A\n\nB")
        assertTrue(editLanded(edit, base.copy(leadStage = "Qualified", notes = "A\n\nC\n\nD (appended)")))
        assertFalse("B was deleted on purpose", editLanded(edit, base.copy(leadStage = "qualified", notes = "A\n\nB\n\nC")))
        assertFalse(editLanded(edit, base.copy(notes = "A\n\nC")))
        assertFalse(editLanded(LeadEdit(tags = listOf("y")), base))
        assertTrue(editLanded(LeadEdit(tags = listOf("x")), base))
    }
}
