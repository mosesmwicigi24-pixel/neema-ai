package ke.co.bethanyhouse.neema.app

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ColorFilter
import androidx.compose.ui.unit.dp
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.auth.AuthException
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.TestDevice
import ke.co.bethanyhouse.neema.testing.snapshotOn
import org.junit.Rule
import org.junit.Test

/**
 * Round 7: the shell and the sign-in screens across the device / font /
 * theme matrix (see testing/DeviceMatrix.kt) — a 360dp phone, a phone at
 * 130% and 200% text, a 600dp foldable, a tablet upright and on its side,
 * and dark mode.
 */
class ShellMatrixScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config, showSystemUi = false)

    @get:Rule
    val main = ke.co.bethanyhouse.neema.testing.MainDispatcherRule()

    private fun shellOn(
        devices: List<TestDevice>, view: ViewId = ViewId.Orders, drawer: Boolean = false,
        toast: Toast? = null, menu: Boolean = false, bell: Boolean = false,
    ) = devices.forEach { d ->
        val dash = ShellShots.live(paparazzi.context, d.dark, notifications = if (bell) ShellShots.frames else emptyList())
        dash.navigate(view)
        // The alerts just pushed also raised a toast (it now waits to be seen);
        // this shot is about the bell.
        if (bell) dash.dismissToast()
        paparazzi.snapshotOn(d) {
            AppFrame(d.dark) {
                DashboardShell(
                    dash, d.widthClass, initialDrawerOpen = drawer, initialToast = toast,
                    initialAccountMenu = menu, initialBellOpen = bell,
                )
            }
        }
    }

    @Test fun shell() = shellOn(DeviceMatrix.core)

    @Test fun drawer() = shellOn(
        listOf(DeviceMatrix.SMALL_PHONE, DeviceMatrix.PHONE_HUGE_TEXT, DeviceMatrix.PHONE.dark().fontScale(1.3f)),
        drawer = true,
    )

    @Test fun toast() = shellOn(
        listOf(DeviceMatrix.SMALL_PHONE, DeviceMatrix.PHONE_HUGE_TEXT, DeviceMatrix.FOLDABLE),
        toast = Toast("Couldn't send — the 24-hour window has closed. Send a template instead.", ToastType.Error),
    )

    @Test fun accountMenu() = shellOn(
        listOf(DeviceMatrix.FOLDABLE, DeviceMatrix.TABLET_PORTRAIT.fontScale(2f)),
        menu = true,
    )

    @Test fun bellPopup() = shellOn(listOf(DeviceMatrix.TABLET_PORTRAIT.fontScale(1.3f), DeviceMatrix.FOLDABLE.dark()), bell = true)

    @Test
    fun bellSheet() = listOf(DeviceMatrix.SMALL_PHONE, DeviceMatrix.PHONE_HUGE_TEXT.dark()).forEach { d ->
        paparazzi.snapshotOn(d) {
            AppFrame(d.dark) {
                ShellShots.SheetFrame(d.dark) {
                    NotificationsPanel(ShellShots.sample(), {}, {}, {}, {}, listMaxHeight = 520.dp, now = ShellShots.NOW)
                }
            }
        }
    }

    @Test
    fun login() = paparazzi.run {
        (DeviceMatrix.core + DeviceMatrix.SMALL_PHONE.fontScale(2f)).forEach { d ->
            snapshotOn(d) {
                AppFrame(d.dark) {
                    LoginContent(
                        initialEmail = "moses@bethanyhouse.co.ke", login = { _, _ -> }, onSignedIn = {},
                        initialPassword = "secret", initialError = "Invalid email or password. Please try again.", year = 2026,
                    )
                }
            }
        }
    }

    @Test
    fun sessionExpired() = listOf(DeviceMatrix.SMALL_PHONE.fontScale(2f), DeviceMatrix.TABLET_LANDSCAPE.dark().fontScale(1.3f)).forEach { d ->
        val dash = ShellShots.live(paparazzi.context, d.dark).apply { navigate(ViewId.Orders) }
        paparazzi.snapshotOn(d) {
            AppFrame(d.dark) {
                DashboardShell(dash, d.widthClass)
                SessionExpiredCard(
                    "moses.mwicigi.long.address@bethanyhouse.co.ke", login = { _, _ -> throw AuthException("x") },
                    onSuccess = {}, onSignOut = {}, initialPassword = "hunter2",
                    initialError = "Incorrect password. Please try again.", autoFocus = false,
                )
            }
        }
    }

    @Test
    fun offlineBanner() = listOf(DeviceMatrix.SMALL_PHONE.fontScale(2f), DeviceMatrix.FOLDABLE.dark()).forEach { d ->
        val dash = ShellShots.live(paparazzi.context, d.dark, connected = false)
        dash.container.online.value = false
        dash.navigate(ViewId.Orders)
        paparazzi.snapshotOn(d) { AppFrame(d.dark) { DashboardShell(dash, d.widthClass) } }
    }

    /**
     * The launcher icon (moss disc, white bubble inside the 66dp safe zone,
     * shown under circle and squircle masks), the Android 13 themed icon (the
     * monochrome layer, dots cut out) and the splash (disc on the login's night).
     */
    @Test
    fun appIcon() = paparazzi.snapshot {
        val fg = androidx.compose.ui.res.painterResource(ke.co.bethanyhouse.neema.R.drawable.ic_launcher_foreground)
        val mono = androidx.compose.ui.res.painterResource(ke.co.bethanyhouse.neema.R.drawable.ic_launcher_monochrome)
        AppFrame {
            Column(
                Modifier.fillMaxSize().background(Palette.Prussian950).padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(24.dp),
            ) {
                Row(horizontalArrangement = Arrangement.spacedBy(24.dp)) {
                    listOf(CircleShape, RoundedCornerShape(30)).forEach { shape ->
                        Image(fg, null, Modifier.size(96.dp).clip(shape).background(Palette.Moss600))
                    }
                    // Themed icon: the system tints the monochrome layer on a pale disc.
                    Image(
                        mono, null,
                        Modifier.size(96.dp).clip(CircleShape).background(Palette.Moss100),
                        colorFilter = ColorFilter.tint(Palette.Moss800),
                    )
                }
                // Splash: a 240dp icon canvas whose moss background is masked to a 160dp disc.
                Box(Modifier.fillMaxWidth().height(320.dp).background(Palette.Prussian950), contentAlignment = Alignment.Center) {
                    Box(Modifier.size(160.dp).clip(CircleShape).background(Palette.Moss600), contentAlignment = Alignment.Center) {
                        Image(fg, null, Modifier.requiredSize(240.dp))
                    }
                }
            }
        }
    }
}
