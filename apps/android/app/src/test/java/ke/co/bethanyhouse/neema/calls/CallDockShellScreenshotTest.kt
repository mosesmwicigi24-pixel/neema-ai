package ke.co.bethanyhouse.neema.calls

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardShell
import ke.co.bethanyhouse.neema.app.ShellShotsAccess
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.feature.calls.CallPhase
import ke.co.bethanyhouse.neema.feature.calls.MESSENGER
import ke.co.bethanyhouse.neema.feature.calls.WHATSAPP
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.TestDevice
import ke.co.bethanyhouse.neema.testing.snapshotOn
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * The whole shell with a live call on it, WhatsApp and Messenger: docked
 * beside the inbox on the Tab S9 Ultra in landscape, over it in portrait and
 * on a phone. The microphone prompt's host sits outside both places the card
 * can be, so the card moving between them (rotating the tablet mid-call)
 * can't take the permission request with it.
 */
class CallDockShellScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.TAB_S9U.config, showSystemUi = false, maxPercentDifference = 0.1)

    @get:Rule
    val main = ke.co.bethanyhouse.neema.testing.MainDispatcherRule()

    private val devices = listOf(DeviceMatrix.TAB_S9U, DeviceMatrix.TAB_S9U_PORTRAIT, DeviceMatrix.PHONE)

    private fun ringing(channel: String, list: List<TestDevice> = devices) = list.forEach { d ->
        val dash = ShellShotsAccess.live(paparazzi.context, d.dark)
        dash.navigate(ViewId.Conversations)
        val calls = dash.container.calls
        calls.onFrame(JsonObject(buildMap {
            put("type", JsonPrimitive("incoming_call"))
            put("call_id", JsonPrimitive(if (channel == MESSENGER) "c_msg.dock" else "wacid.dock"))
            put("from", JsonPrimitive(if (channel == MESSENGER) "7788990011" else "254712345678"))
            put("name", JsonPrimitive("Fr. Peter Kamau"))
            if (channel == MESSENGER) put("channel", JsonPrimitive(MESSENGER))
        }))
        assertEquals(CallPhase.Ringing, calls.state.value.phase)
        paparazzi.snapshotOn(d) { AppFrame(d.dark) { DashboardShell(dash, d.widthClass) } }
    }

    @Test fun whatsappCall() = ringing(WHATSAPP)
    @Test fun messengerCall() = ringing(MESSENGER)
    @Test fun whatsappCallDark() = ringing(WHATSAPP, listOf(DeviceMatrix.TAB_S9U.dark()))
}
