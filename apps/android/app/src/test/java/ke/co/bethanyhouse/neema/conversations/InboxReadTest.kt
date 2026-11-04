package ke.co.bethanyhouse.neema.conversations

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
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
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Opening a chat reads it (owner, 2026-11-04): "When someone opens a chat, the
 * counter should remove [it]. If there are 5 chats that are not open, it should
 * say 5." The badges drop the moment it opens, the server is told, and a chat
 * someone opens on another screen drops here too.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxReadTest {
    @get:Rule val paparazzi = Paparazzi()

    private val sched = TestCoroutineScheduler()
    private val scope = CoroutineScope(UnconfinedTestDispatcher(sched))
    private lateinit var fake: FakeNeema
    private val sockets = FakeSocketFactory()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        fake = FakeNeema.withFixtures().also(InboxFixtures::install)
        fake.on("GET", "/admin/conversations/summary", body = SUMMARY)
        fake.on("POST", "/admin/conversations/[^/]+/read", body = """{"ok":true}""")
    }

    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun live(): Pair<DashboardViewModel, ConversationsViewModel> {
        val dash = dashboard(paparazzi.context, fake, appDispatcher = UnconfinedTestDispatcher(sched), wsFactory = sockets)
        val vm = ConversationsViewModel(dash)
        dash.container.socket.connect(Fixtures.ME_ID)
        sockets.last.open()
        sched.runCurrent()
        return dash to vm
    }

    private fun frame(json: String) { sockets.last.frame(json); sched.runCurrent() }
    private fun advance(ms: Long) { sched.advanceTimeBy(ms); sched.runCurrent() }
    private fun ConversationsViewModel.row(id: String) = inbox.value.cache.getValue(id)
    private fun reads(id: String) = fake.callsTo("POST", "/admin/conversations/$id/read").size

    @Test fun openingAChat_dropsItFromEveryBadge_andTellsTheServer() {
        val (dash, vm) = live()
        assertEquals(1, vm.row("c2").unread)
        // The server's next count: what it will say once the read is saved.
        fake.on("GET", "/admin/conversations/summary", body = SUMMARY.replace("\"all\":5", "\"all\":4"))
        vm.select("c2")
        assertEquals(0, vm.row("c2").unread)
        assertEquals(1, reads("c2"))
        val s = dash.inboxSummary.value!!
        assertEquals(4, s.unreadChats?.get("all"))
    }

    @Test fun theOptimisticDrop_isOneChat_notTheMessages() {
        val (_, vm) = live()
        // The server is down: the count still drops at once — one chat, not its messages.
        fake.on("POST", "/admin/conversations/c2/read", code = 503, body = "{}")
        vm.select("c2")
        val s = vm.inbox.value.summary!!
        assertEquals(4, s.unread)
        assertEquals(4, s.unreadChats?.get("all"))
    }

    @Test fun theTabletsOwnFirstRow_isNotSomeoneOpeningIt() {
        val (_, vm) = live()
        vm.select("c2", openThread = false)
        assertEquals(0, reads("c2"))
    }

    @Test fun aColleagueOpeningIt_elsewhere_readsItHere() {
        val (_, vm) = live()
        assertEquals(1, vm.row("c2").unread)
        frame("""{"event":"inbox_read","type":"conversation_read","conversationId":"c2","by":"Grace"}""")
        assertEquals(0, vm.row("c2").unread)
    }

    @Test fun aMessageIntoTheOpenChat_isReadAsItArrives() {
        val (_, vm) = live()
        vm.select("c7")
        val before = reads("c7")
        frame("""{"type":"new_message","conversationId":"c7","direction":"inbound","sender":"user","text":"Hello again"}""")
        assertEquals(0, vm.row("c7").unread)
        advance(1_300)
        assertEquals(before + 1, reads("c7"))
    }

    private companion object {
        const val SUMMARY = """{"unread":5,"human":2,"yours":1,"unread_messages":{"all":37,"whatsapp":30,"messenger":7},"unread_chats":{"all":5,"whatsapp":4,"messenger":1},"tags":[]}"""
    }
}
