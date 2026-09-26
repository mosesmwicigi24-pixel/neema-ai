package ke.co.bethanyhouse.neema.feature.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.agents.TeamApi
import ke.co.bethanyhouse.neema.feature.agents.UNCERTAIN_SAVE
import ke.co.bethanyhouse.neema.feature.agents.refreshAfterForbidden
import ke.co.bethanyhouse.neema.feature.reports.BUSY_TEXT
import ke.co.bethanyhouse.neema.feature.reports.attempt
import ke.co.bethanyhouse.neema.feature.reports.friendlyError
import ke.co.bethanyhouse.neema.feature.reports.httpStatus
import ke.co.bethanyhouse.neema.feature.reports.masking
import ke.co.bethanyhouse.neema.feature.reports.mayHaveApplied
import ke.co.bethanyhouse.neema.core.util.quietly
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.serialization.json.JsonPrimitive
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.launch

/** One of the web's four notification preferences (NotifSettings). */
data class NotifPref(val key: String, val label: String, val desc: String, val default: Boolean)

val NOTIF_PREFS = listOf(
    NotifPref("new_conv", "New conversations", "Alert when a new chat arrives", true),
    NotifPref("human_transfer", "Human transfers", "Alert when a conversation is transferred to you", true),
    NotifPref("order_updates", "Order updates", "Notify on order status changes", false),
    NotifPref("daily_summary", "Daily summary", "Morning digest of activity", true),
)

/** What a password change with no answer says: it can't be read back, and setting it again is harmless. */
internal const val PASSWORD_UNCERTAIN =
    "No answer from the server, so your password may not have changed — what you typed is kept. Check your connection and tap Change Password again."

/**
 * ProfileView.tsx: edit your name/email, change your password, and personal
 * preferences. Saves go to PATCH /admin/me, then /me is refetched so the shell
 * (top bar avatar, permissions) follows.
 *
 * Every failure keeps the form open with what was typed (the forms close only
 * through `onDone`), a save with no answer is checked against the server
 * before it is called a failure, and a typed password is never shown back.
 */
class ProfileViewModel(private val dash: DashboardViewModel) : ViewModel(), ke.co.bethanyhouse.neema.feature.reports.KeepsUiState {
    private val team = TeamApi(dash.api.http)
    private val prefs = dash.container.prefs.raw

    // ── The forms (ProfileView.tsx's `form` and `passwordForm`) ───────────────
    // Held here, not in the screen: like the web's, they keep what was typed
    // when Cancel folds them away, and here they also outlive a rotation, a
    // save still on the wire when the phone turns, and a trip to another
    // screen. The name/email/department come back after Android restarts the
    // app; the passwords are never saved anywhere.

    /** Whose profile the form was filled from (the web re-fills it when agent.id changes). */
    private var formFor: String? = null
    var name by mutableStateOf("")
    var email by mutableStateOf("")
    /** The web shows a Department field but never sends it (PATCH /me has no such column). */
    var department by mutableStateOf("")
    /** Never saved. */
    var password by mutableStateOf("")
    /** Never saved. */
    var confirm by mutableStateOf("")

    /** Fill the form from [agent] — once per agent, as the web's `useEffect([agent?.id])`. */
    fun fillForm(agent: ke.co.bethanyhouse.neema.core.model.Agent) {
        if (formFor == agent.id) return
        formFor = agent.id
        name = agent.name; email = agent.email; department = ""
    }

    private val _closed = kotlinx.coroutines.channels.Channel<String>(kotlinx.coroutines.channels.Channel.UNLIMITED)
    /**
     * Forms to fold away because their save succeeded ("edit", "password"),
     * for whichever screen is on display — the one that started the save may
     * have been replaced by a rotation while it was on the wire.
     */
    val closed: kotlinx.coroutines.flow.Flow<String> = _closed.receiveAsFlow()

    fun close(form: String) { _closed.trySend(form) }

    override fun saveUi(): String? = formFor?.let { id ->
        kotlinx.serialization.json.buildJsonObject {
            put("for", JsonPrimitive(id)); put("name", JsonPrimitive(name))
            put("email", JsonPrimitive(email)); put("department", JsonPrimitive(department))
        }.toString()
    }

    override fun restoreUi(saved: String) {
        val o = runCatching { ke.co.bethanyhouse.neema.core.net.NeemaJson.parseToJsonElement(saved) as kotlinx.serialization.json.JsonObject }
            .getOrNull() ?: return
        fun str(k: String) = (o[k] as? JsonPrimitive)?.takeIf { it.isString }?.content
        formFor = str("for") ?: return
        name = str("name").orEmpty(); email = str("email").orEmpty(); department = str("department").orEmpty()
    }

    private val _saving = MutableStateFlow(false)
    val saving: StateFlow<Boolean> = _saving.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    private val _loadError = MutableStateFlow<String?>(null)
    /**
     * Why the profile couldn't be read, while there is nothing to show
     * (signed in offline: no /me and no team row). The screen shows it with a
     * Retry instead of "Loading profile…" forever.
     */
    val loadError: StateFlow<String?> = _loadError.asStateFlow()

    /** null = follow the server's value; set while an availability change is in flight. */
    private val _availableOverride = MutableStateFlow<Boolean?>(null)
    val availableOverride: StateFlow<Boolean?> = _availableOverride.asStateFlow()
    private var settingAvailable = false

    /**
     * The web keeps these in component state only. Here they persist on the
     * device so a choice survives a restart (keys prefixed "notif_").
     */
    private val _notifs = MutableStateFlow(NOTIF_PREFS.associate { it.key to prefs.getBoolean("notif_${it.key}", it.default) })
    val notifs: StateFlow<Map<String, Boolean>> = _notifs.asStateFlow()

