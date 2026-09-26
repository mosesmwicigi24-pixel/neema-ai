package ke.co.bethanyhouse.neema.conversations

import ke.co.bethanyhouse.neema.core.util.AppClock

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
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
 * The inbox's behaviour against the fake backend: useInbox's semantics, the
 * thread's merge/dedupe with socket frames, and every control's request.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class ConversationsViewModelTest {
    @get:Rule val paparazzi = Paparazzi()

    private val sched = TestCoroutineScheduler()
    private val scope = CoroutineScope(UnconfinedTestDispatcher(sched))
    private lateinit var fake: FakeNeema
    private val toasts = mutableListOf<Toast>()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        fake = FakeNeema.withFixtures().also(InboxFixtures::install)
    }

    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun vm(role: String = "admin", superuser: Boolean = true): Pair<DashboardViewModel, ConversationsViewModel> {
        val dash = dashboard(paparazzi.context, fake, role, superuser)
        scope.launch { dash.toasts.collect { toasts += it } }
        return dash to ConversationsViewModel(dash)
    }

    private fun calls(method: String, path: String) = fake.calls.filter { it.method == method && it.path == path }
    private fun lastBody(method: String, path: String) = calls(method, path).last().body?.let { Json.parseToJsonElement(it).jsonObject }

    @Suppress("UNCHECKED_CAST")
    private fun socket(dash: DashboardViewModel, json: String) {
        val f = LiveSocket::class.java.getDeclaredField("_events").apply { isAccessible = true }
        (f.get(dash.container.socket) as MutableSharedFlow<JsonObject>).tryEmit(Json.parseToJsonElement(json).jsonObject)
        sched.runCurrent()
    }

    private fun page(vararg ids: String, cursor: String? = null) =
        """{"items":[${ids.map { id -> InboxFixtures.conversations.first { it.contains("\"id\":\"$id\"") } }.joinToString(",")}],"next_cursor":${cursor?.let { "\"$it\"" } ?: "null"}}"""

    /** `rows` is computed in place when I/O is synchronous; this only guards against regressions. */
    private fun ConversationsViewModel.rowsWhen(ok: (List<ke.co.bethanyhouse.neema.feature.conversations.RowGroup>) -> Boolean): List<ke.co.bethanyhouse.neema.feature.conversations.RowGroup> {
        val end = AppClock.now() + 3000
        while (!ok(rows.value) && AppClock.now() < end) Thread.sleep(5)
        return rows.value
    }

    // ═══════════════ useInbox ═══════════════

    @Test fun pageOne_loadsGroupsPeopleAndBadges() {
        val (_, vm) = vm()
        val s = vm.inbox.value
        assertTrue(s.freshLoaded); assertFalse(s.loading); assertTrue(s.hasMore)
        assertEquals("limit=50", calls("GET", "/admin/conversations").first().query)
        assertEquals(2, s.summary?.unread)
        // c1 (WhatsApp) + c5 (Facebook) are one person: one row, WhatsApp chip first.
        val rows = vm.rowsWhen { it.size == 6 }
        val row = rows.first { it.key == "p1" }
        assertEquals(listOf("whatsapp", "facebook"), row.siblings.map { it.channel })
        assertEquals(6, rows.size)
    }

    /** Carry-over: rows used flowOn(Default), so the first frame was sometimes empty. */
    @Test fun rows_areReadyTheMomentTheViewModelIs_noWaiting() {
        val (_, vm) = vm()
        // Read straight away — no polling, no sleeping.
        assertEquals(6, vm.rows.value.size)
        vm.setTab("human")
        assertEquals(setOf("c1", "c6"), vm.rows.value.map { it.rep.id }.toSet())
    }

    /** Carry-over: after a failure the list offers Retry instead of "Loading…" forever. */
    @Test fun listLoadFailure_flagsTheError_andRetryRecovers() {
        fake.on("GET", "/admin/conversations", code = 500, body = """{"detail":"down"}""")
        val (_, vm) = vm()
        vm.inbox.value.let {
            assertTrue(it.loadError); assertFalse(it.loading); assertFalse(it.freshLoaded)
        }
        assertTrue(vm.rows.value.isEmpty())
        fake.on("GET", "/admin/conversations", body = InboxFixtures.page)
        vm.refresh()
        vm.inbox.value.let { assertFalse(it.loadError); assertTrue(it.freshLoaded) }
        assertEquals(6, vm.rows.value.size)
    }

    @Test fun listLoadFailure_isTheLiveFiltersOwn_aNewFilterStartsClean() {
        fake.on("GET", "/admin/conversations") { r, _ ->
            if (r.url.queryParameter("tab") == "unread") 500 to """{"detail":"down"}""" else 200 to InboxFixtures.page
        }
        val (_, vm) = vm()
        assertFalse(vm.inbox.value.loadError)
        vm.setTab("unread")
        assertTrue(vm.inbox.value.loadError)
        vm.setTab("all")
        assertFalse(vm.inbox.value.loadError)
        assertEquals(6, vm.rows.value.size)
    }

    @Test fun listLoadFailure_afterASnapshotOrPageOne_keepsTheRowsQuietly() {
        val (_, vm) = vm()
        fake.on("GET", "/admin/conversations", code = 500, body = """{"detail":"down"}""")
        vm.refresh()
        // A background refresh failing leaves the list as it was (the web's rule);
        // the flag only matters when there is nothing to show.
        assertEquals(6, vm.rows.value.size)
        assertFalse(vm.inbox.value.loading)
    }

    /** Carry-over: a web-chat visitor's `web_<hash>` (or a Meta PSID) is never dialled. */
    @Test fun call_isRefusedForWebVisitorsAndNonNumbers() {
        val (_, vm) = vm()
        val before = fake.calls.size
        vm.call("web_3fa9c1e20b7d4c5a9e11", null)
        vm.call("3fa9c1e20b7d4c5a9e11", null)
        vm.call("25898765432101234567", null)   // a 20-digit PSID
        assertEquals(before, fake.calls.size)
        assertTrue(toasts.none { it.message.contains("call", ignoreCase = true) })
    }

    @Test fun newestRequestWins_anOlderResponseLandingLastIsDropped() {
        var n = 0
        lateinit var vmRef: ConversationsViewModel
        fake.on("GET", "/admin/conversations") { _, _ ->
            n++
            // While the first (older) request is in flight, a newer refresh starts and finishes.
            if (n == 2) vmRef.refresh()
            200 to if (n == 2) page("c1", "c2") else page("c3")
        }
        val (_, vm) = vm().also { vmRef = it.second }
        n = 1
        vm.refresh()
        // The newer request (c3) won; the older (c1, c2) response was ignored.
        assertEquals(listOf("c3"), vm.inbox.value.orderIds)
    }

    @Test fun refreshReplacesPageOne_butMergesOnceScrolledFurther() {
        fake.on("GET", "/admin/conversations") { r, _ ->
            200 to if (r.url.queryParameter("cursor") == "cursor-2") page("c6", "c7") else page("c1", "c2", "c3", cursor = "cursor-2")
        }
        val (_, vm) = vm()
        assertEquals(listOf("c1", "c2", "c3"), vm.inbox.value.orderIds)
        // Only page one loaded: a refresh REPLACES it (c3 fell off page one → gone).
        fake.on("GET", "/admin/conversations") { r, _ -> 200 to if (r.url.queryParameter("cursor") == "cursor-2") page("c6", "c7") else page("c2", "c1", cursor = "cursor-2") }
        vm.refresh()
        assertEquals(listOf("c2", "c1"), vm.inbox.value.orderIds)
        // Scrolled to page two: a refresh keeps page two below the fresh page one.
        vm.loadMore()
        assertEquals("cursor=cursor-2&limit=50", calls("GET", "/admin/conversations").last().query?.split("&")?.sorted()?.joinToString("&"))
        assertEquals(listOf("c2", "c1", "c6", "c7"), vm.inbox.value.orderIds)
        fake.on("GET", "/admin/conversations", body = page("c4", "c1"))
        vm.refresh()
        assertEquals(listOf("c4", "c1", "c2", "c6", "c7"), vm.inbox.value.orderIds)
        // The cache never loses a row: c3 is still there for lookups.
        assertNotNull(vm.inbox.value.cache["c3"])
    }

    @Test fun loadMoreInFlight_isCancelledByAPageOneReplace() {
        lateinit var vmRef: ConversationsViewModel
        fake.on("GET", "/admin/conversations") { r, _ ->
            if (r.url.queryParameter("cursor") != null) {
                // Page one lands (a replace) while the old-cursor page is still in flight.
                kotlin.concurrent.thread { vmRef.refresh() }.join()
                200 to page("c6", "c7", cursor = "cursor-3")
            } else 200 to page("c1", "c2", cursor = "cursor-2")
        }
        val (_, vm) = vm().also { vmRef = it.second }
        vm.loadMore()
        val s = vm.inbox.value
        assertEquals(listOf("c1", "c2"), s.orderIds)   // no stale page appended past a moved boundary
        assertFalse(s.loadingMore)
        assertTrue(s.hasMore)
    }

    @Test fun filters_eachStartsItsOwnListAndSearchIsDebounced() {
        val (_, vm) = vm()
        fake.on("GET", "/admin/conversations", body = page("c1", "c2"))
        vm.setTab("unread")
        assertTrue(calls("GET", "/admin/conversations").last().query!!.contains("tab=unread"))
        assertEquals(setOf("p1", "c2"), vm.rowsWhen { r -> r.map { it.key }.toSet() == setOf("p1", "c2") }.map { it.key }.toSet())
        vm.setChannel("messenger")
        assertTrue(calls("GET", "/admin/conversations").last().query!!.contains("channel=messenger"))
        assertEquals(listOf("c2"), vm.rowsWhen { it.size == 1 }.map { it.rep.id })
        val before = calls("GET", "/admin/conversations").size
        vm.setSearch("pe"); vm.setSearch("peter")
        assertEquals(before, calls("GET", "/admin/conversations").size) // not yet — waits for a pause
        sched.advanceTimeBy(301); sched.runCurrent()
        assertEquals(before + 1, calls("GET", "/admin/conversations").size)
        assertTrue(calls("GET", "/admin/conversations").last().query!!.contains("q=peter"))
        vm.setTag("vip"); vm.setMode("human")
        val q = calls("GET", "/admin/conversations").last().query!!
        assertTrue(q.contains("tag=vip") && q.contains("mode=human"))
    }

    @Test fun watch_keepsTheOpenThreadFreshWhenOffPageOne() {
        val (_, vm) = vm()
        vm.select("c6")
        fake.on("GET", "/admin/conversations", body = page("c1", "c2"))
        fake.calls.clear()
        vm.refresh()
        // (It follows the snapshot write, which hops to the IO pool.)
        val end = AppClock.now() + 3000
        while (!fake.called("GET", "/admin/conversations/c6") && AppClock.now() < end) Thread.sleep(5)
        assertTrue(fake.called("GET", "/admin/conversations/c6"))
    }

    // ═══════════════ openConvKey ═══════════════

    @Test fun openKey_matchesPhonePreferringWhatsApp_andConsumesTheKey() {
        val (dash, vm) = vm()
        dash.openConversationFor("+254712345678|BH-1042")
        assertEquals("c1", vm.thread.value.activeId)
        assertNull(dash.openConvKey.value)
        assertFalse(fake.called("GET", "/admin/conversations/resolve"))
    }

    @Test fun openKey_unknownPhoneWithRef_resolvesOnTheServerAndReveals() {
        fake.on("GET", "/admin/conversations/resolve", body = """{"conversation_id":"c99"}""")
        fake.on("GET", "/admin/conversations/c99", body = Fixtures.conv("c99", "Bishop Otieno", "254799000111", "whatsapp", "ai", "Old thread", 60L * 24 * 90))
        val (dash, vm) = vm()
        dash.openConversationFor("254799000111|BH-0999")
        val r = calls("GET", "/admin/conversations/resolve").single()
        assertEquals("key=254799000111&ref=BH-0999", r.query)
        assertEquals("c99", vm.thread.value.activeId)
        assertTrue("c99" in vm.inbox.value.orderIds)   // revealed: survives the next page-one replace
        vm.refresh()
        assertTrue("c99" in vm.inbox.value.orderIds)
    }

    @Test fun openKey_noConversation_warns() {
        fake.on("GET", "/admin/conversations/resolve", body = """{"conversation_id":null}""")
        val (dash, vm) = vm()
        dash.openConversationFor("254700000000")
        assertEquals("", vm.thread.value.activeId)
        assertEquals(ToastType.Warning, toasts.last().type)
        assertEquals("No conversation yet — they haven't messaged. Use Invite to WhatsApp.", toasts.last().message)
    }

    @Test fun openKey_waitsForTheFreshList() {
        fake.on("GET", "/admin/conversations", code = 500, body = """{"detail":"down"}""")
        fake.on("GET", "/admin/conversations/resolve", body = """{"conversation_id":"c1"}""")
        val (dash, _) = vm()
        dash.openConversationFor("254700000000")
        // Empty list: the key is kept, nothing resolved against it.
        assertEquals("254700000000", dash.openConvKey.value)
        assertFalse(fake.called("GET", "/admin/conversations/resolve"))
    }

    // ═══════════════ The thread ═══════════════

    @Test fun select_loadsNewestPage_clearsUnread_snapshotsDivider() {
        val (_, vm) = vm()
        vm.select("c1")
        assertEquals("limit=50", calls("GET", "/admin/conversations/c1/messages").last().query)
        assertEquals(8, vm.thread.value.messages["c1"]?.size)
        assertEquals(false, vm.thread.value.hasMore["c1"])
        assertEquals(2, vm.thread.value.unreadSnapshot["c1"])
        assertEquals(0, vm.inbox.value.cache["c1"]?.unread)
        assertTrue(fake.called("GET", "/admin/conversations/c1/window"))
        assertTrue(fake.called("GET", "/admin/conversations/c1/latest-draft"))  // human-held → the draft pill
    }

    @Test fun loadError_saysSoAndRetries() {
        fake.on("GET", "/admin/conversations/[^/]+/messages", code = 500, body = """{"detail":"boom"}""")
        val (_, vm) = vm()
        vm.select("c2")
        assertTrue(vm.thread.value.error)
        assertEquals("Failed to load messages", toasts.last().message)
        fake.on("GET", "/admin/conversations/[^/]+/messages", body = Fixtures.messages)
        vm.loadMessages("c2")
        assertFalse(vm.thread.value.error)
        assertEquals(8, vm.thread.value.messages["c2"]?.size)
    }

    @Test fun pagingOlder_usesBeforeAndMerges() {
        fake.on("GET", "/admin/conversations/[^/]+/messages") { r, _ ->
            200 to if (r.url.queryParameter("before") != null) InboxFixtures.plainPage("old", 10, 500) else InboxFixtures.plainPage("new", 50, 100)
        }
        val (_, vm) = vm()
        vm.select("c2")
        assertEquals(true, vm.thread.value.hasMore["c2"])
        val oldest = vm.thread.value.messages["c2"]!!.first().createdAt
        vm.loadOlder()
        val q = calls("GET", "/admin/conversations/c2/messages").last()
        assertTrue(q.query!!.contains("before=") && q.query!!.contains("limit=50"))
        assertEquals(oldest, java.net.URLDecoder.decode(q.query!!.substringAfter("before=").substringBefore("&"), "UTF-8"))
        val msgs = vm.thread.value.messages["c2"]!!
        assertEquals(60, msgs.size)
        assertEquals("old0", msgs.first().id)
        assertEquals(false, vm.thread.value.hasMore["c2"])   // 10 < 50: the start of the thread
    }

    @Test fun socket_newMessage_appendsDedupesById_andByMediaWithin15s() {
        val (dash, vm) = vm()
        vm.select("c1")
        socket(dash, """{"type":"new_message","conversationId":"c1","id":"w1","direction":"inbound","sender":"user","text":"Hello again"}""")
        socket(dash, """{"type":"new_message","conversationId":"c1","id":"w1","direction":"inbound","sender":"user","text":"Hello again"}""")
        val now = AppClock.instant()
        socket(dash, """{"type":"new_message","conversationId":"c1","id":"a-rand-1","direction":"outbound","sender":"ai","text":"","mediaType":"audio","mediaUrl":"https://x/a.ogg","created_at":"$now"}""")
        socket(dash, """{"type":"new_message","conversationId":"c1","id":"a-rand-2","direction":"outbound","sender":"ai","text":"","mediaType":"audio","mediaUrl":"https://x/a.ogg","created_at":"${now.plusSeconds(5)}"}""")
        // Another conversation's frame never lands in this thread.
        socket(dash, """{"type":"new_message","conversationId":"c2","id":"z","direction":"inbound","sender":"user","text":"other"}""")
        val ids = vm.thread.value.messages["c1"]!!.map { it.id }
        assertEquals(1, ids.count { it == "w1" })
        assertTrue("a-rand-1" in ids); assertFalse("a-rand-2" in ids); assertFalse("z" in ids)
        assertEquals(10, ids.size)
    }

    @Test fun socket_translationsDraftsPillsAndClear() {
        val (dash, vm) = vm()
        vm.select("c1")
        socket(dash, """{"type":"translations","conversationId":"c1","items":[{"id":"m3","text":"Inchi 16, mbili nyeusi","lang":"sw"}]}""")
        val m3 = vm.thread.value.messages["c1"]!!.first { it.id == "m3" }
        assertEquals("Inchi 16, mbili nyeusi", m3.translation); assertEquals("sw", m3.translatedFrom)

        socket(dash, """{"type":"ai_draft_ready","conversationId":"c1","draft":"Yes Father, Friday works."}""")
        assertTrue(vm.composer.value.draftVisible); assertFalse(vm.composer.value.draftExpanded)
        assertEquals("Yes Father, Friday works.", vm.composer.value.draftText)

        socket(dash, """{"type":"intercept_changed","conversationId":"c1","eventKind":"release","eventAgentName":"Grace"}""")
        socket(dash, """{"type":"intercept_changed","conversationId":"c1","eventKind":"release","eventAgentName":"Grace"}""")
        val live = vm.thread.value.messages["c1"]!!.filter { it.id.startsWith("live-evt-") }
        assertEquals(1, live.size); assertEquals("Released to AI by Grace", live.single().text)

        socket(dash, """{"type":"history_cleared","conversationId":"c1","clearedBy":"Grace"}""")
        assertTrue(vm.thread.value.messages["c1"]!!.isEmpty())
        assertEquals("History cleared by Grace", toasts.last().message)
    }

    // ═══════════════ Sending ═══════════════

    @Test fun sendReply_optimisticBubbleIsReplacedByTheServerRow() {
        var serverHasIt = false
        fake.on("GET", "/admin/conversations/[^/]+/messages") { _, _ ->
            val extra = if (serverHasIt) """,{"id":"srv-1","type":"message","direction":"outbound","sender":"human_agent","text":"On its way Friday","created_at":"${AppClock.instant()}"}""" else ""
            200 to Fixtures.messages.trimEnd().removeSuffix("]") + extra + "]"
        }
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ -> serverHasIt = true; 200 to """{"ok":true}""" }
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("On its way Friday")
        vm.sendReply()
        assertEquals("On its way Friday", lastBody("POST", "/admin/conversations/c1/reply")!!["text"].toString().trim('"'))
        val msgs = vm.thread.value.messages["c1"]!!
        assertEquals(1, msgs.count { it.body == "On its way Friday" })
        assertEquals("srv-1", msgs.last().id)
        assertEquals("", vm.composer.value.replyText)
        assertFalse(vm.composer.value.sending)
    }

    @Test fun sendReply_deliveryFailure_restoresTheTextAndSaysWhy() {
        fake.on("POST", "/admin/conversations/c1/reply", body = """{"ok":false,"error":"Couldn't send the reply: window closed"}""")
        val (_, vm) = vm()
        vm.select("c1")
        vm.setReplyText("Hello")
        vm.sendReply()
        assertTrue(vm.thread.value.messages["c1"]!!.none { it.id.startsWith("optimistic-") })
        assertEquals("Hello", vm.composer.value.replyText)
        assertEquals(ToastType.Error, toasts.last().type)
        assertEquals("Couldn't send the reply: window closed", toasts.last().message)
    }

    @Test fun sendReply_sameChannelQuoteThreads_crossChannelQuotePrefixes() {
        val (_, vm) = vm()
        vm.select("c1")
        val m6 = vm.thread.value.messages["c1"]!!.first { it.id == "m6" }
        vm.beginReplyTo(m6)
        vm.setReplyText("Yes")
        vm.sendReply()
        var b = lastBody("POST", "/admin/conversations/c1/reply")!!
        assertEquals("\"m6\"", b["reply_to"].toString()); assertEquals("\"Yes\"", b["text"].toString())
        // A quote grabbed on WhatsApp, answered on the Facebook sibling: a text prefix.
        vm.beginReplyTo(m6)
        vm.select("c5")
        vm.setReplyText("Yes")
        vm.sendReply()
        b = lastBody("POST", "/admin/conversations/c5/reply")!!
        assertNull(b["reply_to"])
        assertEquals("↩ Re (WhatsApp): \"Can you deliver to Nyeri by Friday?\"\n\nYes", Json.decodeFromJsonElement(kotlinx.serialization.serializer<String>(), b["text"]!!))
    }

    @Test fun translateToggle_sendsTheirLanguageWithTheEnglishAlong() {
        fake.on("GET", "/admin/conversations/[^/]+/messages", body = """[{"id":"t1","type":"message","direction":"inbound","sender":"user","text":"Habari","created_at":"${Fixtures.ago(3)}","translation":"Hello","translated_from":"sw"}]""")
        val (_, vm) = vm()
        vm.select("c1")
        assertTrue(vm.txOn())          // ON by default: the thread reads foreign
        vm.setReplyText("Yes, Friday")
        sched.advanceTimeBy(701); sched.runCurrent()
        assertEquals("\"Yes, Friday\"", lastBody("POST", "/admin/conversations/c1/translate-reply")!!["text"].toString())
        assertEquals("Ndiyo, tutafikisha Ijumaa.", vm.composer.value.txPreview?.text)
        val before = calls("POST", "/admin/conversations/c1/translate-reply").size
        vm.sendReply()
        // The preview is reused — nothing is translated twice.
        assertEquals(before, calls("POST", "/admin/conversations/c1/translate-reply").size)
        val b = lastBody("POST", "/admin/conversations/c1/reply")!!
        assertEquals("\"Ndiyo, tutafikisha Ijumaa.\"", b["text"].toString())
        assertEquals("\"Yes, Friday\"", b["original_text"].toString())
        assertEquals("\"Swahili\"", b["original_lang"].toString())   // translate_reply names the language
        vm.toggleTx()
        assertFalse(vm.txOn())
    }

    // ═══════════════ Controls → endpoints ═══════════════

    @Test fun controls_callTheRightEndpointsWithTheRightBodies_andSucceed() {
        val (_, vm) = vm()
        vm.select("c2")
        vm.intercept("c2")
        assertEquals("{}", calls("POST", "/admin/conversations/c2/intercept").single().body)
        assertEquals("Conversation claimed — you now control replies", toasts.last().message)
        assertEquals(ToastType.Success, toasts.last().type)
        vm.pause("c2")
        assertEquals("Paused — Neema holds all replies until you resume", toasts.last().message)
        vm.release("c2")
        assertEquals("Conversation released back to AI", toasts.last().message)
        vm.transfer(Fixtures.AGENT2_ID, "Grace Wanjiru")
        assertEquals("\"${Fixtures.AGENT2_ID}\"", lastBody("POST", "/admin/conversations/c2/transfer")!!["agent_id"].toString())
        assertEquals("Transferred to Grace Wanjiru", toasts.last().message)
        assertEquals("", vm.thread.value.convBusy)
    }

    @Test fun intercept_conflict_saysAlreadyClaimed() {
        fake.on("POST", "/admin/conversations/[^/]+/intercept", code = 409, body = """{"detail":"Already intercepted"}""")
        val (_, vm) = vm()
        vm.intercept("c2")
        assertEquals("Already claimed by another agent", toasts.last().message)
        fake.on("POST", "/admin/conversations/[^/]+/pause", code = 409, body = """{"detail":"held"}""")
        vm.pause("c2")
        assertEquals("Handled by another agent — they must pause it", toasts.last().message)
    }

    @Test fun note_draft_clear_bodies() {
        val (_, vm) = vm()
        vm.select("c1")
        vm.showNote(true); vm.setNoteText("  Measure on Friday  "); vm.saveNote()
        assertEquals("\"Measure on Friday\"", lastBody("POST", "/admin/conversations/c1/note")!!["text"].toString())
        assertFalse(vm.dialogs.value.note)

        vm.generateDraft()
        assertTrue(fake.called("POST", "/admin/conversations/c1/generate-draft"))
        assertTrue(vm.composer.value.draftVisible && vm.composer.value.draftExpanded)
        vm.setDraftText("Edited draft")
        vm.approveDraft()
        assertEquals("\"Edited draft\"", lastBody("POST", "/admin/conversations/c1/approve-draft")!!["text"].toString())
        assertEquals("AI draft approved & sent", toasts.last().message)
        assertFalse(vm.composer.value.draftVisible)

        vm.showClear(true); vm.clearHistory()
        assertEquals(1, calls("DELETE", "/admin/conversations/c1/messages").size)
        assertTrue(vm.thread.value.messages["c1"]!!.isEmpty())
        assertFalse(vm.dialogs.value.clearConfirm)
    }

    @Test fun noteFailure_putsTheNoteBack() {
        fake.on("POST", "/admin/conversations/[^/]+/note", code = 500, body = """{"detail":"x"}""")
        val (_, vm) = vm()
        vm.select("c1")
        vm.setNoteText("Keep me"); vm.saveNote()
        assertTrue(vm.dialogs.value.note); assertEquals("Keep me", vm.dialogs.value.noteText)
        assertTrue(vm.thread.value.messages["c1"]!!.none { it.id.startsWith("optimistic-note-") })
        assertEquals("Failed to save note", toasts.last().message)
    }

    @Test fun clearForbidden_saysSo() {
        fake.on("DELETE", "/admin/conversations/[^/]+/messages", code = 403, body = """{"detail":"Only admins can clear chat history"}""")
        val (_, vm) = vm()
        vm.select("c1"); vm.clearHistory()
        assertEquals("You don't have permission to clear chat history", toasts.last().message)
    }

    @Test fun bulkRelease_releasesOnlyHumanHeldThreads() {
        val (_, vm) = vm()
        vm.enterSelect("p1")          // Fr. Peter — c1 held, c5 with Neema
        vm.toggleRow("c6")            // held by Grace
        vm.toggleRow("c2")            // with Neema: selectable, costs nothing
        vm.rowsWhen { it.size == 6 }
        assertEquals(setOf("c1", "c6"), vm.selectedHeldIds().toSet())
        vm.releaseSelected()
        assertEquals(setOf("/admin/conversations/c1/release", "/admin/conversations/c6/release"),
            fake.calls.filter { it.method == "POST" && it.path.endsWith("/release") }.map { it.path }.toSet())
        assertEquals("2 conversations released back to Neema", toasts.last().message)
        assertFalse(vm.list.value.selectMode)
    }

    @Test fun bulkRelease_nothingHeld_warns() {
        val (_, vm) = vm()
        vm.rowsWhen { it.size == 6 }
        vm.enterSelect("c2")
        vm.releaseSelected()
        assertEquals("None of those are held by a human", toasts.last().message)
        assertFalse(fake.calls.any { it.path.endsWith("/release") })
    }

    @Test fun changingTheListClearsThePicks() {
        val (_, vm) = vm()
        vm.enterSelect("p1")
        vm.setTab("human")
        assertTrue(vm.list.value.selected.isEmpty())
        vm.toggleRow("c6")
        vm.setMode("paused")          // like the web, the mode filter keeps the picks
        assertEquals(setOf("c6"), vm.list.value.selected)
    }
}
