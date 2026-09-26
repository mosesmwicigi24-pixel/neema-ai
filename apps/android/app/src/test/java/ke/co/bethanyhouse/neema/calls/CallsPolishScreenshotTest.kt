package ke.co.bethanyhouse.neema.calls

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.unit.dp
import androidx.lifecycle.viewmodel.compose.viewModel
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.calls.CallActions
import ke.co.bethanyhouse.neema.feature.calls.CallCard
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallReadiness
import ke.co.bethanyhouse.neema.feature.calls.CallUiState
import ke.co.bethanyhouse.neema.feature.calls.CallsScreen
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.orders.Devices
import ke.co.bethanyhouse.neema.orders.Tappable
import ke.co.bethanyhouse.neema.orders.TouchAudit
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Round 7 — the incoming / in-call card and the call log across the device /
 * font / theme matrix. Every shot reads the semantics tree too: call controls
 * are ≥ 56dp and labelled, the log's icon buttons ≥ 48dp and labelled.
 */
class CallsPolishScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private val audit = TouchAudit()
    private val peter = CallUiState(callId = CallsFixtures.C1, from = "254712345678", name = "Askofu Mkuu Emmanuel Wabukala Onyango-Kipchumba 🙏")

    private fun shot(device: DeviceConfig, dark: Boolean, content: @Composable () -> Unit) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        paparazzi.snapshot { AppFrame(dark) { audit.Wrap(content) } }
        assertEquals("unlabelled tappables", emptyList<Tappable>(), audit.unlabelled())
    }

    private fun card(device: DeviceConfig, s: CallUiState, dark: Boolean = false) {
        shot(device, dark) { CallCard(s, CallActions()) }
        val controls = listOf("Decline", "Callback", "Answer", "Mute", "Unmute", "Speaker", "Hang up")
        assertEquals("call controls under 56dp", emptyList<Tappable>(), audit.tooSmall(56.dp, *controls.toTypedArray()))
        assertTrue("no call controls found", audit.tappables.any { t -> controls.any { t.label.contains(it) } })
    }

    private fun console(device: DeviceConfig, dark: Boolean = false, long: Boolean = true, setup: (CallsViewModel) -> Unit = {}) {
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install)
        if (long) fake.on("GET", "/admin/calls", body = CallsFixtures.longLog)
        val dash = dashboard(paparazzi.context, fake)
        shot(device, dark) {
            val vm: CallsViewModel = viewModel { CallsViewModel(dash) }
            remember { setup(vm) }
            CallsScreen(dash, readinessOverride = CallReadiness(fullScreen = false))
        }
        assertEquals(
            "log icon buttons under 48dp", emptyList<Tappable>(),
            audit.tooSmall(48.dp, "Open the conversation", "Call summary", "Call recording", "missed", "Allow", "Retry", "Transcribe", "full transcript"),
        )
    }

    // ── Incoming / in-call card ─────────────────────────────────────────────
    @Test fun ringingSmallPhone() = card(Devices.SmallPhoneLargeText, peter.copy(phase = CallPhase.Ringing))
    @Test fun ringingHugeText() = card(Devices.HugeText, peter.copy(phase = CallPhase.Ringing))
    @Test fun ringingHugeTextDark() = card(Devices.HugeText, peter.copy(phase = CallPhase.Ringing), dark = true)
    @Test fun inCallSmallPhone() = card(Devices.SmallPhoneLargeText, peter.copy(phase = CallPhase.InCall, seconds = 3_725, muted = true))
    @Test fun inCallHugeTextDark() = card(Devices.HugeText, peter.copy(phase = CallPhase.InCall, seconds = 187), dark = true)
    @Test fun inCallTabletPortrait() = card(Devices.TabletPortrait, peter.copy(phase = CallPhase.InCall, seconds = 42))
    @Test fun ringingFoldable() = card(Devices.Foldable, peter.copy(phase = CallPhase.Ringing))

    // ── Call log ────────────────────────────────────────────────────────────
    @Test fun logSmallPhone() = console(Devices.SmallPhoneLargeText)
    @Test fun logHugeTextDark() = console(Devices.HugeText, dark = true)
    @Test fun logFoldable() = console(Devices.Foldable)
    @Test fun logTabletPortrait() = console(Devices.TabletPortrait)
    @Test fun logTranscriptSmallPhone() = console(Devices.SmallPhoneLargeText, long = false) { it.toggleTranscript(CallsFixtures.C1) }
}
