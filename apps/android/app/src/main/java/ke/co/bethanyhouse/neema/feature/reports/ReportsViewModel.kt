package ke.co.bethanyhouse.neema.feature.reports

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Conversation
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.LocalDate

/** The web's `Range`. */
enum class ReportRange(val key: String, val label: String) {
    D7("7d", "Last 7 days"),
    D30("30d", "Last 30 days"),
    D90("90d", "Last 90 days"),
    Custom("custom", "Custom range"),
}

/** The web's `ReportTab`. */
enum class ReportTab(val label: String) {
    Overview("Overview"), Conversations("Conversations"), Orders("Orders"), Agents("Agents"),
}

/**
 * Reports aggregate a date range over EVERY conversation, so — like the web —
 * this screen fetches the full (un-paged) list itself, only while it is open.
 * Computing from the inbox's loaded rows would report on one page.
 */
class ReportsViewModel(private val dash: DashboardViewModel) : ViewModel() {

    private val _allConvs = MutableStateFlow<List<Conversation>?>(null)
    /** null while loading — never show zeros that look like real figures. */
    val allConvs: StateFlow<List<Conversation>?> = _allConvs.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    val tab = MutableStateFlow(ReportTab.Overview)
    val range = MutableStateFlow(ReportRange.D30)
    val customFrom = MutableStateFlow<LocalDate?>(null)
    val customTo = MutableStateFlow<LocalDate?>(null)

    init { load() }

    private suspend fun fetch() {
        runCatching { dash.api.conversations.list() }
            .onSuccess { _allConvs.value = it }
            .onFailure {
                // Keep what we had on a refresh; on first load fall back to empty.
                if (_allConvs.value == null) _allConvs.value = emptyList()
                dash.toast("Could not load conversations for this report.", ToastType.Error)
            }
    }

    private fun load() { viewModelScope.launch { fetch() } }

    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            dash.refetchOrders(); dash.refetchAgents()
            fetch()
            _refreshing.value = false
        }
    }
}
