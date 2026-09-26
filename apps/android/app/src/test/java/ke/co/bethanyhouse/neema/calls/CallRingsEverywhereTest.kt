package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.NeemaCallApi
import ke.co.bethanyhouse.neema.feature.calls.PeerEvent
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import ke.co.bethanyhouse.neema.testing.testContainer
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.time.Instant
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList

/**
 * A call must ring the agent in every realistic situation. End to end: the
 * real [ke.co.bethanyhouse.neema.core.ws.LiveSocket] on a fake WebSocket, the
 * real HTTP client on a stateful fake backend that behaves like
 * routers/whatsapp_webhook.py + routers/admin.py (the call log, the redis
 * answer lock, the 2-minute stale sweep), and one [CallManager] per phone.
 * Only the device (WebRTC, speaker, ringtone, notification shade) is faked.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallRingsEverywhereTest {
    // Only for a Context (layoutlib); nothing is rendered here.
    @get:Rule val paparazzi = Paparazzi()

    private val scheduler = TestCoroutineScheduler()
    private val d = UnconfinedTestDispatcher(scheduler)
    private val base = Instant.parse("2026-09-26T08:00:00Z").toEpochMilli()
    private fun now() = base + scheduler.currentTime
    private fun advance(ms: Long) { scheduler.advanceTimeBy(ms); scheduler.runCurrent() }
    private val scopes = mutableListOf<CoroutineScope>()
    @After fun stop() { scopes.forEach { it.cancel() } }

    /** WhatsApp Cloud API + the Neema backend, for calls. */
    private inner class Backend {
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install)
        inner class Row(val callId: String, val waId: String?, val name: String?, val direction: String, var status: String, val startedAt: Long)
        val rows = CopyOnWriteArrayList<Row>()
        val phones = CopyOnWriteArrayList<Phone>()
        /** The redis `wa:call:answered:{id}` lock (calls_answer): set once per call. */
        val answeredBy = ConcurrentHashMap<String, String>()

        private fun id(path: String) = java.net.URLDecoder.decode(path.split('/')[3], "UTF-8")

        init {
            // list_calls: the stale sweep, then newest first.
            fake.on("GET", "/admin/calls") { _, _ ->
                rows.filter { it.status == "ringing" && now() - it.startedAt > 120_000 }.forEach { it.status = "missed" }
                200 to rows.sortedByDescending { it.startedAt }.joinToString(",", "[", "]") { r ->
                    CallsFixtures.row(
                        "k-${r.callId}", r.callId, r.waId, r.name, r.direction, r.status, null, null,
                        Instant.ofEpochMilli(r.startedAt).toString(), null, "none", false,
                    )
                }
            }
            fake.on("GET", "/admin/calls/[^/]+/offer") { req, _ -> 200 to CallsFixtures.offer(id(req.url.encodedPath.removePrefix("/api"))) }
            // calls_answer: one phone wins the lock; the others get 409.
            fake.on("POST", "/admin/calls/[^/]+/answer") { req, _ ->
                val cid = id(req.url.encodedPath.removePrefix("/api"))
                if (answeredBy.putIfAbsent(cid, "agent") != null) 409 to """{"detail":"call already answered"}"""
                else {
                    rows.find { it.callId == cid && it.status == "ringing" }?.status = "answered"
                    200 to """{"ok":true,"call_id":"$cid"}"""
                }
            }
            // calls_terminate: Meta ends the call, then its terminate webhook publishes call_ended.
            fake.on("POST", "/admin/calls/[^/]+/terminate") { req, _ ->
                val cid = id(req.url.encodedPath.removePrefix("/api"))
                metaTerminate(cid)
                200 to """{"ok":true,"call_id":"$cid"}"""
            }
            fake.on("POST", "/admin/calls/[^/]+/recording") { req, _ ->
                200 to """{"ok":true,"call_id":"${id(req.url.encodedPath.removePrefix("/api"))}","will_transcribe":false}"""
            }
        }

        /** A customer rings: record_ringing, then publish incoming_call to every connected dashboard. */
        fun ring(cid: String, from: String = "254712345678", name: String? = "Fr. Peter Kamau") {
            rows += Row(cid, from, name, "inbound", "ringing", now())
            publish("""{"type": "incoming_call", "call_id": "$cid", "from": "$from", "name": ${if (name == null) "null" else "\"$name\""}, "at": "${now() / 1000}"}""")
        }

        /** Meta's terminate webhook: mark_ended, then call_ended. */
        fun metaTerminate(cid: String) {
            rows.find { it.callId == cid }?.let { r ->
                if (r.status !in listOf("ended", "missed", "declined", "callback")) r.status = if (r.status == "answered") "ended" else "missed"
            }
            publish("""{"type": "call_ended", "call_id": "$cid", "status": "COMPLETED", "duration": null}""")
        }

        /** websocket.py: every frame to every CONNECTED socket (a dropped one hears nothing). */
        fun publish(json: String) = phones.forEach { p -> if (p.container.socket.connected.value) p.ws.last.frame(json) }
    }

    private inner class Phone(val backend: Backend, val label: String, foreground: Boolean = true) {
        val ws = FakeSocketFactory()
        val container = testContainer(paparazzi.context, backend.fake, appDispatcher = d, wsFactory = ws).also {
            it.foreground.value = foreground
        }
        val ringer = FakeRinger()
        val media = FakeMedia()
        val audio = FakeAudio()
        private val scope = CoroutineScope(SupervisorJob() + d).also { scopes += it; scopes += container.appScope }
        val calls = CallManager(
            api = NeemaCallApi(container.api), events = container.socket.events, connected = container.socket.connected,
            scope = scope, foreground = container.foreground,
            signedInFn = { container.sessionStore.session.value != null },
            media = media, ringer = ringer, audio = audio, micGranted = { true }, main = d, io = d, now = ::now,
        )
        val state get() = calls.state.value
        val polls get() = backend.fake.calls.count { it.method == "GET" && it.path == "/admin/calls" }

        init { backend.phones += this }

        fun start() = calls.start()
        /** The session watcher in NeemaApplication opens the socket; the server accepts it. */
        fun connect() { container.socket.connect(Fixtures.ME_ID); ws.last.open() }
        /** The network drops; reconnect attempts every 2s are refused until [restore]. */
        fun dropNetwork() = ws.last.fail()
        fun restore() { advance(2_000); ws.last.open() }
    }

    private fun phone(backend: Backend = Backend(), label: String = "A", foreground: Boolean = true) =
        Phone(backend, label, foreground).also { it.start(); it.connect() }

    // ── 1. The app in front ─────────────────────────────────────────────────
    @Test fun appInFrontRingsTheInstantTheFrameArrives() {
        val p = phone()
        p.backend.ring("wacid.F1")
        assertEquals(CallPhase.Ringing, p.state.phase)
        assertEquals("wacid.F1", p.state.callId)
        assertEquals("Fr. Peter Kamau", p.state.name)
        assertTrue(p.ringer.ringing)
        assertTrue("the card is the alert: no system notification in front", p.ringer.posted.isEmpty())
    }

    // ── 2. Backgrounded, socket live (LiveService) ──────────────────────────
    @Test fun backgroundedWithTheSocketLiveRingsAndNotifies() {
        val p = phone(foreground = false)
        p.backend.ring("wacid.B1", name = null)
        assertEquals(CallPhase.Ringing, p.state.phase)
        assertTrue(p.ringer.ringing)
        assertEquals(listOf(Triple("wacid.B1", "+254712345678", "254712345678")), p.ringer.posted)
        // Tapping the notification's Answer routes back through MainActivity.
        p.container.foreground.value = true
        p.calls.handleAction("answer", "wacid.B1")
        assertEquals(CallPhase.Connecting, p.state.phase)
        assertFalse(p.ringer.showing)
        assertTrue(p.backend.fake.called("POST", "/admin/calls/wacid.B1/answer"))
    }

    // ── 3. The socket is down when the call arrives ─────────────────────────
    @Test fun socketDownThePollCatchesTheCallWithinTheWebsCadence() {
        val p = phone()
        advance(1_000)
        p.dropNetwork()
        p.backend.ring("wacid.D1")
        assertEquals("the frame was lost", CallPhase.Idle, p.state.phase)
        advance(11_000)   // the 12s idle poll started when the app did
        assertEquals(CallPhase.Ringing, p.state.phase)
        assertEquals("wacid.D1", p.state.callId)
        assertTrue(p.ringer.ringing)
    }

    @Test fun socketDownTheReconnectCatchesTheCallAtOnce() {
        val p = phone()
        advance(1_000)
        p.dropNetwork()
        p.backend.ring("wacid.D2")
        val polls = p.polls
        p.restore()   // 2s later, well before the 12s tick
        assertEquals(polls + 1, p.polls)
        assertEquals(CallPhase.Ringing, p.state.phase)
        assertEquals("wacid.D2", p.state.callId)
    }

    @Test fun socketDownTheCustomersHangUpIsCaughtWithin2500ms() {
        val p = phone()
        p.backend.ring("wacid.D3")
        p.dropNetwork()
        advance(700)
        p.backend.metaTerminate("wacid.D3")   // call_ended lost; the row is "missed" now
        advance(2_500)
        assertEquals(CallPhase.Idle, p.state.phase)
        assertFalse(p.ringer.ringing)
    }

    // ── 4. Process killed; LiveService (START_STICKY) restarts it ───────────
    @Test fun processRestartedByLiveServiceRingsACallAlreadyRinging() {
        val backend = Backend()
        backend.ring("wacid.R1")   // rang while the process was dead: nobody heard the frame
        advance(4_000)
        // The new process: no activity (background), a stored session, a
        // ringing notification left behind by the dead process.
        val p = Phone(backend, "A", foreground = false)
        p.ringer.showing = true
        p.start()
        assertFalse("the dead process's notification is cleared", p.ringer.showing)
        assertEquals(CallPhase.Idle, p.state.phase)
        p.connect()   // the socket reconnects from the stored session
        assertEquals("found by the catch-up poll, not 12s later", CallPhase.Ringing, p.state.phase)
        assertEquals(listOf(Triple("wacid.R1", "Fr. Peter Kamau", "254712345678")), p.ringer.posted)
    }

    @Test fun afterSignOutNothingIsPolledOrRung() {
        val p = phone()
        p.container.sessionStore.clear()
        p.container.socket.disconnect()
        val polls = p.polls
        p.backend.ring("wacid.S1")
        advance(60_000)
        assertEquals(polls, p.polls)
        assertEquals(CallPhase.Idle, p.state.phase)
    }

    // ── 5. The screen is locked ─────────────────────────────────────────────
    @Test fun screenLockedRingsThroughTheFullScreenNotification() {
        val p = phone()
        // Locking the screen stops the activity: ProcessLifecycleOwner.onStop.
        p.container.foreground.value = false
        p.backend.ring("wacid.L1", name = "Rev. Mary Achieng")
        assertTrue(p.ringer.ringing)
        assertEquals("CallAlert posts it with a full-screen intent", "wacid.L1", p.ringer.posted.single().first)
        assertTrue(p.ringer.showing)
        // Unlocked into the app: the card takes over, the notification goes.
        p.container.foreground.value = true
        assertFalse(p.ringer.showing)
        assertEquals(CallPhase.Ringing, p.state.phase)
        assertTrue(p.ringer.ringing)
    }

    @Test fun screenLockedWithTheSocketAsleepStillRings() {
        val p = phone()
        p.container.foreground.value = false
        p.dropNetwork()   // doze cut the connection
        p.backend.ring("wacid.L2")
        advance(12_000)
        assertEquals(CallPhase.Ringing, p.state.phase)
        assertEquals("wacid.L2", p.ringer.posted.single().first)
    }

    // ── 6. Two agents, two phones ───────────────────────────────────────────
    @Test fun whenOnePhoneAnswersTheOtherStopsRingingWithin2500ms() {
        val backend = Backend()
        val a = phone(backend, "A")
        val b = phone(backend, "B", foreground = false)
        advance(5_000)   // mid-way through both phones' 12s idle wait
        backend.ring("wacid.T1")
        assertEquals(CallPhase.Ringing, a.state.phase)
        assertEquals(CallPhase.Ringing, b.state.phase)
        assertTrue(b.ringer.showing)
        a.calls.answer()
        assertEquals(CallPhase.Connecting, a.state.phase)
        assertEquals("wacid.T1", backend.answeredBy.keys.single())
        // No frame tells B; its 2.5s ringing poll sees the row "answered".
        advance(2_500)
        assertEquals(CallPhase.Idle, b.state.phase)
        assertFalse(b.ringer.ringing)
        assertFalse(b.ringer.showing)
        assertFalse("B must not end A's live call", backend.fake.called("POST", "/admin/calls/wacid.T1/terminate"))
        assertEquals(CallPhase.Connecting, a.state.phase)
    }

    @Test fun bothPhonesAnswerAtOnceTheLoserBacksOffQuietly() {
        val backend = Backend()
        val a = phone(backend, "A")
        val b = phone(backend, "B")
        backend.ring("wacid.T2")
        a.calls.answer()
        b.calls.answer()
        assertEquals(CallManager.TAKEN_ELSEWHERE, b.state.error)
        advance(1_800)
        assertEquals(CallPhase.Ended, b.state.phase)
        assertFalse(backend.fake.called("POST", "/admin/calls/wacid.T2/terminate"))
        advance(1_000)
        assertEquals(CallPhase.Idle, b.state.phase)
        assertEquals(CallPhase.Connecting, a.state.phase)
    }

    // ── 7. The customer hangs up while it rings ─────────────────────────────
    @Test fun customerHangsUpWhileRingingOnEveryPhone() {
        val backend = Backend()
        val a = phone(backend, "A")
        val b = phone(backend, "B", foreground = false)
        backend.ring("wacid.H1")
        backend.metaTerminate("wacid.H1")
        for (p in listOf(a, b)) {
            assertEquals(CallPhase.Ended, p.state.phase)
            assertFalse(p.ringer.ringing); assertFalse(p.ringer.showing)
        }
        advance(1_000)
        assertEquals(CallPhase.Idle, a.state.phase)
        assertNull(a.state.callId)
        assertFalse(backend.fake.called("POST", "/admin/calls/wacid.H1/terminate"))
    }

    // ── 8. A second call during a live call ─────────────────────────────────
    @Test fun aSecondCallDuringALiveCallWaitsThenRingsWhenTheFirstEnds() {
        val p = phone()
        p.backend.ring("wacid.C1")
        p.calls.answer()
        p.media.peer.onEvent(PeerEvent.Connected)
        assertEquals(CallPhase.InCall, p.state.phase)
        p.backend.ring("wacid.C2", "254799999999", "Sr. Agnes Wairimu")
        // As the web: the live call is untouched, nothing rings over it.
        assertEquals(CallPhase.InCall, p.state.phase)
        assertEquals("wacid.C1", p.state.callId)
        assertEquals(1, p.ringer.ringStarts)
        advance(30_000)
        p.calls.hangup()
        assertEquals(CallPhase.Ended, p.state.phase)
        advance(1_000)
        assertEquals("the waiting customer rings through at once", CallPhase.Ringing, p.state.phase)
        assertEquals("wacid.C2", p.state.callId)
        assertEquals("Sr. Agnes Wairimu", p.state.name)
        assertTrue(p.backend.fake.called("POST", "/admin/calls/wacid.C1/recording"))
    }

    // ── 9. call_ended for a call we never saw ───────────────────────────────
    @Test fun callEndedForACallNeverSeenChangesNothing() {
        val p = phone()
        val before = p.backend.fake.calls.size
        p.backend.publish("""{"type": "call_ended", "call_id": "wacid.X1", "status": "COMPLETED", "duration": 12}""")
        assertEquals(CallPhase.Idle, p.state.phase)
        assertEquals("no request", before, p.backend.fake.calls.size)
        assertEquals(0, p.ringer.ringStarts)
        // And a ringing call carries on through someone else's end.
        p.backend.ring("wacid.X2")
        p.backend.publish("""{"type": "call_ended", "call_id": "wacid.X3", "status": "COMPLETED", "duration": 12}""")
        assertEquals(CallPhase.Ringing, p.state.phase)
    }
}
