package ke.co.bethanyhouse.neema.app

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.NeemaApplication
import ke.co.bethanyhouse.neema.core.api.NeemaApi
import ke.co.bethanyhouse.neema.core.auth.Session
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.InboxSummary
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.perm.Perms
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.serialization.builtins.ListSerializer

/** Every top-level screen of the dashboard (types/index.ts ViewId). */
enum class ViewId(val label: String) {
    Conversations("Inbox"),
    Calls("Calls"),
    Orders("Orders"),
    Reports("Reports"),
    Deals("Deals"),
    Leads("Leads"),
    Overview("Analytics"),
    Catalog("Catalog"),
    Agents("Team"),
    Settings("Settings"),
    Profile("Profile");

    companion object {
        /** The web's `?view=` names. */
        fun fromWeb(name: String?): ViewId? = when (name?.lowercase()) {
            "conversations", "inbox" -> Conversations
            "calls" -> Calls
            "orders" -> Orders
            "reports" -> Reports
            "deals" -> Deals
            "leads" -> Leads
            "overview", "analytics" -> Overview
            "catalog" -> Catalog
            "agents", "team" -> Agents
            "settings" -> Settings
            "profile" -> Profile
            else -> null
        }
    }
}

enum class ToastType { Success, Error, Warning, Info }
data class Toast(val message: String, val type: ToastType = ToastType.Success, val id: Long = System.nanoTime())

/**
 * The dashboard page's shared state (app/dashboard/page.tsx): the signed-in
 * agent, the team, orders and catalog (polled as a fallback to the socket),
 * permissions, the current view, cross-view requests, and toasts. Every
 * feature screen receives this.
 */
class DashboardViewModel : ViewModel() {
    val container: AppContainer = NeemaApplication.instance.container
    val api: NeemaApi get() = container.api

    val session: StateFlow<Session?> = container.sessionStore.session
    private val scope: String? get() = session.value?.agentId

    private val _me = MutableStateFlow<Agent?>(null)
    /** GET /admin/me — name, email, role and permissions of whoever is signed in. */
    val me: StateFlow<Agent?> = _me.asStateFlow()

    private val _agents = MutableStateFlow<List<Agent>>(emptyList())
    val agents: StateFlow<List<Agent>> = _agents.asStateFlow()

    private val _orders = MutableStateFlow<List<Order>>(emptyList())
    val orders: StateFlow<List<Order>> = _orders.asStateFlow()

    private val _catalog = MutableStateFlow<List<CatalogItem>>(emptyList())
    val catalog: StateFlow<List<CatalogItem>> = _catalog.asStateFlow()

    /** Inbox badges, counted by the server over ALL conversations. The inbox keeps it fresh. */
    val inboxSummary = MutableStateFlow<InboxSummary?>(null)

    private val _view = MutableStateFlow(ViewId.Conversations)
    val view: StateFlow<ViewId> = _view.asStateFlow()

    /** Cross-view request: open this customer's thread (wa_id / external_id / "phone|orderRef" / conversation id). */
    val openConvKey = MutableStateFlow<String?>(null)
    /** Cross-view request: focus the Calls console on one customer (wa_id). */
    val callsFocusKey = MutableStateFlow<String?>(null)

    private val _inboxRefresh = MutableSharedFlow<Unit>(extraBufferCapacity = 4)
    /** Emits when something (a push notification) says the inbox should refetch now. */
    val inboxRefresh: SharedFlow<Unit> = _inboxRefresh.asSharedFlow()

    private val _toasts = MutableSharedFlow<Toast>(extraBufferCapacity = 8)
    val toasts: SharedFlow<Toast> = _toasts.asSharedFlow()

    val sessionExpired = MutableStateFlow(false)

    /**
     * A feature sets this while it owns the whole screen (an open chat thread,
     * a full-screen editor) so the shell hides its top bar and bottom nav.
     */
    val immersive = MutableStateFlow(false)

    val dark: StateFlow<Boolean> = container.prefs.dark
    fun setDark(v: Boolean) = container.prefs.setDark(v)

    private var pollers = mutableListOf<Job>()

    init {
        viewModelScope.launch {
            container.http.sessionExpired.collect { if (session.value != null) sessionExpired.value = true }
        }
        viewModelScope.launch {
            container.notifications.incoming.collect { n ->
                toast("${n.title}: ${n.body}", ToastType.Info)
                // Push events drive freshness; polls are just the fallback.
                when (n.type) {
                    "new_conversation", "human_transfer", "intercept", "transfer", "media_escalation" -> {
                        delay(800); _inboxRefresh.tryEmit(Unit)
                    }
                    "order_update" -> { delay(800); refetchOrders() }
                }
            }
        }
        viewModelScope.launch {
            session.collect { s -> if (s != null) onSignedIn() else stopPolling() }
        }
    }

