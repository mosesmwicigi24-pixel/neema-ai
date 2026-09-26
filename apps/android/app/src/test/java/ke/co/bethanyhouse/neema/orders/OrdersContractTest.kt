package ke.co.bethanyhouse.neema.orders

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.feature.orders.amount
import ke.co.bethanyhouse.neema.feature.orders.effectiveQty
import ke.co.bethanyhouse.neema.feature.orders.effectiveUnit
import ke.co.bethanyhouse.neema.feature.orders.hubMeta
import ke.co.bethanyhouse.neema.feature.orders.hubOrderHref
import ke.co.bethanyhouse.neema.feature.orders.lineTotal
import ke.co.bethanyhouse.neema.feature.orders.priceKnown
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import java.time.Instant

/**
 * The Orders screen against the REAL shapes of admin.py `list_orders`,
 * `get_order` and `update_order` (round 3: API contract). Every request is
 * asserted exactly; every response variant the server can legitimately send
 * must decode.
 */
class OrdersContractTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi()

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private val dash by lazy { dashboard(paparazzi.context, fake) }
    private var toasts: ToastLog? = null

    @After fun tearDown() { toasts?.close() }

    // ── GET /admin/orders ───────────────────────────────────────────────────

    @Test fun listIsAPlainGetWithNoQuery() {
        val list = runBlocking { dash.api.orders.list() }
        val call = fake.callsTo("GET", "/admin/orders").last()
        assertNull("the dashboard's list sends no filter", call.query)
        assertEquals(6, list.size)
    }

    @Test fun listFiltersUseTheServersParamNames() {
        runBlocking { dash.api.orders.list(status = "confirmed", waId = "254712345678") }
        assertEquals("status=confirmed&wa_id=254712345678", fake.callsTo("GET", "/admin/orders").last().query)
    }

    @Test fun aFullOrmRowDecodesEveryFieldTheScreenReads() {
        fake.on("GET", "/admin/orders", body = SalesFixtures.ordersJson(listOf(SalesFixtures.linkedOrder)))
        val o = runBlocking { dash.api.orders.list() }.single()
        assertEquals("254712345678_1773480600000", o.id)
        assertEquals(9800.0, o.subtotal, 0.0)                     // Decimal → float via jsonable_encoder
        assertEquals(9800.0, o.amount, 0.0)
        assertEquals("KES", o.currency)
        assertEquals("confirmed", o.status)
        assertEquals("unpaid", o.paymentStatus)
        assertEquals("pending", o.fulfillmentStatus)
        assertEquals(1042L, o.hubOrderId)
        assertEquals("BH-1042", o.hubOrderNumber)
        assertEquals("pushed", o.hubPushStatus)
        assertEquals("processing", o.hubStatus)
        assertEquals("paid", o.hubPaymentStatus)
        assertEquals("tok1042", o.hubPublicToken)
        assertEquals("https://hub.bethanyhouse.co.ke/order/tok1042", o.hubPublicUrl)
        assertEquals("https://hub.bethanyhouse.co.ke/handoff/orders/1042#v=tok1042", hubOrderHref(o))
        assertEquals("Confirmed", hubMeta(o)?.label)
        // No contact_name on the wire (it isn't a column): the name falls back to the wa_id.
        assertNull(o.contactName)
        assertEquals("254712345678", o.customerName)
        // "+00:00" with no fraction parses to the exact instant.
        assertEquals(Instant.parse("2026-03-14T09:30:00Z").toEpochMilli(), Fmt.millis(o.createdAt))
        assertEquals(3, o.items.size)
        assertEquals(7000.0, o.items[0].lineTotal, 0.0)
        assertEquals(3500.0, o.items[0].effectiveUnit, 0.0)
    }

    @Test fun microsecondOffsetTimestampsParse() {
        val iso = SalesFixtures.pyIso(Instant.parse("2026-09-25T08:15:30.123456Z"))
        assertEquals("2026-09-25T08:15:30.123456+00:00", iso)
        assertEquals(Instant.parse("2026-09-25T08:15:30.123Z").toEpochMilli(), Fmt.millis(iso))
    }

    @Test fun agentOrderLinesCarryUnitPriceOnlyAndNeverPrintAMadeUpZero() {
        fake.on("GET", "/admin/orders", body = SalesFixtures.ordersJson(listOf(SalesFixtures.agentOrder)))
        val o = runBlocking { dash.api.orders.list() }.single()
        assertEquals("pending", o.status)
        assertEquals(145000.0, o.amount, 0.0)
        val line = o.items.first()
        assertEquals("Mitre — Gold embroidered", line.name)
        assertEquals("MIT-GLD", line.sku)
        assertEquals(1.0, line.effectiveQty, 0.0)
        // The agent's cart lines carry only `unit_price` (agent/tools.py); the core
        // OrderItemsSerializer normalises it into `unit` and `total`, so the line is priced.
        assertEquals(true, line.priceKnown)
        assertEquals(85000.0, line.unit, 0.0)
        assertEquals(85000.0, line.total, 0.0)
        assertEquals(145000.0, o.items.sumOf { it.total }, 0.0)  // lines add up to the order
    }

    @Test fun cartSnapshotWithNoLinesDecodes() {
        val snap = SalesFixtures.orders.first { it.contains("\"id\":\"o5\"") }
        fake.on("GET", "/admin/orders", body = SalesFixtures.ordersJson(listOf(snap)))
        val o = runBlocking { dash.api.orders.list() }.single()
        assertEquals("pending", o.status)  // "open" is shown as pending
        assertTrue(o.items.isEmpty())
        assertEquals("cart", o.eventType)
    }

    @Test fun decimalsAsStringsAndMissingColumnsStillDecode() {
        // pydantic v2 serialises Decimal as a STRING; an older API had no hub columns at all.
        fake.on("GET", "/admin/orders", body = """[{"id":"254700000001_1","wa_id":"254700000001",
            "items":[{"name":"Alb","qty":"2","unit":"3500.00","total":"7000.00"}],
            "subtotal":"7000.00","currency":"KES","status":"open","channel":"whatsapp",
            "created_at":"2026-03-14T09:30:00","hub_total":"7000.00"}]""")
        val o = runBlocking { dash.api.orders.list() }.single()
        assertEquals(7000.0, o.subtotal, 0.0)
        assertEquals(2.0, o.items[0].qty, 0.0)
        assertEquals(3500.0, o.items[0].effectiveUnit, 0.0)
        assertNull(o.hubOrderId)
        assertNull(o.updatedAt)
        assertNull(o.hubPushStatus)
        // A naive timestamp is read as UTC, as the server wrote it.
        assertEquals(Instant.parse("2026-03-14T09:30:00Z").toEpochMilli(), Fmt.millis(o.createdAt))
    }

    @Test fun nullablesSentAsExplicitNullDecode() {
        fake.on("GET", "/admin/orders", body = """[{"id":"x","wa_id":"254700000001","session_id":null,"event_type":null,
            "items":[{"name":"Alb","qty":1,"unit":100,"total":100,"sku":null}],"subtotal":100.0,"currency":"KES","status":"pending",
            "payment_status":"unpaid","fulfillment_status":"pending","reply_text":null,"channel":"whatsapp","state":{},
            "created_at":"2026-03-14T09:30:00+00:00","updated_at":"2026-03-14T09:30:00+00:00","hub_order_id":null,
            "hub_total":null,"hub_status":null,"hub_public_token":null}]""")
        val o = runBlocking { dash.api.orders.list() }.single()
        assertNull(o.items[0].sku)
        assertNull(hubOrderHref(o))
        assertNull(hubMeta(o))
    }

    // ── GET /admin/orders/{id} ──────────────────────────────────────────────

    @Test fun getOneAndItsNotFound() {
        fake.on("GET", "/admin/orders/[^/]+", body = SalesFixtures.failedOrder)
        val o = runBlocking { dash.api.orders.get("254722000111_1773480600000") }
        assertEquals("/admin/orders/254722000111_1773480600000", fake.calls.last().path)
        assertEquals("failed", o.hubPushStatus)
        assertEquals("Variant CAS-PUR-L is out of stock in the hub (0 available)", o.hubLastError)

        fake.on("GET", "/admin/orders/[^/]+", code = 404, body = """{"detail":"Order not found"}""")
        try {
            runBlocking { dash.api.orders.get("nope") }
            fail("404 must throw")
        } catch (e: ApiException) {
            assertEquals(404, e.status)
            assertEquals("Order not found", e.detail)
        }
    }

    // ── PATCH /admin/orders/{id} ────────────────────────────────────────────

    @Test fun patchSendsOnlyAllowedKeysAndDecodesTheNaiveUpdatedAt() {
        val o = runBlocking { dash.api.orders.updateStatus("o2", "confirmed") }
        val call = fake.callsTo("PATCH", "/admin/orders/o2").single()
        assertEquals(Json.parseToJsonElement("""{"status":"confirmed"}"""), Json.parseToJsonElement(call.body!!))
        assertEquals("confirmed", o.status)
        // update_order returns the row with updated_at from datetime.utcnow(): no offset.
        val updated = o.updatedAt!!
        assertTrue("naive: $updated", !updated.endsWith("Z") && !updated.contains("+"))
        assertNotNull(Fmt.millis(updated))

        runBlocking { dash.api.orders.updateStatus("o3", "delivered", paymentStatus = "paid", fulfillmentStatus = "fulfilled") }
        assertEquals(
            Json.parseToJsonElement("""{"status":"delivered","payment_status":"paid","fulfillment_status":"fulfilled"}"""),
            Json.parseToJsonElement(fake.callsTo("PATCH", "/admin/orders/o3").single().body!!),
        )
    }

    @Test fun patchingAHubLinkedOrderOnlyChangesOurFlag() {
        // update_order never touches hub_*: the row comes back with the hub's own state intact.
        fake.on("PATCH", "/admin/orders/[^/]+", body = SalesFixtures.linkedOrder.replace("\"status\":\"confirmed\"", "\"status\":\"delivered\""))
        val o = runBlocking { dash.api.orders.updateStatus("254712345678_1773480600000", "delivered") }
        assertEquals("delivered", o.status)
        assertEquals("processing", o.hubStatus)
        assertEquals("Confirmed", hubMeta(o)?.label) // the list keeps reading hub truth
    }

    @Test fun patchNotFoundAndUnprocessableToastTheWebsCopy() {
        val vm = OrdersViewModel(dash)
        toasts = ToastLog(dash)
        fake.on("PATCH", "/admin/orders/.*", code = 404, body = """{"detail":"Order not found"}""")
        vm.updateStatus("gone", "confirmed")
        assertEquals("Failed to update order", toasts!!.all.last().message)
        // FastAPI's 422 for a non-object body is a pydantic LIST detail.
        fake.on("PATCH", "/admin/orders/.*", code = 422,
            body = """{"detail":[{"type":"dict_type","loc":["body"],"msg":"Input should be a valid dictionary","input":"x"}]}""")
        vm.updateStatus("o1", "confirmed")
        assertEquals("Failed to update order", toasts!!.all.last().message)
        assertNull(vm.updating.value)
    }

    @Test fun zambianOrderKeepsItsCurrency() {
        val zmw = SalesFixtures.orders.first { it.contains("\"id\":\"o6\"") }
        fake.on("GET", "/admin/orders", body = SalesFixtures.ordersJson(listOf(zmw)))
        val o = runBlocking { dash.api.orders.list() }.single()
        assertEquals("ZMW", o.currency)
        assertEquals("ZMW 1,450", Fmt.currency(o.amount, o.currency))
        assertEquals("Shipped", hubMeta(o)?.label)
    }
}
