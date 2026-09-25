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
import java.net.SocketTimeoutException
import java.util.concurrent.TimeUnit

/** Thrown for any non-2xx answer; [status] is the HTTP code (0 = network). */
class ApiException(val status: Int, val method: String, val path: String, val body: String) :
    IOException("$method $path → $status: $body") {
    /**
     * The server's `detail` when it sent one (FastAPI convention): a plain
     * string from `HTTPException(detail=…)`, or — for a request pydantic
     * rejected (422) — a list of `{loc, msg, type}` errors, read as their
     * messages. Anything else (a proxy's HTML page, "Internal Server Error")
     * is shown trimmed.
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
        }.getOrNull() ?: body.trim().take(200)
}

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
 * proactively before expiry and once more on a 401 before giving up.
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

    private val _sessionExpired = MutableSharedFlow<Unit>(extraBufferCapacity = 1)
    /** Fires when a request came back 401 and a refresh could not rescue it. */
    val sessionExpired: SharedFlow<Unit> = _sessionExpired.asSharedFlow()

    private val jsonType = "application/json".toMediaType()

    suspend fun raw(method: String, path: String, body: RequestBody? = null, upload: Boolean = false): String =
        withContext(io) {
            val url = if (path.startsWith("http")) path else "$apiBase$path"
            fun build(token: String?): Request = Request.Builder()
                .url(url)
                .method(method, body ?: if (method == "GET" || method == "DELETE") null else "".toRequestBody(jsonType))
                .header("Accept", "application/json")
                .apply { if (token != null) header("Authorization", "Bearer $token") }
                .build()

            val c = if (upload) uploadClient else client
            val used = tokens.validAccessToken()
            var res = execute(c, build(used), method, path)
            // FastAPI 0.115's HTTPBearer answers a request with NO token 403
            // "Not authenticated", not 401. That only happens once the token ran
            // out and could not be refreshed: the same dead session.
            if (res.code == 401 || (res.code == 403 && used == null)) {
                res.close()
                tokens.onRejected(used)
                // One rescue attempt: the token may have expired between the
                // proactive check and the server's clock.
                val fresh = tokens.forceRefresh()
                if (fresh != null) res = execute(c, build(fresh), method, path)
                if (fresh == null || res.code == 401) {
                    res.close()
                    _sessionExpired.tryEmit(Unit)
                    throw ApiException(401, method, path, "Session expired")
                }
            }
            res.use { r ->
                val text = r.body?.string().orEmpty()
                if (!r.isSuccessful) throw ApiException(r.code, method, path, text)
                text
            }
        }

    private fun execute(c: OkHttpClient, req: Request, method: String, path: String): Response = try {
        c.newCall(req).execute()
    } catch (e: SocketTimeoutException) {
        throw ApiException(0, method, path, "timed out after 30s")
    } catch (e: IOException) {
        if (e is ApiException) throw e
        throw ApiException(0, method, path, e.message ?: "network error")
    }

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
        if (text.isNotBlank()) return NeemaJson.decodeFromString(serializer<T>(), text)
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
    /** Refresh now regardless of expiry; null when the session is gone. */
    suspend fun forceRefresh(): String?
    /** The server refused this token — never hand it out again as "still valid". */
    fun onRejected(token: String?)
}
