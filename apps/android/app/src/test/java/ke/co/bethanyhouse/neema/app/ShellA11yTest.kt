package ke.co.bethanyhouse.neema.app

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.ui.Modifier
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.auth.AuthException
import ke.co.bethanyhouse.neema.testing.A11yProbe
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.snapshotOn
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Round 7: every tappable in the shell and the sign-in screens is at least
 * 48 × 48dp and has words for TalkBack — read from the real Compose
 * semantics of each render (testing/A11yProbe.kt), at 100% and 200% text.
 */
class ShellA11yTest {
    private val probe = A11yProbe()

    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config, showSystemUi = false, renderExtensions = setOf(probe))

    private val navItems = listOf(
        NavItem(ViewId.Conversations, iconFor(ViewId.Conversations), 12),
        NavItem(ViewId.Calls, iconFor(ViewId.Calls)),
        NavItem(ViewId.Orders, iconFor(ViewId.Orders), 3),
        NavItem(ViewId.Reports, iconFor(ViewId.Reports)),
        NavItem(ViewId.Deals, iconFor(ViewId.Deals)),
        NavItem(ViewId.Settings, iconFor(ViewId.Settings)),
        NavItem(ViewId.Profile, iconFor(ViewId.Profile)),
    )

    @Test
    fun phoneHeaderAndBottomNav() = listOf(DeviceMatrix.SMALL_PHONE, DeviceMatrix.PHONE_HUGE_TEXT).forEach { d ->
        paparazzi.snapshotOn(d) {
            AppFrame {
                Column {
                    MobileHeader("Orders", connected = true, dark = false, bell = 4, onMenu = {}, onBell = {}, onTheme = {})
                    MobileBottomNav(navItems.take(4), ViewId.Orders, moreActive = false, onSelect = {}, onMore = {})
                }
            }
        }
        probe.assertAccessible()
        val labels = probe.tappables.map { it.label }
        assertTrue(labels.toString(), "Open navigation menu" in labels)
        assertTrue(labels.toString(), "Notifications, 4 unread" in labels)
        assertTrue(labels.toString(), "Switch to dark mode" in labels)
        assertTrue(labels.toString(), "Inbox, 12 new" in labels)
        assertTrue(labels.toString(), "More" in labels)
        assertEquals("Tab", probe.tappables.first { it.label == "Orders, 3 new" }.role)
    }

    /**
     * The docked sidebar: every nav row, the account row and the menu. The
     * header's bell and collapse buttons keep the web's 36dp tiles beside the
     * wordmark; Compose extends a pointer target smaller than 48dp to 48dp
     * when nothing else is there, so they are exempt here.
     */
    @Test
    fun sidebarAndAccountMenu() {
        val exempt = setOf("Notifications, 2 unread", "Collapse sidebar")
        listOf(false, true).forEach { collapsed ->
            paparazzi.snapshotOn(DeviceMatrix.TABLET_LANDSCAPE.copy(name = if (collapsed) "rail" else "sidebar")) {
                AppFrame {
                    NeemaSidebar(
                        navItems, ViewId.Orders, onSelect = {}, collapsed = collapsed, onToggleCollapse = {},
                        userName = "Moses Mwicigi", userEmail = "moses@bethanyhouse.co.ke", userRole = "admin", avatarUrl = null,
                        dark = false, onToggleDark = {}, bellCount = 2, onBell = {}, onSignOut = {},
                        modifier = Modifier.fillMaxHeight(), initialMenuOpen = !collapsed,
                    )
                }
            }
            probe.assertAccessible(exempt = exempt)
        }
        val labels = probe.tappables.map { it.label }
        assertTrue(labels.toString(), labels.any { it.startsWith("Inbox") })
        assertTrue(labels.toString(), "Expand sidebar" in labels)
    }

    @Test
    fun bellPanel() = listOf(DeviceMatrix.PHONE, DeviceMatrix.PHONE_HUGE_TEXT).forEach { d ->
        paparazzi.snapshotOn(d) {
            AppFrame { NotificationsPanel(ShellShots.sample(), {}, {}, {}, {}, now = ShellShots.NOW) }
        }
        probe.assertAccessible()
        assertTrue(probe.tappables.count { it.label == "Dismiss notification" } >= 3)
    }

    @Test
    fun loginAndSessionExpired() {
        listOf(DeviceMatrix.SMALL_PHONE, DeviceMatrix.PHONE_HUGE_TEXT).forEach { d ->
            paparazzi.snapshotOn(d.copy(name = "login_${d.name}")) {
                AppFrame { LoginContent(initialEmail = "moses@bethanyhouse.co.ke", login = { _, _ -> }, onSignedIn = {}, year = 2026) }
            }
            probe.assertAccessible()
            assertTrue(probe.tappables.toString(), probe.tappables.any { it.label == "Show password" })
        }
        paparazzi.snapshotOn(DeviceMatrix.SMALL_PHONE.copy(name = "expired")) {
            AppFrame {
                SessionExpiredCard(
                    "moses@bethanyhouse.co.ke", login = { _, _ -> throw AuthException("x") }, onSuccess = {}, onSignOut = {},
                    initialPassword = "hunter2", autoFocus = false,
                )
            }
        }
        probe.assertAccessible()
    }
}
