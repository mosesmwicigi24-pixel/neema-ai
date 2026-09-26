package ke.co.bethanyhouse.neema.team

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.saveable.LocalSaveableStateRegistry
import androidx.compose.runtime.saveable.SaveableStateRegistry
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import app.cash.paparazzi.Paparazzi
import ke.co.bethanyhouse.neema.testing.AppFrame

/** A ViewModel store, as the signed-in agent's scope holds one. */
class Store : ViewModelStoreOwner {
    override val viewModelStore = ViewModelStore()

    /** Put [vm] where the screen's `viewModel { }` will find it. */
    inline fun <reified T : ViewModel> put(vm: T): T =
        ViewModelProvider(this, object : ViewModelProvider.Factory {
            @Suppress("UNCHECKED_CAST")
            override fun <V : ViewModel> create(modelClass: Class<V>): V = vm as V
        })[T::class.java]
}

/**
 * Renders [content] twice and snapshots both: "before" as the agent left it,
 * then "restored" — a new composition given only what the first one wrote to
 * its saved-instance state (a [SaveableStateRegistry] round trip, exactly
 * what the activity keeps when Android recreates it).
 *
 * With a new [after] store the screen's ViewModels are new too: Android
 * killed the process in the background. With the same store as [before],
 * only the activity was recreated (a rotation, a theme or font change).
 *
 * The two renders are separate compositions, as an activity's are; the
 * screens name their saved state (feature/reports keptKey) so it is found
 * whatever composed around them.
 */
fun Paparazzi.beforeAndRestored(
    before: Store,
    after: Store,
    dark: Boolean = false,
    between: () -> Unit = {},
    content: @Composable () -> Unit,
): Restored {
    var saved: Map<String, List<Any?>> = emptyMap()
    var again: Map<String, List<Any?>> = emptyMap()
    val first = SaveableStateRegistry(null) { true }
    snapshot("before") { Frame(first, before, dark, { saved = it }, content) }
    between()
    val second = SaveableStateRegistry(saved) { true }
    snapshot("restored") { Frame(second, after, dark, { again = it }, content) }
    return Restored(saved, again)
}

/** What the first render wrote to saved state, and what the restored one would write in turn (its live state). */
class Restored(val saved: Map<String, List<Any?>>, val restored: Map<String, List<Any?>>) {
    /** Whether anything the first render saved mentions [s]. */
    fun savedMentions(s: String) = saved.values.flatten().any { it.toString().contains(s) }

    /** The restored render's value under the named key [name] (feature/reports keptKey), unwrapped from its state. */
    fun restoredValue(name: String): Any? =
        restored["neema.$name"]?.firstOrNull().let { (it as? androidx.compose.runtime.State<*>)?.value ?: it }
}

@Composable
private fun Frame(
    registry: SaveableStateRegistry,
    owner: Store,
    dark: Boolean,
    onSaved: (Map<String, List<Any?>>) -> Unit,
    content: @Composable () -> Unit,
) {
    AppFrame(dark = dark) {
        CompositionLocalProvider(LocalSaveableStateRegistry provides registry, LocalViewModelStoreOwner provides owner) {
            content()
        }
        // After every remember observer of this frame ran: what onSaveInstanceState would write now.
        SideEffect { onSaved(registry.performSave()) }
    }
}
