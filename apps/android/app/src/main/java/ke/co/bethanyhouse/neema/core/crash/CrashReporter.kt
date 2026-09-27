package ke.co.bethanyhouse.neema.core.crash

import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.filter
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File

/**
 * Delivers saved crash reports to `POST /admin/client-crashes` once someone
 * is signed in (at start, on sign-in, and after a non-fatal). A report that
 * can't be sent stays on the phone for the next try; the server keeps them
 * for the owner (Settings → App crash reports) and logs each one.
 */
class CrashReporter(
    private val scope: CoroutineScope,
    private val http: NeemaHttp,
    private val signedIn: StateFlow<Boolean>,
    private val pending: () -> List<Pair<File, CrashReport>> = CrashVault::pending,
    private val delivered: (File) -> Unit = CrashVault::delivered,
) {
    private val lock = Mutex()

    fun start() {
        scope.launch { signedIn.filter { it }.collect { flush() } }
    }

    /** Send what is waiting (a no-op when signed out or nothing waits). */
    fun flushSoon() { scope.launch { flush() } }

    suspend fun flush(): Int = lock.withLock {
        if (!signedIn.value) return 0
        var sent = 0
        for ((file, report) in pending()) {
            try {
                val body = http.jsonBody(NeemaJson.encodeToJsonElement(CrashReport.serializer(), report))
                http.raw("POST", "/admin/client-crashes", body)
                delivered(file)
                sent++
            } catch (e: CancellationException) {
                throw e
            } catch (_: Exception) {
                break // offline or refused: try again next time, in order
            }
        }
        sent
    }
}
