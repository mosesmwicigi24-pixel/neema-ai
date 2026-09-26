package ke.co.bethanyhouse.neema.feature.reports

import ke.co.bethanyhouse.neema.core.util.AppClock

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.outlined.CloudOff
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Agent
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.ui.components.Panel
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import androidx.compose.foundation.lazy.LazyColumn
import ke.co.bethanyhouse.neema.core.util.Fmt
import java.io.File

import java.time.Instant
import java.time.format.DateTimeFormatter
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.TextStyle
import java.util.Locale

/**
 * A badge as the web draws it: `px-1.5 py-0.5 rounded text-[10px] font-semibold`
 * on a Tailwind -50 tint. By night the text takes the -400 shade and the tint
 * becomes a wash of it, so the badges read on navy.
 */
private class Hue(val text: Color, val bg: Color, val nightText: Color)

private val EmeraldHue = Hue(Palette.Emerald700, Palette.Emerald50, Palette.Emerald400)
private val BlueHue = Hue(Palette.Blue700, Palette.Blue50, Palette.Blue400)
private val RedHue = Hue(Palette.Red600, Palette.Red50, Palette.Red400)
private val AmberHue = Hue(Palette.Amber700, Palette.Amber50, Palette.Amber400)
// The web's own greens: open #427425 on #f0f9ec; anything else #699a32 on #e6f3d8.
private val OpenHue = Hue(Palette.Moss700, Palette.Moss50, Palette.Willow400)
private val QuietHue = Hue(Palette.Willow600, Palette.Willow100, Palette.Sage400)

