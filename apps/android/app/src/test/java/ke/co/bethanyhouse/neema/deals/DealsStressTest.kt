package ke.co.bethanyhouse.neema.deals

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.model.Deal
import ke.co.bethanyhouse.neema.core.model.PlannedAction
import ke.co.bethanyhouse.neema.feature.deals.DealsViewModel
import ke.co.bethanyhouse.neema.feature.deals.groupByStage
import ke.co.bethanyhouse.neema.core.util.ScreenLife
import ke.co.bethanyhouse.neema.orders.ClockedMainRule
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.SalesStressFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Round 8 — the Deals queue at two hundred planned actions with live
 * updates: sends and vetoes one after another, a load that was already on
 * the wire when a send landed, a burst of notifications, and the board's
 * grouping at size.
 */
class DealsStressTest {
    @get:Rule val main = ClockedMainRule()
    @get:Rule val paparazzi = Paparazzi() // a layoutlib Context for the container

    private val fake = FakeNeema.withFixtures().also { SalesStressFixtures.install(it) }
    private val scopes = mutableListOf<CoroutineScope>()
    @After fun tearDown() = scopes.forEach { it.cancel() }

    /** The server's queue: what is still pending after the sends and vetoes it received. */
    private val resolved = mutableSetOf<String>()
    /** When set, the next GET /admin/actions answers this instead (an answer from before a send). */
    private var staleOnce: String? = null

    private fun serveTheQueue() {
        fake.on("GET", "/admin/actions") { _, _ ->
            staleOnce?.let { staleOnce = null; return@on 200 to it }
            200 to SalesStressFixtures.actionsJson((0 until 200).filter { SalesStressFixtures.actionId(it) !in resolved }.map(SalesStressFixtures::actionRow))
        }
        fake.on("POST", "/admin/actions/[^/]+/(approve|veto)") { r, _ ->
            resolved += r.url.pathSegments[r.url.pathSegments.size - 2]
            200 to """{"ok":true,"sent":"Hello 🙏"}"""
        }
    }

    private fun ids(list: List<PlannedAction>?) = list.orEmpty().map { it.id }

    @Test fun twoHundredActionsLoadInOrder() {
        serveTheQueue()
        val vm = DealsViewModel(dashboard(paparazzi.context, fake))
        assertEquals((0 until 200).map(SalesStressFixtures::actionId), ids(vm.actions.value))
        assertEquals("one read per resource on mount", 1, fake.callsTo("GET", "/admin/actions").size)
    }

    @Test fun sendingAndVetoingFiftyInARowSendsEachExactlyOnce() {
        serveTheQueue()
        val vm = DealsViewModel(dashboard(paparazzi.context, fake))
        val picked = (0 until 50).map { SalesStressFixtures.actionId(it * 4) }
        picked.forEachIndexed { i, id ->
            val verb = if (i % 2 == 0) "approve" else "veto"
            vm.act(id, verb)
        }
        val posts = fake.calls.filter { it.method == "POST" && it.path.startsWith("/admin/actions/") }
        assertEquals("one request per action", 50, posts.size)
        assertEquals(picked.toSet(), posts.map { it.path.split('/')[3] }.toSet())
        assertEquals(150, vm.actions.value!!.size)
        assertTrue(picked.none { it in ids(vm.actions.value) })
        assertTrue("nothing left locked", vm.acting.value.isEmpty())
    }

    /**
     * A load was already on the wire when a send landed; its (older) answer
     * arrives after. The sent follow-up must not come back with a live Send
     * button — not even for a frame — and the loads never overlap.
     */
    @Test fun aLoadFromBeforeASendNeverBringsTheSentActionBack() {
        serveTheQueue()
        val vm = DealsViewModel(dashboard(paparazzi.context, fake))
        val seen = mutableListOf<List<String>>()
        CoroutineScope(Dispatchers.Unconfined).also { scopes += it }.launch { vm.actions.collect { seen += ids(it) } }
        val target = SalesStressFixtures.actionId(3)
        val before = fake.callsTo("GET", "/admin/actions").size

        val hold = fake.hang("GET", "/admin/actions")
        vm.refresh() // the poll's read, now slow
        assertEquals(1, hold.waiting)
        staleOnce = SalesStressFixtures.actions(200) // the server answered before the send reached it
        vm.act(target, "approve")
        assertFalse(target in ids(vm.actions.value))
        val sentAt = seen.size
        assertEquals("the reload after the send waits for the read on the wire", 1, hold.waiting)
        hold.release()

        assertTrue("never shown again after the send", seen.drop(sentAt).none { target in it })
        assertFalse(target in ids(vm.actions.value))
        assertEquals(199, vm.actions.value!!.size)
        assertEquals("the slow read and one after the send — no third", before + 2, fake.callsTo("GET", "/admin/actions").size)
    }

    @Test fun aBurstOfTwoHundredNotificationsIsOneReload() {
        serveTheQueue()
        val ws = FakeSocketFactory()
        val dash = dashboard(paparazzi.context, fake, appDispatcher = Dispatchers.Unconfined, wsFactory = ws)
        dash.container.notifications.start(dash.container.foreground)
        dash.container.socket.connect(Fixtures.ME_ID)
        ws.last.open()
        DealsViewModel(dash)
        val before = fake.callsTo("GET", "/admin/actions").size
        repeat(200) { i ->
            ws.last.frame("""{"event":"notification","type":"${if (i % 2 == 0) "planned_action" else "hub_event"}","title":"Neema","body":"#$i"}""")
        }
        main.advance(ScreenLife.EVENT_WINDOW_MS + 1)
        assertEquals("200 frames, one reload", before + 1, fake.callsTo("GET", "/admin/actions").size)
    }

    @Test fun aDoubleTapWhileTheSendIsOnTheWireSendsOnce() {
        serveTheQueue()
        val vm = DealsViewModel(dashboard(paparazzi.context, fake))
        val id = SalesStressFixtures.actionId(0)
        val hold = fake.hang("POST", "/admin/actions/[^/]+/approve")
        repeat(5) { vm.act(id, "approve") }
        assertEquals(1, hold.waiting)
        assertTrue(id in vm.acting.value)
        hold.release()
        assertEquals(1, fake.calls.count { it.method == "POST" && it.path == "/admin/actions/$id/approve" })
        assertFalse(id in ids(vm.actions.value))
    }

    @Test fun groupingFiveThousandDealsIsOnePassAndKeepsOrder() {
        val deals = (0 until 5_000).map { i ->
            Deal(id = "d$i", customer = "C$i", stage = listOf("new", "qualified", "proposal", "negotiation", "")[i % 5], status = "open")
        }
        repeat(3) { groupByStage(deals) }
        val t = System.nanoTime()
        val g = groupByStage(deals)
        val ms = (System.nanoTime() - t) / 1e6
        assertTrue("grouped in ${ms}ms (budget 200)", ms < 200)
        assertEquals(listOf("new", "qualified", "proposal"), g.keys.toList())
        assertEquals("unknown stages land under New", 3_000, g.getValue("new").size)
        assertEquals(1_000, g.getValue("qualified").size)
        assertEquals((0 until 5_000).filter { it % 5 == 1 }.map { "d$it" }, g.getValue("qualified").map { it.id })
    }
}
