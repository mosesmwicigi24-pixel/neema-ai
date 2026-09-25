package ke.co.bethanyhouse.neema.orders

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import androidx.compose.runtime.CompositionLocalProvider
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import org.junit.rules.TestWatcher
import org.junit.runner.Description

/**
 * A ViewModel store pre-seeded with a screen's ViewModel, so a test can put
 * the screen in a state (a filter, an open sheet) before the first frame —
 * `viewModel { … }` inside the screen finds this instance under its default key.
 */
class SeededStore : ViewModelStoreOwner {
    override val viewModelStore = ViewModelStore()

    inline fun <reified T : ViewModel> seed(vm: T): T {
        val factory = object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <V : ViewModel> create(modelClass: Class<V>): V = vm as V
        }
        return ViewModelProvider(this, factory)[T::class.java]
    }

    @Composable
    fun Provide(content: @Composable () -> Unit) =
        CompositionLocalProvider(LocalViewModelStoreOwner provides this) { content() }
}

/**
 * A modal bottom sheet as the app shows it (scrim, rounded top, drag handle).
 * Paparazzi can't capture the sheet's own window, so detail content is
 * rendered in this frame instead.
 */
@Composable
fun SheetFrame(content: @Composable () -> Unit) {
    val c = Neema.colors
    Box(Modifier.fillMaxSize().background(Color(0x66000000))) {
        Column(
            Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(top = 48.dp)
                .clip(RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp)).background(c.bg2),
        ) {
            Box(
                Modifier.align(Alignment.CenterHorizontally).padding(vertical = 22.dp).size(width = 32.dp, height = 4.dp)
                    .clip(RoundedCornerShape(2.dp)).background(c.muted.copy(alpha = 0.4f)),
            )
            content()
        }
    }
}

/** Main = an unconfined test dispatcher: every viewModelScope launch runs inline, delays never fire. */
@OptIn(ExperimentalCoroutinesApi::class)
class MainDispatcherRule : TestWatcher() {
    override fun starting(description: Description) = Dispatchers.setMain(UnconfinedTestDispatcher())
    override fun finished(description: Description) = Dispatchers.resetMain()
}
