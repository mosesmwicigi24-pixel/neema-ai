package ke.co.bethanyhouse.neema.app

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.LocalSaveableStateRegistry
import androidx.compose.runtime.saveable.SaveableStateRegistry
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.SavedStateHandle
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.core.ui.components.SearchField
import ke.co.bethanyhouse.neema.core.ui.components.StatTile
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.FakeSocketFactory
import ke.co.bethanyhouse.neema.testing.Fixtures
import ke.co.bethanyhouse.neema.testing.MainDispatcherRule
import ke.co.bethanyhouse.neema.testing.TestDevice
import ke.co.bethanyhouse.neema.testing.snapshotOn
import ke.co.bethanyhouse.neema.testing.testContainer
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/**
 * Round 9: what a restored shell looks like. Each "restored" image is a
 * SECOND composition, fed only the state the first one saved (its
 * SaveableStateRegistry, and the DashboardViewModel's SavedStateHandle
 * after a simulated process death) — the first composition opened the
 * drawer / the account menu / the bell, the second is told nothing and
 * must come back with them open, on the same view.
 */
class ShellRestoreScreenshotTest {
    @get:Rule val main = MainDispatcherRule()

    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config, showSystemUi = false)

    /** A signed-in dashboard on a live socket, built from [handle] as Android would after a process death. */
    private fun restoredDash(handle: SavedStateHandle, dark: Boolean = false, notifications: List<String> = emptyList()): DashboardViewModel {
        val ws = FakeSocketFactory()
        val c = testContainer(paparazzi.context, FakeNeema.withFixtures(), appDispatcher = Dispatchers.Unconfined, wsFactory = ws)
        c.prefs.setDark(dark)
        c.notifications.start(c.foreground)
        c.socket.connect(Fixtures.ME_ID)
        ws.last.open()
        notifications.forEach { ws.last.frame(it) }
        return DashboardViewModel(c, handle)
    }

    private fun SavedStateHandle.afterProcessDeath() = SavedStateHandle(keys().associateWith { get<Any?>(it) })

    /**
     * Composes the shell twice through ONE composable lambda (so every
     * rememberSaveable key is the same both times): first with [open]
     * applied through the shell's initial-state knobs, then with none of
     * them and only the saved registry. Only the second is recorded.
     */
    private fun restore(device: TestDevice, open: Set<ShellOverlay>, dark: Boolean = false) {
        val handle = SavedStateHandle()
        val bell = if (ShellOverlay.Bell in open) ShellShots.frames else emptyList()
        val first = restoredDash(handle, dark, bell).apply { navigate(ViewId.Orders); navigate(ViewId.Deals) }
        var pass = 1
        var saved: Map<String, List<Any?>> = emptyMap()
        lateinit var dash: DashboardViewModel
        dash = first
        val scene: @Composable () -> Unit = {
            val registry = remember(pass) { SaveableStateRegistry(if (pass == 1) null else saved) { true } }
            CompositionLocalProvider(LocalSaveableStateRegistry provides registry) {
                AppFrame(dark) {
                    DashboardShell(
                        dash, device.widthClass,
                        initialDrawerOpen = pass == 1 && ShellOverlay.Drawer in open,
                        initialBellOpen = pass == 1 && ShellOverlay.Bell in open,
                        initialAccountMenu = pass == 1 && ShellOverlay.AccountMenu in open,
                    )
                }
            }
            SideEffect { if (pass == 1) saved = registry.performSave() }
        }
        paparazzi.unsafeUpdateConfig(deviceConfig = device.config)
        // Pass 1 is recorded too: the "before" to compare the restored image with.
        paparazzi.snapshot("${device.name}_before", scene)
        assertTrue("the first composition saved the shell's state", saved.isNotEmpty())
        pass = 2
        dash = restoredDash(handle.afterProcessDeath(), dark, bell)
        assertEquals("the view comes back before the first frame", ViewId.Deals, dash.view.value)
        paparazzi.snapshot("${device.name}_restored", scene)
    }

    @Test fun phoneDrawerAndAccountMenu() = restore(DeviceMatrix.PHONE, setOf(ShellOverlay.Drawer, ShellOverlay.AccountMenu))

    @Test fun phoneDrawerDark() = restore(DeviceMatrix.PHONE.dark(), setOf(ShellOverlay.Drawer), dark = true)

    @Test fun tabletBell() = restore(DeviceMatrix.TABLET_LANDSCAPE, setOf(ShellOverlay.Bell))

    /** Sidebar.tsx while signing out waits on a live call's hang-up: the account button spins. */
    @Test fun tabletSigningOut() {
        val d = DeviceMatrix.TABLET_LANDSCAPE
        val dash = restoredDash(SavedStateHandle())
        dash.navigate(ViewId.Orders)
        dash.endCall = { awaitCancellation() }
        dash.logout()
        assertTrue(dash.signingOut.value)
        paparazzi.snapshotOn(d) { AppFrame { DashboardShell(dash, d.widthClass) } }
    }

    /**
     * Core's StatTile three abreast on a 360dp phone at 130% text, as the
     * Profile tiles sit: "Permissions" steps its size down onto one line
     * instead of breaking as "Permission / s"; two-word labels still wrap.
     */
    @Test fun statTilesAtLargeText() = listOf(DeviceMatrix.SMALL_PHONE.fontScale(1.3f), DeviceMatrix.PHONE_HUGE_TEXT).forEach { d ->
        paparazzi.snapshotOn(d) {
            AppFrame {
                Row(Modifier.padding(16.dp).height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    StatTile("Active chats", "12", Modifier.weight(1f).fillMaxHeight())
                    StatTile("Status", "Online", Modifier.weight(1f).fillMaxHeight(), accent = Neema.colors.gold, hint = "Seen 5m ago")
                    StatTile("Permissions", "20/20", Modifier.weight(1f).fillMaxHeight())
                }
            }
        }
    }

    /** Core's SearchField: the web's 40dp box, inside a 48dp touch band, empty and typed, both themes. */
    @Test fun searchField() = listOf(DeviceMatrix.PHONE, DeviceMatrix.PHONE.dark()).forEach { d ->
        paparazzi.snapshotOn(d) {
            AppFrame(d.dark) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    SearchField("", {}, placeholder = "Search orders, customers, phone…")
                    SearchField("Mama 🌸 Njeri", {})
                    SearchField("", {}, placeholder = "Search catalog…", height = 36.dp)
                }
            }
        }
    }
}
