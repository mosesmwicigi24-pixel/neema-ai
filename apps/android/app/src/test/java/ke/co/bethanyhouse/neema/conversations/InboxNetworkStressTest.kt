package ke.co.bethanyhouse.neema.conversations

import android.net.Uri
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.conversations.*
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures.dropped
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures.offline
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures.row
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures.timeout
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 5 — errors and network stress. Every load and every action of the
 * inbox and the thread against a server that times out, can't be reached,
 * drops the connection halfway, answers 401/403/404/409/422/429/5xx or
 * garbage — with the rule above all: a sent message is never duplicated and
 * never falsely reported as failed, and what the agent typed is never lost.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxNetworkStressTest {
    @get:Rule val paparazzi = Paparazzi()

    private val sched = TestCoroutineScheduler()
    private val scope = CoroutineScope(UnconfinedTestDispatcher(sched))
    private lateinit var fake: FakeNeema
    private lateinit var server: InboxNetFixtures.Server
    private val toasts = mutableListOf<Toast>()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        fake = FakeNeema.withFixtures().also(InboxFixtures::install)
        server = InboxNetFixtures.Server(fake)
    }

    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private class Owner : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }

    private fun vm(owner: Owner = Owner()): Pair<DashboardViewModel, ConversationsViewModel> {
        val dash = dashboard(paparazzi.context, fake)
        scope.launch { dash.toasts.collect { toasts += it } }
        val vm = ViewModelProvider.create(owner, viewModelFactory { initializer { ConversationsViewModel(dash) } })[ConversationsViewModel::class]
        return dash to vm
    }

    private fun idle(ms: Long) { sched.advanceTimeBy(ms); sched.runCurrent() }
    private fun posts(path: String) = fake.calls.filter { it.method == "POST" && it.path == path }
    private fun thread(vm: ConversationsViewModel, id: String = "c1") = vm.thread.value.messages[id].orEmpty()
    private fun mine(vm: ConversationsViewModel, id: String = "c1") = thread(vm, id).filter { it.id.startsWith("optimistic-") }
    private fun errors() = toasts.filter { it.type == ToastType.Error }
    private fun bodyText(path: String) = posts(path).last().body!!.let { Json.parseToJsonElement(it).jsonObject["text"]!!.jsonPrimitive.content }

    /** The reply route: [before] runs first (store the row, switch threads…), then [answer] decides. */
    private fun replyRoute(conv: String = "c1", answer: () -> Pair<Int, String>) =
        fake.on("POST", "/admin/conversations/$conv/reply") { _, _ -> answer() }

    // ═══════════════════ What a failure means ═══════════════════

    @Test fun fate_classifiesEveryFailure() {
        fun api(code: Int, body: String) = ke.co.bethanyhouse.neema.core.net.ApiException(code, "POST", "/x", body)
        assertEquals(Fate.Unknown, fateOf(api(0, "timed out after 30s")))
        assertEquals(Fate.Unknown, fateOf(api(0, "unexpected end of stream on https://neema.test/...")))
        assertEquals(Fate.NotSent, fateOf(api(0, "Failed to connect to neema.test/10.0.0.1:443")))
        assertEquals(Fate.NotSent, fateOf(api(0, "Unable to resolve host \"neema.test\": No address associated with hostname")))
        for (c in listOf(500, 502, 503, 504)) assertEquals("$c", Fate.Unknown, fateOf(api(c, "x")))
        for (c in listOf(400, 401, 403, 404, 409, 413, 415, 422, 429)) assertEquals("$c", Fate.NotSent, fateOf(api(c, "x")))
        assertEquals(Fate.NotSent, fateOf(NotDelivered("window closed")))
        assertEquals(Fate.Done, fateOf(kotlinx.serialization.SerializationException("bad body")))
        // The words: plain for transport trouble, the server's own when written for people, never HTML.
        assertEquals("Neema's server is unavailable right now — try again shortly.", whyFailed(api(502, "<html>Bad Gateway</html>"), "F"))
        assertEquals("F", whyFailed(api(403, "<html>Forbidden</html>"), "F", useDetail = true))
        assertEquals("F", whyFailed(api(422, """{"detail":[{"msg":"Field required"}]}"""), "F", useDetail = true))
        assertEquals("Nope.", whyFailed(api(409, """{"detail":"Nope."}"""), "F", useDetail = true))
        assertTrue(conversationGone(api(404, """{"detail":"Conversation not found"}""")))
        assertFalse(conversationGone(api(404, """{"detail":"Not Found"}""")))   // a route the server lacks
    }

    // ═══════════════════ Reply: timeout — the critical rule ═══════════════════

    /** The reply reached the customer but the answer was lost: one bubble, confirmed, never "failed". */
    @Test fun reply_timesOut_butWasDelivered_isConfirmedByRefetch_neverDuplicated() {
        replyRoute { server.rows += row("srv-r1", "On its way Friday"); timeout() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("On its way Friday"); vm.sendReply()
        // At once: the box is free and the bubble says "sending…" — nothing claims failure.
        assertEquals("", vm.composer.value.replyText)
        assertEquals("sending", mine(vm).single().sendState)
        assertTrue(errors().isEmpty())
        idle(2_100)
        val all = thread(vm)
        assertEquals(1, all.count { it.body == "On its way Friday" })
        assertEquals("srv-r1", all.last().id)
        assertTrue(mine(vm).isEmpty())
        assertEquals(1, posts("/admin/conversations/c1/reply").size)
        assertTrue(errors().isEmpty())
    }

    /** It never reached the server: after the checks it turns "Not sent" with Retry, and Retry sends it once. */
    @Test fun reply_timesOut_andWasNotDelivered_turnsNotSent_thenRetrySendsItOnce() {
        replyRoute { timeout() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Shall I send the M-Pesa details?"); vm.sendReply()
        idle(2_100); idle(8_000)
        assertEquals("sending", mine(vm).single().sendState)   // still checking — not failed yet
        assertTrue(errors().isEmpty())
        idle(20_000)
        val failed = mine(vm).single()
        assertEquals("failed", failed.sendState)
        assertEquals("Shall I send the M-Pesa details?", failed.body)   // the words are all there
        assertNotNull(failed.sendError)
        assertTrue(errors().last().message.contains("Tap Retry", ignoreCase = true))

        replyRoute { server.rows += row("srv-r2", "Shall I send the M-Pesa details?"); 200 to """{"ok":true}""" }
        vm.retrySend(failed.id)
        assertEquals(2, posts("/admin/conversations/c1/reply").size)
        assertEquals(1, thread(vm).count { it.body == "Shall I send the M-Pesa details?" })
        assertTrue(mine(vm).isEmpty())
    }

    /** It turned up on the server after all: Retry finds it and does NOT send it a second time. */
    @Test fun reply_retryOfATimedOutSend_findsItOnTheServer_andNeverSendsTwice() {
        replyRoute { timeout() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Asante Father"); vm.sendReply()
        idle(31_000)
        val failed = mine(vm).single()
        assertEquals("failed", failed.sendState)
        server.rows += row("srv-late", "Asante Father")   // the slow server finished delivering it
        vm.retrySend(failed.id)
        assertEquals(1, posts("/admin/conversations/c1/reply").size)
        assertEquals(1, thread(vm).count { it.body == "Asante Father" })
        assertEquals("It had already gone through — not sent twice.", toasts.last().message)
    }

    /** A later poll that brings the row settles even a "Not sent" bubble — it did go. */
    @Test fun reply_failedBubble_isReplacedWhenThePollBringsTheRealRow() {
        replyRoute { timeout() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Late but sent"); vm.sendReply()
        idle(31_000)
        assertEquals("failed", mine(vm).single().sendState)
        server.rows += row("srv-poll", "Late but sent")
        vm.loadMessages("c1", silent = true)
        assertEquals(1, thread(vm).count { it.body == "Late but sent" })
        assertTrue(mine(vm).isEmpty())
    }

    /** The checks themselves can't reach the server: stay "sending…" — then the next good read settles it. */
    @Test fun reply_timesOut_andTheChecksAreOffline_staysSending_untilAReadSucceeds() {
        replyRoute { timeout() }
        val (_, vm) = vm()
        vm.select("c1")
        server.threadDown = { offline() }
        vm.setReplyText("Karibu"); vm.sendReply()
        idle(31_000)
        assertEquals("sending", mine(vm).single().sendState)
        assertTrue(errors().none { it.message.contains("Karibu") || it.message.contains("Retry") })
        // Back online (the catch-up / 20 s poll): the server never got it → Not sent, with Retry.
        server.threadDown = null
        vm.loadMessages("c1", silent = true)
        assertEquals("failed", mine(vm).single().sendState)
        assertEquals("Karibu", mine(vm).single().body)
    }

    /** A connection that drops mid-answer is "maybe": checked, never reported failed while it was delivered. */
    @Test fun reply_droppedConnection_and502_and500_areAllCheckedBeforeAnyVerdict() {
        val (_, vm) = vm()
        vm.select("c1")
        for ((i, fail) in listOf<() -> Pair<Int, String>>(
            { dropped() },
            { 502 to "<html><body>502 Bad Gateway</body></html>" },
            { 500 to "Internal Server Error" },
        ).withIndex()) {
            val text = "Reply $i"
            replyRoute { server.rows += row("srv-x$i", text); fail() }
            vm.setReplyText(text); vm.sendReply()
            assertEquals("sending", mine(vm).single().sendState)
            idle(2_100)
            assertEquals(1, thread(vm).count { it.body == text })
            assertTrue(mine(vm).isEmpty())
        }
        assertTrue(errors().isEmpty())
        assertTrue(toasts.none { it.message.contains("<html") })
    }

    // ═══════════════════ Reply: definite failures ═══════════════════

    /** No connection at all: it never left the phone — the words go straight back in the box, and it says why. */
    @Test fun reply_offline_textBackInTheBox_andAPlainReason() {
        replyRoute { offline() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Habari"); vm.sendReply()
        assertEquals("Habari", vm.composer.value.replyText)
        assertTrue(mine(vm).isEmpty())
        assertEquals("No connection — check your internet and try again.", errors().last().message)
    }

    @Test fun reply_eachStatus_getsTheRightWords_andTheTextSurvives() {
        val (_, vm) = vm()
        vm.select("c1")
        for ((code, body, said) in listOf(
            Triple(403, "<html><h1>403 Forbidden</h1></html>", "Failed to send message"),
            Triple(422, """{"detail":[{"loc":["body","text"],"msg":"Field required","type":"missing"}]}""", "Failed to send message"),
            Triple(429, """{"detail":"Too Many Requests"}""", "Too many requests — wait a moment and try again."),
            Triple(400, """{"detail":"SMS is receive-only — Neema cannot send SMS. Reach this customer on WhatsApp or by phone."}""",
                "SMS is receive-only — Neema cannot send SMS. Reach this customer on WhatsApp or by phone."),
        )) {
            replyRoute { code to body }
            vm.setReplyText("Hi $code"); vm.sendReply()
            assertEquals(said, errors().last().message)
            assertEquals("Hi $code", vm.composer.value.replyText)
            vm.setReplyText("")
        }
        assertTrue(toasts.none { it.message.contains("<") || it.message.contains("loc") })
    }

    /** 409: someone else holds it — the reason, the current truth fetched, the words kept. */
    @Test fun reply_409_showsWhoHoldsIt_refetchesTheRow_andKeepsTheText() {
        replyRoute { 409 to """{"detail":"Conversation is handled by Grace Wanjiru."}""" }
        var got = 0
        fake.on("GET", "/admin/conversations/c1") { _, _ -> got++; 200 to InboxFixtures.conversations.first { it.contains("\"id\":\"c1\"") } }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Mine now?"); vm.sendReply()
        assertEquals("Conversation is handled by Grace Wanjiru.", errors().last().message)
        assertEquals("Mine now?", vm.composer.value.replyText)
        assertTrue(got >= 1)
    }

    /** 404: someone deleted the conversation — it leaves the list and the agent is told. */
    @Test fun reply_404_conversationDeleted_isRemovedAndSaid() {
        replyRoute { 404 to """{"detail":"Conversation not found"}""" }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Hello?"); vm.sendReply()
        assertFalse("c1" in vm.inbox.value.cache)
        assertEquals("", vm.thread.value.activeId)
        assertTrue(toasts.last().message.contains("deleted"))
    }

    /** 200 {ok:false}: the channel refused — never "sent", never silent. */
    @Test fun reply_okFalse_andA2xxWithGarbage() {
        val (_, vm) = vm()
        vm.select("c1")
        replyRoute { 200 to """{"ok":false,"error":"Couldn't send the reply: page token expired"}""" }
        vm.setReplyText("One"); vm.sendReply()
        assertEquals("One", vm.composer.value.replyText)
        assertEquals("Couldn't send the reply: page token expired", errors().last().message)
        // A 2xx whose body is not JSON at all is still a delivered reply.
        replyRoute { server.rows += row("srv-g", "One"); 200 to "<html>ok</html>" }
        vm.sendReply()
        assertEquals("", vm.composer.value.replyText)
        assertEquals(1, thread(vm).count { it.body == "One" })
    }

    // ═══════════════════ 401 mid-send ═══════════════════

    @Test fun reply_401_refreshesTheTokenSilently_andSendsOnce() {
        var n = 0
        replyRoute { if (n++ == 0) 401 to """{"detail":"Token expired"}""" else { server.rows += row("srv-a", "After refresh"); 200 to """{"ok":true}""" } }
        // A genuinely NEW access token (the default fixture could mint the very same string in the same second).
        fake.on("POST", "/(agent-auth|auth)/refresh", body = ke.co.bethanyhouse.neema.testing.Fixtures.tokenResponse(access = ke.co.bethanyhouse.neema.testing.fakeJwt(expiresInSec = 300L * 24 * 3600)))
        val (dash, vm) = vm()
        vm.select("c1")
        vm.setReplyText("After refresh"); vm.sendReply()
        assertFalse(dash.sessionExpired.value)
        assertEquals(1, thread(vm).count { it.body == "After refresh" })
        assertTrue(mine(vm).isEmpty())
        assertTrue(errors().isEmpty())
        assertTrue(fake.called("POST", "/auth/refresh") || fake.called("POST", "/agent-auth/refresh"))
    }

    @Test fun reply_401_andTheRefreshFails_sessionExpiredDialog_andTheWordsWaitInTheBox() {
        replyRoute { 401 to """{"detail":"Token expired"}""" }
        fake.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val (dash, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Please keep me"); vm.sendReply()
        assertTrue(dash.sessionExpired.value)
        assertEquals("Please keep me", vm.composer.value.replyText)
        // Signed back in: the same screen, the same words — one tap sends them.
        fake.on("POST", "/(agent-auth|auth)/refresh", body = ke.co.bethanyhouse.neema.testing.Fixtures.tokenResponse())
        replyRoute { server.rows += row("srv-b", "Please keep me"); 200 to """{"ok":true}""" }
        dash.onReauthenticated()
        vm.sendReply()
        assertEquals(1, thread(vm).count { it.body == "Please keep me" })
    }

    // ═══════════════════ Impatient users, moving on ═══════════════════

    @Test fun doubleTapSend_sendsOnce() {
        replyRoute { timeout() }   // the slowest case: still in flight on the second tap
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Once"); vm.sendReply(); vm.sendReply(); vm.sendReply()
        assertEquals(1, posts("/admin/conversations/c1/reply").size)
        assertEquals(1, mine(vm).size)
    }

    /** Switching threads mid-send: the answer lands on the thread it belongs to; the new thread's box is untouched. */
    @Test fun switchingThreadsMidSend_theResultLandsOnTheRightThread() {
        lateinit var vmRef: ConversationsViewModel
        replyRoute {
            // The agent moved on to Mary and started typing while this was in flight.
            vmRef.select("c2"); vmRef.setReplyText("For Mary")
            422 to """{"detail":"text is required"}"""
        }
        val (_, vm) = vm(); vmRef = vm
        vm.select("c1")
        vm.setReplyText("For Peter"); vm.sendReply()
        assertEquals("c2", vm.thread.value.activeId)
        assertEquals("For Mary", vm.composer.value.replyText)          // never overwritten
        assertTrue(mine(vm, "c2").isEmpty())                          // nothing landed on Mary
        val failed = mine(vm, "c1").single()                           // Peter's words wait on Peter's thread
        assertEquals("failed", failed.sendState); assertEquals("For Peter", failed.body)
        assertTrue(errors().last().message.startsWith("Reply to Fr. Peter Kamau not sent"))
        // Back on Peter: Edit puts the words back in HIS box.
        vm.select("c1")
        assertEquals("", vm.composer.value.replyText)
        vm.editFailed(failed.id)
        assertEquals("For Peter", vm.composer.value.replyText)
        assertTrue(mine(vm).isEmpty())
        vm.select("c2")
        assertEquals("For Mary", vm.composer.value.replyText)
    }

    /** Each customer keeps their own composer: Peter's half-typed reply never shows in Mary's box. */
    @Test fun composerTextBelongsToItsCustomer() {
        val (_, vm) = vm()
        vm.select("c1"); vm.setReplyText("Peter's words")
        vm.select("c2")
        assertEquals("", vm.composer.value.replyText)
        vm.setReplyText("Mary's words")
        vm.select("c1")
        assertEquals("Peter's words", vm.composer.value.replyText)
        // Peter's Facebook thread (same person) shares his box — a WhatsApp quote can be answered there.
        vm.select("c5")
        assertEquals("Peter's words", vm.composer.value.replyText)
    }

    // ═══════════════════ Approve and note ═══════════════════

    @Test fun approve_timesOut_butWasSent_confirmedOnce_andNeverResent() {
        fake.on("POST", "/admin/conversations/c1/approve-draft") { _, _ -> server.rows += row("srv-ai", "Yes Father", sender = "ai"); timeout() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setDraftText("Yes Father"); vm.approveDraft(); vm.approveDraft()
        assertEquals(1, posts("/admin/conversations/c1/approve-draft").size)
        assertTrue(errors().isEmpty())
        idle(2_100)
        assertEquals(1, thread(vm).count { it.body == "Yes Father" })
        assertEquals("AI draft approved & sent", toasts.last().message)
        assertFalse(vm.composer.value.draftVisible)
    }

    @Test fun approve_offline_draftComesBack() {
        fake.on("POST", "/admin/conversations/c1/approve-draft") { _, _ -> offline() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setDraftText("Keep this draft"); vm.approveDraft()
        assertTrue(vm.composer.value.draftVisible && vm.composer.value.draftExpanded)
        assertEquals("Keep this draft", vm.composer.value.draftText)
        assertEquals("Failed to approve draft. No connection — check your internet and try again.", errors().last().message)
    }

    @Test fun note_timesOut_butWasSaved_notSavedTwice_andNoDialogBack() {
        fake.on("POST", "/admin/conversations/c1/note") { _, _ -> server.rows += row("srv-n", "Repeat buyer", note = true); timeout() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.showNote(true); vm.setNoteText("Repeat buyer"); vm.saveNote()
        assertFalse(vm.dialogs.value.note)
        assertEquals("sending", mine(vm).single().sendState)
        assertTrue(toasts.none { it.message == "Note saved" })   // not claimed before the server says so
        idle(2_100)
        assertEquals(1, thread(vm).count { it.body == "Repeat buyer" && it.isNote })
        assertEquals("Note saved", toasts.last().message)
        assertEquals(1, posts("/admin/conversations/c1/note").size)
        assertFalse(vm.dialogs.value.note)
    }

    @Test fun note_offline_backInItsDialog() {
        fake.on("POST", "/admin/conversations/c1/note") { _, _ -> offline() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.showNote(true); vm.setNoteText("Measurements next week"); vm.saveNote()
        assertTrue(vm.dialogs.value.note)
        assertEquals("Measurements next week", vm.dialogs.value.noteText)
        assertEquals("Failed to save note. No connection — check your internet and try again.", errors().last().message)
    }

    // ═══════════════════ Generate draft (the long client) ═══════════════════

    @Test fun generateDraft_timeout_saysSo_andTheButtonComesBack() {
        fake.on("POST", "/admin/conversations/c1/generate-draft") { _, _ -> timeout() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.generateDraft()
        assertFalse(vm.composer.value.generatingDraft)
        assertEquals("Failed to generate draft. No answer from the server — the connection is too slow right now.", errors().last().message)
    }

    @Test fun generateDraft_landsOnTheThreadThatAskedForIt() {
        lateinit var vmRef: ConversationsViewModel
        fake.on("POST", "/admin/conversations/c1/generate-draft") { _, _ ->
            vmRef.select("c2")
            200 to """{"draft":"Yes Father — Friday."}"""
        }
        val (_, vm) = vm(); vmRef = vm
        vm.select("c1"); vm.generateDraft()
        assertFalse(vm.composer.value.draftVisible)       // not in Mary's box
        assertEquals("Draft ready for Fr. Peter Kamau — open their chat to review it.", toasts.last().message)
        vm.select("c1")
        assertTrue(vm.composer.value.draftVisible && vm.composer.value.draftExpanded)
        assertEquals("Yes Father — Friday.", vm.composer.value.draftText)
        assertFalse(vm.composer.value.generatingDraft)
    }

    // ═══════════════════ Loads ═══════════════════

    @Test fun list_offline_keepsTheRows_saysWhy_andRetryRecovers() {
        val (_, vm) = vm()
        assertEquals(6, vm.rows.value.size)
        fake.on("GET", "/admin/conversations") { _, _ -> offline() }
        vm.refresh()
        vm.inbox.value.let {
            assertTrue(it.loadError); assertFalse(it.loading)
            assertEquals("No connection — check your internet and try again.", it.errorText)
        }
        assertEquals(6, vm.rows.value.size)                  // cached rows stay
        fake.on("GET", "/admin/conversations", body = InboxFixtures.page)
        vm.refresh()
        assertFalse(vm.inbox.value.loadError); assertNull(vm.inbox.value.errorText)
    }

    @Test fun list_eachFailure_getsPlainWords_neverRawHtml() {
        val (_, vm) = vm()
        for ((reply, said) in listOf<Pair<() -> Pair<Int, String>, String>>(
            { timeout() } to "No answer from the server — the connection is too slow right now.",
            { 503 to "<html><body>Service Unavailable</body></html>" } to "Neema's server is unavailable right now — try again shortly.",
            { 429 to """{"detail":"slow down"}""" } to "Too many requests — wait a moment and try again.",
            { 200 to "<html>captive portal</html>" } to "The server sent an answer the app couldn't read.",
            { 200 to "" } to "The server sent an answer the app couldn't read.",
        )) {
            fake.on("GET", "/admin/conversations") { _, _ -> reply() }
            vm.refresh()
            assertEquals(said, vm.inbox.value.errorText)
        }
    }

    /** A failed next page stops auto-paging (no tight loop offline) until Retry. */
    @Test fun loadMore_failure_stopsAutoPaging_untilRetry() {
        val (_, vm) = vm()
        assertTrue(vm.inbox.value.hasMore)
        fake.on("GET", "/admin/conversations") { r, _ -> if (r.url.queryParameter("cursor") != null) offline() else 200 to InboxFixtures.page }
        vm.loadMore()
        assertTrue(vm.inbox.value.moreError); assertFalse(vm.inbox.value.loadingMore)
        val n = fake.calls.count { it.params.containsKey("cursor") }
        vm.loadMore(); vm.loadMore()                        // what scrolling would do
        assertEquals(n, fake.calls.count { it.params.containsKey("cursor") })
        vm.loadMore(force = true)                           // the Retry button
        assertEquals(n + 1, fake.calls.count { it.params.containsKey("cursor") })
    }

    @Test fun thread_offline_empty_saysWhy_andRetryWorks() {
        server.threadDown = { offline() }
        val (_, vm) = vm()
        vm.select("c1")
        vm.thread.value.let {
            assertTrue(it.error); assertFalse(it.loading)
            assertEquals("No connection — check your internet and try again.", it.errorText)
        }
        server.threadDown = null
        vm.loadMessages("c1")
        assertFalse(vm.thread.value.error)
        assertTrue(thread(vm).isNotEmpty())
    }

    /** An HTML page with a 200 (a captive portal) is an error — never "No messages yet". */
    @Test fun thread_garbageBody_isAnError_notAnEmptyThread() {
        fake.on("GET", "/admin/conversations/c1/messages", body = "<html>Log in to Safaricom Wi-Fi</html>")
        val (_, vm) = vm()
        vm.select("c1")
        assertTrue(vm.thread.value.error)
        assertTrue(thread(vm).isEmpty())
    }

    @Test fun thread_404_theConversationWasDeleted() {
        fake.on("GET", "/admin/conversations/c1/messages", code = 404, body = """{"detail":"Conversation not found"}""")
        val (_, vm) = vm()
        vm.select("c1")
        assertFalse("c1" in vm.inbox.value.cache)
        assertFalse(vm.thread.value.threadOpen)
        assertTrue(toasts.last().message.contains("deleted"))
        assertFalse(vm.rows.value.any { g -> g.siblings.any { it.id == "c1" } })
    }

    /** Peter's load fails after the agent already opened Mary: Mary's pane never shows Peter's error. */
    @Test fun thread_aLateFailureForTheThreadLeftBehind_neverTouchesTheOpenOne() {
        lateinit var vmRef: ConversationsViewModel
        fake.on("GET", "/admin/conversations/c1/messages") { _, _ -> vmRef.select("c2"); offline() }
        val (_, vm) = vm(); vmRef = vm
        vm.select("c1")
        assertEquals("c2", vm.thread.value.activeId)
        assertFalse(vm.thread.value.error); assertFalse(vm.thread.value.loading)
        assertTrue(toasts.none { it.message == "Failed to load messages" })
        assertTrue(thread(vm, "c2").isNotEmpty())
    }

    @Test fun olderPage_failure_offersATap_andTheTapRetries() {
        val many = (1..50).map { i -> row("h$i", "old $i", sender = "user", direction = "inbound") }
        server.rows.addAll(many)
        val (_, vm) = vm()
        vm.select("c1")
        assertTrue(vm.thread.value.hasMore["c1"] == true)
        fake.on("GET", "/admin/conversations/c1/messages") { r, _ -> if (r.url.queryParameter("before") != null) timeout() else 200 to InboxNetFixtures.thread(many) }
        vm.loadOlder()
        assertEquals("c1", vm.thread.value.olderError); assertEquals("", vm.thread.value.olderLoading)
        fake.on("GET", "/admin/conversations/c1/messages") { r, _ -> 200 to if (r.url.queryParameter("before") != null) "[]" else InboxNetFixtures.thread(many) }
        vm.loadOlder()
        assertEquals("", vm.thread.value.olderError)
    }

    // ═══════════════════ Ownership ═══════════════════

    private fun convRow(id: String, mode: String, agent: String?) =
        InboxFixtures.conversations.first { it.contains("\"id\":\"$id\"") }
            .replace(Regex("\"intercept_mode\":\"[a-z]+\""), "\"intercept_mode\":\"$mode\"")
            .replace(Regex("\"assigned_agent_id\":(null|\"[^\"]*\")"), "\"assigned_agent_id\":${agent?.let { "\"$it\"" } ?: "null"}")

    @Test fun intercept_timesOut_butHappened_saysClaimed() {
        fake.on("POST", "/admin/conversations/c2/intercept") { _, _ -> timeout() }
        fake.on("GET", "/admin/conversations/c2") { _, _ -> 200 to convRow("c2", "human", ke.co.bethanyhouse.neema.testing.Fixtures.ME_ID) }
        val (_, vm) = vm()
        vm.select("c2"); vm.intercept("c2")
        assertEquals("Conversation claimed — you now control replies", toasts.last().message)
        assertTrue(fake.called("GET", "/admin/conversations/c2"))
        assertTrue(vm.thread.value.busy.isEmpty())
    }

    @Test fun intercept_timesOut_andDidNotHappen_saysFailedWithWhy() {
        fake.on("POST", "/admin/conversations/c2/intercept") { _, _ -> timeout() }
        fake.on("GET", "/admin/conversations/c2") { _, _ -> 200 to convRow("c2", "ai", null) }
        val (_, vm) = vm()
        vm.select("c2"); vm.intercept("c2")
        assertEquals("Failed to claim conversation. No answer from the server — the connection is too slow right now.", errors().last().message)
    }

    @Test fun intercept_timesOut_andCantCheck_neverSaysFailed() {
        fake.on("POST", "/admin/conversations/c2/intercept") { _, _ -> timeout() }
        fake.on("GET", "/admin/conversations/c2") { _, _ -> offline() }
        val (_, vm) = vm()
        vm.select("c2"); vm.intercept("c2")
        assertTrue(errors().none { it.message.startsWith("Failed") })
        assertEquals(ToastType.Warning, toasts.last().type)
        assertTrue(toasts.last().message.startsWith("Couldn't confirm"))
    }

    /** Double taps claim once; a slow claim on one thread never blocks another thread's controls. */
    @Test fun controls_exactlyOncePerThread_butNeverBlockAnotherThread() {
        lateinit var vmRef: ConversationsViewModel
        fake.on("POST", "/admin/conversations/c2/intercept") { _, _ ->
            vmRef.intercept("c2"); vmRef.intercept("c2")   // impatient taps while in flight
            vmRef.pause("c4")                                 // another thread: goes ahead
            200 to InboxFixtures.Contract.intercept
        }
        val (_, vm) = vm(); vmRef = vm
        vm.intercept("c2")
        assertEquals(1, posts("/admin/conversations/c2/intercept").size)
        assertEquals(1, posts("/admin/conversations/c4/pause").size)
        assertTrue(vm.thread.value.busy.isEmpty())
    }

    @Test fun ownership_404_403_409() {
        val (_, vm) = vm()
        fake.on("POST", "/admin/conversations/c4/release", code = 404, body = """{"detail":"Conversation not found"}""")
        vm.select("c4"); vm.release("c4")
        assertFalse("c4" in vm.inbox.value.cache)
        assertTrue(toasts.last().message.contains("deleted"))
        fake.on("POST", "/admin/conversations/c2/pause", code = 403, body = """{"detail":"Only the agent handling it or an admin can pause it."}""")
        vm.pause("c2")
        assertEquals("Failed to pause. Only the agent handling it or an admin can pause it.", errors().last().message)
        var truth = 0
        fake.on("GET", "/admin/conversations/c2") { _, _ -> truth++; 200 to convRow("c2", "human", ke.co.bethanyhouse.neema.testing.Fixtures.AGENT2_ID) }
        fake.on("POST", "/admin/conversations/c2/intercept", code = 409, body = InboxFixtures.Contract.interceptConflict)
        vm.intercept("c2")
        assertEquals("Already claimed by another agent", errors().last().message)
        assertEquals(1, truth)
    }

    @Test fun transfer_dropped_butDone_closesTheDialog() {
        fake.on("POST", "/admin/conversations/c1/transfer") { _, _ -> dropped() }
        fake.on("GET", "/admin/conversations/c1") { _, _ -> 200 to convRow("c1", "human", ke.co.bethanyhouse.neema.testing.Fixtures.AGENT2_ID) }
        val (_, vm) = vm()
        vm.select("c1"); vm.showTransfer(true)
        vm.transfer(ke.co.bethanyhouse.neema.testing.Fixtures.AGENT2_ID, "Grace Wanjiru")
        assertEquals("Transferred to Grace Wanjiru", toasts.last().message)
        assertFalse(vm.dialogs.value.transfer)
    }

    @Test fun bulkRelease_countsWhatReallyHappened() {
        fake.on("POST", "/admin/conversations/c1/release") { _, _ -> timeout() }   // it did release
        fake.on("GET", "/admin/conversations/c1") { _, _ -> 200 to convRow("c1", "ai", null) }
        fake.on("POST", "/admin/conversations/c6/release") { _, _ -> offline() }   // never left the phone
        val (_, vm) = vm()
        vm.enterSelect(); vm.selectAllOrClear()
        vm.releaseSelected()
        assertEquals("Released 1 — 1 failed. No connection — check your internet and try again.", errors().last().message)
        assertFalse(vm.list.value.bulkBusy)
    }

    @Test fun clearHistory_timesOut_butTheThreadIsEmpty_isCleared_andDoubleTapClearsOnce() {
        var n = 0
        fake.on("DELETE", "/admin/conversations/c1/messages") { _, _ -> n++; fake.on("GET", "/admin/conversations/c1/messages", body = "[]"); timeout() }
        val (_, vm) = vm()
        vm.select("c1"); vm.showClear(true)
        vm.clearHistory()
        assertEquals("Chat history cleared", toasts.last().message)
        assertEquals(1, n)
        assertFalse(vm.dialogs.value.clearConfirm)
    }

    // ═══════════════════ Attachments ═══════════════════

    @Suppress("UNCHECKED_CAST")
    private fun ConversationsViewModel.pick(vararg m: PickedMedia) {
        val f = ConversationsViewModel::class.java.getDeclaredField("_composer").apply { isAccessible = true }
        val comp = f.get(this) as MutableStateFlow<ComposerUi>
        comp.value = comp.value.copy(media = m.toList())
    }

    private val video = PickedMedia("v1", Uri.parse("content://m/clip.mp4"), "clip.mp4", "video/mp4", 150L * 1024 * 1024 - 1, bytes = byteArrayOf(1, 2, 3), caption = "Fitting video")

    /** A 150 MB video times out and the server never got it: it stays in the tray, captioned, with the reason. */
    @Test fun video_timesOut_notOnServer_staysInTheTray_withWhy() {
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ -> timeout() }
        val (_, vm) = vm()
        vm.select("c1"); vm.pick(video)
        vm.sendMedia()
        val left = vm.composer.value.media.single()
        assertEquals("Fitting video", left.caption)
        assertEquals("upload timed out — check your connection and try again", left.error)
        assertTrue(left.unconfirmed)
        assertFalse(vm.composer.value.uploading)
        assertEquals("clip.mp4: upload timed out — check your connection and try again", errors().last().message)
    }

    /** It dropped halfway but the server DID finish: counted as sent, never uploaded twice. */
    @Test fun video_dropsHalfway_butArrived_isSent_notUploadedTwice() {
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ -> server.rows += row("srv-v", "Fitting video", mediaType = "video"); dropped() }
        val (_, vm) = vm()
        vm.select("c1"); vm.pick(video)
        vm.sendMedia()
        assertTrue(vm.composer.value.media.isEmpty())
        assertEquals("Media sent", toasts.last().message)
        assertEquals(1, posts("/admin/conversations/c1/upload-media").size)
    }

    /** Retry of a file whose upload went unanswered: found on the server → not uploaded again. */
    @Test fun video_retryAfterTimeout_checksFirst() {
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ -> timeout() }
        val (_, vm) = vm()
        vm.select("c1"); vm.pick(video)
        vm.sendMedia()
        server.rows += row("srv-v2", "Fitting video", mediaType = "video")   // the server finished after all
        vm.sendMedia()
        assertEquals(1, posts("/admin/conversations/c1/upload-media").size)
        assertTrue(vm.composer.value.media.isEmpty())
    }

    /** Signing out while a video uploads: no crash, no toast for a screen that is gone, nothing for the next agent. */
    @Test fun signOutMidUpload_isSilent() {
        val owner = Owner()
        lateinit var dashRef: DashboardViewModel
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ ->
            dashRef.logout(); owner.viewModelStore.clear()     // the signed-in scope is gone
            200 to InboxFixtures.Contract.uploaded("video", "https://api.bethanyhouse.co.ke/api/admin/media/v.mp4", "Fitting video")
        }
        val (dash, vm) = vm(owner); dashRef = dash
        vm.select("c1"); vm.pick(video)
        val before = toasts.size
        vm.sendMedia()
        assertEquals(before, toasts.size)
        assertNull(dash.session.value)
    }

    /** Switching threads mid-upload: the sent file leaves ITS thread's tray, not the open one's. */
    @Test fun upload_switchThreadsMidUpload_resultLandsOnItsThread() {
        lateinit var vmRef: ConversationsViewModel
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ ->
            vmRef.select("c2")
            200 to InboxFixtures.Contract.uploaded("video", "https://api.bethanyhouse.co.ke/api/admin/media/v.mp4", "Fitting video")
        }
        val (_, vm) = vm(); vmRef = vm
        vm.select("c1"); vm.pick(video)
        vm.sendMedia()
        assertTrue(thread(vm, "c1").any { it.id == "srv-u1" })
        assertTrue(thread(vm, "c2").none { it.id == "srv-u1" })
        assertFalse(vm.composer.value.uploading)
        vm.select("c1")
        assertTrue(vm.composer.value.media.isEmpty()); assertFalse(vm.composer.value.uploading)
    }

    // ═══════════════════ Recover media, Ask / Answer, invite, deep links ═══════════════════

    @Test fun recoverMedia_offlineIsTryAgain_404IsGone() {
        val (_, vm) = vm()
        vm.select("c1")
        var got: Recovery? = null
        fake.on("POST", "/admin/messages/m2/recover-media") { _, _ -> offline() }
        vm.recoverMedia("m2") { got = it }
        assertEquals(Recovery.Failed("No connection — check your internet and try again."), got)
        fake.on("POST", "/admin/messages/m2/recover-media", code = 404, body = InboxFixtures.Contract.recoverGone)
        vm.recoverMedia("m2") { got = it }
        assertEquals(Recovery.Gone, got)
    }

    @Test fun askNeema_offlineAndTimeout_sayWhy() = runBlocking {
        val (_, vm) = vm()
        vm.select("c1")
        fake.on("POST", "/admin/conversations/c1/ask") { _, _ -> offline() }
        assertEquals("No connection — check your internet and try again.", vm.askNeema("sizes?"))
        fake.on("POST", "/admin/conversations/c1/ask") { _, _ -> timeout() }
        assertEquals("Neema took too long to answer — try again.", vm.askNeema("sizes?"))
    }

    /** The answer went out but the connection dropped: the new message from Neema proves it. */
    @Test fun answerViaNeema_dropped_butSent_isReportedSent() = runBlocking {
        fake.on("POST", "/admin/conversations/c1/answer") { _, _ -> server.rows += row("srv-ans", "Yes Reverend — KES 12,500 🙏", sender = "ai"); dropped() }
        val (_, vm) = vm()
        vm.select("c1")
        assertEquals(true to "Neema sent: “Yes Reverend — KES 12,500 🙏”", vm.answerViaNeema("yes, KES 12,500"))
    }

    @Test fun invite_timeoutIsUnknown_offlineAndRefusalFallBack() = runBlocking {
        val (_, vm) = vm()
        fake.on("POST", "/admin/whatsapp-invite") { _, _ -> timeout() }
        assertTrue(vm.invite("254700000001", null) is ConversationsViewModel.InviteResult.Unknown)
        fake.on("POST", "/admin/whatsapp-invite") { _, _ -> offline() }
        assertEquals(ConversationsViewModel.InviteResult.Refused, vm.invite("254700000001", null))
        fake.on("POST", "/admin/whatsapp-invite", code = 503, body = """{"detail":"WhatsApp sending is not configured."}""")
        assertTrue(vm.invite("254700000001", null) is ConversationsViewModel.InviteResult.Unknown)
    }

    /** A deep link resolved while offline opens by itself once the app is back. */
    @Test fun deepLink_offline_opensOnReconnect() {
        fake.on("GET", "/admin/conversations/resolve") { _, _ -> offline() }
        val (dash, vm) = vm()
        dash.openConversationFor("254799999999")
        assertTrue(errors().last().message.startsWith("Couldn't open that chat — no connection"))
        assertEquals("", vm.thread.value.activeId)
        fake.on("GET", "/admin/conversations/resolve", body = """{"conversation_id":"c2"}""")
        dash.container.foreground.value = false; dash.container.foreground.value = true   // back
        assertEquals("c2", vm.thread.value.activeId)
    }

    @Test fun openIdentity_offline_neverClaimsThereIsNoConversation() {
        fake.on("GET", "/admin/conversations") { r, _ -> if (r.url.queryParameter("q") != null) offline() else 200 to InboxFixtures.page }
        val (_, vm) = vm()
        vm.openIdentity("instagram", "17849999999999999")
        assertTrue(toasts.none { it.message == "No conversation on that channel yet." })
        assertEquals("Couldn't open that conversation. No connection — check your internet and try again.", errors().last().message)
    }
}
