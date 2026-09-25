package ke.co.bethanyhouse.neema.feature.overview

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.NeemaApplication
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.api.InboxQuery
import ke.co.bethanyhouse.neema.core.model.Attribution
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.Stats
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * State for the Analytics (overview) screen. Headline counts come from the
 * server (GET /admin/stats, counted by the database); attribution from
 * GET /admin/attribution; human-held threads from the inbox's "human" tab —
 * the web's OverviewView does exactly these three calls and polls stats and
 * intercepts every 30 s while visible.
 */
class OverviewViewModel(private val dash: DashboardViewModel) : ViewModel() {

    private val _stats = MutableStateFlow<Stats?>(null)
    val stats: StateFlow<Stats?> = _stats.asStateFlow()

    private val _statsLoading = MutableStateFlow(true)
    val statsLoading: StateFlow<Boolean> = _statsLoading.asStateFlow()

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

    init {
        viewModelScope.launch { loadAll() }
        viewModelScope.launch {
            val fg = NeemaApplication.instance.foreground
            while (isActive) {
                delay(30_000)
                // Like the web's visibilityState check: no polling in the background.
                if (!fg.value) continue
                runCatching { dash.api.stats.overview() }.onSuccess { _stats.value = it }
                loadHuman()
            }
        }
    }

    private suspend fun loadAll() {
        _statsLoading.value = true
        runCatching { dash.api.stats.overview() }
            .onSuccess { _stats.value = it }
            .onFailure {
                _stats.value = null
                runCatching { dash.api.conversations.page(InboxQuery(), limit = 50) }
                    .onSuccess { _fallbackConvs.value = it.items }
            }
        _statsLoading.value = false
        _attrib.value = runCatching { dash.api.attribution() }.getOrNull()
        loadHuman()
    }

    private suspend fun loadHuman() {
        runCatching { dash.api.conversations.page(InboxQuery(tab = "human"), limit = 10) }
            .onSuccess { _humanRows.value = it.items }
    }

    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            dash.refetchOrders(); dash.refetchAgents(); dash.refetchCatalog()
            loadAll()
            _refreshing.value = false
        }
    }
}
