package ke.co.bethanyhouse.neema.feature.reports

import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.repeatOnLifecycle
import ke.co.bethanyhouse.neema.core.util.AppClock
import kotlinx.coroutines.delay
import java.util.Collections
import java.util.WeakHashMap

/**
 * A screen ViewModel whose choices (tab, range, filter) and half-typed input
 * must come back after Android kills the app in the background.
 *
 * The ViewModels live in the signed-in agent's store, so a rotation, a theme
 * or font change, a fold or a resize already keeps them; only process death
 * loses them. [KeepUiState] writes [saveUi] into the activity's saved state
 * and hands it to [restoreUi] on the fresh ViewModel the restarted process
 * creates — never to one that survived (a rotation), whose state is newer.
 *
 * What is saved is plain text (JSON) and never a password or other secret:
 * saved state is kept by the system outside the app.
 */
interface KeepsUiState {
    /** What a restarted process should get back, or null for nothing. Never a secret. */
    fun saveUi(): String?

    /** Called at most once, on a fresh ViewModel, with what [saveUi] returned before the process died. */
    fun restoreUi(saved: String)
}

/** ViewModels a screen has already shown: their own state is the truth, not the saved copy. */
private val adopted: MutableSet<Any> = Collections.newSetFromMap(WeakHashMap())

/**
 * Keeps [owner]'s [KeepsUiState.saveUi] in the saved-instance state for as
 * long as this is composed, and restores it into [owner] when the process
 * was restarted. Call it first in the screen, before reading the state.
 */
@Composable
fun KeepUiState(owner: KeepsUiState) {
    val saver = remember(owner) {
        Saver<KeepsUiState, String>(
            save = { it.saveUi() },
            restore = { saved -> if (adopted.add(owner)) owner.restoreUi(saved); owner },
        )
    }
    rememberSaveable(saver = saver, key = keptKey("ui:" + owner.javaClass.name)) { adopted.add(owner); owner }
}

/**
 * A saved-state key that names what it holds ("team.tab", "catalog.product").
 * By default Compose keys saved state by the position of the call in the
 * whole composition, so a restored screen only gets its state back if every
 * ancestor composed exactly as before — after a process restart the shell's
 * first frame need not (a banner, the call card, the rail). A named key does
 * not depend on that. One of each screen is on display at a time, so these
 * never collide.
 */
fun keptKey(name: String) = "neema.$name"

/** A list's scroll position, saved under [name] (see [keptKey]). */
@Composable
fun rememberKeptListState(name: String, firstItem: Int = 0): LazyListState =
    rememberSaveable(saver = LazyListState.Saver, key = keptKey(name)) { LazyListState(firstItem) }

/** A page's scroll position, saved under [name] (see [keptKey]). */
@Composable
fun rememberKeptScrollState(name: String, initial: Int = 0): ScrollState =
    rememberSaveable(saver = ScrollState.Saver, key = keptKey(name)) { ScrollState(initial) }

/** Test hook: forget which ViewModels were shown (each test starts cold). */
internal fun forgetAdopted() = adopted.clear()

/**
 * "Now" for relative times ("4m ago", "Last seen 2h ago", today's bar): read
 * again every [everyMs] while the app is on screen, and at once when it
 * comes back to the foreground — so a phone left in a pocket for an hour
 * never returns to "2m ago".
 */
@Composable
fun rememberNow(everyMs: Long = 60_000L, clock: () -> Long = AppClock::now): Long {
    var now by remember { mutableLongStateOf(clock()) }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    LaunchedEffect(lifecycle, everyMs) {
        lifecycle.repeatOnLifecycle(Lifecycle.State.STARTED) {
            while (true) {
                now = clock()
                delay(everyMs)
            }
        }
    }
    return now
}
