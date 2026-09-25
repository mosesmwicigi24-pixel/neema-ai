package ke.co.bethanyhouse.neema.core.auth

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/** What the web keeps in its NextAuth JWT cookie, kept here in encrypted prefs. */
data class Session(
    val accessToken: String,
    val refreshToken: String?,
    val agentId: String,
    val email: String,
    val name: String,
    val role: String,
    val isSuperuser: Boolean,
    /** "direct" = FastAPI tokens; "nextauth" = tokens minted through the web's NextAuth. */
    val mode: String,
    /** NextAuth session cookie (only in "nextauth" mode) — lets us ask the web to refresh. */
    val nextAuthCookie: String? = null,
)

class SessionStore(context: Context, override: SharedPreferences? = null) {
    private val prefs: SharedPreferences = override ?: runCatching {
        val key = MasterKey.Builder(context).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(
            context, "neema_session", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
        )
    }.getOrElse {
        // A keystore that can't be opened (restored backup on a new device)
        // must not brick the app: start clean.
        context.deleteSharedPreferences("neema_session")
        context.getSharedPreferences("neema_session_fallback", Context.MODE_PRIVATE)
    }

    private val _session = MutableStateFlow(read())
    val session: StateFlow<Session?> = _session.asStateFlow()
    val current: Session? get() = _session.value

    private fun read(): Session? {
        val token = prefs.getString("access", null) ?: return null
        val agentId = prefs.getString("agent_id", null) ?: return null
        return Session(
            accessToken = token,
            refreshToken = prefs.getString("refresh", null),
            agentId = agentId,
            email = prefs.getString("email", "") ?: "",
            name = prefs.getString("name", "") ?: "",
            role = prefs.getString("role", "agent") ?: "agent",
            isSuperuser = prefs.getBoolean("superuser", false),
            mode = prefs.getString("mode", "direct") ?: "direct",
            nextAuthCookie = prefs.getString("na_cookie", null),
        )
    }

    fun save(s: Session) {
        prefs.edit()
            .putString("access", s.accessToken)
            .putString("refresh", s.refreshToken)
            .putString("agent_id", s.agentId)
            .putString("email", s.email)
            .putString("name", s.name)
            .putString("role", s.role)
            .putBoolean("superuser", s.isSuperuser)
            .putString("mode", s.mode)
            .putString("na_cookie", s.nextAuthCookie)
            .apply()
        _session.value = s
    }

    /** Forget the tokens but remember who was signed in (for the re-auth prompt). */
    fun clear() {
        val email = current?.email
        prefs.edit().clear().apply()
        if (email != null) prefs.edit().putString("last_email", email).apply()
        _session.value = null
    }

    val lastEmail: String? get() = current?.email ?: prefs.getString("last_email", null)
}
