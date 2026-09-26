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
import ke.co.bethanyhouse.neema.core.util.AppClock
import ke.co.bethanyhouse.neema.core.util.Coalescer
import ke.co.bethanyhouse.neema.core.util.ScreenLife
import ke.co.bethanyhouse.neema.core.util.SingleFlight
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModelStore
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
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

/** The dashboard's query parameters (open + ref, view + caller), from a URL or a notification. */
data class DeepLink(val open: String?, val ref: String?, val view: String?, val caller: String?) {
    val isEmpty: Boolean get() = open.isNullOrBlank() && view.isNullOrBlank()

    companion object {
        /** From a dashboard URL's (https or neema://) query parameters. */
        fun of(param: (String) -> String?) = DeepLink(param("open"), param("ref"), param("view"), param("caller"))
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
class DashboardViewModel(
    val container: AppContainer = NeemaApplication.instance.container,
    /**
     * What must survive the process being killed in the background: the view
     * on screen, the way back through the views, and a deep link waiting for
     * sign-in. The activity's default factory hands one in.
     */
    private val saved: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    /** MainActivity's `by viewModels()`: the default factory calls this with the activity's saved state. */
    constructor(saved: SavedStateHandle) : this(NeemaApplication.instance.container, saved)

    /** True while the app is on screen — polls pause in the background. */
    val foreground: StateFlow<Boolean> get() = container.foreground
    /** The device has a network (the shell's offline banner). */
    val online: StateFlow<Boolean> get() = container.online
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

    private val _view = MutableStateFlow(
        saved.get<String>(KEY_VIEW)?.let { n -> ViewId.entries.find { it.name == n } } ?: ViewId.Conversations,
    )
    val view: StateFlow<ViewId> = _view.asStateFlow()

    /**
     * The views visited before this one, most recent last, each at most once
     * (see [back]). Restored with the view after a process death.
     */
    private val history = ArrayDeque<ViewId>(
        saved.get<ArrayList<String>>(KEY_HISTORY).orEmpty().mapNotNull { n -> ViewId.entries.find { it.name == n } },
    )

    private val _canGoBack = MutableStateFlow(history.isNotEmpty() || _view.value != ViewId.Conversations)
    /** System back has a view to return to (the shell's lowest-priority back handler). */
    val canGoBack: StateFlow<Boolean> = _canGoBack.asStateFlow()

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

    /** When orders last arrived (a poll that just ran makes a catch-up redundant). */
    @Volatile private var lastOrdersFetch = 0L

    /** "Now" for the catch-up freshness check; tests drive it by hand. */
    internal var clock: () -> Long = AppClock::now

    /**
     * A deep link that arrived signed out — page.tsx's sessionStorage
     * "neema:deeplink" — kept in the saved state, so the login screen being
     * killed in the background does not lose it either.
     */
    private var pendingLink: DeepLink?
        get() = saved.get<ArrayList<String?>>(KEY_LINK)?.takeIf { it.size == 4 }?.let { DeepLink(it[0], it[1], it[2], it[3]) }
        set(v) { if (v == null) saved.remove<Any>(KEY_LINK) else saved[KEY_LINK] = arrayListOf(v.open, v.ref, v.view, v.caller) }

    private val _signingOut = MutableStateFlow(false)
    /** Sign-out is waiting (bounded) for a live call's terminate to reach the server. */
    val signingOut: StateFlow<Boolean> = _signingOut.asStateFlow()
    private var signOutJob: Job? = null

    /**
     * Ends any call and returns once the server has been told, bounded
     * (CallManager.endForSignOut: 3 s; a merely ringing call is left ringing
     * for colleagues). Tests replace it.
     */
    internal var endCall: suspend () -> Unit = { container.calls.endForSignOut() }

    private companion object {
        const val KEY_VIEW = "shell.view"
        const val KEY_HISTORY = "shell.history"
        /** Whose view and history those are: another agent signing in starts on the inbox. */
        const val KEY_OWNER = "shell.owner"
        const val KEY_LINK = "shell.pendingLink"
        /** Views remembered for back; each appears once, so this is plenty. */
        const val HISTORY_MAX = 10
        /**
         * The shell's own cap on waiting for the call to end before the token
         * goes (the terminate request needs it). endForSignOut bounds itself
         * at 3 s; this only guards against it ever hanging.
         */
        const val SIGN_OUT_CALL_MS = 4_000L
        /** Orders fetched this recently need no catch-up on reconnect. */
        const val CATCH_UP_FRESH_MS = 5_000L
        /** A burst of 403s (a screen's parallel loads) costs one reread. */
        const val FORBIDDEN_WINDOW_MS = 1_000L
        /** A screen that keeps getting 403s rereads the team list at most this often. */
        const val FORBIDDEN_COOLDOWN_MS = 15_000L
    }

    /** One inbox refetch per burst of inbox alerts (see the notification collector). */
    private val inboxKick = Coalescer(viewModelScope, ScreenLife.EVENT_WINDOW_MS) { _inboxRefresh.emit(Unit) }
    /**
     * One GET /admin/orders on the wire at a time: the 90 s poll, a
     * reconnect's catch-up, an order alert, re-auth and a pull-to-refresh
     * that meet share a read (a caller arriving mid-read gets the next one,
     * so its answer never predates its reason to ask).
     */
    private val ordersRead = SingleFlight(viewModelScope) { fetchOrdersNow() }
    /** One GET /admin/orders per burst of order alerts. */
    private val ordersKick = Coalescer(viewModelScope, ScreenLife.EVENT_WINDOW_MS) { refetchOrdersNow() }

    /**
     * The ViewModelStore of the signed-in agent's screens (MainActivity's
     * SignedInScope). Held here, not in composition, so anything that
     * recreates the activity's content (a locale or font-size change) keeps
     * every screen's state and in-flight work instead of refetching it all;
     * a sign-out or a switch of agent clears it (cancelling its calls).
     */
    private var agentStore: Pair<String, ViewModelStore>? = null

    fun viewModelStoreFor(agentId: String): ViewModelStore {
        agentStore?.let { (id, store) -> if (id == agentId) return store; store.clear() }
        return ViewModelStore().also { agentStore = agentId to it }
    }

    private fun dropAgentStore() { agentStore?.second?.clear(); agentStore = null }

    override fun onCleared() { dropAgentStore() }

    init {
        viewModelScope.launch {
            container.http.sessionExpired.collect { if (session.value != null) sessionExpired.value = true }
        }
        viewModelScope.launch {
            container.notifications.incoming.collect { n ->
                toast("${n.title}: ${n.body}", ToastType.Info)
                // Push events drive freshness; polls are just the fallback.
                // The web's setTimeout(refetch, 800) per event, coalesced: a
                // burst of alerts (a busy hour, a replayed backlog) costs one
                // refetch 800 ms after the first, not one per alert; an alert
                // that lands while that refetch runs schedules the next.
                when (n.type) {
                    "new_conversation", "human_transfer", "intercept", "transfer", "media_escalation" -> inboxKick.kick()
                    "order_update" -> ordersKick.kick()
                }
            }
        }
        // Keyed by who is signed in, not by the session object: a token refresh
        // or a profile update saves a new Session for the same agent, and
        // must not reload snapshots and restart every poll.
        viewModelScope.launch {
            var last: String? = null
            session.map { it?.agentId }.distinctUntilChanged().collect { id ->
                if (id == null) { stopPolling(); ordersRead.cancel(); dropAgentStore(); last = null; return@collect }
                // Someone else signed in without a sign-out in between (a
                // restored session, a re-login as another agent): nothing of
                // the previous agent's may stay on screen.
                if (last != null && last != id) clearAgentState()
                // A view restored after a process death belongs to whoever was
                // signed in then: someone else starts on the inbox.
                val owner = saved.get<String>(KEY_OWNER)
                if (owner != null && owner != id) resetNav()
                saved[KEY_OWNER] = id
                last = id
                onSignedIn()
            }
        }
        // Frames sent while the socket was down (a dead network, a restart of
        // the API, the app backgrounded without live mode) are gone for good:
        // catch up on what the socket would have told us. The web has no such
        // hook — its polls eventually notice.
        viewModelScope.launch {
            container.socket.reconnected.collect {
                if (session.value == null) return@collect
                // The inbox (alive from sign-in) catches itself up on reconnect —
                // list, open thread and draft — so asking it too would fetch twice.
                if (clock() - lastOrdersFetch > CATCH_UP_FRESH_MS) refetchOrders()
            }
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
        // A link that arrived at the login screen, replayed once signed in.
        pendingLink?.let { pendingLink = null; applyDeepLink(it) }
        stopPolling()
        pollers += poll(180_000) { refetchAgentsNow() }
        pollers += poll(300_000) { refetchCatalogNow() }
        pollers += poll(90_000) { refetchOrdersNow() }
    }

    private fun stopPolling() { pollers.forEach { it.cancel() }; pollers.clear() }

    /**
     * usePolling(): fetch now and every [everyMs] while the app is in the
     * foreground; ticks pause in the background, and coming back to the
     * foreground refetches at once (the web's visibilitychange handler).
     */
    private fun poll(everyMs: Long, fetch: suspend () -> Unit): Job = viewModelScope.launch {
        val fg = container.foreground
        while (isActive) {
            runCatching { fetch() }
            // Wait out the interval — unless the app leaves and comes back
            // meanwhile, which refetches at once.
            val returned = withTimeoutOrNull(everyMs) { fg.first { !it }; fg.first { it } }
            if (returned == null && !fg.value) fg.first { it }
        }
    }

    fun refetchMe(attempt: Int = 1) {
        val who = scope
        viewModelScope.launch {
            runCatching { api.profile.me() }
                .onSuccess {
                    // Signed out (or in as someone else) while it was in flight.
                    if (scope != who || who == null) return@onSuccess
                    _me.value = it
                    container.snapshots.write(scope, "me", Agent.serializer(), it)
                    // A NextAuth sign-in (route.ts) carries no role: /admin/me is where it
                    // comes from. FastAPI's token response already carries the real one.
                    val nextAuth = session.value?.mode == "nextauth"
                    container.auth.updateProfile(
                        it.name, it.email,
                        role = it.role.takeIf { nextAuth }, isSuperuser = it.isSuperuser.takeIf { nextAuth },
                    )
                }
                .onFailure { e ->
                    // A dead session is the dialog's business; retrying can't help.
                    val expired = (e as? ke.co.bethanyhouse.neema.core.net.ApiException)?.status == 401
                    if (attempt < 3 && !expired && scope == who) { delay(attempt * 500L); refetchMe(attempt + 1) }
                }
        }
    }

    /**
     * Fetch, then publish only if the same agent is still signed in: a slow
     * answer that lands after a sign-out or a switch of agent is dropped.
     */
    private suspend inline fun <T> forCurrentAgent(fetch: () -> T, publish: (String, T) -> Unit) {
        val who = scope ?: return
        val value = fetch()
        if (scope == who) publish(who, value)
    }

    private suspend fun refetchAgentsNow() = forCurrentAgent({ api.agents.list() }) { who, list ->
        _agents.value = list
        container.snapshots.write(who, "agents", ListSerializer(Agent.serializer()), list)
    }
    private suspend fun refetchOrdersNow() = ordersRead.run()
    private suspend fun fetchOrdersNow() = forCurrentAgent({ api.orders.list() }) { who, list ->
        lastOrdersFetch = clock()
        _orders.value = list
        container.snapshots.write(who, "orders", ListSerializer(Order.serializer()), list)
    }
    private suspend fun refetchCatalogNow() = forCurrentAgent({ api.catalog.list() }) { who, list ->
        _catalog.value = list
        container.snapshots.write(who, "catalog", ListSerializer(CatalogItem.serializer()), list)
    }

    fun refetchAgents() { viewModelScope.launch { runCatching { refetchAgentsNow() } } }
    fun refetchOrders() { viewModelScope.launch { runCatching { refetchOrdersNow() } } }
    /** Refetch orders and return when done (pull-to-refresh spinners). Throws on failure. */
    suspend fun refreshOrders() = refetchOrdersNow()
    suspend fun refreshAgents() = refetchAgentsNow()
    suspend fun refreshCatalog() = refetchCatalogNow()
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

    /**
     * page.tsx's `currentAgent`: the signed-in agent's row in the team list
     * (GET /admin/agents), the only place role_permissions and
     * custom_permissions come from. The web finds it by email; this finds it
     * by id first (the same agent, robust to an email edit in flight), then
     * by email. Null until the team list has loaded (or been restored from
     * this agent's snapshot).
     */
    val teamRow: Agent?
        get() {
            val agents = _agents.value
            val me = _me.value
            val id = me?.id ?: session.value?.agentId
            val email = me?.email?.ifBlank { null } ?: session.value?.email
            return agents.find { it.id == id }
                ?: email?.let { e -> agents.find { it.email.equals(e, ignoreCase = true) } }
        }

    /**
     * getAgentPermissions(currentAgent) — or nothing at all while there is no
     * team row, exactly as the web's `can()` returns false then: gated nav
     * items appear once the team list lands, never before.
     */
    fun permissions(): List<String> = teamRow?.let(Perms::of) ?: emptyList()

    /** page.tsx `can(perm)`: the one permission test every feature uses. */
    fun can(perm: String): Boolean = perm in permissions()

    /** The nav, gated exactly as page.tsx builds its desktopNavItems. */
    fun navItems(): List<NavItem> = buildNavItems(
        can = ::can,
        humanConvs = inboxSummary.value?.human ?: 0,
        pendingOrders = _orders.value.count { it.status == "pending" },
    )

    /**
     * page.tsx `isAdmin`: the session's role is admin, or the team row's role
     * is admin, or the team row is a superuser, or `can(manage_agents)`.
     */
    val isAdmin: Boolean
        get() {
            val row = teamRow
            return session.value?.role == "admin" || row?.role == "admin" || row?.isSuperuser == true || can(Perms.MANAGE_AGENTS)
        }

    /** What the signed-in agent may do, for screens that recompose when it changes. */
    data class Access(val permissions: Set<String>, val isAdmin: Boolean) {
        fun can(perm: String) = perm in permissions
    }

    private val _access = MutableStateFlow(Access(emptySet(), false))
    /**
     * [can] / [isAdmin] as state: re-derived whenever /admin/me, the team list
     * or the session changes (the 180 s agents poll, a 403's refetch), so a
     * screen that collects it updates the moment an admin edits this agent's
     * role. [can] itself always reads the latest values directly.
     */
    val access: StateFlow<Access> = _access.asStateFlow()

    private fun republishAccess() { _access.value = Access(permissions().toSet(), isAdmin) }

    /** GETs of the team list and /admin/me folded into one per burst of 403s. */
    private val forbiddenRefresh = Coalescer(viewModelScope, FORBIDDEN_WINDOW_MS) {
        lastForbiddenRefresh = clock()
        refetchMe()
        refetchAgentsNow()
    }
    @Volatile private var lastForbiddenRefresh = Long.MIN_VALUE / 2

    // After the properties above exist (initialisers run in declaration order).
    init {
        viewModelScope.launch { container.http.forbidden.collect { onForbidden() } }
        viewModelScope.launch {
            combine(_agents, _me, session) { _, _, _ -> }.collect { republishAccess() }
        }
    }

    /**
     * The server refused something (403): this agent's permissions may have
     * changed since the app last read them. Rereads /admin/me and the team
     * list (coalesced over [FORBIDDEN_WINDOW_MS], at most once per
     * [FORBIDDEN_COOLDOWN_MS]) so the nav and every [can] check correct
     * themselves without waiting for the 180 s poll. NeemaHttp reports every
     * 403 here on its own; a feature may also call it directly.
     */
    fun onForbidden() {
        if (session.value == null) return
        if (clock() - lastForbiddenRefresh < FORBIDDEN_COOLDOWN_MS) return
        forbiddenRefresh.kick()
    }

    /**
     * Switch view, remembering where the agent came from for system back.
     * The web's view is plain state (no history entry), so the browser's
     * back leaves the dashboard; on a phone that would throw the agent out
     * of the app from any view, so the app keeps a short history instead —
     * each view at most once, most recent last — and back walks it: the
     * previous view, then the inbox, and only then out of the app.
     */
    fun navigate(v: ViewId) {
        val from = _view.value
        if (v == from) return
        history.remove(v)
        history.addLast(from)
        while (history.size > HISTORY_MAX) history.removeFirst()
        _view.value = v
        saveNav()
    }

    /**
     * System back with nothing above the view to close: the previous view,
     * else the inbox. False when already on the inbox with nowhere to go
     * back to (the system then leaves the app).
     */
    fun back(): Boolean {
        val to = history.removeLastOrNull() ?: ViewId.Conversations.takeIf { _view.value != it } ?: return false
        _view.value = to
        saveNav()
        return true
    }

    private fun saveNav() {
        saved[KEY_VIEW] = _view.value.name
        saved[KEY_HISTORY] = ArrayList(history.map { it.name })
        _canGoBack.value = history.isNotEmpty() || _view.value != ViewId.Conversations
    }

    private fun resetNav() {
        history.clear()
        _view.value = ViewId.Conversations
        saveNav()
    }

    fun openConversationFor(key: String) { openConvKey.value = key; navigate(ViewId.Conversations) }
    fun focusCalls(waId: String) { callsFocusKey.value = waId; navigate(ViewId.Calls) }

    /**
     * page.tsx's deep links: `?open=<wa_id>[&ref=<order>]` opens that chat;
     * otherwise `?view=<name>` switches view, and `?view=calls&caller=<wa_id>`
     * also focuses the call console on that customer. Unknown views are ignored.
     */
    fun applyDeepLink(open: String?, ref: String?, view: String?, caller: String?) =
        applyDeepLink(DeepLink(open, ref, view, caller))

    /**
     * Signed out, the link is kept and replayed right after sign-in (the web
     * stashes it in sessionStorage across the /login redirect). A newer link
     * replaces an older one; sign-out drops it.
     */
    fun applyDeepLink(link: DeepLink) {
        if (link.isEmpty) return
        if (session.value == null) { pendingLink = link; return }
        val (open, ref, view, caller) = link
        val v = ViewId.fromWeb(view)
        when {
            !open.isNullOrBlank() -> openConversationFor(if (!ref.isNullOrBlank()) "$open|$ref" else open)
            v == ViewId.Calls && !caller.isNullOrBlank() -> focusCalls(caller)
            v != null -> navigate(v)
        }
    }

    /**
     * A tap on one of our system notifications (Notifier's extras): mark the
     * bell entry read, then go where it points — through [applyDeepLink], so
     * a tap that finds the agent signed out waits for sign-in too.
     */
    fun openFromNotification(convKey: String?, view: String?, notificationId: String?) {
        notificationId?.let { container.notifications.markRead(it) }
        applyDeepLink(DeepLink(open = convKey, ref = null, view = view, caller = null))
    }

    fun toast(message: String, type: ToastType = ToastType.Success) { _toasts.tryEmit(Toast(message, type)) }

    /**
     * Friendly message for a failed call, for toasts and inline errors: every
     * status, offline and timeouts, in words for people ([ErrorText]).
     */
    fun errorText(t: Throwable): String = ke.co.bethanyhouse.neema.core.net.ErrorText.of(t)

    fun onReauthenticated() {
        sessionExpired.value = false
        refetchMe(); refetchAgents(); refetchOrders(); refetchCatalog(); refreshInbox()
    }

    /**
     * Sidebar.tsx's sign-out. A live call is ended first and its terminate
     * request given up to [SIGN_OUT_CALL_MS] to reach the server BEFORE the
     * token goes — cleared first, the request would leave without one and
     * the customer's phone would stay on the line. Meanwhile [signingOut]
     * is true (the web's spinner over the account button) and further taps
     * are ignored. Then: the token, the bell, and every per-agent state go;
     * the session change drops the agent's screens (cancelling their work).
     */
    fun logout() {
        if (signOutJob?.isActive == true) return
        stopPolling()
        // In-flight reads of this agent's orders go with the polls.
        ordersRead.cancel()
        _signingOut.value = true
        signOutJob = viewModelScope.launch {
            try {
                withTimeoutOrNull(SIGN_OUT_CALL_MS) {
                    try { endCall() } catch (e: CancellationException) { throw e } catch (_: Exception) { /* sign out regardless */ }
                }
            } finally {
                container.auth.logout()
                container.notifications.clear()
                clearAgentState()
                pendingLink = null
                _signingOut.value = false
            }
        }
    }

    /** Forget everything that belonged to the signed-in agent. */
    private fun clearAgentState() {
        ordersRead.cancel()
        _me.value = null; _agents.value = emptyList(); _orders.value = emptyList(); _catalog.value = emptyList()
        inboxSummary.value = null
        openConvKey.value = null
        callsFocusKey.value = null
        sessionExpired.value = false
        immersive.value = false
        lastOrdersFetch = 0L
        resetNav()
    }
}
