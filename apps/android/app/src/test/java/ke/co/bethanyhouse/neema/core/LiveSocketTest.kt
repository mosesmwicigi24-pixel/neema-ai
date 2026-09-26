package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.core.ws.str
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** lib/websocket.tsx createNativeWs(): /ws/{agent_id}, ping every 25 s, reconnect 2 s after any close. */
@OptIn(ExperimentalCoroutinesApi::class)
class LiveSocketTest {
    private val factory = FakeSocketFactory()

    private fun TestScope.socket(base: String = "https://neema.test") = LiveSocket(factory, base, backgroundScope)

    @Test
    fun theUrlIsTheWsTwinOfTheOriginWithoutApi() = runTest {
        assertEquals("wss://neema.test/ws/a1", socket().url("a1"))
        assertEquals("ws://10.0.2.2:8000/ws/a1", socket("http://10.0.2.2:8000/api/").url("a1"))
        assertEquals("wss://x.test/ws/a1", socket("https://x.test/").url("a1"))
    }

    @Test
    fun connectOpensOnceAndIsIdempotentPerAgent() = runTest {
        val s = socket()
        s.connect("a1"); s.connect("a1")
        assertEquals(1, factory.sockets.size)
        assertTrue(factory.last.url, factory.last.url.endsWith("://neema.test/ws/a1"))
        assertFalse("not connected until the server accepts", s.connected.value)
        factory.last.open()
        assertTrue(s.connected.value)

        s.connect("a2")
        assertEquals("switching agent closes the old socket", 1000, factory.sockets[0].closedWith)
        assertTrue(factory.last.url.endsWith("://neema.test/ws/a2"))
    }

    @Test
    fun pingsEvery25SecondsWhileOpen() = runTest {
        val s = socket()
        s.connect("a1"); factory.last.open()
        advanceTimeBy(24_999); runCurrent()
        assertTrue(factory.last.sent.isEmpty())
        advanceTimeBy(2); runCurrent()
        assertEquals(listOf("""{"type":"ping"}"""), factory.last.sent)
        advanceTimeBy(25_000); runCurrent()
        assertEquals(2, factory.last.sent.size)
    }

    @Test
    fun framesAreEmittedPongsAndGarbageAreNot() = runTest {
        val s = socket()
        val got = mutableListOf<JsonObject>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { s.events.toList(got) }
        s.connect("a1"); factory.last.open()
        factory.last.frame("""{"type":"pong"}""")
        factory.last.frame("not json")
        factory.last.frame("[1,2]")
        factory.last.frame("""{"event":"notification","type":"intercept","title":"Picked up"}""")
        factory.last.frame("""{"type":"new_message","conversationId":"c1"}""")
        assertEquals(listOf("notification", null), got.map { it.str("event") })
        assertEquals("c1", got[1].str("conversationId"))
    }

    @Test
    fun aDroppedSocketReconnectsAfterTwoSeconds() = runTest {
        val s = socket()
        s.connect("a1"); factory.last.open()
        factory.last.fail()
        assertFalse(s.connected.value)
        advanceTimeBy(1_999); runCurrent()
        assertEquals(1, factory.sockets.size)
        advanceTimeBy(2); runCurrent()
        assertEquals(2, factory.sockets.size)
        factory.last.open()
        assertTrue(s.connected.value)
        // The dead socket's ping stopped with it.
        advanceTimeBy(25_001); runCurrent()
        assertTrue(factory.sockets[0].sent.isEmpty())
        assertEquals(1, factory.sockets[1].sent.size)
    }

    @Test
    fun aCleanServerCloseAlsoReconnects() = runTest {
        socket().apply { connect("a1") }
        factory.last.open(); factory.last.serverClose()
        advanceTimeBy(2_001); runCurrent()
        assertEquals(2, factory.sockets.size)
    }

    @Test
    fun aRefusedHandshakeKeepsRetryingBackingOffTo30Seconds() = runTest {
        val s = socket()
        s.connect("a1")
        // 2 s like the web, then 4, 8, 16, 30, 30 … while the server stays away.
        for ((i, wait) in listOf(2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L).withIndex()) {
            factory.last.fail()
            advanceTimeBy(wait - 1); runCurrent()
            assertEquals("retry ${i + 1} waits ${wait}ms", i + 1, factory.sockets.size)
            advanceTimeBy(2); runCurrent()
            assertEquals(i + 2, factory.sockets.size)
        }
        assertEquals(listOf(2_000L, 4_000L, 8_000L, 16_000L, 30_000L, 30_000L), (1..6).map(s::backoff))
    }

    @Test
    fun anOpenSocketResetsTheBackoff() = runTest {
        socket().connect("a1")
        repeat(4) { factory.last.fail(); advanceTimeBy(40_000); runCurrent() }
        factory.last.open()
        factory.last.fail()
        advanceTimeBy(2_001); runCurrent()
        assertEquals("back to 2 s after a good connection", 6, factory.sockets.size)
    }

    @Test
    fun nudgeSkipsALongBackoff() = runTest {
        val s = socket()
        s.connect("a1")
        repeat(5) { factory.last.fail(); advanceTimeBy(40_000); runCurrent() }
        factory.last.fail() // now 30 s away
        s.nudge() // the network came back / the app came to the front
        assertEquals(7, factory.sockets.size)
        factory.last.fail()
        advanceTimeBy(2_001); runCurrent()
        assertEquals("and the backoff starts over", 8, factory.sockets.size)
    }

