package ke.co.bethanyhouse.neema.feature.agents

import ke.co.bethanyhouse.neema.core.util.AppClock

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CustomRole
import ke.co.bethanyhouse.neema.core.net.ApiException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/** The role editor's form (roleForm in the web). */
data class RoleForm(
    val name: String = "",
    val description: String = "",
    val color: String = ROLE_COLORS[0],
    val permissions: List<String> = emptyList(),
)

/**
 * Team management (AgentsView.tsx): agents come from the dashboard's shared
 * list; custom roles are loaded here. Every write refetches whatever it
 * changed, like the web, and reports through the dashboard's toasts.
 * Dialog callbacks ([onDone]) fire only on success so a failed save keeps
 * the form open with what was typed.
 */
class AgentsViewModel(private val dash: DashboardViewModel) : ViewModel() {
    private val team = TeamApi(dash.api.http)

    private val _roles = MutableStateFlow<List<CustomRole>>(emptyList())
    val roles: StateFlow<List<CustomRole>> = _roles.asStateFlow()

    private val _rolesLoading = MutableStateFlow(true)
    val rolesLoading: StateFlow<Boolean> = _rolesLoading.asStateFlow()

    private val _saving = MutableStateFlow(false)
    val saving: StateFlow<Boolean> = _saving.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    /**
     * Availability flips the moment the switch is touched; the refetched
     * list confirms it. Cleared per agent once the server answers.
     */
    private val _availability = MutableStateFlow<Map<String, Boolean>>(emptyMap())
    val availability: StateFlow<Map<String, Boolean>> = _availability.asStateFlow()

    init { viewModelScope.launch { fetchRoles() } }

