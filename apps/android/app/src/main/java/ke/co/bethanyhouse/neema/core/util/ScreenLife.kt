package ke.co.bethanyhouse.neema.core.util

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

/**
 * Screen lifecycle helpers shared by every feature (moved here from
 * feature/reports, which keeps typealiases so existing imports compile).
 */

/** A background refetch whose failure leaves the screen as it was (the dashboard's poller keeps trying). */
suspend fun quietly(block: suspend () -> Unit) {
    try {
        block()
    } catch (e: CancellationException) {
        throw e
    } catch (e: Exception) {
        // keep what is on screen
    }
}

/**
 * One refetch for a burst of reasons: [kick] schedules [block] after
 * [windowMs] unless one is already waiting, so ten frames (or a return to the
 * foreground plus the socket reconnecting a moment later) cost one round
 * trip. The web's `setTimeout(refetch, 800)` per event, without the storm.
 */
class Coalescer(private val scope: CoroutineScope, private val windowMs: Long, private val block: suspend () -> Unit) {
    private val lock = Any()
    private var pending: Job? = null
    /** Runs never overlap: a kick during a slow run waits for it, so fetches can't stack. */
    private val running = Mutex()

    /** Safe from any thread (socket readers, the main thread) at any rate. */
    fun kick() {
        synchronized(lock) {
            if (pending?.isActive == true) return
            // Recorded before it starts: on an immediate dispatcher the body
            // may run (and clear `pending`) before launch() even returns.
            val job = scope.launch(start = CoroutineStart.LAZY) {
                delay(windowMs)
                synchronized(lock) { pending = null }
                running.withLock { quietly { block() } }
            }
            pending = job
            job.start()
        }
    }
}

/**
 * The web view's lifecycle for a ViewModel that outlives its screen.
 *
 * The shell creates every feature ViewModel with `viewModel { }`, scoped to
 * the activity, so it lives on after the operator leaves the screen; the web's
 * views unmount instead, which stops their `setInterval` and reloads them on
 * the next visit. This gives such a ViewModel the same behaviour:
 *
 * - [shown] is true while the screen is composed (the screen calls
 *   [TrackShown]). It starts true: the screen creates its ViewModel on its
 *   first frame, and the ViewModel's own `init` does the first load.
 * - Each time the screen comes back into view — and, when
 *   [catchUpOnForeground], each time the app comes back to the foreground
 *   (usePolling's `visibilitychange` refetch) — [catchUp] runs once.
 * - When [connected] (the live socket) comes back up after a drop while the
 *   screen is on display, [catchUp] runs: the frames sent while it was down
 *   are lost, so the screen reads the truth again.
 * - Every [pollMs] while the screen is on display AND the app is in front,
 *   [poll] runs (the view's visibility-gated interval). Nothing polls while
 *   the screen is off-screen or the app is in the background.
 *
 * Every refetch is quiet: a failure keeps what is on screen. Catch-ups are
 * coalesced ([catchUpWindowMs]) so a return plus a reconnect is one fetch.
 */
class ScreenLife(
    private val scope: CoroutineScope,
    private val foreground: StateFlow<Boolean>,
    connected: StateFlow<Boolean>? = null,
    pollMs: Long? = null,
    catchUpOnForeground: Boolean = true,
    catchUpWindowMs: Long = CATCH_UP_WINDOW_MS,
    poll: suspend () -> Unit = {},
    catchUp: suspend () -> Unit,
) {
    val shown = MutableStateFlow(true)

    /** On display: the screen is composed and the app is in front. */
    val active: Boolean get() = shown.value && foreground.value

    private val catchUps = Coalescer(scope, catchUpWindowMs, catchUp)

    /** Ask for a catch-up now (coalesced with any already waiting). */
    fun catchUpNow() = catchUps.kick()

    init {
        scope.launch {
            var wasShown = shown.value
            var wasFront = foreground.value
            combine(shown, foreground) { s, f -> s to f }.collectLatest { (s, f) ->
                val reShown = s && !wasShown
                val cameBack = catchUpOnForeground && s && f && !wasFront
                wasShown = s; wasFront = f
                if (!(s && f)) return@collectLatest
                if (reShown || cameBack) catchUps.kick()
                val every = pollMs ?: return@collectLatest
                while (true) {
                    delay(every)
                    quietly { poll() }
                }
            }
        }
        if (connected != null) {
            scope.launch {
                var wasUp = connected.value
                connected.collect { up ->
                    if (up && !wasUp && active) catchUps.kick()
                    wasUp = up
                }
            }
        }
    }

    companion object {
        /** Long enough to fold a foreground return and the socket's reconnect into one fetch. */
        const val CATCH_UP_WINDOW_MS = 500L
        /** The web's `setTimeout(refetch, 800)` after a notification lands. */
        const val EVENT_WINDOW_MS = 800L
    }
}

/** Marks [life]'s screen as on display for as long as this is composed. */
@Composable
fun TrackShown(life: ScreenLife) {
    DisposableEffect(life) {
        life.shown.value = true
        onDispose { life.shown.value = false }
    }
}
