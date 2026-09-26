package ke.co.bethanyhouse.neema.testing.fixtures

import ke.co.bethanyhouse.neema.testing.FakeNeema

/**
 * A Nairobi phone network, for the Reports / Analytics / Catalog / Team /
 * Profile / Settings error tests: each helper makes one route fail the way
 * a real link does. The client turns a thrown IOException into its
 * status-0 ApiException exactly as it does for a real socket.
 */
object NetStressFixtures {
    /** No network at all: the connection is refused before anything is sent. */
    fun offline(f: FakeNeema, method: String, path: String) =
        f.on(method, path) { _, _ -> throw java.net.ConnectException("Failed to connect to neema.test/10.0.0.1:443") }

    /** The server never answered within the client's ceiling. */
    fun timeout(f: FakeNeema, method: String, path: String) =
        f.on(method, path) { _, _ -> throw java.net.SocketTimeoutException("timeout") }

    /** The server did the work ([land] runs), then the answer was lost on the way back. */
    fun landThenTimeout(f: FakeNeema, method: String, path: String, land: (String?) -> Unit) =
        f.on(method, path) { _, body -> land(body); throw java.net.SocketTimeoutException("timeout") }

    /** A load balancer's HTML error page. */
    const val HTML_502 = "<html><head><title>502 Bad Gateway</title></head><body><center><h1>502 Bad Gateway</h1></center><hr><center>nginx</center></body></html>"

    fun html(f: FakeNeema, method: String, path: String, code: Int = 502) = f.on(method, path, code = code, body = HTML_502)

    /** FastAPI's shape: `{"detail": "…"}`. */
    fun status(f: FakeNeema, method: String, path: String, code: Int, detail: String) =
        f.on(method, path, code = code, body = """{"detail":${kotlinx.serialization.json.JsonPrimitive(detail)}}""")

    /** Every sign-in route refuses: a 401 can't be rescued, so the session-expired dialog must show. */
    fun refreshRefused(f: FakeNeema) =
        f.on("POST", "/(agent-auth|auth)/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")

    /**
     * Answers 401 once (a stale token), then hands over to [then]. The refresh
     * hands out a token that differs from the rejected one (the base fixture's
     * would be byte-identical within the same second, which the auth layer
     * rightly refuses as "no rescue").
     */
    fun unauthorizedOnce(f: FakeNeema, method: String, path: String, then: (String?) -> Pair<Int, String>) {
        f.on("POST", "/(agent-auth|auth)/refresh") { _, _ ->
            200 to ke.co.bethanyhouse.neema.testing.Fixtures.tokenResponse(access = ke.co.bethanyhouse.neema.testing.fakeJwt(expiresInSec = 7L * 24 * 3600))
        }
        var first = true
        f.on(method, path) { _, body -> if (first) { first = false; 401 to """{"detail":"Could not validate credentials"}""" } else then(body) }
    }
}
