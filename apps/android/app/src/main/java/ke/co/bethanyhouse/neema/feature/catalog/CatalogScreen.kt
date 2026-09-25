package ke.co.bethanyhouse.neema.feature.catalog

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.SubcomposeAsyncImage
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.PriceAudit
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.ConfirmDialog
import ke.co.bethanyhouse.neema.core.ui.components.SearchField
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt

// ── Category glyphs and card tints (the web's catEmoji / catColors) ─────────

internal val catEmoji = mapOf(
    "Anointing Oil" to "🕯️", "Communion Wafers" to "🍞", "Communion Cups" to "🥛",
    "Prefilled Cups" to "🍷", "Communion Wine" to "🍾", "Communion Trays" to "🫙",
    "Communion Accessories" to "🧴", "Clergy Apparel" to "👕", "Clergy Vestments" to "👘",
    "anointing" to "🕯️", "communion" to "🍷", "vestments" to "👘", "trays" to "🫙",
    "wine" to "🍾", "apparel" to "👕",
)

internal fun glyph(category: String?): String = catEmoji[category ?: ""] ?: "📦"

// Tailwind *-50 shades, as gradient stops.
private val Amber50 = Color(0xFFFFFBEB); private val Yellow50 = Color(0xFFFEFCE8)
private val Orange50 = Color(0xFFFFF7ED); private val Sky50 = Color(0xFFF0F9FF)
private val Blue50 = Color(0xFFEFF6FF); private val Red50 = Color(0xFFFEF2F2)
private val Rose50 = Color(0xFFFFF1F2); private val Pink50 = Color(0xFFFDF2F8)
private val Stone50 = Color(0xFFFAFAF9); private val Slate50 = Color(0xFFF8FAFC)
private val Teal50 = Color(0xFFF0FDFA); private val Cyan50 = Color(0xFFECFEFF)
private val Indigo50 = Color(0xFFEEF2FF); private val Purple50 = Color(0xFFFAF5FF)
private val Violet50 = Color(0xFFF5F3FF); private val Stone100 = Color(0xFFF5F5F4)

private val catColors = mapOf(
    "Anointing Oil" to (Amber50 to Yellow50), "Communion Wafers" to (Orange50 to Amber50),
    "Communion Cups" to (Sky50 to Blue50), "Prefilled Cups" to (Red50 to Rose50),
    "Communion Wine" to (Red50 to Pink50), "Communion Trays" to (Stone50 to Slate50),
    "Communion Accessories" to (Teal50 to Cyan50), "Clergy Apparel" to (Blue50 to Indigo50),
    "Clergy Vestments" to (Purple50 to Violet50),
    "anointing" to (Amber50 to Yellow50), "communion" to (Red50 to Rose50),
    "vestments" to (Purple50 to Violet50), "trays" to (Stone50 to Slate50),
    "wine" to (Red50 to Pink50), "apparel" to (Blue50 to Indigo50),
)

@Composable
internal fun categoryBrush(category: String?): Brush {
    val (a, b) = catColors[category ?: ""] ?: (Stone50 to Stone100)
    // The pastel tints would glare on the night theme; soften them there.
    val alpha = if (Neema.colors.isDark) 0.12f else 1f
    return Brush.linearGradient(listOf(a.copy(alpha = alpha), b.copy(alpha = alpha)))
}

internal val Emerald600 = Color(0xFF059669)
internal val Red500 = Color(0xFFEF4444)

/** "1500" not "1500.0". */
internal fun num(v: Double): String = if (v == Math.floor(v) && !v.isInfinite()) Fmt.number(v.toLong()) else Fmt.number(v)

/** "$10" for whole dollars, "$9.50" otherwise (the audit's usd()). */
internal fun usd(v: Double): String =
    "$" + if (v == Math.floor(v)) Fmt.number(v.toLong()) else "%,.2f".format(java.util.Locale.US, v)

/** Price or "KES min – KES max" when the variants differ. */
internal fun priceText(i: CatalogItem): String {
    val lo = i.priceMinKes; val hi = i.priceMaxKes
    return if (lo != null && hi != null && lo != hi) "${Fmt.currency(lo)} – ${Fmt.currency(hi)}" else Fmt.currency(i.price)
}

