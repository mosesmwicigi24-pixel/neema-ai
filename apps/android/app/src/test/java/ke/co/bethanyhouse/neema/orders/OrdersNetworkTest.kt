package ke.co.bethanyhouse.neema.orders

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
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
 * The Orders screen on a bad network: the list (first load, pull-to-refresh,
 * cached data) and the status change from the detail sheet, under offline,
 * timeouts, lost answers, 401/404/5xx, HTML pages, garbage and double taps.
 */
class OrdersNetworkTest {
    @get:Rule val main = ClockedMainRule()
    @get:Rule val paparazzi = Paparazzi()

    private val fake = FakeNeema.withFixtures().also { SalesFixtures.install(it) }
    private lateinit var toasts: ToastLog

    private fun vm(): Pair<DashboardViewModel, OrdersViewModel> {
        val dash = dashboard(paparazzi.context, fake)
        toasts = ToastLog(dash)
        return dash to OrdersViewModel(dash)
    }

    @After fun tearDown() { if (::toasts.isInitialized) toasts.close() }

    private val errors get() = toasts.all.filter { it.type == ToastType.Error }.map { it.message }

    /** The server's list with order [id] now in [status]. */
    private fun listWith(id: String, status: String) = SalesFixtures.ordersJson(
        SalesFixtures.orders.map { if (it.contains("\"id\":\"$id\"")) it.replace(Regex("\"status\":\"[a-z]+\""), "\"status\":\"$status\"") else it },
    )

    // ── The list ────────────────────────────────────────────────────────────

    @Test fun offlineFirstLoadShowsWhyAndRetryLoadsIt() {
        fake.offline("GET", "/admin/orders")
        val (dash, vm) = vm()
        assertFalse(vm.initialLoading.value)
        assertTrue(dash.orders.value.isEmpty())
        assertEquals("No connection — check your internet and try again", vm.loadError.value)
        // Back online.
        SalesFixtures.install(fake)
        vm.retry()
        assertFalse(vm.initialLoading.value)
        assertEquals(6, dash.orders.value.size)
        assertNull(vm.loadError.value)
    }

    @Test fun aFailedRefreshKeepsTheCachedListAndSaysWhy() {
        val (dash, vm) = vm()
        val shown = dash.orders.value
        fake.htmlPage("GET", "/admin/orders", 503)
        vm.refresh()
        assertFalse(vm.refreshing.value)
        assertEquals(shown, dash.orders.value)
        assertEquals("The server is unavailable right now — try again shortly", vm.loadError.value)
        // The next good read clears it.
        SalesFixtures.install(fake)
        vm.refresh()
        assertNull(vm.loadError.value)
    }

    @Test fun timeoutAndGarbageEachSayTheirOwnThing() {
        val (_, vm) = vm()
        fake.timeout("GET", "/admin/orders")
        vm.refresh()
        assertEquals("The server took too long to answer — try again", vm.loadError.value)
        fake.on("GET", "/admin/orders", body = """[{"id":"o1","wa_id":""")
        vm.refresh()
        assertEquals("The server sent an answer the app couldn't read", vm.loadError.value)
        fake.on("GET", "/admin/orders", code = 429, body = """{"detail":"Too Many Requests"}""")
        vm.refresh()
        assertEquals("Too many requests — wait a moment and try again", vm.loadError.value)
    }

    // ── Status change ───────────────────────────────────────────────────────

    @Test fun aTimeoutThatLandedIsReportedAsDone() {
        fake.timeout("PATCH", "/admin/orders/o2") { fake.on("GET", "/admin/orders", body = listWith("o2", "confirmed")) }
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o2" })
        vm.updateStatus("o2", "confirmed")
        assertEquals("Order marked as confirmed", toasts.all.last().message)
        assertTrue(errors.isEmpty())
        assertNull(vm.selectedId.value)
        assertEquals("confirmed", dash.orders.value.first { it.id == "o2" }.status)
    }

    @Test fun aTimeoutThatDidNotLandSaysNotUpdatedAndKeepsTheSheet() {
        fake.timeout("PATCH", "/admin/orders/o2")
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o2" })
        vm.updateStatus("o2", "confirmed")
        assertEquals("Order not updated — the server took too long to answer — try again", errors.last())
        assertEquals("o2", vm.selectedId.value)
        assertNull(vm.updating.value)
    }

    @Test fun whenNothingCanBeReadItSaysItMayNotHaveUpdated() {
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o2" })
        fake.dropped("PATCH", "/admin/orders/o2")
        fake.offline("GET", "/admin/orders")
        vm.updateStatus("o2", "confirmed")
        assertEquals("No answer from the server — the order may not have updated. Pull down to check.", errors.last())
        assertEquals("o2", vm.selectedId.value)
    }

