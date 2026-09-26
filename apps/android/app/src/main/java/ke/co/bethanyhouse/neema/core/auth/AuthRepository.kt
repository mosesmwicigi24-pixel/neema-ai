package ke.co.bethanyhouse.neema.core.auth

import ke.co.bethanyhouse.neema.core.util.AppClock

import ke.co.bethanyhouse.neema.BuildConfig
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.net.RefreshUnavailable
import ke.co.bethanyhouse.neema.core.net.TokenProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import java.io.IOException
import java.io.InterruptedIOException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.longOrNull
import kotlinx.serialization.json.put
import okhttp3.FormBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

class AuthException(message: String) : Exception(message)

/**
 * Sign-in and silent refresh.
 *
 * The web signs in through NextAuth, whose server calls FastAPI's
 * `POST /api/auth/login` (routers/auth.py `login`) internally. Which process
 * answers `/api/auth/…` on the public origin depends on the proxy: the repo's
 * nginx.conf sends every `/api/` path to FastAPI, while a deployment that
 * serves the web first hands `/api/auth/` to NextAuth. So the app tries, in
 * order:
 *
 *  1. `POST /api/agent-auth/login` — the same FastAPI auth router, mounted a
 *     second time under a path NextAuth never claims (main.py);
 *  2. `POST /api/auth/login` — FastAPI's original mount, for a server that
 *     predates (1) behind a proxy that routes `/api/` to FastAPI;
 *  3. NextAuth v4's credentials flow — `GET /api/auth/csrf` → `POST
 *     /api/auth/callback/credentials` → `GET /api/auth/session`, whose session
 *     carries `accessToken`. The route actually served
 *     (app/api/auth/[...nextauth]/route.ts — lib/auth.ts is not mounted) keeps
 *     no refresh token, no role and no superuser flag: the role comes from
 *     `/admin/me` once signed in (see [updateProfile]).
 *
 * FastAPI answers `{access_token, refresh_token, token_type, agent_id, role,
 * is_superuser}` (schemas/auth.py TokenResponse); a wrong password is 401
 * `{"detail":"Invalid credentials"}`, a malformed body 422.
 */
