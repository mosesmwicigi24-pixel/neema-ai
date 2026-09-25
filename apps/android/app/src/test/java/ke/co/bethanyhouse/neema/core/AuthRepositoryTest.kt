package ke.co.bethanyhouse.neema.core

import ke.co.bethanyhouse.neema.core.auth.AuthException
import ke.co.bethanyhouse.neema.core.auth.AuthRepository
import ke.co.bethanyhouse.neema.core.auth.Session
import ke.co.bethanyhouse.neema.core.auth.SessionStore
import ke.co.bethanyhouse.neema.testing.FakeNeema
import ke.co.bethanyhouse.neema.testing.MemoryPrefs
import ke.co.bethanyhouse.neema.testing.fakeJwt
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/**
 * Sign-in and silent refresh (lib/auth.ts + the NextAuth route) against a
 * fake that plays both FastAPI's `/api/agent-auth` routes and NextAuth's
 * csrf → callback → session flow.
 */
class AuthRepositoryTest {
    private val fake = FakeNeema()
    private val store = SessionStore(null, MemoryPrefs())
    private val auth = AuthRepository(store, "https://neema.test", fake, backoffMs = 0)

    private fun tokens(access: String, refresh: String = "r-1", role: String = "admin", superuser: Boolean = true) =
        """{"access_token":"$access","refresh_token":"$refresh","token_type":"bearer","agent_id":"a1","role":"$role","is_superuser":$superuser}"""

    private fun direct(access: String = fakeJwt("a1", 3600)) = Session(
        accessToken = access, refreshToken = "r-1", agentId = "a1", email = "moses@bethanyhouse.co.ke",
        name = "Moses Mwicigi", role = "admin", isSuperuser = true, mode = "direct",
    )

    /** NextAuth v4 (the deployed app/api/auth/[...nextauth]/route.ts): csrf, credentials callback, session. */
    private fun installNextAuth(sessionAccess: String, wrongPassword: Boolean = false) {
        fake.reply("GET", "/auth/csrf") { _, _ ->
            FakeNeema.Reply(200, """{"csrfToken":"csrf-123"}""", mapOf("Set-Cookie" to listOf("__Host-next-auth.csrf-token=csrf-123%7Chash; Path=/; HttpOnly")))
        }
        fake.reply("POST", "/auth/callback/credentials") { _, _ ->
            if (wrongPassword) FakeNeema.Reply(200, """{"url":"https://neema.test/api/auth/error?error=CredentialsSignin&provider=credentials"}""")
            else FakeNeema.Reply(
                200, """{"url":"https://neema.test/dashboard"}""",
                mapOf("Set-Cookie" to listOf("__Secure-next-auth.session-token=SESS-1; Path=/; HttpOnly; Secure")),
            )
        }
        fake.reply("GET", "/auth/session") { req, _ ->
            if (req.header("Cookie")?.contains("next-auth.session-token=SESS") != true) FakeNeema.Reply(200, "{}")
            else FakeNeema.Reply(
                200,
                """{"user":{"id":"a1","email":"moses@bethanyhouse.co.ke"},"accessToken":"$sessionAccess","expires":"2099-01-01T00:00:00Z"}""",
                mapOf("Set-Cookie" to listOf("__Secure-next-auth.session-token=SESS-2; Path=/; HttpOnly; Secure")),
            )
        }
    }

    // ── Login ───────────────────────────────────────────────────────────────

    @Test
    fun directLoginSavesTheFastApiSession() = runBlocking {
        val access = fakeJwt("a1", 3600)
        fake.on("POST", "/agent-auth/login", body = tokens(access))

        val s = auth.login("moses@bethanyhouse.co.ke", "pw")

        assertEquals("direct", s.mode)
        assertEquals(access, s.accessToken)
        assertEquals("r-1", s.refreshToken)
        assertEquals("a1", s.agentId)
        assertEquals("admin", s.role)
        assertTrue(s.isSuperuser)
        assertEquals(s, store.current)
        val body = fake.callsTo("POST", "/agent-auth/login").single().body!!
        assertTrue(body, body.contains("\"email\":\"moses@bethanyhouse.co.ke\"") && body.contains("\"password\":\"pw\""))
        assertFalse("never touches NextAuth when the direct route answers", fake.called("GET", "/auth/csrf"))
    }

