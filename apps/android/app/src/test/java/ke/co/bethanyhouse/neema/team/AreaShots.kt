package ke.co.bethanyhouse.neema.team

import androidx.compose.runtime.Composable
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.dashboard
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.After
import org.junit.Before
import org.junit.Rule

/** Devices the area renders on. Tall variants show a whole scrolling page in one image. */
object Devices {
    val PHONE = DeviceConfig.PIXEL_6
    fun tallPhone(heightPx: Int) = DeviceConfig.PIXEL_6.copy(screenHeight = heightPx)
    val TABLET = DeviceConfig.PIXEL_C
    fun tallTablet(heightPx: Int) = DeviceConfig.PIXEL_C.copy(screenHeight = heightPx)
}

/** Base for Team / Profile / Settings screenshots: real screens on the fake backend. */
@OptIn(ExperimentalCoroutinesApi::class)
abstract class AreaShots {
    @get:Rule val paparazzi = Paparazzi(deviceConfig = Devices.PHONE, showSystemUi = false)

    @Before fun eager() { Dispatchers.setMain(UnconfinedTestDispatcher()) }
    @After fun reset() { Dispatchers.resetMain() }

    /** A signed-in dashboard on [fake] with the team list loaded. */
    fun dash(
        fake: FakeNeema = FakeNeema.withFixtures(),
        role: String = "admin",
        superuser: Boolean = true,
    ): DashboardViewModel = dashboard(paparazzi.context, fake, role, superuser).also {
        it.refetchAgents()
        it.refetchCatalog()
    }

    fun shot(device: DeviceConfig = Devices.PHONE, dark: Boolean = false, content: @Composable () -> Unit) {
        if (device != Devices.PHONE) paparazzi.unsafeUpdateConfig(deviceConfig = device)
        paparazzi.snapshot { AppFrame(dark = dark) { content() } }
    }
}
