package ke.co.bethanyhouse.neema.calls

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.lifecycle.viewmodel.compose.viewModel
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.feature.calls.CallActions
import ke.co.bethanyhouse.neema.feature.calls.CallCard
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallReadiness
import ke.co.bethanyhouse.neema.feature.calls.CallUiState
import ke.co.bethanyhouse.neema.feature.calls.CallsScreen
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import org.junit.Rule
import org.junit.Test

/**
 * The call card in every phase, the call console (populated, empty, missed
 * filter, every transcript state, the readiness prompts), and the caller
 * pane — phone, dark and tablet.
 *   ./gradlew :app:recordPaparazziDebug --tests '*CallsScreenshotTest'
 */
class CallsScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private val peter = CallUiState(callId = "wacid.1", from = "254712345678", name = "Fr. Peter Kamau")
    private val peterCall = Call(id = "k1", callId = "wacid.1", waId = "254712345678", name = "Fr. Peter Kamau", status = "answered", startedAt = Fixtures.ago(40))

    private fun card(s: CallUiState, dark: Boolean = false) = paparazzi.snapshot {
        AppFrame(dark) { CallCard(s, CallActions()) }
    }

    // ── The call card ────────────────────────────────────────────────────────
    @Test fun cardRinging() = card(peter.copy(phase = CallPhase.Ringing))
    @Test fun cardRingingUnknownNumber() = card(CallUiState(phase = CallPhase.Ringing, callId = "x", from = "254700123456"))
    @Test fun cardRingingLongName() = card(peter.copy(phase = CallPhase.Ringing, name = "The Most Reverend Archbishop Emmanuel Wabukala Onyango-Kipchumba"))
    @Test fun cardConnecting() = card(peter.copy(phase = CallPhase.Connecting))
    @Test fun cardOutboundConnecting() = card(CallUiState(phase = CallPhase.Connecting, callId = "pending", from = "254733444555", name = "Deacon James Mwangi", outbound = true))
    @Test fun cardInCall() = card(peter.copy(phase = CallPhase.InCall, seconds = 187))
    @Test fun cardInCallMutedSpeaker() = card(peter.copy(phase = CallPhase.InCall, seconds = 3_725, muted = true, speaker = true))
    @Test fun cardEnded() = card(peter.copy(phase = CallPhase.Ended, seconds = 187))
    @Test fun cardEndedCallbackNote() = card(peter.copy(phase = CallPhase.Ended, note = "Callback saved — find them under Calls"))
    @Test fun cardErrorMic() = card(peter.copy(phase = CallPhase.Connecting, error = CallManager.MIC_BLOCKED))
    @Test fun cardErrorNoPermission() = card(
        CallUiState(phase = CallPhase.Connecting, callId = "pending", from = "254733444555", name = "Deacon James Mwangi",
            outbound = true, error = CallManager.NO_CALL_PERMISSION),
    )
    @Test fun cardInCallDark() = card(peter.copy(phase = CallPhase.InCall, seconds = 42), dark = true)

    // ── The console ──────────────────────────────────────────────────────────
    private fun fake() = FakeNeema.withFixtures().also(CallsFixtures::install)

    @Composable
    private fun Console(
        dash: DashboardViewModel,
        dark: Boolean = false,
        readiness: CallReadiness = CallReadiness(),
        setup: (CallsViewModel) -> Unit = {},
    ) = AppFrame(dark) {
        val vm: CallsViewModel = viewModel { CallsViewModel(dash) }
        remember { setup(vm) }
        CallsScreen(dash, readinessOverride = readiness)
    }

    private fun console(
        device: DeviceConfig = DeviceConfig.PIXEL_6,
        dark: Boolean = false,
        readiness: CallReadiness = CallReadiness(),
        fake: FakeNeema = fake(),
        setup: (CallsViewModel) -> Unit = {},
    ) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        val dash = dashboard(paparazzi.context, fake)
        paparazzi.snapshot { Console(dash, dark, readiness, setup) }
    }

    @Test fun log() = console()
    @Test fun logDark() = console(dark = true)
    @Test fun logEmpty() = console(fake = fake().also { it.on("GET", "/admin/calls", body = "[]") })
    @Test fun logMissedFilter() = console { it.missedOnly.value = true }
    @Test fun logNeedsNotifications() = console(readiness = CallReadiness(notifications = false))
    @Test fun logNeedsFullScreen() = console(readiness = CallReadiness(fullScreen = false))
    @Test fun logNeedsFullScreenDark() = console(dark = true, readiness = CallReadiness(fullScreen = false))

    @Test fun transcriptDone() = console { it.toggleTranscript("wacid.1") }
    @Test fun transcriptDoneFull() = console { it.toggleTranscript("wacid.1"); it.toggleFull() }
    @Test fun transcriptPending() = console { it.toggleTranscript("wacid.3") }
    @Test fun transcriptRecorded() = console { it.toggleTranscript("wacid.5") }
    @Test fun transcriptFailed() = console { it.toggleTranscript("wacid.6") }
    @Test fun transcriptLoading() = console(fake = fake().also { it.on("GET", "/admin/calls/wacid.5/transcript", code = 500, body = "{}") }) {
        it.toggleTranscript("wacid.5")
    }
    @Test fun transcriptNotEnabled() = console(
        fake = fake().also { it.on("POST", "/admin/calls/wacid.5/transcribe", code = 409, body = """{"detail":"Transcription isn't enabled yet."}""") },
    ) { it.toggleTranscript("wacid.5"); it.runTranscribe() }

    @Test fun callerPane() = console { vm -> vm.select(peterCall) }
    @Test fun callerPaneDark() = console(dark = true) { vm -> vm.select(peterCall) }

    @Test fun logLong() = console(fake = fake().also { it.on("GET", "/admin/calls", body = CallsFixtures.longLog) })
    @Test fun logLongDark() = console(dark = true, fake = fake().also { it.on("GET", "/admin/calls", body = CallsFixtures.longLog) })

    @Test fun cardRingingSmallPhone() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.NEXUS_5)
        card(peter.copy(phase = CallPhase.Ringing))
    }
    @Test fun cardInCallSmallPhone() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.NEXUS_5)
        card(peter.copy(phase = CallPhase.InCall, seconds = 187))
    }
    @Test fun tabletCardInCall() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_C)
        card(peter.copy(phase = CallPhase.InCall, seconds = 187))
    }

    @Test fun tabletLog() = console(device = DeviceConfig.PIXEL_C)
    @Test fun tabletCallerPane() = console(device = DeviceConfig.PIXEL_C) { vm ->
        vm.select(peterCall); vm.toggleTranscript("wacid.1")
    }
    @Test fun tabletCallerPaneDark() = console(device = DeviceConfig.PIXEL_C, dark = true) { vm -> vm.select(peterCall) }
    @Test fun tabletCardRinging() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_C)
        card(peter.copy(phase = CallPhase.Ringing))
    }
}
