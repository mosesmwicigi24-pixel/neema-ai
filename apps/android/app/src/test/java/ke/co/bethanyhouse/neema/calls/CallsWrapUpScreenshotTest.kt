package ke.co.bethanyhouse.neema.calls

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.feature.calls.CallActions
import ke.co.bethanyhouse.neema.feature.calls.CallCard
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallOutcome
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallUiState
import ke.co.bethanyhouse.neema.feature.calls.CallbackSave
import ke.co.bethanyhouse.neema.feature.calls.MinimisedCallBar
import ke.co.bethanyhouse.neema.feature.calls.PermissionGrant
import ke.co.bethanyhouse.neema.feature.calls.PermissionGrantBanner
import ke.co.bethanyhouse.neema.feature.calls.WaitingBanner
import ke.co.bethanyhouse.neema.feature.calls.WaitingCall
import ke.co.bethanyhouse.neema.feature.conversations.ThreadMsg
import ke.co.bethanyhouse.neema.feature.conversations.ThreadCallEvent
import ke.co.bethanyhouse.neema.feature.conversations.customer.CallOnWhatsAppContent
import ke.co.bethanyhouse.neema.feature.conversations.customer.CallPlatform
import ke.co.bethanyhouse.neema.orders.Devices
import ke.co.bethanyhouse.neema.orders.Tappable
import ke.co.bethanyhouse.neema.orders.TouchAudit
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * After the call and around it (CALLING_UX.md §3 wrap-ups, §6, §7): the
 * wrap-up card for every outcome (phone, tablet, 200% text), the minimised
 * bar, the second-caller banner, "allowed calls", the Messenger / Instagram
 * "call on WhatsApp instead" sheets, and the thread's call pill with its
 * summary card. Every shot checks each tappable is labelled.
 *   ./gradlew :app:recordPaparazziDebug --tests '*CallsWrapUpScreenshotTest'
 */
class CallsWrapUpScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)
    @get:Rule val clock = ke.co.bethanyhouse.neema.testing.PinnedClock()

    private val audit = TouchAudit()
    private val peter = CallUiState(
        phase = CallPhase.Ended, callId = CallsFixtures.C1, from = "254712345678", name = "Fr. Peter Kamau", conversationId = "c1",
    )
    private val james = CallUiState(
        phase = CallPhase.Ended, callId = "wacid.out", from = "254733444555", name = "Deacon James Mwangi", outbound = true,
    )

    private fun shot(device: DeviceConfig = DeviceConfig.PIXEL_6, dark: Boolean = false, content: @Composable () -> Unit) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        paparazzi.snapshot { AppFrame(dark) { audit.Wrap(content) } }
        assertEquals("unlabelled tappables", emptyList<Tappable>(), audit.unlabelled())
        assertEquals("tappables under 48dp", emptyList<Tappable>(), audit.tooSmall(48.dp, ""))
    }

    private fun card(s: CallUiState, device: DeviceConfig = DeviceConfig.PIXEL_6) = shot(device) { CallCard(s, CallActions()) }

    // ── The wrap-up, outcome by outcome ─────────────────────────────────────
    @Test fun completed() = card(peter.copy(seconds = 252, outcome = CallOutcome.Completed, recordingNote = CallManager.RECORDING_SAVED_AUTO))
    @Test fun answeredElsewhere() = card(peter.copy(outcome = CallOutcome.AnsweredElsewhere("Ann Wanjiru")))
    @Test fun declined() = card(peter.copy(outcome = CallOutcome.Declined()))
    @Test fun missed() = card(peter.copy(outcome = CallOutcome.Missed()))
    @Test fun missedAlreadyEnded() = card(peter.copy(outcome = CallOutcome.Missed(CallManager.CALL_GONE)))
    @Test fun callback() = card(peter.copy(outcome = CallOutcome.Callback(CallbackSave.Saved)))
    @Test fun noAnswer() = card(james.copy(outcome = CallOutcome.NoAnswer))
    @Test fun cancelled() = card(james.copy(outcome = CallOutcome.Cancelled))
    @Test fun connectionLost() = card(peter.copy(seconds = 133, outcome = CallOutcome.ConnectionLost, recordingNote = CallManager.RECORDING_SAVED_MANUAL))
    @Test fun failed() = card(james.copy(outcome = CallOutcome.Failed("The customer's phone is switched off")))
    @Test fun permissionNeeded() = card(james.copy(outcome = CallOutcome.PermissionNeeded))
    @Test fun permissionNeededSending() = card(james.copy(outcome = CallOutcome.PermissionNeeded, busy = true))
    @Test fun permissionNeededSendFailed() = card(
        james.copy(outcome = CallOutcome.PermissionNeeded, error = "No connection — the call request wasn't sent"),
    )
    @Test fun permissionRequested() = card(james.copy(outcome = CallOutcome.PermissionRequested))
    @Test fun micBlocked() = card(peter.copy(outcome = CallOutcome.MicBlocked))

    @Test fun missedTablet() = card(peter.copy(outcome = CallOutcome.Missed()), DeviceConfig.PIXEL_C)
    @Test fun completedHugeText() = card(peter.copy(seconds = 252, outcome = CallOutcome.Completed), Devices.HugeText)
    @Test fun permissionNeededHugeText() = card(james.copy(outcome = CallOutcome.PermissionNeeded), Devices.HugeText)
    @Test fun connectionLost320() = card(peter.copy(seconds = 133, outcome = CallOutcome.ConnectionLost), Devices.Narrow320HugeText)
    @Test fun missedLandscape() = card(peter.copy(outcome = CallOutcome.Missed()), Devices.PhoneLandscape)

    // ── Minimised, a second caller, "allowed calls" (§6, §3) ────────────────
    @Composable
    private fun OverApp(content: @Composable () -> Unit) {
        // The bar pinned above the app's content, which stays usable under it.
        Column(Modifier.fillMaxSize().background(Neema.colors.surface)) { content() }
    }

    @Test fun minimisedInCall() = shot {
        OverApp { MinimisedCallBar(peter.copy(phase = CallPhase.InCall, seconds = 187), CallActions()) }
    }
    @Test fun minimisedReconnecting() = shot {
        OverApp { MinimisedCallBar(peter.copy(phase = CallPhase.InCall, seconds = 187, reconnecting = true, muted = true), CallActions()) }
    }
    @Test fun minimisedRingingOut() = shot {
        OverApp { MinimisedCallBar(james.copy(phase = CallPhase.RingingOut), CallActions()) }
    }
    @Test fun minimisedEnded() = shot {
        OverApp { MinimisedCallBar(peter.copy(seconds = 252, outcome = CallOutcome.Completed), CallActions()) }
    }
    @Test fun minimisedWithWaitingCallerHugeText() = shot(Devices.HugeText) {
        OverApp {
            MinimisedCallBar(peter.copy(phase = CallPhase.InCall, seconds = 187), CallActions())
            WaitingBanner(WaitingCall("wacid.2", "254799999999", "Sr. Agnes Wairimu"), CallActions())
        }
    }
    @Test fun permissionGranted() = shot {
        OverApp { PermissionGrantBanner(PermissionGrant("254733444555", "Deacon James Mwangi"), onCall = {}, onDismiss = {}) }
    }
    @Test fun permissionGrantedDark() = shot(dark = true) {
        OverApp { PermissionGrantBanner(PermissionGrant("254733444555", "Deacon James Mwangi"), onCall = {}, onDismiss = {}) }
    }

    // ── Messenger / Instagram: no business calling — WhatsApp instead ───────
    private fun sheet(platform: CallPlatform, phone: String?, dark: Boolean = false, device: DeviceConfig = DeviceConfig.PIXEL_6) = shot(device, dark) {
        Column(Modifier.fillMaxSize().background(Neema.colors.bg2).padding(top = 24.dp)) {
            CallOnWhatsAppContent(platform, "Grace", phone, onCall = {}, onAsk = {}, onDismiss = {})
        }
    }
    @Test fun messengerSheetWithPhone() = sheet(CallPlatform.Messenger, "254711222333")
    @Test fun messengerSheetNoPhone() = sheet(CallPlatform.Messenger, null)
    @Test fun instagramSheetWithPhone() = sheet(CallPlatform.Instagram, "254711222333")
    @Test fun instagramSheetNoPhoneDark() = sheet(CallPlatform.Instagram, null, dark = true)
    @Test fun messengerSheetHugeText() = sheet(CallPlatform.Messenger, "254711222333", device = Devices.HugeText)

    // ── The thread's call pills and the summary card (§7) ───────────────────
    private fun callEvent(id: String, label: String, row: String, agent: String?, summary: String?, minutes: Long) = ThreadMsg(
        id = id, type = "system_event", direction = "inbound", sender = "human_agent", text = label,
        createdAt = Fixtures.ago(minutes), eventKind = "call", eventReason = summary, agentName = agent,
        callRaw = NeemaJson.parseToJsonElement(row),
    )

    private val summarised = callEvent(
        "call-k1", "Incoming call · 3:04",
        CallsFixtures.row(
            CallsFixtures.K1, CallsFixtures.C1, "254712345678", "Fr. Peter Kamau", "inbound", "completed", 184, "Moses Mwicigi",
            CallsFixtures.pyIso(40), "Wants two black clergy shirts delivered to Nyeri by Friday.", "done", true,
            insights = CallsFixtures.PETER_INSIGHTS,
        ),
        "Moses Mwicigi", "Wants two black clergy shirts delivered to Nyeri by Friday.", 40,
    )
    private val missedPill = callEvent(
        "call-k2", "Missed call",
        CallsFixtures.row("k2", CallsFixtures.C2, "254712345678", "Fr. Peter Kamau", "inbound", "missed", null, null, CallsFixtures.pyIso(130), null, "none", false),
        null, null, 130,
    )
    private val outgoing = callEvent(
        "call-k3", "Outgoing call · no answer",
        CallsFixtures.row("k3", CallsFixtures.C3, "254712345678", "Fr. Peter Kamau", "outbound", "no_answer", null, "Grace Wanjiru", CallsFixtures.pyIso(20), null, "none", false),
        "Grace Wanjiru", null, 20,
    )
    /** A row the server sent in a shape this build doesn't know: the pill still shows its label. */
    private val odd = ThreadMsg(
        id = "call-odd", type = "system_event", sender = "human_agent", text = "Call", createdAt = Fixtures.ago(5), eventKind = "call",
        callRaw = NeemaJson.parseToJsonElement("""{"call_id":5,"status":["?"],"insights":"not an object"}"""),
    )

    private fun thread(dark: Boolean = false, device: DeviceConfig = DeviceConfig.PIXEL_6) = shot(device, dark) {
        Column(
            Modifier.fillMaxSize().background(if (dark) Neema.colors.bg else Palette.Mist).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            listOf(missedPill, summarised, outgoing, odd).forEach { ThreadCallEvent(it, onUseAsReply = {}) }
        }
    }
    @Test fun threadCallPills() = thread()
    @Test fun threadCallPillsDark() = thread(dark = true)
    @Test fun threadCallPillsHugeText() = thread(device = Devices.HugeText)
    @Test fun threadCallPillsTablet() = thread(device = DeviceConfig.PIXEL_C)
}
