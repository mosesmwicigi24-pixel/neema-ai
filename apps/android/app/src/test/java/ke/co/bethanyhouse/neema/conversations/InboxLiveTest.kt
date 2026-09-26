package ke.co.bethanyhouse.neema.conversations

import ke.co.bethanyhouse.neema.core.util.AppClock

import android.net.Uri
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel
import ke.co.bethanyhouse.neema.feature.conversations.InboxApi
import ke.co.bethanyhouse.neema.feature.conversations.PickedMedia
import ke.co.bethanyhouse.neema.feature.conversations.sortThread
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 4 — the inbox stays live. Every conversation frame the backend
 * publishes (core/ws/LiveSocket.kt's list) is pushed through a real
 * [ke.co.bethanyhouse.neema.core.ws.LiveSocket] on a fake WebSocket, on
 * virtual time: the list rows move, badges refetch once per burst, the open
 * thread paints without duplicates, and anything missed while the socket was
 * down or the app was away is caught up without a pull-to-refresh.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxLiveTest {
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

    /** A signed-in inbox with its socket open. */
    private fun live(): Pair<DashboardViewModel, ConversationsViewModel> {
        val dash = dashboard(paparazzi.context, fake, appDispatcher = UnconfinedTestDispatcher(sched), wsFactory = sockets)
        scope.launch { dash.toasts.collect { toasts += it } }
        val vm = ConversationsViewModel(dash)
        dash.container.socket.connect(Fixtures.ME_ID)
        sockets.last.open()
        sched.runCurrent()
        return dash to vm
    }

    private fun frame(json: String) { sockets.last.frame(json); sched.runCurrent() }
    private fun advance(ms: Long) { sched.advanceTimeBy(ms); sched.runCurrent() }
    private fun listFetches() = fake.callsTo("GET", "/admin/conversations").size
    private fun threadFetches(id: String) = fake.callsTo("GET", "/admin/conversations/$id/messages").size
    private fun ConversationsViewModel.row(id: String) = inbox.value.cache.getValue(id)
    private fun ConversationsViewModel.msgs(id: String) = thread.value.messages[id].orEmpty()

    // ═══════════════ Rows move the moment a frame lands ═══════════════

    @Test fun newMessage_movesTheRowToTheTop_now_thenOneRefetchConfirms() {
        val (dash, vm) = live()
        val before = listFetches()
        assertNotEquals("c3", vm.rows.value.first().rep.id)
        frame("""{"type":"new_message","conversationId":"c3","sender":"user","text":"Nimefika — the photo is of the stole","waId":"255754333222"}""")
        // Live: top of the list, the preview and the unread count, with no request yet.
        assertEquals("c3", vm.rows.value.first().rep.id)
        assertEquals("Nimefika — the photo is of the stole", vm.row("c3").lastMessagePreview)
        assertEquals(1, vm.row("c3").unread)
        assertEquals(before, listFetches())
        // 1.5 s later the list and badges refetch — once.
        fake.on("GET", "/admin/conversations/summary", body = """{"unread":4,"human":2,"yours":1,"unread_messages":{"all":5,"whatsapp":4,"messenger":1},"tags":["bulk","clergy","vip"]}""")
        advance(1_500)
        assertEquals(before + 1, listFetches())
        assertEquals(4, dash.inboxSummary.value?.unread)
        assertEquals(4, vm.inbox.value.summary?.unread)
    }

    @Test fun outboundReply_zeroesUnread_likeTheServerCounts() {
        val (_, vm) = live()
        assertEquals(1, vm.row("c2").unread)
        frame("""{"type":"new_message","conversationId":"c2","sender":"ai","text":"The purple cassock is KES 12,500."}""")
        assertEquals(0, vm.row("c2").unread)
        assertEquals("The purple cassock is KES 12,500.", vm.row("c2").lastMessagePreview)
        // A media frame with no text keeps the last preview rather than blanking it.
        frame("""{"type":"new_message","conversationId":"c2","sender":"user","text":"","mediaType":"image","mediaUrl":"https://x/p.jpg"}""")
        assertEquals("The purple cassock is KES 12,500.", vm.row("c2").lastMessagePreview)
        assertEquals(1, vm.row("c2").unread)
    }

    /** Carry-over 1: web chat, ManyChat, TikTok and the Tier-2 agent's replies use `type:"message"`. */
    @Test fun legacyMessageFrame_paintsInTheOpenThread_andMovesTheRow() {
        val (_, vm) = live()
        vm.select("c7")
        val before = listFetches()
        // web_chat.py: direction but no sender — the customer.
        frame("""{"type":"message","conversationId":"c7","waId":"web_3fa9c1e20b7d4c5a9e11","direction":"inbound","text":"Hello from the website"}""")
        val m = vm.msgs("c7").last()
        assertEquals("Hello from the website", m.text); assertEquals("inbound", m.direction); assertEquals("user", m.sender)
        assertEquals("c7", vm.rows.value.first().rep.id)
        // n8n_bridge.save_outbound_message: the Tier-2 agent's WhatsApp reply.
        frame("""{"type":"message","conversationId":"c7","waId":"web_3fa9c1e20b7d4c5a9e11","direction":"outbound","text":"Yes — we ship to Kampala."}""")
        val r = vm.msgs("c7").last()
        assertEquals("outbound", r.direction); assertEquals("ai", r.sender)
        assertEquals(0, vm.row("c7").unread)
        advance(1_500)
        assertEquals(before + 1, listFetches())
        // The next poll brings the server rows; the live bubbles give way to them (no doubles).
        fake.on("GET", "/admin/conversations/c7/messages", body = """[
          {"id":"s1","type":"message","direction":"inbound","sender":"user","text":"Hello from the website","created_at":"${AppClock.instant()}"},
          {"id":"s2","type":"message","direction":"outbound","sender":"ai","text":"Yes — we ship to Kampala.","created_at":"${AppClock.instant()}"}]""")
        advance(20_000)
        assertEquals(listOf("s1", "s2"), vm.msgs("c7").filter { !it.isSystem }.map { it.id }.takeLast(2))
        assertEquals(2, vm.msgs("c7").count { it.text == "Hello from the website" || it.text == "Yes — we ship to Kampala." })
    }

    /** channel sends (Messenger/IG/FB) name the channel and the sender; a comment reply's reply_to is a comment id, not a quote. */
    @Test fun legacyChannelSend_withCommentReplyId_paintsPlainly() {
        val (_, vm) = live()
        vm.select("c2")
        frame("""{"type":"message","conversationId":"c2","channel":"messenger","sender":"ai","direction":"outbound","text":"Sent you a DM 🙏","reply_to":"cmt_1"}""")
        val m = vm.msgs("c2").last()
        assertEquals("Sent you a DM 🙏", m.text); assertNull(m.replyTo); assertEquals("ai", m.sender)
    }

    // ═══════════════ Bursts, duplicates, order ═══════════════

    @Test fun burst_ofFramesAcrossThreads_isOneRefetch_notAStorm() {
        val (_, vm) = live()
        vm.select("c1")
        advance(3_000) // opening cleared c1's badge; its quiet refresh has run
        val before = listFetches()
        repeat(30) { i ->
            val id = listOf("c1", "c2", "c3", "c4")[i % 4]
            frame("""{"type":"new_message","conversationId":"$id","sender":"user","text":"burst $i"}""")
            advance(40) // 30 frames over 1.2 s
        }
        assertEquals(before, listFetches())
        advance(300)
        assertEquals(before + 1, listFetches())
        // Frames still pouring in after it ran get their own single refetch.
        frame("""{"type":"intercept_changed","conversationId":"c2","mode":"human","assignedAgentId":"${Fixtures.AGENT2_ID}","assignedAgentName":"Grace Wanjiru","eventKind":"intercept","eventAgentName":"Grace Wanjiru"}""")
        frame("""{"type":"history_cleared","conversationId":"c4","clearedBy":"Grace"}""")
        advance(1_500)
        assertEquals(before + 2, listFetches())
        // Every c1 burst frame landed once, in order.
        assertEquals((0 until 30 step 4).map { "burst $it" }, vm.msgs("c1").filter { it.text?.startsWith("burst") == true }.map { it.text })
    }

    @Test fun duplicates_areDropped_butACustomersRepeatedOkIsKept() {
        val (_, vm) = live()
        vm.select("c1")
        val base = vm.msgs("c1").size
        // The AI reply carries the DB id: delivered twice, shown once.
        repeat(2) { frame("""{"type":"new_message","conversationId":"c1","id":"db-9","sender":"ai","text":"Friday works 🙏"}""") }
        // An id-less outbound relayed twice (both frame shapes for one send).
        frame("""{"type":"new_message","conversationId":"c1","sender":"ai","text":"Sending the M-Pesa details now"}""")
        frame("""{"type":"message","conversationId":"c1","direction":"outbound","text":"Sending the M-Pesa details now"}""")
        // The customer really did say "ok" twice.
        repeat(2) { frame("""{"type":"new_message","conversationId":"c1","sender":"user","text":"ok"}""") }
        val added = vm.msgs("c1").drop(base)
        assertEquals(listOf("Friday works 🙏", "Sending the M-Pesa details now", "ok", "ok"), added.map { it.text })
    }

    @Test fun outOfOrder_frameWithAnOlderTimestamp_sortsIntoPlace() {
        val (_, vm) = live()
        vm.select("c1")
        val t = AppClock.instant()
        frame("""{"type":"new_message","conversationId":"c1","id":"late","sender":"ai","text":"second","created_at":"$t"}""")
        frame("""{"type":"new_message","conversationId":"c1","id":"early","sender":"user","text":"first","created_at":"${t.minusSeconds(30)}"}""")
        val shown = sortThread(vm.msgs("c1")).map { it.id }
        assertTrue(shown.indexOf("early") < shown.indexOf("late"))
    }

    // ═══════════════ Threads that aren't open, rows not loaded ═══════════════

    @Test fun framesForAThreadThatIsNotOpen_touchOnlyItsRow() {
        val (_, vm) = live()
        vm.select("c2"); vm.select("c1") // c2's thread is cached, c1 is open
        val c1Before = vm.msgs("c1")
        val c2Before = vm.msgs("c2")
        val composerBefore = vm.composer.value
        frame("""{"type":"new_message","conversationId":"c2","sender":"user","text":"Are you open Saturday?"}""")
        frame("""{"type":"ai_draft_ready","conversationId":"c2","draft":"We are, 9–1."}""")
        frame("""{"type":"translations","conversationId":"c2","items":[{"id":"m1","text":"x","lang":"sw"}]}""")
        frame("""{"type":"intercept_changed","conversationId":"c2","eventKind":"escalated"}""")
        assertEquals(c1Before, vm.msgs("c1"))
        assertEquals(c2Before, vm.msgs("c2"))           // not painted into a closed thread (the web's rule)
        assertEquals(composerBefore, vm.composer.value) // another thread's draft is not this one's pill
        assertEquals("Are you open Saturday?", vm.row("c2").lastMessagePreview)
        // A clear on a cached-but-closed thread empties it, quietly.
        val toastsBefore = toasts.size
        frame("""{"type":"history_cleared","conversationId":"c2","clearedBy":"Grace"}""")
        assertTrue(vm.msgs("c2").isEmpty())
        assertNull(vm.row("c2").lastMessagePreview); assertEquals(0, vm.row("c2").unread)
        assertEquals(toastsBefore, toasts.size)
    }

    @Test fun frameForAConversationNotLoadedYet_appearsWithTheRefetch() {
        val (_, vm) = live()
        assertFalse("c99" in vm.inbox.value.cache)
        frame("""{"type":"new_message","conversationId":"c99","sender":"user","text":"Hello, new here"}""")
        // Nothing invented locally…
        assertFalse("c99" in vm.inbox.value.cache)
        assertTrue(vm.thread.value.messages["c99"] == null)
        // …the refetch brings the real row, on top.
        val newcomer = Fixtures.conv("c99", "Br. Paul Otieno", "254700111222", "whatsapp", "ai", "Hello, new here", 0, unread = 1)
        fake.on("GET", "/admin/conversations", body = """{"items":[$newcomer,${Fixtures.inbox.joinToString(",")}],"next_cursor":"cursor-2"}""")
        advance(1_500)
        assertEquals("c99", vm.rows.value.first().rep.id)
        assertEquals(1, vm.row("c99").unread)
    }

    @Test fun newRowOnASearch_waitsForTheServer() {
        val (_, vm) = live()
        fake.on("GET", "/admin/conversations") { r, _ ->
            200 to if (r.url.queryParameter("q") == "Peter") """{"items":[${Fixtures.inbox.first()}],"next_cursor":null}""" else Fixtures.conversationPage
        }
        vm.setSearch("Peter"); advance(301)
        assertEquals(listOf("c1"), vm.rows.value.map { it.rep.id })
        frame("""{"type":"new_message","conversationId":"c4","sender":"user","text":"albs?"}""")
        assertFalse(vm.rows.value.any { it.rep.id == "c4" })
    }

    // ═══════════════ Mode changes, drafts, translations, clears ═══════════════

    @Test fun interceptChanged_setsTheRowsModeAndOwner_andOnePillPerKind() {
        val (_, vm) = live()
        vm.select("c2")
        frame("""{"type":"intercept_changed","conversationId":"c2","mode":"human","assignedAgentId":"${Fixtures.ME_ID}","assignedAgentName":"Moses Mwicigi","eventKind":"intercept","eventAgentName":"Moses Mwicigi"}""")
        assertEquals("human", vm.row("c2").interceptMode); assertEquals(Fixtures.ME_ID, vm.row("c2").assignedAgentId)
        assertEquals("Moses Mwicigi", vm.row("c2").assignedAgentName)
        // The "Yours" tab counts it at once.
        vm.setTab("yours")
        frame("""{"type":"intercept_changed","conversationId":"c2","mode":"human","assignedAgentId":"${Fixtures.ME_ID}","eventKind":"intercept","eventAgentName":"Moses Mwicigi"}""")
        assertEquals(1, vm.msgs("c2").count { it.id.startsWith("live-evt-") && it.eventKind == "intercept" })
        // Released: no owner.
        frame("""{"type":"intercept_changed","conversationId":"c2","mode":"ai","assignedAgentId":null,"eventKind":"release","eventAgentName":"Moses Mwicigi"}""")
        assertEquals("ai", vm.row("c2").interceptMode); assertNull(vm.row("c2").assignedAgentId)
        // An AI escalation carries no mode: the row waits for the refetch, the pill shows now.
        frame("""{"type":"intercept_changed","conversationId":"c2","eventKind":"escalated","eventReason":"Asked for a custom quote"}""")
        assertEquals("ai", vm.row("c2").interceptMode)
        assertEquals("Escalated — needs human", vm.msgs("c2").last().text)
    }

    @Test fun aiDraft_showsAPill_notExpanded_andTranslationsFillInPlaceOnce() {
        val (_, vm) = live()
        vm.select("c1")
        frame("""{"type":"ai_draft_ready","conversationId":"c1","draft":"Yes Father, Friday works.","waId":"254712345678"}""")
        vm.composer.value.let { assertTrue(it.draftVisible); assertFalse(it.draftExpanded); assertEquals("Yes Father, Friday works.", it.draftText) }
        frame("""{"type":"translations","conversationId":"c1","items":[{"id":"m3","text":"Inchi 16, mbili nyeusi","lang":"sw"},{"id":"nope","text":"x","lang":null}]}""")
        val snap = vm.thread.value
        assertEquals("Inchi 16, mbili nyeusi", vm.msgs("c1").first { it.id == "m3" }.translation)
        // The same frame again changes nothing — not even the state object.
        frame("""{"type":"translations","conversationId":"c1","items":[{"id":"m3","text":"other","lang":"sw"}]}""")
        assertSame(snap, vm.thread.value)
    }

    @Test fun historyCleared_emptiesTheOpenThread_andTheRow() {
        val (_, vm) = live()
        vm.select("c1")
        frame("""{"type":"history_cleared","conversationId":"c1","clearedBy":"Grace Wanjiru"}""")
        assertTrue(vm.msgs("c1").isEmpty())
        assertNull(vm.row("c1").lastMessagePreview)
        assertEquals("History cleared by Grace Wanjiru", toasts.last().message)
    }

    // ═══════════════ Agent notifications ═══════════════

    @Test fun agentNotifications_neverPaintABubble_andOnlyAnSmsArrivalRefetchesHere() {
        val (_, vm) = live()
        vm.select("c1")
        advance(3_000)
        val base = vm.msgs("c1")
        val before = listFetches()
        // The shell (DashboardViewModel) refetches for these kinds; the inbox adds nothing.
        frame("""{"event":"notification","type":"intercept","title":"Picked up","body":"Grace took Fr. Peter","conversationId":"c1"}""")
        frame("""{"event":"notification","type":"draft_ready","title":"Draft ready","body":"…","conversationId":"c1"}""")
        advance(1_500)
        assertEquals(before, listFetches())
        // sms.py's `new_message` ping is not a thread frame, but it is a new message.
        frame("""{"event":"notification","type":"new_message","title":"New SMS","body":"Hello","conv_id":"c1"}""")
        advance(1_500)
        assertEquals(before + 1, listFetches())
        assertEquals(base, vm.msgs("c1"))
    }

    // ═══════════════ Missed events: reconnect and foreground ═══════════════

    @Test fun reconnect_catchesUpTheListAndTheOpenThread_once() {
        val (_, vm) = live()
        vm.select("c1")
        advance(5_000)
        val list0 = listFetches(); val thread0 = threadFetches("c1")
        // The socket drops; a message arrives server-side meanwhile and its frame is lost.
        sockets.last.fail()
        fake.on("GET", "/admin/conversations/c1/messages", body = Fixtures.messages.trimEnd().removeSuffix("]") +
            """,{"id":"missed","type":"message","direction":"inbound","sender":"user","text":"Did you get my photo?","created_at":"${AppClock.instant()}"}]""")
        advance(2_000) // LiveSocket reconnects after 2 s
        assertEquals(2, sockets.sockets.size)
        assertEquals(list0, listFetches())
        sockets.last.open(); sched.runCurrent()
        assertEquals(list0 + 1, listFetches())
        assertEquals(thread0 + 1, threadFetches("c1"))
        assertTrue(vm.msgs("c1").any { it.id == "missed" })
        // The app coming to the front right after is the same catch-up, not a second one.
        vm.dash.container.foreground.value = false; sched.runCurrent()
        vm.dash.container.foreground.value = true; sched.runCurrent()
        assertEquals(list0 + 1, listFetches())
    }

    @Test fun foregroundReturn_refetches_andPicksUpADraftWrittenMeanwhile() {
        val (dash, vm) = live()
        vm.select("c1") // human-held, mine; no draft yet
        assertFalse(vm.composer.value.draftVisible)
        advance(5_000)
        dash.container.foreground.value = false; sched.runCurrent()
        val list0 = listFetches(); val thread0 = threadFetches("c1")
        // Away for ten minutes: neither poll runs.
        fake.on("GET", "/admin/conversations/c1/latest-draft", body = """{"draft":"Father, Friday is confirmed 🙏"}""")
        advance(10 * 60_000L)
        assertEquals(list0, listFetches()); assertEquals(thread0, threadFetches("c1"))
        dash.container.foreground.value = true; sched.runCurrent()
        assertEquals(list0 + 1, listFetches())
        assertEquals(thread0 + 1, threadFetches("c1"))
        vm.composer.value.let { assertTrue(it.draftVisible); assertFalse(it.draftExpanded); assertEquals("Father, Friday is confirmed 🙏", it.draftText) }
        // The poll tick that fell due while away does not fetch a second time on return.
        advance(59_000)
        assertEquals(list0 + 1, listFetches())
    }

    @Test fun pollCadences_matchTheWeb_listEveryMinute_threadEvery20s() {
        val (_, vm) = live()
        vm.select("c2")
        advance(3_000)
        val list0 = listFetches(); val thread0 = threadFetches("c2")
        advance(20_000)
        assertEquals(thread0 + 1, threadFetches("c2"))
        advance(40_000)
        assertEquals(thread0 + 3, threadFetches("c2"))
        assertEquals(list0 + 1, listFetches())
    }

    @Test fun signedOut_noCatchUp() {
        val (dash, vm) = live()
        vm.select("c1")
        advance(5_000)
        dash.container.sessionStore.clear()
        val list0 = listFetches()
        dash.container.foreground.value = false; sched.runCurrent()
        dash.container.foreground.value = true; sched.runCurrent()
        advance(120_000)
        assertEquals(list0, listFetches())
    }

    // ═══════════════ Carry-over 3: attachments stream through the core UploadFile ═══════════════

    @Test fun upload_streamsTheFile_andResendsItWholeAfterATokenRefresh() = runBlocking {
        val file = java.io.File.createTempFile("measure", ".pdf").apply { writeText("%PDF-1.4 two black shirts, 16 inch") }
        var n = 0
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ ->
            if (n++ == 0) 401 to """{"detail":"Token expired"}""" else 200 to InboxFixtures.Contract.uploaded("document", "https://x/m.pdf", "Sizes")
        }
        // A new pair, not the same token string back (fakeJwt is per-second).
        fake.on("POST", "/(agent-auth|auth)/refresh") { _, _ -> 200 to Fixtures.tokenResponse(access = ke.co.bethanyhouse.neema.testing.fakeJwt(expiresInSec = 7_200)) }
        val dash = dashboard(paparazzi.context, fake)
        val item = PickedMedia("1", Uri.fromFile(file), "measure.pdf", "application/pdf", file.length(), caption = "Sizes")
        val msg = InboxApi(dash.api.http).upload(paparazzi.context.contentResolver, "c1", item)
        assertEquals("srv-u1", msg.id)
        val sent = fake.callsTo("POST", "/admin/conversations/c1/upload-media").map { it.body!! }
        assertEquals(2, sent.size)
        sent.forEach { b ->
            assertTrue(b, b.contains("filename=\"measure.pdf\"")); assertTrue(b, b.contains("Content-Type: application/pdf"))
            assertTrue(b, b.contains("%PDF-1.4 two black shirts, 16 inch"))
        }
        file.delete(); Unit
    }
}