    // ── The "reconnected" signal: frames may have been missed ───────────────

    private fun TestScope.reconnects(s: LiveSocket): MutableList<Unit> {
        val got = mutableListOf<Unit>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { s.reconnected.toList(got) }
        return got
    }

    @Test
    fun theFirstOpenIsNotAReconnect() = runTest {
        val s = socket(); val got = reconnects(s)
        s.connect("a1"); factory.last.open()
        assertTrue(got.isEmpty())
    }

    @Test
    fun everyReopenAfterADropSignalsAReconnect() = runTest {
        val s = socket(); val got = reconnects(s)
        s.connect("a1"); factory.last.open()
        factory.last.fail(); advanceTimeBy(2_001); runCurrent()
        assertTrue("not until it is actually open again", got.isEmpty())
        factory.last.open()
        assertEquals(1, got.size)
        factory.last.serverClose(); advanceTimeBy(2_001); runCurrent(); factory.last.open()
        assertEquals(2, got.size)
    }

    @Test
    fun failedRetriesSignalOnceWhenTheyFinallyConnect() = runTest {
        val s = socket(); val got = reconnects(s)
        s.connect("a1"); factory.last.open()
        repeat(3) { factory.last.fail(); advanceTimeBy(40_000); runCurrent() }
        factory.last.open()
        assertEquals(1, got.size)
    }

    @Test
    fun reopeningAfterABackgroundCloseIsAReconnect() = runTest {
        val s = socket(); val got = reconnects(s)
        s.connect("a1"); factory.last.open()
        s.disconnect() // backgrounded without live mode
        s.connect("a1"); factory.last.open()
        assertEquals("frames were missed while closed", 1, got.size)
    }

    @Test
    fun aNewAgentOrANewSignInIsNotAReconnect() = runTest {
        val s = socket(); val got = reconnects(s)
        s.connect("a1"); factory.last.open()
        s.connect("a2"); factory.last.open()
        s.signOut()
        s.connect("a2"); factory.last.open()
        assertTrue(got.isEmpty())
    }

    @Test
    fun afterSignOutNothingReconnects() = runTest {
        val s = socket()
        s.connect("a1"); factory.last.open()
        s.signOut()
        factory.last.fail(); s.nudge()
        advanceTimeBy(120_000); runCurrent()
        assertEquals(1, factory.sockets.size)
        assertFalse(s.connected.value)
    }

    @Test
    fun aReplacedSocketThatOpensLateIsCancelledAndIgnored() = runTest {
        val s = socket(); val got = reconnects(s)
        s.connect("a1"); val stale = factory.last
        s.connect("a2"); val live = factory.last
        stale.open()
        assertTrue("the stale handshake is torn down", stale.cancelled)
        assertFalse(s.connected.value)
        live.open()
        assertTrue(s.connected.value)
        assertTrue(got.isEmpty())
    }

    @Test
    fun aReplacedSocketStillDrainingDoesNotDoubleFrames() = runTest {
        val s = socket()
        val got = mutableListOf<JsonObject>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { s.events.toList(got) }
        s.connect("a1"); val old = factory.last; old.open()
        old.fail(); advanceTimeBy(2_001); runCurrent(); factory.last.open()
        old.frame("""{"type":"new_message","conversationId":"c1"}""")
        factory.last.frame("""{"type":"new_message","conversationId":"c1"}""")
        assertEquals(1, got.size)
    }

    @Test
    fun aBurstOfFramesArrivesInOrder() = runTest {
        val s = socket()
        val got = mutableListOf<JsonObject>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { s.events.toList(got) }
        s.connect("a1"); factory.last.open()
        repeat(200) { factory.last.frame("""{"type":"new_message","conversationId":"c$it"}""") }
        assertEquals((0 until 200).map { "c$it" }, got.map { it.str("conversationId") })
    }

    @Test
    fun disconnectStopsReconnectingAndPinging() = runTest {
        val s = socket()
        s.connect("a1"); factory.last.open()
        s.disconnect()
        assertEquals(1000, factory.last.closedWith)
        assertFalse(s.connected.value)
        factory.last.fail() // the close handshake reports back late
        advanceTimeBy(60_000); runCurrent()
        assertEquals(1, factory.sockets.size)
        assertTrue(factory.last.sent.isEmpty())
    }

    @Test
    fun nudgeReconnectsAtOnceWhenDown() = runTest {
        val s = socket()
        s.connect("a1"); factory.last.open(); factory.last.fail()
        s.nudge()
        assertEquals("no 2 s wait when the app comes back", 2, factory.sockets.size)
        advanceTimeBy(2_001); runCurrent()
        assertEquals("the pending timer was cancelled", 2, factory.sockets.size)

        s.disconnect(); s.nudge()
        assertEquals("a socket closed on purpose (signed out) stays closed", 2, factory.sockets.size)
    }

    @Test
    fun nudgeWhileConnectedDoesNothing() = runTest {
        val s = socket()
        s.connect("a1"); factory.last.open()
        s.nudge()
        assertEquals(1, factory.sockets.size)
    }

    @Test
    fun callbacksFromAReplacedSocketAreIgnored() = runTest {
        val s = socket()
        s.connect("a1"); val old = factory.last; old.open()
        s.connect("a2"); factory.last.open()
        old.fail()
        assertTrue("the old socket's failure must not mark the new one down", s.connected.value)
        advanceTimeBy(2_001); runCurrent()
        assertEquals(2, factory.sockets.size)
    }
}
