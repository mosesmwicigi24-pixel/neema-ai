package ke.co.bethanyhouse.neema.app

import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.Persona
import org.junit.Rule
import org.junit.Test

/**
 * The docked sidebar (the web's desktopNavItems) for contrasting personas:
 * a superuser sees all eleven views; legacy read-only loses Reports, Team and
 * Settings; a custom Sales role keeps only Inbox, Calls, Orders and Profile —
 * while the account menu still offers Settings to everyone, as the web's does.
 */
class PersonaShellTabletScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_C, showSystemUi = false)

    private fun shell(p: Persona, menu: Boolean = false) {
        val dash = ShellShots.live(paparazzi.context, persona = p)
        dash.navigate(ViewId.Orders)
        paparazzi.snapshot {
            AppFrame { DashboardShell(dash, WindowWidthSizeClass.Expanded, initialAccountMenu = menu) }
        }
    }

    @Test fun sidebar_superuser() = shell(Persona.Superuser)
    @Test fun sidebar_readonly() = shell(Persona.Readonly)
    @Test fun sidebar_salesRole() = shell(Persona.Sales)
    @Test fun sidebar_salesRoleAccountMenu() = shell(Persona.Sales, menu = true)
}
