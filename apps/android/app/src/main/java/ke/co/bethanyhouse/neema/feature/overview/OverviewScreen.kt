package ke.co.bethanyhouse.neema.feature.overview

import ke.co.bethanyhouse.neema.core.util.AppClock

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.RoundRect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.Attribution
import ke.co.bethanyhouse.neema.core.model.CatalogItem
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.model.Stats
import ke.co.bethanyhouse.neema.core.ui.components.ALL_CHANNELS
import ke.co.bethanyhouse.neema.core.ui.components.Panel
import ke.co.bethanyhouse.neema.core.ui.components.channelStyle
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.reports.capitalizeWords
import java.time.Clock
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.TextStyle
import java.util.Locale

/** The web's STAT_COLORS, by accent. */
// By day exactly the web's hexes (#589b31 #427425 #2a48a2 #bcc13e #4d66b3);
// by night the theme's lifted hues, so no accent sinks into the navy.
private val AccentGreen @Composable get() = Neema.colors.gold
private val AccentEmerald @Composable get() = Neema.colors.gold2
private val AccentBlue @Composable get() = Neema.colors.blue
private val AccentOrange @Composable get() = Neema.colors.amber
private val AccentViolet @Composable get() = if (Neema.colors.isDark) Color(0xFF7085C2) else Color(0xFF4D66B3)

/** Port of components/views/OverviewView.tsx — the Analytics screen. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OverviewScreen(
    dash: DashboardViewModel,
    vm: OverviewViewModel = viewModel { OverviewViewModel(dash) },
    /** "Now" for the 7-day chart and the activity times (fixed in tests). */
    clock: Clock = Clock.systemDefaultZone(),
) {
    ke.co.bethanyhouse.neema.feature.reports.TrackShown(vm.life)
    val apiStats by vm.stats.collectAsStateWithLifecycle()
    val statsLoading by vm.statsLoading.collectAsStateWithLifecycle()
    val attrib by vm.attrib.collectAsStateWithLifecycle()
    val humanRows by vm.humanRows.collectAsStateWithLifecycle()
    val conversations by vm.fallbackConvs.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val agents by dash.agents.collectAsStateWithLifecycle()
    val orders by dash.orders.collectAsStateWithLifecycle()
    val catalog by dash.catalog.collectAsStateWithLifecycle()
    val c = Neema.colors

    val stats = remember(apiStats, conversations, agents, orders, catalog) {
        headline(apiStats, conversations, agents, orders, catalog)
    }
    val channels = remember(apiStats, conversations) { channelRows(apiStats, conversations) }
    val activity = remember(orders, humanRows, conversations, agents) {
        activityFeed(orders, humanRows ?: conversations, agents)
    }
    val bars = remember(orders, clock) { sevenDayRevenue(orders, LocalDate.now(clock), clock.zone) }
    val top = remember(orders) { topProducts(orders) }
    val cardsLoading = statsLoading && apiStats == null

    BoxWithConstraints(Modifier.fillMaxSize().background(c.bg)) {
        val wide = maxWidth >= 600.dp
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(if (wide) 24.dp else 16.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                // ── Header ───────────────────────────────────────────────
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("Overview", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = c.text)
                        Text("Real-time metrics and platform performance", fontSize = 14.sp, color = c.muted)
                    }
                    if (statsLoading) {
                        CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(12.dp))
                        Spacer(Modifier.width(6.dp))
                        Text("Refreshing…", fontSize = 12.sp, color = c.muted)
                    }
                }

                // ── Stat grid ────────────────────────────────────────────
                val cards = listOf<@Composable (Modifier) -> Unit>(
                    { StatCard("Open Conversations", stats.openConvs.toString(), "${stats.humanConvs} with agents", OverviewIcons.Chat, AccentGreen, cardsLoading, it) },
                    { StatCard("Active Agents", stats.activeAgents.toString(), "of ${stats.totalAgents} total", OverviewIcons.Team, AccentEmerald, cardsLoading, it) },
                    { StatCard("Total Revenue", Fmt.currency(stats.revenue), "${stats.totalOrders} orders", OverviewIcons.Money, AccentGreen, cardsLoading, it) },
                    { StatCard("Pending Orders", stats.pendingOrders.toString(), "Awaiting confirmation", OverviewIcons.Box, AccentOrange, cardsLoading, it) },
                    { StatCard("AI Conversations", stats.aiConvs.toString(), "Fully automated", OverviewIcons.Robot, AccentBlue, cardsLoading, it) },
                    { StatCard("Catalog Items", stats.totalItems.toString(), "${stats.inStockItems} in stock", OverviewIcons.Box, AccentViolet, cardsLoading, it) },
                )
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    cards.chunked(if (wide) 3 else 2).forEach { row ->
                        Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            row.forEach { it(Modifier.weight(1f).fillMaxHeight()) }
                        }
                    }
                }

                // ── Attribution — which source/post drives leads + revenue ──
                attrib?.takeIf { it.sources.isNotEmpty() }?.let { AttributionPanel(it, wide) }

                // ── Charts row ───────────────────────────────────────────
                val revenue: @Composable (Modifier) -> Unit = { RevenueChart(bars, it) }
                val status: @Composable (Modifier) -> Unit = { OrderStatusPanel(stats, it) }
                if (wide) Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    revenue(Modifier.weight(3f).fillMaxHeight()); status(Modifier.weight(2f).fillMaxHeight())
                } else { revenue(Modifier.fillMaxWidth()); status(Modifier.fillMaxWidth()) }

                // ── Bottom row ───────────────────────────────────────────
                val byChannel: @Composable (Modifier) -> Unit = { ChannelPanel(channels, apiStats, conversations.size, it) }
                val feed: @Composable (Modifier) -> Unit = { ActivityPanel(activity, clock.millis(), it) }
                if (wide) Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    byChannel(Modifier.weight(2f).fillMaxHeight()); feed(Modifier.weight(3f).fillMaxHeight())
                } else { byChannel(Modifier.fillMaxWidth()); feed(Modifier.fillMaxWidth()) }

                // ── Top products ─────────────────────────────────────────
                if (top.isNotEmpty()) TopProductsPanel(top)
                Spacer(Modifier.height(8.dp))
            }
        }
    }
}

