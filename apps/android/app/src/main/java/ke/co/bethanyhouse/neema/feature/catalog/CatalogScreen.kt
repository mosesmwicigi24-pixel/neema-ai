package ke.co.bethanyhouse.neema.feature.catalog

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.SubcomposeLayout
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.PriceAudit
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

/** The web's #b5da8b for SKUs and ids; a readable slate by night (the dark border hue vanishes). */
@Composable
internal fun faint(): Color = if (Neema.colors.isDark) Neema.colors.muted.copy(alpha = 0.75f) else Neema.colors.border

/** The web's catalog search border: `border-[#cee6b2]` (the other search fields use #b5da8b). */
private val CatalogSearchBorder = Color(0xFFCEE6B2)

internal val Emerald600 = Color(0xFF059669)
private val Stone200 = Color(0xFFE7E5E4)
internal val Red500 = Color(0xFFEF4444)

/** "1,500" not "1500.0" — the web's toLocaleString(). */
internal fun num(v: Double): String = if (v == Math.floor(v) && !v.isInfinite()) Fmt.number(v.toLong()) else Fmt.number(v)

/** "1500" / "129.5" — a number the web interpolates bare (`${x}`). */
internal fun plainNum(v: Double): String = if (v == Math.floor(v) && !v.isInfinite()) v.toLong().toString() else v.toString()

/** "$10" for whole dollars, "$9.50" otherwise (the audit's usd()). */
internal fun usd(v: Double): String =
    "$" + if (v == Math.floor(v)) Fmt.number(v.toLong()) else "%,.2f".format(java.util.Locale.US, v)

/**
 * The web's grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6, read
 * against the width the catalogue actually has.
 */
internal fun catalogColumns(width: Dp): Int = when {
    width < 640.dp -> 2
    width < 768.dp -> 3
    width < 1024.dp -> 4
    else -> 6
}

/** Price or "KES min – KES max" when the variants differ. */
internal fun priceText(i: CatalogItem): String {
    val lo = i.priceMinKes; val hi = i.priceMaxKes
    return if (lo != null && hi != null && lo != hi) "${Fmt.currency(lo)} – ${Fmt.currency(hi)}" else Fmt.currency(i.price)
}

