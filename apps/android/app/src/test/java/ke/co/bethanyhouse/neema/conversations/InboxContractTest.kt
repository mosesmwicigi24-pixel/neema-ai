package ke.co.bethanyhouse.neema.conversations

import ke.co.bethanyhouse.neema.core.util.AppClock

import android.net.Uri
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.api.InboxQuery
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.feature.conversations.*
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures.Contract
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * Round 3 — the inbox against the REAL backend contract. Every request is
 * asserted exactly (method, path, query, body) and every response decoded
 * from the shape its handler in apps/api/app/routers/admin.py (and
 * services/conversation.py, services/translate.py) actually returns —
 * including the variants hand-written fixtures hid: Meta rows with a null
 * wa_id, "+00:00" microsecond timestamps, tags that aren't a list, 200
 * {ok:false} replies, pydantic 422 lists, proxy HTML error pages, and socket
 * frames without an id or a direction.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxContractTest {
    @get:Rule val paparazzi = Paparazzi()

    private val sched = TestCoroutineScheduler()
    private val scope = CoroutineScope(UnconfinedTestDispatcher(sched))
    private lateinit var fake: FakeNeema
    private val toasts = mutableListOf<Toast>()

    @Before fun setUp() {
        Dispatchers.setMain(UnconfinedTestDispatcher(sched))
        fake = FakeNeema.withFixtures().also(InboxFixtures::install)
        fake.on("GET", "/admin/conversations", body = Contract.page(Contract.peterWa, Contract.maryMsgr, Contract.peterFb, Contract.visitor, cursor = Contract.CURSOR))
        fake.on("GET", "/admin/conversations/summary", body = Contract.summary)
        fake.on("GET", "/admin/conversations/[^/]+/messages", body = Contract.thread())
    }

    @After fun tearDown() { scope.cancel(); Dispatchers.resetMain() }

    private fun vm(role: String = "admin", superuser: Boolean = true): Pair<DashboardViewModel, ConversationsViewModel> {
        val dash = dashboard(paparazzi.context, fake, role, superuser)
        scope.launch { dash.toasts.collect { toasts += it } }
        return dash to ConversationsViewModel(dash)
    }

    private fun api(): InboxApi = InboxApi(dashboard(paparazzi.context, fake).api.http)
    private fun calls(method: String, path: String) = fake.calls.filter { it.method == method && it.path == path }
    private fun body(method: String, path: String): JsonObject = Json.parseToJsonElement(calls(method, path).last().body!!).jsonObject
    private fun JsonObject.str(k: String) = this[k]?.jsonPrimitive?.content

    @Suppress("UNCHECKED_CAST")
    private fun socket(dash: DashboardViewModel, json: String) {
        val f = LiveSocket::class.java.getDeclaredField("_events").apply { isAccessible = true }
        (f.get(dash.container.socket) as MutableSharedFlow<JsonObject>).tryEmit(Json.parseToJsonElement(json).jsonObject)
        sched.runCurrent()
    }

    // ═══════════════ The list: page, summary, get, resolve ═══════════════

    @Test fun page_sendsTheServersQueryNames_andDecodesRealRows() = runBlocking {
        val res = api().page(InboxQuery(tab = "unread", channel = "messenger", mode = "human", tag = "vip", q = "  Nyeri Friday "), 50, Contract.CURSOR)
        val c = fake.calls.last()
        assertEquals("GET", c.method); assertEquals("/admin/conversations", c.path)
        // list_conversations(limit, cursor, tab, channel, mode, tag, q) — spaces encoded, the search trimmed.
        assertEquals("limit=50&cursor=${Contract.CURSOR}&tab=unread&channel=messenger&mode=human&tag=vip&q=Nyeri+Friday", c.query)
        assertEquals(Contract.CURSOR, res.nextCursor)
        val mary = res.items.first { it.id == "k2" }
        assertNull(mary.waId)                                  // Meta rows carry no wa_id…
        assertEquals("7123456789012345", mary.externalId)      // …the PSID is the key
        assertEquals("messenger", mary.channel); assertNull(mary.countryIso); assertNull(mary.leadStage)
        val peter = res.items.first { it.id == "k1" }
        assertEquals(listOf("vip", "clergy"), peter.tags); assertEquals(3, peter.ordersCount)
        assertEquals(Fixtures.ME_ID, peter.assignedAgentId); assertEquals("human", peter.interceptMode)
        // Python's "+00:00" microsecond timestamps parse to the right instant.
        assertTrue(kotlin.math.abs(AppClock.now() - 2 * 60_000 - ke.co.bethanyhouse.neema.core.util.Fmt.millis(peter.lastMessageAt)!!) < 60_000)
    }

    @Test fun page_allFilters_omitsTheirKeys() = runBlocking {
        api().page(InboxQuery(), 50)
        assertEquals("limit=50", fake.calls.last().query)
    }

    @Test fun page_legacyBareArray_isOneFinalPage() = runBlocking {
        fake.on("GET", "/admin/conversations", body = "[${Contract.peterWa},${Contract.maryMsgr}]")
        val res = api().page(InboxQuery(), 50)
        assertEquals(listOf("k1", "k2"), res.items.map { it.id }); assertNull(res.nextCursor)
    }

    /** `tags` comes off free-form JSONB: a bare string, nulls, numbers — none may blank the inbox. */
    @Test fun page_oddTags_areNormalised_notFatal() = runBlocking {
        fake.on("GET", "/admin/conversations", body = """{"items":[${Contract.oddTags},${Contract.mixedTags},{"wa_id":"x"},${Contract.row("k9", "No tags", "254700000009", "254700000009", "whatsapp", "ai", "hi", 5).replace("\"tags\":[]", "\"tags\":null")}],"next_cursor":null}""")
        val res = api().page(InboxQuery(), 50)
        assertEquals(listOf("k3", "k4", "k9"), res.items.map { it.id })   // the id-less row drops, nothing else
        assertEquals(listOf("vip"), res.items[0].tags)
        assertEquals(listOf("bulk", "7"), res.items[1].tags)
        assertEquals(emptyList<String>(), res.items[2].tags)
    }

    @Test fun page_badCursor400_leavesTheListAndSaysNothing() {
        val (_, vm) = vm()
        assertTrue(vm.inbox.value.hasMore)
        fake.on("GET", "/admin/conversations") { r, _ ->
            if (r.url.queryParameter("cursor") != null) 400 to """{"detail":"bad cursor"}""" else 200 to Contract.page(Contract.peterWa, cursor = Contract.CURSOR)
        }
        val before = vm.inbox.value.orderIds
        vm.loadMore()
        assertEquals(before, vm.inbox.value.orderIds); assertFalse(vm.inbox.value.loadingMore)
        assertTrue(toasts.none { it.type == ToastType.Error })
    }

    @Test fun summary_decodesEveryBadge() {
        val (_, vm) = vm()
        val s = vm.inbox.value.summary!!
        assertEquals(2, s.unread); assertEquals(1, s.human); assertEquals(1, s.yours)
        assertEquals(mapOf("all" to 3, "whatsapp" to 2, "messenger" to 1), s.unreadMessages)
        assertEquals(listOf("bulk", "clergy", "vip"), s.tags)
    }

    @Test fun get_oneRow_andA404Throws() = runBlocking {
        fake.on("GET", "/admin/conversations/k2", body = Contract.maryMsgr)
        assertEquals("7123456789012345", api().get("k2").externalId)
        fake.on("GET", "/admin/conversations/nope", code = 404, body = """{"detail":"conversation not found"}""")
        val e = runCatching { api().get("nope") }.exceptionOrNull() as ApiException
        assertEquals(404, e.status); assertEquals("conversation not found", e.detail)
    }

    @Test fun resolve_sendsKeyAndRef_andRevealsTheThread() {
        fake.on("GET", "/admin/conversations/resolve", body = Contract.resolved)
        fake.on("GET", "/admin/conversations/k2", body = Contract.maryMsgr)
        fake.on("GET", "/admin/conversations", body = Contract.page(Contract.peterWa))
        val (dash, vm) = vm()
        dash.openConvKey.value = "+250788123456|BH-1042"
        val q = calls("GET", "/admin/conversations/resolve").single().query
        assertEquals("key=250788123456&ref=BH-1042", q)
        assertEquals("k2", vm.thread.value.activeId)
        assertTrue("k2" in vm.inbox.value.orderIds)
    }

    @Test fun resolve_null_warnsToInvite() {
        fake.on("GET", "/admin/conversations/resolve", body = Contract.unresolved)
        val (dash, _) = vm()
        dash.openConvKey.value = "250788000000"
        assertEquals("No conversation yet — they haven't messaged. Use Invite to WhatsApp.", toasts.last().message)
    }

    // ═══════════════ The thread: messages, paging, activity, window ═══════════════

    @Test fun messages_decodeTheRealShape_nullsAndAll() {
        val (_, vm) = vm()
        vm.select("k2")
        assertEquals("limit=50", calls("GET", "/admin/conversations/k2/messages").last().query)
        val m = vm.thread.value.messages["k2"]!!.associateBy { it.id }
        assertEquals(6, m.size)
        assertEquals("Hello, do you deliver to Kigali?", m["m1"]!!.translation); assertEquals("French", m["m1"]!!.translatedFrom)
        assertTrue(m["evt-9f1"]!!.isSystem); assertEquals("escalated", m["evt-9f1"]!!.eventKind)
        assertNull(m["m2"]!!.text); assertEquals("image", m["m2"]!!.mediaType); assertEquals("A purple clergy stole", m["m2"]!!.mediaCaption)
        assertEquals("m1", m["m3"]!!.replyTo!!.id); assertEquals("user", m["m3"]!!.replyTo!!.sender)
        assertTrue(m["m4"]!!.isNote)
        assertEquals("p_77", m["m5"]!!.commentContext!!.postId); assertNull(m["m5"]!!.commentContext!!.thumb)
        // The thread reads French → the translate toggle starts ON (threadLang from inbound rows).
        assertEquals("French", vm.threadLang())
    }

    /** One malformed row (or a non-object comment_context) must not blank the thread. */
    @Test fun messages_aBadRowDropsOut_theRestShow() = runBlocking {
        fake.on("GET", "/admin/conversations/[^/]+/messages", body = """[
          {"id":"ok1","type":"message","direction":"inbound","sender":"user","text":"hi","created_at":"${InboxFixtures.iso(3)}"},
          {"id":"bad","type":"message","direction":"inbound","sender":"user","text":{"oops":1},"created_at":"${InboxFixtures.iso(2)}"},
          {"id":"ok2","type":"message","direction":"inbound","sender":"user","text":"[comment] hey","comment_context":"legacy-string","created_at":"${InboxFixtures.iso(1)}"}
        ]""")
        val msgs = api().messages("k1")
        assertEquals(listOf("ok1", "ok2"), msgs.map { it.id })
        assertNull(msgs[1].commentContext)
    }

    @Test fun messages_aNonArrayIsAnError_notAnEmptyThread() {
        fake.on("GET", "/admin/conversations/[^/]+/messages", body = """{"detail":"weird"}""")
        val (_, vm) = vm()
        vm.select("k2")
        assertTrue(vm.thread.value.error)
    }

    /** `before` is the oldest row's created_at verbatim — its "+00:00" must reach FastAPI as "+", not a space. */
    @Test fun olderPage_encodesTheOffset() {
        fake.on("GET", "/admin/conversations/[^/]+/messages") { r, _ ->
            200 to if (r.url.queryParameter("before") != null) "[]" else InboxFixtures.plainPage("n", 50, 100).replace(Regex("\"created_at\":\"[^\"]+\"")) { "\"created_at\":\"${InboxFixtures.iso(100)}\"" }
        }
        val (_, vm) = vm()
        vm.select("k1")
        vm.loadOlder()
        val q = calls("GET", "/admin/conversations/k1/messages").last().query!!
        assertTrue(q, q.startsWith("limit=50&before="))
        assertTrue(q, q.contains("%2B00%3A00"))
        assertEquals(false, vm.thread.value.hasMore["k1"])   // an empty older page: the start of the thread
    }

    @Test fun activity_decodes_blankDetailsHidden_labelLessDropped() = runBlocking {
        val ev = api().activity("k1")
        assertEquals(listOf("icpt-1", "act-2", "ord-3", "tool-4"), ev.map { it.id })
        assertEquals("", ev[1].detail.orEmpty()); assertNull(ev[2].at); assertNull(ev[3].detail)
        fake.on("GET", "/admin/conversations/[^/]+/activity", body = """{"events":[{"id":"x","kind":"deal","label":null},{"kind":"call","label":"Call ended · 1:04","at":null}]}""")
        val ev2 = api().activity("k1")
        assertEquals(1, ev2.size); assertEquals("Call ended · 1:04", ev2.single().label)
    }

    @Test fun window_decodesEveryMode() {
        for ((fixture, mode) in listOf(InboxFixtures.windowOpen() to "open", InboxFixtures.windowHumanAgent() to "human_agent", InboxFixtures.windowClosed() to "closed",
            """{"mode":"n/a","channel":"facebook"}""" to "n/a")) {
            fake.on("GET", "/admin/conversations/[^/]+/window", body = fixture)
            val (_, vm) = vm()
            vm.select("k1")
            val w = vm.thread.value.window!!
            assertEquals(mode, w.mode)
            if (mode == "closed") assertEquals("Outside the messaging window — an approved template is the only way in", w.reason)
            if (mode == "n/a") assertNull(w.expiresAt)
        }
    }

    // ═══════════════ Replies ═══════════════

    @Test fun reply_bodyKeysAreExactlyTheServers() {
        fake.on("POST", "/admin/conversations/k1/translate-reply", body = Contract.untranslated)
        val (_, vm) = vm()
        vm.select("k1")
        vm.toggleTx() // this thread reads French → toggle it OFF: plain English goes out
        vm.setReplyText("Yes, Friday.")
        vm.sendReply()
        val b = body("POST", "/admin/conversations/k1/reply")
        assertEquals(setOf("text", "client_msg_id"), b.keys)
        assertEquals("Yes, Friday.", b.str("text"))
        // The outbox bubble's id: the server sends each id once, so a resend
        // after a lost answer can't reach the customer twice.
        assertTrue(b.str("client_msg_id").orEmpty().isNotBlank())
        assertEquals("", vm.composer.value.replyText)
        assertTrue(toasts.none { it.type == ToastType.Error })
    }

    @Test fun reply_translated_carriesTheEnglishAlong() {
        fake.on("POST", "/admin/conversations/k1/translate-reply", body = Contract.translated)
        val (_, vm) = vm()
        vm.select("k1")
        vm.setReplyText("Yes, we deliver Friday.")
        vm.sendReply()
        assertEquals("""{"text":"Yes, we deliver Friday."}""", calls("POST", "/admin/conversations/k1/translate-reply").last().body)
        val b = body("POST", "/admin/conversations/k1/reply")
        assertEquals(setOf("text", "client_msg_id", "original_text", "original_lang"), b.keys)
        assertEquals("Oui, nous livrons vendredi.", b.str("text"))
        assertEquals("Yes, we deliver Friday.", b.str("original_text")); assertEquals("French", b.str("original_lang"))
    }

    /** 200 {ok:false, error} is a DELIVERY failure: the text comes back and the reason is shown. */
    @Test fun reply_okFalse_isAFailure() {
        fake.on("POST", "/admin/conversations/k1/reply", body = Contract.replyFailed)
        val (_, vm) = vm()
        vm.select("k1"); vm.toggleTx()
        vm.setReplyText("Hello"); vm.sendReply()
        assertEquals("Hello", vm.composer.value.replyText)
        assertEquals("Couldn't send the reply: (#10) This message is sent outside of allowed window.", toasts.last().message)
        assertTrue(vm.thread.value.messages["k1"]!!.none { it.id.startsWith("optimistic-") })
    }

    @Test fun reply_409And400_showTheServersReason() {
        val (_, vm) = vm()
        vm.select("k1"); vm.toggleTx()
        for ((code, bodyJson, msg) in listOf(
            Triple(409, Contract.replyLocked, "Conversation is handled by Grace Wanjiru."),
            Triple(400, Contract.replySms, "SMS is receive-only — Neema cannot send SMS. Reach this customer on WhatsApp or by phone."),
        )) {
            fake.on("POST", "/admin/conversations/k1/reply", code = code, body = bodyJson)
            vm.setReplyText("Hi"); vm.sendReply()
            assertEquals(msg, toasts.last().message); assertEquals("Hi", vm.composer.value.replyText)
        }
    }

    /** Sent, then the refetch fails: still a success — never restore the text for a second send. */
    @Test fun reply_sentButRefetchFails_isStillSent() {
        val (_, vm) = vm()
        vm.select("k1"); vm.toggleTx()
        fake.on("GET", "/admin/conversations/[^/]+/messages", code = 502, body = "<html>Bad Gateway</html>")
        vm.setReplyText("On its way"); vm.sendReply()
        assertEquals("", vm.composer.value.replyText)
        assertTrue(toasts.none { it.type == ToastType.Error })
        assertTrue(vm.thread.value.messages["k1"]!!.any { it.id.startsWith("optimistic-") && it.body == "On its way" })
    }

    @Test fun note_bodyAndServerRow_andARefetchFailureIsNotAFailedSave() {
        val (_, vm) = vm()
        vm.select("k1")
        fake.on("POST", "/admin/conversations/k1/note", body = Contract.note("Repeat buyer"))
        fake.on("GET", "/admin/conversations/[^/]+/messages", code = 500, body = """{"detail":"db"}""")
        vm.showNote(true); vm.setNoteText("Repeat buyer"); vm.saveNote()
        assertEquals("""{"text":"Repeat buyer"}""", calls("POST", "/admin/conversations/k1/note").single().body)
        assertFalse(vm.dialogs.value.note)
        assertEquals("Note saved", toasts.last().message)
    }

    // ═══════════════ Drafts, ask, answer ═══════════════

    @Test fun drafts_latestGenerateApprove_bodiesAndErrors() {
        fake.on("GET", "/admin/conversations/k1/latest-draft", body = Contract.latestDraft)
        val (_, vm) = vm()
        vm.select("k1")   // human-held → the latest held draft shows as the pill
        assertTrue(vm.composer.value.draftVisible); assertFalse(vm.composer.value.draftExpanded)

        fake.on("POST", "/admin/conversations/k1/generate-draft", body = Contract.generated)
        vm.generateDraft()
        assertEquals("{}", calls("POST", "/admin/conversations/k1/generate-draft").single().body)
        assertEquals("Yes Father — Nyeri by Friday. Shall I send the M-Pesa details?", vm.composer.value.draftText)

        fake.on("POST", "/admin/conversations/k1/generate-draft", code = 422, body = Contract.generateNoMessages)
        vm.generateDraft()
        assertEquals("Failed to generate draft", toasts.last().message); assertFalse(vm.composer.value.generatingDraft)

        // approve_draft answers the sent ROW, not {ok}: a success all the same.
        fake.on("POST", "/admin/conversations/k1/approve-draft", body = Contract.approved("Yes Father"))
        vm.setDraftText("Yes Father"); vm.approveDraft()
        assertEquals("""{"text":"Yes Father"}""", calls("POST", "/admin/conversations/k1/approve-draft").last().body)
        assertEquals("AI draft approved & sent", toasts.last().message)

        // No text → {"text": null}: the server sends its own held draft.
        vm.dismissDraft(); vm.approveDraft()
        assertEquals(JsonNull, body("POST", "/admin/conversations/k1/approve-draft")["text"])

        fake.on("POST", "/admin/conversations/k1/approve-draft", code = 422, body = Contract.noDraft)
        vm.setDraftText("x"); vm.approveDraft()
        assertEquals("Failed to approve draft", toasts.last().message)
        assertTrue(vm.composer.value.draftVisible && vm.composer.value.draftExpanded)
    }

    @Test fun approve_sentButRefetchFails_neverBringsTheDraftBack() {
        val (_, vm) = vm()
        vm.select("k1")
        fake.on("GET", "/admin/conversations/[^/]+/messages", code = 500, body = """{"detail":"db"}""")
        vm.setDraftText("Yes Father"); vm.approveDraft()
        assertEquals("AI draft approved & sent", toasts.last().message)
        assertFalse(vm.composer.value.draftVisible)
    }

    @Test fun ask_andAnswer_bodiesAndThe409() = runBlocking {
        fake.on("POST", "/admin/conversations/k1/ask", body = Contract.answer)
        fake.on("POST", "/admin/conversations/k1/answer", body = Contract.sent)
        val (_, vm) = vm()
        vm.select("k1")
        assertEquals("Collar 16 inch, chest 42 — from BH-1042.", vm.askNeema("What were his sizes?"))
        assertEquals("""{"question":"What were his sizes?"}""", calls("POST", "/admin/conversations/k1/ask").single().body)
        assertEquals(true to "Neema sent: “Yes Reverend — KES 12,500, ready in 5 days 🙏”", vm.answerViaNeema("yes, KES 12,500"))
        assertEquals("""{"facts":"yes, KES 12,500"}""", calls("POST", "/admin/conversations/k1/answer").single().body)
        fake.on("POST", "/admin/conversations/k1/answer", code = 409, body = Contract.outsideWindow)
        assertEquals(false to "Outside the messaging window — reply yourself when they next write.", vm.answerViaNeema("x"))
        fake.on("POST", "/admin/conversations/k1/answer", code = 422, body = """{"detail":"facts is required — what the team confirmed"}""")
        assertEquals(false to "Couldn't send right now — try again.", vm.answerViaNeema("x"))
        // A gateway error mid-turn may still end with Neema sending it: never "failed".
        fake.on("POST", "/admin/conversations/k1/answer", code = 502, body = "<html>502 Bad Gateway</html>")
        assertEquals(false to "No answer from the server — Neema may still be sending it. Watch the thread before sending it again.", vm.answerViaNeema("x"))
    }

    // ═══════════════ State and ownership ═══════════════

    @Test fun controls_bodiesPathsAndTheirRealAnswers() {
        val (_, vm) = vm()
        vm.select("k1")
        vm.intercept("k1"); vm.release("k1"); vm.pause("k1"); vm.transfer(Fixtures.AGENT2_ID, "Grace Wanjiru")
        for (a in listOf("intercept", "release", "pause")) assertEquals("{}", calls("POST", "/admin/conversations/k1/$a").single().body)
        assertEquals("""{"agent_id":"${Fixtures.AGENT2_ID}"}""", calls("POST", "/admin/conversations/k1/transfer").single().body)
        assertTrue(toasts.none { it.type == ToastType.Error })
        assertEquals("Transferred to Grace Wanjiru", toasts.last().message)
        // The idempotent re-click answers a different envelope — still a success.
        fake.on("POST", "/admin/conversations/k1/intercept", body = Contract.interceptAlready)
        fake.on("POST", "/admin/conversations/k1/release", body = Contract.releaseAlready)
        vm.intercept("k1"); assertEquals("Conversation claimed — you now control replies", toasts.last().message)
        vm.release("k1"); assertEquals("Conversation released back to AI", toasts.last().message)
    }

    @Test fun controls_409s() {
        val (_, vm) = vm(role = "agent", superuser = false)
        vm.select("k1")
        fake.on("POST", "/admin/conversations/k1/intercept", code = 409, body = Contract.interceptConflict)
        vm.intercept("k1"); assertEquals("Already claimed by another agent", toasts.last().message)
        fake.on("POST", "/admin/conversations/k1/pause", code = 409, body = Contract.pauseConflict)
        vm.pause("k1"); assertEquals("Handled by another agent — they must pause it", toasts.last().message)
        assertTrue(vm.thread.value.busy.isEmpty())
    }

    @Test fun clearHistory_deleteAndThe403() {
        val (_, vm) = vm()
        vm.select("k1"); vm.showClear(true); vm.clearHistory()
        assertEquals(1, calls("DELETE", "/admin/conversations/k1/messages").size)
        assertEquals("Chat history cleared", toasts.last().message)
        fake.on("DELETE", "/admin/conversations/k1/messages", code = 403, body = Contract.clearForbidden)
        vm.clearHistory()
        assertEquals("You don't have permission to clear chat history", toasts.last().message)
    }

    // ═══════════════ Media ═══════════════

    /** upload_media(file: UploadFile, caption: Form) — the part names, the filename, the type, the caption. */
    @Test fun upload_multipartFieldsAndTheRowItReturns() = runBlocking {
        fake.on("POST", "/admin/conversations/k1/upload-media", body = Contract.uploaded("image", "https://api.bethanyhouse.co.ke/api/admin/media/ab.jpg", null))
        val item = PickedMedia("x", Uri.parse("content://media/photo.jpg"), "photo.jpg", "image/jpeg", 3, bytes = byteArrayOf(1, 2, 3), caption = "  The black one  ")
        val msg = api().upload(paparazzi.context.contentResolver, "k1", item)
        val b = calls("POST", "/admin/conversations/k1/upload-media").single().body!!
        assertTrue(b, b.contains("Content-Disposition: form-data; name=\"file\"; filename=\"photo.jpg\""))
        assertTrue(b, b.contains("Content-Type: image/jpeg"))
        assertTrue(b, b.contains("Content-Disposition: form-data; name=\"caption\"\r\nContent-Length: 13\r\n\r\nThe black one"))
        assertEquals("srv-u1", msg.id); assertEquals("image", msg.mediaType); assertNull(msg.text)
        // No caption → no caption part at all (the server's Form(None)).
        api().upload(paparazzi.context.contentResolver, "k1", item.copy(caption = " "))
        assertFalse(calls("POST", "/admin/conversations/k1/upload-media").last().body!!.contains("name=\"caption\""))
    }

    @Test fun upload_errorsReadAsTheServerWrote_orPlainly() {
        fun err(code: Int, body: String) = ApiException(code, "POST", "/admin/conversations/k1/upload-media", body)
        assertEquals("Image too large — max 5 MB.", uploadErrorOf(err(413, Contract.tooLarge)))
        assertEquals("Unsupported media type: video/webm", uploadErrorOf(err(415, Contract.unsupported)))
        assertEquals("Couldn't convert this video for WhatsApp — try a shorter clip or export it as MP4 (H.264).", uploadErrorOf(err(422, Contract.unconvertible)))
        assertEquals("too large to upload", uploadErrorOf(err(413, Contract.proxyTooLarge)))
        assertEquals("the server couldn't process this file", uploadErrorOf(err(422, Contract.pydantic422)))
        assertEquals("upload timed out — check your connection and try again", uploadErrorOf(ApiException(0, "POST", "/x", "timed out after 30s")))
        assertEquals("Internal Server Error", uploadErrorOf(err(500, "Internal Server Error")))
    }

    @Test fun upload_onlyWhatTheServerAccepts() {
        for (ok in listOf("image/jpeg" to "a.jpg", "video/quicktime" to "a.mov", "audio/ogg" to "a.ogg", "application/pdf" to "a.pdf",
            "application/octet-stream" to "IMG_1.MOV", "" to "clip.m4v")) assertTrue(ok.toString(), uploadable(ok.first, ok.second))
        for (bad in listOf("video/webm" to "a.webm", "audio/mp4" to "a.m4a", "image/heic" to "a.heic", "application/zip" to "a.zip",
            "application/octet-stream" to "a.bin")) assertFalse(bad.toString(), uploadable(bad.first, bad.second))
    }

    /** A 413 on the second of two files: one sent, one failed, the server's reason named. */
    @Test fun sendMedia_partialFailure() {
        var n = 0
        fake.on("POST", "/admin/conversations/k1/upload-media") { _, _ ->
            if (n++ == 0) 200 to Contract.uploaded("document", "https://api.bethanyhouse.co.ke/api/admin/media/m.pdf", "Measurements") else 413 to Contract.tooLarge
        }
        val (_, vm) = vm()
        vm.select("k1")
        val f = ConversationsViewModel::class.java.getDeclaredField("_composer").apply { isAccessible = true }
        @Suppress("UNCHECKED_CAST") val comp = f.get(vm) as kotlinx.coroutines.flow.MutableStateFlow<ComposerUi>
        comp.value = comp.value.copy(media = listOf(
            PickedMedia("1", Uri.parse("content://m/a.pdf"), "Measurements.pdf", "application/pdf", 3, bytes = byteArrayOf(1, 2, 3)),
            PickedMedia("2", Uri.parse("content://m/b.jpg"), "big.jpg", "image/jpeg", 3, bytes = byteArrayOf(1, 2, 3)),
        ))
        vm.sendMedia()
        assertTrue(toasts.any { it.message == "big.jpg: Image too large — max 5 MB." })
        assertEquals("Sent 1, 1 failed", toasts.last().message)
        assertTrue(vm.thread.value.messages["k1"]!!.any { it.id == "srv-u1" && it.mediaType == "document" })
        // Input is sacred: the file that failed stays in the tray, with why, for a retry.
        assertEquals(listOf("big.jpg"), vm.composer.value.media.map { it.name })
        assertEquals("Image too large — max 5 MB.", vm.composer.value.media.single().error)
        assertFalse(vm.composer.value.uploading)
    }

    @Test fun replyMedia_bodyKeys() = runBlocking {
        val dash = dashboard(paparazzi.context, fake)
        fake.on("POST", "/admin/conversations/k1/reply-media", body = Contract.uploaded("image", "https://cdn/x.jpg", "Hi"))
        val m = dash.api.conversations.sendMediaUrl("k1", "https://cdn/x.jpg", "image", "Hi", "x.jpg")
        assertEquals("""{"media_url":"https://cdn/x.jpg","media_type":"image","caption":"Hi","filename":"x.jpg"}""", calls("POST", "/admin/conversations/k1/reply-media").single().body)
        assertEquals("srv-u1", m.id)
    }

    @Test fun recoverMedia_pathBody_andTheUnrecoverable404() {
        val (_, vm) = vm()
        vm.select("k1")
        fake.on("POST", "/admin/messages/m2/recover-media", body = Contract.recovered)
        var got: Recovery? = null
        vm.recoverMedia("m2") { got = it }
        assertEquals("{}", calls("POST", "/admin/messages/m2/recover-media").single().body)
        assertEquals(Recovery.Found("https://api.bethanyhouse.co.ke/api/admin/media/rehosted.jpg"), got)
        assertEquals((got as Recovery.Found).url, vm.thread.value.recovered["m2"])
        fake.on("POST", "/admin/messages/m9/recover-media", code = 404, body = Contract.recoverGone)
        vm.recoverMedia("m9") { got = it }
        assertEquals(Recovery.Gone, got)
    }

    @Test fun postVideo_pathEncodingAndChannel() = runBlocking {
        val dash = dashboard(paparazzi.context, fake)
        fake.on("GET", "/admin/post-video/.+", body = Contract.postVideo)
        assertEquals("https://video.xx.fbcdn.net/v/t42/reel.mp4?oe=1", dash.api.conversations.postVideo("1784_99", "instagram"))
        val c = fake.calls.last()
        assertEquals("/admin/post-video/1784_99", c.path); assertEquals("channel=instagram", c.query)
    }

    // ═══════════════ WhatsApp invite ═══════════════

    @Test fun invite_bodyAndFailure() {
        val (_, vm) = vm()
        vm.select("k2")
        fake.on("POST", "/admin/whatsapp-invite", body = Contract.invited)
        assertEquals(ConversationsViewModel.InviteResult.Sent, runBlocking { vm.invite("250788123456", "Rev. Mary Achieng") })
        assertEquals("""{"phone":"250788123456","name":"Rev. Mary Achieng"}""", calls("POST", "/admin/whatsapp-invite").last().body)
        fake.on("POST", "/admin/whatsapp-invite", code = 400, body = Contract.inviteBadPhone)
        assertEquals(ConversationsViewModel.InviteResult.Refused, runBlocking { vm.invite("123", null) })
        assertEquals("""{"phone":"123"}""", calls("POST", "/admin/whatsapp-invite").last().body)
    }

    /** Carry-over 1: the thread menu offers the invite only as CustomerSidebar does. */
    @Test fun inviteShortcut_followsTheProfile() {
        val profile = { phone: String?, channels: String ->
            """{"id":"7123456789012345","wa_id":null,"name":"Rev. Mary Achieng","phone":${phone?.let { "\"$it\"" } ?: "null"},"lead_stage":"new","channels":$channels,"merged_ids":[]}"""
        }
        val msgr = """[{"channel":"messenger","identifier":null,"conversation_count":1}]"""
        // A Messenger customer with a captured phone and no WhatsApp thread → offered, to THAT phone.
        fake.on("GET", "/admin/customers/7123456789012345", body = profile("+250 788 123 456", msgr))
        var v = vm().second
        v.select("k2")
        assertEquals("channel=messenger", calls("GET", "/admin/customers/7123456789012345").last().query)
        assertEquals("250788123456", inviteTarget(v.thread.value.reach, "k2"))
        // No phone on the profile → not offered.
        fake.on("GET", "/admin/customers/7123456789012345", body = profile(null, msgr))
        v = vm().second; v.select("k2")
        assertNull(inviteTarget(v.thread.value.reach, "k2"))
        // Already on WhatsApp (per the profile's channels) → not offered.
        fake.on("GET", "/admin/customers/7123456789012345", body = profile("+250788123456", """[{"channel":"whatsapp","identifier":"250788123456"}]"""))
        v = vm().second; v.select("k2")
        assertNull(inviteTarget(v.thread.value.reach, "k2"))
        // The profile can't be read → hidden, never guessed.
        fake.on("GET", "/admin/customers/7123456789012345", code = 500, body = """{"detail":"x"}""")
        v = vm().second; v.select("k2")
        assertNull(inviteTarget(v.thread.value.reach, "k2"))
        // A person whose WhatsApp thread is in the list needs no lookup at all (Peter on Facebook).
        val before = fake.calls.count { it.path.startsWith("/admin/customers/") }
        v = vm().second; v.select("k6")
        assertEquals(before, fake.calls.count { it.path.startsWith("/admin/customers/") })
        assertNull(inviteTarget(v.thread.value.reach, "k6"))
        // A web visitor's hash is never a phone, even with 7–15 digits in it.
        assertNull(inviteTarget(Reach("k5", "web_3fa9c1e20b7d4c5a9e11", false), "k5"))
        // A 20-digit PSID is not a phone either.
        assertNull(inviteTarget(Reach("k2", "25898765432101234567", false), "k2"))
        // A stale answer for another thread never shows.
        assertNull(inviteTarget(Reach("k1", "+250788123456", false), "k2"))
    }

    // ═══════════════ Live frames (what app/services, app/agent and app/routers publish) ═══════════════

    /** The WhatsApp webhook / meta_webhook / sms / public forms publish INBOUND frames with no `direction`. */
    @Test fun ws_inboundFrameWithoutDirection_isInbound() {
        val (dash, vm) = vm()
        vm.select("k2")
        socket(dash, """{"type":"new_message","conversationId":"k2","channel":"messenger","sender":"user","text":"Still there?","mediaType":null,"mediaUrl":null}""")
        val m = vm.thread.value.messages["k2"]!!.last()
        assertEquals("Still there?", m.body); assertTrue(m.inbound); assertEquals("user", m.sender)
        // n8n_bridge's inbound WhatsApp frame: media fields, no id / direction.
        socket(dash, """{"type":"new_message","conversationId":"k2","waId":"250788123456","sender":"user","text":"[image]","mediaType":"image","mediaId":"wamid.M2","mediaUrl":"https://x/p.jpg","mediaCaption":null,"mimeType":"image/jpeg","filename":null}""")
        val img = vm.thread.value.messages["k2"]!!.last()
        assertTrue(img.inbound); assertEquals("image/jpeg", img.mimeType); assertEquals("wamid.M2", img.mediaId)
    }

    /** The SMS bridge also pings agents:all with `event: notification, type: new_message` — not a message. */
    @Test fun ws_notificationFrames_neverPaintBubbles() {
        val (dash, vm) = vm()
        vm.select("k2")
        val n = vm.thread.value.messages["k2"]!!.size
        socket(dash, """{"event":"notification","type":"new_message","title":"SMS to the business number from +250788","body":"hi","conversationId":"k2"}""")
        socket(dash, """{"event":"notification","type":"draft_ready","title":"✍️ Draft ready — one tap to send","body":"x","conversationId":"k2"}""")
        assertEquals(n, vm.thread.value.messages["k2"]!!.size)
        assertFalse(vm.composer.value.draftVisible)
    }

    /** send_agent_reply's echo has no id: once the refetch holds the real row, it must not double up. */
    @Test fun ws_ourReplyEcho_afterTheRefetch_isNotADuplicate() {
        var serverHasIt = false
        fake.on("GET", "/admin/conversations/[^/]+/messages") { _, _ ->
            val extra = if (serverHasIt) """,{"id":"srv-r1","type":"message","direction":"outbound","sender":"human_agent","text":"On its way","isNote":false,"created_at":"${InboxFixtures.iso(0)}"}""" else ""
            200 to Contract.thread().trimEnd().removeSuffix("]") + extra + "]"
        }
        fake.on("POST", "/admin/conversations/k1/reply") { _, _ -> serverHasIt = true; 200 to Contract.replySent("On its way") }
        val (dash, vm) = vm()
        vm.select("k1"); vm.toggleTx()
        vm.setReplyText("On its way"); vm.sendReply()
        socket(dash, """{"type":"new_message","conversationId":"k1","sender":"human_agent","text":"On its way","replyTo":null,"translation":null,"translatedFrom":null}""")
        assertEquals(1, vm.thread.value.messages["k1"]!!.count { it.body == "On its way" })
        // Same words from a different sender (m3 is the human's; this is Neema's) are a new line.
        socket(dash, """{"type":"new_message","conversationId":"k1","sender":"ai","text":"Oui, 5 jours."}""")
        assertEquals(1, vm.thread.value.messages["k1"]!!.count { it.body == "Oui, 5 jours." && it.sender == "ai" })
        // …but a customer who says "ok" twice is heard twice.
        socket(dash, """{"type":"new_message","conversationId":"k1","sender":"user","text":"ok"}""")
        socket(dash, """{"type":"new_message","conversationId":"k1","sender":"user","text":"ok"}""")
        assertEquals(2, vm.thread.value.messages["k1"]!!.count { it.body == "ok" })
    }

    /** The AI reply frame (n8n_bridge) carries the DB id and, for voice, the media. */
    @Test fun ws_aiReplyAndTranslationsAndPills() {
        val (dash, vm) = vm()
        vm.select("k1")
        socket(dash, """{"type":"new_message","id":"ai-1","conversationId":"k1","sender":"ai","text":"Sawa","mediaType":"audio","mediaUrl":"https://x/r.ogg","mediaCaption":"🛒 2 × Shirt"}""")
        socket(dash, """{"type":"new_message","id":"ai-1","conversationId":"k1","sender":"ai","text":"Sawa"}""")
        val ai = vm.thread.value.messages["k1"]!!.filter { it.id == "ai-1" }
        assertEquals(1, ai.size); assertFalse(ai.single().inbound); assertEquals("🛒 2 × Shirt", ai.single().mediaCaption)
        // translate.py: {type:"translations", items:[{id, text, lang}]} — lang may be null.
        socket(dash, """{"type":"translations","conversationId":"k1","items":[{"id":"m5","text":"Price?","lang":null}]}""")
        assertEquals("Price?", vm.thread.value.messages["k1"]!!.first { it.id == "m5" }.translation)
        // record_escalation's frame has no agent; transfer's carries eventNote.
        socket(dash, """{"type":"intercept_changed","conversationId":"k1","eventKind":"escalated","eventReason":"Wants a quote"}""")
        socket(dash, """{"type":"intercept_changed","conversationId":"k1","mode":"human","assignedAgentId":"${Fixtures.AGENT2_ID}","assignedAgentName":"Grace Wanjiru","eventKind":"transfer","eventAgentName":"Grace Wanjiru","eventNote":"Moses Mwicigi → Grace Wanjiru"}""")
        val live = vm.thread.value.messages["k1"]!!.filter { it.id.startsWith("live-evt-") }.associateBy { it.eventKind }
        assertEquals("Wants a quote", live["escalated"]!!.eventReason)
        assertEquals("Transferred — Moses Mwicigi → Grace Wanjiru", live["transfer"]!!.text)
        // copilot / runtime ai_draft_ready.
        socket(dash, """{"type":"ai_draft_ready","conversationId":"k1","waId":"254712345678","draft":"Yes Father"}""")
        assertEquals("Yes Father", vm.composer.value.draftText)
        // clear_chat_history.
        socket(dash, """{"type":"history_cleared","conversationId":"k1","clearedBy":"Grace Wanjiru"}""")
        assertTrue(vm.thread.value.messages["k1"]!!.isEmpty())
        assertEquals("History cleared by Grace Wanjiru", toasts.last().message)
    }
}