// ── Computation ─────────────────────────────────────────────────────────────

data class Headline(
    val openConvs: Int, val humanConvs: Int, val aiConvs: Int,
    val activeAgents: Int, val totalAgents: Int,
    val revenue: Double, val totalOrders: Int,
    val pendingOrders: Int, val deliveredOrders: Int, val confirmedOrders: Int, val cancelledOrders: Int,
    val inStockItems: Int, val totalItems: Int,
)

/** API stats when available, computed from what the app holds as a fallback. */
internal fun headline(s: Stats?, convs: List<Conversation>, agents: List<Agent>, orders: List<Order>, catalog: List<CatalogItem>) = Headline(
    openConvs = s?.openConversations ?: convs.count { it.status == "open" },
    humanConvs = s?.humanConversations ?: convs.count { it.interceptMode == "human" },
    aiConvs = s?.aiConversations ?: convs.count { it.interceptMode == "ai" },
    activeAgents = s?.activeAgents ?: agents.count { it.isAvailable },
    totalAgents = s?.totalAgents ?: agents.size,
    revenue = s?.totalRevenue ?: orders.filter { it.status != "cancelled" }.sumOf { it.subtotal },
    totalOrders = s?.totalOrders ?: orders.size,
    pendingOrders = s?.pendingOrders ?: orders.count { it.status == "pending" },
    deliveredOrders = s?.deliveredOrders ?: orders.count { it.status == "delivered" },
    confirmedOrders = s?.confirmedOrders ?: orders.count { it.status == "confirmed" },
    cancelledOrders = s?.cancelledOrders ?: orders.count { it.status == "cancelled" },
    inStockItems = s?.inStockItems ?: catalog.count { it.inStock },
    totalItems = s?.totalItems ?: catalog.size,
)

data class ChannelRow(val ch: String, val count: Int, val open: Int)

internal fun channelRows(s: Stats?, convs: List<Conversation>): List<ChannelRow> =
    if (s != null) s.channelBreakdown.filter { it.count > 0 }.map { ChannelRow(it.channel, it.count, it.open) }
    else ALL_CHANNELS.map { ch ->
        ChannelRow(ch, convs.count { it.channel == ch }, convs.count { it.channel == ch && it.status == "open" })
    }.filter { it.count > 0 }

/** [icon] is the web's emoji: 📦 for an order, ⚡ for an intercept. */
data class ActivityEntry(val id: String, val user: String, val action: String, val target: String?, val at: String, val icon: String)

