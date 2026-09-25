package ke.co.bethanyhouse.neema.feature.orders

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Order
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

/**
 * OrdersView's local state. The orders themselves are the dashboard's polled
 * list ([DashboardViewModel.orders]); this holds the filter, search, page, the
 * open order and which row is mid-update.
 */
class OrdersViewModel(private val dash: DashboardViewModel) : ViewModel() {

    /** "all" or one of [ORDER_STATUSES]. */
    val filter = MutableStateFlow("all")
    val search = MutableStateFlow("")
    val page = MutableStateFlow(1)

    private val _selectedId = MutableStateFlow<String?>(null)
    /** The open order's id — the sheet re-reads the live row so a refetch shows through. */
    val selectedId: StateFlow<String?> = _selectedId.asStateFlow()

    private val _updating = MutableStateFlow<String?>(null)
    val updating: StateFlow<String?> = _updating.asStateFlow()

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    /**
     * True only while the very first fetch is in flight with nothing cached —
     * otherwise an empty list on first paint would claim "No orders found".
     */
    private val _initialLoading = MutableStateFlow(dash.orders.value.isEmpty())
    val initialLoading: StateFlow<Boolean> = _initialLoading.asStateFlow()

    init {
        if (dash.orders.value.isEmpty()) {
            viewModelScope.launch {
                awaitRefetch()
                _initialLoading.value = false
            }
        }
    }

    fun setFilter(f: String) { filter.value = f; page.value = 1 }
    /** Tapping the active status card clears it (the web's toggle). */
    fun toggleFilter(f: String) = setFilter(if (filter.value == f) "all" else f)
    fun setSearch(q: String) { search.value = q; page.value = 1 }
    fun setPage(p: Int) { page.value = p }

    fun select(order: Order?) { _selectedId.value = order?.id }

    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            awaitRefetch()
            _refreshing.value = false
        }
    }

    /** Ask the dashboard to refetch and wait (bounded) for the new list to land. */
    private suspend fun awaitRefetch() {
        dash.refetchOrders()
        withTimeoutOrNull(8_000) { dash.orders.drop(1).first() }
    }

    fun updateStatus(id: String, status: String) {
        if (_updating.value != null) return
        viewModelScope.launch {
            _updating.value = id
            try {
                dash.api.orders.updateStatus(id, status)
                dash.refetchOrders()
                if (_selectedId.value == id) _selectedId.value = null
                dash.toast("Order marked as $status")
            } catch (e: Exception) {
                dash.toast("Failed to update order — ${dash.errorText(e)}", ToastType.Error)
            } finally {
                _updating.value = null
            }
        }
    }
}
