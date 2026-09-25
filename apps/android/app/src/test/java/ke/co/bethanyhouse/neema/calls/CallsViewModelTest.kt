package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** The call console's state (components/views/CallsView.tsx) against the fake backend. */
@OptIn(ExperimentalCoroutinesApi::class)
class CallsViewModelTest {
    @get:Rule val paparazzi = Paparazzi()

    @Before fun main() { Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun reset() { Dispatchers.resetMain() }

    private fun vm(fake: FakeNeema = FakeNeema.withFixtures().also(CallsFixtures::install)): Pair<CallsViewModel, FakeNeema> {
        val dash = dashboard(paparazzi.context, fake)
        return CallsViewModel(dash) to fake
    }

    @Test fun loadsTheLogAndFallsBackToEmptyOnError() {
        val (v, _) = vm()
        assertEquals(7, v.calls.value!!.size)
        val (v2, _) = vm(FakeNeema.withFixtures().also { it.on("GET", "/admin/calls", code = 500, body = "{}") })
        assertEquals(emptyList<Any>(), v2.calls.value)
    }

    @Test fun deepLinkFocusPicksTheNewestCallOfThatCustomer() {
        val dash = dashboard(paparazzi.context, FakeNeema.withFixtures().also(CallsFixtures::install))
        val v = CallsViewModel(dash)
        dash.callsFocusKey.value = "+254712345678"
        v.consumeFocus("+254712345678")
        assertEquals(CallsFixtures.K1, v.selected.value!!.id)
        assertNull(dash.callsFocusKey.value)
        v.consumeFocus("254799999999")
        assertEquals(CallsFixtures.K1, v.selected.value!!.id)
    }

    @Test fun transcriptPanelLoadsTogglesAndTranscribes() {
        val (v, fake) = vm()
        v.toggleTranscript(CallsFixtures.C5)
        assertEquals("recorded", v.transcript.value!!.data!!.status)
        v.runTranscribe()
        assertTrue(fake.called("POST", CallsFixtures.path(CallsFixtures.C5, "transcribe")))
        assertEquals(false, v.transcript.value!!.busy)
        v.toggleTranscript(CallsFixtures.C5)
        assertNull(v.transcript.value)
    }

    @Test fun transcribeErrorsUseTheWebCopy() {
        val (v, fake) = vm()
        fake.on("POST", CallsFixtures.route(CallsFixtures.C5, "transcribe"), code = 409, body = """{"detail":"off"}""")
        v.toggleTranscript(CallsFixtures.C5); v.runTranscribe()
        assertEquals("Turn on transcription on the server first (WHISPER_ENABLED).", v.transcript.value!!.err)
        assertEquals("recorded", v.transcript.value!!.data!!.status)
        fake.on("POST", CallsFixtures.route(CallsFixtures.C5, "transcribe"), code = 502, body = "{}")
        v.runTranscribe()
        assertEquals("Couldn't start transcription.", v.transcript.value!!.err)
    }

    @Test fun transcribeTellsTheTwo409sApart() {
        // routers/admin.py calls_transcribe raises 409 when Whisper is off AND
        // when the call has no recording; only the first is a server setting.
        val (v, fake) = vm()
        fake.on("POST", CallsFixtures.route(CallsFixtures.C6, "transcribe"), code = 409, body = CallsFixtures.WHISPER_OFF)
        v.toggleTranscript(CallsFixtures.C6); v.runTranscribe()
        assertEquals("Turn on transcription on the server first (WHISPER_ENABLED).", v.transcript.value!!.err)
        fake.on("POST", CallsFixtures.route(CallsFixtures.C6, "transcribe"), code = 409, body = CallsFixtures.NO_RECORDING)
        v.runTranscribe()
        assertEquals("No recording was captured for this call.", v.transcript.value!!.err)
        fake.on("POST", CallsFixtures.route(CallsFixtures.C6, "transcribe"), code = 404, body = """{"detail":"Call not found"}""")
        v.runTranscribe()
        assertEquals("Couldn't start transcription.", v.transcript.value!!.err)
    }

    @Test fun transcribeAlreadyRunningIsASuccess() {
        // calls_transcribe returns {"ok":true,"status":"pending"} without re-queuing.
        val (v, fake) = vm()
        fake.on("POST", CallsFixtures.route(CallsFixtures.C3, "transcribe"), body = """{"ok":true,"call_id":"${CallsFixtures.C3}","status":"pending"}""")
        v.toggleTranscript(CallsFixtures.C3); v.runTranscribe()
        assertNull(v.transcript.value!!.err)
        assertEquals("pending", v.transcript.value!!.data!!.status)
        assertEquals("{}", fake.callsTo("POST", CallsFixtures.path(CallsFixtures.C3, "transcribe")).last().body)
    }

    @Test fun showFullTranscriptToggles() {
        val (v, _) = vm()
        v.toggleTranscript(CallsFixtures.C1)
        v.toggleFull()
        assertTrue(v.transcript.value!!.showFull)
    }
}
