package ke.co.bethanyhouse.neema.app

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaTheme
import org.junit.Rule
import org.junit.Test

/**
 * Renders the app shell on the JVM (no device):
 *   ./gradlew :app:recordPaparazziDebug   → app/src/test/snapshots/images/
 */
class ShellScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_6, showSystemUi = false)

    private val items = listOf(
        NavItem(ViewId.Conversations, iconFor(ViewId.Conversations), 3),
        NavItem(ViewId.Calls, iconFor(ViewId.Calls)),
        NavItem(ViewId.Orders, iconFor(ViewId.Orders), 12),
        NavItem(ViewId.Reports, iconFor(ViewId.Reports)),
        NavItem(ViewId.Deals, iconFor(ViewId.Deals)),
        NavItem(ViewId.Leads, iconFor(ViewId.Leads)),
        NavItem(ViewId.Overview, iconFor(ViewId.Overview)),
        NavItem(ViewId.Catalog, iconFor(ViewId.Catalog)),
        NavItem(ViewId.Agents, iconFor(ViewId.Agents)),
        NavItem(ViewId.Settings, iconFor(ViewId.Settings)),
        NavItem(ViewId.Profile, iconFor(ViewId.Profile)),
    )

    @Test
    fun sidebarDrawer() = paparazzi.snapshot {
        NeemaTheme(dark = false) {
            Row(Modifier.fillMaxSize().background(Color(0x66000000))) {
                NeemaSidebar(
                    items = items, view = ViewId.Conversations, onSelect = {},
                    collapsed = false, onToggleCollapse = null,
                    userName = "Moses Mwicigi", userEmail = "moses@bethanyhouse.co.ke", userRole = "admin",
                    avatarUrl = null, dark = false, onToggleDark = {}, canSettings = true,
                    bellCount = 2, onBell = {}, onSignOut = {},
                )
            }
        }
    }

    @Test
    fun phoneChrome() = paparazzi.snapshot {
        NeemaTheme(dark = false) {
            Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                MobileHeader("Inbox", connected = true, dark = false, bell = 2, onMenu = {}, onBell = {}, onTheme = {})
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Text("(screen content)", color = Color(0xFF8A9E80))
                }
                MobileBottomNav(items.take(4), ViewId.Conversations, moreActive = false, onSelect = {}, onMore = {})
            }
        }
    }

    @Test
    fun phoneChromeDark() = paparazzi.snapshot {
        NeemaTheme(dark = true) {
            Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                MobileHeader("Orders", connected = false, dark = true, bell = 0, onMenu = {}, onBell = {}, onTheme = {})
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    Text("(screen content)", color = Color(0xFF8A9E80))
                }
                MobileBottomNav(items.take(4), ViewId.Orders, moreActive = false, onSelect = {}, onMore = {})
            }
        }
    }

    @Test
    fun tabletSidebarCollapsed() = paparazzi.snapshot {
        NeemaTheme(dark = false) {
            Row(Modifier.fillMaxSize()) {
                NeemaSidebar(
                    items = items, view = ViewId.Orders, onSelect = {},
                    collapsed = true, onToggleCollapse = {},
                    userName = "Moses Mwicigi", userEmail = "moses@bethanyhouse.co.ke", userRole = "admin",
                    avatarUrl = null, dark = false, onToggleDark = {}, canSettings = true,
                    bellCount = 0, onBell = {}, onSignOut = {},
                )
            }
        }
    }

    @Test
    fun login() = paparazzi.snapshot {
        NeemaTheme(dark = false) { LoginContent(initialEmail = "", login = { _, _ -> }, onSignedIn = {}) }
    }
}
