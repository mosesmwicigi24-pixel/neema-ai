package ke.co.bethanyhouse.neema.tablet

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardShell
import ke.co.bethanyhouse.neema.app.ShellShotsAccess
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.TestDevice
import ke.co.bethanyhouse.neema.testing.snapshotOn
import org.junit.Rule
import org.junit.Test

/**
 * The Samsung Galaxy Tab S9 Ultra: every major view on every window the
 * tablet gives the app — full screen both ways (two zoom levels), split
 * screen ½ / ⅓ / ⅔, upright split and the pop-up window.
 */
class TabS9UltraScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.TAB_S9U.config, showSystemUi = false, maxPercentDifference = 0.1)

    @get:Rule
    val main = ke.co.bethanyhouse.neema.testing.MainDispatcherRule()

    private fun on(view: ViewId, devices: List<TestDevice> = DeviceMatrix.tabS9Ultra) = devices.forEach { d ->
        val dash = ShellShotsAccess.live(paparazzi.context, d.dark)
        dash.navigate(view)
        paparazzi.snapshotOn(d) { AppFrame(d.dark) { DashboardShell(dash, d.widthClass) } }
    }

    @Test fun inbox() = on(ViewId.Conversations)
    @Test fun overview() = on(ViewId.Overview)
    @Test fun orders() = on(ViewId.Orders)
    @Test fun calls() = on(ViewId.Calls)
    @Test fun catalog() = on(ViewId.Catalog)
    @Test fun deals() = on(ViewId.Deals)
    @Test fun leads() = on(ViewId.Leads)
    @Test fun reports() = on(ViewId.Reports)
    @Test fun team() = on(ViewId.Agents)
    @Test fun settings() = on(ViewId.Settings)
}
