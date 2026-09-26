package ke.co.bethanyhouse.neema.core.net

import ke.co.bethanyhouse.neema.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.serializer
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.IOException
import java.io.InterruptedIOException
import java.util.concurrent.TimeUnit

/**
 * Thrown for any non-2xx answer; [status] is the HTTP code (0 = the request
 * never got an answer: offline, connection refused or dropped, timed out).
 *
 * [retryAfterSeconds] is a 429/503's `Retry-After` (seconds form) when sent.
 * [malformed] marks a 2xx whose body could not be read as what was asked
 * for (a captive portal's page, a cut-off answer); [status] is then the
 * code that came back.
 */
class ApiException(
    val status: Int,
    val method: String,
    val path: String,
    val body: String,
    val retryAfterSeconds: Long? = null,
    val malformed: Boolean = false,
) : IOException("$method $path → $status: ${body.take(500)}") {
    /** The request ran out of time (the 30 s ceiling, or the long client's). */
    val timedOut: Boolean get() = status == 0 && body.startsWith("timed out")

    /**
     * The server's `detail` when it sent one (FastAPI convention): a plain
     * string from `HTTPException(detail=…)`, or — for a request pydantic
     * rejected (422) — a list of `{loc, msg, type}` errors, read as their
     * messages. A plain-text answer ("Internal Server Error") is shown
     * trimmed; a proxy's HTML page never is: it reads as no detail at all.
     */
    val detail: String
        get() = runCatching {
            when (val d = (NeemaJson.parseToJsonElement(body) as? JsonObject)?.get("detail")) {
                null, is JsonNull -> null
                is JsonPrimitive -> d.content
                is JsonArray -> d.mapNotNull { e ->
                    ((e as? JsonObject)?.get("msg") as? JsonPrimitive)?.content ?: (e as? JsonPrimitive)?.content
                }.joinToString("; ").ifEmpty { null }
                is JsonObject -> (d["message"] as? JsonPrimitive)?.content
                    ?: (d["error"] as? JsonPrimitive)?.content ?: d.toString()
            }
        }.getOrNull() ?: body.trim().let { if (looksLikeHtml(it)) "" else it.take(200) }

    companion object {
        /** A web page rather than an API answer (a proxy's error page, a captive portal). */
        fun looksLikeHtml(text: String): Boolean {
            val t = text.trimStart().take(64).lowercase()
            return t.startsWith("<!doctype") || t.startsWith("<html") || t.startsWith("<head") ||
                t.startsWith("<body") || t.startsWith("<?xml") || (t.startsWith("<") && text.contains("</"))
        }
    }
}

/**
 * Tests only: a hook [NeemaHttp] awaits before each request, in the caller's
 * coroutine (so a test's virtual clock drives it). The fake backend uses it
 * to delay a request or hold it until released. Production has none.
 */
interface RequestGate {
    /** [path] is the part after `/api`, without the query string. */
    suspend fun beforeRequest(method: String, path: String)
}

/**
 * The auth server could not be asked (offline, timed out, 5xx, 429): the
 * session may be perfectly good, so this must never read as "signed out".
 * [status] is 0 for no answer, else the auth server's code.
 */
class RefreshUnavailable(val status: Int, val timedOut: Boolean, message: String) : IOException(message)

/** How much of an error body is kept (plenty for any FastAPI `detail`). */
const val MAX_ERROR_BODY: Long = 64 * 1024

val NeemaJson: Json = Json {
    ignoreUnknownKeys = true
    isLenient = true
    coerceInputValues = true
    explicitNulls = false
    encodeDefaults = true
}

/**
 * The Android twin of `lib/api.ts`'s `req()`: JSON over HTTPS against
 * `${BASE}/api`, a bearer token on every call, a 30-second ceiling so a
 * dropped connection can never become a spinner that never dies, and a
 * single session-expired signal when the server stops accepting us.
 *
 * Token handling lives in [TokenProvider] (the auth layer): it refreshes
 * proactively before expiry and once more on a 401 before giving up. Only
 * a refresh the server actually refused expires the session; one it could
 * not answer (offline, 5xx) fails this request and keeps the session.
 */
