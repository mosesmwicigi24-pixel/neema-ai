package ke.co.bethanyhouse.neema.core.auth

import android.util.Base64
import ke.co.bethanyhouse.neema.BuildConfig
import ke.co.bethanyhouse.neema.core.net.NeemaJson
import ke.co.bethanyhouse.neema.core.net.TokenProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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
 * `/api/auth/login` internally. In production `/api/auth/` on the public
 * origin belongs to NextAuth, so the app tries, in order:
 *
 *  1. `/api/agent-auth/login` — FastAPI's auth router, mounted a second time
 *     under a path NextAuth doesn't claim (added alongside this app);
 *  2. NextAuth's own credentials flow — csrf → callback → session, whose
 *     session payload already carries `accessToken`/`refreshToken`. This keeps
 *     the app working against a server that hasn't deployed (1) yet.
 */
class AuthRepository(private val store: SessionStore) : TokenProvider {
    private val base = BuildConfig.NEEMA_BASE_URL
    private val http = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .callTimeout(30, TimeUnit.SECONDS)
        .followRedirects(false)
        .build()
    private val json = "application/json".toMediaType()
    private val refreshLock = Mutex()

    suspend fun login(email: String, password: String): Session = withContext(Dispatchers.IO) {
        val direct = runCatching { directLogin(email, password) }
        direct.getOrNull()?.let { return@withContext it.also(store::save) }
        val err = direct.exceptionOrNull()
        // Wrong password is final; only "route not there" falls through.
        if (err is AuthException) throw err
        nextAuthLogin(email, password).also(store::save)
    }

    fun logout() = store.clear()

    // ── Direct FastAPI ──────────────────────────────────────────────────────

    private class RouteMissing : Exception()

    private fun directLogin(email: String, password: String): Session {
        val body = buildJsonObject { put("email", email); put("password", password) }.toString()
        val req = Request.Builder().url("$base/api/agent-auth/login")
            .post(body.toRequestBody(json)).build()
        http.newCall(req).execute().use { r ->
            val text = r.body?.string().orEmpty()
            if (r.code == 404 || r.code == 405 || !text.trimStart().startsWith("{")) throw RouteMissing()
            if (r.code == 401 || r.code == 422) throw AuthException("Invalid email or password. Please try again.")
            if (!r.isSuccessful) throw RouteMissing()
            val o = NeemaJson.parseToJsonElement(text).jsonObject
            return sessionFromTokens(o, email, mode = "direct", cookie = null)
        }
    }

