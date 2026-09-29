package ke.co.bethanyhouse.neema.core.crash

import android.app.ActivityManager
import android.app.ApplicationExitInfo
import android.content.Context
import android.os.Build
import ke.co.bethanyhouse.neema.BuildConfig
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.time.Instant
import java.util.UUID

/**
 * Crash reports that survive the crash (owner, 2026-09-27: "Neema closed
 * because this app has a bug" and nobody could say why).
 *
 * - An uncaught exception on any thread is written to disk synchronously,
 *   then handed on to the system's handler (the app still closes: continuing
 *   after an unknown failure is worse than restarting).
 * - An error that escaped a background coroutine of the app scope is recorded
 *   as `nonfatal` — the scope's handler keeps the app alive.
 * - On Android 11+ the system's own exit record adds what no Java handler can
 *   see: native crashes (WebRTC) and freezes the system killed (ANR).
 *
 * Reports wait in `files/crash/` until [CrashReporter] delivers them.
 */
object CrashVault {
    private const val DIR = "crash"
    private const val MAX_FILES = 10
    private const val MAX_TRACE = 48_000
    private const val PREF = "neema_crash"
    private const val KEY_EXIT_SEEN = "exit_seen_ms"

    private val json = Json { ignoreUnknownKeys = true; explicitNulls = false }

    @Volatile private var dir: File? = null

    /** First thing in Application.onCreate. */
    fun install(context: Context) {
        val app = context.applicationContext
        dir = File(app.filesDir, DIR).apply { mkdirs() }
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        Thread.setDefaultUncaughtExceptionHandler { thread, error ->
            if (contained(thread.name)) {
                // WebRTC's own audio threads assert on the device's audio state (the mic or
                // speaker changing under them): that thread ends and the call goes quiet —
                // the agent can hang up and call again. The whole app closing is worse.
                runCatching { save(report("nonfatal", error, thread.name)) }
                return@setDefaultUncaughtExceptionHandler
            }
            runCatching { save(report("crash", error, thread.name)) }
            if (previous != null) previous.uncaughtException(thread, error)
            else { android.os.Process.killProcess(android.os.Process.myPid()); kotlin.system.exitProcess(10) }
        }
        runCatching { collectExitReasons(app) }
    }

    /** Threads whose failure ends only themselves (see [install]): WebRTC's Java audio threads. */
    internal fun contained(thread: String?): Boolean = thread == "AudioTrackJavaThread" || thread == "AudioRecordJavaThread"

    /** An error that was caught at the edge (a background coroutine) — the app keeps running. */
    fun recordNonFatal(error: Throwable, where: String = Thread.currentThread().name) {
        runCatching { save(report("nonfatal", error, where)) }
    }

    /** Reports not yet delivered, oldest first. */
    fun pending(): List<Pair<File, CrashReport>> {
        val d = dir ?: return emptyList()
        return (d.listFiles { f -> f.name.endsWith(".json") } ?: emptyArray())
            .sortedBy { it.name }
            .mapNotNull { f -> runCatching { f to json.decodeFromString(CrashReport.serializer(), f.readText()) }.getOrNull() ?: run { f.delete(); null } }
    }

    /** The newest report on this phone (delivered or not) — Settings shows it with Copy. */
    fun latest(): CrashReport? = (dir?.let { File(it, "last.txt") })?.takeIf { it.exists() }
        ?.let { runCatching { json.decodeFromString(CrashReport.serializer(), it.readText()) }.getOrNull() }

    fun delivered(file: File) { runCatching { file.delete() } }

    internal fun report(kind: String, error: Throwable?, thread: String?, trace: String? = null, at: Instant = Instant.now()): CrashReport {
        val text = (trace ?: error?.let { stackOf(it) }).orEmpty()
        return CrashReport(
            id = UUID.randomUUID().toString(),
            at = at.toString(),
            kind = kind,
            thread = thread,
            summary = (error?.let { "${it.javaClass.name}: ${it.message.orEmpty()}" } ?: text.lineSequence().firstOrNull().orEmpty()).take(500),
            trace = text.take(MAX_TRACE),
            appVersion = BuildConfig.VERSION_NAME,
            build = BuildConfig.BUILD_NUMBER,
            device = "${Build.MANUFACTURER} ${Build.MODEL}".take(120),
            sdk = Build.VERSION.SDK_INT,
        )
    }

    private fun save(r: CrashReport) {
        val d = dir ?: return
        val body = json.encodeToString(CrashReport.serializer(), r)
        File(d, "${System.currentTimeMillis()}-${r.kind}.json").writeText(body)
        File(d, "last.txt").writeText(body)
        (d.listFiles { f -> f.name.endsWith(".json") } ?: emptyArray())
            .sortedBy { it.name }.dropLast(MAX_FILES).forEach { it.delete() }
    }

    private fun stackOf(e: Throwable): String = StringWriter().also { e.printStackTrace(PrintWriter(it)) }.toString()

    /** Native crashes and ANRs since the last look (Android 11+). Java crashes are already on disk. */
    private fun collectExitReasons(context: Context) {
        if (Build.VERSION.SDK_INT < 30) return
        val am = context.getSystemService(ActivityManager::class.java) ?: return
        val prefs = context.getSharedPreferences(PREF, Context.MODE_PRIVATE)
        val seen = prefs.getLong(KEY_EXIT_SEEN, 0L)
        val exits = am.getHistoricalProcessExitReasons(context.packageName, 0, 10)
        var newest = seen
        for (x in exits) {
            if (x.timestamp <= seen) continue
            newest = maxOf(newest, x.timestamp)
            val kind = when (x.reason) {
                ApplicationExitInfo.REASON_CRASH_NATIVE -> "native"
                ApplicationExitInfo.REASON_ANR -> "anr"
                else -> continue
            }
            // Only the first run records the past: never report exits from before install.
            if (seen == 0L) continue
            val trace = runCatching { x.traceInputStream?.use { s -> s.readBytes().decodeToString().take(MAX_TRACE) } }.getOrNull()
            save(report(kind, null, x.processName, trace = listOfNotNull(x.description, trace).joinToString("\n"),
                at = Instant.ofEpochMilli(x.timestamp)))
        }
        prefs.edit().putLong(KEY_EXIT_SEEN, if (newest == 0L) System.currentTimeMillis() else newest).apply()
    }
}

/**
 * One live frame (or one step of a long-lived collector) handled on its own: a
 * failure is recorded and the collector carries on. A collector in a
 * viewModelScope has no handler — one bad frame used to close the app.
 */
internal inline fun contained(where: String, block: () -> Unit) {
    try { block() } catch (e: kotlinx.coroutines.CancellationException) { throw e } catch (e: Throwable) {
        CrashVault.recordNonFatal(e, where)
    }
}

@Serializable
data class CrashReport(
    val id: String,
    val at: String,
    val kind: String,
    val thread: String? = null,
    val summary: String = "",
    val trace: String = "",
    @SerialName("app_version") val appVersion: String = "",
    val build: String = "",
    val device: String = "",
    val sdk: Int = 0,
)