    @Test fun offlineIsPlainlyNotUpdated() {
        fake.offline("PATCH", "/admin/orders/.*")
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o1" })
        val reads = fake.callsTo("GET", "/admin/orders").size
        vm.updateStatus("o1", "delivered")
        assertEquals("Failed to update order — no connection — check your internet and try again", errors.last())
        assertEquals("nothing reached the server: no reconcile read", reads, fake.callsTo("GET", "/admin/orders").size)
        assertEquals("o1", vm.selectedId.value)
    }

    @Test fun aDeletedOrderLeavesTheListAndTheSheetCloses() {
        fake.on("PATCH", "/admin/orders/o2", code = 404, body = """{"detail":"Order not found"}""")
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o2" })
        fake.on("GET", "/admin/orders", body = SalesFixtures.ordersJson(SalesFixtures.orders.filterNot { it.contains("\"id\":\"o2\"") }))
        vm.updateStatus("o2", "confirmed")
        assertEquals("This order no longer exists — it may have been deleted", errors.last())
        assertNull(vm.selectedId.value)
        assertTrue(dash.orders.value.none { it.id == "o2" })
    }

    @Test fun serverErrorsNeverShowHtml() {
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o1" })
        fake.on("PATCH", "/admin/orders/o1", code = 500, body = "<!doctype html><title>500</title><h1>Internal Server Error</h1>")
        vm.updateStatus("o1", "delivered")
        assertEquals("Failed to update order — the server hit an error — try again", errors.last())
        fake.on("PATCH", "/admin/orders/o1", code = 403, body = """{"detail":"Not enough permissions"}""")
        vm.updateStatus("o1", "delivered")
        assertEquals("Failed to update order — not enough permissions", errors.last())
    }

    @Test fun anExpiredTokenIsRefreshedAndTheChangeLands() {
        fake.expiredOnce("PATCH", "/admin/orders/o2") { 200 to """{"id":"o2","status":"confirmed"}""" }
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ -> 200 to Fixtures.tokenResponse(access = fakeJwt() + "r") }
        val (dash, vm) = vm()
        vm.updateStatus("o2", "confirmed")
        assertEquals("Order marked as confirmed", toasts.all.last().message)
        assertFalse(dash.sessionExpired.value)
    }

    @Test fun aDeadSessionKeepsTheSheetOpenWithoutAnExtraToast() {
        fake.on("PATCH", "/admin/orders/o2", code = 401, body = """{"detail":"Could not validate credentials"}""")
        fake.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val (dash, vm) = vm()
        vm.select(dash.orders.value.first { it.id == "o2" })
        vm.updateStatus("o2", "confirmed")
        assertTrue(dash.sessionExpired.value)
        assertEquals("o2", vm.selectedId.value)
        assertTrue(errors.isEmpty())
        assertNull(vm.updating.value)
    }

    @Test fun doubleTapsPatchOnce() {
        lateinit var vm: OrdersViewModel
        fake.on("PATCH", "/admin/orders/o2") { _, _ ->
            vm.updateStatus("o2", "confirmed"); vm.updateStatus("o2", "cancelled"); vm.updateStatus("o1", "delivered")
            200 to """{"id":"o2","status":"confirmed"}"""
        }
        vm = vm().second
        vm.updateStatus("o2", "confirmed")
        assertEquals(1, fake.calls.count { it.method == "PATCH" })
    }

    @Test fun anUnreadableSuccessIsSettledByTheList() {
        // A 200 whose body a proxy mangled: the list, re-read, says it went.
        fake.on("PATCH", "/admin/orders/o2") { _, _ ->
            fake.on("GET", "/admin/orders", body = listWith("o2", "cancelled"))
            200 to "<html>OK</html>"
        }
        val (_, vm) = vm()
        vm.updateStatus("o2", "cancelled")
        assertEquals("Order marked as cancelled", toasts.all.last().message)
    }

    @Test fun signingOutMidUpdateIsQuiet() {
        val (dash, _) = vm()
        val store = SeededStore()
        lateinit var vm: OrdersViewModel
        fake.on("PATCH", "/admin/orders/o2") { _, _ -> store.viewModelStore.clear(); 200 to "{}" }
        vm = store.seed(OrdersViewModel(dash))
        val before = toasts.all.size
        vm.updateStatus("o2", "confirmed")
        assertEquals(before, toasts.all.size)
    }
}
