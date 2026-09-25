package ke.co.bethanyhouse.neema.orders

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.feature.orders.STATUS_ACTIONS
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.feature.orders.filterOrders
import ke.co.bethanyhouse.neema.feature.orders.hubMeta
import ke.co.bethanyhouse.neema.feature.orders.hubOrderHref
import ke.co.bethanyhouse.neema.feature.orders.pageWindow
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.testContainer
import ke.co.bethanyhouse.neema.testing.fixtures.SalesFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Collects every toast the dashboard raises. */
class ToastLog(dash: DashboardViewModel) {
    private val scope = CoroutineScope(Dispatchers.Unconfined)
    val all = mutableListOf<Toast>()
    init { scope.launch { dash.toasts.collect { all += it } } }
    fun close() = scope.cancel()
}

fun FakeNeema.bodies(method: String, path: String): List<JsonObject> =
    calls.filter { it.method == method && it.path == path }.map { Json.parseToJsonElement(it.body ?: "{}").jsonObject }

/** OrdersView's behaviour against the fake API: status moves, filters, paging, hub linkage. */
class OrdersBehaviourTest {
    @get:Rule val main = MainDispatcherRule()
    @get:Rule val paparazzi = Paparazzi() // a layoutlib Context for the container

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private lateinit var toasts: ToastLog

    private fun vm(): Pair<DashboardViewModel, OrdersViewModel> {
        val dash = dashboard(paparazzi.context, fake)
        toasts = ToastLog(dash)
        return dash to OrdersViewModel(dash)
    }

    @After fun tearDown() { if (::toasts.isInitialized) toasts.close() }

    private fun order(id: String, status: String = "open", name: String? = "Fr. Peter Kamau", waId: String = "254712345678") =
        Order(id = id, waId = waId, rawStatus = status, contactName = name)

    @Test fun statusMovePatchesOnlyTheStatusThenRefetchesAndClosesTheSheet() {
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o2" })
        val getsBefore = fake.calls.count { it.method == "GET" && it.path == "/admin/orders" }

        vm.updateStatus("o2", "confirmed")

        // JSON.stringify drops the web's undefined payment/fulfilment fields: only status goes.
        assertEquals(listOf(Json.parseToJsonElement("""{"status":"confirmed"}""")), fake.bodies("PATCH", "/admin/orders/o2"))
        assertTrue(fake.calls.count { it.method == "GET" && it.path == "/admin/orders" } > getsBefore)
        assertNull(vm.selectedId.value)
        assertNull(vm.updating.value)
        assertEquals("Order marked as confirmed", toasts.all.last().message)
    }

    @Test fun failedStatusMoveToastsAndKeepsTheSheetOpen() {
        fake.on("PATCH", "/admin/orders/.*", code = 500, body = """{"detail":"hub unreachable"}""")
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o1" })

        vm.updateStatus("o1", "delivered")

        assertEquals("o1", vm.selectedId.value)
        assertNull(vm.updating.value)
        val t = toasts.all.last()
        assertEquals(ToastType.Error, t.type)
        assertTrue(t.message, t.message.startsWith("Failed to update order"))
    }

    @Test fun allowedTransitionsMatchTheWeb() {
        assertEquals(listOf("confirmed", "cancelled"), STATUS_ACTIONS[order("a", "open").status])
        assertEquals(listOf("confirmed", "cancelled"), STATUS_ACTIONS["pending"])
        assertEquals(listOf("delivered", "cancelled"), STATUS_ACTIONS["confirmed"])
        assertEquals(emptyList<String>(), STATUS_ACTIONS["delivered"])
        assertEquals(emptyList<String>(), STATUS_ACTIONS["cancelled"])
    }

    @Test fun openCartsCountAsPending() = assertEquals("pending", order("a", "open").status)

