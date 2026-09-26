package ke.co.bethanyhouse.neema.core.util

import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.compositionLocalOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.LifecycleResumeEffect
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * A screen ViewModel whose in-progress UI state — a filter, the search text,
 * the open row, a half-typed draft — must come back after Android kills the
 * app in the background.
 *
 * The screen ViewModels live in a per-agent store the activity keeps across a
 * rotation, but not across process death: this is the part of them that goes
 * into the activity's saved state ([RestoreUi]) and is put back into the fresh
 * ViewModel the restored process builds. Data is never saved — it is re-read.
 */
interface SavesUi {
    /** The UI state to keep, as values a Bundle can hold (String, Int, Boolean, null). */
    fun saveUi(): Map<String, Any?>

    /** Puts back what [saveUi] returned before the process died. */
    fun restoreUi(saved: Map<String, Any?>)

    /**
     * Set once a screen has been composed on this ViewModel: a later restore
     * (a rotation, whose saved state is this very ViewModel's) must not replay
     * an older copy over it.
     */
    var uiAttached: Boolean
}

/**
 * Wires [vm] into the activity's saved state. Call it first thing in the
 * screen, before the state is collected, so a restored filter or draft is
 * there on the first frame (no flash of the defaults).
 */
@Composable
fun RestoreUi(vm: SavesUi) {
    rememberSaveable(
        vm,
        saver = Saver<SavesUi, HashMap<String, Any?>>(
            save = { HashMap(it.saveUi()) },
            restore = { saved ->
                // A fresh ViewModel after process death takes the saved state;
                // one that survived (a rotation) already holds the newer truth.
                if (!vm.uiAttached) vm.restoreUi(saved)
                vm
            },
        ),
    ) { vm }
    vm.uiAttached = true
}

/** Reads a saved string (null when absent or not a string). */
fun Map<String, Any?>.str(key: String): String? = this[key] as? String

/**
 * The current minute while the screen is in front: it moves on every minute
 * boundary and on every return to the app, so relative times ("2m ago",
 * "in 3h") read true without a data change to recompose them.
 */
val LocalMinute = compositionLocalOf { 0L }

/** Provides [LocalMinute] to [content], ticking only while the screen is resumed. */
@Composable
fun MinuteTicker(content: @Composable () -> Unit) {
    var minute by remember { mutableLongStateOf(AppClock.now() / 60_000L) }
    val scope = rememberCoroutineScope()
    LifecycleResumeEffect(Unit) {
        minute = AppClock.now() / 60_000L
        val job = scope.launch {
            while (isActive) {
                delay(60_000L - AppClock.now() % 60_000L + 50L)
                minute = AppClock.now() / 60_000L
            }
        }
        onPauseOrDispose { job.cancel() }
    }
    CompositionLocalProvider(LocalMinute provides minute, content = content)
}

/** [Fmt.timeAgo] that re-reads the clock each minute under a [MinuteTicker]. */
@Composable
fun liveAgo(iso: String?): String {
    LocalMinute.current
    return Fmt.timeAgo(iso)
}