internal fun activityFeed(orders: List<Order>, human: List<Conversation>, agents: List<Agent>): List<ActivityEntry> {
    val out = mutableListOf<ActivityEntry>()
    // Recent orders
    orders.sortedByDescending { Fmt.millis(it.createdAt) ?: 0 }.take(4).forEach { o ->
        out += ActivityEntry(
            // mapOrder() makes contact_phone the wa_id: an unnamed buyer shows their number, never "Unknown".
            "order-${o.id}", Fmt.displayName(o.contactName, o.contactPhone?.takeIf { it.isNotBlank() } ?: o.waId), "placed an order",
            Fmt.currency(o.total), o.createdAt, "📦",
        )
    }
    // Recent human intercepts
    // mapConversation() dates a thread with no messages yet from its creation,
    // so the web's `c.last_message_at` test only drops a thread with neither.
    human.filter { it.interceptMode == "human" && !(it.lastMessageAt ?: it.createdAt).isNullOrEmpty() }
        .sortedByDescending { Fmt.millis(it.lastMessageAt ?: it.createdAt) ?: 0 }.take(3).forEach { conv ->
            out += ActivityEntry(
                "conv-${conv.id}", agents.find { it.id == conv.assignedAgentId }?.name ?: "An agent",
                "intercepted conversation with", Fmt.displayName(conv.name, conv.waId),
                (conv.lastMessageAt ?: conv.createdAt)!!, "⚡",
            )
        }
    return out.sortedByDescending { Fmt.millis(it.at) ?: 0 }.take(8)
}

data class DayBar(val label: String, val value: Double, val isToday: Boolean)

/** Revenue per day from real orders over the last 7 days (cancelled excluded). */
internal fun sevenDayRevenue(orders: List<Order>, today: LocalDate = AppClock.today(), zone: ZoneId = ZoneId.systemDefault()): List<DayBar> {
    val byDay = orders.filter { it.status != "cancelled" }
        .groupBy { o -> Fmt.millis(o.createdAt)?.let { Instant.ofEpochMilli(it).atZone(zone).toLocalDate() } }
    return (0 until 7).map { i ->
        val d = today.minusDays((6 - i).toLong())
        DayBar(d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH), byDay[d].orEmpty().sumOf { it.total }, i == 6)
    }
}

data class TopProduct(val name: String, val qty: Double, val revenue: Double)

internal fun topProducts(orders: List<Order>): List<TopProduct> {
    val map = linkedMapOf<String, Pair<Double, Double>>()
    orders.filter { it.status != "cancelled" }.forEach { o ->
        o.items.forEach { item ->
            val qty = item.qty.takeIf { it != 0.0 } ?: 1.0
            val rev = item.total.takeIf { it != 0.0 } ?: (item.unit * qty)
            val (q, r) = map[item.name] ?: (0.0 to 0.0)
            map[item.name] = (q + qty) to (r + rev)
        }
    }
    return map.map { (k, v) -> TopProduct(k, v.first, v.second) }.sortedByDescending { it.revenue }.take(5)
}

private fun qtyText(q: Double): String = if (q == Math.floor(q)) q.toLong().toString() else q.toString()

// ── Pieces ──────────────────────────────────────────────────────────────────

/** The web's #2c4e18 (totals, today, top-product revenue); the bright moss by night. */
@Composable
private fun strong(): Color = if (Neema.colors.isDark) Neema.colors.gold2 else Color(0xFF2C4E18)

/** The web's #b5da8b (rank numbers); a readable slate by night. */
@Composable
private fun faint(): Color = if (Neema.colors.isDark) Neema.colors.muted.copy(alpha = 0.75f) else Neema.colors.border

@Composable
private fun PanelTitle(text: String, modifier: Modifier = Modifier) {
    Text(text.uppercase(), fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp, color = Neema.colors.muted, modifier = modifier)
}

@Composable
private fun ThinBar(fraction: Float, color: Color, modifier: Modifier = Modifier) {
    val f by animateFloatAsState(fraction.coerceIn(0f, 1f), tween(700), label = "bar")
    Box(modifier.fillMaxWidth().height(6.dp).clip(CircleShape).background(Neema.colors.bg3)) {
        Box(Modifier.fillMaxWidth(f).fillMaxHeight().clip(CircleShape).background(color))
    }
}