class NeemaHttp(
    val baseUrl: String = BuildConfig.NEEMA_BASE_URL,
    private val tokens: TokenProvider,
    /** Tests only: answers requests without the network. */
    interceptor: okhttp3.Interceptor? = null,
    private val io: kotlinx.coroutines.CoroutineDispatcher = Dispatchers.IO,
) {
    val apiBase: String get() = "$baseUrl/api"

    val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        .apply { if (interceptor != null) addInterceptor(interceptor) }
        .build()

    /** Long-lived client for media uploads (videos up to 150 MB are transcoded server-side). */
    val uploadClient: OkHttpClient = client.newBuilder()
        .callTimeout(10, TimeUnit.MINUTES)
        .readTimeout(10, TimeUnit.MINUTES)
        .writeTimeout(10, TimeUnit.MINUTES)
        .build()

    /** The socket and websockets share connection pools with REST. */
    val wsClient: OkHttpClient = client.newBuilder()
        .callTimeout(0, TimeUnit.MILLISECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()

    private val gate: RequestGate? = interceptor as? RequestGate

    private val _sessionExpired = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    /** Fires when a request came back 401 and a refresh could not rescue it. */
    val sessionExpired: SharedFlow<Unit> = _sessionExpired.asSharedFlow()

    private val _forbidden = MutableSharedFlow<String>(extraBufferCapacity = 8)
    /**
     * Fires ("METHOD /path") when the server refused a signed-in request with
     * 403: the agent's role or permissions may have changed since the app last
     * read them, so the dashboard rereads /admin/me and the team list.
     * GETs of those two are left out, so a refusal there can't loop.
     */
    val forbidden: SharedFlow<String> = _forbidden.asSharedFlow()

    private val jsonType = "application/json".toMediaType()

    suspend fun raw(method: String, path: String, body: RequestBody? = null, upload: Boolean = false): String {
        try { gate?.beforeRequest(method, gatePath(path)) } catch (e: IOException) { throw networkError(e, method, path, upload) }
        return withContext(io) {
            val url = if (path.startsWith("http")) path else "$apiBase$path"
            fun build(token: String?): Request = Request.Builder()
                .url(url)
                .method(method, body ?: if (method == "GET" || method == "DELETE") null else "".toRequestBody(jsonType))
                .header("Accept", "application/json")
                .apply { if (token != null) header("Authorization", "Bearer $token") }
                .build()

            val c = if (upload) uploadClient else client
            val used = authStep(method, path) { tokens.validAccessToken() }
            var res = execute(c, build(used), method, path, upload)
            // FastAPI 0.115's HTTPBearer answers a request with NO token 403
            // "Not authenticated", not 401. That only happens once the token ran
            // out and could not be refreshed: the same dead session.
            if (res.code == 401 || (res.code == 403 && used == null)) {
                res.close()
                tokens.onRejected(used)
                // One rescue attempt: the token may have expired between the
                // proactive check and the server's clock. Requests rejected
                // together share that one refresh (the auth layer serialises
                // it). A refresh the auth server could not answer is an
                // outage, not a signed-out agent: it fails this request only.
                val fresh = authStep(method, path) { tokens.forceRefresh() }
                if (fresh != null) res = execute(c, build(fresh), method, path, upload)
                if (fresh == null || res.code == 401) {
                    res.close()
                    _sessionExpired.tryEmit(Unit)
                    throw ApiException(401, method, path, "Session expired")
                }
            }
            res.use { r ->
                if (!r.isSuccessful) {
                    // An error page can be anything (a proxy's multi-megabyte
                    // HTML dump): only its head is worth keeping.
                    val text = runCatching { r.peekBody(MAX_ERROR_BODY).string() }.getOrDefault("")
                    if (r.code == 403 && !isIdentityRead(method, path)) _forbidden.tryEmit("$method ${gatePath(path)}")
                    throw ApiException(r.code, method, path, text, retryAfterSeconds = retryAfter(r))
                }
                // The connection can still drop while the body streams in.
                try { r.body?.string().orEmpty() } catch (e: IOException) { throw networkError(e, method, path, upload) }
            }
        }
    }

    private fun isIdentityRead(method: String, path: String): Boolean =
        method == "GET" && gatePath(path).trimEnd('/') in setOf("/admin/me", "/admin/agents")

    private fun gatePath(path: String): String =
        (if (path.startsWith("http")) path.substringAfter("://").substringAfter('/').let { "/$it" }.removePrefix("/api") else path)
            .substringBefore('?')

    private suspend fun <T> authStep(method: String, path: String, step: suspend () -> T): T = try {
        step()
    } catch (e: RefreshUnavailable) {
        throw ApiException(e.status, method, path, if (e.timedOut) "timed out after 30s" else (e.message ?: "network error"))
    }

    private fun execute(c: OkHttpClient, req: Request, method: String, path: String, upload: Boolean): Response = try {
        c.newCall(req).execute()
    } catch (e: IOException) {
        throw networkError(e, method, path, upload)
    }

    private fun networkError(e: IOException, method: String, path: String, upload: Boolean): ApiException = when (e) {
        is ApiException -> e
        // SocketTimeoutException (connect/read/write) and OkHttp's call
        // timeout (a bare InterruptedIOException "timeout") alike.
        is InterruptedIOException -> ApiException(0, method, path, if (upload) "timed out after 10 min" else "timed out after 30s")
        else -> ApiException(0, method, path, e.message ?: "network error")
    }

    /** `Retry-After: <seconds>` (the HTTP-date form is rare enough to ignore). */
    private fun retryAfter(r: Response): Long? = r.header("Retry-After")?.trim()?.toLongOrNull()?.coerceIn(0, 3600)

    fun jsonBody(value: JsonElement): RequestBody = value.toString().toRequestBody(jsonType)

    suspend inline fun <reified T> get(path: String): T = decode(raw("GET", path))
    suspend inline fun <reified T> delete(path: String): T = decode(raw("DELETE", path))
    suspend inline fun <reified B, reified T> post(path: String, body: B): T =
        decode(raw("POST", path, encode(body)))
    suspend inline fun <reified B, reified T> patch(path: String, body: B): T =
        decode(raw("PATCH", path, encode(body)))
    suspend inline fun <reified B, reified T> put(path: String, body: B): T =
        decode(raw("PUT", path, encode(body)))

    suspend inline fun <reified T> multipart(path: String, parts: MultipartBody): T =
        decode(raw("POST", path, parts, upload = true))

    inline fun <reified B> encode(body: B): RequestBody =
        NeemaJson.encodeToString(serializer<B>(), body).toRequestBody("application/json".toMediaType())

    inline fun <reified T> decode(text: String): T {
        if (T::class == Unit::class) return Unit as T
        if (text.isNotBlank()) return try {
            NeemaJson.decodeFromString(serializer<T>(), text)
        } catch (e: IllegalArgumentException) {
            // SerializationException is one: a captive portal's page, a cut-off
            // answer, a shape the app doesn't know. A readable failure, not a crash.
            throw ApiException(200, "", "(response)", text.take(MAX_ERROR_BODY.toInt()), malformed = true)
        }
        // An empty 2xx (a 204, or a handler that returned None) is a success:
        // read it as null, else as an empty object / list, never as a failure.
        val ser = serializer<T>()
        return runCatching { NeemaJson.decodeFromString(ser, "null") }
            .recoverCatching { NeemaJson.decodeFromString(ser, "{}") }
            .getOrElse { NeemaJson.decodeFromString(ser, "[]") }
    }
}

/** Implemented by the auth layer; the HTTP client never touches storage directly. */
interface TokenProvider {
    /** A token good for at least a few minutes, refreshing first if needed. */
    suspend fun validAccessToken(): String?
    /**
     * Refresh now regardless of expiry; null when the server refused (the
     * session is gone). Throws [RefreshUnavailable] when the auth server could
     * not be asked — the session is not known to be gone. [validAccessToken]
     * may throw it too, for a token already expired.
     */
    suspend fun forceRefresh(): String?
    /** The server refused this token — never hand it out again as "still valid". */
    fun onRejected(token: String?)
}
