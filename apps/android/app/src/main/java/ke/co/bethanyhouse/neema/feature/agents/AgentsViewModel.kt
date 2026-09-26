package ke.co.bethanyhouse.neema.feature.agents

import ke.co.bethanyhouse.neema.core.util.AppClock

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CustomRole
import ke.co.bethanyhouse.neema.core.net.ApiException
import ke.co.bethanyhouse.neema.feature.reports.BUSY_TEXT
import ke.co.bethanyhouse.neema.feature.reports.ScreenLife
import ke.co.bethanyhouse.neema.feature.reports.attempt
import ke.co.bethanyhouse.neema.feature.reports.friendlyError
import ke.co.bethanyhouse.neema.feature.reports.httpStatus
import ke.co.bethanyhouse.neema.feature.reports.masking
import ke.co.bethanyhouse.neema.feature.reports.mayHaveApplied
import ke.co.bethanyhouse.neema.feature.reports.quietly
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
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
    /**
     * A new role's id, fixed when its editor opens. roles.py create_role
     * upserts by id, so re-sending after a timeout updates the role the first
     * try may have made instead of adding a twin.
     */
    val id: String? = null,
)

/** The availability switch's failure: the web's words, unless the phone is offline or signed out. */
internal fun availabilityFailure(e: Throwable): String = when (e.httpStatus()) {
    0, 401, 429 -> friendlyError(e)
    else -> "Failed to update availability"
}

/**
 * A 403 can mean this agent's role or permissions changed while the app was
 * open (the web only notices on its 3-minute agents poll): re-read /me and the
 * team now, so the nav and every permission check correct themselves.
 * Any other failure does nothing. (Replace with dash.onForbidden() once core has it.)
 */
internal fun DashboardViewModel.refreshAfterForbidden(e: Throwable) {
    if (e.httpStatus() == 403) onForbidden()
}

/** What a write that got no answer says when it can't tell whether it landed. */
internal const val UNCERTAIN_SAVE =
    "No answer from the server, so this may not have saved — what you typed is kept. Check your connection and try again."

/**
 * Team management (AgentsView.tsx): agents come from the dashboard's shared
 * list; custom roles are loaded here. Every write refetches whatever it
 * changed, like the web, and reports through the dashboard's toasts.
 * Dialog callbacks ([onDone]) fire only on success so a failed save keeps
 * the form open with what was typed.
 *
 * On a phone network three failures get more than a toast:
 * - No answer (a timeout, a dropped connection): the write may have landed,
 *   so the truth is re-read, and if it shows the change the save counts as
 *   done; otherwise the form stays open, input intact, and says so.
 * - 404: someone else deleted the agent or role — the list is re-read (the
 *   row disappears) and the toast says who is gone.
 * - A cancelled write (signing out mid-save) says nothing at all.
 */
class AgentsViewModel(private val dash: DashboardViewModel) : ViewModel(), ke.co.bethanyhouse.neema.feature.reports.KeepsUiState {
    private val team = TeamApi(dash.api.http)

    /** The dialogs' typed input (see [TeamForms]): outlives a rotation and a restart, passwords excepted. */
    val forms = TeamForms()

    private val _closed = kotlinx.coroutines.channels.Channel<String>(kotlinx.coroutines.channels.Channel.UNLIMITED)
    /**
     * Dialogs to close because their save succeeded ("create", "edit", "pw",
     * "del", "assign", "role", "delrole"). A save outlives the screen that
     * started it — the phone may turn while it is on the wire — so its
     * success is announced here and the screen on display then closes the
     * dialog, rather than a callback into a screen that is gone.
     */
    val closed: kotlinx.coroutines.flow.Flow<String> = _closed.receiveAsFlow()

    /** Close [dialog] on whichever screen is showing (see [closed]). */
    fun close(dialog: String) { _closed.trySend(dialog) }

    override fun saveUi(): String = forms.save()
    override fun restoreUi(saved: String) = forms.restore(saved)

    private val _roles = MutableStateFlow<List<CustomRole>>(emptyList())
    val roles: StateFlow<List<CustomRole>> = _roles.asStateFlow()

    private val _rolesLoading = MutableStateFlow(true)
    val rolesLoading: StateFlow<Boolean> = _rolesLoading.asStateFlow()

    private val _rolesError = MutableStateFlow<String?>(null)
    /** Why the roles couldn't be read; the Roles tab shows it (with Retry) rather than "No roles yet". */
    val rolesError: StateFlow<String?> = _rolesError.asStateFlow()

