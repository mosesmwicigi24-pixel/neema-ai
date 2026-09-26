package ke.co.bethanyhouse.neema.app

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.testing.AppFrame
import org.junit.Rule
import org.junit.Test

/**
 * Round 5: the offline banner on a phone and a tablet, light and dark, and
 * the bar in both of its states. Record: ./gradlew :app:recordPaparazziDebug
 */
class ConnectivityScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private fun shell(dark: Boolean, width: WindowWidthSizeClass) {
        // Offline: the socket is down too, but the banner (not "Reconnecting…") speaks.
        val dash = ShellShots.live(paparazzi.context, dark, connected = false)
        dash.container.online.value = false
        dash.navigate(ViewId.Orders)
        paparazzi.snapshot { AppFrame(dark) { DashboardShell(dash, width) } }
    }

    @Test fun phoneOffline() = shell(false, WindowWidthSizeClass.Compact)
    @Test fun phoneOfflineDark() = shell(true, WindowWidthSizeClass.Compact)

    @Test fun tabletOffline() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_C)
        shell(false, WindowWidthSizeClass.Expanded)
    }

    @Test fun tabletOfflineDark() {
        paparazzi.unsafeUpdateConfig(deviceConfig = DeviceConfig.PIXEL_C)
        shell(true, WindowWidthSizeClass.Expanded)
    }

    private fun bars(dark: Boolean) = paparazzi.snapshot {
        AppFrame(dark) {
            Column {
                ConnectivityBar(offline = true)
                Spacer(Modifier.height(24.dp))
                ConnectivityBar(offline = false)
            }
        }
    }

    @Test fun bars() = bars(false)
    @Test fun barsDark() = bars(true)
}