    private fun directRefresh(refresh: String): Session? {
        val body = buildJsonObject { put("refresh_token", refresh) }.toString()
        val req = Request.Builder().url("$base/api/agent-auth/refresh")
            .post(body.toRequestBody(json)).build()
        return http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) return null
            val o = NeemaJson.parseToJsonElement(r.body?.string().orEmpty()).jsonObject
            val cur = store.current
            sessionFromTokens(o, cur?.email ?: "", "direct", null).copy(
                name = cur?.name ?: "", email = cur?.email ?: "",
            )
        }
    }

    private fun sessionFromTokens(o: JsonObject, email: String, mode: String, cookie: String?): Session {
        val access = o.str("access_token") ?: throw AuthException("Login failed — no token returned")
        return Session(
            accessToken = access,
            refreshToken = o.str("refresh_token"),
            agentId = o.str("agent_id") ?: jwtSub(access) ?: "",
            email = email,
            name = email,
            role = o.str("role") ?: "agent",
            isSuperuser = o["is_superuser"]?.jsonPrimitive?.booleanOrNull ?: false,
            mode = mode,
            nextAuthCookie = cookie,
        )
    }

    // ── NextAuth bridge ─────────────────────────────────────────────────────

    private fun nextAuthLogin(email: String, password: String): Session {
        val jar = linkedMapOf<String, String>()
        fun absorb(r: okhttp3.Response) = r.headers("Set-Cookie").forEach { c ->
            val kv = c.substringBefore(';'); val k = kv.substringBefore('=')
            jar[k] = kv.substringAfter('=')
        }
        fun cookieHeader() = jar.entries.joinToString("; ") { "${it.key}=${it.value}" }

        val csrf = http.newCall(Request.Builder().url("$base/api/auth/csrf").build()).execute().use { r ->
            absorb(r)
            if (!r.isSuccessful) throw AuthException("Can't reach Neema — check your connection.")
            NeemaJson.parseToJsonElement(r.body?.string().orEmpty()).jsonObject.str("csrfToken")
                ?: throw AuthException("Sign-in is unavailable right now.")
        }
        val form = FormBody.Builder()
            .add("csrfToken", csrf).add("email", email).add("password", password)
            .add("json", "true").add("callbackUrl", "$base/dashboard").build()
        http.newCall(
            Request.Builder().url("$base/api/auth/callback/credentials")
                .header("Cookie", cookieHeader()).post(form).build(),
        ).execute().use { r ->
            absorb(r)
            val loc = r.header("Location").orEmpty() + r.body?.string().orEmpty()
            if (loc.contains("error=")) throw AuthException("Invalid email or password. Please try again.")
        }
        val sessionCookie = jar.keys.firstOrNull { it.endsWith("next-auth.session-token") }
            ?: throw AuthException("Invalid email or password. Please try again.")
        return nextAuthSession("$sessionCookie=${jar[sessionCookie]}", email)
            ?: throw AuthException("Invalid email or password. Please try again.")
    }

    /** GET /api/auth/session — NextAuth refreshes the FastAPI tokens itself when they near expiry. */
    private fun nextAuthSession(cookie: String, email: String): Session? {
        val req = Request.Builder().url("$base/api/auth/session").header("Cookie", cookie).build()
        return http.newCall(req).execute().use { r ->
            if (!r.isSuccessful) return null
            var newCookie = cookie
            r.headers("Set-Cookie").firstOrNull { it.contains("next-auth.session-token") }?.let {
                newCookie = it.substringBefore(';')
            }
            val o = NeemaJson.parseToJsonElement(r.body?.string().orEmpty().ifBlank { "{}" }).jsonObject
            if (o.str("error") != null) return null
            val access = o.str("accessToken") ?: return null
            val user = o["user"] as? JsonObject
            Session(
                accessToken = access,
                refreshToken = o.str("refreshToken"),
                agentId = user?.str("id") ?: jwtSub(access) ?: "",
                email = user?.str("email") ?: email,
                name = user?.str("name") ?: email,
                role = o.str("role") ?: "agent",
                isSuperuser = (user?.get("isSuperuser"))?.jsonPrimitive?.booleanOrNull ?: false,
                mode = "nextauth",
                nextAuthCookie = newCookie,
            )
        }
    }

    // ── TokenProvider ───────────────────────────────────────────────────────

    override suspend fun validAccessToken(): String? {
        val s = store.current ?: return null
        val left = jwtExp(s.accessToken) - System.currentTimeMillis() / 1000
        // Same 5-minute buffer the web's jwt() callback uses.
        if (left > 300) return s.accessToken
        return forceRefresh() ?: s.accessToken.takeIf { left > 0 }
    }

    override suspend fun forceRefresh(): String? = refreshLock.withLock {
        withContext(Dispatchers.IO) {
            val s = store.current ?: return@withContext null
            // Another caller may have refreshed while we waited for the lock.
            if (jwtExp(s.accessToken) - System.currentTimeMillis() / 1000 > 300 &&
                s.accessToken != lastRejected
            ) return@withContext s.accessToken
            var fresh: Session? = null
            for (attempt in 1..3) {
                fresh = runCatching {
                    s.refreshToken?.let { directRefresh(it) }
                        ?: s.nextAuthCookie?.let { nextAuthSession(it, s.email) }
                }.getOrNull()
                    ?: runCatching { s.nextAuthCookie?.let { nextAuthSession(it, s.email) } }.getOrNull()
                if (fresh != null) break
                Thread.sleep(attempt * 500L)
            }
            if (fresh == null) { lastRejected = s.accessToken; return@withContext null }
            val merged = fresh.copy(
                name = s.name.ifBlank { fresh.name },
                email = s.email.ifBlank { fresh.email },
                nextAuthCookie = fresh.nextAuthCookie ?: s.nextAuthCookie,
                refreshToken = fresh.refreshToken ?: s.refreshToken,
            )
            store.save(merged)
            merged.accessToken
        }
    }

    @Volatile private var lastRejected: String? = null

    /** Called after a 401 so forceRefresh() doesn't trust an unexpired-but-revoked token. */
    override fun onRejected(token: String?) { lastRejected = token }

    fun updateProfile(name: String, email: String) {
        store.current?.let { store.save(it.copy(name = name, email = email)) }
    }

    companion object {
        private fun JsonObject.str(k: String): String? = this[k]?.jsonPrimitive?.contentOrNull

        private fun claims(jwt: String): JsonObject? = runCatching {
            val part = jwt.split(".")[1]
            val bytes = Base64.decode(part, Base64.URL_SAFE or Base64.NO_WRAP or Base64.NO_PADDING)
            NeemaJson.parseToJsonElement(String(bytes)).jsonObject
        }.getOrNull()

        fun jwtExp(jwt: String): Long = claims(jwt)?.get("exp")?.jsonPrimitive?.longOrNull ?: 0L
        fun jwtSub(jwt: String): String? = claims(jwt)?.str("sub")
    }
}