@Composable
private fun Badge(text: String, hue: Hue) {
    val dark = Neema.colors.isDark
    val fg = if (dark) hue.nightText else hue.text
    Text(
        text, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = fg, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(if (dark) fg.copy(alpha = 0.14f) else hue.bg)
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

/** CSS `text-transform: capitalize`: the first letter of every word. */
internal fun capitalizeWords(s: String): String =
    s.split(" ").joinToString(" ") { w -> w.replaceFirstChar { it.uppercaseChar() } }

/** Port of components/views/ReportsView.tsx — admin reports over a date range. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportsScreen(
    dash: DashboardViewModel,
    vm: ReportsViewModel = viewModel { ReportsViewModel(dash) },
) {
    TrackShown(vm.life)
    val allConvs by vm.allConvs.collectAsStateWithLifecycle()
    val report by vm.report.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val exporting by vm.exporting.collectAsStateWithLifecycle()
    val agents by dash.agents.collectAsStateWithLifecycle()
    val tab by vm.tab.collectAsStateWithLifecycle()
    val range by vm.range.collectAsStateWithLifecycle()
    val customFrom by vm.customFrom.collectAsStateWithLifecycle()
    val customTo by vm.customTo.collectAsStateWithLifecycle()
    val c = Neema.colors
    val context = LocalContext.current

    // Never show zeros that look like real figures while the data is loading.
    val loadError by vm.loadError.collectAsStateWithLifecycle()
    if (allConvs == null && loadError != null) {
        // The first download failed: say why and offer another go — a report
        // of zeros here would read as the truth.
        Box(Modifier.fillMaxSize().background(c.bg).padding(16.dp), contentAlignment = Alignment.Center) {
            ke.co.bethanyhouse.neema.core.ui.components.EmptyState(
                title = "Couldn't load the report",
                subtitle = loadError,
                icon = Icons.Outlined.CloudOff,
                modifier = Modifier.widthIn(max = 420.dp),
            ) {
                Button(
                    onClick = vm::retry, shape = RoundedCornerShape(8.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = c.gold, contentColor = MaterialTheme.colorScheme.onPrimary),
                ) { Text("Retry", fontSize = 13.sp, fontWeight = FontWeight.SemiBold) }
            }
        }
        return
    }
    // Still downloading, or the first report is being built off the main thread.
    val r = report
    if (r == null) {
        Box(Modifier.fillMaxSize().background(c.bg).padding(16.dp), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(24.dp))
                Spacer(Modifier.height(10.dp))
                Text("Loading every conversation for the report…", fontSize = 14.sp, color = c.textDim, textAlign = TextAlign.Center)
            }
        }
        return
    }

    // The visible table's rows, built once per report / tab — not on every
    // recomposition — with the agent lookup indexed rather than searched per row.
    val table = remember(r, tab, agents) { tableFor(tab, r, agents, vm.clock.millis()) }

    BoxWithConstraints(Modifier.fillMaxSize().background(c.bg)) {
        val wide = maxWidth >= 600.dp
        val pad = if (wide) 24.dp else 16.dp
        val panelWidth = maxWidth - pad * 2
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(pad)) {
                // ── Header ───────────────────────────────────────────────
                // Title left, range + export right (wide); stacked on a phone.
                item(key = "header", contentType = "header") {
                    val title: @Composable () -> Unit = {
                        Column {
                            Text("Reports", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = c.text)
                            Text(
                                "${range.label} · ${r.convs.size} conversations",
                                fontSize = 14.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp),
                            )
                        }
                    }
                    val controls: @Composable () -> Unit = {
                        RangeControls(
                            range = range,
                            customFrom = customFrom, customTo = customTo,
                            exporting = exporting,
                            onRange = { vm.range.value = it },
                            onFrom = { vm.customFrom.value = it },
                            onTo = { vm.customTo.value = it },
                            onExport = {
                                // Written on the I/O thread; only the share sheet opens here.
                                vm.exportCsv(File(context.cacheDir, "reports")) { file, forRange ->
                                    runCatching { shareCsv(context, file, forRange) }
                                        .onSuccess { dash.toast("Report exported") }
                                        .onFailure { dash.toast(exportFailureText(it), ToastType.Error) }
                                }
                            },
                        )
                    }
                    Column(Modifier.padding(bottom = if (wide) 24.dp else 16.dp)) {
                        if (wide) Row(verticalAlignment = Alignment.Top) {
                            Box(Modifier.weight(1f)) { title() }
                            Spacer(Modifier.width(16.dp))
                            controls()
                        } else {
                            title()
                            Spacer(Modifier.height(12.dp))
                            controls()
                        }
                    }
                }

                // ── Tabs ─────────────────────────────────────────────────
                // The web's tab strip: a hairline under the whole width, not just the tabs.
                item(key = "tabs", contentType = "tabs") {
                    Box(Modifier.fillMaxWidth().padding(bottom = 16.dp)) {
                        HorizontalDivider(color = c.bg4, modifier = Modifier.align(Alignment.BottomStart))
                        PrimaryScrollableTabRow(
                            selectedTabIndex = tab.ordinal,
                            edgePadding = 0.dp,
                            containerColor = Color.Transparent,
                            contentColor = c.gold2,
                            divider = {},
                        ) {
                            ReportTab.entries.forEach { t ->
                                Tab(
                                    selected = tab == t,
                                    onClick = { vm.tab.value = t },
                                    selectedContentColor = c.gold2,
                                    unselectedContentColor = if (c.isDark) c.muted else c.border2,
                                    text = { Text(t.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold) },
                                )
                            }
                        }
                    }
                }

                if (table == null) {
                    item(key = "overview", contentType = "overview") { OverviewTab(r, wide) }
                } else {
                    reportTable(tab.name, table, wide, panelWidth)
                }
                item(key = "end", contentType = "end") { Spacer(Modifier.height(24.dp)) }
            }
        }
    }
}

/** The table for [tab] (null for Overview): the web's first 50 conversations, first 20 orders, every agent. */
internal fun tableFor(tab: ReportTab, r: Report, agents: List<Agent>, now: Long): TableModel? = when (tab) {
    ReportTab.Overview -> null
    ReportTab.Conversations -> {
        // `agents.find(...)`: the first agent with the id, as the web picks it.
        val names = HashMap<String, String>(agents.size * 2)
        agents.forEach { names.putIfAbsent(it.id, it.name) }
        val shown = r.convs.take(50)
        TableModel(
            "${r.convs.size} conversations in period",
            listOf("Customer", "Channel", "Status", "Mode", "Last Activity", "Agent"),
            shown.map { conv -> conversationRow(conv, names, now) },
            uniqueKeys(shown.map { "c:${it.id}" }),
        )
    }
    ReportTab.Orders -> {
        val shown = r.orders.take(20)
        TableModel(
            "${r.orders.size} orders · ${Fmt.currency(r.revenue)} total",
            listOf("Customer", "Phone", "Amount", "Status", "Date"),
            shown.map { orderRow(it) },
            uniqueKeys(shown.map { "o:${it.id}" }),
        )
    }
    ReportTab.Agents -> TableModel(
        "Agent Performance",
        listOf("Agent", "Role", "Conversations", "Revenue", "Status"),
        r.agentStats.map { agentRow(it) },
        uniqueKeys(r.agentStats.map { "a:${it.agent.id}" }),
    )
}

// ── Computation ─────────────────────────────────────────────────────────────

data class AgentStat(val agent: Agent, val handled: Int, val revenue: Double)

class Report(
    val convs: List<Conversation>,
    val orders: List<Order>,
    val revenue: Double,
    val humanConvs: Int,
    val aiConvs: Int,
    val pending: Int,
    val confirmed: Int,
    val delivered: Int,
    val cancelled: Int,
    val convByDay: List<BarPoint>,
    val orderByDay: List<BarPoint>,
    val agentStats: List<AgentStat>,
)

/** The web's `mapConversation`: a thread with no messages yet dates from its creation. */
internal fun Conversation.reportAt(): String? = lastMessageAt ?: createdAt

/**
 * Every figure the web's ReportsView computes, for one range. Custom ranges
 * cover whole local days, "to" inclusive -- a deliberate fix: the web parses
 * `new Date("2026-09-01")` as UTC midnight, which silently drops the whole
 * "to" day (and starts "from" at 03:00 in Nairobi).
 */
internal fun buildReport(
    all: List<Conversation>, orders: List<Order>, agents: List<Agent>,
    range: ReportRange, customFrom: LocalDate?, customTo: LocalDate?,
    now: Long = AppClock.now(), zone: ZoneId = ZoneId.systemDefault(),
): Report = buildReportDated(datedConversations(all), datedOrders(orders), agents, range, customFrom, customTo, now, zone)

/** A row with its timestamp parsed once ([NO_DATE] when it has none or it doesn't parse). */
class Dated<T>(val item: T, val at: Long)

internal const val NO_DATE = Long.MIN_VALUE

/** Conversations dated as the web's `mapConversation` dates them (last message, else creation). */
internal fun datedConversations(all: List<Conversation>): List<Dated<Conversation>> =
    all.map { Dated(it, Fmt.millis(it.reportAt()) ?: NO_DATE) }

internal fun datedOrders(orders: List<Order>): List<Dated<Order>> =
    orders.map { Dated(it, Fmt.millis(it.createdAt) ?: NO_DATE) }

/**
 * [buildReport] over rows whose dates are already parsed: one pass per
 * figure, per-day buckets by binary search over the day boundaries, and
 * agent performance from per-agent / per-customer indexes instead of a scan
 * of every conversation and order for each agent — 10,000 conversations,
 * 1,000 orders and 200 agents build in a few milliseconds.
 */
internal fun buildReportDated(
    all: List<Dated<Conversation>>, orders: List<Dated<Order>>, agents: List<Agent>,
    range: ReportRange, customFrom: LocalDate?, customTo: LocalDate?,
    now: Long, zone: ZoneId,
): Report {
    val day = 86_400_000L
    // Date range (the web's daysAgo(): same time of day, n days back).
    val (from, to) = when {
        range == ReportRange.D7 -> now - 7 * day to now
        range == ReportRange.D90 -> now - 90 * day to now
        range == ReportRange.Custom && customFrom != null && customTo != null ->
            // Inclusive of the whole "to" day.
            customFrom.atStartOfDay(zone).toInstant().toEpochMilli() to
                customTo.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli() - 1
        else -> now - 30 * day to now
    }
    fun inRange(at: Long): Boolean = at != NO_DATE && at in from..to

    val datedConvs = all.filter { inRange(it.at) }
    val datedFOrders = orders.filter { inRange(it.at) }
    val convs = datedConvs.map { it.item }
    val fOrders = datedFOrders.map { it.item }
    val revenue = fOrders.filter { it.status != "cancelled" }.sumOf { it.total }

    // Per-day charts: at most 14 bars ending on the range's last day. Each
    // row lands in its local day by binary search over the days' start
    // instants (DST-safe, no per-row calendar maths).
    val days = when (range) { ReportRange.D7 -> 7; ReportRange.D30 -> 14; else -> 30 }
    val n = minOf(days, 14)
    val toDay = Instant.ofEpochMilli(to).atZone(zone).toLocalDate()
    val dayList = (0 until n).map { i -> toDay.minusDays((n - 1 - i).toLong()) }
    val starts = LongArray(n + 1) { i ->
        (if (i < n) dayList[i] else toDay.plusDays(1)).atStartOfDay(zone).toInstant().toEpochMilli()
    }
    fun bucket(at: Long): Int {
        if (at < starts[0] || at >= starts[n]) return -1
        val i = java.util.Arrays.binarySearch(starts, at)
        return if (i >= 0) i else -i - 2
    }
    val convCounts = IntArray(n)
    datedConvs.forEach { d -> bucket(d.at).takeIf { it >= 0 }?.let { convCounts[it]++ } }
    // Summed in list order per day, exactly as the web's reduce adds them.
    val orderSums = DoubleArray(n)
    datedFOrders.forEach { d -> bucket(d.at).takeIf { it >= 0 }?.let { orderSums[it] += d.item.total } }
    fun wk(d: LocalDate) = d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH)
    val convByDay = dayList.mapIndexed { i, d -> BarPoint(wk(d), convCounts[i].toDouble()) }
    val orderByDay = dayList.mapIndexed { i, d -> BarPoint(wk(d), orderSums[i]) }

    // Agent performance: threads they hold, and orders from those customers.
    // Indexed once — never every conversation and order scanned per agent.
    val byAgent = HashMap<String, MutableList<Conversation>>()
    convs.forEach { conv -> conv.assignedAgentId?.let { byAgent.getOrPut(it) { ArrayList() } += conv } }
    val ordersByCustomer = HashMap<String, MutableList<Int>>()
    fOrders.forEachIndexed { i, o -> if (o.waId.isNotEmpty()) ordersByCustomer.getOrPut(o.waId) { ArrayList() } += i }
    val agentStats = agents.map { a ->
        val mine = byAgent[a.id].orEmpty()
        val waIds = mine.mapNotNullTo(HashSet()) { it.waId }
        // The same orders the web's filter keeps, added in the same (list) order.
        val idx = waIds.flatMap { ordersByCustomer[it].orEmpty() }.sorted()
        var rev = 0.0
        idx.forEach { rev += fOrders[it].total }
        AgentStat(a, mine.size, rev)
    }.sortedByDescending { it.handled }

    var human = 0; var ai = 0
    convs.forEach { when (it.interceptMode) { "human" -> human++; "ai" -> ai++ } }
    var pending = 0; var confirmed = 0; var delivered = 0; var cancelled = 0
    fOrders.forEach {
        when (it.status) { "pending" -> pending++; "confirmed" -> confirmed++; "delivered" -> delivered++; "cancelled" -> cancelled++ }
    }
    return Report(
        convs = convs, orders = fOrders, revenue = revenue,
        humanConvs = human, aiConvs = ai,
        pending = pending, confirmed = confirmed, delivered = delivered, cancelled = cancelled,
        convByDay = convByDay, orderByDay = orderByDay, agentStats = agentStats,
    )
}

// ── Header controls ─────────────────────────────────────────────────────────

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun RangeControls(
    range: ReportRange,
    customFrom: LocalDate?, customTo: LocalDate?,
    onRange: (ReportRange) -> Unit,
    onFrom: (LocalDate) -> Unit,
    onTo: (LocalDate) -> Unit,
    exporting: Boolean,
    onExport: () -> Unit,
) {
    val c = Neema.colors
    var menu by remember { mutableStateOf(false) }
    var picking by remember { mutableStateOf<String?>(null) } // "from" | "to"

    @OptIn(ExperimentalLayoutApi::class)
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp), itemVerticalAlignment = Alignment.CenterVertically) {
        Box {
            OutlinedButton(
                onClick = { menu = true }, shape = RoundedCornerShape(8.dp),
                contentPadding = PaddingValues(horizontal = 12.dp), modifier = Modifier.heightIn(min = 38.dp),
            ) {
                Text(range.label, fontSize = 13.sp, color = c.text)
                Icon(Icons.Outlined.ExpandMore, null, modifier = Modifier.size(18.dp))
            }
            DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                ReportRange.entries.forEach { r ->
                    DropdownMenuItem(text = { Text(r.label) }, onClick = { onRange(r); menu = false })
                }
            }
        }
        if (range == ReportRange.Custom) {
            DateButton(customFrom) { picking = "from" }
            Text("to", fontSize = 12.sp, color = c.border2)
            DateButton(customTo) { picking = "to" }
        }
        // The web shows Export CSV to everyone who can open Reports (it never
        // checks export_reports), so this does too.
        run {
            Button(
                onClick = onExport, enabled = !exporting, shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = c.gold, contentColor = MaterialTheme.colorScheme.onPrimary,
                    // Writing the file: the button stays itself, just quieter, while a second tap is ignored.
                    disabledContainerColor = c.gold.copy(alpha = 0.7f), disabledContentColor = MaterialTheme.colorScheme.onPrimary,
                ),
                contentPadding = PaddingValues(horizontal = 14.dp), modifier = Modifier.heightIn(min = 38.dp),
            ) {
                Icon(Icons.Outlined.Download, null, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(6.dp))
                Text("Export CSV", fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            }
        }
    }

    picking?.let { which ->
        val initial = if (which == "from") customFrom else customTo
        val state = rememberDatePickerState(
            initialSelectedDateMillis = initial?.atStartOfDay(ZoneOffset.UTC)?.toInstant()?.toEpochMilli(),
        )
        DatePickerDialog(
            onDismissRequest = { picking = null },
            confirmButton = {
                TextButton(onClick = {
                    state.selectedDateMillis?.let {
                        // The picker speaks UTC midnight.
                        val d = Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate()
                        if (which == "from") onFrom(d) else onTo(d)
                    }
                    picking = null
                }) { Text("OK") }
            },
            dismissButton = { TextButton(onClick = { picking = null }) { Text("Cancel") } },
        ) { DatePicker(state) }
    }
}