/**
 * Port of components/views/CatalogView.tsx: a READ-ONLY look at the live hub
 * catalogue — exactly what Neema quotes. Products, prices and stock are
 * maintained in the hub, so nothing is edited here. Tapping a card opens the
 * whole product (every variant's price), which the web's card only counts.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CatalogScreen(
    dash: DashboardViewModel,
    vm: CatalogViewModel = viewModel { CatalogViewModel(dash) },
    /** Open on a product's sheet (tests). */
    initialDetail: CatalogItem? = null,
) {
    ke.co.bethanyhouse.neema.feature.reports.TrackShown(vm.life)
    val catalog by dash.catalog.collectAsStateWithLifecycle()
    val filter by vm.filter.collectAsStateWithLifecycle()
    val search by vm.search.collectAsStateWithLifecycle()
    val audit by vm.audit.collectAsStateWithLifecycle()
    val auditOpen by vm.auditOpen.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val c = Neema.colors

    val categories = remember(catalog) { catalogCategories(catalog) }
    val filtered = remember(catalog, filter, search) { filterCatalog(catalog, filter, search) }
    val inStock = catalog.count { it.inStock }
    val outStock = catalog.count { !it.inStock }

    var detail by remember { mutableStateOf(initialDetail) }

    PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize().background(c.bg)) {
        BoxWithConstraints(Modifier.fillMaxSize()) {
            val wide = maxWidth >= 600.dp
            val pad = if (wide) 24.dp else 16.dp
            val cols = catalogColumns(maxWidth - pad * 2)
            // The web's gap-4: 16 between cards, both ways.
            val gap = 16.dp
            LazyColumn(contentPadding = PaddingValues(pad), modifier = Modifier.fillMaxSize()) {
                audit?.let { a ->
                    if (a.currencyGaps.isNotEmpty() || a.perPiece.isNotEmpty()) {
                        item(key = "audit") {
                            Box(Modifier.padding(bottom = 16.dp)) {
                                PriceAuditBanner(a, auditOpen) { vm.auditOpen.value = !auditOpen }
                            }
                        }
                    }
                }
                // ── Header ───────────────────────────────────────────────
                item(key = "header") {
                    Column(Modifier.padding(bottom = 16.dp)) {
                        Text("Catalog", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = c.text)
                        Text(
                            buildAnnotatedString {
                                withStyle(SpanStyle(color = c.muted)) { append("${catalog.size} items") }
                                withStyle(SpanStyle(color = Stone200)) { append("  ·  ") }
                                withStyle(SpanStyle(color = Emerald600)) { append("$inStock in stock") }
                                if (outStock > 0) {
                                    withStyle(SpanStyle(color = Stone200)) { append("  ·  ") }
                                    withStyle(SpanStyle(color = Red500)) { append("$outStock out of stock") }
                                }
                            },
                            fontSize = 14.sp, modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }
                // ── Source banner ────────────────────────────────────────
                item(key = "source") {
                    Row(
                        Modifier.padding(bottom = 20.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp))
                            .background(if (c.isDark) c.goldDim else Color(0xFFEAF5DD))
                            .border(1.dp, c.bg4, RoundedCornerShape(12.dp))
                            .padding(horizontal = 14.dp, vertical = 10.dp),
                    ) {
                        Icon(Icons.Outlined.Info, null, tint = c.gold2, modifier = Modifier.padding(top = 2.dp).size(16.dp))
                        Spacer(Modifier.width(10.dp))
                        Text(
                            buildAnnotatedString {
                                withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append("Live from the Bethany House hub.") }
                                append(" Prices and stock are maintained in the hub and shared with the POS and website — this is exactly what Neema quotes to customers. To change a product, edit it in the hub.")
                            },
                            fontSize = 12.sp, lineHeight = 19.5.sp, color = c.gold2,
                        )
                    }
                }
                // ── Search + category ────────────────────────────────────
                item(key = "filters") {
                    Box(Modifier.padding(bottom = 20.dp)) {
                        if (wide) Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                            SearchField(search, { vm.search.value = it }, "Search name, SKU or alias…", Modifier.weight(1f), borderColor = CatalogSearchBorder)
                            // A set width: the button's label fills it, and would otherwise squeeze the search to nothing.
                            CategoryDropdown(categories, filter, Modifier.width(240.dp)) { vm.filter.value = it }
                        } else Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            SearchField(search, { vm.search.value = it }, "Search name, SKU or alias…", borderColor = CatalogSearchBorder)
                            CategoryDropdown(categories, filter, Modifier.fillMaxWidth()) { vm.filter.value = it }
                        }
                    }
                }
                // ── Grid ─────────────────────────────────────────────────
                // Rows of equal height, like the web's CSS grid: every card in
                // a row stretches to the tallest one in it.
                // No keys: a hub row and a local row may share a SKU-derived id.
                val rows = filtered.chunked(cols)
                itemsIndexed(rows) { i, row ->
                    EqualHeightRow(
                        cols = cols, gap = gap,
                        modifier = Modifier.padding(bottom = if (i < rows.lastIndex) gap else 0.dp),
                    ) {
                        row.forEach { item -> ProductCard(item = item, onOpen = { detail = item }) }
                    }
                }
                if (filtered.isEmpty()) {
                    item(key = "empty") {
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
        // Keep the sheet in step with the polled catalogue.
        val live = catalog.find { it.id == item.id } ?: item
        ProductSheet(item = live, onDismiss = { detail = null })
    }
}

/**
 * One grid row whose cells all take the height of the tallest, like a CSS grid
 * row. Measured twice (natural heights, then that max as a fixed height), since
 * intrinsic sizes under-report wrapping content such as the alias chips. A
 * short last row keeps the full grid's column widths.
 */
@Composable
internal fun EqualHeightRow(cols: Int, gap: Dp, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    SubcomposeLayout(modifier.fillMaxWidth()) { constraints ->
        val gapPx = gap.roundToPx()
        val cell = ((constraints.maxWidth - gapPx * (cols - 1)) / cols).coerceAtLeast(0)
        val natural = subcompose("natural", content).map { it.measure(Constraints(minWidth = cell, maxWidth = cell)) }
        val h = natural.maxOfOrNull { it.height } ?: 0
        val placeables = subcompose("stretched", content).map { it.measure(Constraints.fixed(cell, h)) }
        layout(constraints.maxWidth, h) {
            placeables.forEachIndexed { i, p -> p.placeRelative(i * (cell + gapPx), 0) }
        }
    }
}

@Composable
private fun CategoryDropdown(categories: List<String>, selected: String, modifier: Modifier = Modifier, onSelect: (String) -> Unit) {
    val c = Neema.colors
    var open by remember { mutableStateOf(false) }
    Box(modifier) {
        OutlinedButton(
            onClick = { open = true }, shape = RoundedCornerShape(12.dp),
            modifier = Modifier.then(modifier).heightIn(min = 52.dp).widthIn(min = 160.dp),
            contentPadding = PaddingValues(horizontal = 14.dp),
        ) {
            Text(
                if (selected == "all") "All categories" else "${glyph(selected)} $selected",
                color = c.text, fontSize = 14.sp, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f),
                maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.width(6.dp))
            Icon(Icons.Outlined.ExpandMore, null, tint = if (c.isDark) c.muted else c.border2)
        }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            DropdownMenuItem(text = { Text("All categories") }, onClick = { onSelect("all"); open = false })
            categories.forEach { cat ->
                DropdownMenuItem(text = { Text("${glyph(cat)} $cat") }, onClick = { onSelect(cat); open = false })
            }
        }
    }
}

