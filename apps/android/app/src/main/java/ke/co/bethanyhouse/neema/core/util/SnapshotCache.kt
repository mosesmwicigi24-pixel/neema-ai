package ke.co.bethanyhouse.neema.core.util

import android.content.Context
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import kotlinx.serialization.KSerializer
import java.io.File

/**
 * Stale-while-revalidate snapshots (hooks/useApi.ts): the last good payload
 * per key, so a cold start paints instantly from disk while the real fetch
 * runs. Keys are scoped per agent so the next person on a shared phone never
 * sees the previous agent's data. Best-effort — any failure is a cache miss.
 */
class SnapshotCache(context: Context) {
    private val dir = File(context.cacheDir, "snapshots").apply { mkdirs() }

    private fun file(scope: String, key: String) = File(dir, "${scope.hashCode()}_$key.json")

    fun <T> read(scope: String?, key: String, serializer: KSerializer<T>): T? {
        if (scope == null) return null
        return runCatching { NeemaJson.decodeFromString(serializer, file(scope, key).readText()) }.getOrNull()
    }

    fun <T> write(scope: String?, key: String, serializer: KSerializer<T>, value: T) {
        if (scope == null) return
        runCatching { file(scope, key).writeText(NeemaJson.encodeToString(serializer, value)) }
    }

    /** Forget one snapshot (a draft that was sent, a conversation that was closed). */
    fun delete(scope: String?, key: String) {
        if (scope == null) return
        runCatching { file(scope, key).delete() }
    }

    fun clear() { dir.listFiles()?.forEach { it.delete() } }
}