@Composable
private fun DateButton(date: LocalDate?, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick, shape = RoundedCornerShape(8.dp),
        contentPadding = PaddingValues(horizontal = 10.dp), modifier = Modifier.heightIn(min = 38.dp),
    ) {
        Icon(Icons.Outlined.CalendarMonth, null, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        // The web's <input type="date"> in en-KE reads dd/mm/yyyy.
        Text(date?.format(DateTimeFormatter.ofPattern("dd/MM/yyyy")) ?: "dd/mm/yyyy", fontSize = 12.sp, color = if (date == null) Neema.colors.muted else Neema.colors.text)
    }
}

// ── Overview tab ────────────────────────────────────────────────────────────

@Composable
private fun OverviewTab(r: Report, wide: Boolean) {
    val c = Neema.colors
    val deliveryRate = if (r.orders.isNotEmpty()) Math.round(r.delivered * 100.0 / r.orders.size) else 0
    val tiles = listOf<@Composable (Modifier) -> Unit>(
        { StatBox("Total Conversations", r.convs.size.toString(), "${r.humanConvs} human · ${r.aiConvs} AI", c.gold, it) },
        { StatBox("Revenue", Fmt.currency(r.revenue), "${r.orders.size} orders", c.gold2, it) },
        { StatBox("Pending Orders", r.pending.toString(), "Awaiting confirmation", c.amber, it) },
        { StatBox("Delivered Orders", r.delivered.toString(), "$deliveryRate% delivery rate", c.blue, it) },
    )
    BoxWithConstraints { val width = maxWidth; Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        // The web's grid-cols-2 / grid-cols-4, fewer when the cards would be
        // too narrow for their figures (a foldable, or a large font).
        val cols = gridColumns(width, if (wide) 4 else 2)
        tiles.chunked(cols).forEach { rowTiles ->
            // Equal heights across a row, like the web's grid.
            Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                rowTiles.forEach { it(Modifier.weight(1f).fillMaxHeight()) }
                repeat(cols - rowTiles.size) { Spacer(Modifier.weight(1f)) }
            }
        }
        val convChart: @Composable (Modifier) -> Unit = {
            Panel(it) {
                ChartTitle("Conversations over time")
                MiniBar(r.convByDay, c.gold)
            }
        }
        val revChart: @Composable (Modifier) -> Unit = {
            Panel(it) {
                ChartTitle("Revenue over time (KES)")
                MiniBar(r.orderByDay, c.blue) { v -> plain(v) }
            }
        }
        if (wide) Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            convChart(Modifier.weight(1f)); revChart(Modifier.weight(1f))
        } else {
            convChart(Modifier.fillMaxWidth()); revChart(Modifier.fillMaxWidth())
        }

        Panel(Modifier.fillMaxWidth()) {
            ChartTitle("Order Status Breakdown")
            Spacer(Modifier.height(4.dp))
            val items = listOf(
                // The web's #bcc13e / #2a48a2 / #589b31 / #c0392b — the theme's own hues, lifted by night.
                Triple("Pending", c.amber, r.pending),
                Triple("Confirmed", c.blue, r.confirmed),
                Triple("Delivered", c.green, r.delivered),
                Triple("Cancelled", c.red, r.cancelled),
            )
            // The web's grid-cols-4; two by two when "Confirmed" wouldn't fit a quarter.
            BoxWithConstraints {
                val perRow = if (gridColumns(maxWidth, 4, minCell = 64.dp, minWideCell = 72.dp) > 2) 4 else 2
                Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    items.chunked(perRow).forEach { line ->
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                            line.forEach { (label, color, count) ->
                                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                                    BigNumber(count.toString(), color, max = 20.sp)
                                    Text(label, fontSize = 11.sp, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
                                    Spacer(Modifier.height(8.dp))
                                    val frac = if (r.orders.isNotEmpty()) count.toFloat() / r.orders.size else 0f
                                    Box(Modifier.fillMaxWidth().height(4.dp).clip(CircleShape).background(c.bg3)) {
                                        Box(Modifier.fillMaxWidth(frac).fillMaxHeight().clip(CircleShape).background(color))
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    }
}

@Composable
private fun ChartTitle(text: String) {
    Text(
        text.uppercase(), fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp,
        color = Neema.colors.muted, modifier = Modifier.padding(bottom = 8.dp),
    )
}

// ── Table rows ──────────────────────────────────────────────────────────────

private fun conversationRow(conv: Conversation, agentNames: Map<String, String>, now: Long): List<Cell> = listOf(
    textCell(Fmt.displayName(conv.name, conv.waId)),
    // `<span className="capitalize">{c.channel || "whatsapp"}</span>`
    textCell(capitalizeWords(conv.channel.ifEmpty { "whatsapp" })),
    { Badge(conv.status, if (conv.status == "open") OpenHue else QuietHue) },
    {
        Badge(
            conv.interceptMode,
            when (conv.interceptMode) { "human" -> AmberHue; "ai" -> BlueHue; else -> QuietHue },
        )
    },
    textCell(Fmt.timeAgo(conv.reportAt(), now)),
    // `?.name || "—"`: an agent with a blank name reads "—" too.
    textCell(conv.assignedAgentId?.let(agentNames::get)?.takeIf { it.isNotEmpty() } ?: "—"),
)

private fun orderStatusHue(status: String): Hue = when (status) {
    "delivered" -> EmeraldHue
    "confirmed" -> BlueHue
    "cancelled" -> RedHue
    else -> AmberHue
}

private fun orderRow(o: Order): List<Cell> {
    val phone = o.contactPhone?.takeIf { it.isNotBlank() } ?: o.waId
    return listOf(
        textCell(Fmt.displayName(o.contactName, phone)),
        textCell(Fmt.formatPhone(phone)),
        textCell(Fmt.currency(o.total)),
        { Badge(o.status, orderStatusHue(o.status)) },
        textCell(Fmt.date(o.createdAt)),
    )
}

private fun agentRow(s: AgentStat): List<Cell> = listOf(
    textCell(s.agent.name),
    {
        val c = Neema.colors
        Text(
            capitalizeWords(s.agent.role),
            fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = c.gold2,
            modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(c.goldDim)
                .border(1.dp, c.border, RoundedCornerShape(4.dp)).padding(horizontal = 6.dp, vertical = 2.dp),
        )
    },
    textCell(s.handled.toString()),
    textCell(Fmt.currency(s.revenue)),
    {
        val c = Neema.colors
        val on = s.agent.isAvailable
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(6.dp).clip(CircleShape).background(if (on) c.gold else Palette.Stone300))
            Spacer(Modifier.width(4.dp))
            Text(if (on) "Online" else "Offline", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = if (on) c.gold else c.border2)
        }
    },
)

// ── CSV export ──────────────────────────────────────────────────────────────

/** "1500" not "1500.0" — the web prints the raw number. */
internal fun plain(v: Double): String = if (v == Math.floor(v) && !v.isInfinite()) v.toLong().toString() else v.toString()

internal fun csvField(s: String): String =
    if (s.any { it == ',' || it == '"' || it == '\n' || it == '\r' }) "\"" + s.replace("\"", "\"\"") + "\"" else s

/**
 * The web downloads `neema-report-<range>.csv`; on a phone the same file is
 * written to the cache and handed to the share sheet (email, Drive, WhatsApp…).
 */
/**
 * The web's CSV: `Date,Customer,Amount,Status`, one line per order in range.
 * Fields are RFC-4180 quoted when they need it -- the web writes them bare, so
 * a customer called "Kamau, Peter" split into two columns there.
 */
internal fun reportCsv(orders: List<Order>): String = buildString { writeCsv(this, orders) }

/** The CSV written straight to [out], one row at a time (10,000 orders never become one string). */
internal fun writeCsv(out: Appendable, orders: List<Order>) {
    out.append("Date,Customer,Amount,Status\n")
    orders.forEachIndexed { i, o ->
        if (i > 0) out.append('\n')
        val phone = o.contactPhone?.takeIf { it.isNotBlank() } ?: o.waId
        out.append(csvField(Fmt.date(o.createdAt))).append(',')
            .append(csvField(Fmt.displayName(o.contactName, phone))).append(',')
            .append(csvField(plain(o.total))).append(',')
            .append(csvField(o.status))
    }
}

internal fun csvFileName(range: ReportRange) = "neema-report-${range.key}.csv"

/**
 * Streams the CSV into [dir] (created if needed) through a buffered writer;
 * throws an IOException when the phone can't store it. Written to a temporary
 * name first, so a failure halfway never leaves a truncated report to share.
 */
internal fun writeReportCsv(dir: File, orders: List<Order>, range: ReportRange): File {
    if (!dir.isDirectory && !dir.mkdirs()) throw java.io.IOException("can't create ${dir.name}")
    val file = File(dir, csvFileName(range))
    val part = File(dir, file.name + ".part")
    try {
        part.bufferedWriter(Charsets.UTF_8, 64 * 1024).use { writeCsv(it, orders) }
        if (!part.renameTo(file)) {
            file.delete()
            if (!part.renameTo(file)) throw java.io.IOException("can't save ${file.name}")
        }
    } finally { part.delete() }
    return file
}

/** Why an export didn't reach the share sheet, in words that say what to do. */
internal fun exportFailureText(e: Throwable): String = when (e) {
    is android.content.ActivityNotFoundException ->
        "No app on this phone can receive the CSV — install Gmail, Drive or a file manager, then export again."
    is java.io.IOException, is SecurityException ->
        "Couldn't save the report file — free up some storage on this phone and try again."
    is IllegalArgumentException -> "Couldn't share the report file — try again."
    else -> "Couldn't export the report — try again."
}

private fun shareCsv(context: Context, file: File, range: ReportRange) {
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/csv"
        putExtra(Intent.EXTRA_STREAM, uri)
        putExtra(Intent.EXTRA_SUBJECT, "Neema report — ${range.label}")
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(Intent.createChooser(send, "Export report").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}
