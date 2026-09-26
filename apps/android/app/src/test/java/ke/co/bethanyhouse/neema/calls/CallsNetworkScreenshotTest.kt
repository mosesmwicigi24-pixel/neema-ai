package ke.co.bethanyhouse.neema.calls

import androidx.compose.runtime.remember
import androidx.lifecycle.viewmodel.compose.viewModel
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
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
import java.net.ConnectException

/**
 * The softphone and the call console when the network misbehaves: a call
 * reconnecting after a blip, a lost connection, a callback being saved or
 * still retrying, the console offline (empty and with the last log kept), and
 * a transcript that could not load.
 *   ./gradlew :app:recordPaparazziDebug --tests '*CallsNetworkScreenshotTest'
 */
class CallsNetworkScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private val peter = CallUiState(callId = CallsFixtures.C1, from = "254712345678", name = "Fr. Peter Kamau")

    private fun card(s: CallUiState, dark: Boolean = false) = paparazzi.snapshot { AppFrame(dark) { CallCard(s, CallActions()) } }

    @Test fun cardReconnecting() = card(peter.copy(phase = CallPhase.InCall, seconds = 187, reconnecting = true))
    @Test fun cardReconnectingDark() = card(peter.copy(phase = CallPhase.InCall, seconds = 187, reconnecting = true), dark = true)
    @Test fun cardConnectionLost() = card(peter.copy(phase = CallPhase.Ended, seconds = 187, note = CallManager.CONNECTION_LOST))
    @Test fun cardSavingCallback() = card(peter.copy(phase = CallPhase.Ringing, busy = true))
    @Test fun cardCallbackRetrying() = card(peter.copy(phase = CallPhase.Ended, note = CallManager.CALLBACK_RETRYING))
    @Test fun cardAnswerOffline() = card(peter.copy(phase = CallPhase.Connecting, error = CallManager.ANSWER_OFFLINE))
    @Test fun cardOutboundUnconfirmed() = card(
        CallUiState(phase = CallPhase.Connecting, callId = "pending", from = "254733444555", name = "Deacon James Mwangi",
            outbound = true, error = CallManager.UNCONFIRMED_CALL),
    )
    @Test fun cardReconnectingSmallPhone() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.NEXUS_5)
        card(peter.copy(phase = CallPhase.InCall, seconds = 187, reconnecting = true))
    }

    // ── The console ──────────────────────────────────────────────────────────
    private fun fake() = FakeNeema.withFixtures().also(CallsFixtures::install)

    private fun console(
        device: DeviceConfig = DeviceConfig.PIXEL_6,
        dark: Boolean = false,
        fake: FakeNeema = fake(),
        setup: (CallsViewModel) -> Unit = {},
    ) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        val dash = dashboard(paparazzi.context, fake)
        paparazzi.snapshot {
            AppFrame(dark) {
                val vm: CallsViewModel = viewModel { CallsViewModel(dash) }
                remember { setup(vm) }
                CallsScreen(dash, readinessOverride = CallReadiness())
            }
        }
    }

    private fun offline(f: FakeNeema) = f.on("GET", "/admin/calls") { _, _ -> throw ConnectException("Failed to connect") }

    /** The log loads once, then the network goes: every later request fails. */
    private fun dropsAfterFirstLoad(f: FakeNeema) {
        var n = 0
        f.on("GET", "/admin/calls") { _, _ -> if (n++ == 0) 200 to CallsFixtures.calls else throw ConnectException("Failed to connect") }
    }

    @Test fun logOffline() = console(fake = fake().also(::offline))
    @Test fun logOfflineDark() = console(dark = true, fake = fake().also(::offline))
    @Test fun logServerDown() = console(fake = fake().also { it.on("GET", "/admin/calls", code = 502, body = "<html><body>502 Bad Gateway</body></html>") })

    @Test fun logKeptAfterAFailedRefresh() {
        val f = fake().also(::dropsAfterFirstLoad)
        console(fake = f) { vm -> vm.load() }
    }
    @Test fun logKeptAfterAFailedRefreshDark() {
        val f = fake().also(::dropsAfterFirstLoad)
        console(dark = true, fake = f) { vm -> vm.load() }
    }
    @Test fun tabletLogKeptAfterAFailedRefresh() {
        val f = fake().also(::dropsAfterFirstLoad)
        console(device = DeviceConfig.PIXEL_C, fake = f) { vm -> vm.load() }
    }

    @Test fun transcriptOffline() = console(
        fake = fake().also { it.on("GET", CallsFixtures.route(CallsFixtures.C5, "transcript")) { _, _ -> throw ConnectException("Failed to connect") } },
    ) { it.toggleTranscript(CallsFixtures.C5) }
    @Test fun transcriptOfflineDark() = console(
        dark = true,
        fake = fake().also { it.on("GET", CallsFixtures.route(CallsFixtures.C5, "transcript")) { _, _ -> throw ConnectException("Failed to connect") } },
    ) { it.toggleTranscript(CallsFixtures.C5) }
}
