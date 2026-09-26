package ke.co.bethanyhouse.neema.core

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.TokenProvider
import ke.co.bethanyhouse.neema.core.notify.NotificationCenter
import ke.co.bethanyhouse.neema.core.util.AppPrefs
import ke.co.bethanyhouse.neema.core.util.Coalescer
import ke.co.bethanyhouse.neema.core.net.ErrorText
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.core.ws.str
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.MemoryPrefs
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.withTimeout
import kotlinx.serialization.json.JsonObject
import okhttp3.Interceptor
import okhttp3.Response
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicInteger

/**
 * Round 8 — the core under load: cancellation reaching OkHttp, socket bursts
 * with a slow reader, the bell under a storm of alerts, the coalescer from
 * many threads, and rough time bounds on the hot pure helpers.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CorePerfStressTest {
    // Only for a Context (the bell's prefs); nothing is rendered.
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6)

    private object Tokens : TokenProvider {
        override suspend fun validAccessToken() = "tok"
        override suspend fun forceRefresh(): String? = null
        override fun onRejected(token: String?) {}
    }

    // ── NeemaHttp: cancellation reaches the OkHttp call ─────────────────────

    /** A server that answers only once the call is cancelled (or after 5 s, which fails the test). */
    private class StuckServer : Interceptor {
        val entered = CountDownLatch(1)
        val sawCancel = AtomicBoolean(false)
        override fun intercept(chain: Interceptor.Chain): Response {
            entered.countDown()
            val until = System.nanoTime() + TimeUnit.SECONDS.toNanos(5)
            while (!chain.call().isCanceled() && System.nanoTime() < until) Thread.sleep(2)
            sawCancel.set(chain.call().isCanceled())
            throw IOException("Canceled")
        }
    }

    @Test
    fun leavingAScreenCancelsItsOkHttpCallAndEndsAsCancelledNotAsAnError() = runBlocking {
        val server = StuckServer()
        val http = NeemaHttp("https://neema.test", Tokens, server, Dispatchers.IO)
        val outcome = CompletableDeferred<Throwable?>()
        val job = launch(Dispatchers.Default) {
            try { http.raw("GET", "/admin/conversations"); outcome.complete(null) } catch (t: Throwable) { outcome.complete(t); throw t }
        }
        assertTrue("the request reached the server", server.entered.await(5, TimeUnit.SECONDS))
        val t0 = System.nanoTime()
        job.cancel()
        val e = withTimeout(5_000) { outcome.await() }
        val ms = (System.nanoTime() - t0) / 1_000_000
        assertTrue("the OkHttp call itself was cancelled", server.sawCancel.get())
        assertTrue("a cancelled request never surfaces as an ApiException (it was $e)", e is CancellationException && e !is ApiException)
        assertTrue("the blocked read ended promptly ($ms ms), not at the 30 s timeout", ms < 2_000)
    }

    @Test
    fun aCallCancelledBeforeItStartsNeverReachesTheServer() = runBlocking {
        val hits = AtomicInteger()
        val http = NeemaHttp("https://neema.test", Tokens, Interceptor { hits.incrementAndGet(); throw IOException("x") }, Dispatchers.IO)
        val job = launch(Dispatchers.Default, start = kotlinx.coroutines.CoroutineStart.LAZY) { http.raw("GET", "/admin/orders") }
        job.cancel(); job.join()
        assertEquals(0, hits.get())
    }

    @Test
    fun aTransportFailureKeepsTheIOExceptionAsTheCause() {
        val boom = java.net.ConnectException("Connection refused")
        val http = NeemaHttp("https://neema.test", Tokens, Interceptor { throw boom }, Dispatchers.Unconfined)
        val e = runBlocking { try { http.raw("GET", "/admin/me"); null } catch (e: ApiException) { e } }
        assertEquals(0, e!!.status)
        assertTrue("the root cause is kept for logs", e.cause === boom)
    }

    @Test
    fun aTimeoutKeepsItsCauseToo() {
        val boom = java.net.SocketTimeoutException("read timed out")
        val http = NeemaHttp("https://neema.test", Tokens, Interceptor { throw boom }, Dispatchers.Unconfined)
        val e = runBlocking { try { http.raw("GET", "/admin/me"); null } catch (e: ApiException) { e } }!!
        assertTrue(e.timedOut)
        assertTrue(e.cause === boom)
    }

    @Test
    fun manyCompletedRequestsLeaveNoCancellationHandlersBehind() = runBlocking {
        // A finished request must not be cancelled by its screen leaving later.
        var n = 0
        val http = NeemaHttp("https://neema.test", Tokens, Interceptor { chain ->
            n++
            Response.Builder().request(chain.request()).protocol(okhttp3.Protocol.HTTP_1_1).code(200).message("OK")
                .body(okhttp3.ResponseBody.create(null, "{}")).build()
        }, Dispatchers.Unconfined)
        val parent = kotlinx.coroutines.Job()
        val scope = CoroutineScope(parent + Dispatchers.Unconfined)
        val results = (1..1_000).map { scope.async { http.raw("GET", "/admin/orders") } }
        results.forEach { assertEquals("{}", it.await()) }
        assertEquals(1_000, n)
        assertEquals("no leftover children or handlers on the screen's job", 0, parent.children.count())
        parent.cancel()
    }

    // ── LiveSocket: a burst with a slow reader ──────────────────────────────

    @Test
    fun aBurstOf200FramesReachesASlowCollectorCompleteAndInOrder() {
        val scheduler = TestCoroutineScheduler()
        val slow = StandardTestDispatcher(scheduler) // runs only when the test says so
        val factory = FakeSocketFactory()
        val socket = LiveSocket(factory, "https://neema.test", CoroutineScope(Dispatchers.Unconfined))
        val seen = mutableListOf<String>()
        CoroutineScope(slow).launch { socket.events.collect { seen += it.str("id")!! } }
        scheduler.runCurrent() // subscribed
        socket.connect("a1"); factory.last.open()

        repeat(200) { i -> factory.last.frame("""{"type":"new_message","conversationId":"c${i % 7}","id":"m$i","text":"hi"}""") }
        assertTrue("nothing processed yet: the collector is busy", seen.isEmpty())
        scheduler.runCurrent()
        assertEquals((0 until 200).map { "m$it" }, seen)
        assertEquals(0L, socket.droppedFrames)
    }

    @Test
    fun aBacklogUpToTheBufferIsKeptAndBeyondItIsCountedNotSilent() {
        val scheduler = TestCoroutineScheduler()
        val factory = FakeSocketFactory()
        val socket = LiveSocket(factory, "https://neema.test", CoroutineScope(Dispatchers.Unconfined))
        var got = 0
        CoroutineScope(StandardTestDispatcher(scheduler)).launch { socket.events.collect { got++ } }
        scheduler.runCurrent()
        socket.connect("a1"); factory.last.open()
        val total = LiveSocket.EVENT_BUFFER + 50
        repeat(total) { factory.last.frame("""{"type":"message","n":$it}""") }
        scheduler.runCurrent()
        // The collector had a frame in hand before the buffer filled; the rest overflowed.
        assertTrue("the whole buffer is delivered ($got)", got >= LiveSocket.EVENT_BUFFER)
        assertEquals(total.toLong(), got + socket.droppedFrames)
    }

    // ── The bell under a storm ──────────────────────────────────────────────

    @Test
    fun aStormOf500AlertsKeepsTheBellBoundedNewestFirstAndPersistsTheLatest() {
        val prefs = MemoryPrefs()
        val scheduler = TestCoroutineScheduler()
        val scope = CoroutineScope(StandardTestDispatcher(scheduler))
        val factory = FakeSocketFactory()
        val socket = LiveSocket(factory, "https://neema.test", CoroutineScope(Dispatchers.Unconfined))
        val nc = NotificationCenter(paparazzi.context, scope, socket, AppPrefs(paparazzi.context, MemoryPrefs()), prefs)
        nc.start(MutableStateFlow(true))
        scheduler.runCurrent()
        socket.connect("a1"); factory.last.open()

        val t0 = System.nanoTime()
        repeat(500) { i -> factory.last.frame("""{"event":"notification","type":"new_conversation","title":"Chat $i","body":"hi","wa_id":"2547$i"}""") }
        scheduler.runCurrent()
        val ms = (System.nanoTime() - t0) / 1_000_000

        val items = nc.items.value
        assertEquals(NotificationCenter.MAX_ITEMS, items.size)
        assertEquals("Chat 499", items.first().title)
        assertEquals("Chat 440", items.last().title)
        assertEquals("ids stay unique", items.size, items.map { it.id }.toSet().size)
        val saved = prefs.getString("items", "")!!
        assertTrue("the disk copy is the latest list", saved.contains("Chat 499") && !saved.contains("\"Chat 439\""))
        assertTrue("500 alerts handled in $ms ms", ms < 2_000)
    }

    // ── Coalescer ───────────────────────────────────────────────────────────

    @Test
    fun tenThousandKicksFromEightThreadsCostOneRun() = runBlocking {
        val runs = AtomicInteger()
        val scope = CoroutineScope(Dispatchers.Default)
        val c = Coalescer(scope, 50) { runs.incrementAndGet() }
        val threads = (1..8).map { Thread { repeat(1_250) { c.kick() } } }
        threads.forEach(Thread::start); threads.forEach(Thread::join)
        withTimeout(5_000) { while (runs.get() == 0) kotlinx.coroutines.delay(5) }
        kotlinx.coroutines.delay(80)
        assertEquals(1, runs.get())
    }

    @Test
    fun runsNeverOverlapAndAKickDuringARunIsNotLost() {
        val scheduler = TestCoroutineScheduler()
        val scope = CoroutineScope(StandardTestDispatcher(scheduler))
        var active = 0; var maxActive = 0; var runs = 0
        val gate = CompletableDeferred<Unit>()
        val c = Coalescer(scope, 100) {
            active++; maxActive = maxOf(maxActive, active); runs++
            if (runs == 1) gate.await()
            active--
        }
        c.kick(); scheduler.advanceTimeBy(101); scheduler.runCurrent()
        assertEquals(1, runs)
        c.kick() // lands while run 1 is still going
        scheduler.advanceTimeBy(500); scheduler.runCurrent()
        assertEquals("the second run waits for the first", 1, runs)
        gate.complete(Unit); scheduler.runCurrent()
        assertEquals(2, runs)
        assertEquals(1, maxActive)
    }

    @Test
    fun anImmediateCoalescerStillCoalescesWhileItsRunIsSuspended() {
        val gate = CompletableDeferred<Unit>()
        var runs = 0
        val c = Coalescer(CoroutineScope(Dispatchers.Unconfined), 0) { runs++; gate.await() }
        c.kick()
        c.kick() // run 1 is suspended: this one is queued behind it, not dropped
        assertEquals(1, runs)
        gate.complete(Unit)
        assertEquals(2, runs)
    }

    // ── Hot pure helpers ────────────────────────────────────────────────────

    @Test
    fun formattingFiveThousandRowsIsCheap() {
        val phones = (0 until 5_000).map { "2547%08d".format(it) }
        val stamps = (0 until 5_000).map { "2026-09-%02dT%02d:15:00Z".format(1 + it % 28, it % 24) }
        Fmt.formatPhone(phones[0]); Fmt.millis(stamps[0]) // warm up
        val t0 = System.nanoTime()
        val out = phones.map(Fmt::formatPhone)
        val ms = stamps.map(Fmt::millis)
        val took = (System.nanoTime() - t0) / 1_000_000
        assertEquals(5_000, out.size)
        assertTrue(ms.all { it != null && it > 0 })
        assertTrue("5k phones + 5k timestamps took $took ms", took < 500)
    }

    @Test
    fun errorTextForAHugeErrorPageIsBoundedAndQuick() {
        val html = "<!doctype html><html>" + "x".repeat(2_000_000) + "</html>"
        val t0 = System.nanoTime()
        val msg = ErrorText.of(ApiException(502, "GET", "/admin/orders", html))
        val took = (System.nanoTime() - t0) / 1_000_000
        assertFalse("never shows the page", msg.contains("<html"))
        assertTrue(msg.length < 300)
        assertTrue("took $took ms", took < 500)
    }

}
