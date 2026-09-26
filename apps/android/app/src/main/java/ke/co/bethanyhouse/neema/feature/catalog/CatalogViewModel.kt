package ke.co.bethanyhouse.neema.feature.catalog

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.PriceAudit
import ke.co.bethanyhouse.neema.feature.reports.ScreenLife
import ke.co.bethanyhouse.neema.feature.reports.attempt
import ke.co.bethanyhouse.neema.feature.reports.friendlyError
import ke.co.bethanyhouse.neema.feature.reports.recheckAccessOn
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.feature.reports.cpu
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.mapLatest
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** The web's category list: every distinct, non-empty category, in catalogue order. */
internal fun catalogCategories(catalog: List<CatalogItem>): List<String> =
    catalog.map { it.category }.filter { it.isNotEmpty() }.distinct()

/**
 * The web's filter: the chosen category ("all" = any), then a case-insensitive
 * match of the search text against name, SKU or any alias.
 */
internal fun filterCatalog(catalog: List<CatalogItem>, filter: String, search: String): List<CatalogItem> {
    val q = search.lowercase()
    return catalog.filter { i ->
        (filter == "all" || i.category == filter) &&
            (q.isEmpty() || i.name.lowercase().contains(q) || i.sku.lowercase().contains(q) ||
                i.aliases.any { it.lowercase().contains(q) })
    }
}

/**
 * A catalogue with each product's searchable text lowercased once, so a
 * keystroke in the search box over 2,000 products compares strings instead
 * of lowercasing every name, SKU and alias again.
 */
internal class CatalogIndex(val items: List<CatalogItem>) {
    private val haystacks: List<List<String>> =
        items.map { i -> buildList(2 + i.aliases.size) { add(i.name.lowercase()); add(i.sku.lowercase()); i.aliases.forEach { add(it.lowercase()) } } }
    val categories: List<String> = catalogCategories(items)
    val inStock: Int = items.count { it.inStock }

    /** Exactly [filterCatalog]'s answer. */
    fun filter(filter: String, search: String): List<CatalogItem> {
        val q = search.lowercase()
        if (filter == "all" && q.isEmpty()) return items
        val out = ArrayList<CatalogItem>()
        items.forEachIndexed { n, i ->
            if ((filter == "all" || i.category == filter) && (q.isEmpty() || haystacks[n].any { it.contains(q) })) out += i
        }
        return out
    }
}

/** What the grid shows: the filtered products, the category menu, and the header's counts. */
class CatalogView(
    val filtered: List<CatalogItem>,
    val categories: List<String>,
    val total: Int,
    val inStock: Int,
) {
    val outStock: Int get() = total - inStock
}

/**
 * Catalog state. The list itself is the dashboard's shared, polled
 * `dash.catalog`; this holds the filters and the price audit. Like the web
 * view it is READ-ONLY: products, prices and stock live in the hub, the single
 * source of truth — nothing is written from here.
 */
@OptIn(ExperimentalCoroutinesApi::class)
class CatalogViewModel(private val dash: DashboardViewModel) : ViewModel() {

    val filter = MutableStateFlow("all")
    val search = MutableStateFlow("")

    private val cpu = dash.container.cpu

    /** The catalogue indexed once per poll (not once per keystroke). */
    private val index = dash.catalog.map(::CatalogIndex).flowOn(cpu)

    private fun viewOf(ix: CatalogIndex, f: String, q: String) =
        CatalogView(ix.filter(f, q), ix.categories, ix.items.size, ix.inStock)

    /**
     * The grid's contents, filtered off the main thread; a newer keystroke
     * cancels the search still running for the last one. Starts from the
     * catalogue already held, so the screen never flashes "No items found".
     */
    val view: StateFlow<CatalogView> =
        combine(index, filter, search) { ix, f, q -> Triple(ix, f, q) }
            .mapLatest { (ix, f, q) -> viewOf(ix, f, q) }
            .flowOn(cpu)
            .stateIn(viewModelScope, SharingStarted.Eagerly, viewOf(CatalogIndex(dash.catalog.value), filter.value, search.value))

    private val _audit = MutableStateFlow<PriceAudit?>(null)
    val audit: StateFlow<PriceAudit?> = _audit.asStateFlow()
    val auditOpen = MutableStateFlow(false)

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    private val _catalogError = MutableStateFlow<String?>(null)
    /**
     * Why the catalogue couldn't be read, when this screen asked and failed;
     * null once it arrives. With nothing to show the screen says this (and
     * offers Retry) instead of "No items found", which would be untrue.
     */
    val catalogError: StateFlow<String?> = _catalogError.asStateFlow()

    /**
     * The catalogue itself is the dashboard's 5-minute poll (paused in the
     * background, refetched on return). The price audit is CatalogView's
     * mount-time read: each return to this screen reads it again, as a
     * remount of the web view does, and the catalogue with it.
     */
    val life = ScreenLife(
        viewModelScope, dash.foreground, catchUpOnForeground = false,
        catchUp = {
            coroutineScope {
                launch { loadAudit() }
                launch { loadCatalog() }
            }
        },
    )

    init {
        viewModelScope.launch { loadAudit() }
        // The dashboard read the catalogue at sign-in; if that failed (a phone
        // offline at start) the list is empty until its 5-minute poll — ask now.
        if (dash.catalog.value.isEmpty()) viewModelScope.launch { loadCatalog() }
        // Any successful read (the dashboard's poll included) clears the notice.
        viewModelScope.launch { dash.catalog.collect { if (it.isNotEmpty()) _catalogError.value = null } }
    }

    /** The shared catalogue, remembering why it failed; answers the failure. */
    private suspend fun loadCatalog(): Throwable? =
        attempt { dash.refreshCatalog() }
            .onSuccess { _catalogError.value = null }
            .onFailure {
                _catalogError.value = friendlyError(it, fallback = "The server couldn't send the catalogue just now.")
                dash.recheckAccessOn(it)
            }
            .exceptionOrNull()

    /** The empty state's Retry. */
    fun retry() = refresh()

    /**
     * GET /admin/catalog/audit (admin.py `catalog_price_audit`). A failed
     * audit just stays hidden, as on the web; a failed refresh keeps the
     * banner already shown.
     */
    private suspend fun loadAudit() {
        attempt { dash.api.catalog.audit() }
            .onSuccess { _audit.value = it }
            .onFailure { dash.recheckAccessOn(it) }
    }

    /** Pull-to-refresh: the audit and the shared catalogue, the spinner lasting until both have landed (or failed). */
    fun refresh() {
        if (_refreshing.value) return
        viewModelScope.launch {
            _refreshing.value = true
            try {
                var failed: Throwable? = null
                coroutineScope {
                    launch { loadAudit() }
                    launch { failed = loadCatalog() }
                }
                // With products on screen they stay; the pull just says it didn't reach the hub.
                failed?.takeIf { dash.catalog.value.isNotEmpty() }?.let {
                    dash.toast("Couldn't refresh the catalogue. ${friendlyError(it)}", ToastType.Error)
                }
            } finally { _refreshing.value = false }
        }
    }
}
