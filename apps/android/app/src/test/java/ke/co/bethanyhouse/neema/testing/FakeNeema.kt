package ke.co.bethanyhouse.neema.testing

import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import java.util.concurrent.CopyOnWriteArrayList

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
 */
class FakeNeema : Interceptor {
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
        routes.add(0, Route(method, Regex("^$path$")) { r, b -> handler(r, b).let { (c, t) -> Reply(c, t) } })
    }

    /** Register a route that also answers with headers (cookies, redirects). */
    fun reply(method: String, path: String, handler: (Request, String?) -> Reply) {
        routes.add(0, Route(method, Regex("^$path$"), handler))
    }

    /** Every recorded call to [method] [path] (exact path). */
    fun callsTo(method: String, path: String) = calls.filter { it.method == method && it.path == path }

    fun called(method: String, pathPrefix: String) = calls.any { it.method == method && it.path.startsWith(pathPrefix) }

    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request()
        val path = req.url.encodedPath.removePrefix("/api")
        val body = req.body?.let { b -> Buffer().also { b.writeTo(it) }.readUtf8() }
        calls.add(Call(req.method, path, req.url.encodedQuery, body, req.headers))
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
