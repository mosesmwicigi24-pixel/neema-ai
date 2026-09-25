package ke.co.bethanyhouse.neema.app

import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.auth.AuthException
import ke.co.bethanyhouse.neema.testing.AppFrame
import org.junit.Rule
import org.junit.Test

/**
 * The shell on a tablet (the web's desktop layout): the docked navy sidebar
 * expanded and collapsed, the account menu, the bell popup, a toast, the
 * session-expired prompt and the two-panel login.
 */
class ShellTabletScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_C, showSystemUi = false)

    private fun shell(
        dark: Boolean = false, collapsed: Boolean = false, bell: Boolean = false, menu: Boolean = false,
        toast: Toast? = null, connected: Boolean = true, view: ViewId? = null,
    ) {
        val dash = ShellShots.live(
            paparazzi.context, dark, connected = connected,
            notifications = if (bell) ShellShots.frames else emptyList(),
        )
        // Orders paints synchronously from the fake; the inbox list settles off the main thread.
        dash.navigate(view ?: ViewId.Orders)
        paparazzi.snapshot {
            AppFrame(dark) {
                DashboardShell(
                    dash, WindowWidthSizeClass.Expanded, initialBellOpen = bell, initialToast = toast,
                    initialAccountMenu = menu, initialCollapsed = collapsed,
                )
            }
        }
    }

    @Test fun tabletShell() = shell()
    @Test fun tabletShellDark() = shell(dark = true)
    @Test fun tabletCollapsed() = shell(collapsed = true, view = ViewId.Catalog)
    @Test fun tabletCollapsedDarkOffline() = shell(collapsed = true, dark = true, connected = false)
    @Test fun tabletAccountMenu() = shell(menu = true)
    @Test fun tabletAccountMenuDark() = shell(menu = true, dark = true)
    @Test fun tabletBell() = shell(bell = true)
    @Test fun tabletBellCollapsedDark() = shell(bell = true, collapsed = true, dark = true)
    @Test fun tabletToast() = shell(toast = Toast("Settings saved", ToastType.Success))

    @Test
    fun tabletSessionExpired() {
        val dash = ShellShots.live(paparazzi.context).apply { navigate(ViewId.Orders) }
        paparazzi.snapshot {
            AppFrame {
                DashboardShell(dash, WindowWidthSizeClass.Expanded)
                SessionExpiredCard(
                    "moses@bethanyhouse.co.ke", login = { _, _ -> throw AuthException("x") }, onSuccess = {}, onSignOut = {},
                    autoFocus = false,
                )
            }
        }
    }

    @Test
    fun tabletLogin() = paparazzi.snapshot {
        AppFrame { LoginContent(initialEmail = "", login = { _, _ -> }, onSignedIn = {}, year = 2026) }
    }

    @Test
    fun tabletLoginError() = paparazzi.snapshot {
        AppFrame {
            LoginContent(
                initialEmail = "moses@bethanyhouse.co.ke", login = { _, _ -> }, onSignedIn = {},
                initialPassword = "nope", initialError = "Invalid email or password. Please try again.", year = 2026,
            )
        }
    }
}
