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
    /** PIXEL_C upright: 900dp wide, two card columns. */
    val TABLET_PORTRAIT = DeviceConfig.PIXEL_C.copy(
        screenWidth = DeviceConfig.PIXEL_C.screenHeight, screenHeight = DeviceConfig.PIXEL_C.screenWidth,
        orientation = com.android.resources.ScreenOrientation.PORTRAIT,
    )
    fun tallTablet(heightPx: Int) = DeviceConfig.PIXEL_C.copy(screenHeight = heightPx)

    // ── Round 7's device / font matrix ───────────────────────────────────────
    /** The smallest phone we support: 360 x 640dp. */
    val SMALL = DeviceConfig.NEXUS_5
    /** 360dp at the largest accessibility font (2.0). */
    val SMALL_XL_FONT = DeviceConfig.NEXUS_5.copy(fontScale = 2f)
    /** A compact phone (393dp) at font scale 1.3. */
    val PIXEL5_LARGE_FONT = DeviceConfig.PIXEL_5.copy(fontScale = 1.3f)
    /** A regular phone at font scale 2.0. */
    val PHONE_XL_FONT = DeviceConfig.PIXEL_6.copy(fontScale = 2f)
    /** A foldable's inner screen, about 600dp wide. */
    val FOLD = DeviceConfig.PIXEL_6.copy(screenWidth = 1575, screenHeight = 2000)
    /** Tablet landscape at font scale 1.3. */
    val TABLET_LARGE_FONT = DeviceConfig.PIXEL_C.copy(fontScale = 1.3f)
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
