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
    fun aRefusedHandshakeKeepsRetrying() = runTest {
        socket().connect("a1")
        repeat(3) { factory.last.fail(); advanceTimeBy(2_001); runCurrent() }
        assertEquals(4, factory.sockets.size)
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