    private val _agentsError = MutableStateFlow<String?>(null)
    /** Why the team couldn't be read when this screen asked; shown instead of "No agents yet." while the list is empty. */
    val agentsError: StateFlow<String?> = _agentsError.asStateFlow()

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

    /** Agents whose availability change is on the wire: a second tap waits for the first. */
    private val toggling = mutableSetOf<String>()

    /**
     * The team (availability, last seen, active chats) is the dashboard's
     * 3-minute poll, which pauses in the background and refetches on return
     * (usePolling); nothing on the socket announces presence. AgentsView reads
     * its roles on mount. Each return to this screen re-reads both, so the
     * list is never older than the moment it was opened.
     */
    val life = ScreenLife(
        viewModelScope, dash.foreground, catchUpOnForeground = false,
        catchUp = {
            coroutineScope {
                launch { loadAgents() }
                launch { quietly { _roles.value = dash.api.roles.list(); _rolesError.value = null } }
            }
        },
    )

    init {
        viewModelScope.launch { fetchRoles() }
        // The sign-in read of the team failed (offline at start): ask now rather than wait 3 minutes.
        if (dash.agents.value.isEmpty()) viewModelScope.launch { loadAgents() }
        viewModelScope.launch { dash.agents.collect { if (it.isNotEmpty()) _agentsError.value = null } }
    }

    private suspend fun loadAgents(): Throwable? =
        attempt { dash.refreshAgents() }
            .onSuccess { _agentsError.value = null }
            .onFailure { _agentsError.value = friendlyError(it, fallback = "The server couldn't send the team just now.") }
            .exceptionOrNull()

    private suspend fun fetchRoles() {
        _rolesLoading.value = true
        try {
            _roles.value = dash.api.roles.list()
            _rolesError.value = null
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            ke.co.bethanyhouse.neema.feature.reports.stillHere()
            _rolesError.value = friendlyError(e, fallback = "The server couldn't send the roles just now.")
            dash.toast("Failed to load roles", ToastType.Error)
        } finally { _rolesLoading.value = false }
    }

