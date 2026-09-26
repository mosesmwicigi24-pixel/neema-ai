package ke.co.bethanyhouse.neema.core.util

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Deferred
import kotlinx.coroutines.async

/**
 * One read of a resource on the wire at a time. A caller that arrives while a
 * read is in flight does not start a second one: it shares the NEXT read,
 * which starts the moment the current one ends — so its answer never predates
 * the caller's own reason to ask (a save that just landed, a socket frame).
 * However many callers pile up (a poll tick, a reconnect, a return to the
 * app, a pull-to-refresh and three saves), at most one read runs and one waits.
 *
 * Not thread-safe by design: every caller runs on the main dispatcher (the
 * ViewModel's scope), as the screens' state does. The read runs in [scope],
 * so leaving for good (the ViewModel cleared) cancels it — and its OkHttp call.
 */
class SingleFlight<T>(private val scope: CoroutineScope, private val block: suspend () -> T) {
    private var running: Deferred<T>? = null
    private var queued: Deferred<T>? = null

    /** True while a read is on the wire. */
    val inFlight: Boolean get() = running?.isCompleted == false

    /**
     * Abandon the read on the wire and the one waiting behind it (sign-out,
     * a switch of agent): their OkHttp calls are cancelled and their callers
     * see a CancellationException. The next [run] starts afresh.
     */
    fun cancel() {
        queued?.cancel(); running?.cancel()
        queued = null; running = null
    }

    suspend fun run(): T {
        queued?.let { if (!it.isCompleted) return it.await() }
        val prev = running?.takeIf { !it.isCompleted }
        lateinit var job: Deferred<T>
        job = scope.async(start = CoroutineStart.LAZY) {
            // A queued read starts only once the one ahead of it is over (success or not).
            prev?.join()
            if (queued === job) queued = null
            running = job
            block()
        }
        if (prev == null) running = job else queued = job
        return job.await()
    }
}
