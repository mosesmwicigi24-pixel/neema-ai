package ke.co.bethanyhouse.neema.customer

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerProfile
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerViewModel
import ke.co.bethanyhouse.neema.feature.conversations.customer.StageCache
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CustomerFixtures
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/**
 * The customer panel stays current while it is open, as CustomerSidebar.tsx's
 * loadProfile effect keeps the web's (it re-runs on every change to the thread
 * row) — and catches up on what a phone misses that a browser tab would not:
 * a socket that dropped, an app that went to the background, an order that
 * landed. Driven through the real socket ([FakeSocketFactory]), the real
 * notification centre and the fake backend, on virtual time.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CustomerLiveTest {
    // Paparazzi only to get an Android context on the JVM.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private val scheduler = TestCoroutineScheduler()
    private val main = UnconfinedTestDispatcher(scheduler)
    private val scope = CoroutineScope(main)
    private lateinit var fake: FakeNeema
    private lateinit var ws: FakeSocketFactory
    private lateinit var dash: DashboardViewModel
    private lateinit var baseOrders: String

    private val path = "/admin/customers/${CustomerFixtures.PETER}"
    private val row: Conversation get() = CustomerFixtures.conversation("c1")

    @Before fun setUp() {
        Dispatchers.setMain(main)
        StageCache.stages = null
        fake = FakeNeema.withFixtures().also(CustomerFixtures::install)
        // One fixed copy: the fixture's timestamps follow the wall clock, the server's do not.
        baseOrders = Fixtures.orders
        fake.on("GET", "/admin/orders", body = baseOrders)
        ws = FakeSocketFactory()
        dash = dashboard(paparazzi.context, fake, appDispatcher = main, wsFactory = ws)
        dash.container.notifications.start(dash.container.foreground)
        dash.container.socket.connect(Fixtures.ME_ID)
        ws.last.open()
    }

    @After fun tearDown() {
        dash.container.socket.disconnect()
        scope.cancel()
        Dispatchers.resetMain()
        StageCache.stages = null
    }

    private fun advance(ms: Long = CustomerViewModel.RELOAD_COALESCE_MS + 1) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }
    private fun gets(p: String = path) = fake.callsTo("GET", p).size

    private fun peter(edit: (String) -> String = { it }): CustomerProfile =
        NeemaJson.decodeFromString(CustomerProfile.serializer(), edit(CustomerFixtures.peter))

    /** A panel on screen for [conv]; [fetch] replaces the GET when a test must hold or reorder answers. */
    private fun shown(
        conv: Conversation = row,
        fetch: (suspend (String, String?) -> CustomerProfile)? = null,
    ): CustomerViewModel = CustomerViewModel(dash, conv, fetchProfile = fetch).also { it.onShown() }

    /** Answers that wait until the test releases them, in request order. */
    private class Held {
        val answers = mutableListOf<CompletableDeferred<CustomerProfile>>()
        val fetch: suspend (String, String?) -> CustomerProfile = { _, _ ->
            CompletableDeferred<CustomerProfile>().also { answers += it }.await()
        }
    }

    private fun ordersWith(extra: String) = baseOrders.trimEnd().removeSuffix("]") + ",$extra]"

    // ── Row changes (the web's loadProfile deps) ────────────────────────────

    @Test fun aStageTheAiSetsWhileThePanelIsOpenShowsUpWithoutReopening() {
        val vm = shown()
        assertEquals("proposal", vm.profile.value!!.leadStage)
        // The AI advanced the lead; the inbox's refetch hands the panel the moved row.
        fake.on("GET", path, body = CustomerFixtures.peter.replace("\"lead_stage\":\"proposal\"", "\"lead_stage\":\"negotiation\""))
        vm.sync(row.copy(leadStage = "negotiation"))
        assertEquals("coalesced: nothing leaves at once", 1, gets())
        advance()
        assertEquals(2, gets())
        assertEquals("negotiation", vm.profile.value!!.leadStage)
        assertFalse("a live reload never blanks the panel", vm.loading.value)
        assertFalse(vm.refreshing.value)
    }

    @Test fun aNewMessageRenameOrNewKeyOnTheRowEachReload() {
        val vm = shown()
        vm.sync(row.copy(lastMessageAt = "2026-09-26T09:00:00Z")); advance()
        vm.sync(row.copy(lastMessageAt = "2026-09-26T09:00:00Z", name = "Fr. P. Kamau")); advance()
        vm.sync(row.copy(lastMessageAt = "2026-09-26T09:00:00Z", name = "Fr. P. Kamau", ordersCount = 4)); advance()
        assertEquals(4, gets())
    }

    @Test fun aBurstOfRowUpdatesCostsOneRequest() {
        val vm = shown()
        // Twelve moves of the row 50 ms apart (a chatty customer, the inbox poll, a rename).
        repeat(12) { i ->
            vm.sync(row.copy(lastMessageAt = "2026-09-26T09:00:${(10 + i)}Z"))
            advance(50)
        }
        assertEquals(1, gets())
        advance()
        assertEquals(2, gets())
    }

    @Test fun anUnchangedRowOrAnotherThreadsRowCostsNothing() {
        val vm = shown()
        repeat(5) { vm.sync(row.copy()) }
        vm.sync(CustomerFixtures.conversation("c2"))
        advance()
        assertEquals(1, gets())
    }

    @Test fun aRowThatGainsAWaIdReloadsAgainstTheNewKey() {
        val psid = row.copy(waId = null, externalId = "PSID77", channel = "messenger")
        fake.on("GET", "/admin/customers/PSID77", body = CustomerFixtures.mary)
        val vm = shown(psid)
        assertEquals(1, gets("/admin/customers/PSID77"))
        vm.sync(psid.copy(waId = CustomerFixtures.MARY))
        advance()
        assertEquals(1, gets("/admin/customers/${CustomerFixtures.MARY}"))
    }

    @Test fun aQuietReloadThatFailsKeepsWhatIsPainted() {
        val vm = shown()
        fake.on("GET", path, code = 502, body = """{"detail":"hub down"}""")
        vm.sync(row.copy(lastMessageAt = "2026-09-26T09:00:00Z")); advance()
        assertEquals(2, gets())
        assertEquals("Fr. Peter Kamau", vm.profile.value!!.name)
        assertEquals("the real profile, not the fallback", 24, vm.profile.value!!.totalOrders)
        assertFalse(vm.refreshing.value)
    }

    // ── Out-of-order answers ────────────────────────────────────────────────

    @Test fun theNewestAnswerWinsWhenAnOlderOneLandsLate() {
        val held = Held()
        val vm = shown(fetch = held.fetch)
        held.answers[0].complete(peter())
        vm.load(showSpinner = false)            // answer 1: slow
        vm.load(showSpinner = false)            // answer 2: the newest
        held.answers[2].complete(peter { it.replace("\"lead_stage\":\"proposal\"", "\"lead_stage\":\"won\"") })
        held.answers[1].complete(peter { it.replace("\"lead_stage\":\"proposal\"", "\"lead_stage\":\"contacted\"") })
        assertEquals("won", vm.profile.value!!.leadStage)
        assertFalse(vm.refreshing.value)
    }

    @Test fun anAnswerThatLeftBeforeAnEditIsNotPaintedOverIt() {
        val held = Held()
        val vm = shown(fetch = held.fetch)
        held.answers[0].complete(peter())
        vm.load(showSpinner = false)            // a live reload in flight…
        vm.addTag("choir")                      // …the agent adds a tag (PATCH accepted)
        assertTrue("choir" in vm.profile.value!!.tags)
        held.answers[1].complete(peter())       // the pre-edit answer lands: no "choir"
        assertTrue("the optimistic edit survives the stale answer", "choir" in vm.profile.value!!.tags)
        // …and the reload runs again, now that the edit has settled.
        advance()
        assertEquals(3, held.answers.size)
        held.answers[2].complete(peter { it.replace("\"tags\":[\"vip\",\"clergy\",\"bulk\"]", "\"tags\":[\"vip\",\"clergy\",\"bulk\",\"choir\"]") })
        assertEquals(listOf("vip", "clergy", "bulk", "choir"), vm.profile.value!!.tags)
    }

    @Test fun aReloadAskedForMidSaveWaitsForTheSave() {
        lateinit var vm: CustomerViewModel
        var getsDuringSave = -1
        fake.on("PATCH", path) { _, _ ->
            // A pull-to-refresh and a row move land while the stage is being saved.
            vm.load(showSpinner = false)
            vm.sync(row.copy(lastMessageAt = "2026-09-26T09:00:00Z"))
            getsDuringSave = gets()
            200 to """{"ok":true}"""
        }
        vm = shown()
        vm.setStage("won")
        assertEquals("nothing is fetched over an unsettled save", 1, getsDuringSave)
        assertEquals("won", vm.profile.value!!.leadStage)
        advance()
        assertEquals("one catch-up fetch once it settled", 2, gets())
    }

    // ── Typing is never clobbered ───────────────────────────────────────────

    @Test fun theNotesDraftSurvivesALiveReloadAndKeepsItsBase() {
        val vm = shown()
        val base = vm.profile.value!!.notes!!
        vm.startEditNotes()
        vm.noteDraft.value = "$base\n\nWants gold thread on the stole."
        // A call summary is appended server-side while the agent types; the row moves.
        val summary = "Call summary: asked about delivery to Nyeri."
        fake.on("GET", path, body = CustomerFixtures.peter.replace("Ask about the Easter order in March.", "Ask about the Easter order in March.\\n\\n$summary"))
        vm.sync(row.copy(lastMessageAt = "2026-09-26T09:00:00Z")); advance()
        assertTrue(vm.profile.value!!.notes!!.endsWith(summary))
        assertTrue("still editing", vm.editNotes.value)
        assertEquals("$base\n\nWants gold thread on the stole.", vm.noteDraft.value)
        assertEquals(base, vm.notesBase.value)

        vm.saveNotes()
        val body = NeemaJson.parseToJsonElement(fake.callsTo("PATCH", path).last().body!!).jsonObject
        assertEquals("$base\n\nWants gold thread on the stole.", body["notes"]!!.jsonPrimitive.content)
        assertEquals("the snapshot the edit STARTED from, so the server keeps the summary", base, body["notes_base"]!!.jsonPrimitive.content)
        assertFalse(vm.editNotes.value)
        assertNull(vm.notesBase.value)
        // The server merged the summary back in: fetch what it kept.
        advance()
        assertEquals(3, gets())
    }

    @Test fun cancellingTheNotesEditDropsTheDraftAndBase() {
        val vm = shown()
        vm.startEditNotes()
        vm.noteDraft.value = "scratch"
        vm.cancelEditNotes()
        assertFalse(vm.editNotes.value)
        assertNull(vm.notesBase.value)
        assertTrue(fake.callsTo("PATCH", path).isEmpty())
        vm.startEditNotes()
        assertEquals("a fresh edit starts from the notes, not the old draft", vm.profile.value!!.notes, vm.noteDraft.value)
    }

    // ── Missed frames: foreground, reconnect ────────────────────────────────

    @Test fun comingBackToTheForegroundCatchesUp() {
        val vm = shown()
        dash.container.foreground.value = false
        advance()
        assertEquals(1, gets())
        dash.container.foreground.value = true
        advance()
        assertEquals(2, gets())
        assertFalse(vm.loading.value)
    }

    @Test fun aSocketReconnectCatchesUpOnFramesItMissed() {
        shown()
        ws.last.fail()
        assertFalse(dash.container.socket.connected.value)
        advance(2_001)                          // LiveSocket retries after 2 s
        assertEquals(2, ws.sockets.size)
        ws.last.open()
        advance()
        assertEquals(2, gets())
    }

    @Test fun aForegroundReturnThatAlsoReconnectsCostsOneRequest() {
        shown()
        dash.container.foreground.value = false
        ws.last.fail()
        advance(2_001)
        dash.container.foreground.value = true
        ws.last.open()
        advance()
        assertEquals(2, gets())
    }

    // ── Orders ──────────────────────────────────────────────────────────────

    @Test fun anOrderUpdateForThisCustomerRefreshesTheProfile() {
        val vm = shown()
        fake.on("GET", "/admin/orders", body = ordersWith(Fixtures.orderRow("o9", CustomerFixtures.PETER, "[]", "5000.0", "confirmed", "whatsapp", 1)))
        fake.on("GET", path, body = CustomerFixtures.peter.replace("\"total_orders\":24", "\"total_orders\":25"))
        ws.last.frame("""{"event":"notification","type":"order_update","title":"Order confirmed","body":"Fr. Peter Kamau","wa_id":"${CustomerFixtures.PETER}"}""")
        advance(801)                            // the dashboard refetches orders 800 ms after the event
        assertEquals(1, gets())
        advance()
        assertEquals(2, gets())
        assertEquals(25, vm.profile.value!!.totalOrders)
    }

    @Test fun anOrderForSomeoneElseCostsNothing() {
        shown()
        fake.on("GET", "/admin/orders", body = ordersWith(Fixtures.orderRow("o9", CustomerFixtures.MARY, "[]", "5000.0", "confirmed", "messenger", 1)))
        ws.last.frame("""{"event":"notification","type":"order_update","title":"Order confirmed","body":"Rev. Mary"}""")
        advance(801); advance()
        assertEquals(1, gets())
    }

    @Test fun anOrdersPollThatChangesNothingCostsNothing() {
        shown()
        dash.refetchOrders(); dash.refetchOrders()
        advance()
        assertEquals(1, gets())
    }

    // ── On screen or not ────────────────────────────────────────────────────

    @Test fun aHiddenPanelMakesNoRequests() {
        val vm = shown()
        vm.sync(row.copy(lastMessageAt = "2026-09-26T09:00:00Z"))
        vm.onHidden()                           // closed before the coalesced reload left
        dash.container.foreground.value = false
        dash.container.foreground.value = true
        ws.last.fail(); advance(2_001); ws.last.open()
        fake.on("GET", "/admin/orders", body = ordersWith(Fixtures.orderRow("o9", CustomerFixtures.PETER, "[]", "5000.0", "confirmed", "whatsapp", 1)))
        dash.refetchOrders()
        advance()
        assertEquals(1, gets())
    }

    @Test fun reopeningThePanelRefetchesQuietly() {
        val vm = shown()
        vm.onHidden()
        vm.onShown()
        assertTrue("the last profile stays painted meanwhile", vm.profile.value != null)
        advance()
        assertEquals(2, gets())
        assertFalse(vm.loading.value)
    }

    @Test fun switchingConversationsNeverShowsTheOldProfile() {
        val first = shown()
        assertEquals("Fr. Peter Kamau", first.profile.value!!.name)
        first.onHidden()
        // The next thread's profile is slow; its panel must never paint Peter meanwhile.
        val held = Held()
        val next = shown(CustomerFixtures.conversation("c2"), fetch = held.fetch)
        val seen = mutableListOf<String?>()
        scope.launch { next.profile.collect { seen += it?.name } }
        assertTrue(next.loading.value)
        assertNull(next.profile.value)
        // Peter's panel answering late changes nothing for Mary's.
        first.load(showSpinner = false)
        held.answers[0].complete(NeemaJson.decodeFromString(CustomerProfile.serializer(), CustomerFixtures.mary))
        assertEquals(listOf(null, "Rev. Mary Achieng"), seen)
        assertFalse(next.loading.value)
    }
}
