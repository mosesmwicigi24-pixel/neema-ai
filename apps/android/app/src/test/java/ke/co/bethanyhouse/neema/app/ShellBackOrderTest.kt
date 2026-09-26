package ke.co.bethanyhouse.neema.app

import androidx.activity.OnBackPressedDispatcher
import androidx.activity.OnBackPressedDispatcherOwner
import androidx.activity.compose.LocalOnBackPressedDispatcherOwner
import androidx.compose.foundation.layout.Box
import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleRegistry
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel
import ke.co.bethanyhouse.neema.testing.AppFrame
import ke.co.bethanyhouse.neema.testing.DeviceMatrix
import ke.co.bethanyhouse.neema.testing.MainDispatcherRule
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/**
 * Round 9: system back through the REAL shell and the REAL inbox, with a
 * real OnBackPressedDispatcher. The inbox registers its own back handler
 * (clear the search); with the phone drawer open, the drawer must take the
 * press and the search stay; with it shut, the inbox takes it.
 *
 * The press is dispatched once the frame has been laid out — by then every
 * handler, the views' (composed during measure) included, is registered.
 */
class ShellBackOrderTest {
    @get:Rule val main = MainDispatcherRule()

    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceMatrix.PHONE.config, showSystemUi = false)

    private class BackOwner : OnBackPressedDispatcherOwner {
        override val onBackPressedDispatcher = OnBackPressedDispatcher()
        override val lifecycle: Lifecycle = LifecycleRegistry.createUnsafe(this).apply { currentState = Lifecycle.State.RESUMED }
    }

    /** Back pressed once over the inbox with "cassock" typed in its search; returns the search after. */
    private fun backWith(drawerOpen: Boolean, shot: String): String {
        val dash = ShellShots.live(paparazzi.context)
        val store = ViewModelStore()
        val owner = object : ViewModelStoreOwner { override val viewModelStore = store }
        val inbox = ViewModelProvider(owner, viewModelFactory { initializer { ConversationsViewModel(dash) } })[ConversationsViewModel::class.java]
        inbox.setSearch("cassock")
        val back = BackOwner()
        var pressed = false
        paparazzi.snapshot(shot) {
            AppFrame {
                CompositionLocalProvider(
                    LocalViewModelStoreOwner provides owner,
                    LocalOnBackPressedDispatcherOwner provides back,
                ) {
                    Box(Modifier.onGloballyPositioned { if (!pressed) { pressed = true; back.onBackPressedDispatcher.onBackPressed() } }) {
                        DashboardShell(dash, WindowWidthSizeClass.Compact, initialDrawerOpen = drawerOpen)
                    }
                }
            }
        }
        assertEquals("the press was dispatched", true, pressed)
        return inbox.list.value.search
    }

    @Test fun theOpenDrawerTakesBackBeforeTheInboxSearch() {
        assertEquals("cassock", backWith(drawerOpen = true, shot = "drawerOpen"))
    }

    @Test fun withTheDrawerShutTheInboxClearsItsSearch() {
        assertEquals("", backWith(drawerOpen = false, shot = "drawerShut"))
    }
}