    @Test fun filterBySearchAndStatus() {
        val list = listOf(
            order("ORD-1", "open", "Fr. Peter Kamau", "254712345678"),
            order("ORD-2", "confirmed", "Rev. Mary Achieng", "254722000111"),
            order("abc-3", "delivered", null, "255754333222"),
        )
        assertEquals(listOf("ORD-1"), filterOrders(list, "pending", "").map { it.id })
        assertEquals(listOf("ORD-2"), filterOrders(list, "all", "MARY").map { it.id })
        assertEquals(listOf("ORD-2"), filterOrders(list, "all", "722000").map { it.id })
        assertEquals(listOf("ORD-1", "ORD-2"), filterOrders(list, "all", "ord-").map { it.id })
        // A nameless order is searched by its wa_id, as contact_name falls back to it.
        assertEquals(listOf("abc-3"), filterOrders(list, "all", "2557543").map { it.id })
        assertEquals(emptyList<String>(), filterOrders(list, "confirmed", "peter").map { it.id })
    }

    @Test fun filterAndSearchResetThePage() {
        val (_, vm) = vm()
        vm.setPage(3); vm.setFilter("confirmed"); assertEquals(1, vm.page.value)
        vm.setPage(2); vm.setSearch("x"); assertEquals(1, vm.page.value)
        vm.toggleFilter("confirmed"); assertEquals("all", vm.filter.value)
        vm.toggleFilter("pending"); assertEquals("pending", vm.filter.value)
    }

    @Test fun pagerWindowsFiveAroundTheCurrentPage() {
        assertEquals(listOf(1, 2, 3), pageWindow(2, 3))
        assertEquals(listOf(1, 2, 3, 4, 5), pageWindow(1, 7))
        assertEquals(listOf(1, 2, 3, 4, 5), pageWindow(3, 7))
        assertEquals(listOf(2, 3, 4, 5, 6), pageWindow(4, 7))
        assertEquals(listOf(3, 4, 5, 6, 7), pageWindow(6, 7))
        assertEquals(listOf(3, 4, 5, 6, 7), pageWindow(7, 7))
    }

    @Test fun hubLinkageFollowsTheHubsOwnState() {
        val linked = order("a").copy(hubOrderId = 1042, hubPublicToken = "tok", hubStatus = "processing")
        assertEquals("https://hub.bethanyhouse.co.ke/handoff/orders/1042#v=tok", hubOrderHref(linked))
        assertEquals("https://hub.bethanyhouse.co.ke/handoff/orders/1042", hubOrderHref(linked.copy(hubPublicToken = null)))
        assertNull(hubOrderHref(order("b")))
        assertEquals("Confirmed", hubMeta(linked)?.label)
        assertEquals("Shipped", hubMeta(linked.copy(hubStatus = "SHIPPED"))?.label)
        assertEquals("Completed", hubMeta(linked.copy(hubStatus = "delivered"))?.label)
        assertEquals("Cancelled", hubMeta(linked.copy(hubStatus = "voided"))?.label)
        assertNull(hubMeta(linked.copy(hubStatus = "on-hold")))
        // Never pushed: the hub has no say, whatever the row carries.
        assertNull(hubMeta(order("c").copy(hubStatus = "completed")))
    }

    @Test fun quietRefreshEndsAtOnceWithOneRequest() {
        val (_, vm) = vm()
        val before = fake.calls.count { it.path == "/admin/orders" }
        vm.refresh()
        assertFalse("the spinner must stop when nothing changed", vm.refreshing.value)
        assertEquals(before + 1, fake.calls.count { it.path == "/admin/orders" })
    }

    @Test fun refreshThatFindsNewOrdersHandsThemToTheDashboard() {
        val (dash, vm) = vm()
        fake.on("GET", "/admin/orders", body = SalesFixtures.ordersJson(SalesFixtures.orders.take(2)))
        vm.refresh()
        assertFalse(vm.refreshing.value)
        assertEquals(listOf("o1", "o2"), dash.orders.value.map { it.id })
    }

    @Test fun emptyShopFinishesLoading() {
        fake.on("GET", "/admin/orders", body = "[]")
        // No cached snapshot to paint from: this is a genuinely empty first load.
        val container = testContainer(paparazzi.context, fake).also { it.snapshots.clear() }
        val dash = DashboardViewModel(container)
        assertTrue(dash.orders.value.isEmpty())
        val vm = OrdersViewModel(dash)
        assertFalse("an empty list must read 'No orders found', not spin", vm.initialLoading.value)
    }
}
