package ke.co.bethanyhouse.neema.testing

import ke.co.bethanyhouse.neema.core.net.RequestGate
import kotlinx.coroutines.CompletableDeferred
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import java.io.IOException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger

/**
 * A fake Neema API for tests: answers every request in-process from
 * registered routes (default fixtures in [Fixtures]), and records what was
 * called so tests can assert on it. Unmatched routes answer FastAPI's own
 * 404 `{"detail":"Not Found"}` so a missing fixture shows up as an error state
 * rather than hanging.
 *
 * Bodies: a `DELETE`/`GET` carries none; a JSON body is recorded as sent; a
 * multipart body is recorded as its raw bytes read as UTF-8 (part headers
 * and text parts are legible).
 *
 * Bad networks (see "Network faults" below): [delay] a request (virtual
 * time under `runTest`), [hang] it until the test releases or drops it,
 * [drop] the connection, [timeout], or go [offline] entirely. Delays and
 * holds run in the caller's coroutine before the request is sent (through
 * NeemaHttp's [RequestGate] hook), so a test's virtual clock drives them and
 * cancelling the caller (leaving a screen) abandons the request. They apply
 * to API calls made through NeemaHttp; drops, timeouts and [offline] apply
 * to every request, sign-in and token refresh included.
 */
class FakeNeema : Interceptor, RequestGate {
    data class Call(val method: String, val path: String, val query: String?, val body: String?, val headers: okhttp3.Headers = okhttp3.Headers.headersOf()) {
        /** The decoded query string, e.g. `status=pending&wa_id=254…` → {status=pending, wa_id=254…}. */
        val params: Map<String, String>
            get() = query.orEmpty().split('&').filter { it.isNotEmpty() }.associate {
                java.net.URLDecoder.decode(it.substringBefore('='), "UTF-8") to
                    java.net.URLDecoder.decode(it.substringAfter('=', ""), "UTF-8")
            }
    }

    /** A full answer: status, body and headers (Set-Cookie, Location…). */
    data class Reply(val code: Int = 200, val body: String = "", val headers: Map<String, List<String>> = emptyMap())

    private class Route(val method: String, val pattern: Regex, val handler: (Request, String?) -> Reply)

    private val routes = CopyOnWriteArrayList<Route>()
    val calls = CopyOnWriteArrayList<Call>()

    /** Register a route; later registrations win. [path] is a regex over the path after `/api`. */
    fun on(method: String, path: String, code: Int = 200, body: String) =
        on(method, path) { _, _ -> code to body }

    fun on(method: String, path: String, handler: (Request, String?) -> Pair<Int, String>) {
        // A fresh answer for exactly this route heals any fault injected on it:
        // "timeout(GET /x) … on(GET /x, body)" reads as "then it answers".
        val covers = Regex("^$path$")
        faults.removeAll { f ->
            f.method == method && (f.pattern.pattern == covers.pattern ||
                covers.matches(f.pattern.pattern.removePrefix("^").removeSuffix("$")))
        }
        routes.add(0, Route(method, Regex("^$path$")) { r, b -> handler(r, b).let { (c, t) -> Reply(c, t) } })
    }

    /** Register a route that also answers with headers (cookies, redirects). */
    fun reply(method: String, path: String, handler: (Request, String?) -> Reply) {
        routes.add(0, Route(method, Regex("^$path$"), handler))
    }

    /** Every recorded call to [method] [path] (exact path). */
    fun callsTo(method: String, path: String) = calls.filter { it.method == method && it.path == path }

    fun called(method: String, pathPrefix: String) = calls.any { it.method == method && it.path.startsWith(pathPrefix) }

    // ── Network faults ──────────────────────────────────────────────────────

    /** No network at all: every request fails as a phone with no signal does (UnknownHostException). */
    @Volatile var offline: Boolean = false

    private class Fault(val method: String, val pattern: Regex, val left: AtomicInteger, val kind: Kind) {
        enum class Kind { Drop, Timeout }
        fun matches(m: String, p: String) = (method == "*" || method == m) && pattern.matches(p) && left.getAndUpdate { if (it > 0) it - 1 else it } > 0
    }

    private class Slow(val method: String, val pattern: Regex, val ms: Long, val left: AtomicInteger) {
        fun matches(m: String, p: String) = (method == "*" || method == m) && pattern.matches(p) && left.getAndUpdate { if (it > 0) it - 1 else it } > 0
    }