    private fun onSignedIn() {
        val sc = scope
        // Paint instantly from this agent's last snapshot.
        container.snapshots.read(sc, "agents", ListSerializer(Agent.serializer()))?.let { _agents.value = it }
        container.snapshots.read(sc, "orders", ListSerializer(Order.serializer()))?.let { _orders.value = it }
        container.snapshots.read(sc, "catalog", ListSerializer(CatalogItem.serializer()))?.let { _catalog.value = it }
        container.snapshots.read(sc, "me", Agent.serializer())?.let { _me.value = it }
        refetchMe()
        stopPolling()
        pollers += poll(180_000) { refetchAgentsNow() }
        pollers += poll(300_000) { refetchCatalogNow() }
        pollers += poll(90_000) { refetchOrdersNow() }
    }

    private fun stopPolling() { pollers.forEach { it.cancel() }; pollers.clear() }

    /** Poll while the app is in the foreground; refetch once on return. */
    private fun poll(everyMs: Long, fetch: suspend () -> Unit): Job = viewModelScope.launch {
        val fg = NeemaApplication.instance.foreground
        while (isActive) {
            runCatching { fetch() }
            delay(everyMs)
            if (!fg.value) fg.first { it }
        }
    }

    fun refetchMe(attempt: Int = 1) {
        viewModelScope.launch {
            runCatching { api.profile.me() }
                .onSuccess {
                    _me.value = it
                    container.snapshots.write(scope, "me", Agent.serializer(), it)
                    container.auth.updateProfile(it.name, it.email)
                }
                .onFailure { if (attempt < 3) { delay(attempt * 500L); refetchMe(attempt + 1) } }
        }
    }

    private suspend fun refetchAgentsNow() {
        val list = api.agents.list()
        _agents.value = list
        container.snapshots.write(scope, "agents", ListSerializer(Agent.serializer()), list)
    }
    private suspend fun refetchOrdersNow() {
        val list = api.orders.list()
        _orders.value = list
        container.snapshots.write(scope, "orders", ListSerializer(Order.serializer()), list)
    }
    private suspend fun refetchCatalogNow() {
        val list = api.catalog.list()
        _catalog.value = list
        container.snapshots.write(scope, "catalog", ListSerializer(CatalogItem.serializer()), list)
    }

    fun refetchAgents() { viewModelScope.launch { runCatching { refetchAgentsNow() } } }
    fun refetchOrders() { viewModelScope.launch { runCatching { refetchOrdersNow() } } }
    fun refetchCatalog() { viewModelScope.launch { runCatching { refetchCatalogNow() } } }
    fun refreshInbox() { _inboxRefresh.tryEmit(Unit) }

    /**
     * The signed-in agent. The team-list row wins: /admin/me is the bare DB row
     * without role_permissions / custom_permissions, so reading permissions from
     * it alone would drop every custom role back to the legacy defaults.
     */
    val currentAgent: Agent?
        get() {
            val me = _me.value
            val email = me?.email ?: session.value?.email
            val id = me?.id ?: session.value?.agentId
            return _agents.value.find { it.id == id }
                ?: _agents.value.find { it.email.equals(email, ignoreCase = true) }
                ?: me
        }

    fun permissions(): List<String> {
        val a = currentAgent
        val s = session.value
        return when {
            a != null -> Perms.of(a)
            s != null -> Perms.effective(s.role, s.isSuperuser, null)
            else -> emptyList()
        }
    }

    fun can(perm: String): Boolean = perm in permissions()

    val isAdmin: Boolean
        get() = session.value?.role == "admin" || currentAgent?.role == "admin" ||
            currentAgent?.isSuperuser == true || session.value?.isSuperuser == true || can(Perms.MANAGE_AGENTS)

    fun navigate(v: ViewId) { _view.value = v }

    fun openConversationFor(key: String) { openConvKey.value = key; _view.value = ViewId.Conversations }
    fun focusCalls(waId: String) { callsFocusKey.value = waId; _view.value = ViewId.Calls }

    fun toast(message: String, type: ToastType = ToastType.Success) { _toasts.tryEmit(Toast(message, type)) }

    /** Friendly message for a failed call, for toasts. */
    fun errorText(t: Throwable): String =
        (t as? ke.co.bethanyhouse.neema.core.net.ApiException)?.let {
            if (it.status == 0) "Network problem — check your connection" else it.detail
        } ?: (t.message ?: "Something went wrong")

    fun onReauthenticated() {
        sessionExpired.value = false
        refetchMe(); refetchAgents(); refetchOrders(); refetchCatalog(); refreshInbox()
    }

    fun logout() {
        stopPolling()
        container.calls.hangup()
        container.auth.logout()
        container.notifications.clear()
        _me.value = null; _agents.value = emptyList(); _orders.value = emptyList(); _catalog.value = emptyList()
        inboxSummary.value = null
        sessionExpired.value = false
        _view.value = ViewId.Conversations
    }
}