    init {
        if (dash.me.value == null) viewModelScope.launch { load() }
        viewModelScope.launch { dash.me.collect { if (it != null) _loadError.value = null } }
    }

    /** /me straight from the server (so its failure is known), then the shell's copy and the team row. */
    private suspend fun load(): Throwable? {
        val failed = attempt { dash.api.profile.me() }.exceptionOrNull()
        if (failed == null) {
            _loadError.value = null
            dash.refetchMe()
        } else if (dash.me.value == null) {
            _loadError.value = friendlyError(failed, fallback = "The server couldn't send your profile just now.")
        }
        quietly { dash.refreshAgents() }
        return failed
    }

    fun toggleNotif(key: String) {
        val next = !(_notifs.value[key] ?: false)
        _notifs.value = _notifs.value + (key to next)
        prefs.edit().putBoolean("notif_$key", next).apply()
    }

    /** Pull-to-refresh and the Retry button: the spinner lasts until /me and the team row have landed. */
    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            try {
                val failed = load()
                if (failed != null && dash.me.value != null)
                    dash.toast("Couldn't refresh your profile. ${friendlyError(failed)}", ToastType.Error)
            } finally { _refreshing.value = false }
        }
    }

    /** Runs [write] under the saving flag; a second tap while it is on the wire does nothing. */
    private fun save(
        failText: (Exception) -> String,
        uncertain: String,
        verify: (suspend () -> Boolean)?,
        write: suspend () -> Unit,
        done: suspend () -> Unit,
    ) {
        if (_saving.value) return
        _saving.value = true
        viewModelScope.launch {
            try {
                try {
                    write()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Exception) {
                    ke.co.bethanyhouse.neema.feature.reports.stillHere()
                    if (e.mayHaveApplied() && verify != null && attempt { verify() }.getOrDefault(false)) { done(); return@launch }
                    dash.refreshAfterForbidden(e)
                    dash.toast(if (e.mayHaveApplied()) uncertain else failText(e), ToastType.Error)
                    return@launch
                }
                done()
            } finally { _saving.value = false }
        }
    }

    fun saveProfile(name: String, email: String, onDone: () -> Unit) {
        if (name.isBlank() || email.isBlank()) return dash.toast("Name and email required", ToastType.Error)
        // agents.email is UNIQUE and PATCH /admin/me turns a clash into a bare 500.
        val myId = dash.me.value?.id ?: dash.session.value?.agentId
        if (dash.agents.value.any { it.id != myId && it.email.trim().equals(email.trim(), ignoreCase = true) })
            return dash.toast("Another agent already uses that email", ToastType.Error)
        save(
            failText = { failText(it, "Failed to update profile — that email may already be in use") },
            uncertain = UNCERTAIN_SAVE,
            // No answer: if /me now reads what was typed, the save went through.
            verify = { dash.api.profile.me().let { it.name == name.trim() && it.email.equals(email.trim(), ignoreCase = true) } },
            write = { dash.api.profile.update(name = name.trim(), email = email.trim()) },
            done = {
                dash.refetchMe()
                dash.refetchAgents()
                onDone()
                dash.toast("Profile updated")
            },
        )
    }

    fun changePassword(password: String, confirm: String, onDone: () -> Unit) {
        if (password != confirm) return dash.toast("Passwords don't match", ToastType.Error)
        if (password.length < 8) return dash.toast("Password must be at least 8 characters", ToastType.Error)
        save(
            // Whatever the server said, the password itself never appears in it.
            failText = { failText(it, "Failed to change password").masking(password) },
            uncertain = PASSWORD_UNCERTAIN,
            verify = null,
            write = { dash.api.profile.update(password = password) },
            done = {
                // The web empties passwordForm once the change has gone through.
                this.password = ""; this.confirm = ""
                onDone()
                dash.toast("Password changed successfully")
            },
        )
    }

    /**
     * The server's words, except a 5xx: update_me has no error handling, so a
     * refused write comes back as a bare "Internal Server Error".
     */
    private fun failText(e: Exception, serverError: String): String {
        val status = e.httpStatus()
        return when {
            status == 409 -> "Another agent already uses that email"
            status == 429 -> BUSY_TEXT
            status == 500 || status == 501 -> serverError
            else -> friendlyError(e, serverError)
        }
    }

    /** Online / away for the signed-in agent — the same flag the Team screen toggles. */
    fun setAvailable(agentId: String, available: Boolean) {
        if (settingAvailable) return
        settingAvailable = true
        _availableOverride.value = available
        viewModelScope.launch {
            try {
                team.setAvailable(agentId, available)
                dash.refetchMe()
                dash.refetchAgents()
                dash.toast(if (available) "You're available" else "You're away")
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                ke.co.bethanyhouse.neema.feature.reports.stillHere()
                _availableOverride.value = null
                if (e.mayHaveApplied()) {
                    // It may have flipped: show what the server has instead of guessing.
                    val truth = attempt { dash.api.profile.me().isAvailable }.getOrNull()
                    dash.refetchMe()
                    if (truth != available) dash.toast("Couldn't reach the server — availability unchanged", ToastType.Error)
                    else dash.toast(if (available) "You're available" else "You're away")
                } else {
                    dash.refreshAfterForbidden(e)
                    dash.toast(ke.co.bethanyhouse.neema.feature.agents.availabilityFailure(e), ToastType.Error)
                }
            } finally { settingAvailable = false }
        }
    }

    /** Drop the optimistic value once /me agrees. */
    fun reconcile(serverValue: Boolean?) {
        if (_availableOverride.value != null && _availableOverride.value == serverValue) _availableOverride.value = null
    }
}
