package ke.co.bethanyhouse.neema.calls

import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.lifecycle.viewmodel.compose.viewModel
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.feature.calls.AudioRoute
import ke.co.bethanyhouse.neema.feature.calls.AudioRouteKind
import ke.co.bethanyhouse.neema.feature.calls.CallActions
import ke.co.bethanyhouse.neema.feature.calls.WaitingCall
import ke.co.bethanyhouse.neema.feature.calls.CallCard
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
 * The call screen in every live phase (the wrap-ups are CallsWrapUpScreenshotTest),
 * the Calls view (populated, loading, empty, Follow-ups, every transcript state,
 * the readiness prompts) and a call's details — phone, dark and tablet.
 *   ./gradlew :app:recordPaparazziDebug --tests '*CallsScreenshotTest'
 */
class CallsScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)
    @get:Rule val clock = ke.co.bethanyhouse.neema.testing.PinnedClock()

    private val peter = CallUiState(callId = CallsFixtures.C1, from = "254712345678", name = "Fr. Peter Kamau")
    private val peterCall = Call(
        id = CallsFixtures.K1, callId = CallsFixtures.C1, waId = "254712345678", name = "Fr. Peter Kamau", status = "completed",
        duration = 184, agentName = "Moses Mwicigi", startedAt = Fixtures.ago(40), answeredAt = Fixtures.ago(40), endedAt = Fixtures.ago(37),
        summary = "Wants two black clergy shirts delivered to Nyeri by Friday.", transcriptStatus = "done", hasRecording = true,
        insightsRaw = ke.co.bethanyhouse.neema.core.net.NeemaJson.parseToJsonElement(CallsFixtures.PETER_INSIGHTS),
    )
    private val missedCall = Call(
        id = "5b0f7d0e-8a1c-4a8e-9d64-0f1e2d3c4b02", callId = CallsFixtures.C2, waId = "254722000111", name = "Rev. Mary Achieng",
        status = "missed", startedAt = Fixtures.ago(130), endedAt = Fixtures.ago(129), followUpOpen = true,
    )

    private fun card(s: CallUiState, dark: Boolean = false) = paparazzi.snapshot {
        AppFrame(dark) { CallCard(s, CallActions()) }
    }

    // ── The call screen, phase by phase (CALLING_UX.md §3) ─────────────────
    @Test fun cardRinging() = card(peter.copy(phase = CallPhase.Ringing))
    @Test fun cardRingingUnknownNumber() = card(CallUiState(phase = CallPhase.Ringing, callId = "x", from = "254700123456"))
    @Test fun cardRingingLongName() = card(peter.copy(phase = CallPhase.Ringing, name = "The Most Reverend Archbishop Emmanuel Wabukala Onyango-Kipchumba"))
    @Test fun cardConnecting() = card(peter.copy(phase = CallPhase.Connecting))
    @Test fun cardOutboundPlacing() = card(CallUiState(phase = CallPhase.Placing, callId = "pending", from = "254733444555", name = "Deacon James Mwangi", outbound = true))
    @Test fun cardOutboundRinging() = card(CallUiState(phase = CallPhase.RingingOut, callId = "wacid.out", from = "254733444555", name = "Deacon James Mwangi", outbound = true))
    @Test fun cardInCall() = card(peter.copy(phase = CallPhase.InCall, seconds = 187, recording = true))
    @Test fun cardInCallMutedSpeaker() = card(peter.copy(phase = CallPhase.InCall, seconds = 3_725, muted = true, route = AudioRoute.Speaker))
    @Test fun cardInCallBluetooth() = card(
        peter.copy(
            phase = CallPhase.InCall, seconds = 64, route = AudioRoute(AudioRouteKind.Bluetooth, "Jabra Talk 25"),
            routes = listOf(AudioRoute.Earpiece, AudioRoute.Speaker, AudioRoute(AudioRouteKind.Bluetooth, "Jabra Talk 25")),
        ),
    )
    @Test fun cardInCallWaiting() = card(peter.copy(phase = CallPhase.InCall, seconds = 95, waiting = WaitingCall("wacid.2", "254799999999", "Sr. Agnes Wairimu")))
    @Test fun transcriptNoRecording() = console(
        fake = fake().also {
            // The only way to reach that 409: a failed row whose recording_url is gone.
            it.on("GET", CallsFixtures.route(CallsFixtures.C6, "transcript"), body = CallsFixtures.transcript(CallsFixtures.C6, "failed", hasRecording = false))
            it.on("POST", CallsFixtures.route(CallsFixtures.C6, "transcribe"), code = 409, body = CallsFixtures.NO_RECORDING)
        },
    ) { it.toggleTranscript(CallsFixtures.C6); it.runTranscribe() }
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
    @Test fun logFollowUps() = console { it.followUpsOnly.value = true }
    @Test fun logFollowUpsEmpty() = console(fake = fake().also { it.on("GET", "/admin/calls", body = "[]") }) { it.followUpsOnly.value = true }
    @Test fun logLoading() = console(fake = fake().also { it.hang("GET", "/admin/calls") })
    @Test fun logNeedsNotifications() = console(readiness = CallReadiness(notifications = false))
    @Test fun logNeedsFullScreen() = console(readiness = CallReadiness(fullScreen = false))
    @Test fun logNeedsFullScreenDark() = console(dark = true, readiness = CallReadiness(fullScreen = false))
    @Test fun logNeedsBattery() = console(readiness = CallReadiness(battery = false))
    @Test fun logNeedsBatteryDark() = console(dark = true, readiness = CallReadiness(battery = false))
    @Test fun logNeedsBackground() = console(readiness = CallReadiness(background = false, battery = false))

    @Test fun transcriptDone() = console { it.toggleTranscript(CallsFixtures.C1) }
    @Test fun transcriptDoneFull() = console { it.toggleTranscript(CallsFixtures.C1); it.toggleFull() }
    @Test fun transcriptPending() = console { it.toggleTranscript(CallsFixtures.C3) }
    @Test fun transcriptRecorded() = console { it.toggleTranscript(CallsFixtures.C5) }
    @Test fun transcriptFailed() = console { it.toggleTranscript(CallsFixtures.C6) }
    @Test fun transcriptLoadFailed() = console(fake = fake().also { it.on("GET", CallsFixtures.route(CallsFixtures.C5, "transcript"), code = 500, body = "{}") }) {
        it.toggleTranscript(CallsFixtures.C5)
    }
    @Test fun transcriptNotEnabled() = console(
        fake = fake().also { it.on("POST", CallsFixtures.route(CallsFixtures.C5, "transcribe"), code = 409, body = CallsFixtures.WHISPER_OFF) },
    ) { it.toggleTranscript(CallsFixtures.C5); it.runTranscribe() }

    @Test fun callerPane() = console { vm -> vm.select(peterCall) }
    @Test fun callerPaneDark() = console(dark = true) { vm -> vm.select(peterCall) }
    @Test fun callDetailsMissedFollowUp() = console { vm -> vm.select(missedCall) }

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
        vm.select(peterCall); vm.toggleTranscript(CallsFixtures.C1)
    }
    @Test fun tabletCallerPaneDark() = console(device = DeviceConfig.PIXEL_C, dark = true) { vm -> vm.select(peterCall) }
    @Test fun tabletCardRinging() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_C)
        card(peter.copy(phase = CallPhase.Ringing))
    }
}
