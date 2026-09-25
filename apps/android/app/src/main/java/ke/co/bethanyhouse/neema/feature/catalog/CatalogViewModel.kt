package ke.co.bethanyhouse.neema.feature.catalog

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.PriceAudit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlinx.serialization.json.putJsonArray

/** What the add/edit form collects (CreateCatalogPayload). */
data class CatalogDraft(
    val sku: String = "",
    val name: String = "",
    val price: String = "",
    val unit: String = "",
    val category: String = "",
    val description: String = "",
    /** Comma-separated. */
    val aliases: String = "",
    val inStock: Boolean = true,
) {
    companion object {
        fun of(i: CatalogItem) = CatalogDraft(
            sku = i.sku, name = i.name,
            price = if (i.price == Math.floor(i.price)) i.price.toLong().toString() else i.price.toString(),
            unit = i.unit.orEmpty(), category = i.rawCategory.orEmpty(), description = i.description.orEmpty(),
            aliases = i.aliases.joinToString(", "), inStock = i.inStock,
        )
    }

    fun toJson(): JsonObject = buildJsonObject {
        put("sku", sku.trim())
        put("name", name.trim())
        put("price", price.trim().toDouble())
        put("unit", unit.trim().ifEmpty { null })
        put("category", category.trim().ifEmpty { null })
        put("description", description.trim().ifEmpty { null })
        putJsonArray("aliases") {
            aliases.split(',').map { it.trim() }.filter { it.isNotEmpty() }.forEach { add(JsonPrimitive(it)) }
        }
        put("in_stock", inStock)
    }
}

/**
 * Catalog state. The list itself is the dashboard's shared, polled
 * `dash.catalog`; this holds the filters, the price audit and the (local-item)
 * mutations. Hub rows are never written — the hub is their source of truth.
 */
class CatalogViewModel(private val dash: DashboardViewModel) : ViewModel() {

    val filter = MutableStateFlow("all")
    val search = MutableStateFlow("")

    private val _audit = MutableStateFlow<PriceAudit?>(null)
    val audit: StateFlow<PriceAudit?> = _audit.asStateFlow()
    val auditOpen = MutableStateFlow(false)

    private val _refreshing = MutableStateFlow(false)
    val refreshing: StateFlow<Boolean> = _refreshing.asStateFlow()

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    init { loadAudit() }

    /** A failed audit just stays hidden, as on the web. */
    private fun loadAudit() {
        viewModelScope.launch { runCatching { dash.api.catalog.audit() }.onSuccess { _audit.value = it } }
    }

    /** Refetch the shared catalogue and wait (briefly) for the new list to land. */
    private suspend fun refetchAndWait() {
        dash.refetchCatalog()
        withTimeoutOrNull(3_000) { dash.catalog.drop(1).first() }
    }

    fun refresh() {
        viewModelScope.launch {
            _refreshing.value = true
            loadAudit()
            refetchAndWait()
            _refreshing.value = false
        }
    }

    private fun mutate(success: String, onDone: () -> Unit = {}, block: suspend () -> Unit) {
        viewModelScope.launch {
            _busy.value = true
            runCatching { block() }
                .onSuccess { dash.toast(success); onDone(); refetchAndWait() }
                .onFailure { dash.toast(dash.errorText(it), ToastType.Error) }
            _busy.value = false
        }
    }

    // The server answers with the raw DB row (price as a Decimal); we only
    // need to know it worked, then the shared list is refetched.
    private val http get() = dash.api.http

    fun create(d: CatalogDraft, onDone: () -> Unit) =
        mutate("Item added", onDone) { http.raw("POST", "/admin/catalog", http.jsonBody(d.toJson())) }

    fun update(item: CatalogItem, d: CatalogDraft, onDone: () -> Unit) =
        mutate("Item updated", onDone) { http.raw("PATCH", "/admin/catalog/${item.id}", http.jsonBody(d.toJson())) }

    fun toggleStock(item: CatalogItem) {
        val next = !item.inStock
        mutate(if (next) "Marked in stock" else "Marked out of stock") {
            http.raw("PATCH", "/admin/catalog/${item.id}", http.jsonBody(buildJsonObject { put("in_stock", next) }))
        }
    }

    fun delete(item: CatalogItem, onDone: () -> Unit = {}) =
        mutate("Item deleted", onDone) { dash.api.catalog.delete(item.id) }
}
