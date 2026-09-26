package ke.co.bethanyhouse.neema.feature.orders

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.util.ScreenLife
import ke.co.bethanyhouse.neema.core.util.SavesUi
import ke.co.bethanyhouse.neema.core.util.SingleFlight
import ke.co.bethanyhouse.neema.core.util.str
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch

/**
 * OrdersView's local state. The orders themselves are the dashboard's polled
 * list ([DashboardViewModel.orders]); this holds the filter, search, page, the
 * open order, which row is mid-update and why the last read failed.
 */
class OrdersViewModel(private val dash: DashboardViewModel) : ViewModel(), SavesUi {

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

    /**
     * Why the last read of the list failed (null when it worked). With orders
     * on screen it is a banner over them; with none it replaces "No orders
     * found", which would be a lie. The dashboard's poller keeps trying, and
     * any good answer clears it.
     */
    private val _loadError = MutableStateFlow<String?>(null)
    val loadError: StateFlow<String?> = _loadError.asStateFlow()

    /**
     * This screen's reads of the list, one on the wire at a time: a pull, a
     * Retry, a catch-up on return and the settle after a status change that
     * pile up on a slow network share one round trip instead of stacking.
     */
    private val reads = SingleFlight(viewModelScope) {
        try {
            dash.refreshOrders()
            _loadError.value = null
            true
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _loadError.value = dash.salesFailure(e).message()
            false
        }
    }

    /**
     * The list is the dashboard's 90 s poll, which already pauses in the
     * background and refetches on return (usePolling). On top of that, while
     * this screen is on display: coming back to it re-reads the orders, and so
     * does the live socket reconnecting — an `order_update` sent while it was
     * down is lost, and the pending badge must not wait 90 s to catch up.
     */
    val life = ScreenLife(
        viewModelScope, dash.foreground, dash.container.socket.connected,
        catchUpOnForeground = false, catchUp = { awaitRefetch() },
    )

    init {
        if (dash.orders.value.isEmpty()) {
            viewModelScope.launch {
                awaitRefetch()
                _initialLoading.value = false
            }
        }
        // A good read from anywhere (the dashboard's own poll included) clears the error.
        viewModelScope.launch { dash.orders.drop(1).collect { _loadError.value = null } }
    }

    fun setFilter(f: String) { filter.value = f; page.value = 1 }
    /** Tapping the active status card clears it (the web's toggle). */
    fun toggleFilter(f: String) = setFilter(if (filter.value == f) "all" else f)
    fun setSearch(q: String) { search.value = q; page.value = 1 }
    fun setPage(p: Int) { page.value = p }

    fun select(order: Order?) { _selectedId.value = order?.id }

    /** Whether the list has been read at least once (so an open order missing from it is really gone). */
    val loaded: Boolean get() = dash.orders.value.isNotEmpty() || (!_initialLoading.value && _loadError.value == null)

    // ── Process death: the filter, search, page and the open order come back ──
    override var uiAttached = false

    /** The list's scroll (first visible item, its offset), kept current by the screen. */
    var scroll: Pair<Int, Int> = 0 to 0

    private val _pendingScroll = MutableStateFlow<Pair<Int, Int>?>(null)
    /** A scroll restored after process death, applied by the screen once the orders are in. */
    val pendingScroll: StateFlow<Pair<Int, Int>?> = _pendingScroll.asStateFlow()
    fun scrollRestored() { _pendingScroll.value = null }

    override fun saveUi(): Map<String, Any?> {
        // Not applied yet (the orders are still loading): that is still where the agent was.
        val at = _pendingScroll.value ?: scroll
        return mapOf(
            "filter" to filter.value, "search" to search.value, "page" to page.value, "selected" to _selectedId.value,
            "scrollIndex" to at.first, "scrollOffset" to at.second,
        )
    }

    override fun restoreUi(saved: Map<String, Any?>) {
        saved.str("filter")?.let { if (it == "all" || it in ORDER_STATUSES) filter.value = it }
        saved.str("search")?.let { search.value = it }
        (saved["page"] as? Int)?.let { page.value = it.coerceAtLeast(1) }
        _selectedId.value = saved.str("selected")
        val index = (saved["scrollIndex"] as? Int)?.coerceAtLeast(0) ?: 0
        val offset = (saved["scrollOffset"] as? Int)?.coerceAtLeast(0) ?: 0
        if (index > 0 || offset > 0) { scroll = index to offset; _pendingScroll.value = index to offset }
    }

    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            awaitRefetch()
            _refreshing.value = false
        }
    }

    /** The error state's Retry: the first load again, with its spinner. */
    fun retry() {
        if (_initialLoading.value || _refreshing.value) return
        viewModelScope.launch {
            _initialLoading.value = true
            awaitRefetch()
            _initialLoading.value = false
        }
    }

    /**
     * Refetch through the dashboard and return when the round trip is over
     * ([DashboardViewModel.refreshOrders] suspends until the list has landed).
     * A failure keeps the list as it was and says why; true when it worked.
     */
    private suspend fun awaitRefetch(): Boolean = reads.run()

    /**
     * PATCH the order's status. The web toasts "Failed to update order" on any
     * throw; on a phone network that is often a lie — the PATCH can land and
     * its answer be lost — so a failure that may have happened is settled by
     * re-reading the list: the order's real status decides what is said. A
     * 404 means someone deleted it: the list is re-read (the row goes) and the
     * sheet closes. On any other failure the sheet stays open for another tap.
     */
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
                val f = dash.salesFailure(e)
                when {
                    f.kind == FailKind.NotFound -> {
                        dash.toast("This order no longer exists — it may have been deleted", ToastType.Error)
                        awaitRefetch()
                        if (_selectedId.value == id) _selectedId.value = null
                    }
                    f.mayHaveHappened -> {
                        val read = awaitRefetch()
                        val now = dash.orders.value.find { it.id == id }
                        when {
                            read && now?.status == status -> {
                                if (_selectedId.value == id) _selectedId.value = null
                                dash.toast("Order marked as $status")
                            }
                            read -> dash.toast("Order not updated — ${f.message().lowerFirst()}", ToastType.Error)
                            else -> dash.toast("No answer from the server — the order may not have updated. Pull down to check.", ToastType.Error)
                        }
                    }
                    // The session-expired dialog says so; the sheet waits for a retry after sign-in.
                    f.kind == FailKind.SessionExpired -> Unit
                    else -> dash.toast("Failed to update order — ${f.message().lowerFirst()}", ToastType.Error)
                }
            } finally {
                _updating.value = null
            }
        }
    }
}

/** "No connection — …" → "no connection — …", for the tail of a sentence. */
internal fun String.lowerFirst(): String = replaceFirstChar { it.lowercase() }