/**
 * Port of components/views/CatalogView.tsx. The web view is a read-only look
 * at the live hub catalogue; hub rows stay read-only here too. Rows that live
 * in Neema's own table (a hub outage fallback, or items added here) can be
 * added, edited, stocked and deleted by agents with `manage_catalog`.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CatalogScreen(dash: DashboardViewModel) {
    val vm: CatalogViewModel = viewModel { CatalogViewModel(dash) }
    val catalog by dash.catalog.collectAsStateWithLifecycle()
    val filter by vm.filter.collectAsStateWithLifecycle()
    val search by vm.search.collectAsStateWithLifecycle()
    val audit by vm.audit.collectAsStateWithLifecycle()
    val auditOpen by vm.auditOpen.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val busy by vm.busy.collectAsStateWithLifecycle()
    dash.me.collectAsStateWithLifecycle() // recompose when permissions arrive
    val canManage = dash.can(Perms.MANAGE_CATALOG)
    val c = Neema.colors

    val categories = remember(catalog) { catalog.map { it.category }.filter { it.isNotEmpty() }.distinct() }
    val filtered = remember(catalog, filter, search) {
        val q = search.lowercase()
        catalog.filter { i ->
            (filter == "all" || i.category == filter) &&
                (q.isEmpty() || i.name.lowercase().contains(q) || i.sku.lowercase().contains(q) ||
                    i.aliases.any { it.lowercase().contains(q) })
        }
    }
    val inStock = catalog.count { it.inStock }
    val outStock = catalog.count { !it.inStock }

    var detail by remember { mutableStateOf<CatalogItem?>(null) }
    var editing by remember { mutableStateOf<CatalogItem?>(null) }
    var creating by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<CatalogItem?>(null) }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize().background(c.bg)) {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 600.dp
            LazyVerticalGrid(
                columns = GridCells.Adaptive(if (wide) 170.dp else 150.dp),
                contentPadding = PaddingValues(if (wide) 24.dp else 16.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                modifier = Modifier.fillMaxSize(),
            ) {
                audit?.let { a ->
                    if (a.currencyGaps.isNotEmpty() || a.perPiece.isNotEmpty()) {
                        item(span = { GridItemSpan(maxLineSpan) }, key = "audit") {
                            PriceAuditBanner(a, auditOpen) { vm.auditOpen.value = !auditOpen }
                        }
                    }
                }
                // ── Header ───────────────────────────────────────────────
                item(span = { GridItemSpan(maxLineSpan) }, key = "header") {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Catalog", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = c.text)
                            Text(
                                buildAnnotatedString {
                                    withStyle(SpanStyle(color = c.muted)) { append("${catalog.size} items") }
                                    withStyle(SpanStyle(color = Color(0xFFD6D3D1))) { append("  ·  ") }
                                    withStyle(SpanStyle(color = Emerald600)) { append("$inStock in stock") }
                                    if (outStock > 0) {
                                        withStyle(SpanStyle(color = Color(0xFFD6D3D1))) { append("  ·  ") }
                                        withStyle(SpanStyle(color = Red500)) { append("$outStock out of stock") }
                                    }
                                },
                                fontSize = 14.sp,
                            )
                        }
                        if (canManage) {
                            Button(
                                onClick = { creating = true }, enabled = !busy, shape = RoundedCornerShape(10.dp),
                                contentPadding = PaddingValues(horizontal = 12.dp),
                            ) {
                                Icon(Icons.Outlined.Add, null, Modifier.size(16.dp))
                                Spacer(Modifier.width(4.dp))
                                Text("Add item", fontSize = 13.sp)
                            }
                        }
                    }
                }
                // ── Source banner ────────────────────────────────────────
                item(span = { GridItemSpan(maxLineSpan) }, key = "source") {
                    Row(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                            .background(if (c.isDark) c.goldDim else Color(0xFFEAF5DD))
                            .border(1.dp, c.bg4, RoundedCornerShape(12.dp))
                            .padding(horizontal = 14.dp, vertical = 10.dp),
                    ) {
                        Icon(Icons.Outlined.Info, null, tint = c.gold2, modifier = Modifier.size(16.dp).padding(top = 1.dp))
                        Spacer(Modifier.width(10.dp))
                        Text(
                            buildAnnotatedString {
                                withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append("Live from the Bethany House hub.") }
                                append(" Prices and stock are maintained in the hub and shared with the POS and website — this is exactly what Neema quotes to customers. To change a product, edit it in the hub.")
                            },
                            fontSize = 12.sp, lineHeight = 18.sp, color = c.gold2,
                        )
                    }
                }
                // ── Search + category ────────────────────────────────────
                item(span = { GridItemSpan(maxLineSpan) }, key = "filters") {
                    if (wide) Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                        SearchField(search, { vm.search.value = it }, "Search name, SKU or alias…", Modifier.weight(1f))
                        CategoryDropdown(categories, filter) { vm.filter.value = it }
                    } else Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        SearchField(search, { vm.search.value = it }, "Search name, SKU or alias…")
                        CategoryDropdown(categories, filter, Modifier.fillMaxWidth()) { vm.filter.value = it }
                    }
                }
                // ── Grid ─────────────────────────────────────────────────
                // No keys: a hub row and a local row may share a SKU-derived id.
                items(filtered) { item ->
                    ProductCard(
                        item = item,
                        manageable = canManage && !item.isHub,
                        busy = busy,
                        onOpen = { detail = item },
                        onEdit = { editing = item },
                        onToggle = { vm.toggleStock(item) },
                        onDelete = { deleting = item },
                    )
                }
                if (filtered.isEmpty()) {
                    item(span = { GridItemSpan(maxLineSpan) }, key = "empty") {
                        Column(Modifier.fillMaxWidth().padding(vertical = 64.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                            Text("📦", fontSize = 30.sp)
                            Spacer(Modifier.height(12.dp))
                            Text("No items found", fontSize = 14.sp, color = c.muted)
                        }
                    }
                }
            }
        }
    }

    detail?.let { item ->
        // Keep the sheet in step with refetches (stock toggles, edits).
        val live = catalog.find { it.id == item.id } ?: item
        ProductSheet(
            item = live,
            manageable = canManage && !live.isHub,
            busy = busy,
            onDismiss = { detail = null },
            onEdit = { editing = live },
            onToggle = { vm.toggleStock(live) },
            onDelete = { deleting = live },
        )
    }
    if (creating) {
        CatalogEditor(title = "Add catalog item", initial = CatalogDraft(category = filter.takeIf { it != "all" } ?: ""), categories = categories, busy = busy,
            onDismiss = { creating = false }, onSave = { d -> vm.create(d) { creating = false } })
    }
    editing?.let { item ->
        CatalogEditor(title = "Edit item", initial = CatalogDraft.of(item), categories = categories, busy = busy,
            onDismiss = { editing = null }, onSave = { d -> vm.update(item, d) { editing = null } })
    }
    deleting?.let { item ->
        ConfirmDialog(
            title = "Delete item?",
            message = "Remove “${item.name}” from the catalog? Neema will stop quoting it.",
            confirmLabel = "Delete", destructive = true,
            onConfirm = { vm.delete(item) { if (detail?.id == item.id) detail = null } },
            onDismiss = { deleting = null },
        )
    }
}

@Composable
private fun CategoryDropdown(categories: List<String>, selected: String, modifier: Modifier = Modifier, onSelect: (String) -> Unit) {
    val c = Neema.colors
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        OutlinedButton(
            onClick = { open = true }, shape = RoundedCornerShape(12.dp),
            modifier = Modifier.then(modifier).heightIn(min = 52.dp).widthIn(min = 180.dp),
            contentPadding = PaddingValues(horizontal = 14.dp),
        ) {
            Text(
                if (selected == "all") "All categories" else "${glyph(selected)} $selected",
                color = c.text, fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f, fill = false),
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.width(6.dp))
            Icon(Icons.Outlined.ExpandMore, null, tint = c.border2)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text("All categories") }, onClick = { onSelect("all"); open = false })
            categories.forEach { cat ->
                DropdownMenuItem(text = { Text("${glyph(cat)} $cat") }, onClick = { onSelect(cat); open = false })
            }
        }
    }
}

/** A product image that fills its square edge-to-edge; the category glyph when missing or broken. */
@Composable
internal fun ProductThumb(item: CatalogItem, glyphSize: Int = 56) {
    // Prefer the FULL-res image — the hub's *_thumb.webp looks soft upscaled onto big cards.
    val src = item.imageUrl?.takeIf { it.isNotBlank() } ?: item.thumbnailUrl?.takeIf { it.isNotBlank() }
    val fallback = @Composable {
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text(glyph(item.rawCategory), fontSize = glyphSize.sp, modifier = Modifier.padding(4.dp))
        }
    }
    if (src == null) fallback()
    else SubcomposeAsyncImage(
        model = src, contentDescription = item.name, contentScale = ContentScale.Crop,
        modifier = Modifier.fillMaxSize(), loading = { fallback() }, error = { fallback() },
    )
}

