package ke.co.bethanyhouse.neema.calls

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.feature.calls.CallActions
import ke.co.bethanyhouse.neema.feature.calls.CallCard
import ke.co.bethanyhouse.neema.feature.calls.CallChannelBadge
import ke.co.bethanyhouse.neema.feature.calls.CallManager
import ke.co.bethanyhouse.neema.feature.calls.CallOutcome
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.CallUiState
import ke.co.bethanyhouse.neema.feature.calls.MinimisedCallBar
import ke.co.bethanyhouse.neema.feature.calls.PermissionGrant
import ke.co.bethanyhouse.neema.feature.calls.PermissionGrantBanner
import ke.co.bethanyhouse.neema.feature.calls.WaitingBanner
import ke.co.bethanyhouse.neema.feature.calls.WaitingCall
import ke.co.bethanyhouse.neema.feature.conversations.ThreadCallEvent
import ke.co.bethanyhouse.neema.feature.conversations.ThreadMsg
import ke.co.bethanyhouse.neema.feature.conversations.customer.CallButton
import ke.co.bethanyhouse.neema.feature.conversations.customer.CallOnWhatsAppContent
import ke.co.bethanyhouse.neema.feature.conversations.customer.CallPlatform
import ke.co.bethanyhouse.neema.feature.conversations.customer.ReachCallButton
import ke.co.bethanyhouse.neema.orders.Devices
import ke.co.bethanyhouse.neema.orders.Tappable
import ke.co.bethanyhouse.neema.orders.TouchAudit
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.fixtures.CallsFixtures
import androidx.compose.runtime.remember
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.feature.calls.CallReadiness
import ke.co.bethanyhouse.neema.feature.calls.CallsScreen
import ke.co.bethanyhouse.neema.feature.calls.CallsViewModel
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * A Messenger call (CALLING_UX.md §2.0, §5): the same card, layout and
 * controls as WhatsApp's, in Messenger's look — the blue → purple avatar
 * ring, the blue Answer, the darker blue behind white words, "Messenger
 * voice call" with its glyph, never a PSID. Plus the panel's Call button
 * with Messenger calling on and off, the "call on WhatsApp instead" sheet's
 * words, and the channel badges on the thread's pills.
 *   ./gradlew :app:recordPaparazziDebug --tests '*CallsMessengerScreenshotTest'
 */
