package ke.co.bethanyhouse.neema.app

import android.content.Intent
import ke.co.bethanyhouse.neema.core.auth.Session
import ke.co.bethanyhouse.neema.core.auth.SessionStore
import ke.co.bethanyhouse.neema.core.notify.BootReceiver
import ke.co.bethanyhouse.neema.core.notify.LiveService
import ke.co.bethanyhouse.neema.core.ws.LiveSocket
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.MemoryPrefs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * The socket and LiveService across sign-in, sign-out, live mode, the app
 * going to the background, and the process being killed and restarted.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class LiveLifecycleTest {
    private val factory = FakeSocketFactory()
    private val sessionPrefs = MemoryPrefs()
    private val bg = MutableStateFlow(true)
    private val fg = MutableStateFlow(true)
    private var serviceRunning = false
    private var serviceStarts = 0

    private fun session(agent: String = "a1") = Session("tok", "ref", agent, "m@b.co.ke", "Moses", "admin", true, "direct")

    /** A "process": a session store over the persisted prefs, a socket, the lifecycle. */
    private fun TestScope.process(): Pair<SessionStore, LiveSocket> {
        val store = SessionStore(null, sessionPrefs)
        val socket = LiveSocket(factory, "https://neema.test", backgroundScope)
        LiveLifecycle(
            CoroutineScope(backgroundScope.coroutineContext + UnconfinedTestDispatcher(testScheduler)), store.session, bg, fg, socket,
            startService = { serviceRunning = true; serviceStarts++ },
            stopService = { serviceRunning = false },
        ).start()
        return store to socket
    }

    @Test
    fun signedOutThereIsNoSocketAndNoService() = runTest {
        process()
        assertTrue(factory.sockets.isEmpty())
        assertFalse(serviceRunning)
    }

    @Test
    fun signingInConnectsAsThatAgentAndStartsTheService() = runTest {
        val (store) = process()
        store.save(session("a1"))
        assertTrue(factory.last.url.endsWith("/ws/a1"))
        assertTrue(serviceRunning)
    }

    @Test
    fun signingOutClosesForGoodEvenIfTheSocketDropsAfterwards() = runTest {
        val (store, socket) = process()
        store.save(session()); factory.last.open()
        store.clear()
        assertFalse(serviceRunning)
        assertEquals(1000, factory.last.closedWith)
        factory.last.fail() // a late failure callback from the closed socket
        socket.nudge()      // the app comes to the front / the network returns
        advanceTimeBy(120_000); runCurrent()
        assertEquals("nothing reconnects after sign-out", 1, factory.sockets.size)
    }

    @Test
    fun liveModeKeepsTheSocketUpInTheBackground() = runTest {
        val (store, socket) = process()
        store.save(session()); factory.last.open()
        fg.value = false
        assertTrue(socket.connected.value)
        assertTrue(serviceRunning)
        fg.value = true; fg.value = false
        assertEquals("trips to the background don't re-promote the service", 1, serviceStarts)
    }

    @Test
    fun withoutLiveModeThereIsNoServiceAndAlertsStillArriveWhileOpen() = runTest {
        bg.value = false
        val (store, socket) = process()
        store.save(session()); factory.last.open()
        assertFalse(serviceRunning)
        assertTrue("connected while the app is open", socket.connected.value)

        fg.value = false
        assertFalse("closed in the background", socket.connected.value)
        assertEquals(1000, factory.last.closedWith)
        advanceTimeBy(60_000); runCurrent()
        assertEquals(1, factory.sockets.size)

        fg.value = true
        assertEquals("reopened on return", 2, factory.sockets.size)
    }

    @Test
    fun turningLiveModeOffStopsTheService() = runTest {
        val (store) = process()
        store.save(session())
        bg.value = false
        assertFalse(serviceRunning)
        bg.value = true
        assertTrue(serviceRunning)
    }

    @Test
    fun aRestartedProcessReconnectsFromTheStoredSession() = runTest {
        val (store) = process()
        store.save(session("a7"))
        // Android kills the process; START_STICKY (or boot) starts a new one in the background.
        factory.sockets.clear()
        fg.value = false
        process()
        assertTrue(factory.last.url.endsWith("/ws/a7"))
        assertTrue(serviceRunning)
    }

    @Test
    fun aRestartedProcessAfterSignOutStaysDisconnected() = runTest {
        val (store) = process()
        store.save(session()); store.clear()
        factory.sockets.clear()
        process()
        assertTrue(factory.sockets.isEmpty())
        assertFalse(serviceRunning)
    }

    @Test
    fun theServiceAndBootReceiverRunOnlyWhenSignedInWithLiveModeOn() {
        assertTrue(LiveService.wanted(signedIn = true, backgroundLive = true))
        assertFalse(LiveService.wanted(signedIn = true, backgroundLive = false))
        assertFalse(LiveService.wanted(signedIn = false, backgroundLive = true))
        assertTrue("a call keeps it up without live mode", LiveService.wanted(true, false, inCall = true))
        assertFalse(LiveService.wanted(false, false, inCall = true))
        assertEquals(setOf(Intent.ACTION_BOOT_COMPLETED, Intent.ACTION_MY_PACKAGE_REPLACED), BootReceiver.ACTIONS)
    }

    @Test
    fun switchingAgentsReconnectsAsTheNewOne() = runTest {
        val (store) = process()
        store.save(session("a1")); factory.last.open()
        store.save(session("a2"))
        assertTrue(factory.last.url.endsWith("/ws/a2"))
        assertEquals(1000, factory.sockets[0].closedWith)
    }
}
