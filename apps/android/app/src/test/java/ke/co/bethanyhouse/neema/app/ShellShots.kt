package ke.co.bethanyhouse.neema.app

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import ke.co.bethanyhouse.neema.core.notify.AppNotification
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.dashboard
import kotlinx.coroutines.Dispatchers

/** Shared set-up for the shell's screenshot tests. */
internal object ShellShots {
    const val NOW = 1_750_000_000_000L

    /** A signed-in dashboard whose live socket is up (no "Reconnecting…" pill). */
    fun live(
        ctx: Context, dark: Boolean = false, fake: FakeNeema = FakeNeema.withFixtures(),
        role: String = "admin", superuser: Boolean = true, connected: Boolean = true,
        notifications: List<String> = emptyList(),
        persona: ke.co.bethanyhouse.neema.testing.Persona? = null,
    ): DashboardViewModel {
        val ws = FakeSocketFactory()
        val dash = dashboard(ctx, fake, role, superuser, appDispatcher = Dispatchers.Unconfined, wsFactory = ws, persona = persona)
        dash.container.prefs.setDark(dark)
        dash.container.notifications.start(dash.container.foreground)
        dash.container.socket.connect(Fixtures.ME_ID)
        if (connected) ws.last.open()
        notifications.forEach { ws.last.frame(it) }
        return dash
    }

    /** Live frames with a `ts`, so "45m ago" labels are stable between runs. */
    val frames get() = listOf(
        """{"event":"notification","type":"order_update","title":"📦 Order BH-1042 paid","body":"KES 8,000 via M-Pesa — Fr. Peter Kamau","ts":"${Fixtures.ago(45)}"}""",
        """{"event":"notification","type":"new_conversation","title":"New chat from Rev. Mary Achieng","body":"Asante! How much is the purple cassock?","wa_id":"254722000111","ts":"${Fixtures.ago(9)}"}""",
        """{"event":"notification","type":"intercept","title":"🤖 AI Escalation","body":"Customer asked for a custom embroidered stole with the parish crest — needs a human quote","conversationId":"c1","ts":"${Fixtures.ago(2)}"}""",
    )

    fun sample(now: Long = NOW) = listOf(
        AppNotification("n1", "intercept", "🤖 AI Escalation", "Customer asked for a custom embroidered stole with the parish crest — needs a human quote before Friday", "c1", now - 2 * 60_000),
        AppNotification("n2", "new_conversation", "New chat from Rev. Mary Achieng", "Asante! How much is the purple cassock?", "254722000111", now - 9 * 60_000),
        AppNotification("n3", "order_update", "📦 Order BH-1042 paid", "KES 8,000 via M-Pesa", null, now - 45 * 60_000, read = true),
        AppNotification("n4", "transfer", "Transferred to you", "Grace Wanjiru handed over Deacon James Mwangi", "c6", now - 3 * 3_600_000, read = true),
        AppNotification("n5", "standup", "☀️ Neema's morning standup", "3 deals need a follow-up today; 1 order is waiting on payment.", null, now - 26 * 3_600_000, read = true),
    )

    /** A phone bottom sheet's frame (Paparazzi can't capture the real sheet window). */
    @Composable
    fun SheetFrame(dark: Boolean, content: @Composable () -> Unit) {
        Box(Modifier.fillMaxSize().background(Color(0x52000000)), contentAlignment = Alignment.BottomCenter) {
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp))
                    .background(if (dark) Color(0xFF0A1229) else Color.White),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(
                    Modifier.padding(vertical = 16.dp).size(32.dp, 4.dp).clip(RoundedCornerShape(2.dp))
                        .background(if (dark) Color(0xFF1F367A) else Color(0xFFD5DBCF)),
                )
                content()
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}