    @Test
    fun wrongPasswordOnTheDirectRouteIsFinal() = runBlocking {
        fake.on("POST", "/agent-auth/login", code = 401, body = """{"detail":"Invalid credentials"}""")
        try {
            auth.login("moses@bethanyhouse.co.ke", "nope"); fail("expected AuthException")
        } catch (e: AuthException) {
            assertEquals("Invalid email or password. Please try again.", e.message)
        }
        assertNull(store.current)
        assertFalse("a wrong password must not fall through to NextAuth", fake.called("GET", "/auth/csrf"))
    }

    @Test
    fun invalidEmailShapeIsAWrongPasswordToo() = runBlocking {
        fake.on("POST", "/agent-auth/login", code = 422, body = """{"detail":[{"msg":"value is not a valid email"}]}""")
        try { auth.login("nobody", "pw"); fail() } catch (e: AuthException) { assertTrue(e.message!!.startsWith("Invalid")) }
    }

    @Test
    fun missingDirectRouteFallsBackToNextAuth() = runBlocking {
        val access = fakeJwt("a1", 3600)
        fake.on("POST", "/agent-auth/login", code = 404, body = """{"detail":"Not Found"}""")
        installNextAuth(access)

        val s = auth.login("moses@bethanyhouse.co.ke", "pw")

        assertEquals("nextauth", s.mode)
        assertEquals(access, s.accessToken)
        assertNull("route.ts keeps no refresh token", s.refreshToken)
        assertEquals("a1", s.agentId)
        assertEquals("agent", s.role)
        assertEquals("the session call rotates the cookie", "__Secure-next-auth.session-token=SESS-2", s.nextAuthCookie)
        // The credentials POST carries the csrf token + cookie, as NextAuth's signIn() does.
        val cb = fake.callsTo("POST", "/auth/callback/credentials").single()
        assertTrue(cb.body!!, cb.body!!.contains("csrfToken=csrf-123") && cb.body!!.contains("email=moses%40bethanyhouse.co.ke"))
        assertTrue(cb.headers["Cookie"]!!.contains("__Host-next-auth.csrf-token="))
        assertEquals(s, store.current)
    }

    @Test
    fun anHtmlPageFromTheDirectRouteAlsoFallsBack() = runBlocking {
        fake.on("POST", "/agent-auth/login", body = "<!doctype html><html>Next.js</html>")
        installNextAuth(fakeJwt("a1", 3600))
        assertEquals("nextauth", auth.login("moses@bethanyhouse.co.ke", "pw").mode)
    }

    @Test
    fun nextAuthWrongPassword() = runBlocking {
        fake.on("POST", "/agent-auth/login", code = 405, body = "{}")
        installNextAuth(fakeJwt("a1", 3600), wrongPassword = true)
        try { auth.login("moses@bethanyhouse.co.ke", "nope"); fail() } catch (e: AuthException) {
            assertEquals("Invalid email or password. Please try again.", e.message)
        }
        assertNull(store.current)
    }

    @Test
    fun logoutForgetsTokensButRemembersWhoWasSignedIn() {
        store.save(direct())
        auth.logout()
        assertNull(store.current)
        assertEquals("moses@bethanyhouse.co.ke", store.lastEmail)
    }

    // ── Refresh ─────────────────────────────────────────────────────────────

    @Test
    fun aTokenWithTimeLeftIsUsedAsIs() = runBlocking {
        val s = direct(fakeJwt("a1", 3600)).also(store::save)
        assertEquals(s.accessToken, auth.validAccessToken())
        assertFalse(fake.called("POST", "/agent-auth/refresh"))
    }

    @Test
    fun aTokenInsideTheFiveMinuteBufferIsRefreshedFirst() = runBlocking {
        store.save(direct(fakeJwt("a1", 120)))
        val fresh = fakeJwt("a1", 3600)
        fake.on("POST", "/agent-auth/refresh", body = tokens(fresh, refresh = "r-2"))

        assertEquals(fresh, auth.validAccessToken())

        val body = fake.callsTo("POST", "/agent-auth/refresh").single().body!!
        assertTrue(body, body.contains("\"refresh_token\":\"r-1\""))
        val saved = store.current!!
        assertEquals(fresh, saved.accessToken)
        assertEquals("r-2", saved.refreshToken)
        assertEquals("keeps the profile name", "Moses Mwicigi", saved.name)
        assertEquals("moses@bethanyhouse.co.ke", saved.email)
    }

