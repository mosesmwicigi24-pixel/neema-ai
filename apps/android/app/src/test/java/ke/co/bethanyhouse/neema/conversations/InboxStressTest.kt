package ke.co.bethanyhouse.neema.conversations

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.conversations.*
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures.Contract
import ke.co.bethanyhouse.neema.testing.fixtures.InboxStressFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 8 — the inbox at the shop's real scale: 5,000 conversations in
 * cursor pages, a 2,000-message thread with photos and voice notes, bursts
 * of 200 socket frames into the list and the open thread, a search typed at
 * speed and a bulk release across 500 rows. Every test asserts correctness
 * under load (order, no duplicates, nothing dropped, bounded memory) and the
 * number of requests made; the pure merges are also timed, with generous
 * bounds so a slow CI machine never flakes.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxStressTest {
    @get:Rule val paparazzi = Paparazzi()

    private val sched = TestCoroutineScheduler()
    private val scope = CoroutineScope(UnconfinedTestDispatcher(sched))
    private lateinit var fake: FakeNeema
    private val sockets = FakeSocketFactory()
    private val toasts = mutableListOf<Toast>()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        fake = FakeNeema.withFixtures().also(InboxFixtures::install)
    }

    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun vm(live: Boolean = false): Pair<DashboardViewModel, ConversationsViewModel> {
        val dash = if (live) dashboard(paparazzi.context, fake, appDispatcher = UnconfinedTestDispatcher(sched), wsFactory = sockets)
        else dashboard(paparazzi.context, fake)
        scope.launch { dash.toasts.collect { toasts += it } }
        val vm = ConversationsViewModel(dash)
        if (live) {
            dash.container.socket.connect(Fixtures.ME_ID)
            sockets.last.open()
            sched.runCurrent()
        }
        return dash to vm
    }

    private fun frame(json: String) { sockets.last.frame(json); sched.runCurrent() }
    private fun advance(ms: Long) { sched.advanceTimeBy(ms); sched.runCurrent() }
    private fun gets(path: String) = fake.callsTo("GET", path).size

    private fun ConversationsViewModel.pageAll(max: Int = 500) {
        var n = 0
        while (inbox.value.hasMore && n++ < max) loadMore()
    }

    /** Median of five runs, in ms — a pure function, warmed up first. */
    private fun timeMs(block: () -> Unit): Double {
        repeat(2) { block() }
        return (0 until 5).map { val t = System.nanoTime(); block(); (System.nanoTime() - t) / 1e6 }.sorted()[2]
    }

    // ═══════════════ 5,000 conversations ═══════════════

    @Test fun inbox5000_pagesThroughInServerOrder_noDuplicates_onePerPage() {
        val server = InboxStressFixtures.Inbox(fake)
        val (_, vm) = vm()
        vm.pageAll()
        val ids = vm.inbox.value.orderIds
        assertEquals(5_000, ids.size)
        assertEquals(5_000, ids.toSet().size)
        assertEquals(server.ids, ids)
        // One request per page — page one, then 99 cursors, each asked for exactly once.
        assertEquals(100, server.cursors.size)
        assertEquals(server.cursors.size, server.cursors.toSet().size)
        assertFalse(vm.inbox.value.hasMore)
        // The same people on two channels are one row: 5,000 − 100 pairs.
        val rows = vm.rows.value
        assertEquals(4_900, rows.size)
        assertEquals(rows.size, rows.map { it.key }.toSet().size)
        // Newest first, all the way down.
        val times = rows.map { Fmt.millis(it.rep.lastMessageAt) ?: 0L }
        assertTrue(times.zipWithNext().all { (a, b) -> a >= b })
        // Every cached row is one the list can show (nothing orphaned or doubled).
        assertEquals(5_000, vm.inbox.value.cache.size)
    }

    @Test fun inbox5000_refreshWhileScrolledDeep_keepsEveryPage_andPutsPageOneOnTop() {
        val server = InboxStressFixtures.Inbox(fake)
        val (_, vm) = vm()
        vm.pageAll()
        server.bump("s4999", 4_999)
        val before = server.cursors.size
        vm.refresh()
        assertEquals("one request: page one only", before + 1, server.cursors.size)
        val ids = vm.inbox.value.orderIds
        assertEquals(5_000, ids.size)
        assertEquals(5_000, ids.toSet().size)
        assertEquals("s4999", ids.first())
        assertEquals("s4999", vm.rows.value.first().rep.id)
    }

    @Test fun inbox5000_searchTypedAtSpeed_isOneRequest() {
        val server = InboxStressFixtures.Inbox(fake)
        val (_, vm) = vm()
        val before = server.queries.size
        "purple cassock".forEachIndexed { i, _ -> vm.setSearch("purple cassock".substring(0, i + 1)); advance(80) }
        advance(300)
        val asked = server.queries.drop(before)
        assertEquals(listOf("purple cassock"), asked)
    }

    // ═══════════════ A burst of 200 socket frames ═══════════════

    @Test fun socketBurst200_listAndThreadStayExact_oneRefetch_oneWindowCheck() {
        InboxStressFixtures.Inbox(fake)
        val (_, vm) = vm(live = true)
        vm.pageAll(4) // 250 rows loaded: every frame below lands on a row on screen
        vm.select("s1")
        val listBefore = gets("/admin/conversations")
        val threadBefore = gets("/admin/conversations/s1/messages")
        val windowBefore = gets("/admin/conversations/s1/window")
        val threadIds = mutableListOf<String>()
        for (k in 0 until 200) {
            when (k % 4) {
                0 -> { frame(InboxStressFixtures.newMessage("s1", "live-$k", "burst $k")); threadIds += "live-$k" }
                1 -> frame(InboxStressFixtures.newMessage("s$k", "other-$k", "burst $k"))
                2 -> frame(InboxStressFixtures.interceptChanged("s$k", "human"))
                3 -> frame(InboxStressFixtures.typing("s1"))
            }
        }
        // A duplicate delivery of a frame already shown changes nothing.
        frame(InboxStressFixtures.newMessage("s1", "live-0", "burst 0"))
        val live = vm.thread.value.messages["s1"].orEmpty().filter { it.id.startsWith("live-") }.map { it.id }
        assertEquals("every frame, once, in arrival order", threadIds, live)
        // The last frame's conversation is on top, and every row moved exactly once.
        assertEquals("s197", vm.rows.value.first().rep.id)
        assertEquals(vm.rows.value.size, vm.rows.value.map { it.key }.toSet().size)
        assertEquals("human", vm.inbox.value.cache.getValue("s2").interceptMode)
        // Nothing was fetched during the burst…
        assertEquals(listBefore, gets("/admin/conversations"))
        assertEquals(threadBefore, gets("/admin/conversations/s1/messages"))
        // …then one list refetch and one window check for the whole burst.
        advance(1_500)
        assertEquals(listBefore + 1, gets("/admin/conversations"))
        assertEquals(windowBefore + 1, gets("/admin/conversations/s1/window"))
    }

    // ═══════════════ A 2,000-message thread ═══════════════

    @Test fun thread2000_olderPagesMergeInOrder_noDuplicates_onePerPage() {
        InboxStressFixtures.Inbox(fake)
        val t = InboxStressFixtures.Thread(fake, "s3")
        val (_, vm) = vm()
        vm.select("s3")
        var n = 0
        while (vm.thread.value.hasMore["s3"] == true && n++ < 100) vm.loadOlder()
        val msgs = vm.thread.value.messages["s3"].orEmpty()
        assertEquals(2_000 + t.events, msgs.size)
        assertEquals(msgs.size, msgs.map { it.id }.toSet().size)
        assertEquals(2_000, msgs.count { !it.isSystem })
        assertTrue(msgs.map { it.millis }.zipWithNext().all { (a, b) -> a <= b })
        // Page one, 39 older pages, and the empty page that says "that's all".
        assertEquals(41, t.befores.size)
        assertEquals(t.befores.size, t.befores.toSet().size)
        // The rendered rows: every message accounted for (albums fold photos in).
        val rows = buildThreadRows(sortThread(msgs), 0)
        assertEquals(rows.size, rows.map { it.key }.toSet().size)
    }

    @Test fun openThreads_keepABoundedCache() {
        InboxStressFixtures.Inbox(fake)
        val (_, vm) = vm()
        vm.pageAll(2)
        for (i in 0 until 40) vm.select("s$i")
        val cached = vm.thread.value.messages
        assertTrue("cached ${cached.size}", cached.size <= ConversationsViewModel.MAX_CACHED_THREADS)
        assertTrue("s39" in cached)
        // Reopening an evicted thread loads it again.
        vm.select("s0")
        assertTrue(vm.thread.value.messages["s0"].orEmpty().isNotEmpty())
    }

    // ═══════════════ Bulk select across hundreds of rows ═══════════════

    @Test fun bulk500_selectAll_releasesEachOnce() {
        InboxStressFixtures.Inbox(fake, total = 500, pairs = 0, mode = "human")
        fake.on("POST", "/admin/conversations/[^/]+/release", body = """{"ok":true,"mode":"ai"}""")
        val (_, vm) = vm()
        vm.pageAll()
        vm.enterSelect()
        vm.selectAllOrClear()
        assertEquals(500, vm.list.value.selected.size)
        assertEquals(500, vm.selectedHeldIds().size)
        vm.toggleRow("s7"); vm.toggleRow("s7")
        assertEquals(500, vm.list.value.selected.size)
        vm.releaseSelected()
        val posts = fake.calls.filter { it.method == "POST" && it.path.endsWith("/release") }.map { it.path }
        assertEquals(500, posts.size)
        assertEquals(500, posts.toSet().size)
        assertEquals("500 conversations released back to Neema", toasts.last().message)
        assertFalse(vm.list.value.selectMode)
    }

    // ═══════════════ The flake: refresh() must not hop threads ═══════════════

    /**
     * InboxContractTest.resolve_sendsKeyAndRef_andRevealsTheThread flaked: the
     * page-one snapshot was written on a hard-coded Dispatchers.IO, and under
     * the tests' unconfined Main the rest of refresh() — the open thread's
     * row fetch, and every collector that fetch woke (the deep-link combine
     * among them) — carried on on that IO thread, racing the test thread.
     * All of refresh() now runs on the container's I/O dispatcher: in tests,
     * synchronously, on the caller's thread.
     */
    @Test fun refresh_finishesOnTheCallersThread_beforeReturning() {
        fake.on("GET", "/admin/conversations/summary", body = Contract.summary)
        fake.on("GET", "/admin/conversations", body = Contract.page(Contract.peterWa))
        fake.on("GET", "/admin/conversations/resolve", body = Contract.resolved)
        val seen = java.util.concurrent.CopyOnWriteArrayList<Thread>()
        fake.on("GET", "/admin/conversations/k2") { _, _ -> seen += Thread.currentThread(); 200 to Contract.maryMsgr }
        val (dash, vm) = vm()
        dash.openConvKey.value = "+250788123456|BH-1042"
        assertEquals("k2", vm.thread.value.activeId)
        // k2 is open but not on page one: every refresh re-reads its row.
        repeat(20) {
            val n = seen.size
            vm.refresh()
            assertEquals("the open thread's row was re-read before refresh() returned", n + 1, seen.size)
        }
        assertTrue(seen.all { it === Thread.currentThread() })
        assertTrue("k2" in vm.inbox.value.orderIds)
    }

    // ═══════════════ Pure functions, timed ═══════════════

    private fun conv(i: Int): String = InboxStressFixtures.row(i, (i + 1).toLong())

    @Test fun groupRows5000_isFast() {
        val convs = (0 until 5_000).map { Json.parseToJsonElement(conv(it)) }.map { conversationOf(it)!!.normalized() }
        val s = InboxUi(cache = convs.associateBy { it.id }, orderIds = convs.map { it.id })
        val rows = groupRows(s, Fixtures.ME_ID)
        assertEquals(4_900, rows.size)
        val ms = timeMs { groupRows(s, Fixtures.ME_ID) }
        assertTrue("grouping 5,000 rows took $ms ms", ms < 200)
        // A filter over them too (the Human tab).
        val human = groupRows(s.copy(filters = s.filters.copy(tab = "human"), orderKey = filterKeyOf(s.filters.copy(tab = "human"))), Fixtures.ME_ID)
        assertTrue(human.isNotEmpty() && human.all { g -> g.siblings.all { it.interceptMode == "human" } })
    }

    private fun thread(n: Int): List<ThreadMsg> {
        val f = FakeNeema.withFixtures()
        val t = InboxStressFixtures.Thread(f, "x", total = n)
        return t.json.map { ke.co.bethanyhouse.neema.core.net.NeemaJson.decodeFromString(ThreadMsg.serializer(), it) }
    }

    @Test fun mergeThread2000_andAppend200Frames_areFastAndExact() {
        val all = thread(2_050)
        val existing = all.take(all.size - 50)
        val incoming = all.takeLast(60) // overlaps 10, adds 50
        val merged = mergeThread(existing, incoming)
        assertEquals(all.size, merged.size)
        assertEquals(all.map { it.id }, merged.map { it.id })
        assertTrue("merge took", timeMs { mergeThread(existing, incoming) } < 200)
        assertTrue("server merge took", timeMs { mergeServer(existing, incoming) } < 200)
        // 200 socket frames appended one by one onto the 2,000 (each deduped against the thread).
        val frames = (0 until 200).map { k -> ThreadMsg(id = "live-$k", direction = "inbound", sender = "user", text = "burst $k", createdAt = nowIso()) }
        var out = existing
        val ms = timeMs { var t = existing; for (f in frames) t = appendWs(t, f); out = t }
        assertEquals(existing.size + 200, out.size)
        assertTrue("200 appends onto 2,000 took $ms ms", ms < 200)
    }

    @Test fun threadRows2000_areFast_withAlbumsAndEvents() {
        val msgs = thread(2_000)
        val ms = timeMs { buildThreadRows(sortThread(msgs), 12) }
        assertTrue("building 2,000 rows took $ms ms", ms < 200)
        val rows = buildThreadRows(sortThread(msgs), 12)
        assertTrue(rows.any { it is TBubble && it.album != null })
        assertEquals(1, rows.count { it is TNewDivider })
    }

    @Test fun waText_longMessage_isFast_andKeepsEveryLink() {
        val text = InboxStressFixtures.longMessage(200)
        val out = formatWa(text)
        assertFalse(out.text.contains("*Item"))
        assertEquals(400, out.getLinkAnnotations(0, out.length).size)
        val ms = timeMs { formatWa(text) }
        assertTrue("formatting ${text.length} chars took $ms ms", ms < 200)
    }
}
