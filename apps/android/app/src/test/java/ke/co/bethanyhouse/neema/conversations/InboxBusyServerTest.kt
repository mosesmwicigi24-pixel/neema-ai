package ke.co.bethanyhouse.neema.conversations

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Owner, 2026-09-26: "The Facebook messages, Messenger and IG are not current"
 * on the phone — list, open chat and channel tab all a day old — while the web
 * was current.
 *
 * On the live server the inbox page takes seconds, and on a busy day a frame
 * (a customer's message, Neema's reply, a comment) lands every second or so.
 * Every frame scheduled a refresh 1.5 s later, and every refresh CANCELLED the
 * page request still on its way — so while traffic kept flowing no page ever
 * arrived, and the list (and every chat opened from it) stayed on the last
 * copy that had loaded. New Messenger/Instagram/Facebook threads, which only a
 * page brings in, never showed. A refresh now joins the one in flight and runs
 * once more after it; only a change of filter cancels.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxBusyServerTest {
    @get:Rule val paparazzi = Paparazzi()

    private val sched = TestCoroutineScheduler()
    private val scope = CoroutineScope(UnconfinedTestDispatcher(sched))
    private lateinit var fake: FakeNeema
    private val sockets = FakeSocketFactory()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        fake = FakeNeema.withFixtures().also(InboxFixtures::install)
    }

    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun live(): ConversationsViewModel {
        val dash = dashboard(paparazzi.context, fake, appDispatcher = UnconfinedTestDispatcher(sched), wsFactory = sockets)
        val vm = ConversationsViewModel(dash)
        dash.container.socket.connect(Fixtures.ME_ID)
        sockets.last.open()
        sched.runCurrent()
        return vm
    }

    private fun frame(json: String) { sockets.last.frame(json); sched.runCurrent() }
    private fun advance(ms: Long) { sched.advanceTimeBy(ms); sched.runCurrent() }

    /** Today's Messenger thread, on page one of the server's inbox. */
    private val newMessenger = """{"id":"m-today","wa_id":null,"external_id":"psid-778899","person_id":"p-today",""" +
        """"channel":"messenger","name":"Grace Wanjiru","intercept_mode":"ai","status":"open","unread":1,""" +
        """"last_message_at":"2026-09-25T09:00:30+00:00","last_message_preview":"Do you have the purple stole?",""" +
        """"created_at":"2026-09-25T09:00:30+00:00","tags":[]}"""

    private fun serveToday() {
        fake.on("GET", "/admin/conversations") { _, _ ->
            200 to """{"items":[$newMessenger,${InboxFixtures.conversations.joinToString(",")}],"next_cursor":null}"""
        }
    }

    @Test fun aSlowServerUnderSteadyTraffic_stillDeliversTheNewestPage() {
        val vm = live()
        assertTrue(vm.inbox.value.cache["m-today"] == null)
        // The live server: three seconds for a page, and today's Messenger thread on it.
        serveToday()
        fake.delay("GET", "/admin/conversations", 3_000)
        // A frame every second for half a minute (other threads moving).
        repeat(30) {
            frame("""{"type":"new_message","conversationId":"c2","sender":"ai","text":"Reply $it"}""")
            advance(1_000)
        }
        assertTrue("today's Messenger thread reached the list while traffic kept flowing",
            vm.rows.value.any { it.rep.id == "m-today" })
    }

    @Test fun refreshesDuringALoadJoinIt_andOneMoreRunsAfter_noneCancelled() {
        val vm = live()
        serveToday()
        fake.delay("GET", "/admin/conversations", 3_000)
        val before = fake.callsTo("GET", "/admin/conversations").size
        vm.refresh()          // starts a load
        advance(500)
        vm.refresh(); vm.refresh(); vm.refresh()   // three more ask while it is on its way
        advance(3_000)        // the first answers…
        assertTrue(vm.rows.value.any { it.rep.id == "m-today" })
        advance(3_500)        // …and exactly one follow-up runs for the three
        assertEquals(before + 2, fake.callsTo("GET", "/admin/conversations").size)
        advance(10_000)
        assertEquals("nothing further queued", before + 2, fake.callsTo("GET", "/admin/conversations").size)
    }

    @Test fun changingTheChannelTab_stillCancelsTheOldFiltersLoad() {
        val vm = live()
        fake.delay("GET", "/admin/conversations", 3_000)
        val before = fake.callsTo("GET", "/admin/conversations").size
        vm.refresh()
        advance(500)
        vm.setChannel("messenger")
        advance(3_500)
        // The fake records a request when it answers: an abandoned one never shows.
        val since = fake.callsTo("GET", "/admin/conversations").drop(before)
        assertTrue("the Messenger page was fetched", since.isNotEmpty())
        assertTrue("the unfiltered load was abandoned, not answered", since.all { it.params["channel"] == "messenger" })
    }
}