/**
 * A product image that fills its square edge-to-edge; the category glyph when
 * missing or broken (and while it loads), which the image covers once it arrives.
 */
@Composable
internal fun ProductThumb(item: CatalogItem, glyphSize: Int = 56) {
    // Prefer the FULL-res image — the hub's *_thumb.webp looks soft upscaled onto big cards.
    val src = item.imageUrl?.takeIf { it.isNotBlank() } ?: item.thumbnailUrl?.takeIf { it.isNotBlank() }
    var shown by remember(src) { mutableStateOf(false) }
    var failed by remember(src) { mutableStateOf(false) }
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        if (!shown) Text(glyph(item.rawCategory), fontSize = glyphSize.sp, modifier = Modifier.padding(4.dp))
        if (src != null && !failed) AsyncImage(
            model = src, contentDescription = item.name, contentScale = ContentScale.Crop,
            modifier = Modifier.fillMaxSize(),
            onSuccess = { shown = true },
            onError = { failed = true; shown = false },
        )
    }
}

@Composable
internal fun StockBadge(item: CatalogItem) {
    val dark = Neema.colors.isDark
    // The web prints the bare number ("1200 left"), no grouping.
    val text = if (item.inStock) item.availableQty?.let { "${plainNum(it)} left" } ?: "IN" else "OUT"
    // bg-emerald-50 text-emerald-600 border-emerald-200 / bg-red-50 text-red-500 border-red-200;
    // by night the same hues as tints, so the badge doesn't glare on navy.
    val fg = if (item.inStock) (if (dark) Color(0xFF34D399) else Emerald600) else (if (dark) Color(0xFFF87171) else Red500)
    val bg = if (dark) fg.copy(alpha = 0.12f) else if (item.inStock) Color(0xFFECFDF5) else Color(0xFFFEF2F2)
    val line = if (dark) fg.copy(alpha = 0.35f) else if (item.inStock) Color(0xFFA7F3D0) else Color(0xFFFECACA)
    Text(
        text, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = fg, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(bg)
            .border(1.dp, line, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

@Composable
private fun ProductCard(item: CatalogItem, onOpen: () -> Unit, modifier: Modifier = Modifier) {
    val c = Neema.colors
    Column(
        modifier.fillMaxSize().clip(RoundedCornerShape(12.dp)).background(c.bg2).border(1.dp, c.bg3, RoundedCornerShape(12.dp)).clickable(onClick = onOpen),
    ) {
        Box(Modifier.fillMaxWidth().aspectRatio(1f).background(categoryBrush(item.rawCategory))) {
            ProductThumb(item)
        }
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Text(item.name, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text, lineHeight = 15.sp, modifier = Modifier.weight(1f))
                Spacer(Modifier.width(4.dp))
                StockBadge(item)
            }
            val hasDescription = !item.description.isNullOrEmpty()
            if (hasDescription) {
                Text(item.description.orEmpty(), fontSize = 12.sp, color = c.muted, maxLines = 2, overflow = TextOverflow.Ellipsis, lineHeight = 16.5.sp, modifier = Modifier.padding(top = 4.dp))
            }
            Text(priceText(item), fontSize = 14.sp, fontWeight = FontWeight.Bold, color = if (c.isDark) c.gold2 else Color(0xFF2C4E18), modifier = Modifier.padding(top = if (hasDescription) 8.dp else 4.dp))
            if (item.variants.isNotEmpty()) {
                Text("${item.variants.size} variants", fontSize = 10.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp))
            }
            if (item.aliases.isNotEmpty()) {
                @OptIn(ExperimentalLayoutApi::class)
                FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    item.aliases.take(3).forEach { AliasChip(it) }
                }
            }
            Row(Modifier.fillMaxWidth().padding(top = 8.dp)) {
                Text(item.sku, fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = faint(), modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                item.hubProductId?.let { Text("#$it", fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = faint()) }
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
    val rate = plainNum(audit.rate)
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
                    Text("Product", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = fg900.copy(alpha = 0.7f), modifier = Modifier.weight(2f))
                    Text("KES", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = fg900.copy(alpha = 0.7f), modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                    Text("USD in hub", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = fg900.copy(alpha = 0.7f), modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                    Text("KES ÷ $rate", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = fg900.copy(alpha = 0.7f), modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                }
                gaps.forEach { g ->
                    HorizontalDivider(color = Color(0xFFFDE68A), modifier = Modifier.padding(vertical = 4.dp))
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            buildAnnotatedString {
                                withStyle(SpanStyle(color = fg950)) { append(g.name) }
                                // The hub's category is "" for an uncategorised product (and null on
                                // older rows): the web then prints a dangling " · "; drop it instead.
                                g.category?.takeIf { it.isNotBlank() }?.let { cat ->
                                    withStyle(SpanStyle(color = (if (dark) Color(0xFFFBBF24) else amber700).copy(alpha = 0.7f))) { append(" · $cat") }
                                }
                            },
                            fontSize = 12.sp, modifier = Modifier.weight(2f),
                        )
                        Text(num(g.kes), fontSize = 12.sp, color = fg950, modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                        Text(
                            usd(g.usd), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, textAlign = TextAlign.End,
                            // red-700 / blue-700 by day; red-400 / blue-400 so they read on the night banner.
                            color = if (g.usd > g.usdExpected) (if (dark) Color(0xFFF87171) else Color(0xFFB91C1C))
                                else (if (dark) Color(0xFF60A5FA) else Color(0xFF1D4ED8)),
                            modifier = Modifier.weight(1f),
                        )
                        Text(usd(g.usdExpected), fontSize = 12.sp, color = fg950, modifier = Modifier.weight(1f), textAlign = TextAlign.End)
                    }
                }
            }
            if (pp.isNotEmpty()) {
                if (gaps.isNotEmpty()) Spacer(Modifier.height(12.dp))
                Text(
                    buildAnnotatedString {
                        withStyle(SpanStyle(fontWeight = FontWeight.SemiBold)) { append("Priced per piece, no pack size in the name:") }
                        append(" ")
                        append(pp.joinToString(", ") { "${it.name} (KES ${it.kes?.let(::plainNum) ?: "?"})" })
                        append(". Neema says \"each\" and asks how many — she will not invent a pack price. Give these rows a pack quantity and a pack price in the hub.")
                    },
                    fontSize = 12.sp, color = fg900,
                )
            }
        }
    }
}
