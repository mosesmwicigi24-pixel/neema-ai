package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.Fixtures

/**
 * A Nairobi phone network, for the inbox: requests that time out, never
 * connect, or drop halfway — thrown from inside a FakeNeema route exactly
 * where OkHttp would throw them — plus a thread whose server rows a test can
 * add to (the row a timed-out send DID create).
 */
object InboxNetFixtures {
    /** The read timed out: the server may have acted on it. */
    fun timeout(): Nothing = throw java.net.SocketTimeoutException("timeout")

    /** No route to the server at all: the request never left the phone. */
    fun offline(): Nothing = throw java.net.ConnectException("Failed to connect to neema.test/10.0.0.1:443")

    /** The connection died mid-transfer (a 150 MB video halfway up, a reply's answer lost). */
    fun dropped(): Nothing = throw java.io.IOException("unexpected end of stream on https://neema.test/...")

    /** One server thread row created now (admin.py get_thread's shape). */
    fun row(id: String, text: String?, sender: String = "human_agent", note: Boolean = false, mediaType: String? = null, direction: String = "outbound") =
        """{"id":"$id","type":"message","direction":"$direction","sender":"$sender","text":${text?.let { "\"$it\"" } ?: "null"},"isNote":$note,""" +
            """"media_type":${mediaType?.let { "\"$it\"" } ?: "null"},"media_url":${mediaType?.let { "\"https://api.bethanyhouse.co.ke/api/admin/media/$id\"" } ?: "null"},"created_at":"${AppClock.instant()}"}"""

    /** The base thread plus [extra] rows. */
    fun thread(extra: List<String>) = Fixtures.messages.trimEnd().removeSuffix("]") + extra.joinToString("") { ",$it" } + "]"

    /**
     * A server whose thread holds whatever the test's sends have created:
     * `rows` is the live list; GET …/messages always answers the base thread
     * plus those rows (unless [threadDown] says the network is out).
     */
    class Server(val f: FakeNeema) {
        val rows = java.util.concurrent.CopyOnWriteArrayList<String>()
        @Volatile var threadDown: (() -> Nothing)? = null
        init {
            f.on("GET", "/admin/conversations/[^/]+/messages") { _, _ ->
                threadDown?.invoke()
                200 to thread(rows)
            }
        }
        fun calls(method: String, path: String) = f.calls.filter { it.method == method && it.path == path }
    }
}
