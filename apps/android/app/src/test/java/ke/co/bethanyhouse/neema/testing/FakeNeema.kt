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
 * called so tests can assert on it. Unmatched routes answer 404 so a missing
 * fixture shows up as an error state rather than hanging.
 */
class FakeNeema : Interceptor {
    data class Call(val method: String, val path: String, val query: String?, val body: String?)

    private class Route(val method: String, val pattern: Regex, val handler: (Request, String?) -> Pair<Int, String>)

    private val routes = CopyOnWriteArrayList<Route>()
    val calls = CopyOnWriteArrayList<Call>()

    /** Register a route; later registrations win. [path] is a regex over the path after `/api`. */
    fun on(method: String, path: String, code: Int = 200, body: String) =
        on(method, path) { _, _ -> code to body }

    fun on(method: String, path: String, handler: (Request, String?) -> Pair<Int, String>) {
        routes.add(0, Route(method, Regex("^$path$"), handler))
    }

    fun called(method: String, pathPrefix: String) = calls.any { it.method == method && it.path.startsWith(pathPrefix) }

    override fun intercept(chain: Interceptor.Chain): Response {
        val req = chain.request()
        val path = req.url.encodedPath.removePrefix("/api")
        val body = req.body?.let { b -> Buffer().also { b.writeTo(it) }.readUtf8() }
        calls.add(Call(req.method, path, req.url.encodedQuery, body))
        val route = routes.firstOrNull { it.method == req.method && it.pattern.matches(path) }
        val (code, text) = route?.handler?.invoke(req, body) ?: (404 to """{"detail":"no fixture for ${req.method} $path"}""")
        return Response.Builder()
            .request(req).protocol(Protocol.HTTP_1_1).code(code).message("fake")
            .body(text.toResponseBody("application/json".toMediaType()))
            .build()
    }

    companion object {
        /** A backend preloaded with a realistic data set for every screen. */
        fun withFixtures(): FakeNeema = FakeNeema().also(Fixtures::install)
    }
}
