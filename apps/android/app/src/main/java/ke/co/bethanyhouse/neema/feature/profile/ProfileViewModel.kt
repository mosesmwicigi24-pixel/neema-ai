package ke.co.bethanyhouse.neema.feature.profile

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.agents.TeamApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/** One of the web's four notification preferences (NotifSettings). */
data class NotifPref(val key: String, val label: String, val desc: String, val default: Boolean)

val NOTIF_PREFS = listOf(
    NotifPref("new_conv", "New conversations", "Alert when a new chat arrives", true),
    NotifPref("human_transfer", "Human transfers", "Alert when a conversation is transferred to you", true),
    NotifPref("order_updates", "Order updates", "Notify on order status changes", false),
    NotifPref("daily_summary", "Daily summary", "Morning digest of activity", true),
)

/**
 * ProfileView.tsx: edit your name/email, change your password, and personal
 * preferences. Saves go to PATCH /admin/me, then /me is refetched so the shell
 * (top bar avatar, permissions) follows.
 */
class ProfileViewModel(private val dash: DashboardViewModel) : ViewModel() {
    private val team = TeamApi(dash.api.http)
    private val prefs = dash.container.prefs.raw

    private val _saving = MutableStateFlow(false)
    val saving: StateFlow<Boolean> = _saving.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    /** null = follow the server's value; set while an availability change is in flight. */
    private val _availableOverride = MutableStateFlow<Boolean?>(null)
    val availableOverride: StateFlow<Boolean?> = _availableOverride.asStateFlow()

    /**
     * The web keeps these in component state only. Here they persist on the
     * device so a choice survives a restart (keys prefixed "notif_").
     */
    private val _notifs = MutableStateFlow(NOTIF_PREFS.associate { it.key to prefs.getBoolean("notif_${it.key}", it.default) })
    val notifs: StateFlow<Map<String, Boolean>> = _notifs.asStateFlow()

    fun toggleNotif(key: String) {
        val next = !(_notifs.value[key] ?: false)
        _notifs.value = _notifs.value + (key to next)
        prefs.edit().putBoolean("notif_$key", next).apply()
    }

    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            dash.refetchMe()
            dash.refetchAgents()
            kotlinx.coroutines.delay(600)
            _refreshing.value = false
        }
    }

    fun saveProfile(name: String, email: String, onDone: () -> Unit) {
        if (name.isBlank() || email.isBlank()) return dash.toast("Name and email required", ToastType.Error)
        if (_saving.value) return
        viewModelScope.launch {
            _saving.value = true
            try {
                dash.api.profile.update(name = name.trim(), email = email.trim())
                dash.refetchMe()
                dash.refetchAgents()
                onDone()
                dash.toast("Profile updated")
            } catch (e: Exception) {
                dash.toast(dash.errorText(e).ifBlank { "Failed to update profile" }, ToastType.Error)
            } finally { _saving.value = false }
        }
    }

    fun changePassword(password: String, confirm: String, onDone: () -> Unit) {
        if (password != confirm) return dash.toast("Passwords don't match", ToastType.Error)
        if (password.length < 8) return dash.toast("Password must be at least 8 characters", ToastType.Error)
        if (_saving.value) return
        viewModelScope.launch {
            _saving.value = true
            try {
                dash.api.profile.update(password = password)
                onDone()
                dash.toast("Password changed successfully")
            } catch (e: Exception) {
                dash.toast(dash.errorText(e).ifBlank { "Failed to change password" }, ToastType.Error)
            } finally { _saving.value = false }
        }
    }

    /** Online / away for the signed-in agent — the same flag the Team screen toggles. */
    fun setAvailable(agentId: String, available: Boolean) {
        _availableOverride.value = available
        viewModelScope.launch {
            try {
                team.setAvailable(agentId, available)
                dash.refetchMe()
                dash.refetchAgents()
                dash.toast(if (available) "You're available" else "You're away")
            } catch (e: Exception) {
                _availableOverride.value = null
                dash.toast("Failed to update availability", ToastType.Error)
            }
        }
    }

    /** Drop the optimistic value once /me agrees. */
    fun reconcile(serverValue: Boolean?) {
        if (_availableOverride.value != null && _availableOverride.value == serverValue) _availableOverride.value = null
    }
}