    @Test
    fun refreshRetriesThreeTimesThenGivesUp() = runBlocking {
        val expiring = fakeJwt("a1", 120)
        store.save(direct(expiring))
        fake.on("POST", "/agent-auth/refresh", code = 401, body = """{"detail":"Invalid refresh token"}""")

        assertNull(auth.forceRefresh())
        assertEquals("doRefresh(): three attempts", 3, fake.callsTo("POST", "/agent-auth/refresh").size)
        // Still unexpired, so it is handed out until the server says otherwise.
        assertEquals(expiring, auth.validAccessToken())
    }

    @Test
    fun anExpiredTokenThatCannotBeRefreshedIsNotHandedOut() = runBlocking {
        store.save(direct(fakeJwt("a1", -60)))
        fake.on("POST", "/agent-auth/refresh", code = 500, body = "{}")
        assertNull(auth.validAccessToken())
    }

    @Test
    fun aRefreshThatSucceedsOnTheSecondTryIsUsed() = runBlocking {
        store.save(direct(fakeJwt("a1", 60)))
        val fresh = fakeJwt("a1", 3600)
        var n = 0
        fake.on("POST", "/agent-auth/refresh") { _, _ -> if (++n == 1) 502 to "bad gateway" else 200 to tokens(fresh) }
        assertEquals(fresh, auth.forceRefresh())
        assertEquals(2, n)
    }

    @Test
    fun aRejectedButUnexpiredTokenIsRefreshedAnyway() = runBlocking {
        val revoked = fakeJwt("a1", 3600)
        store.save(direct(revoked))
        val fresh = fakeJwt("a2", 3600)
        fake.on("POST", "/agent-auth/refresh", body = tokens(fresh))

        auth.onRejected(revoked)
        assertEquals(fresh, auth.forceRefresh())
    }

    @Test
    fun concurrentCallersShareOneRefresh() = runBlocking {
        store.save(direct(fakeJwt("a1", 30)))
        val fresh = fakeJwt("a1", 3600)
        fake.on("POST", "/agent-auth/refresh", body = tokens(fresh))

        val got = (1..5).map { async(kotlinx.coroutines.Dispatchers.IO) { auth.validAccessToken() } }.awaitAll()

        assertTrue(got.all { it == fresh })
        assertEquals(1, fake.callsTo("POST", "/agent-auth/refresh").size)
    }

    @Test
    fun nextAuthSessionsRefreshThroughTheSessionEndpoint() = runBlocking {
        val fresh = fakeJwt("a1", 3600)
        installNextAuth(fresh)
        store.save(
            direct(fakeJwt("a1", 60)).copy(refreshToken = null, mode = "nextauth", nextAuthCookie = "__Secure-next-auth.session-token=SESS-1"),
        )

        assertEquals(fresh, auth.validAccessToken())
        assertEquals("__Secure-next-auth.session-token=SESS-2", store.current!!.nextAuthCookie)
        assertEquals("nextauth", store.current!!.mode)
    }

    @Test
    fun nextAuthHandingBackTheRefusedTokenIsNoRescue() = runBlocking {
        val stale = fakeJwt("a1", 3600)
        installNextAuth(stale)
        store.save(direct(stale).copy(refreshToken = null, mode = "nextauth", nextAuthCookie = "__Secure-next-auth.session-token=SESS-1"))

        auth.onRejected(stale)
        assertNull(auth.forceRefresh())
    }

    @Test
    fun noSessionMeansNoToken() = runBlocking {
        assertNull(auth.validAccessToken())
        assertNull(auth.forceRefresh())
        assertTrue(fake.calls.isEmpty())
    }

    // ── Round 3: the contract of routers/auth.py and NextAuth v4 ─────────────

    @Test
    fun theOriginalFastApiMountIsTriedBeforeNextAuth() = runBlocking {
        // nginx.conf sends every /api/ path to FastAPI, so /api/auth/login is FastAPI there.
        val access = fakeJwt("a1", 3600)
        fake.on("POST", "/agent-auth/login", code = 404, body = """{"detail":"Not Found"}""")
        fake.on("POST", "/auth/login", body = tokens(access, role = "agent", superuser = false))

        val s = auth.login("grace@bethanyhouse.co.ke", "pw")

        assertEquals("direct", s.mode)
        assertEquals(access, s.accessToken)
        assertEquals("agent", s.role)
        assertFalse(s.isSuperuser)
        assertFalse(fake.called("GET", "/auth/csrf"))
    }

