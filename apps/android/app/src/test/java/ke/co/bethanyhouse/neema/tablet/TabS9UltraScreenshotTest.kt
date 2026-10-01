package ke.co.bethanyhouse.neema.tablet

import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.app.DashboardShell
import ke.co.bethanyhouse.neema.app.ShellShotsAccess
import ke.co.bethanyhouse.neema.app.ViewId
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.TestDevice
import ke.co.bethanyhouse.neema.testing.snapshotOn
import androidx.lifecycle.viewmodel.initializer
import org.junit.Rule
import org.junit.Test

/**
 * The Samsung Galaxy Tab S9 Ultra: every major view on every window the
 * tablet gives the app — full screen both ways (two zoom levels), split
 * screen ½ / ⅓ / ⅔, upright split and the pop-up window.
 */
class TabS9UltraScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.TAB_S9U.config, showSystemUi = false, maxPercentDifference = 0.1)

    @get:Rule
    val main = ke.co.bethanyhouse.neema.testing.MainDispatcherRule()

    private class Owner : androidx.lifecycle.ViewModelStoreOwner { override val viewModelStore = androidx.lifecycle.ViewModelStore() }

    /** The instance the screen's `viewModel { }` will find in this store. */
    private inline fun <reified T : androidx.lifecycle.ViewModel> Owner.vm(crossinline make: () -> T): T =
        androidx.lifecycle.ViewModelProvider.create(this, androidx.lifecycle.viewmodel.viewModelFactory { initializer { make() } })[T::class]

    private fun on(view: ViewId, devices: List<TestDevice> = DeviceMatrix.tabS9Ultra) = devices.forEach { d ->
        // These views print clock times ("11:20"): start each at the pinned moment, not
        // however far into the run this test happens to be, so the goldens hold still.
        ke.co.bethanyhouse.neema.core.util.AppClock.pinTo(java.time.Instant.parse(PIN))
        val dash = ShellShotsAccess.live(paparazzi.context, d.dark)
        dash.navigate(view)
        // The view's ViewModel is built (and, test I/O being synchronous, loaded) before the
        // first frame — the same instance the screen's viewModel { } finds — so the shot never
        // races the list arriving (the inbox's auto-open of the first chat included).
        val owner = Owner()
        when (view) {
            ViewId.Conversations -> {
                val inbox = owner.vm {
                    ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel(dash)
                }
                val first = checkNotNull(inbox.rows.value.firstOrNull()) { "inbox rows not ready before the first frame" }
                inbox.select(first.rep.id, openThread = false)
            }
            ViewId.Calls -> owner.vm { ke.co.bethanyhouse.neema.feature.calls.CallsViewModel(dash) }
            else -> Unit
        }
        paparazzi.snapshotOn(d) {
            AppFrame(d.dark) {
                // Inside AppFrame, which provides a fresh store of its own.
                androidx.compose.runtime.CompositionLocalProvider(androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner provides owner) {
                    DashboardShell(dash, d.widthClass)
                }
            }
        }
    }

    private companion object { const val PIN = "2026-09-25T09:00:00Z" }

    @Test fun inbox() = on(ViewId.Conversations)
    @Test fun overview() = on(ViewId.Overview)
    @Test fun orders() = on(ViewId.Orders)
    @Test fun calls() = on(ViewId.Calls)
    @Test fun catalog() = on(ViewId.Catalog)
    @Test fun deals() = on(ViewId.Deals)
    @Test fun leads() = on(ViewId.Leads)
    @Test fun reports() = on(ViewId.Reports)
    @Test fun team() = on(ViewId.Agents)
    @Test fun settings() = on(ViewId.Settings)
}