@Composable
internal fun StockBadge(item: CatalogItem) {
    val (text, color) = if (item.inStock) (item.availableQty?.let { "${num(it)} left" } ?: "IN") to Emerald600 else "OUT" to Red500
    Text(
        text, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = color, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(color.copy(alpha = 0.08f))
            .border(1.dp, color.copy(alpha = 0.3f), RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

@Composable
private fun ProductCard(
    item: CatalogItem, manageable: Boolean, busy: Boolean,
    onOpen: () -> Unit, onEdit: () -> Unit, onToggle: () -> Unit, onDelete: () -> Unit,
) {
    val c = Neema.colors
    Column(
        Modifier.clip(RoundedCornerShape(12.dp)).background(c.bg2).border(1.dp, c.bg3, RoundedCornerShape(12.dp)).clickable(onClick = onOpen),
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(1f).background(categoryBrush(item.rawCategory))) {
            ProductThumb(item)
            if (manageable) {
                var menu by remember { mutableStateOf(false) }
                Box(Modifier.align(Alignment.TopEnd).padding(4.dp)) {
                    IconButton(
                        onClick = { menu = true }, enabled = !busy,
                        modifier = Modifier.size(32.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.85f)),
                    ) { Icon(Icons.Outlined.MoreVert, "Manage", tint = Color(0xFF16270C), modifier = Modifier.size(18.dp)) }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Edit") }, onClick = { menu = false; onEdit() })
                        DropdownMenuItem(text = { Text(if (item.inStock) "Mark out of stock" else "Mark in stock") }, onClick = { menu = false; onToggle() })
                        DropdownMenuItem(text = { Text("Delete", color = c.red) }, onClick = { menu = false; onDelete() })
                    }
                }
            }
        }
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Text(item.name, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text, lineHeight = 15.sp, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(4.dp))
                StockBadge(item)
            }
            if (!item.description.isNullOrBlank()) {
                Text(item.description, fontSize = 12.sp, color = c.muted, maxLines = 2, overflow = TextOverflow.Ellipsis, lineHeight = 15.sp, modifier = Modifier.padding(top = 4.dp))
            }
            Text(priceText(item), fontSize = 14.sp, fontWeight = FontWeight.Bold, color = if (c.isDark) c.gold2 else Color(0xFF2C4E18), modifier = Modifier.padding(top = 6.dp))
            if (item.variants.isNotEmpty()) {
                Text("${item.variants.size} variants", fontSize = 10.sp, color = c.textDim)
            }
            if (item.aliases.isNotEmpty()) {
                @OptIn(ExperimentalLayoutApi::class)
                FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    item.aliases.take(3).forEach { AliasChip(it) }
                }
            }
            Row(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                Text(item.sku, fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = c.border, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                item.hubProductId?.let { Text("#$it", fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = c.border) }
            }
        }
    }
}