    private suspend fun fetchRoles() {
        _rolesLoading.value = true
        try { _roles.value = dash.api.roles.list() }
        catch (e: Exception) { dash.toast("Failed to load roles", ToastType.Error) }
        finally { _rolesLoading.value = false }
    }

    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            dash.refetchAgents()
            fetchRoles()
            _refreshing.value = false
        }
    }

    /**
     * Runs [block] with the shared saving flag, toasting any failure.
     * [fallbackError] replaces the server's words entirely (the web's fixed
     * "Failed to remove"); [serverError] is what a 5xx says instead of the bare
     * "Internal Server Error" body the API sends when the database refuses a
     * write (admin.py has no handler for IntegrityError).
     */
    private fun save(fallbackError: String? = null, serverError: String = "Something went wrong — please try again", block: suspend () -> Unit) {
        if (_saving.value) return
        viewModelScope.launch {
            _saving.value = true
            try { block() }
            catch (e: Exception) { dash.toast(fallbackError ?: failText(e, serverError), ToastType.Error) }
            finally { _saving.value = false }
        }
    }

    private fun failText(e: Exception, serverError: String): String {
        val status = (e as? ApiException)?.status ?: return dash.errorText(e)
        return when {
            status == 409 -> "An agent with that email already exists"
            status >= 500 -> serverError
            else -> dash.errorText(e)
        }
    }

    /**
     * agents.email is UNIQUE and the API turns a clash into an unhandled 500,
     * so a duplicate is caught here, against the list already on screen.
     */
    private fun emailTaken(email: String, exceptId: String? = null): Boolean =
        dash.agents.value.any { it.id != exceptId && it.email.trim().equals(email.trim(), ignoreCase = true) }

    // ── Agent CRUD ────────────────────────────────────────────────────────────

    fun createAgent(name: String, email: String, password: String, roleId: String, onDone: () -> Unit) {
        if (name.isBlank() || email.isBlank() || password.isEmpty())
            return dash.toast("Name, email and password are required", ToastType.Error)
        if (password.length < 8) return dash.toast("Password must be ≥8 characters", ToastType.Error)
        if (emailTaken(email)) return dash.toast("An agent with that email already exists", ToastType.Error)
        save(serverError = "Couldn't create the agent — that email may already be in use") {
            dash.api.agents.create(name.trim(), email.trim(), password, toDbRole(roleId))
            dash.refetchAgents()
            onDone()
            dash.toast("Agent created")
        }
    }

    fun saveEdit(agent: Agent, name: String, email: String, onDone: () -> Unit) {
        if (name.isBlank() || email.isBlank()) return dash.toast("Name and email required", ToastType.Error)
        if (emailTaken(email, exceptId = agent.id)) return dash.toast("An agent with that email already exists", ToastType.Error)
        save(serverError = "Couldn't update the agent — that email may already be in use") {
            team.updateAgent(agent.id, buildJsonObject { put("name", name.trim()); put("email", email.trim()) })
            dash.refetchAgents()
            onDone()
            dash.toast("Agent updated")
        }
    }

    fun savePassword(agent: Agent, password: String, confirm: String, onDone: () -> Unit) {
        if (password.length < 8) return dash.toast("Password must be ≥8 characters", ToastType.Error)
        if (password != confirm) return dash.toast("Passwords do not match", ToastType.Error)
        save {
            team.updateAgent(agent.id, buildJsonObject { put("password", password) })
            onDone()
            dash.toast("Password updated")
        }
    }

    /**
     * Why [agent] can't be removed from here, or null when it can. The API
     * deletes any row it is asked to — including the caller's own, after which
     * every request answers 404 "Agent not found" (not 401), so the app could
     * neither work nor sign out — and the last admin, which leaves nobody
     * able to manage the team.
     */
    fun removalBlocker(agent: Agent): String? {
        val meId = dash.me.value?.id ?: dash.session.value?.agentId
        if (agent.id == meId) return "You can't remove your own account — ask another admin"
        val isAdmin = { a: Agent -> a.role == "admin" || a.isSuperuser }
        if (isAdmin(agent) && dash.agents.value.count(isAdmin) <= 1) return "You can't remove the last admin"
        return null
    }

    /** The trash button: true opens the confirmation; false has already said why not. */
    fun requestRemove(agent: Agent): Boolean {
        val why = removalBlocker(agent) ?: return true
        dash.toast(why, ToastType.Error)
        return false
    }

    fun deleteAgent(agent: Agent, onDone: () -> Unit) {
        removalBlocker(agent)?.let { return dash.toast(it, ToastType.Error) }
        doDelete(agent, onDone)
    }

    private fun doDelete(agent: Agent, onDone: () -> Unit) = save("Failed to remove") {
        dash.api.agents.delete(agent.id)
        dash.refetchAgents()
        onDone()
        dash.toast("Agent removed")
    }

    fun toggleOnline(agent: Agent, current: Boolean) {
        val next = !current
        _availability.update { it + (agent.id to next) }
        viewModelScope.launch {
            try {
                team.setAvailable(agent.id, next)
                dash.refetchAgents()
                // The dashboard also polls /me; keep the signed-in agent's own row in step.
                if (agent.id == dash.me.value?.id) dash.refetchMe()
            } catch (e: Exception) {
                _availability.update { it - agent.id }
                dash.toast("Failed to update availability", ToastType.Error)
            }
        }
    }

    /** Drop optimistic values the refetched list now agrees with. */
    fun reconcile(agents: List<Agent>) {
        val cur = _availability.value
        if (cur.isEmpty()) return
        _availability.value = cur.filter { (id, v) -> agents.find { it.id == id }?.isAvailable != v }
    }

    // ── Role assignment ───────────────────────────────────────────────────────

    /**
     * [customPermissions] non-null gives this one agent their own permission
     * set on top of the role (agents.custom_permissions); null clears it.
     */
    fun saveAssign(agent: Agent, roleId: String, customPermissions: List<String>?, onDone: () -> Unit) {
        if (roleId.isEmpty()) return dash.toast("Please select a role", ToastType.Error)
        save {
            team.assignRole(agent.id, roleId, customPermissions)
            dash.refetchAgents()
            if (agent.id == dash.me.value?.id) dash.refetchMe()
            onDone()
            dash.toast("Role assigned")
        }
    }

    // ── Role CRUD ─────────────────────────────────────────────────────────────

    /** [editing] null = create a new role. */
    fun saveRole(editing: CustomRole?, form: RoleForm, onDone: () -> Unit) {
        if (form.name.isBlank()) return dash.toast("Role name required", ToastType.Error)
        save {
            if (editing == null) {
                dash.api.roles.create(
                    id = "role_${AppClock.now()}",
                    name = form.name, description = form.description,
                    color = form.color, permissions = form.permissions,
                )
                dash.toast("Role created")
            } else {
                dash.api.roles.update(editing.id, buildJsonObject {
                    put("name", form.name)
                    put("description", form.description)
                    put("color", form.color)
                    putJsonArray("permissions") { form.permissions.forEach { add(JsonPrimitive(it)) } }
                })
                dash.toast("Role updated")
            }
            fetchRoles()
            // Agents on this role carry its permissions in their rows.
            dash.refetchAgents()
            onDone()
        }
    }

    fun deleteRole(role: CustomRole, onDone: () -> Unit) = save {
        dash.api.roles.delete(role.id)
        fetchRoles()
        dash.refetchAgents()
        onDone()
        dash.toast("Role deleted")
    }
}