/** The web's StatCard: accent strip, tinted icon tile, value (or a pulsing placeholder). */
@Composable
private fun StatCard(label: String, value: String, sub: String, icon: ImageVector, accent: Color, loading: Boolean, modifier: Modifier) {
    val c = Neema.colors
    Box(modifier.clip(RoundedCornerShape(12.dp)).background(c.bg2).border(1.dp, c.hairline, RoundedCornerShape(12.dp))) {
        Box(Modifier.fillMaxWidth().height(2.dp).background(accent))
        Column(Modifier.padding(14.dp)) {
            Box(Modifier.size(36.dp).clip(RoundedCornerShape(10.dp)).background(accent.copy(alpha = 0.10f)), contentAlignment = Alignment.Center) {
                Icon(icon, null, tint = accent, modifier = Modifier.size(20.dp))
            }
            Spacer(Modifier.height(10.dp))
            if (loading) {
                val pulse by rememberInfiniteTransition(label = "pulse").animateFloat(
                    0.4f, 1f, infiniteRepeatable(tween(800), RepeatMode.Reverse), label = "pulse",
                )
                Box(Modifier.padding(vertical = 2.dp).size(56.dp, 26.dp).alpha(pulse).clip(RoundedCornerShape(4.dp)).background(c.bg3))
            } else {
                Text(value, fontSize = 22.sp, fontWeight = FontWeight.Bold, color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Text(label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = accent, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(sub, fontSize = 12.sp, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

@Composable
private fun AttributionPanel(a: Attribution, wide: Boolean) {
    val c = Neema.colors
    Panel(Modifier.fillMaxWidth(), padding = PaddingValues(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PanelTitle("Where Sales Come From", Modifier.weight(1f))
            Text("${a.totals.leads} attributed lead${if (a.totals.leads == 1) "" else "s"}", fontSize = 11.sp, color = c.muted)
        }
        Spacer(Modifier.height(10.dp))
        val slate = Color(0xFF64748B)
        if (wide) {
            Row(Modifier.padding(vertical = 6.dp)) {
                listOf("Source" to 1.2f, "Post" to 2f, "Leads" to 0.7f, "Orders" to 0.7f, "Revenue (KES)" to 1.2f).forEachIndexed { i, (h, w) ->
                    Text(h.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = c.muted, modifier = Modifier.weight(w), textAlign = if (i >= 2) TextAlign.End else TextAlign.Start)
                }
            }
            HorizontalDivider(color = c.hairline)
            a.sources.take(8).forEach { r ->
                Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(capitalizeWords(r.source), fontSize = 12.sp, fontWeight = FontWeight.Medium, color = c.text, modifier = Modifier.weight(1.2f))
                    Text(
                        r.postTitle ?: r.post ?: "—", fontSize = 10.sp, color = slate, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        fontFamily = if (r.postTitle.isNullOrEmpty()) FontFamily.Monospace else null, modifier = Modifier.weight(2f),
                    )
                    Text("${r.leads}", fontSize = 12.sp, color = c.text, modifier = Modifier.weight(0.7f), textAlign = TextAlign.End)
                    Text("${r.orders}", fontSize = 12.sp, color = c.text, modifier = Modifier.weight(0.7f), textAlign = TextAlign.End)
                    Text(Fmt.currency(r.revenue), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text, modifier = Modifier.weight(1.2f), textAlign = TextAlign.End)
                }
                HorizontalDivider(color = c.hairline.copy(alpha = 0.5f))
            }
            if (a.unattributed.orders > 0) {
                val grey = Color(0xFF94A3B8)
                Row(Modifier.padding(vertical = 8.dp)) {
                    Text("unattributed", fontSize = 12.sp, fontStyle = FontStyle.Italic, color = grey, modifier = Modifier.weight(1.2f))
                    Text("—", fontSize = 12.sp, color = grey, modifier = Modifier.weight(2f))
                    Text("—", fontSize = 12.sp, color = grey, modifier = Modifier.weight(0.7f), textAlign = TextAlign.End)
                    Text("${a.unattributed.orders}", fontSize = 12.sp, color = grey, modifier = Modifier.weight(0.7f), textAlign = TextAlign.End)
                    Text(Fmt.currency(a.unattributed.revenue), fontSize = 12.sp, color = grey, modifier = Modifier.weight(1.2f), textAlign = TextAlign.End)
                }
            }
        } else {
            // Phone: one card per source.
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                a.sources.take(8).forEach { r ->
                    AttributionCard(
                        source = capitalizeWords(r.source),
                        post = r.postTitle ?: r.post ?: "—", mono = r.postTitle.isNullOrEmpty(),
                        leads = "${r.leads}", orders = "${r.orders}", revenue = Fmt.currency(r.revenue), dim = false,
                    )
                }
                if (a.unattributed.orders > 0) AttributionCard(
                    source = "unattributed", post = "—", mono = false, leads = "—",
                    orders = "${a.unattributed.orders}", revenue = Fmt.currency(a.unattributed.revenue), dim = true,
                )
            }
        }
    }
}

@Composable
private fun AttributionCard(source: String, post: String, mono: Boolean, leads: String, orders: String, revenue: String, dim: Boolean) {
    val c = Neema.colors
    val fg = if (dim) Color(0xFF94A3B8) else c.text
    Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(c.bg).padding(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                source, fontSize = 13.sp, fontWeight = if (dim) FontWeight.Normal else FontWeight.SemiBold,
                fontStyle = if (dim) FontStyle.Italic else FontStyle.Normal, color = fg, modifier = Modifier.weight(1f),
            )
            Text(revenue, fontSize = 13.sp, fontWeight = if (dim) FontWeight.Normal else FontWeight.SemiBold, color = fg)
        }
        Text(post, fontSize = 11.sp, color = if (dim) fg else Color(0xFF64748B), fontFamily = if (mono) FontFamily.Monospace else null, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(4.dp))
        Text("Leads $leads  ·  Orders $orders", fontSize = 11.sp, color = if (dim) fg else c.muted)
    }
}

/** 7-day revenue bars on a Canvas; today's bar in the dark green. Tap a bar for its amount. */
@Composable
private fun RevenueChart(bars: List<DayBar>, modifier: Modifier) {
    val c = Neema.colors
    var picked by remember(bars) { mutableStateOf<Int?>(null) }
    val max = (bars.maxOfOrNull { it.value } ?: 0.0).coerceAtLeast(1.0)
    // Web: today #427425, other days #cee6b2, hover green-400.
    val todayColor = if (c.isDark) c.gold else AccentEmerald
    val restColor = if (c.isDark) c.gold.copy(alpha = 0.22f) else c.bg4
    val pickedColor = Color(0xFF4ADE80)
    Panel(modifier, padding = PaddingValues(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            PanelTitle("7-Day Revenue (KES)", Modifier.weight(1f))
            Text(Fmt.currency(bars.sumOf { it.value }), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = strong())
        }
        Text(picked?.let { "${bars[it].label}: ${Fmt.currency(bars[it].value)}" } ?: " ", fontSize = 11.sp, color = c.textDim, modifier = Modifier.padding(top = 8.dp))
        Canvas(
            Modifier.fillMaxWidth().height(104.dp).padding(top = 4.dp).pointerInput(bars) {
                detectTapGestures { pos ->
                    val i = (pos.x / (size.width / bars.size)).toInt().coerceIn(0, bars.size - 1)
                    picked = if (picked == i) null else i
                }
            },
        ) {
            val gap = 8.dp.toPx()
            val slot = size.width / bars.size
            bars.forEachIndexed { i, d ->
                if (d.value <= 0) return@forEachIndexed
                val h = (size.height * (d.value / max).toFloat()).coerceAtLeast(4.dp.toPx())
                val w = slot - gap
                val r = minOf(6.dp.toPx(), h / 2, w / 2)
                drawPath(
                    Path().apply {
                        addRoundRect(
                            RoundRect(
                                Rect(Offset(i * slot + gap / 2, size.height - h), Size(w, h)),
                                topLeft = CornerRadius(r), topRight = CornerRadius(r),
                            ),
                        )
                    },
                    color = when { d.isToday -> todayColor; picked == i -> pickedColor; else -> restColor },
                )
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 6.dp)) {
            bars.forEach { d ->
                Text(
                    d.label, fontSize = 10.sp, fontWeight = FontWeight.Medium, textAlign = TextAlign.Center,
                    color = if (d.isToday) strong() else c.muted, modifier = Modifier.weight(1f),
                )
            }
        }
        if (bars.all { it.value == 0.0 }) {
            Text("No orders in the last 7 days", fontSize = 12.sp, color = c.muted, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
        }
    }
}

@Composable
private fun OrderStatusPanel(s: Headline, modifier: Modifier) {
    val c = Neema.colors
    val items = listOf(
        Triple("Delivered", s.deliveredOrders, Color(0xFF10B981) to Color(0xFF059669)),
        Triple("Confirmed", s.confirmedOrders, Color(0xFF3B82F6) to Color(0xFF2563EB)),
        Triple("Pending", s.pendingOrders, Color(0xFFFBBF24) to Color(0xFFD97706)),
        Triple("Cancelled", s.cancelledOrders, Color(0xFFF87171) to Color(0xFFEF4444)),
    )
    Panel(modifier, padding = PaddingValues(16.dp)) {
        PanelTitle("Order Status")
        Spacer(Modifier.height(14.dp))
        Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
            items.forEach { (label, count, colors) ->
                Column {
                    Row {
                        Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = c.textDim, modifier = Modifier.weight(1f))
                        Text("$count", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = colors.second)
                    }
                    Spacer(Modifier.height(6.dp))
                    ThinBar(if (s.totalOrders > 0) count.toFloat() / s.totalOrders else 0f, colors.first)
                }
            }
        }
    }
}

@Composable
private fun ChannelPanel(rows: List<ChannelRow>, stats: Stats?, localCount: Int, modifier: Modifier) {
    val c = Neema.colors
    // Divide by the SERVER's total, never the handful of rows the app holds.
    val serverTotal = stats?.channelBreakdown?.sumOf { it.count } ?: 0
    val total = maxOf(if (serverTotal > 0) serverTotal else localCount, 1)
    // Only the channels the web knows (CHANNEL_CONFIG); anything else is skipped.
    val known = rows.filter { it.ch in ALL_CHANNELS }
    Panel(modifier, padding = PaddingValues(16.dp)) {
        PanelTitle("By Channel")
        Spacer(Modifier.height(14.dp))
        if (rows.isEmpty()) {
            Text("No channel data yet", fontSize = 12.sp, color = c.muted, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp))
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(14.dp)) {
                known.forEach { r ->
                    val cfg = channelStyle(r.ch)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(28.dp).clip(RoundedCornerShape(8.dp)).background(cfg.color), contentAlignment = Alignment.Center) {
                            OverviewIcons.channel(r.ch)?.let { Icon(it, cfg.label, tint = Color.White, modifier = Modifier.size(14.dp)) }
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Row {
                                Text(cfg.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.gold2, modifier = Modifier.weight(1f))
                                Text("${r.count} · ${r.open} open", fontSize = 12.sp, color = c.muted)
                            }
                            Spacer(Modifier.height(6.dp))
                            ThinBar(r.count.toFloat() / total, cfg.color)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun ActivityPanel(feed: List<ActivityEntry>, now: Long, modifier: Modifier) {
    val c = Neema.colors
    Panel(modifier, padding = PaddingValues(16.dp)) {
        PanelTitle("Recent Activity")
        Spacer(Modifier.height(8.dp))
        if (feed.isEmpty()) {
            Text("No activity yet", fontSize = 12.sp, color = c.muted, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 24.dp))
        } else {
            feed.forEachIndexed { i, e ->
                if (i > 0) HorizontalDivider(color = c.bg)
                Row(Modifier.padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        Modifier.size(28.dp).clip(RoundedCornerShape(8.dp)).background(c.bg).border(1.dp, c.bg3, RoundedCornerShape(8.dp)),
                        contentAlignment = Alignment.Center,
                    ) { Text(e.icon, fontSize = 13.sp) }
                    Spacer(Modifier.width(12.dp))
                    Text(
                        buildAnnotatedString {
                            withStyle(SpanStyle(fontWeight = FontWeight.SemiBold, color = c.text)) { append(e.user) }
                            append(" ${e.action}")
                            if (!e.target.isNullOrEmpty()) append(" · ${e.target}")
                        },
                        fontSize = 12.sp, lineHeight = 16.sp, color = c.gold2, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f),
                    )
                    Spacer(Modifier.width(8.dp))
                    Text(Fmt.timeAgo(e.at, now), fontSize = 10.sp, color = c.muted)
                }
            }
        }
    }
}

@Composable
private fun TopProductsPanel(top: List<TopProduct>) {
    val c = Neema.colors
    val maxRev = top.first().revenue.takeIf { it != 0.0 } ?: 1.0
    Panel(Modifier.fillMaxWidth(), padding = PaddingValues(16.dp)) {
        PanelTitle("Top Products by Revenue")
        Spacer(Modifier.height(14.dp))
        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
            top.forEachIndexed { i, p ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${i + 1}", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = faint(), modifier = Modifier.width(16.dp))
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f)) {
                        Row {
                            Text(p.name, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                            Spacer(Modifier.width(8.dp))
                            Text(Fmt.currency(p.revenue), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = strong())
                        }
                        Spacer(Modifier.height(4.dp))
                        ThinBar((p.revenue / maxRev).toFloat(), c.gold)
                    }
                    Text("×${qtyText(p.qty)}", fontSize = 10.sp, color = c.muted, textAlign = TextAlign.End, modifier = Modifier.width(44.dp))
                }
            }
        }
    }
}