@Composable
internal fun AliasChip(text: String) {
    val c = Neema.colors
    Text(
        text, fontSize = 10.sp, color = c.textDim,
        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(c.bg).border(1.dp, c.bg3, RoundedCornerShape(4.dp))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

/**
 * The hub's prices, checked against themselves. A USD row that is not
 * KES ÷ rate, or a pack good priced per single piece, is a wrong quote waiting
 * to happen. Nothing here is editable: the fix is in the hub.
 */
@Composable
private fun PriceAuditBanner(audit: PriceAudit, open: Boolean, onToggle: () -> Unit) {
    val gaps = audit.currencyGaps
    val pp = audit.perPiece
    val amber900 = Color(0xFF78350F); val amber800 = Color(0xFF92400E); val amber950 = Color(0xFF451A03)
    val amber700 = Color(0xFFB45309)
    val dark = Neema.colors.isDark
    val fg900 = if (dark) Color(0xFFFDE68A) else amber900
    val fg800 = if (dark) Color(0xFFFCD34D) else amber800
    val fg950 = if (dark) Color(0xFFFEF3C7) else amber950
    val rate = num(audit.rate)
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
            .background(if (dark) Color(0x33F59E0B) else Color(0xFFFFFBEB))
            .border(1.dp, Color(0xFFFCD34D), RoundedCornerShape(12.dp))
            .clickable(onClick = onToggle).padding(16.dp),
    ) {
        val parts = buildList {
            if (gaps.isNotEmpty()) add("${gaps.size} product${if (gaps.size == 1) "" else "s"} whose USD price in the hub disagrees with KES ÷ $rate")
            if (pp.isNotEmpty()) add("${pp.size} pack good${if (pp.size == 1) "" else "s"} priced per single piece")
        }
        Text(parts.joinToString(" · "), fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = fg900)
        Text(
            "Neema quotes exactly what the hub holds — these are wrong quotes waiting to happen. Fix the rows in the hub. ${if (open) "Hide" else "Show"} the list.",
            fontSize = 12.sp, color = fg800, modifier = Modifier.padding(top = 2.dp),
        )
        if (open) {
            Spacer(Modifier.height(12.dp))
            if (gaps.isNotEmpty()) {
                Row {
                    Text("Product", fontSize = 11.sp, color = fg900.copy(alpha = 0.7f), modifier = Modifier.weight(2f))
                    Text("KES", fontSize = 11.sp, color = fg900.copy(alpha = 0.7f), modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                    Text("USD in hub", fontSize = 11.sp, color = fg900.copy(alpha = 0.7f), modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                    Text("KES ÷ $rate", fontSize = 11.sp, color = fg900.copy(alpha = 0.7f), modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                }
                gaps.forEach { g ->
                    HorizontalDivider(color = Color(0xFFFDE68A), modifier = Modifier.padding(vertical = 4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            buildAnnotatedString {
                                withStyle(SpanStyle(color = fg950)) { append(g.name) }
                                withStyle(SpanStyle(color = amber700.copy(alpha = 0.7f))) { append(" · ${g.category}") }
                            },
                            fontSize = 11.sp, modifier = Modifier.weight(2f),
                        )
                        Text(num(g.kes), fontSize = 11.sp, color = fg950, modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                        Text(
                            usd(g.usd), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.End,
                            color = if (g.usd > g.usdExpected) Color(0xFFB91C1C) else Color(0xFF1D4ED8), modifier = Modifier.weight(1f),
                        )
                        Text(usd(g.usdExpected), fontSize = 11.sp, color = fg950, modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                    }
                }
            }
            if (pp.isNotEmpty()) {
                Spacer(Modifier.height(12.dp))
                Text(
                    buildAnnotatedString {
                        withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append("Priced per piece, no pack size in the name:") }
                        append(" ")
                        append(pp.joinToString(", ") { "${it.name} (KES ${it.kes?.let(::num) ?: "?"})" })
                        append(". Neema says \"each\" and asks how many — she will not invent a pack price. Give these rows a pack quantity and a pack price in the hub.")
                    },
                    fontSize = 12.sp, color = fg900,
                )
            }
        }
    }
}