    @Test
    fun aWrongPasswordOnTheOriginalMountIsFinalToo() = runBlocking {
        fake.on("POST", "/agent-auth/login", code = 404, body = """{"detail":"Not Found"}""")
        fake.on("POST", "/auth/login", code = 401, body = """{"detail":"Invalid credentials"}""")
        try { auth.login("g@b.co", "nope"); fail() } catch (e: AuthException) { assertTrue(e.message!!.startsWith("Invalid")) }
        assertFalse(fake.called("GET", "/auth/csrf"))
    }

    @Test
    fun nextAuthsPlainTextAnswerToALoginPostFallsThrough() = runBlocking {
        // v4 answers an unknown action with a 400 text body, not JSON.
        fake.on("POST", "/agent-auth/login", code = 404, body = """{"detail":"Not Found"}""")
        fake.on("POST", "/auth/login", code = 400, body = "Error: This action with HTTP POST is not supported by NextAuth.js")
        installNextAuth(fakeJwt("a1", 3600))
        assertEquals("nextauth", auth.login("moses@bethanyhouse.co.ke", "pw").mode)
    }

    @Test
    fun aServerErrorIsNotReportedAsAWrongPassword() = runBlocking {
        fake.on("POST", "/agent-auth/login", code = 500, body = """{"detail":"Internal Server Error"}""")
        try { auth.login("moses@bethanyhouse.co.ke", "pw"); fail() } catch (e: AuthException) {
            assertEquals("Sign-in is unavailable right now. Please try again shortly.", e.message)
        }
        assertFalse("NextAuth would only relay the same failure", fake.called("GET", "/auth/csrf"))
    }

    @Test
    fun aTokenResponseWithoutATokenIsNotASession() = runBlocking {
        fake.on("POST", "/agent-auth/login", body = """{"ok":true}""")
        fake.on("POST", "/auth/login", body = """{"ok":true}""")
        installNextAuth(fakeJwt("a1", 3600))
        assertEquals("nextauth", auth.login("moses@bethanyhouse.co.ke", "pw").mode)
    }

    @Test
    fun refreshFallsBackToTheOriginalMount() = runBlocking {
        store.save(direct(fakeJwt("a1", 60)))
        val fresh = fakeJwt("a1", 3600)
        fake.on("POST", "/agent-auth/refresh", code = 404, body = """{"detail":"Not Found"}""")
        fake.on("POST", "/auth/refresh", body = tokens(fresh, refresh = "r-9"))
        assertEquals(fresh, auth.forceRefresh())
        assertEquals("r-9", store.current!!.refreshToken)
        assertTrue(fake.callsTo("POST", "/auth/refresh").single().body!!.contains("\"refresh_token\":\"r-1\""))
    }

    @Test
    fun aDeletedAgentsRefreshIsARealAnswer() = runBlocking {
        // refresh(): 404 "Agent not found" is the server speaking, not a missing route.
        store.save(direct(fakeJwt("a1", 60)))
        fake.on("POST", "/agent-auth/refresh", code = 404, body = """{"detail":"Agent not found"}""")
        assertNull(auth.forceRefresh())
        assertFalse(fake.called("POST", "/auth/refresh"))
    }

    @Test
    fun aRefreshKeepsTheRoleTheServerNowReports() = runBlocking {
        store.save(direct(fakeJwt("a1", 60)))
        fake.on("POST", "/agent-auth/refresh", body = tokens(fakeJwt("a1", 3600), role = "readonly", superuser = false))
        auth.forceRefresh()
        assertEquals("readonly", store.current!!.role)
        assertFalse(store.current!!.isSuperuser)
    }

