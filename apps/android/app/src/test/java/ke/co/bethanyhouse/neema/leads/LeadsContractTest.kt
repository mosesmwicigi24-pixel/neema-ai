package ke.co.bethanyhouse.neema.leads

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.leads.Lead
import ke.co.bethanyhouse.neema.feature.leads.LeadsApi
import ke.co.bethanyhouse.neema.feature.leads.LeadsViewModel
import ke.co.bethanyhouse.neema.feature.leads.diffLead
import ke.co.bethanyhouse.neema.feature.leads.normaliseStage
import ke.co.bethanyhouse.neema.orders.MainDispatcherRule
import ke.co.bethanyhouse.neema.orders.ToastLog
import ke.co.bethanyhouse.neema.orders.bodies
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * The Leads board against crm.py `list_leads` / `update_lead` (round 3: API
 * contract): the bare array, int scores, float-or-int spend, optional
 * rhythm/tier, tags as stored, `notes_base` and the manual stage lock.
 */
class LeadsContractTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi()

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private val dash by lazy { dashboard(paparazzi.context, fake) }
    private val api by lazy { LeadsApi(dash.api.http) }
    private var toasts: ToastLog? = null

    @After fun tearDown() { toasts?.close() }

    private fun json(s: String) = Json.parseToJsonElement(s)
    private fun decode(s: String): List<Lead> = NeemaJson.decodeFromString(ListSerializer(Lead.serializer()), s)

    // ── GET /admin/leads ────────────────────────────────────────────────────

    @Test fun listIsABareArrayWithNoQuery() {
        val leads = runBlocking { api.list() }
        assertNull(fake.callsTo("GET", "/admin/leads").last().query)
        assertEquals(8, leads.size)
        val u1 = leads.first()
        assertEquals(86, u1.leadScore)
        assertEquals(24500.0, u1.totalSpent, 0.0)
        assertEquals("regular", u1.tier)
        assertEquals(12.0, u1.buyingRhythm!!.daysSinceLast!!, 0.0)
        assertEquals(30.5, u1.buyingRhythm!!.avgIntervalDays!!, 0.0)
        assertNotNull(Fmt.millis(u1.lastSeenAt))
        // No orders: Python's sum([]) is the int 0, and the rhythm is all nulls.
        val u2 = leads.first { it.id == "u2" }
        assertEquals(0.0, u2.totalSpent, 0.0)
        assertEquals("prospect", u2.tier)
        assertNull(u2.buyingRhythm!!.daysSinceLast); assertNull(u2.buyingRhythm!!.cadenceLabel)
        // An Instagram handle is no phone: phone is null, the handle is the wa_id.
        val u4 = leads.first { it.id == "u4" }
        assertNull(u4.phone)
        assertEquals("17840000000000001", u4.handle)
        // Never seen.
        assertNull(leads.first { it.id == "u8" }.lastSeenAt)
    }

    @Test fun stageQueryIsNormalisedLikeTheServer() {
        runBlocking { api.list("Measuring") }
        assertEquals("stage=measuring", fake.callsTo("GET", "/admin/leads").last().query)
        runBlocking { api.list(" Negotiating ") }
        assertEquals("stage=negotiation", fake.callsTo("GET", "/admin/leads").last().query)
        assertEquals("new", normaliseStage(null))
        assertEquals("", normaliseStage("  "))
    }

    @Test fun decimalsAndFloatScoresAndMissingKeysDecode() {
        val l = decode("""[{"id":"0c7d0a3e-1d2b-4c5e-8f90-a1b2c3d4e5f6","wa_id":"254700000001","lead_stage":"new",
            "lead_score":42.0,"total_spent":"18000.50","total_orders":1}]""").single()
        assertEquals(42, l.leadScore)
        assertEquals(18000.5, l.totalSpent, 0.0)
        assertNull(l.buyingRhythm); assertNull(l.tier); assertNull(l.name); assertNull(l.notes)
        assertEquals(emptyList<String>(), l.tags); assertEquals(emptyList<String>(), l.channels)
    }

    @Test fun tagsAsStoredNeverFailTheBoard() {
        // state["tags"] is written verbatim by PATCH /leads and PATCH /customers.
        val rows = decode("""[
          {"id":"a","wa_id":"1","tags":null},
          {"id":"b","wa_id":"2","tags":"vip, clergy"},
          {"id":"c","wa_id":"3","tags":["vip",5,null,{"x":1}," "]},
          {"id":"d","wa_id":"4","tags":{"odd":true}}
        ]""")
        assertEquals(listOf(emptyList(), listOf("vip", "clergy"), listOf("vip", "5"), emptyList<String>()), rows.map { it.tags })
    }

    @Test fun anExtraneousStageStillDecodesAndMatchesCaseInsensitively() {
        val l = decode("""[{"id":"x","wa_id":"1","lead_stage":"measuring"}]""").single()
        assertEquals("measuring", l.leadStage)
    }

    @Test fun failedLoadShowsTheServersReason() {
        fake.on("GET", "/admin/leads", code = 500, body = """{"detail":"database is down"}""")
        toasts = ToastLog(dash)
        val vm = LeadsViewModel(dash)
        assertTrue(vm.leads.value.isEmpty())
        assertEquals(false, vm.loading.value)
        assertEquals("database is down", toasts!!.all.last().message)
        assertEquals(ToastType.Error, toasts!!.all.last().type)
    }

    // ── PATCH /admin/leads/{id} ─────────────────────────────────────────────

    @Test fun patchKeysOnTheUserIdAndReadsOk() {
        val r = runBlocking {
            api.update("0c7d0a3e-1d2b-4c5e-8f90-a1b2c3d4e5f6", buildJsonObject { put("lead_stage", "Measuring") })
        }
        assertTrue(r.ok)
        assertEquals(
            listOf(json("""{"lead_stage":"Measuring"}""")),
            fake.bodies("PATCH", "/admin/leads/0c7d0a3e-1d2b-4c5e-8f90-a1b2c3d4e5f6"),
        )
    }

    @Test fun unchangedStageIsNeverSentSoTheAiStaysUnlocked() {
        // update_lead sets lead_stage_source="manual" whenever lead_stage is in the
        // body — so a notes-only save must not carry the stage.
        val vm = LeadsViewModel(dash)
        val u1 = vm.leads.value.first { it.id == "u1" }
        val edit = diffLead(u1, "Proposal", u1.tags.joinToString(", "), u1.notes + "\n\nCalled: wants 3 more.")
        vm.update(u1, edit.stage, edit.tags, edit.notes, edit.notesBase)
        val body = fake.bodies("PATCH", "/admin/leads/u1").single()
        assertTrue("stage must not be sent: $body", "lead_stage" !in body)
        assertTrue("tags must not be sent: $body", "tags" !in body)
        assertEquals(u1.notes, body["notes_base"]!!.jsonPrimitive.content)
    }

    @Test fun notesSaveReReadsTheServersMergedNotes() {
        // A server that merges like crm.py merge_notes: a call summary appended
        // while the operator typed survives their save, and the board shows it.
        var stored = "Buys for the whole parish. Prefers delivery on Fridays."
        val summary = "📞 Call summary: wants three more shirts."
        stored += "\n\n$summary"
        fake.on("PATCH", "/admin/leads/u1") { _, body ->
            val b = Json.parseToJsonElement(body!!).jsonObject
            val paras = { s: String? -> (s ?: "").split("\n\n").map { it.trim() }.filter { it.isNotEmpty() } }
            val base = paras(b["notes_base"]?.jsonPrimitive?.content)
            val mine = paras(b["notes"]!!.jsonPrimitive.content)
            val cur = paras(stored)
            stored = (mine + cur.filter { it !in base && it !in mine }).joinToString("\n\n")
            200 to """{"ok":true}"""
        }
        fake.on("GET", "/admin/leads") { _, _ ->
            200 to SalesFixtures.leadsJson(listOf(SalesFixtures.lead("u1", "254712345678", "Fr. Peter Kamau", "proposal", 86,
                spent = 24500.0, orders = 3, notes = stored)))
        }
        toasts = ToastLog(dash)
        val vm = LeadsViewModel(dash)
        val u1 = vm.leads.value.single()
        // The operator opened the sheet before the summary landed: their base is the old text.
        val opened = u1.copy(notes = "Buys for the whole parish. Prefers delivery on Fridays.")
        val edit = diffLead(opened, "proposal", "", "Buys for the whole parish. Prefers delivery on Fridays.\n\nVIP pricing agreed.")
        vm.update(opened, edit.stage, edit.tags, edit.notes, edit.notesBase)
        assertEquals("Lead updated", toasts!!.all.last().message)
        assertEquals(
            "Buys for the whole parish. Prefers delivery on Fridays.\n\nVIP pricing agreed.\n\n$summary",
            vm.leads.value.single().notes,
        )
    }

    @Test fun patchNotFoundRollsBack() {
        fake.on("PATCH", "/admin/leads/.*", code = 404, body = """{"detail":"Lead not found"}""")
        toasts = ToastLog(dash)
        val vm = LeadsViewModel(dash)
        vm.moveTo(vm.leads.value.first { it.id == "u2" }, "won")
        assertEquals("Failed to update lead", toasts!!.all.last().message)
        assertEquals("qualified", vm.leads.value.first { it.id == "u2" }.leadStage)
    }
}
