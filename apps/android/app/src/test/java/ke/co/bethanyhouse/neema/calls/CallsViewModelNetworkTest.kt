package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.TestCoroutineScheduler
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.net.ConnectException
import java.net.SocketTimeoutException

/**
 * The call log and the transcript panel on a bad network (FakeNeema throwing
 * what OkHttp throws: no connection, a timeout; or answering 4xx/5xx/HTML).
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CallsViewModelNetworkTest {
    @get:Rule val paparazzi = Paparazzi()
    private val sched = TestCoroutineScheduler()

    @Before fun main() { Dispatchers.setMain(UnconfinedTestDispatcher(sched)) }
    @After fun reset() { Dispatchers.resetMain() }

    private fun fake() = FakeNeema.withFixtures().also(CallsFixtures::install)
    private fun vm(fake: FakeNeema) = CallsViewModel(dashboard(paparazzi.context, fake))

    private fun FakeNeema.offline(method: String, path: String) = on(method, path) { _, _ -> throw ConnectException("Failed to connect to neema.test") }
    private fun FakeNeema.slow(method: String, path: String) = on(method, path) { _, _ -> throw SocketTimeoutException("timeout") }

    // ── The call log ─────────────────────────────────────────────────────────
    @Test fun offlineFirstLoadSaysSoAndRetryRecovers() {
        val f = fake().also { it.offline("GET", "/admin/calls") }
        val v = vm(f)
        assertEquals(emptyList<Any>(), v.calls.value)
        assertEquals("No connection — check your internet and try again.", v.loadError.value)
        f.on("GET", "/admin/calls", body = CallsFixtures.calls)
        v.refresh()
        assertEquals(7, v.calls.value!!.size)
        assertNull(v.loadError.value)
        assertFalse(v.refreshing.value)
    }

    @Test fun aFailedRefreshKeepsTheLogOnScreen() {
        val f = fake()
        val v = vm(f)
        assertEquals(7, v.calls.value!!.size)
        f.slow("GET", "/admin/calls")
        v.load()
        assertEquals("cached rows stay", 7, v.calls.value!!.size)
        assertEquals("The server took too long to answer — try again.", v.loadError.value)
        v.refresh()
        assertEquals(7, v.calls.value!!.size)
        assertFalse("the spinner stops", v.refreshing.value)
    }

    @Test fun serverErrorsNeverShowRawHtml() {
        for ((code, msg) in listOf(
            502 to "The server had a problem — try again shortly.",
            503 to "The server had a problem — try again shortly.",
            500 to "The server had a problem — try again shortly.",
            429 to "Too many requests — wait a moment and try again.",
            403 to "You don't have access to calls.",
            404 to "Couldn't load calls.",
        )) {
            val f = fake().also { it.on("GET", "/admin/calls", code = code, body = "<html><body><h1>$code Bad Gateway</h1></body></html>") }
            val v = vm(f)
            assertEquals("$code", msg, v.loadError.value)
            assertFalse(v.loadError.value!!.contains("<"))
        }
    }

    @Test fun malformedBodyIsAnErrorNotACrash() {
        val v = vm(fake().also { it.on("GET", "/admin/calls", body = """{"not":"a list"}""") })
        assertEquals(emptyList<Any>(), v.calls.value)
        assertNotNull(v.loadError.value)
        val v2 = vm(fake().also { it.on("GET", "/admin/calls", body = "") })
        assertEquals(emptyList<Any>(), v2.calls.value)
    }

    @Test fun aSuccessfulPollClearsTheError() {
        val f = fake().also { it.offline("GET", "/admin/calls") }
        val v = vm(f)
        assertNotNull(v.loadError.value)
        f.on("GET", "/admin/calls", body = CallsFixtures.calls)
        sched.advanceTimeBy(60_001); sched.runCurrent()
        assertEquals(7, v.calls.value!!.size)
        assertNull(v.loadError.value)
    }

    // ── The transcript panel ─────────────────────────────────────────────────
    @Test fun aFlakyPollKeepsTheTranscriptStatusAndKeepsPolling() {
        val f = fake()
        val v = vm(f)
        v.toggleTranscript(CallsFixtures.C3)
        assertEquals("pending", v.transcript.value!!.data!!.status)
        f.offline("GET", CallsFixtures.route(CallsFixtures.C3, "transcript"))
        sched.advanceTimeBy(5_001); sched.runCurrent()
        assertEquals("the failed poll changed nothing", "pending", v.transcript.value!!.data!!.status)
        assertNull(v.transcript.value!!.loadErr)
        f.on("GET", CallsFixtures.route(CallsFixtures.C3, "transcript"), body = CallsFixtures.transcript(CallsFixtures.C3, "done"))
        sched.advanceTimeBy(5_001); sched.runCurrent()
        assertEquals("the poll went on and landed the result", "done", v.transcript.value!!.data!!.status)
    }

    @Test fun aTranscriptThatCannotLoadSaysWhyAndRetries() {
        val f = fake().also { it.offline("GET", CallsFixtures.route(CallsFixtures.C5, "transcript")) }
        val v = vm(f)
        v.toggleTranscript(CallsFixtures.C5)
        assertNull(v.transcript.value!!.data)
        assertEquals("No connection — couldn't load the transcript.", v.transcript.value!!.loadErr)
        f.on("GET", CallsFixtures.route(CallsFixtures.C5, "transcript"), body = CallsFixtures.transcript(CallsFixtures.C5, "recorded"))
        v.retryTranscript()
        assertEquals("recorded", v.transcript.value!!.data!!.status)
        assertNull(v.transcript.value!!.loadErr)
    }

    @Test fun aTranscriptForADeletedCallSaysSo() {
        val f = fake().also { it.on("GET", CallsFixtures.route(CallsFixtures.C5, "transcript"), code = 404, body = """{"detail":"Call not found"}""") }
        val v = vm(f)
        v.toggleTranscript(CallsFixtures.C5)
        assertEquals("This call is no longer in the log.", v.transcript.value!!.loadErr)
    }

    @Test fun closingThePanelMidRequestLandsNothing() {
        val f = fake()
        val v = vm(f)
        f.on("GET", CallsFixtures.route(CallsFixtures.C1, "transcript")) { _, _ ->
            v.toggleTranscript(CallsFixtures.C1)   // closed while the request is in flight
            200 to CallsFixtures.transcript(CallsFixtures.C1, "done")
        }
        v.toggleTranscript(CallsFixtures.C1)
        assertNull(v.transcript.value)
    }

    @Test fun transcribeDoubleTapSendsOneRequest() {
        val f = fake()
        val v = vm(f)
        v.toggleTranscript(CallsFixtures.C5)
        f.on("POST", CallsFixtures.route(CallsFixtures.C5, "transcribe")) { _, _ ->
            assertTrue(v.transcript.value!!.busy)
            v.runTranscribe()   // a second tap while the first is in flight
            200 to """{"ok":true,"call_id":"${CallsFixtures.C5}","status":"pending"}"""
        }
        v.runTranscribe()
        assertEquals(1, f.callsTo("POST", CallsFixtures.path(CallsFixtures.C5, "transcribe")).size)
        assertFalse(v.transcript.value!!.busy)
    }

    @Test fun transcribeTimedOutButStartedShowsTheTruth() {
        val f = fake()
        val v = vm(f)
        v.toggleTranscript(CallsFixtures.C5)
        f.slow("POST", CallsFixtures.route(CallsFixtures.C5, "transcribe"))
        // The job started server-side even though the answer never came back.
        f.on("GET", CallsFixtures.route(CallsFixtures.C5, "transcript"), body = CallsFixtures.transcript(CallsFixtures.C5, "pending"))
        v.runTranscribe()
        assertNull("no failure claimed", v.transcript.value!!.err)
        assertEquals("pending", v.transcript.value!!.data!!.status)
        assertFalse(v.transcript.value!!.busy)
    }

    @Test fun transcribeOfflineSaysSo() {
        val f = fake()
        val v = vm(f)
        v.toggleTranscript(CallsFixtures.C5)
        f.offline("POST", CallsFixtures.route(CallsFixtures.C5, "transcribe"))
        v.runTranscribe()
        assertEquals("No connection — couldn't start transcription.", v.transcript.value!!.err)
        assertEquals("recorded", v.transcript.value!!.data!!.status)
    }
}
