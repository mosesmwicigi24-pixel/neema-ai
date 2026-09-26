package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.auth.AuthException
import ke.co.bethanyhouse.neema.core.auth.AuthRepository
import ke.co.bethanyhouse.neema.core.auth.Session
import ke.co.bethanyhouse.neema.core.auth.SessionStore
import ke.co.bethanyhouse.neema.core.model.OkResponse
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.core.net.ErrorText
import ke.co.bethanyhouse.neema.core.net.NeemaHttp
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.MemoryPrefs
import ke.co.bethanyhouse.neema.testing.fakeJwt
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.JsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.util.concurrent.atomic.AtomicInteger

/**
 * Round 5 — a Nairobi phone network against the real NeemaHttp and
 * AuthRepository: parallel 401s, refreshes that time out or hit an outage,
 * 429s, offline vs timeout, empty / HTML / huge bodies, and sign-in when
 * things are half broken. The rule throughout: only the server refusing the
 * session signs anyone out; an outage is an error message.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class NetworkStressTest {
    private val fake = FakeNeema()
    private val store = SessionStore(null, MemoryPrefs())
    private val auth = AuthRepository(store, "https://neema.test", fake, backoffMs = 0)
    private val http = NeemaHttp("https://neema.test", auth, fake, Dispatchers.Unconfined)

    private fun session(access: String = fakeJwt("a1", 3600)) = Session(
        accessToken = access, refreshToken = "r-1", agentId = "a1", email = "moses@bethanyhouse.co.ke",
        name = "Moses Mwicigi", role = "admin", isSuperuser = true, mode = "direct",
    ).also(store::save)

    private fun tokens(access: String) =
        """{"access_token":"$access","refresh_token":"r-2","token_type":"bearer","agent_id":"a1","role":"admin","is_superuser":true}"""

    private fun expectApi(block: suspend () -> Unit): ApiException = runBlocking {
        try { block(); fail("expected ApiException"); throw IllegalStateException() } catch (e: ApiException) { e }
    }

    /** Counts session-expired signals while [block] runs. */
    private fun expirations(block: () -> Unit): Int = runBlocking {
        val n = AtomicInteger()
        val job = launch(Dispatchers.Unconfined, start = CoroutineStart.UNDISPATCHED) { http.sessionExpired.collect { n.incrementAndGet() } }
        try { block() } finally { job.cancel() }
        n.get()
    }

    // ── 401s and the shared refresh ─────────────────────────────────────────

    @Test
    fun manyParallel401sShareOneRefreshAndAllComplete() = runBlocking {
        val old = session().accessToken
        val fresh = fakeJwt("a1", 7200)
        val refreshes = AtomicInteger()
        fake.on("POST", "/agent-auth/refresh") { _, _ -> refreshes.incrementAndGet(); Thread.sleep(30); 200 to tokens(fresh) }
        fake.on("GET", "/admin/[a-z]+") { req, _ ->
            if (req.header("Authorization") == "Bearer $fresh") 200 to "{}" else 401 to """{"detail":"Token expired"}"""
        }
        val parallel = NeemaHttp("https://neema.test", auth, fake, Dispatchers.IO)
        val paths = listOf("orders", "agents", "catalog", "me", "deals", "leads", "stats", "roles")
        val got = paths.map { p -> async(Dispatchers.IO) { parallel.raw("GET", "/admin/$p") } }.awaitAll()
        assertTrue(got.all { it == "{}" })
        assertEquals("one refresh for the whole burst", 1, refreshes.get())
        assertEquals(fresh, store.current!!.accessToken)
        assertTrue(old != fresh)
    }

    @Test
    fun aRefusedRefreshSignalsExpiryAndABurstAsksTheServerOnce() {
        session()
        fake.on("GET", "/admin/[a-z]+", code = 401, body = """{"detail":"Could not validate credentials"}""")
        fake.on("POST", "/agent-auth/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")
        val n = expirations {
            listOf("orders", "agents", "catalog", "me", "deals", "leads").forEach { p ->
                assertEquals(401, expectApi { http.raw("GET", "/admin/$p") }.status)
            }
        }
        assertTrue("every failed request says so; the dialog is one StateFlow", n >= 1)
        assertEquals("the verdict is remembered", 1, fake.callsTo("POST", "/agent-auth/refresh").size)
        assertNotNull("the dialog re-authenticates over the same session", store.current)
    }

    @Test
    fun aRefreshThatTimesOutIsATimeoutNotASignOut() {
        session()
        fake.on("GET", "/admin/orders", code = 401, body = """{"detail":"Token expired"}""")
        fake.timeout("POST", "/agent-auth/refresh")
        val n = expirations {
            val e = expectApi { http.raw("GET", "/admin/orders") }
            assertEquals(0, e.status)
            assertTrue(e.timedOut)
            assertEquals(ErrorText.TIMED_OUT, ErrorText.of(e))
        }
        assertEquals("no session-expired dialog", 0, n)
        assertEquals("a timeout is not retried (3 × 30 s would freeze every request)", 1, fake.callsTo("POST", "/agent-auth/refresh").size)
        assertNotNull(store.current)
    }

    @Test
    fun aRefreshDuringAnOutageKeepsTheSession() {
        for ((code, body) in listOf(500 to """{"detail":"Internal Server Error"}""", 502 to "<html><body>502 Bad Gateway</body></html>", 503 to "", 429 to "")) {
            fake.calls.clear()
            session()
            fake.on("GET", "/admin/orders", code = 401, body = """{"detail":"Token expired"}""")
            fake.on("POST", "/agent-auth/refresh", code = code, body = body)
            fake.on("POST", "/auth/refresh", code = code, body = body)
            val n = expirations {
                val e = expectApi { http.raw("GET", "/admin/orders") }
                assertEquals("$code", code, e.status)
            }
            assertEquals("$code must not sign anyone out", 0, n)
            assertEquals("$code: three tries", 3, fake.callsTo("POST", "/agent-auth/refresh").size)
            assertNotNull(store.current)
        }
    }

    @Test
    fun aRefreshWhileOfflineOrBehindACaptivePortalKeepsTheSession() {
        session()
        fake.on("GET", "/admin/orders", code = 401, body = """{"detail":"Token expired"}""")
        fake.drop("POST", "/agent-auth/refresh")
        assertEquals(0, expirations { assertEquals(0, expectApi { http.raw("GET", "/admin/orders") }.status) })

        fake.heal()
        // A hotel wifi login page answers everything with its own HTML.
        fake.on("POST", "/(agent-)?auth/refresh", body = "<html><body>Sign in to NairobiFreeWiFi</body></html>")
        assertEquals(0, expirations { assertEquals(0, expectApi { http.raw("GET", "/admin/orders") }.status) })
        assertNotNull(store.current)
    }

    @Test
    fun anOutageDoesNotMakeEveryRequestWaitOutRefreshAttempts() = runBlocking {
        // Inside the 5-minute buffer, so every request would try a proactive refresh.
        val expiring = session(fakeJwt("a1", 120)).accessToken
        fake.on("POST", "/agent-auth/refresh", code = 503, body = "")
        fake.on("GET", "/admin/orders", body = "[]")
        repeat(5) { assertEquals("[]", http.raw("GET", "/admin/orders")) }
        assertEquals("one round of three, then a 30 s cool-down", 3, fake.callsTo("POST", "/agent-auth/refresh").size)
        assertTrue(fake.callsTo("GET", "/admin/orders").all { it.headers["Authorization"] == "Bearer $expiring" })
    }

    @Test
    fun anExpiredTokenDuringAnOutageFailsFastWithoutAPointlessRequest() {
        session(fakeJwt("a1", -10))
        fake.on("POST", "/agent-auth/refresh", code = 502, body = "<html>Bad Gateway</html>")
        fake.on("GET", "/admin/orders", body = "[]")
        val n = expirations { assertEquals(502, expectApi { http.raw("GET", "/admin/orders") }.status) }
        assertEquals(0, n)
        assertTrue("the API is not asked with a dead token", fake.callsTo("GET", "/admin/orders").isEmpty())
    }

    // ── Statuses, bodies, network ───────────────────────────────────────────

    @Test
    fun tooManyRequestsCarriesRetryAfter() {
        session()
        fake.reply("POST", "/admin/conversations/c1/reply") { _, _ ->
            FakeNeema.Reply(429, """{"detail":"Too Many Requests"}""", mapOf("Retry-After" to listOf("12")))
        }
        val e = expectApi { http.raw("POST", "/admin/conversations/c1/reply") }
        assertEquals(429, e.status)
        assertEquals(12L, e.retryAfterSeconds)
        assertEquals("Too many requests. Please wait 12 seconds and try again.", ErrorText.of(e))
    }

    @Test
    fun offlineAndTimeoutReadDifferently() {
        session()
        fake.offline = true
        val off = expectApi { http.raw("GET", "/admin/orders") }
        assertEquals(0, off.status); assertFalse(off.timedOut)
        assertEquals(ErrorText.OFFLINE, ErrorText.of(off))
        fake.offline = false
        fake.timeout("GET", "/admin/orders")
        val slow = expectApi { http.raw("GET", "/admin/orders") }
        assertEquals(0, slow.status); assertTrue(slow.timedOut)
        assertEquals(ErrorText.TIMED_OUT, ErrorText.of(slow))
    }

    @Test
    fun aDroppedConnectionRetriedSucceeds() = runBlocking {
        session()
        fake.on("GET", "/admin/orders", body = "[]")
        fake.drop("GET", "/admin/orders", times = 1)
        assertEquals(0, expectApi { http.raw("GET", "/admin/orders") }.status)
        assertEquals("[]", http.raw("GET", "/admin/orders"))
    }

    @Test
    fun emptyHtmlAndCutOffBodiesNeverCrash() = runBlocking {
        session()
        fake.on("GET", "/admin/empty", body = "")
        assertEquals(null, http.get<OkResponse?>("/admin/empty"))
        assertEquals(JsonObject(emptyMap()), http.get<JsonObject>("/admin/empty"))

        fake.on("GET", "/admin/portal", body = "<!doctype html><html><body>Log in to continue</body></html>")
        val portal = expectApi { http.get<OkResponse>("/admin/portal") }
        assertTrue(portal.malformed)
        assertEquals(ErrorText.UNREADABLE, ErrorText.of(portal))

        fake.on("GET", "/admin/cut", body = """[{"id":"o1","status":"pend""")
        assertTrue(expectApi { http.get<List<JsonObject>>("/admin/cut") }.malformed)
    }

    @Test
    fun aHugeErrorPageIsCappedAndNeverShown() {
        session()
        val page = "<html><body>" + "x".repeat(5_000_000) + "</body></html>"
        fake.on("GET", "/admin/orders", code = 502, body = page)
        val e = expectApi { http.raw("GET", "/admin/orders") }
        assertTrue(e.body.length <= 64 * 1024)
        assertEquals("", e.detail)
        assertEquals(ErrorText.DOWN, ErrorText.of(e))
        assertTrue(e.message!!.length < 1_000)
    }

    // ── The fake's slow and hung server, on virtual time ────────────────────

    @Test
    fun aDelayedAnswerArrivesOnVirtualTime() = runTest {
        session()
        val h = NeemaHttp("https://neema.test", auth, fake, Dispatchers.Unconfined)
        fake.on("GET", "/admin/orders", body = "[]")
        fake.delay("GET", "/admin/orders", 15_000)
        val res = async(StandardTestDispatcher(testScheduler)) { h.raw("GET", "/admin/orders") }
        advanceTimeBy(14_000); runCurrent()
        assertFalse(res.isCompleted)
        assertTrue("not sent until the delay is over", fake.calls.isEmpty())
        advanceTimeBy(1_001); runCurrent()
        assertEquals("[]", res.await())
    }

    @Test
    fun aHungRequestWaitsForReleaseOrDrop() = runTest {
        session()
        val h = NeemaHttp("https://neema.test", auth, fake, Dispatchers.Unconfined)
        fake.on("POST", "/admin/orders/o1/status", body = """{"ok":true}""")
        val hold = fake.hang("POST", "/admin/orders/o1/status")
        val first = async(StandardTestDispatcher(testScheduler)) { h.raw("POST", "/admin/orders/o1/status") }
        advanceTimeBy(600_000); runCurrent()
        assertEquals(1, hold.waiting)
        assertFalse(first.isCompleted)
        hold.release(); runCurrent()
        assertEquals("""{"ok":true}""", first.await())

        val hold2 = fake.hang("POST", "/admin/orders/o1/status")
        val second = async(StandardTestDispatcher(testScheduler)) { runCatching { h.raw("POST", "/admin/orders/o1/status") } }
        runCurrent()
        hold2.drop(); runCurrent()
        assertEquals(0, (second.await().exceptionOrNull() as ApiException).status)

        // Leaving mid-request: the caller is cancelled while held; nothing is ever sent.
        fake.calls.clear()
        fake.hang("GET", "/admin/orders")
        val left = launch(StandardTestDispatcher(testScheduler)) { h.raw("GET", "/admin/orders") }
        runCurrent(); left.cancel(); runCurrent()
        assertTrue(left.isCancelled)
        assertTrue(fake.calls.isEmpty())
    }

    // ── Sign-in when things are broken ──────────────────────────────────────

    private fun loginError(): String = runBlocking {
        try { auth.login("moses@bethanyhouse.co.ke", "pw"); fail(); "" } catch (e: AuthException) { e.message!! }
    }

    @Test
    fun loginOfflineOrTimingOutSaysSo() {
        fake.offline = true
        assertEquals(AuthRepository.OFFLINE, loginError())
        fake.offline = false
        fake.timeout("POST", "/agent-auth/login")
        assertEquals(AuthRepository.TIMED_OUT, loginError())
    }

    @Test
    fun loginAgainstAGatewayOutageOrRateLimitIsNotAWrongPassword() {
        fake.on("POST", "/agent-auth/login", code = 503, body = "<html><body>503 Service Temporarily Unavailable</body></html>")
        assertEquals(AuthRepository.UNAVAILABLE, loginError())
        assertFalse("an outage is final: no NextAuth detour", fake.called("GET", "/auth/csrf"))
        fake.on("POST", "/agent-auth/login", code = 429, body = "<html>Too Many Requests</html>")
        assertEquals(AuthRepository.TOO_MANY, loginError())
    }

    @Test
    fun aHalfBrokenNextAuthIsUnavailableNotAWrongPassword() {
        fake.on("POST", "/agent-auth/login", code = 404, body = """{"detail":"Not Found"}""")
        fake.on("POST", "/auth/login", code = 404, body = """{"detail":"Not Found"}""")
        fake.reply("GET", "/auth/csrf") { _, _ -> FakeNeema.Reply(200, """{"csrfToken":"c"}""") }
        // authorize() threw because FastAPI is down: NextAuth answers 500.
        fake.on("POST", "/auth/callback/credentials", code = 500, body = "Internal Server Error")
        assertEquals(AuthRepository.UNAVAILABLE, loginError())

        // Signed in, but the session endpoint is failing.
        fake.reply("POST", "/auth/callback/credentials") { _, _ ->
            FakeNeema.Reply(200, """{"url":"https://neema.test/dashboard"}""", mapOf("Set-Cookie" to listOf("__Secure-next-auth.session-token=S; Path=/")))
        }
        fake.on("GET", "/auth/session", code = 502, body = "<html>Bad Gateway</html>")
        assertEquals(AuthRepository.UNAVAILABLE, loginError())

        // The session endpoint's connection drops.
        fake.drop("GET", "/auth/session")
        assertEquals(AuthRepository.OFFLINE, loginError())
        assertEquals(null, store.current)
    }
}
