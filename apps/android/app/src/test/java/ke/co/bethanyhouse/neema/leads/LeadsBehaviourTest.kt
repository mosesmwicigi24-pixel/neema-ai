package ke.co.bethanyhouse.neema.leads

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.leads.BASE_STAGES
import ke.co.bethanyhouse.neema.feature.leads.Lead
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.leads.buildStages
import ke.co.bethanyhouse.neema.feature.leads.diffLead
import ke.co.bethanyhouse.neema.feature.leads.filterLeads
import ke.co.bethanyhouse.neema.feature.leads.parseTags
import ke.co.bethanyhouse.neema.orders.MainDispatcherRule
import ke.co.bethanyhouse.neema.orders.ToastLog
import ke.co.bethanyhouse.neema.orders.bodies
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import kotlinx.serialization.json.Json
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** LeadsView's behaviour: stage moves, detail saves, search / filter, custom stages. */
class LeadsBehaviourTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi()

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private lateinit var toasts: ToastLog

    private fun vm(): LeadsViewModel {
        val dash = dashboard(paparazzi.context, fake)
        toasts = ToastLog(dash)
        return LeadsViewModel(dash)
    }

    @After fun tearDown() { if (::toasts.isInitialized) toasts.close() }

    private fun json(s: String) = Json.parseToJsonElement(s)
    private fun lead(id: String = "u1", stage: String = "proposal", notes: String? = "Buys for the parish.", tags: List<String> = listOf("vip")) =
        Lead(id = id, waId = "254712345678", name = "Fr. Peter Kamau", leadStage = stage, notes = notes, tags = tags)

    @Test fun loadsLeadsAndTheOperatorsStages() {
        val vm = vm()
        assertEquals(8, vm.leads.value.size)
        assertEquals(false, vm.loading.value)
        assertEquals(
            listOf("new", "contacted", "qualified", "proposal", "negotiation", "measuring", "won", "lost"),
            vm.stages.value.map { it.id },
        )
    }

    @Test fun customStagesSitBetweenNegotiatingAndWon() {
        assertEquals(BASE_STAGES, buildStages(emptyList()))
        assertEquals(
            listOf("new", "contacted", "qualified", "proposal", "negotiation", "measuring", "fitting", "won", "lost"),
            buildStages(listOf("measuring", " ", "fitting")).map { it.id },
        )
    }

    @Test fun stageMoveSendsOnlyTheStageAndMovesTheCardAtOnce() {
        val vm = vm()
        val l = vm.leads.value.first { it.id == "u3" }
        vm.moveTo(l, "contacted")
        assertEquals(listOf(json("""{"lead_stage":"contacted"}""")), fake.bodies("PATCH", "/admin/leads/u3"))
        assertEquals("contacted", vm.leads.value.first { it.id == "u3" }.leadStage)
        assertEquals("Lead updated", toasts.all.last().message)
    }

    @Test fun failedSaveToastsAndReloadsTheBoard() {
        fake.on("PATCH", "/admin/leads/.*", code = 404, body = """{"detail":"Lead not found"}""")
        val vm = vm()
        val gets = fake.calls.count { it.method == "GET" && it.path == "/admin/leads" }
        vm.moveTo(vm.leads.value.first { it.id == "u3" }, "contacted")
        assertEquals(ToastType.Error, toasts.all.last().type)
        assertTrue(toasts.all.last().message.startsWith("Failed to update lead"))
        assertEquals(gets + 1, fake.calls.count { it.method == "GET" && it.path == "/admin/leads" })
        // The reload rolled the optimistic move back.
        assertEquals("new", vm.leads.value.first { it.id == "u3" }.leadStage)
    }

    @Test fun untouchedSheetSendsNothing() {
        val e = diffLead(lead(), "proposal", "vip", "Buys for the parish.")
        assertTrue(e.isEmpty)
        // Case and spacing of the stage / tags don't count as changes.
        assertTrue(diffLead(lead(stage = "Proposal"), "proposal", " vip , ", "Buys for the parish.").isEmpty)
    }

    @Test fun sheetSendsOnlyChangedFields() {
        val stageOnly = diffLead(lead(), "won", "vip", "Buys for the parish.")
        assertEquals("won", stageOnly.stage); assertNull(stageOnly.tags); assertNull(stageOnly.notes)

        val tagsOnly = diffLead(lead(), "proposal", "vip, clergy,,  nyeri ", "Buys for the parish.")
        assertNull(tagsOnly.stage); assertEquals(listOf("vip", "clergy", "nyeri"), tagsOnly.tags)

        val notes = diffLead(lead(), "proposal", "vip", "Buys for the parish. Wants Friday delivery.")
        assertEquals("Buys for the parish. Wants Friday delivery.", notes.notes)
        assertEquals("Buys for the parish.", notes.notesBase)

        val cleared = diffLead(lead(), "proposal", "", "")
        assertEquals(emptyList<String>(), cleared.tags)
        assertEquals("", cleared.notes)
    }

    @Test fun notesSaveCarriesTheBaseItStartedFrom() {
        val vm = vm()
        val u1 = vm.leads.value.first { it.id == "u1" }
        val edit = diffLead(u1, "proposal", u1.tags.joinToString(", "), "New note")
        vm.update(u1, edit.stage, edit.tags, edit.notes, edit.notesBase)
        assertEquals(
            listOf(json("""{"notes":"New note","notes_base":"Buys for the whole parish. Prefers delivery on Fridays."}""")),
            fake.bodies("PATCH", "/admin/leads/u1"),
        )
        assertEquals("New note", vm.leads.value.first { it.id == "u1" }.notes)
    }

    @Test fun firstNoteHasAnEmptyBase() {
        val vm = vm()
        val u2 = vm.leads.value.first { it.id == "u2" }
        val edit = diffLead(u2, "qualified", "", "Asked for the purple cassock")
        vm.update(u2, edit.stage, edit.tags, edit.notes, edit.notesBase)
        assertEquals(listOf(json("""{"notes":"Asked for the purple cassock","notes_base":""}""")), fake.bodies("PATCH", "/admin/leads/u2"))
    }

    @Test fun stageAndTagsTogether() {
        val vm = vm()
        val u4 = vm.leads.value.first { it.id == "u4" }
        val edit = diffLead(u4, "qualified", "convent, bulk", "")
        vm.update(u4, edit.stage, edit.tags, edit.notes, edit.notesBase)
        assertEquals(listOf(json("""{"lead_stage":"qualified","tags":["convent","bulk"]}""")), fake.bodies("PATCH", "/admin/leads/u4"))
    }

    @Test fun parseTagsLikeTheWeb() = assertEquals(listOf("a", "b c", "d"), parseTags(" a,b c ,, d,"))

    @Test fun searchAndFilter() {
        val all = vm().leads.value
        assertEquals(listOf("u1"), filterLeads(all, "proposal", "").map { it.id })
        assertEquals(listOf("u2"), filterLeads(all, "all", "achieng").map { it.id })
        assertEquals(listOf("u1"), filterLeads(all, "all", "ACKNYERI").map { it.id }) // email
        assertEquals(listOf("u1"), filterLeads(all, "all", "nyeri").map { it.id }) // location
        assertEquals(listOf("u3"), filterLeads(all, "all", "2557543").map { it.id }) // nameless: by wa_id
        assertEquals(listOf("u6"), filterLeads(all, "Measuring", "").map { it.id })
        assertEquals(emptyList<String>(), filterLeads(all, "won", "achieng").map { it.id })
        assertEquals(8, filterLeads(all, "all", "").size)
    }
}