class CallsMessengerScreenshotTest {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)
    @get:Rule val clock = ke.co.bethanyhouse.neema.testing.PinnedClock()

    private val audit = TouchAudit()
    private val grace = CallUiState(callId = "c_in1", from = "7788990011", name = "Grace Wanjiku", channel = "messenger", conversationId = "conv-grace")

    private fun shot(device: DeviceConfig = DeviceConfig.PIXEL_6, dark: Boolean = false, content: @Composable () -> Unit) {
        paparazzi.unsafeUpdateConfig(deviceConfig = device)
        paparazzi.snapshot { AppFrame(dark) { audit.Wrap(content) } }
        assertEquals("unlabelled tappables", emptyList<Tappable>(), audit.unlabelled())
        assertEquals("tappables under 48dp", emptyList<Tappable>(), audit.tooSmall(48.dp, ""))
    }

    private fun card(s: CallUiState, device: DeviceConfig = DeviceConfig.PIXEL_6) = shot(device) { CallCard(s, CallActions()) }

    // ── The call card ───────────────────────────────────────────────────────
    @Test fun ringingNoName() = card(grace.copy(name = null, phase = CallPhase.Ringing))
    @Test fun ringingNamed() = card(grace.copy(phase = CallPhase.Ringing))
    @Test fun ringingOutEarlyMedia() = card(grace.copy(phase = CallPhase.RingingOut, outbound = true))
    @Test fun active() = card(grace.copy(phase = CallPhase.InCall, seconds = 95))
    @Test fun activeHugeText() = card(grace.copy(phase = CallPhase.InCall, seconds = 95), Devices.HugeText)
    @Test fun wrapUpCompleted() = card(grace.copy(phase = CallPhase.Ended, seconds = 252, outcome = CallOutcome.Completed))
    @Test fun wrapUpPermissionNeeded() = card(grace.copy(phase = CallPhase.Ended, outbound = true, outcome = CallOutcome.PermissionNeeded))
    @Test fun wrapUpCallingOff() = card(grace.copy(phase = CallPhase.Ended, outbound = true, outcome = CallOutcome.Failed(CallManager.MESSENGER_OFF, "none")))

    @Test fun minimisedWithWaitingMessengerCaller() = shot {
        Column(Modifier.fillMaxSize().background(Palette.Call.WaBottom)) {
            MinimisedCallBar(grace.copy(phase = CallPhase.InCall, seconds = 187), CallActions())
            WaitingBanner(WaitingCall("c_in2", "7788990022", null, "messenger"), CallActions())
            PermissionGrantBanner(PermissionGrant("7788990011", "Grace Wanjiku", "messenger"), onCall = {}, onDismiss = {})
        }
    }

    // ── The panel's Call button: Messenger on / off, and the sheet ──────────
    @Test fun callButtonsOnAndOff() = shot {
        Column(Modifier.fillMaxSize().background(Neema.colors.bg2).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            // Messenger calling on: calls on Messenger. Off: opens the sheet. Instagram: always the sheet. WhatsApp: its green.
            listOf(
                CallButton.OnMessenger("7788990011"), CallButton.Sheet(CallPlatform.Messenger),
                CallButton.Sheet(CallPlatform.Instagram), CallButton.OnWhatsApp("254711222333"),
            ).forEach { b ->
                Row(Modifier.fillMaxWidth()) { ReachCallButton(b, busy = false, modifier = Modifier.weight(1f).heightIn(min = 48.dp), onClick = {}) }
            }
        }
    }
    @Test fun sheetMessengerOff() = shot {
        Column(Modifier.fillMaxSize().background(Neema.colors.bg2).padding(top = 24.dp)) {
            CallOnWhatsAppContent(CallPlatform.Messenger, "Grace", "254711222333", onCall = {}, onAsk = {}, onDismiss = {})
        }
    }

    // ── Channel badges ──────────────────────────────────────────────────────
    private fun pill(id: String, label: String, channel: String, status: String, direction: String, minutes: Long) = ThreadMsg(
        id = id, type = "system_event", direction = "inbound", sender = "human_agent", text = label,
        createdAt = Fixtures.ago(minutes), eventKind = "call",
        callRaw = NeemaJson.parseToJsonElement(
            CallsFixtures.row(id, "call-$id", if (channel == "messenger") null else "254712345678", "Grace Wanjiku", direction, status,
                if (status == "completed") 95 else null, "Moses Mwicigi", CallsFixtures.pyIso(minutes), null, "none", false)
                .replace("\"channel\":\"whatsapp\"", "\"channel\":\"$channel\""),
        ),
    )

    private fun badges(dark: Boolean) = shot(dark = dark) {
        Column(
            Modifier.fillMaxSize().background(if (dark) Neema.colors.bg else Palette.Mist).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CallChannelBadge("whatsapp", onDark = dark)
                CallChannelBadge("messenger", onDark = dark)
            }
            Row(Modifier.background(Color(0xFF0B1410)).padding(8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                CallChannelBadge("whatsapp", onDark = true)
                CallChannelBadge("messenger", onDark = true)
            }
            ThreadCallEvent(pill("m1", "Incoming call · 1:35", "messenger", "completed", "inbound", 40), onUseAsReply = {})
            ThreadCallEvent(pill("m2", "Outgoing call", "messenger", "rejected", "outbound", 20), onUseAsReply = {})
            ThreadCallEvent(pill("w1", "Missed call", "whatsapp", "missed", "inbound", 10), onUseAsReply = {})
        }
    }
    @Test fun badgesLight() = badges(dark = false)
    @Test fun badgesDark() = badges(dark = true)

    // ── The Calls log with both apps: a badge on every row, the app filter ──
    private fun messengerRow(id: String, name: String?, status: String, direction: String, minutes: Long) =
        CallsFixtures.row(id, "c_$id", null, name, direction, status, if (status == "completed") 95 else null,
            if (status == "completed") "Moses Mwicigi" else null, CallsFixtures.pyIso(minutes), null, "none", false,
            conversationId = "conv-$id")
            .replace("\"channel\":\"whatsapp\"", "\"channel\":\"messenger\",\"external_id\":\"77889900$id\"")

    private val mixed get() = CallsFixtures.calls.removePrefix("[").let { rest ->
        "[" + listOf(
            messengerRow("11", null, "missed", "inbound", 5),
            messengerRow("12", "Grace Wanjiku", "completed", "inbound", 25),
            messengerRow("13", "Grace Wanjiku", "rejected", "outbound", 30),
        ).joinToString(",") + "," + rest
    }

    private fun console(setup: (CallsViewModel) -> Unit = {}) {
        val fake = FakeNeema.withFixtures().also(CallsFixtures::install).also { it.on("GET", "/admin/calls", body = mixed) }
        val dash = dashboard(paparazzi.context, fake)
        paparazzi.snapshot {
            AppFrame(false) {
                val vm: CallsViewModel = viewModel { CallsViewModel(dash) }
                remember { setup(vm) }
                CallsScreen(dash, readinessOverride = CallReadiness())
            }
        }
    }
    @Test fun logBothApps() = console()
    @Test fun logMessengerOnly() = console { it.channelFilter.value = "messenger" }
    @Test fun detailsMessengerCall() = console { vm ->
        vm.select(Call(id = "12", callId = "c_12", channel = "messenger", externalId = "7788990012", name = "Grace Wanjiku", direction = "inbound",
            status = "completed", duration = 95, agentName = "Moses Mwicigi", startedAt = Fixtures.ago(25), conversationId = "conv-12"))
    }
}