    private val faults = CopyOnWriteArrayList<Fault>()
    private val slows = CopyOnWriteArrayList<Slow>()
    private val holds = CopyOnWriteArrayList<Hold>()

    /**
     * The connection drops before an answer (IOException "Connection reset"):
     * NeemaHttp reports status 0. [times] limits it to the next N matching
     * requests (a retry then succeeds). [method] "*" matches any method.
     */
    fun drop(method: String, path: String, times: Int = Int.MAX_VALUE) {
        faults.add(0, Fault(method, Regex("^$path$"), AtomicInteger(times), Fault.Kind.Drop))
    }

    /** The request times out (SocketTimeoutException) — NeemaHttp's "timed out after 30s". */
    fun timeout(method: String, path: String, times: Int = Int.MAX_VALUE) {
        faults.add(0, Fault(method, Regex("^$path$"), AtomicInteger(times), Fault.Kind.Timeout))
    }

    /** Answer only after [ms] (virtual time under runTest): a slow server. */
    fun delay(method: String, path: String, ms: Long, times: Int = Int.MAX_VALUE) {
        slows.add(0, Slow(method, Regex("^$path$"), ms, AtomicInteger(times)))
    }

    /**
     * Hold every matching request until the test decides: [Hold.release] lets
     * them (and later ones) through to their routes, [Hold.drop] fails them
     * with a dropped connection. Nothing moves until then — the "server that
     * never answers", for spinners, double taps and leaving mid-request.
     */
    fun hang(method: String, path: String): Hold = Hold(method, Regex("^$path$")).also { holds.add(0, it) }

    /** Remove every fault, delay and hold (held requests are released). */
    fun heal() {
        offline = false
        faults.clear(); slows.clear()
        holds.forEach { it.release() }; holds.clear()
    }

    class Hold internal constructor(private val method: String, private val pattern: Regex) {
        private val gate = CompletableDeferred<IOException?>()
        private val _waiting = AtomicInteger(0)
        /** Requests currently held. */
        val waiting: Int get() = _waiting.get()
        /** How many requests this hold has caught so far. */
        @Volatile var caught: Int = 0
            private set

        internal fun matches(m: String, p: String) = (method == "*" || method == m) && pattern.matches(p) && !gate.isCompleted

        internal suspend fun await() {
            caught++
            _waiting.incrementAndGet()
            try { gate.await()?.let { throw it } } finally { _waiting.decrementAndGet() }
        }

        /** Let held (and later) requests through to their routes. */
        fun release() { gate.complete(null) }

        /** Fail held (and later) requests with a dropped connection. */
        fun drop(e: IOException = IOException("Connection reset")) { gate.complete(e) }
    }

    override suspend fun beforeRequest(method: String, path: String) {
        slows.firstOrNull { it.matches(method, path) }?.let { kotlinx.coroutines.delay(it.ms) }
        holds.firstOrNull { it.matches(method, path) }?.await()
    }

    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request()
        val path = req.url.encodedPath.removePrefix("/api")
        val body = req.body?.let { b -> Buffer().also { b.writeTo(it) }.readUtf8() }
        calls.add(Call(req.method, path, req.url.encodedQuery, body, req.headers))
        if (offline) throw UnknownHostException("Unable to resolve host \"${req.url.host}\": No address associated with hostname")
        faults.firstOrNull { it.matches(req.method, path) }?.let {
            when (it.kind) {
                Fault.Kind.Drop -> throw IOException("Connection reset")
                Fault.Kind.Timeout -> throw SocketTimeoutException("timeout")
            }
        }
        val route = routes.firstOrNull { it.method == req.method && it.pattern.matches(path) }
        // Exactly what FastAPI answers for a path it has no route for; the
        // X-Fake header says which fixture is missing when debugging.
        val reply = route?.handler?.invoke(req, body)
            ?: Reply(404, """{"detail":"Not Found"}""", mapOf("X-Fake" to listOf("no fixture for ${req.method} $path")))
        return Response.Builder()
            .request(req).protocol(Protocol.HTTP_1_1).code(reply.code).message("fake")
            .apply { reply.headers.forEach { (k, vs) -> vs.forEach { addHeader(k, it) } } }
            .body(reply.body.toResponseBody("application/json".toMediaType()))
            .build()
    }

    companion object {
        /** A backend preloaded with a realistic data set for every screen. */
        fun withFixtures(): FakeNeema = FakeNeema().also(Fixtures::install)
    }
}
