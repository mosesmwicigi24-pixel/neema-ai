package ke.co.bethanyhouse.neema.app

import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.Persona
import org.junit.Rule
import org.junit.Test

/**
 * The phone shell for contrasting personas (round 6): the drawer lists
 * exactly page.tsx's nav for each, and the bottom bar's four slots fill from
 * that same list — a Sales agent's bar is Inbox, Calls, Orders, Profile.
 */
class PersonaShellScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private fun shell(p: Persona, drawer: Boolean, view: ViewId = ViewId.Orders) {
        val dash = ShellShots.live(paparazzi.context, persona = p)
        dash.navigate(view)
        paparazzi.snapshot {
            AppFrame { DashboardShell(dash, WindowWidthSizeClass.Compact, initialDrawerOpen = drawer) }
        }
    }

    @Test fun drawer_superuser() = shell(Persona.Superuser, drawer = true)
    @Test fun drawer_readonly() = shell(Persona.Readonly, drawer = true)
    @Test fun drawer_salesRole() = shell(Persona.Sales, drawer = true)
    @Test fun bottomNav_salesRole() = shell(Persona.Sales, drawer = false)
}
