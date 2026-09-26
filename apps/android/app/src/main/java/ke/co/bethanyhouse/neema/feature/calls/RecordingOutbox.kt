package ke.co.bethanyhouse.neema.feature.calls

import ke.co.bethanyhouse.neema.core.net.ApiException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.io.File
import java.util.Base64

/**
 * Call recordings waiting to reach the server. The web uploads once at hang-up
 * and loses the recording if that fails; on a phone network the upload often
 * does fail (the call ended BECAUSE the network dropped), so here each
 * recording is kept on disk until the server has it, and retried whenever the
 * phone is back online (socket reconnect, app back on screen, the next call).
 *
 * Bounded: a recording the server refuses for good (403 recording disabled,
 * 413 too large, 400 empty) is dropped at once; anything older than
 * [MAX_AGE_MS] is dropped; at most [MAX_FILES] are kept (the oldest go first).
 * One drain at a time, so a recording is never uploaded twice concurrently.
 *
 * A recording is stored as `<savedAtMillis>__<base64url(callId)>.m4a`.
 */
internal class RecordingOutbox(private val dir: File, private val now: () -> Long) {
    private val lock = Mutex()

    /** Moves [file] into the outbox for [callId]; returns false (and deletes it) if it can't be kept. */
    fun put(callId: String, file: File): Boolean {
        runCatching { dir.mkdirs() }
        val dest = File(dir, "${now()}__${encode(callId)}.m4a")
        val kept = runCatching { file.renameTo(dest) }.getOrDefault(false) ||
            runCatching { file.copyTo(dest, overwrite = true); true }.getOrDefault(false)
        runCatching { if (file.exists()) file.delete() }
        if (!kept) runCatching { dest.delete() }
        prune()
        return kept
    }

    /** Waiting recordings, oldest first: (callId, file). */
    fun pending(): List<Pair<String, File>> =
        (runCatching { dir.listFiles() }.getOrNull() ?: emptyArray())
            .mapNotNull { f -> parse(f)?.let { (at, id) -> Triple(at, id, f) } }
            .sortedBy { it.first }
            .map { it.second to it.third }

    /**
     * Uploads every waiting recording, oldest first. Stops at the first
     * transient failure (offline, timeout, 5xx, 429, session expired) and
     * keeps the rest for the next try. Returns how many reached the server.
     */
    suspend fun drain(upload: suspend (callId: String, file: File) -> Unit): Int = lock.withLock {
        prune()
        var sent = 0
        for ((id, f) in pending()) {
            if (!f.exists()) continue
            try {
                upload(id, f)
                sent++
                f.delete()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (isTransient(e)) return@withLock sent
                f.delete()   // refused for good: retrying would only fail again
            }
        }
        sent
    }

    /** Drops expired recordings and the oldest beyond [MAX_FILES]. */
    fun prune() {
        val all = (runCatching { dir.listFiles() }.getOrNull() ?: return)
            .mapNotNull { f -> parse(f)?.let { it.first to f } ?: run { if (f.isFile && f.name.endsWith(".m4a")) f.delete(); null } }
            .sortedByDescending { it.first }
        val t = now()
        all.forEachIndexed { i, (at, f) -> if (i >= MAX_FILES || t - at > MAX_AGE_MS) f.delete() }
    }

    private fun parse(f: File): Pair<Long, String>? {
        if (!f.isFile || !f.name.endsWith(".m4a")) return null
        val stem = f.name.removeSuffix(".m4a")
        val at = stem.substringBefore("__", "").toLongOrNull() ?: return null
        val id = runCatching { String(Base64.getUrlDecoder().decode(stem.substringAfter("__")), Charsets.UTF_8) }.getOrNull()
        return if (id.isNullOrEmpty()) null else at to id
    }

    private fun encode(callId: String) =
        Base64.getUrlEncoder().withoutPadding().encodeToString(callId.toByteArray(Charsets.UTF_8))

    companion object {
        const val MAX_FILES = 10
        const val MAX_AGE_MS = 3 * 24 * 60 * 60 * 1000L

        /** Worth another try later: never reached the server, or the server was briefly unable. */
        fun isTransient(e: Throwable): Boolean =
            e is ApiException && (e.status == 0 || e.status == 401 || e.status == 408 || e.status == 429 || e.status >= 500)
    }
}
