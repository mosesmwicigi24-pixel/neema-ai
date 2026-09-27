package ke.co.bethanyhouse.neema.conversations

import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.Toast
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.conversations.AlbumItem
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel
import ke.co.bethanyhouse.neema.feature.conversations.InboxBack
import ke.co.bethanyhouse.neema.feature.conversations.InboxMemory
import ke.co.bethanyhouse.neema.feature.conversations.MEMORY_KEY
import ke.co.bethanyhouse.neema.feature.conversations.SavedComposer
import ke.co.bethanyhouse.neema.feature.conversations.SavedMedia
import ke.co.bethanyhouse.neema.feature.conversations.Viewer
import ke.co.bethanyhouse.neema.feature.conversations.ViewerSaver
import ke.co.bethanyhouse.neema.feature.conversations.inboxBackStep
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.InboxFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures
import ke.co.bethanyhouse.neema.testing.fixtures.InboxNetFixtures.row
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
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
 * Round 9 — lifecycle and state. What a phone does to the app: rotation
 * (the ViewModel survives; UI state is saveable), Android killing the process
 * in the background (a fresh DashboardViewModel + ConversationsViewModel on
 * the same disk — the inbox's [InboxMemory]), a 401 in the middle of a send,
 * a deep link or a notification tap landing while the agent is mid-task,
 * sign-out on a shared phone, and system back.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class InboxLifecycleTest {
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

    private class App(val dash: DashboardViewModel, val vm: ConversationsViewModel, val owner: Owner)

    private fun start(dash: DashboardViewModel = dashboard(paparazzi.context, fake)): App {
        scope.launch { dash.toasts.collect { toasts += it } }
        val owner = Owner()
        val vm = ViewModelProvider.create(owner, viewModelFactory { initializer { ConversationsViewModel(dash) } })[ConversationsViewModel::class]
        return App(dash, vm, owner)
    }

    /**
     * Android kills the process: nothing is torn down politely (no onCleared),
     * the in-memory state is gone, and a fresh app starts on the same disk.
     * The old ViewModel's work is stopped by clearing a COPY of the memory
     * file around its onCleared, so only what reached disk before counts.
     */
    private fun App.processDeath(before: () -> Unit = {}): App {
        val snaps = dash.container.snapshots
        val saved = snaps.read(Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer())
        owner.viewModelStore.clear()
        if (saved != null) snaps.write(Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer(), saved)
        else snaps.write(Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer(), InboxMemory())
        before()
        return start(DashboardViewModel(dash.container))
    }

    private fun idle(ms: Long) { sched.advanceTimeBy(ms); sched.runCurrent() }
    private fun memory(a: App) = a.dash.container.snapshots.read(Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer())
    private fun replies(conv: String = "c1") = fake.calls.count { it.method == "POST" && it.path == "/admin/conversations/$conv/reply" }
    private fun mine(vm: ConversationsViewModel, id: String = "c1") = vm.thread.value.messages[id].orEmpty().filter { it.id.startsWith("optimistic-") }

    // ═══════════════ The composer draft ═══════════════

    /** Each customer keeps their own draft (the web's single replyText would carry it to the next person). */
    @Test fun draft_isPerCustomer_andComesBackWhenSwitchingBack() {
        val a = start()
        a.vm.select("c1"); a.vm.setReplyText("For Fr. Peter")
        a.vm.select("c2"); assertEquals("", a.vm.composer.value.replyText)
        a.vm.setReplyText("For Rev. Mary")
        a.vm.select("c1"); assertEquals("For Fr. Peter", a.vm.composer.value.replyText)
        // The same person's other channel shares the draft (c5 is Fr. Peter on Facebook).
        a.vm.select("c5"); assertEquals("For Fr. Peter", a.vm.composer.value.replyText)
        a.vm.select("c2"); assertEquals("For Rev. Mary", a.vm.composer.value.replyText)
    }

    @Test fun processDeath_restoresTheOpenThread_theFilters_theSearch_andEveryDraft() {
        val a = start()
        a.vm.setTab("human")
        a.vm.select("c1")
        a.vm.setReplyText("Half a reply for Fr. Peter")
        a.vm.beginReplyTo(a.vm.thread.value.messages["c1"]!!.last { it.inbound })
        a.vm.select("c6")
        a.vm.setReplyText("Measurements — ")
        a.vm.showNote(true); a.vm.setNoteText("Call back after 5")
        idle(ConversationsViewModel.MEMORY_DEBOUNCE_MS + 50)
        // It reached disk after a pause in typing (no teardown needed).
        memory(a)!!.let { m ->
            assertEquals("c6", m.activeId); assertTrue(m.threadOpen); assertEquals("human", m.tab)
            assertEquals("Half a reply for Fr. Peter", m.composers["p:p1"]?.replyText)
        }

        val n = fake.calls.size
        val b = a.processDeath()
        // The first list request is already the restored filter's: no flash of "All".
        assertTrue(fake.calls.drop(n).first { it.method == "GET" && it.path == "/admin/conversations" }.query!!.contains("tab=human"))
        assertEquals("human", b.vm.inbox.value.filters.tab)
        assertEquals("c6", b.vm.thread.value.activeId)
        assertTrue(b.vm.thread.value.threadOpen)
        assertEquals("Measurements — ", b.vm.composer.value.replyText)
        b.vm.dialogs.value.let { assertTrue(it.note); assertEquals("Call back after 5", it.noteText) }
        b.vm.select("c1")
        assertEquals("Half a reply for Fr. Peter", b.vm.composer.value.replyText)
        assertNotNull("the quoted message comes back too", b.vm.composer.value.quoted)
        // The note stays with its own thread.
        assertFalse(b.vm.dialogs.value.note)
        b.vm.select("c6")
        assertEquals("Call back after 5", b.vm.dialogs.value.noteText)
    }

    @Test fun processDeath_inTheBackground_savesAtOnce_noDebounceNeeded() {
        val a = start()
        a.vm.select("c2")
        a.vm.setReplyText("Typed a moment before switching apps")
        a.dash.container.foreground.value = false   // Android may now kill it at any moment
        assertEquals("Typed a moment before switching apps", memory(a)!!.composers["c2"]?.replyText)
        val b = a.processDeath()
        assertEquals("c2", b.vm.thread.value.activeId)
        assertEquals("Typed a moment before switching apps", b.vm.composer.value.replyText)
    }

    @Test fun processDeath_searchAsTyped_comesBack_andRuns() {
        val a = start()
        a.vm.setSearch("Kamau")          // killed before the 300 ms pause ran the query
        a.dash.container.foreground.value = false
        val b = a.processDeath()
        assertEquals("Kamau", b.vm.list.value.search)
        assertEquals("Kamau", b.vm.inbox.value.filters.q)
        assertTrue(fake.calls.any { it.method == "GET" && it.path == "/admin/conversations" && it.query?.contains("q=Kamau") == true })
    }

    @Test fun restore_withNothingSaved_isAFreshInbox_noCrash() {
        val a = start()
        val b = a.processDeath()
        assertEquals("", b.vm.thread.value.activeId)
        assertEquals("all", b.vm.inbox.value.filters.tab)
        assertTrue(b.vm.rows.value.isNotEmpty())
    }

    /** A thread no longer on page one (or gone from the snapshot) is fetched by id and reopened. */
    @Test fun processDeath_openThreadNotOnPageOne_isFetchedAndReopened() {
        val a = start()
        a.vm.select("c4"); a.vm.setReplyText("Albs in M — ")
        a.dash.container.foreground.value = false
        val b = a.processDeath {
            fake.on("GET", "/admin/conversations", body = """{"items":[${InboxFixtures.conversations.filter { !it.contains("\"id\":\"c4\"") }.joinToString(",")}],"next_cursor":null}""")
        }
        assertEquals("c4", b.vm.thread.value.activeId)
        assertEquals("Albs in M — ", b.vm.composer.value.replyText)
        assertTrue(fake.called("GET", "/admin/conversations/c4"))
    }

    // ═══════════════ A send in flight when the app dies ═══════════════

    /** No answer came before the kill; the server had it: the bubble settles — never a second POST. */
    @Test fun processDeath_midSend_theServerHadIt_settles_neverSentTwice() {
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ -> InboxNetFixtures.timeout() }
        val a = start()
        a.vm.select("c1")
        a.vm.setReplyText("On its way"); a.vm.sendReply()
        idle(ConversationsViewModel.MEMORY_DEBOUNCE_MS + 50)
        assertEquals(1, memory(a)!!.outbox.size)
        val b = a.processDeath { server.rows += row("srv-1", "On its way") }
        assertTrue(mine(b.vm).isEmpty())
        assertEquals(1, b.vm.thread.value.messages["c1"]!!.count { it.body == "On its way" })
        assertEquals(1, replies())
    }

    /** The server never got it: after the checks it turns "Not sent" with Retry — nothing is lost, nothing duplicated. */
    @Test fun processDeath_midSend_theServerNeverGotIt_turnsNotSent_retrySendsOnce() {
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ -> InboxNetFixtures.timeout() }
        val a = start()
        a.vm.select("c1")
        a.vm.setReplyText("Lost in the air"); a.vm.sendReply()
        idle(ConversationsViewModel.MEMORY_DEBOUNCE_MS + 50)
        val b = a.processDeath()
        mine(b.vm).single().let { assertEquals("Lost in the air", it.body); assertEquals("sending", it.sendState) }
        idle(10_000)
        val failed = mine(b.vm).single()
        assertEquals("failed", failed.sendState)
        assertEquals(1, replies())
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ -> server.rows += row("srv-2", "Lost in the air"); 200 to """{"ok":true}""" }
        b.vm.retrySend(failed.id)
        assertEquals(2, replies())
        // Both attempts carry the same client_msg_id — even across the kill — so
        // had the first actually landed, the server would answer the second with
        // it instead of messaging the customer again.
        val ids = fake.calls.filter { it.method == "POST" && it.path == "/admin/conversations/c1/reply" }
            .map { kotlinx.serialization.json.Json.parseToJsonElement(it.body!!).let { j ->
                (j as kotlinx.serialization.json.JsonObject)["client_msg_id"].toString() } }
        assertEquals(1, ids.toSet().size)
        assertTrue(ids.first() != "null")
        assertTrue(mine(b.vm).isEmpty())
        assertEquals(1, b.vm.thread.value.messages["c1"]!!.count { it.body == "Lost in the air" })
    }

    /** A "Not sent" bubble (with its Edit / Retry) survives the kill; Edit puts the words back in the box. */
    @Test fun processDeath_notSentBubble_survives_andEditRestoresTheWords() {
        val a = start()
        a.vm.select("c1")
        // The agent is already typing the next thought when the refusal lands: it can't go back in the box.
        fake.on("POST", "/admin/conversations/c1/reply") { _, _ -> a.vm.setReplyText("Next thought"); 422 to """{"detail":"Outside the messaging window"}""" }
        a.vm.setReplyText("Third"); a.vm.sendReply()
        assertEquals("failed", mine(a.vm).single().sendState)
        idle(ConversationsViewModel.MEMORY_DEBOUNCE_MS + 50)
        val b = a.processDeath()
        val bubble = mine(b.vm).single()
        assertEquals("failed", bubble.sendState)
        assertEquals("Third", bubble.body)
        assertEquals("Next thought", b.vm.composer.value.replyText)
        b.vm.editFailed(bubble.id)
        assertTrue(mine(b.vm).isEmpty())
        assertTrue(b.vm.composer.value.replyText.contains("Third"))
    }

    // ═══════════════ 401 in the middle of a send ═══════════════

    @Test fun note_401_waitsForSignIn_thenSavesOnce() {
        var n = 0
        fake.on("POST", "/admin/conversations/c1/note") { _, _ ->
            if (n++ == 0) 401 to """{"detail":"Token expired"}""" else { server.rows += row("srv-n", "Internal: VIP", note = true); 200 to row("srv-n", "Internal: VIP", note = true) }
        }
        fake.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val a = start()
        a.vm.select("c1")
        a.vm.showNote(true); a.vm.setNoteText("Internal: VIP"); a.vm.saveNote()
        assertTrue(a.dash.sessionExpired.value)
        assertEquals(ConversationsViewModel.AUTH_HELD, mine(a.vm).single().sendError)
        fake.on("POST", "/(agent-auth|auth)/refresh", body = Fixtures.tokenResponse())
        a.dash.onReauthenticated()
        assertEquals(2, n)
        assertTrue(mine(a.vm).isEmpty())
        assertTrue(toasts.toString(), toasts.any { it.message == "Note saved" })
    }

    /** Files an expired session refused stay in the tray with their captions and go on sign-in — even if the agent moved on. */
    @Test fun media_401_staysInTheTray_andUploadsOnceAfterSignIn() {
        var n = 0
        fake.on("POST", "/admin/conversations/c1/upload-media") { _, _ ->
            if (n++ == 0) 401 to """{"detail":"Token expired"}"""
            else { server.rows += row("srv-v", "Fitting video", mediaType = "video"); 200 to row("srv-v", "Fitting video", mediaType = "video") }
        }
        fake.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val a = start()
        a.vm.select("c1")
        @Suppress("UNCHECKED_CAST")
        (ConversationsViewModel::class.java.getDeclaredField("_composer").apply { isAccessible = true }.get(a.vm) as kotlinx.coroutines.flow.MutableStateFlow<ke.co.bethanyhouse.neema.feature.conversations.ComposerUi>)
            .let { it.value = it.value.copy(media = listOf(ke.co.bethanyhouse.neema.feature.conversations.PickedMedia("v1", android.net.Uri.parse("content://m/clip.mp4"), "clip.mp4", "video/mp4", 1_000, bytes = byteArrayOf(1, 2, 3), caption = "Fitting video"))) }
        a.vm.sendMedia()
        assertTrue(a.dash.sessionExpired.value)
        a.vm.composer.value.media.single().let { assertEquals("Fitting video", it.caption); assertTrue(it.error!!.contains("sign in again")) }
        a.vm.select("c2")               // moved on while the dialog was up
        fake.on("POST", "/(agent-auth|auth)/refresh", body = Fixtures.tokenResponse())
        a.dash.onReauthenticated()
        assertEquals(2, n)
        a.vm.select("c1")
        assertTrue(a.vm.composer.value.media.isEmpty())
    }

    /** Held for sign-in when the app dies: it comes back as "Not sent" with Retry — never sent on its own hours later. */
    @Test fun processDeath_withAHeldSend_offersRetry_doesNotSendByItself() {
        fake.on("POST", "/admin/conversations/c1/reply", code = 401, body = """{"detail":"Token expired"}""")
        fake.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val a = start()
        a.vm.select("c1"); a.vm.setReplyText("Held"); a.vm.sendReply()
        a.dash.container.foreground.value = false
        val b = a.processDeath {
            fake.on("POST", "/(agent-auth|auth)/refresh", body = Fixtures.tokenResponse())
            fake.on("POST", "/admin/conversations/c1/reply") { _, _ -> server.rows += row("srv-h", "Held"); 200 to """{"ok":true}""" }
        }
        val bubble = mine(b.vm).single()
        assertEquals("failed", bubble.sendState)
        assertTrue(bubble.sendError!!.contains("Tap Retry"))
        idle(30_000)
        assertEquals(1, replies())
        b.vm.retrySend(bubble.id)
        assertEquals(2, replies())
        assertTrue(mine(b.vm).isEmpty())
    }

    // ═══════════════ Deep links in every state ═══════════════

    /** A notification tap switches threads under an open note: the note waits with its own thread; a transfer never retargets. */
    @Test fun deepLink_whileANoteIsOpen_theNoteWaitsWithItsThread() {
        val a = start()
        a.vm.select("c1")
        a.vm.showNote(true); a.vm.setNoteText("Half a note about Fr. Peter")
        a.dash.openConversationFor("254722000111")   // Rev. Mary (c2)
        assertEquals("c2", a.vm.thread.value.activeId)
        a.vm.dialogs.value.let { assertFalse(it.note); assertEquals("", it.noteText) }
        a.vm.select("c1")
        a.vm.dialogs.value.let { assertTrue(it.note); assertEquals("Half a note about Fr. Peter", it.noteText) }
    }

    @Test fun deepLink_whileTransferOrClearIsOpen_closesThem() {
        val a = start()
        a.vm.select("c1")
        a.vm.showTransfer(true)
        a.dash.openConversationFor("254722000111")
        assertFalse(a.vm.dialogs.value.transfer)
        a.vm.showClear(true)
        a.dash.openConversationFor("254712345678")
        assertEquals("c1", a.vm.thread.value.activeId)
        assertFalse(a.vm.dialogs.value.clearConfirm)
    }

    /** Cold start from a notification: the link wins over the thread the app was killed on; drafts still come back. */
    @Test fun coldStart_deepLink_beatsTheRestoredThread() {
        val a = start()
        a.vm.select("c1"); a.vm.setReplyText("Keep me")
        a.dash.container.foreground.value = false
        val snaps = a.dash.container.snapshots
        val saved = snaps.read(Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer())
        a.owner.viewModelStore.clear()
        snaps.write(Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer(), saved!!)
        val dash = DashboardViewModel(a.dash.container)
        dash.applyDeepLink(open = "254722000111", ref = null, view = null, caller = null)
        val b = start(dash)
        assertEquals("c2", b.vm.thread.value.activeId)
        b.vm.select("c1")
        assertEquals("Keep me", b.vm.composer.value.replyText)
    }

    // ═══════════════ Sign-out on a shared phone ═══════════════

    @Test fun signOut_wipesTheAgentsWork_theNextSignInSeesNothing() {
        val a = start()
        a.vm.select("c1"); a.vm.setReplyText("Private words")
        a.dash.container.foreground.value = false
        assertEquals("Private words", memory(a)!!.composers["p:p1"]?.replyText)
        val session = a.dash.session.value!!
        a.dash.logout()
        a.owner.viewModelStore.clear()    // the agent store is dropped on sign-out
        assertTrue(memory(a)!!.isEmpty)
        a.dash.container.sessionStore.save(session)
        val b = start(DashboardViewModel(a.dash.container))
        assertEquals("", b.vm.thread.value.activeId)
        b.vm.select("c1")
        assertEquals("", b.vm.composer.value.replyText)
    }

    // ═══════════════ Files picked but not sent ═══════════════

    /** Android took back the read grant: the file can't come back — it is named, never silently dropped. */
    @Test fun processDeath_pickedFileNoLongerReadable_isNamedForReattaching() {
        val a = start()
        a.vm.select("c2")
        a.vm.setReplyText("See attached")
        a.dash.container.foreground.value = false
        val m = memory(a)!!
        a.dash.container.snapshots.write(
            Fixtures.ME_ID, MEMORY_KEY, InboxMemory.serializer(),
            m.copy(composers = m.composers + ("c2" to (m.composers["c2"] ?: SavedComposer()).copy(
                media = listOf(SavedMedia("content://com.android.providers.media.photopicker/gone/1", "cassock.jpg", "image/jpeg", 120_000, caption = "The purple one")),
            ))),
        )
        val b = a.processDeath()
        assertEquals("c2", b.vm.thread.value.activeId)
        assertEquals("See attached", b.vm.composer.value.replyText)
        assertTrue(b.vm.composer.value.media.isEmpty())
        assertEquals(listOf("cassock.jpg"), b.vm.composer.value.lostMedia)
        b.vm.dismissLostMedia()
        assertTrue(b.vm.composer.value.lostMedia.isEmpty())
    }

    // ═══════════════ Back, and saveable UI state ═══════════════

    @Test fun back_closesTheTopmostThingFirst() {
        assertEquals(InboxBack.CloseThread, inboxBackStep(phoneThread = true, selectMode = true, searching = true, filtersOpen = true))
        assertEquals(InboxBack.ExitSelect, inboxBackStep(phoneThread = false, selectMode = true, searching = true, filtersOpen = true))
        assertEquals(InboxBack.ClearSearch, inboxBackStep(phoneThread = false, selectMode = false, searching = true, filtersOpen = true))
        assertEquals(InboxBack.CloseFilters, inboxBackStep(phoneThread = false, selectMode = false, searching = false, filtersOpen = true))
        assertNull(inboxBackStep(phoneThread = false, selectMode = false, searching = false, filtersOpen = false))
    }

    /** Back from the thread keeps the draft (the web has no prompt here; the text is simply kept). */
    @Test fun back_fromTheThread_keepsTheDraft() {
        val a = start()
        a.vm.select("c1"); a.vm.setReplyText("Not finished")
        a.vm.closeThread()
        assertFalse(a.vm.thread.value.threadOpen)
        a.vm.select("c1")
        assertEquals("Not finished", a.vm.composer.value.replyText)
    }

    @Test fun viewerSaver_roundTripsEveryKind() {
        val scope = object : androidx.compose.runtime.saveable.SaverScope { override fun canBeSaved(value: Any) = true }
        fun rt(v: Viewer?): Viewer? = with(ViewerSaver) { scope.save(v) }?.let { ViewerSaver.restore(it) }
        assertEquals(Viewer.Image("https://neema.test/a.jpg"), rt(Viewer.Image("https://neema.test/a.jpg")))
        assertEquals(Viewer.Video("https://neema.test/v.mp4", "m1"), rt(Viewer.Video("https://neema.test/v.mp4", "m1")))
        assertEquals(Viewer.Video("https://neema.test/v.mp4", null), rt(Viewer.Video("https://neema.test/v.mp4", null)))
        val album = Viewer.Album(listOf(AlbumItem("a", "one"), AlbumItem("b", null), AlbumItem("c", "three")), 1)
        assertEquals(album, rt(album))
        assertNull(rt(null))
    }

    @Suppress("unused") private fun errors() = toasts.filter { it.type == ToastType.Error }
}
