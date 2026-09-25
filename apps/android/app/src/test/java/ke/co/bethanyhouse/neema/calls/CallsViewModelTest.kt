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
        assertEquals("k1", v.selected.value!!.id)
        assertNull(dash.callsFocusKey.value)
        v.consumeFocus("254799999999")
        assertEquals("k1", v.selected.value!!.id)
    }

    @Test fun transcriptPanelLoadsTogglesAndTranscribes() {
        val (v, fake) = vm()
        v.toggleTranscript("wacid.5")
        assertEquals("recorded", v.transcript.value!!.data!!.status)
        v.runTranscribe()
        assertTrue(fake.called("POST", "/admin/calls/wacid.5/transcribe"))
        assertEquals(false, v.transcript.value!!.busy)
        v.toggleTranscript("wacid.5")
        assertNull(v.transcript.value)
    }

    @Test fun transcribeErrorsUseTheWebCopy() {
        val (v, fake) = vm()
        fake.on("POST", "/admin/calls/wacid.5/transcribe", code = 409, body = """{"detail":"off"}""")
        v.toggleTranscript("wacid.5"); v.runTranscribe()
        assertEquals("Turn on transcription on the server first (WHISPER_ENABLED).", v.transcript.value!!.err)
        assertEquals("recorded", v.transcript.value!!.data!!.status)
        fake.on("POST", "/admin/calls/wacid.5/transcribe", code = 502, body = "{}")
        v.runTranscribe()
        assertEquals("Couldn't start transcription.", v.transcript.value!!.err)
    }

    @Test fun showFullTranscriptToggles() {
        val (v, _) = vm()
        v.toggleTranscript("wacid.1")
        v.toggleFull()
        assertTrue(v.transcript.value!!.showFull)
    }
}