class AuthRepository(
    private val store: SessionStore,
    private val base: String = BuildConfig.NEEMA_BASE_URL,
    /** Tests only: answers requests without the network. */
    interceptor: okhttp3.Interceptor? = null,
    /** Pause between refresh attempts (attempt × this), as lib/auth.ts doRefresh(). */
    private val backoffMs: Long = 500,
    /** Where the blocking calls run; tests pass Unconfined so a refresh settles in-line. */
    private val io: kotlinx.coroutines.CoroutineDispatcher = Dispatchers.IO,
) : TokenProvider {
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        .followRedirects(false)
        .apply { if (interceptor != null) addInterceptor(interceptor) }
        .build()
    private val json = "application/json".toMediaType()
    private val refreshLock = Mutex()

    /**
     * Every failure is an [AuthException] whose message is meant for people:
     * a wrong password, the server failing, too many attempts, no network,
     * or a timeout each say which.
     */
    suspend fun login(email: String, password: String): Session = withContext(io) {
        try {
            for (prefix in DIRECT_PREFIXES) {
                val direct = runCatching { directLogin(prefix, email, password) }
                direct.getOrNull()?.let { return@withContext it.also(store::save) }
                // Wrong password is final; only "route not there" falls through.
                val err = direct.exceptionOrNull()
                if (err !is RouteMissing) throw err!!
            }
            nextAuthLogin(email, password).also(store::save)
        } catch (e: RefreshUnavailable) {
            throw AuthException(
                when {
                    e.timedOut -> TIMED_OUT
                    e.status == 0 -> OFFLINE
                    e.status == 429 -> TOO_MANY
                    else -> UNAVAILABLE
                },
            )
        } catch (e: IOException) {
            throw AuthException(if (e is InterruptedIOException) TIMED_OUT else OFFLINE)
        }
    }

    /**
     * Run one auth call. No answer at all (offline, refused, dropped, timed
     * out) becomes [RefreshUnavailable] with status 0, so callers can tell it
     * from the server refusing.
     */
    private fun exec(req: Request): okhttp3.Response = try {
        http.newCall(req).execute()
    } catch (e: InterruptedIOException) {
        throw RefreshUnavailable(0, true, "timed out")
    } catch (e: IOException) {
        throw RefreshUnavailable(0, false, e.message ?: "network error")
    }

    /** The server is up but can't serve this now: a 5xx, a 429, a 408. Never a verdict on the session. */
    private fun transient(code: Int) = code >= 500 || code == 429 || code == 408

    fun logout() = store.clear()

    // ── Direct FastAPI ──────────────────────────────────────────────────────

    /** This path isn't FastAPI's auth router (not deployed, or another app answers it). */
    private class RouteMissing : Exception()

    /**
     * FastAPI's own "no such route" (`{"detail":"Not Found"}` 404 /
     * `{"detail":"Method Not Allowed"}` 405) or any page that isn't JSON (a
     * proxy error page, NextAuth's plain-text 400). A 404 whose detail is
     * anything else — "Agent not found" from `refresh` — is a real answer.
     */
    private fun routeMissing(code: Int, text: String): Boolean {
        if (!text.trimStart().startsWith("{")) return true
        if (code != 404 && code != 405) return false
        val detail = runCatching { (NeemaJson.parseToJsonElement(text).jsonObject["detail"] as? JsonPrimitive)?.contentOrNull }.getOrNull()
        return detail == null || detail == "Not Found" || detail == "Method Not Allowed"
    }

    private fun directLogin(prefix: String, email: String, password: String): Session {
        val body = buildJsonObject { put("email", email); put("password", password) }.toString()
        val req = Request.Builder().url("$base/api/$prefix/login")
            .post(body.toRequestBody(json)).build()
        exec(req).use { r ->
            val text = r.body?.string().orEmpty()
            // Too many attempts, or a gateway with nothing behind it: final,
            // whatever page came with it — NextAuth would only relay the same.
            if (r.code == 429) throw AuthException(TOO_MANY)
            if (r.code in 502..504) throw AuthException(UNAVAILABLE)
            if (routeMissing(r.code, text)) throw RouteMissing()
            if (r.code == 401 || r.code == 422) throw AuthException(INVALID)
            // A 5xx here is the API itself failing — NextAuth would only relay the same failure.
            if (!r.isSuccessful) throw AuthException(UNAVAILABLE)
            val o = runCatching { NeemaJson.parseToJsonElement(text).jsonObject }.getOrNull() ?: throw RouteMissing()
            if (o.str("access_token") == null) throw RouteMissing()
            return sessionFromTokens(o, email, mode = "direct", cookie = null)
        }
    }

    /**
     * `POST …/refresh {refresh_token}` → a new pair. Null when the server
     * refused it (401 "Invalid refresh token", 404 "Agent not found") or no
     * auth router answered. Throws [RefreshUnavailable] when it could not be
     * asked: no answer, or a 5xx / 429 (even as a proxy's HTML page).
     */
    private fun directRefresh(refresh: String): Session? {
        val body = buildJsonObject { put("refresh_token", refresh) }.toString()
        for (prefix in DIRECT_PREFIXES) {
            val req = Request.Builder().url("$base/api/$prefix/refresh")
                .post(body.toRequestBody(json)).build()
            val o = exec(req).use { r ->
                val text = r.body?.string().orEmpty()
                if (transient(r.code)) throw RefreshUnavailable(r.code, false, "auth server answered ${r.code}")
                if (routeMissing(r.code, text)) return@use null
                if (!r.isSuccessful) return null
                // A 2xx that isn't JSON (a captive portal's page) proves nothing about the session.
                runCatching { NeemaJson.parseToJsonElement(text).jsonObject }.getOrNull()
                    ?: throw RefreshUnavailable(0, false, "unreadable refresh answer")
            } ?: continue
            if (o.str("access_token") == null) return null
            val cur = store.current
            return sessionFromTokens(o, cur?.email ?: "", "direct", null).copy(
                name = cur?.name ?: "", email = cur?.email ?: "",
            )
        }
        // This session came from one of these routes, so neither answering as
        // FastAPI is a network in the way (a captive portal's page or
        // redirect), not a refused session.
        throw RefreshUnavailable(0, false, "no auth route answered")
    }

    private fun sessionFromTokens(o: JsonObject, email: String, mode: String, cookie: String?): Session {
        val access = o.str("access_token") ?: throw AuthException(UNAVAILABLE)
        return Session(
            accessToken = access,
            refreshToken = o.str("refresh_token"),
            agentId = o.str("agent_id") ?: jwtSub(access) ?: "",
            email = email,
            name = email,
            role = o.str("role") ?: "agent",
            isSuperuser = o.bool("is_superuser") ?: false,
            mode = mode,
            nextAuthCookie = cookie,
        )
    }

    // ── NextAuth bridge ─────────────────────────────────────────────────────

    private fun nextAuthLogin(email: String, password: String): Session {
        val jar = linkedMapOf<String, String>()
        fun absorb(r: okhttp3.Response) = mergeSetCookies(jar, r.headers("Set-Cookie"))

        val csrf = exec(Request.Builder().url("$base/api/auth/csrf").build()).use { r ->
            absorb(r)
            val text = r.body?.string().orEmpty()
            if (r.code == 429) throw AuthException(TOO_MANY)
            if (!r.isSuccessful) throw AuthException(UNAVAILABLE)
            runCatching { NeemaJson.parseToJsonElement(text).jsonObject.str("csrfToken") }.getOrNull()
                ?: throw AuthException(UNAVAILABLE)
        }
        // What next-auth/react signIn("credentials", {redirect:false}) posts.
        val form = FormBody.Builder()
            .add("csrfToken", csrf).add("email", email).add("password", password)
            .add("json", "true").add("callbackUrl", "$base/dashboard").build()
        exec(
            Request.Builder().url("$base/api/auth/callback/credentials")
                .header("Cookie", cookieHeader(jar)).post(form).build(),
        ).use { r ->
            absorb(r)
            // The web app itself failing (NextAuth's authorize() threw on a
            // FastAPI outage) is not a wrong password.
            if (r.code == 429) throw AuthException(TOO_MANY)
            if (r.code >= 500) throw AuthException(UNAVAILABLE)
            // v4 answers {url} (json=true) or a 302; a failed authorize() points
            // at …/error?error=CredentialsSignin, a stale csrf at …?csrf=true.
            val loc = r.header("Location").orEmpty() + r.body?.string().orEmpty()
            if (loc.contains("error=")) throw AuthException(INVALID)
            if (loc.contains("csrf=true")) throw AuthException(UNAVAILABLE)
        }
        val session = sessionCookies(jar)
        if (session.isEmpty()) throw AuthException(INVALID)
        // Signed in, but the session endpoint is failing: say so, not "wrong password".
        return try {
            nextAuthSession(cookieHeader(session), email)
        } catch (e: RefreshUnavailable) {
            if (e.status == 0) throw e
            throw AuthException(if (e.status == 429) TOO_MANY else UNAVAILABLE)
        } ?: throw AuthException(INVALID)
    }

    /**
     * GET /api/auth/session with the session cookie. v4 answers `{}` when the
     * cookie is gone, else `{user:{name?,email,image?,id}, expires,
     * accessToken}` — and re-issues the session cookie (a new expiry, maybe
     * split into `.0`/`.1` chunks), which is merged back in.
     */
    private fun nextAuthSession(cookie: String, email: String): Session? {
        val req = Request.Builder().url("$base/api/auth/session").header("Cookie", cookie).build()
        return exec(req).use { r ->
            if (transient(r.code)) throw RefreshUnavailable(r.code, false, "session endpoint answered ${r.code}")
            if (!r.isSuccessful) return null
            val jar = parseCookieHeader(cookie)
            mergeSetCookies(jar, r.headers("Set-Cookie"))
            val newCookie = cookieHeader(sessionCookies(jar)).ifEmpty { cookie }
            val o = runCatching { NeemaJson.parseToJsonElement(r.body?.string().orEmpty().ifBlank { "{}" }).jsonObject }
                .getOrNull() ?: return null
            if (o.str("error") != null) return null
            val access = o.str("accessToken") ?: return null
            val user = o["user"] as? JsonObject
            Session(
                accessToken = access,
                refreshToken = o.str("refreshToken"),
                agentId = user?.str("id") ?: jwtSub(access) ?: "",
                email = user?.str("email") ?: email,
                name = user?.str("name") ?: email,
                role = o.str("role") ?: (user?.str("role")) ?: "agent",
                isSuperuser = user?.bool("isSuperuser") ?: false,
                mode = "nextauth",
                nextAuthCookie = newCookie,
            )
        }
    }

    // ── TokenProvider ───────────────────────────────────────────────────────

    override suspend fun validAccessToken(): String? {
        val s = store.current ?: return null
        val left = jwtExp(s.accessToken) - AppClock.now() / 1000
        // Same 5-minute buffer the web's jwt() callback uses.
        if (left > 300) return s.accessToken
        // The auth server just failed to answer: while the token still works,
        // don't make every request wait out another round of attempts.
        if (left > 0 && AppClock.now() < unavailableUntil) return s.accessToken
        return try {
            forceRefresh() ?: s.accessToken.takeIf { left > 0 }
        } catch (e: RefreshUnavailable) {
            // Still unexpired: use it; the server is the judge. Expired: the
            // request would only bounce, so it fails as the outage it is.
            if (left > 0) s.accessToken else throw e
        }
    }

    /**
     * One refresh for everyone: callers queue on a lock, and whoever comes
     * second finds the new token already stored. Up to three attempts
     * (lib/auth.ts doRefresh) while the auth server can't answer; a refusal
     * is final at once, and so is a timeout (three of those would hold every
     * request for 90 s). A refusal is remembered for that token, so a burst of
     * 401s after it asks the server once, not once each.
     */
    override suspend fun forceRefresh(): String? = refreshLock.withLock {
        withContext(io) {
            val s = store.current ?: return@withContext null
            // Another caller may have refreshed while we waited for the lock.
            if (jwtExp(s.accessToken) - AppClock.now() / 1000 > 300 &&
                s.accessToken != lastRejected
            ) return@withContext s.accessToken
            if (s.accessToken == refusedFor) return@withContext null
            var fresh: Session? = null
            var outage: RefreshUnavailable? = null
            for (attempt in 1..3) {
                outage = null
                fresh = try { refreshOnce(s) } catch (e: RefreshUnavailable) { outage = e; null }
                // NextAuth may hand back the very token the API just refused
                // (its session callback doesn't always refresh): that is no rescue.
                if (fresh != null && fresh.accessToken == s.accessToken &&
                    (s.accessToken == lastRejected || jwtExp(s.accessToken) <= AppClock.now() / 1000)
                ) fresh = null
                val retry = fresh == null && outage != null && !outage.timedOut && attempt < 3
                if (!retry) break
                if (backoffMs > 0) delay(attempt * backoffMs)
            }
            if (fresh == null) {
                outage?.let {
                    unavailableUntil = AppClock.now() + UNAVAILABLE_COOLDOWN_MS
                    throw it
                }
                lastRejected = s.accessToken
                refusedFor = s.accessToken
                return@withContext null
            }
            unavailableUntil = 0
            val merged = fresh.copy(
                name = s.name.ifBlank { fresh.name },
                email = s.email.ifBlank { fresh.email },
                nextAuthCookie = fresh.nextAuthCookie ?: s.nextAuthCookie,
                refreshToken = fresh.refreshToken ?: s.refreshToken,
                // NextAuth's session carries no role: keep what /admin/me told us.
                role = if (fresh.mode == "nextauth") s.role else fresh.role,
                isSuperuser = if (fresh.mode == "nextauth") s.isSuperuser else fresh.isSuperuser,
            )
            store.save(merged)
            merged.accessToken
        }
    }

    /**
     * One try through every refresh path this session has: FastAPI's
     * refresh token, then NextAuth's session cookie. Null when refused;
     * [RefreshUnavailable] when none could give an answer either way.
     */
    private fun refreshOnce(s: Session): Session? {
        var outage: RefreshUnavailable? = null
        fun attempt(block: () -> Session?): Session? = try {
            block()
        } catch (e: RefreshUnavailable) {
            outage = outage ?: e; null
        } catch (e: IOException) {
            // The body cut off mid-stream.
            outage = outage ?: RefreshUnavailable(0, e is InterruptedIOException, e.message ?: "network error"); null
        }
        s.refreshToken?.let { rt -> attempt { directRefresh(rt) }?.let { return it } }
        s.nextAuthCookie?.let { c -> attempt { nextAuthSession(c, s.email) }?.let { return it } }
        outage?.let { throw it }
        return null
    }

    @Volatile private var lastRejected: String? = null
    /** The access token whose refresh the server refused — asking again is pointless. */
    @Volatile private var refusedFor: String? = null
    /** Until when proactive refreshes are skipped after the auth server failed to answer. */
    @Volatile private var unavailableUntil = 0L

    /** Called after a 401 so forceRefresh() doesn't trust an unexpired-but-revoked token. */
    override fun onRejected(token: String?) { lastRejected = token }

    /**
     * The signed-in agent as `/admin/me` describes them. Name and email always;
     * role and superuser too when given — a NextAuth sign-in carries neither,
     * and an admin must not be shown an agent's app until the first refresh.
     */
    fun updateProfile(name: String, email: String, role: String? = null, isSuperuser: Boolean? = null) {
        store.current?.let {
            val next = it.copy(
                name = name, email = email,
                role = role?.takeIf { r -> r.isNotBlank() } ?: it.role,
                isSuperuser = isSuperuser ?: it.isSuperuser,
            )
            if (next != it) store.save(next)
        }
    }

    companion object {
        /** FastAPI's auth router mounts, newest first (main.py). */
        private val DIRECT_PREFIXES = listOf("agent-auth", "auth")

        private const val UNAVAILABLE_COOLDOWN_MS = 30_000L

        // What sign-in says, for people.
        const val INVALID = "Invalid email or password. Please try again."
        const val UNAVAILABLE = "Sign-in is unavailable right now. Please try again shortly."
        const val TOO_MANY = "Too many sign-in attempts. Please wait a minute and try again."
        const val OFFLINE = "Can't reach Neema. Check your internet connection and try again."
        const val TIMED_OUT = "Neema is taking too long to answer. Check your connection and try again."

        private fun JsonObject.str(k: String): String? = (this[k] as? JsonPrimitive)?.contentOrNull
        private fun JsonObject.bool(k: String): Boolean? = (this[k] as? JsonPrimitive)?.booleanOrNull

        private fun claims(jwt: String): JsonObject? = runCatching {
            val part = jwt.split(".")[1]
            // java.util (not android.util) so it also runs in plain JVM tests.
            val bytes = java.util.Base64.getUrlDecoder().decode(part.trimEnd('='))
            NeemaJson.parseToJsonElement(String(bytes)).jsonObject
        }.getOrNull()

        fun jwtExp(jwt: String): Long = (claims(jwt)?.get("exp") as? JsonPrimitive)?.longOrNull ?: 0L
        fun jwtSub(jwt: String): String? = claims(jwt)?.str("sub")

        // ── Cookies (just enough of RFC 6265 for NextAuth) ──────────────────

        /** Apply Set-Cookie headers: a new value replaces, an empty value or Max-Age=0 deletes. */
        internal fun mergeSetCookies(jar: MutableMap<String, String>, setCookies: List<String>) {
            setCookies.forEach { c ->
                val kv = c.substringBefore(';').trim()
                val k = kv.substringBefore('=').trim()
                if (k.isEmpty()) return@forEach
                val v = kv.substringAfter('=', "")
                val attrs = c.substringAfter(';', "").lowercase()
                val expired = Regex("max-age=\\s*(-?\\d+)").find(attrs)?.groupValues?.get(1)?.toLongOrNull()?.let { it <= 0 } == true
                if (v.isEmpty() || expired) jar.remove(k) else jar[k] = v
            }
        }

        internal fun parseCookieHeader(header: String): LinkedHashMap<String, String> =
            header.split(';').map { it.trim() }.filter { it.contains('=') }
                .associateTo(LinkedHashMap()) { it.substringBefore('=') to it.substringAfter('=') }

        internal fun cookieHeader(jar: Map<String, String>): String =
            jar.entries.joinToString("; ") { "${it.key}=${it.value}" }

        /**
         * The session cookie under any of its names — `next-auth.session-token`,
         * `__Secure-next-auth.session-token` on https — including the `.0`,
         * `.1` chunks v4 splits a large token into.
         */
        internal fun sessionCookies(jar: Map<String, String>): LinkedHashMap<String, String> =
            jar.filterKeysTo(LinkedHashMap()) { k ->
                k.endsWith("next-auth.session-token") || Regex("next-auth\\.session-token\\.\\d+$").containsMatchIn(k)
            }

        private fun <V> Map<String, V>.filterKeysTo(dest: LinkedHashMap<String, V>, keep: (String) -> Boolean) =
            dest.also { d -> forEach { (k, v) -> if (keep(k)) d[k] = v } }
    }
}
