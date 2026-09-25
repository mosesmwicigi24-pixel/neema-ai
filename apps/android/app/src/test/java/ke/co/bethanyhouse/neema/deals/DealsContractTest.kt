package ke.co.bethanyhouse.neema.deals

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.orders.MainDispatcherRule
import ke.co.bethanyhouse.neema.orders.ToastLog
import ke.co.bethanyhouse.neema.orders.bodies
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Deals, planned actions and pipeline stages against crm.py's real handlers
 * (`list_deals`, `update_deal`, `list_actions`, `approve_action`,
 * `veto_action`, `get_pipeline_stages`) — round 3: API contract.
 */
class DealsContractTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi()

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private val dash by lazy { dashboard(paparazzi.context, fake) }
    private var toasts: ToastLog? = null

    @After fun tearDown() { toasts?.close() }

    private fun json(s: String) = Json.parseToJsonElement(s)
    private fun vm(): DealsViewModel { toasts = ToastLog(dash); return DealsViewModel(dash) }

    // ── GET /admin/deals ────────────────────────────────────────────────────

    @Test fun dealsListIsAnEnvelopeKeyedByStatus() {
        val open = runBlocking { dash.api.deals.list() }
        assertEquals("status=open", fake.callsTo("GET", "/admin/deals").last().query)
        assertEquals(4, open.size)
        val d1 = open.first()
        assertEquals("Fr. Peter Kamau", d1.customer)
        assertEquals("c1", d1.conversationId)
        // items_snapshot's price is the cart line's `price`, absent on Tier 2 lines → null.
        assertEquals(2.0, d1.items.single().qty!!, 0.0)
        assertNull(d1.items.single().price)
        assertEquals("ai", d1.nextAction?.owner)
        assertNotNull(Fmt.millis(d1.nextAction?.dueAt))
        assertNotNull(Fmt.millis(d1.updatedAt))
        // A deal whose conversation is gone: customer "Unknown", no wa_id / channel.
        val d4 = open.last()
        assertNull(d4.conversationId); assertNull(d4.waId); assertNull(d4.channel)
        assertEquals("Unknown", d4.customer)

        val won = runBlocking { dash.api.deals.list("won") }
        assertEquals("status=won", fake.callsTo("GET", "/admin/deals").last().query)
        assertEquals(2, won.size)
        // title / updated_at may be null.
        assertNull(won.last().title); assertNull(won.last().updatedAt)
    }

    @Test fun dealWithEveryOptionalMissingOrNullDecodes() {
        fake.on("GET", "/admin/deals", body = """{"deals":[{"id":"8c1e0f2a-1111-4222-8333-444455556666","customer":"Unknown",
            "items":[{"name":null,"qty":"1","price":"3500.00"}],"stage":"new","status":"open","next_action":null}]}""")
        val d = runBlocking { dash.api.deals.list() }.single()
        assertEquals(3500.0, d.items.single().price!!, 0.0)   // Decimal-as-string
        assertNull(d.items.single().name)
        assertNull(d.nextAction); assertNull(d.guidance); assertNull(d.blocking); assertNull(d.updatedAt)
    }

    @Test fun emptyEnvelopeIsAnEmptyBoard() {
        fake.on("GET", "/admin/deals", body = """{"deals":[]}""")
        assertTrue(runBlocking { dash.api.deals.list() }.isEmpty())
    }

    // ── PATCH /admin/deals/{id} ─────────────────────────────────────────────

    @Test fun patchSendsTheAcceptedFieldsAndReadsOk() {
        val body = buildJsonObject { put("guidance", "No discount"); put("stage", "proposal") }
        val r = runBlocking { dash.api.deals.patch("d1", body) }
        assertTrue(r.ok)
        assertEquals(listOf(json("""{"guidance":"No discount","stage":"proposal"}""")), fake.bodies("PATCH", "/admin/deals/d1"))
    }

    @Test fun patchWithABadIdToastsTheWebsCopy() {
        fake.on("PATCH", "/admin/deals/.*", code = 422, body = """{"detail":"Invalid deal id"}""")
        val vm = vm()
        vm.saveGuidance("not-a-uuid", "x")
        assertEquals("Update failed", toasts!!.all.last().message)
        assertEquals(ToastType.Error, toasts!!.all.last().type)
    }

    // ── GET /admin/actions ──────────────────────────────────────────────────

    @Test fun actionsQueueIsPendingByDefault() {
        val list = runBlocking { dash.api.actions.list() }
        assertEquals("status=pending", fake.callsTo("GET", "/admin/actions").last().query)
        assertEquals(listOf("needs_approval", "planned"), list.map { it.status })
        assertEquals("ai", list.first().createdBy)
        assertNotNull(Fmt.millis(list.first().dueAt))
        assertNull(list.last().draft)
    }

    // ── POST /admin/actions/{id}/approve | veto ─────────────────────────────

    @Test fun approveReadsTheSentEcho() {
        val r = runBlocking { dash.api.actions.approve("x1", "Father, Friday 🙏") }
        assertTrue(r.ok)
        assertEquals(listOf(json("""{"draft":"Father, Friday 🙏"}""")), fake.bodies("POST", "/admin/actions/x1/approve"))
    }

    @Test fun approveOfAnAlreadyResolvedActionSaysWhyAndDropsTheRow() {
        val vm = vm()
        val gets = fake.callsTo("GET", "/admin/actions").size
        // The scheduler sent it first: approve_action → 409 "Action is sent".
        fake.on("POST", "/admin/actions/.*/approve", code = 409, body = """{"detail":"Action is sent"}""")
        fake.on("GET", "/admin/actions", body = """{"actions":[]}""")
        vm.act("x1", "approve")
        assertEquals("approve failed — Action is sent", toasts!!.all.last().message)
        assertEquals(ToastType.Error, toasts!!.all.last().type)
        assertEquals(gets + 1, fake.callsTo("GET", "/admin/actions").size)
        assertEquals(emptyList<Any>(), vm.actions.value)
        assertTrue(vm.acting.value.isEmpty())
    }

    @Test fun approveWhenTheChatIsGoneSaysSo() {
        val vm = vm()
        fake.on("POST", "/admin/actions/.*/approve", code = 404, body = """{"detail":"Conversation gone"}""")
        vm.act("x2", "approve")
        assertEquals("approve failed — Conversation gone", toasts!!.all.last().message)
    }

    @Test fun approveServerCrashKeepsTheWebsToast() {
        val vm = vm()
        // An unhandled send failure is Starlette's plain-text 500, not JSON.
        fake.on("POST", "/admin/actions/.*/approve", code = 500, body = "Internal Server Error")
        vm.act("x1", "approve")
        assertEquals("approve failed", toasts!!.all.last().message)
        // "Could not compose the message" is a JSON 500 — same toast.
        fake.on("POST", "/admin/actions/.*/approve", code = 500, body = """{"detail":"Could not compose the message"}""")
        vm.act("x2", "approve")
        assertEquals("approve failed", toasts!!.all.last().message)
    }

    @Test fun vetoPostsAnEmptyObjectAndReadsOk() {
        val r = runBlocking { dash.api.actions.veto("x2") }
        assertTrue(r.ok)
        assertEquals(listOf(json("{}")), fake.bodies("POST", "/admin/actions/x2/veto"))
    }

    @Test fun vetoOfAMissingActionSaysNotFound() {
        val vm = vm()
        fake.on("POST", "/admin/actions/.*/veto", code = 404, body = """{"detail":"Action not found"}""")
        vm.act("x2", "veto")
        assertEquals("veto failed — Action not found", toasts!!.all.last().message)
    }

    // ── GET /admin/settings/pipeline-stages ─────────────────────────────────

    @Test fun pipelineStagesAreOperatorLabels() {
        assertEquals(listOf("Measuring"), runBlocking { dash.api.settings.getPipelineStages() })
        fake.on("GET", "/admin/settings/pipeline-stages", body = """{"stages":[]}""")
        assertEquals(emptyList<String>(), runBlocking { dash.api.settings.getPipelineStages() })
    }
}