    /** Pull-to-refresh (and the Retry buttons): the spinner lasts until the team and the roles have both landed. */
    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            try {
                var failed: Throwable? = null
                coroutineScope {
                    launch { failed = loadAgents() }
                    launch { fetchRoles() }
                }
                // Agents on screen stay; the pull says it couldn't reach the server.
                failed?.takeIf { dash.agents.value.isNotEmpty() }?.let {
                    dash.toast("Couldn't refresh the team. ${friendlyError(it)}", ToastType.Error)
                }
            } finally { _refreshing.value = false }
        }
    }

    /**
     * One write under the shared saving flag (a second tap while it is in
     * flight does nothing). [write] is the request; [done] the success path
     * (refetch, close the dialog, toast).
     *
     * - A timeout or dropped connection runs [verify] (a fresh read); true
     *   means the write landed after all, so [done] runs.
     * - A 404 goes to [onGone], which answers whether it dealt with it.
     * - Otherwise [fallbackError] replaces the server's words entirely (the
     *   web's fixed "Failed to remove"); [serverError] is what a 5xx says
     *   instead of the bare "Internal Server Error" the API sends when the
     *   database refuses a write (admin.py has no handler for IntegrityError).
     * - [secret] (a typed password) is masked out of anything shown.
     */
    private fun save(
        fallbackError: String? = null,
        serverError: String = "Something went wrong — please try again",
        secret: String = "",
        verify: (suspend () -> Boolean)? = null,
        onGone: (suspend (ApiException) -> Boolean)? = null,
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
                    if (e.mayHaveApplied()) {
                        if (verify != null && attempt { verify() }.getOrDefault(false)) { done(); return@launch }
                        dash.toast(UNCERTAIN_SAVE, ToastType.Error)
                        return@launch
                    }
                    if (e is ApiException && e.status == 404 && onGone != null && onGone(e)) return@launch
                    dash.refreshAfterForbidden(e)
                    // The web's fixed words are for a refusal, not for "you're offline" or "sign in again".
                    val fixed = fallbackError?.takeUnless { e.httpStatus() == 0 || e.httpStatus() == 401 }
                    dash.toast((fixed ?: failText(e, serverError)).masking(secret), ToastType.Error)
                    return@launch
                }
                done()
            } finally { _saving.value = false }
        }
    }

    private fun failText(e: Exception, serverError: String): String {
        val status = e.httpStatus() ?: return friendlyError(e, serverError)
        return when {
            status == 409 -> "An agent with that email already exists"
            status == 429 -> BUSY_TEXT
            status in 500..501 -> serverError
            else -> friendlyError(e, serverError)
        }
    }

    /**
     * agents.email is UNIQUE and the API turns a clash into an unhandled 500,
     * so a duplicate is caught here, against the list already on screen.
     */
    private fun emailTaken(email: String, exceptId: String? = null): Boolean =
        dash.agents.value.any { it.id != exceptId && it.email.trim().equals(email.trim(), ignoreCase = true) }

    /** The team as the server has it now (the dashboard's list follows). */
    private suspend fun freshAgents(): List<Agent> { dash.refreshAgents(); return dash.agents.value }

    /** A 404 on [agent]: someone else removed them. The list is re-read so their card goes, and the dialog with it. */
    private fun agentGone(agent: Agent, onDone: () -> Unit): suspend (ApiException) -> Boolean = { e ->
        if (e.detail.contains("Role not found", ignoreCase = true)) false
        else {
            quietly { dash.refreshAgents() }
            onDone()
            dash.toast("${agent.name.ifBlank { "This agent" }} was removed by someone else", ToastType.Error)
            true
        }
    }

    // ── Agent CRUD ────────────────────────────────────────────────────────────

    fun createAgent(name: String, email: String, password: String, roleId: String, onDone: () -> Unit) {
        if (name.isBlank() || email.isBlank() || password.isEmpty())
            return dash.toast("Name, email and password are required", ToastType.Error)
        if (password.length < 8) return dash.toast("Password must be ≥8 characters", ToastType.Error)
        if (emailTaken(email)) return dash.toast("An agent with that email already exists", ToastType.Error)
        save(
            serverError = "Couldn't create the agent — that email may already be in use",
            secret = password,
            // No answer: if the address is on the team now, the create went through.
            verify = { freshAgents().any { it.email.trim().equals(email.trim(), ignoreCase = true) } },
            write = { dash.api.agents.create(name.trim(), email.trim(), password, toDbRole(roleId)) },
            done = {
                dash.refetchAgents()
                // The web clears createForm only once an agent is made.
                forms.resetCreate()
                onDone()
                dash.toast("Agent created")
            },
        )
    }

    fun saveEdit(agent: Agent, name: String, email: String, onDone: () -> Unit) {
        if (name.isBlank() || email.isBlank()) return dash.toast("Name and email required", ToastType.Error)
        if (emailTaken(email, exceptId = agent.id)) return dash.toast("An agent with that email already exists", ToastType.Error)
        save(
            serverError = "Couldn't update the agent — that email may already be in use",
            verify = {
                freshAgents().find { it.id == agent.id }
                    ?.let { it.name == name.trim() && it.email.equals(email.trim(), ignoreCase = true) } == true
            },
            onGone = agentGone(agent, onDone),
            write = { team.updateAgent(agent.id, buildJsonObject { put("name", name.trim()); put("email", email.trim()) }) },
            done = {
                dash.refetchAgents()
                onDone()
                dash.toast("Agent updated")
            },
        )
    }

    /**
     * No [verify]: a password can't be read back. Setting the same one again
     * is harmless, so a save with no answer keeps both fields for another go.
     */
    fun savePassword(agent: Agent, password: String, confirm: String, onDone: () -> Unit) {
        if (password.length < 8) return dash.toast("Password must be ≥8 characters", ToastType.Error)
        if (password != confirm) return dash.toast("Passwords do not match", ToastType.Error)
        save(
            secret = password,
            onGone = agentGone(agent, onDone),
            write = { team.updateAgent(agent.id, buildJsonObject { put("password", password) }) },
            done = {
                forms.openPassword()
                onDone()
                dash.toast("Password updated")
            },
        )
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

    private fun doDelete(agent: Agent, onDone: () -> Unit) = save(
        fallbackError = "Failed to remove",
        // No answer: gone from the team means the delete went through.
        verify = { freshAgents().none { it.id == agent.id } },
        // Someone else removed them first: what was asked for is done.
        onGone = {
            quietly { dash.refreshAgents() }
            onDone()
            dash.toast("${agent.name.ifBlank { "This agent" }} was already removed")
            true
        },
        write = { dash.api.agents.delete(agent.id) },
        done = {
            dash.refetchAgents()
            onDone()
            dash.toast("Agent removed")
        },
    )

    fun toggleOnline(agent: Agent, current: Boolean) {
        if (agent.id in toggling) return
        val next = !current
        toggling += agent.id
        _availability.update { it + (agent.id to next) }
        viewModelScope.launch {
            try {
                team.setAvailable(agent.id, next)
                dash.refetchAgents()
                // The dashboard also polls /me; keep the signed-in agent's own row in step.
                if (agent.id == dash.me.value?.id) dash.refetchMe()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                ke.co.bethanyhouse.neema.feature.reports.stillHere()
                when {
                    // It may have flipped: show the server's value rather than guess.
                    e.mayHaveApplied() -> {
                        val truth = attempt { freshAgents().find { it.id == agent.id }?.isAvailable }.getOrNull()
                        _availability.update { it - agent.id }
                        if (truth != next) dash.toast("Couldn't reach the server — availability unchanged", ToastType.Error)
                    }
                    e.httpStatus() == 404 -> {
                        _availability.update { it - agent.id }
                        agentGone(agent) {}(e as ApiException)
                    }
                    else -> {
                        _availability.update { it - agent.id }
                        dash.refreshAfterForbidden(e)
                        dash.toast(availabilityFailure(e), ToastType.Error)
                    }
                }
            } finally { toggling -= agent.id }
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
        val gone = agentGone(agent, onDone)
        save(
            verify = {
                freshAgents().find { it.id == agent.id }
                    ?.let { it.customRoleId == roleId && it.customPermissions == customPermissions } == true
            },
            onGone = { e ->
                if (e.detail.contains("Role not found", ignoreCase = true)) {
                    // The role went, not the agent: re-read the roles and let them pick another.
                    quietly { _roles.value = dash.api.roles.list() }
                    dash.toast("That role was deleted by someone else — pick another", ToastType.Error)
                    true
                } else gone(e)
            },
            write = { team.assignRole(agent.id, roleId, customPermissions) },
            done = {
                dash.refetchAgents()
                if (agent.id == dash.me.value?.id) dash.refetchMe()
                onDone()
                dash.toast("Role assigned")
            },
        )
    }

    // ── Role CRUD ─────────────────────────────────────────────────────────────

    /** The roles as the server has them now. */
    private suspend fun freshRoles(): List<CustomRole> = dash.api.roles.list().also { _roles.value = it }

    /** [editing] null = create a new role. */
    fun saveRole(editing: CustomRole?, form: RoleForm, onDone: () -> Unit) {
        if (form.name.isBlank()) return dash.toast("Role name required", ToastType.Error)
        val newId = form.id ?: "role_${AppClock.now()}"
        val id = editing?.id ?: newId
        save(
            verify = {
                freshRoles().find { it.id == id }?.let {
                    it.name == form.name && it.description == form.description &&
                        it.color.equals(form.color, ignoreCase = true) && it.permissions.toSet() == form.permissions.toSet()
                } == true
            },
            onGone = {
                quietly { freshRoles() }
                onDone()
                dash.toast("That role was deleted by someone else", ToastType.Error)
                true
            },
            write = {
                if (editing == null) {
                    dash.api.roles.create(
                        id = newId,
                        name = form.name, description = form.description,
                        color = form.color, permissions = form.permissions,
                    )
                } else {
                    dash.api.roles.update(editing.id, buildJsonObject {
                        put("name", form.name)
                        put("description", form.description)
                        put("color", form.color)
                        putJsonArray("permissions") { form.permissions.forEach { add(JsonPrimitive(it)) } }
                    })
                }
            },
            done = {
                dash.toast(if (editing == null) "Role created" else "Role updated")
                fetchRoles()
                // Agents on this role carry its permissions in their rows.
                dash.refetchAgents()
                onDone()
            },
        )
    }

    fun deleteRole(role: CustomRole, onDone: () -> Unit) = save(
        verify = { freshRoles().none { it.id == role.id } },
        // Someone else deleted it first: what was asked for is done.
        onGone = {
            quietly { freshRoles() }
            dash.refetchAgents()
            onDone()
            dash.toast("That role was already deleted")
            true
        },
        write = { dash.api.roles.delete(role.id) },
        done = {
            fetchRoles()
            dash.refetchAgents()
            onDone()
            dash.toast("Role deleted")
        },
    )
}
