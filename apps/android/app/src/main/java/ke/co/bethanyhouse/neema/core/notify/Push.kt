package ke.co.bethanyhouse.neema.core.notify

import android.content.Context
import android.os.Build
import android.util.Log
import com.google.firebase.FirebaseApp
import com.google.firebase.FirebaseOptions
import com.google.firebase.messaging.FirebaseMessaging
import ke.co.bethanyhouse.neema.BuildConfig
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.coroutines.resume

/**
 * A customer's call rings this phone even when the app is closed (owner,
 * 2026-10-24: "The calls should come through even the app is not open. When
 * any phone is on, route the call there").
 *
 * The live socket reaches only a running app, and Android closes a
 * backgrounded one sooner or later (Samsung sooner). So the server also sends
 * every call event — the ring, "answered", "ended" — to every signed-in phone
 * as a high-priority Firebase data message (apps/api services/push.py).
 * [NeemaPushService] hands it to the same code the socket frame goes to, so
 * the phone rings, and stops, exactly as it does with the app open; the first
 * phone to answer takes the call.
 *
 * Off until the build carries the Firebase project (BuildConfig.FCM_*, from
 * the console's google-services.json): then nothing here runs and calls ring
 * only while the app is running, as before.
 */
object Push {
    private const val TAG = "NeemaPush"
    private val CALL_EVENTS = setOf("incoming_call", "call_answered", "call_ended")

    /** A ring older than this is not rung: Meta stops ringing the business well before. */
    const val STALE_RING_MS = 90_000L

    val configured: Boolean
        get() = BuildConfig.FCM_APP_ID.isNotBlank() && BuildConfig.FCM_PROJECT_ID.isNotBlank() &&
            BuildConfig.FCM_API_KEY.isNotBlank() && BuildConfig.FCM_SENDER_ID.isNotBlank()

    /** Start Firebase from the build's values (there is no google-services.json). True when push is on. */
    fun init(context: Context): Boolean {
        if (!configured) return false
        return runCatching {
            if (FirebaseApp.getApps(context).isEmpty()) {
                FirebaseApp.initializeApp(
                    context,
                    FirebaseOptions.Builder()
                        .setProjectId(BuildConfig.FCM_PROJECT_ID)
                        .setApplicationId(BuildConfig.FCM_APP_ID)
                        .setApiKey(BuildConfig.FCM_API_KEY)
                        .setGcmSenderId(BuildConfig.FCM_SENDER_ID)
                        .build(),
                )
            }
            true
        }.onFailure { runCatching { Log.w(TAG, "Firebase did not start; calls ring only while the app runs", it) } }.getOrDefault(false)
    }

    /** This install's Firebase token, or null (push off, no Google Play services, offline). */
    suspend fun currentToken(): String? {
        if (!configured || runCatching { FirebaseApp.getInstance() }.isFailure) return null
        return suspendCancellableCoroutine { cont ->
            runCatching {
                FirebaseMessaging.getInstance().token.addOnCompleteListener { t ->
                    if (cont.isActive) cont.resume(if (t.isSuccessful) t.result?.takeIf { it.isNotBlank() } else null)
                }
            }.onFailure { if (cont.isActive) cont.resume(null) }
        }
    }

    /**
     * The socket frame a Firebase message stands for, or null when it is not a
     * call event — or a ring so old the caller has long given up (a phone that
     * was off gets the message when it comes back).
     */
    fun frameOf(data: Map<String, String>, nowMs: Long): JsonObject? {
        val type = data["type"] ?: return null
        if (type !in CALL_EVENTS || data["call_id"].isNullOrBlank()) return null
        if (type == "incoming_call") {
            val at = data["at"]?.toLongOrNull()
            if (at != null) {
                val atMs = if (at < 100_000_000_000L) at * 1000 else at   // Meta sends seconds
                if (nowMs - atMs > STALE_RING_MS) return null
            }
        }
        return buildJsonObject { data.forEach { (k, v) -> put(k, JsonPrimitive(v)) } }
    }

    fun device(): String = "${Build.MANUFACTURER} ${Build.MODEL}".trim().take(120)
}

/**
 * Keeps the server told which phone each agent is signed in on: at start, on
 * every sign-in, and whenever Firebase rotates the token. Signing out takes the
 * phone off (before the session goes — the call needs it).
 */
class PushRegistrar(
    private val scope: CoroutineScope,
    private val http: NeemaHttp,
    private val agentId: StateFlow<String?>,
    private val token: suspend () -> String? = Push::currentToken,
    private val enabled: () -> Boolean = { Push.configured },
    private val appVersion: String = "${BuildConfig.VERSION_NAME} (${BuildConfig.BUILD_NUMBER})",
    private val device: () -> String = Push::device,
) {
    @Volatile private var lastToken: String? = null

    fun start() {
        if (!enabled()) return
        scope.launch {
            agentId.map { it }.distinctUntilChanged().collect { id -> if (id != null) register() }
        }
    }

    /** Firebase gave this install a new token. */
    fun onNewToken(fresh: String) {
        if (!enabled()) return
        scope.launch { register(fresh) }
    }

    /** True when the server now rings this phone. Never throws. */
    suspend fun register(fresh: String? = null): Boolean {
        if (!enabled() || agentId.value == null) return false
        val t = fresh ?: token() ?: return false
        return try {
            val body = buildJsonObject {
                put("token", t); put("platform", "android"); put("app_version", appVersion); put("device", device())
            }
            http.raw("POST", "/admin/push/register", http.jsonBody(body))
            lastToken = t
            true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            runCatching { Log.w("NeemaPush", "push registration failed; retried at the next start or sign-in", e) }
            false
        }
    }

    /** Signing out: this phone stops ringing for the team's calls. Best effort. */
    suspend fun unregister() {
        if (!enabled()) return
        val t = lastToken ?: token() ?: return
        try {
            http.raw("POST", "/admin/push/unregister", http.jsonBody(buildJsonObject { put("token", t) }))
        } catch (e: CancellationException) {
            throw e
        } catch (_: Exception) { /* the server forgets it when another agent signs in here */ }
        lastToken = null
    }
}
