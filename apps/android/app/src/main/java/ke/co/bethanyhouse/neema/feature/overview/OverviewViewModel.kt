package ke.co.bethanyhouse.neema.feature.overview

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.NeemaApplication
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.api.InboxQuery
import ke.co.bethanyhouse.neema.core.model.Attribution
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.Stats
import ke.co.bethanyhouse.neema.feature.reports.quietly
import ke.co.bethanyhouse.neema.feature.reports.attempt
import ke.co.bethanyhouse.neema.feature.reports.friendlyError
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.ws.str
import ke.co.bethanyhouse.neema.feature.reports.Coalescer
import ke.co.bethanyhouse.neema.feature.reports.ScreenLife
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * State for the Analytics (overview) screen. Headline counts come from the
 * server (GET /admin/stats, counted by the database); attribution from
 * GET /admin/attribution; human-held threads from the inbox's "human" tab —
 * the web's OverviewView does exactly these three calls and polls stats and
 * intercepts every 30 s while visible.
 */
class OverviewViewModel(private val dash: DashboardViewModel) : ViewModel() {
    companion object {
        /** OverviewView's interval. */
        const val POLL_MS = 30_000L
        /** Notifications after which a headline figure has moved. */
        val RELOAD_ON = setOf(
            "order_update", "new_conversation", "human_transfer", "media_escalation",
            "intercept", "transfer", "system", "take_back", "hub_event",
        )
    }

    private val _stats = MutableStateFlow<Stats?>(null)
    val stats: StateFlow<Stats?> = _stats.asStateFlow()

    private val _statsLoading = MutableStateFlow(true)
    val statsLoading: StateFlow<Boolean> = _statsLoading.asStateFlow()

    private val _statsError = MutableStateFlow<String?>(null)
    /**
     * Why the server's headline counts couldn't be read, while the cards show
     * the phone's own estimate instead; null once they arrive.
     */
    val statsError: StateFlow<String?> = _statsError.asStateFlow()

    private val _attrib = MutableStateFlow<Attribution?>(null)
    val attrib: StateFlow<Attribution?> = _attrib.asStateFlow()

    private val _humanRows = MutableStateFlow<List<Conversation>?>(null)
    /** The latest human-held threads (server-side "human" tab, 10 rows). */
    val humanRows: StateFlow<List<Conversation>?> = _humanRows.asStateFlow()

    private val _fallbackConvs = MutableStateFlow<List<Conversation>>(emptyList())
    /**
     * The web falls back to the inbox's loaded rows when /stats fails. The
     * phone has no such rows here, so it fetches the inbox's first page —
     * only when stats could not be loaded.
     */
    val fallbackConvs: StateFlow<List<Conversation>> = _fallbackConvs.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    /**
     * OverviewView loads on mount and re-reads stats and intercepts every 30 s
     * while the tab is visible. Here: only while this screen is on display and
     * the app in front; every return to it (or to the app) and every socket
     * reconnect reloads all three quietly — no spinner, figures kept on failure.
     */
    val life = ScreenLife(
        viewModelScope, dash.foreground, dash.container.socket.connected,
        pollMs = POLL_MS, poll = ::loadLive, catchUp = ::catchUp,
    )

    /** A live event moved a headline figure: re-read stats and intercepts (800 ms, coalesced). */
    private val onEvent = Coalescer(viewModelScope, ScreenLife.EVENT_WINDOW_MS, ::loadLive)

    init {
        viewModelScope.launch { loadAll() }
        // Notifications that change the open / human / AI / order counts: the
        // web refetches only its orders list on `order_update` and leaves the
        // figures to the 30 s poll; here they follow at once while on display
        // (off-screen, the next visit reloads anyway).
        viewModelScope.launch {
            dash.container.notifications.incoming.collect { n ->
                if (n.type in RELOAD_ON && life.active) onEvent.kick()
            }
        }
        // A thread changing hands (intercept / release / transfer) moves the
        // human and AI counts and the "Human intercepts" feed.
        viewModelScope.launch {
            dash.container.socket.events.collect { e ->
                if (e.str("type") == "intercept_changed" && life.active) onEvent.kick()
            }
        }
        // The dashboard's orders poll found a change (the pending badge moved):
        // keep the order figures in step with it.
        viewModelScope.launch {
            dash.orders.drop(1).collect { if (life.active) onEvent.kick() }
        }
    }

    /** The poll's pair: server stats and the human-held threads. */
    private suspend fun loadLive() {
        coroutineScope {
            launch { quietly { _stats.value = dash.api.stats.overview(); _statsError.value = null } }
            launch { loadHuman() }
        }
    }

    /** A return to the screen: the mount-time three, without the first-load spinner. */
    private suspend fun catchUp() {
        coroutineScope {
            launch { loadLive() }
            launch { quietly { _attrib.value = dash.api.attribution() } }
        }
    }

    /** Loads everything; answers why the headline figures failed, or null. */
    private suspend fun loadAll(): Throwable? {
        _statsLoading.value = true
        val failed = attempt { dash.api.stats.overview() }
            .onSuccess { _stats.value = it; _statsError.value = null }
            .exceptionOrNull()
        if (failed != null && _stats.value == null) {
            // A failed pull-to-refresh keeps the figures already on screen
            // (like the web's 30 s poll); only a first load falls back — and,
            // unlike the web, says the cards are an estimate, and why.
            _statsError.value = friendlyError(failed, fallback = "The server couldn't count them just now.")
            loadFallback()
        }
        _statsLoading.value = false
        attempt { dash.api.attribution() }.onSuccess { _attrib.value = it }
        loadHuman()
        // The web's feed reads `humanRows ?? conversations`: with no human tab,
        // the intercepts come from the inbox's own rows.
        if (_humanRows.value == null && _fallbackConvs.value.isEmpty()) loadFallback()
        return failed
    }

    private suspend fun loadFallback() {
        attempt { dash.api.conversations.page(InboxQuery(), limit = 50) }
            .onSuccess { _fallbackConvs.value = it.items }
    }

    private suspend fun loadHuman() {
        attempt { dash.api.conversations.page(InboxQuery(tab = "human"), limit = 10) }
            .onSuccess { _humanRows.value = it.items }
    }

    /**
     * Pull-to-refresh (and the notice's Retry): the three calls, plus the
     * orders, team and catalogue the fallbacks read — the spinner lasts until
     * all land. A refresh that couldn't reach the server says so; the
     * figures already on screen stay.
     */
    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            try {
                val failed = coroutineScope {
                    launch { quietly { dash.refreshOrders() } }
                    launch { quietly { dash.refreshAgents() } }
                    launch { quietly { dash.refreshCatalog() } }
                    loadAll()
                }
                if (failed != null && _stats.value != null)
                    dash.toast("Couldn't refresh the figures. ${friendlyError(failed)}", ToastType.Error)
            } finally { _refreshing.value = false }
        }
    }
}
