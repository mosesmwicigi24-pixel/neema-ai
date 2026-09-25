package ke.co.bethanyhouse.neema.feature.catalog

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.PriceAudit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull

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
 * Catalog state. The list itself is the dashboard's shared, polled
 * `dash.catalog`; this holds the filters and the price audit. Like the web
 * view it is READ-ONLY: products, prices and stock live in the hub, the single
 * source of truth — nothing is written from here.
 */
class CatalogViewModel(private val dash: DashboardViewModel) : ViewModel() {

    val filter = MutableStateFlow("all")
    val search = MutableStateFlow("")

    private val _audit = MutableStateFlow<PriceAudit?>(null)
    val audit: StateFlow<PriceAudit?> = _audit.asStateFlow()
    val auditOpen = MutableStateFlow(false)

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    init { loadAudit() }

    /** A failed audit just stays hidden, as on the web. */
    private fun loadAudit() {
        viewModelScope.launch { runCatching { dash.api.catalog.audit() }.onSuccess { _audit.value = it } }
    }

    /** Pull-to-refresh: the audit, and the shared catalogue (waiting briefly for it to land). */
    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            loadAudit()
            dash.refetchCatalog()
            withTimeoutOrNull(3_000) { dash.catalog.drop(1).first() }
            _refreshing.value = false
        }
    }
}
