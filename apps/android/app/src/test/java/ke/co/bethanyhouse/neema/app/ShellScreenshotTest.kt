package ke.co.bethanyhouse.neema.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.auth.AuthException
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures
import org.junit.Rule
import org.junit.Test

/**
 * The app shell on a phone (app/dashboard/page.tsx on mobile, plus the
 * drawer that reaches every view): header, bottom nav, drawer, bell sheet,
 * toasts, the session-expired prompt, the login page and avatars — light
 * and dark. Record: ./gradlew :app:recordPaparazziDebug
 */
class ShellScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private fun shell(
        dark: Boolean = false, drawer: Boolean = false, toast: Toast? = null, connected: Boolean = true,
        fake: FakeNeema = FakeNeema.withFixtures(), role: String = "admin", superuser: Boolean = true,
        view: ViewId? = null,
    ) {
        val dash = ShellShots.live(paparazzi.context, dark, fake, role, superuser, connected)
        // Orders paints synchronously from the fake; the inbox list settles off the main thread.
        dash.navigate(view ?: ViewId.Orders)
        paparazzi.snapshot {
            AppFrame(dark) {
                DashboardShell(dash, WindowWidthSizeClass.Compact, initialDrawerOpen = drawer, initialToast = toast)
            }
        }
    }

    @Test fun phoneShell() = shell()
    @Test fun phoneShellDark() = shell(dark = true)
    @Test fun phoneOffline() = shell(connected = false, view = ViewId.Orders)
    @Test fun phoneDrawer() = shell(drawer = true)
    @Test fun phoneDrawerDark() = shell(dark = true, drawer = true, view = ViewId.Catalog)

    /** Brian, a legacy read-only agent: no Reports, Team or Settings. */
    @Test
    fun phoneDrawerReadonly() {
        val fake = FakeNeema.withFixtures()
        val brian = """{"id":"${Fixtures.AGENT3_ID}","name":"Brian Otieno","email":"brian@bethanyhouse.co.ke","role":"readonly","is_available":false,"is_superuser":false}"""
        fake.on("GET", "/admin/me", body = brian)
        fake.on("GET", "/admin/agents", body = "[$brian]")
        shell(drawer = true, fake = fake, role = "readonly", superuser = false)
    }

    @Test fun phoneToastSuccess() = shell(toast = Toast("Order marked as delivered", ToastType.Success))
    @Test fun phoneToastError() = shell(toast = Toast("Couldn't send — the 24-hour window has closed", ToastType.Error), dark = true)
    @Test fun phoneToastWarning() = shell(toast = Toast("Hub push failed: variant out of stock", ToastType.Warning))

    // ── Bell (the sheet's content; Paparazzi can't capture the sheet window) ──

    private fun bell(dark: Boolean, items: List<ke.co.bethanyhouse.neema.core.notify.AppNotification>) = paparazzi.snapshot {
        AppFrame(dark) {
            ShellShots.SheetFrame(dark) {
                NotificationsPanel(items, {}, {}, {}, {}, listMaxHeight = 520.dp, now = ShellShots.NOW)
            }
        }
    }

    @Test fun bellSheet() = bell(false, ShellShots.sample())
    @Test fun bellSheetDark() = bell(true, ShellShots.sample())
    @Test fun bellSheetEmpty() = bell(false, emptyList())
    @Test fun bellSheetAllRead() = bell(true, ShellShots.sample().map { it.copy(read = true) }.take(2))

    // ── Session expired ─────────────────────────────────────────────────────

    private fun expired(dark: Boolean = false, error: String = "", loading: Boolean = false, password: String = "") {
        val dash = ShellShots.live(paparazzi.context, dark).apply { navigate(ViewId.Orders) }
        paparazzi.snapshot {
            AppFrame(dark) {
                DashboardShell(dash, WindowWidthSizeClass.Compact)
                SessionExpiredCard(
                    "moses@bethanyhouse.co.ke", login = { _, _ -> throw AuthException("x") }, onSuccess = {}, onSignOut = {},
                    initialPassword = password, initialError = error, initialLoading = loading, autoFocus = false,
                )
            }
        }
    }

    @Test fun sessionExpired() = expired()
    @Test fun sessionExpiredDark() = expired(dark = true, password = "hunter22")
    @Test fun sessionExpiredWrongPassword() = expired(error = "Incorrect password. Please try again.", password = "hunter2")
    @Test fun sessionExpiredSigningIn() = expired(loading = true, password = "hunter22")

    // ── Login ───────────────────────────────────────────────────────────────

    @Test
    fun login() = paparazzi.snapshot {
        AppFrame { LoginContent(initialEmail = "", login = { _, _ -> }, onSignedIn = {}) }
    }

    @Test
    fun loginError() = paparazzi.snapshot {
        AppFrame {
            LoginContent(
                initialEmail = "moses@bethanyhouse.co.ke", login = { _, _ -> }, onSignedIn = {},
                initialPassword = "wrong-one", initialError = "Invalid email or password. Please try again.",
            )
        }
    }

    @Test
    fun loginSigningIn() = paparazzi.snapshot {
        AppFrame {
            LoginContent(initialEmail = "moses@bethanyhouse.co.ke", login = { _, _ -> }, onSignedIn = {}, initialPassword = "secret", initialLoading = true)
        }
    }

    // ── Avatars ─────────────────────────────────────────────────────────────

    private fun avatars(dark: Boolean) = paparazzi.snapshot {
        AppFrame(dark) {
            Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).padding(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                listOf(
                    "Fr. Peter Kamau" to null,
                    Fmt.displayName(null, "254712345678") to "unnamed WhatsApp contact",
                    Fmt.displayName(null, "25898765432101234") to "unnamed Messenger contact",
                    "Grace" to null,
                    "" to "no name at all",
                ).forEach { (name, note) ->
                    Row(verticalAlignment = androidx.compose.ui.Alignment.CenterVertically) {
                        Avatar(name, size = 44.dp)
                        Spacer(Modifier.width(10.dp))
                        Avatar(name, size = 32.dp)
                        Spacer(Modifier.width(10.dp))
                        Avatar(name, size = 24.dp)
                        Spacer(Modifier.width(14.dp))
                        Column {
                            Text(name.ifEmpty { "—" }, fontSize = 14.sp, color = MaterialTheme.colorScheme.onBackground)
                            if (note != null) Text(note, fontSize = 12.sp, color = Color(0xFF8A9E80))
                        }
                    }
                }
            }
        }
    }

    @Test fun avatars() = avatars(false)
    @Test fun avatarsDark() = avatars(true)
}
