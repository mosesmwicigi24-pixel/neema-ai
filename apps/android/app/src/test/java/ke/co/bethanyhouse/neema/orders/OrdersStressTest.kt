package ke.co.bethanyhouse.neema.orders

import androidx.compose.ui.unit.dp
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.feature.orders.ORDER_STATUSES
import ke.co.bethanyhouse.neema.feature.orders.OrdersViewModel
import ke.co.bethanyhouse.neema.core.util.SingleFlight
import ke.co.bethanyhouse.neema.feature.orders.amount
import ke.co.bethanyhouse.neema.feature.orders.filterOrders
import ke.co.bethanyhouse.neema.feature.orders.orderStats
import ke.co.bethanyhouse.neema.feature.orders.pageOf
import ke.co.bethanyhouse.neema.feature.orders.statusColumns
import ke.co.bethanyhouse.neema.core.util.ScreenLife
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesStressFixtures
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Round 8 — Orders under a busy shop's load: a thousand orders through the
 * real ViewModel and the pure functions the screen derives its figures with,
 * plus the read de-duplication every sales screen now shares.
 */
class OrdersStressTest {
    @get:Rule val main = ClockedMainRule()
    @get:Rule val paparazzi = Paparazzi() // a layoutlib Context for the container

    private val fake = FakeNeema.withFixtures().also { SalesStressFixtures.install(it) }

    private fun ms(block: () -> Unit): Double { val t = System.nanoTime(); block(); return (System.nanoTime() - t) / 1e6 }

    @Test fun aThousandOrdersCountAndSumExactlyInOnePass() {
        val dash = dashboard(paparazzi.context, fake)
        OrdersViewModel(dash)
        val orders = dash.orders.value
        assertEquals(1_000, orders.size)
        val stats = orderStats(orders)
        // The web's per-card filters, done the slow way, must agree to the shilling.
        for (s in ORDER_STATUSES) {
            assertEquals(s, orders.count { it.status == s }, stats.counts[s])
            assertEquals(s, orders.filter { it.status == s }.sumOf { it.amount }, stats.revenueBy.getValue(s), 0.001)
        }
        assertEquals(250, stats.counts["pending"])
        assertEquals(orders.filter { it.status != "cancelled" }.sumOf { it.amount }, stats.revenue, 0.001)
    }

    @Test fun filterSearchAndPagingHoldAtAThousand() {
        val dash = dashboard(paparazzi.context, fake)
        val orders = dash.orders.value
        assertEquals(250, filterOrders(orders, "confirmed", "").size)
        // A phone number finds its order among a thousand (and its id finds it too).
        val wa = SalesStressFixtures.waId(637)
        assertTrue(filterOrders(orders, "all", wa).any { it.id == SalesStressFixtures.orderId(637) })
        assertEquals(listOf(SalesStressFixtures.orderId(637)), filterOrders(orders, "all", SalesStressFixtures.orderId(637)).map { it.id })
        // 1,000 rows are 67 pages of 15; the last holds 10; a page is never more than 15 rows.
        val pages = (orders.size + 14) / 15
        assertEquals(67, pages)
        assertEquals(10, pageOf(orders, pages, 15).size)
        assertEquals(orders.subList(15, 30).map { it.id }, pageOf(orders, 2, 15).map { it.id })
        assertTrue((1..pages).all { pageOf(orders, it, 15).size <= 15 })
        assertTrue("past the end is empty, never a crash", pageOf(orders, pages + 3, 15).isEmpty())
    }

    @Test fun derivingFiveThousandOrdersIsFast() {
        val dash = dashboard(paparazzi.context, fake)
        val base = dash.orders.value
        val many: List<Order> = (0 until 5).flatMap { k -> base.map { it.copy(id = "${it.id}-$k") } }
        assertEquals(5_000, many.size)
        repeat(3) { orderStats(many); filterOrders(many, "pending", "2547") } // warm the JIT
        val t = ms {
            orderStats(many)
            val f = filterOrders(many, "all", "clergy")
            pageOf(f, 3, 15)
            filterOrders(many, "delivered", "2547100")
        }
        assertTrue("5,000 orders derived in ${t}ms (budget 200)", t < 200)
    }