    @Test
    fun chunkedNextAuthSessionCookiesAreAllSent() = runBlocking {
        val access = fakeJwt("a1", 3600)
        fake.on("POST", "/agent-auth/login", code = 404, body = """{"detail":"Not Found"}""")
        fake.reply("GET", "/auth/csrf") { _, _ ->
            FakeNeema.Reply(200, """{"csrfToken":"c"}""", mapOf("Set-Cookie" to listOf("__Host-next-auth.csrf-token=c%7Ch; Path=/")))
        }
        fake.reply("POST", "/auth/callback/credentials") { _, _ ->
            FakeNeema.Reply(302, "", mapOf(
                "Location" to listOf("https://neema.test/dashboard"),
                "Set-Cookie" to listOf(
                    "__Secure-next-auth.session-token.0=PART-A; Path=/; HttpOnly; Secure",
                    "__Secure-next-auth.session-token.1=PART-B; Path=/; HttpOnly; Secure",
                    "__Secure-next-auth.callback-url=https%3A%2F%2Fneema.test; Path=/",
                ),
            ))
        }
        var seen = ""
        fake.reply("GET", "/auth/session") { req, _ ->
            seen = req.header("Cookie").orEmpty()
            FakeNeema.Reply(200, """{"user":{"email":"moses@bethanyhouse.co.ke","id":"a1"},"expires":"2099-01-01T00:00:00.000Z","accessToken":"$access"}""",
                // v4 re-issues the session: here it now fits one cookie, and the chunk is cleared.
                mapOf("Set-Cookie" to listOf(
                    "__Secure-next-auth.session-token=WHOLE; Path=/; HttpOnly; Secure",
                    "__Secure-next-auth.session-token.0=; Max-Age=0; Path=/",
                    "__Secure-next-auth.session-token.1=; Max-Age=0; Path=/",
                )))
        }

        val s = auth.login("moses@bethanyhouse.co.ke", "pw")

        assertEquals("__Secure-next-auth.session-token.0=PART-A; __Secure-next-auth.session-token.1=PART-B", seen)
        assertEquals("__Secure-next-auth.session-token=WHOLE", s.nextAuthCookie)
        assertEquals(access, s.accessToken)
        assertEquals("route.ts sends no name: the email stands in", "moses@bethanyhouse.co.ke", s.name)
    }

    @Test
    fun aStaleCsrfIsNotAWrongPassword() = runBlocking {
        fake.on("POST", "/agent-auth/login", code = 404, body = """{"detail":"Not Found"}""")
        installNextAuth(fakeJwt("a1", 3600))
        fake.reply("POST", "/auth/callback/credentials") { _, _ -> FakeNeema.Reply(200, """{"url":"https://neema.test/api/auth/signin?csrf=true"}""") }
        try { auth.login("moses@bethanyhouse.co.ke", "pw"); fail() } catch (e: AuthException) {
            assertEquals("Sign-in is unavailable right now. Please try again shortly.", e.message)
        }
    }

    @Test
    fun aNextAuthRefreshKeepsTheRoleFromAdminMe() = runBlocking {
        val fresh = fakeJwt("a1", 3600)
        installNextAuth(fresh)
        store.save(direct(fakeJwt("a1", 60)).copy(refreshToken = null, mode = "nextauth", nextAuthCookie = "__Secure-next-auth.session-token=SESS-1"))
        auth.updateProfile("Moses Mwicigi", "moses@bethanyhouse.co.ke", role = "admin", isSuperuser = true)
        assertEquals(fresh, auth.forceRefresh())
        assertEquals("the session payload has no role; /admin/me's stays", "admin", store.current!!.role)
        assertTrue(store.current!!.isSuperuser)
    }

    @Test
    fun updateProfileTakesRoleAndSuperuserWhenGiven() {
        store.save(direct().copy(role = "agent", isSuperuser = false, mode = "nextauth"))
        auth.updateProfile("Moses M.", "m@b.co")
        assertEquals("agent", store.current!!.role)
        auth.updateProfile("Moses M.", "m@b.co", role = "admin", isSuperuser = true)
        assertEquals("admin", store.current!!.role)
        assertTrue(store.current!!.isSuperuser)
        assertEquals("Moses M.", store.current!!.name)
    }

    @Test
    fun jwtClaimsAreReadWithoutVerifying() {
        val t = fakeJwt("agent-9", 100)
        assertEquals("agent-9", AuthRepository.jwtSub(t))
        assertNotEquals(0L, AuthRepository.jwtExp(t))
        assertEquals(0L, AuthRepository.jwtExp("not-a-jwt"))
        assertNull(AuthRepository.jwtSub("a.b.c"))
    }
}