    /**
     * A pull, a catch-up (the socket came back) and a second pull pile up
     * while the list is still on the wire (a slow 3G link): one read runs,
     * the catch-up follows it — never two at once, never three.
     */
    @Test fun pilingRefreshesShareOneReadOnTheWire() {
        val dash = dashboard(paparazzi.context, fake)
        val vm = OrdersViewModel(dash)
        val before = fake.callsTo("GET", "/admin/orders").size
        val hold = fake.hang("GET", "/admin/orders")
        vm.refresh()
        assertTrue(vm.refreshing.value)
        vm.life.catchUpNow(); main.advance(ScreenLife.CATCH_UP_WINDOW_MS + 1)
        vm.refresh() // ignored: already refreshing
        assertEquals("only the first read is on the wire", 1, hold.waiting)
        hold.release()
        assertFalse(vm.refreshing.value)
        assertEquals("the running read plus one that follows it", before + 2, fake.callsTo("GET", "/admin/orders").size)
        assertEquals(1_000, dash.orders.value.size)
    }

    /** Catch-ups kicked again and again during a slow read queue behind it one at a time — they never stack up on the wire. */
    @Test fun repeatedCatchUpsNeverOverlap() {
        val dash = dashboard(paparazzi.context, fake)
        val vm = OrdersViewModel(dash)
        val before = fake.callsTo("GET", "/admin/orders").size
        val hold = fake.hang("GET", "/admin/orders")
        vm.refresh()
        repeat(5) { vm.life.catchUpNow(); main.advance(ScreenLife.CATCH_UP_WINDOW_MS + 1) }
        assertEquals("one read on the wire, whatever piles up", 1, hold.waiting)
        hold.release()
        // core's Coalescer queues each kick that lands during a run behind it
        // (one at a time), so these follow one by one — see the round-8 report.
        assertTrue(fake.callsTo("GET", "/admin/orders").size - before <= 6)
        assertFalse(vm.refreshing.value)
    }

    // The 4-up status cards break words at large text: 2-up (or 1-up) instead.
    @Test fun statusCardsGoTwoUpAtLargeTextOnATablet() {
        assertEquals("tablet portrait, default text", 4, statusColumns(900.dp, 24.dp, 1f))
        assertEquals("tablet portrait at 130%", 4, statusColumns(900.dp, 24.dp, 1.3f))
        assertEquals("tablet portrait at 200%: \"Confirmed\" would break", 2, statusColumns(900.dp, 24.dp, 2f))
        assertEquals("tablet landscape at 200%", 4, statusColumns(1280.dp, 24.dp, 2f))
        assertEquals("foldable", 4, statusColumns(600.dp, 24.dp, 1f))
        assertEquals("foldable at 130%", 2, statusColumns(600.dp, 24.dp, 1.3f))
        assertEquals("phone", 2, statusColumns(411.dp, 16.dp, 1f))
        assertEquals("phone at 200%", 1, statusColumns(411.dp, 16.dp, 2f))
    }
}

/** [SingleFlight] on its own: the contract every sales and calls read relies on. */
@OptIn(ExperimentalCoroutinesApi::class)
class SingleFlightTest {
    @Test fun callersDuringAReadShareTheNextOneAndNothingStacks() = runTest {
        val scope = CoroutineScope(StandardTestDispatcher(testScheduler))
        var runs = 0
        val gates = ArrayDeque<CompletableDeferred<Unit>>()
        val flight = SingleFlight(scope) {
            runs++
            CompletableDeferred<Unit>().also { gates.addLast(it) }.await()
            runs
        }
        val first = async { flight.run() }
        testScheduler.runCurrent()
        assertEquals(1, runs)
        assertTrue(flight.inFlight)
        // Fifty callers while the first read is on the wire.
        val piled = (1..50).map { async { flight.run() } }
        testScheduler.runCurrent()
        assertEquals("nothing else goes out while one is running", 1, runs)
        gates.removeFirst().complete(Unit)
        testScheduler.runCurrent()
        assertEquals(1, first.await())
        assertEquals("the piled-up callers get ONE fresh read, after the first", 2, runs)
        gates.removeFirst().complete(Unit)
        testScheduler.runCurrent()
        assertTrue(piled.all { it.await() == 2 })
        assertFalse(flight.inFlight)
        // Afterwards, a new caller starts a new read.
        val later = async { flight.run() }
        testScheduler.runCurrent()
        gates.removeFirst().complete(Unit)
        assertEquals(3, later.await())
    }

    @Test fun aFailedReadFailsItsCallersButNotTheNextRead() = runTest {
        val scope = CoroutineScope(kotlinx.coroutines.SupervisorJob() + StandardTestDispatcher(testScheduler))
        var n = 0
        val flight = SingleFlight(scope) { if (++n == 1) error("offline") else n }
        val failed = runCatching { flight.run() }
        assertTrue(failed.isFailure)
        assertEquals(2, flight.run())
    }
}
