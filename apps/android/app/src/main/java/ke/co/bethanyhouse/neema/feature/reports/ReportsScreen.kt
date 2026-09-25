package ke.co.bethanyhouse.neema.feature.reports

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
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.ChannelChip
import ke.co.bethanyhouse.neema.core.ui.components.Panel
import ke.co.bethanyhouse.neema.core.ui.components.Pill
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import java.io.File
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.TextStyle
import java.util.Locale

// Badge hues the web takes from Tailwind (emerald / blue / red / amber).
private val Emerald = Color(0xFF047857)
private val Blue700 = Color(0xFF1D4ED8)
private val Red600 = Color(0xFFDC2626)
private val Amber700 = Color(0xFFB45309)

/** Port of components/views/ReportsView.tsx — admin reports over a date range. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ReportsScreen(dash: DashboardViewModel) {
    val vm: ReportsViewModel = viewModel { ReportsViewModel(dash) }
    val allConvs by vm.allConvs.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val agents by dash.agents.collectAsStateWithLifecycle()
    val orders by dash.orders.collectAsStateWithLifecycle()
    val tab by vm.tab.collectAsStateWithLifecycle()
    val range by vm.range.collectAsStateWithLifecycle()
    val customFrom by vm.customFrom.collectAsStateWithLifecycle()
    val customTo by vm.customTo.collectAsStateWithLifecycle()
    val c = Neema.colors
    val context = LocalContext.current

    // Never show zeros that look like real figures while the data is loading.
    val convs = allConvs
    if (convs == null) {
        Box(Modifier.fillMaxSize().background(c.bg).padding(16.dp), contentAlignment = Alignment.Center) {
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                CircularProgressIndicator(strokeWidth = 2.dp, modifier = Modifier.size(24.dp))
                Spacer(Modifier.height(10.dp))
                Text("Loading every conversation for the report…", fontSize = 14.sp, color = c.textDim, textAlign = TextAlign.Center)
            }
        }
        return
    }

    val report = remember(convs, orders, agents, range, customFrom, customTo) {
        buildReport(convs, orders, agents, range, customFrom, customTo)
    }
    dash.me.collectAsStateWithLifecycle() // recompose when permissions arrive
    val canExport = dash.can(Perms.EXPORT_REPORTS)

    BoxWithConstraints(Modifier.fillMaxSize().background(c.bg)) {
        val wide = maxWidth >= 600.dp
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                    .padding(if (wide) 24.dp else 16.dp),
            ) {
                // ── Header ───────────────────────────────────────────────
                Text("Reports", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = c.text)
                Text(
                    "${range.label} · ${report.convs.size} conversations",
                    fontSize = 14.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp),
                )
                Spacer(Modifier.height(12.dp))
                RangeControls(
                    range = range,
                    customFrom = customFrom, customTo = customTo,
                    onRange = { vm.range.value = it },
                    onFrom = { vm.customFrom.value = it },
                    onTo = { vm.customTo.value = it },
                    canExport = canExport,
                    onExport = {
                        runCatching { exportCsv(context, report.orders, range) }
                            .onSuccess { dash.toast("Report exported") }
                            .onFailure { dash.toast(dash.errorText(it), ToastType.Error) }
                    },
                )
                Spacer(Modifier.height(16.dp))

                // ── Tabs ─────────────────────────────────────────────────
                PrimaryScrollableTabRow(
                    selectedTabIndex = tab.ordinal,
                    edgePadding = 0.dp,
                    containerColor = Color.Transparent,
                    contentColor = c.gold2,
                    divider = { HorizontalDivider(color = c.bg4) },
                ) {
                    ReportTab.entries.forEach { t ->
                        Tab(
                            selected = tab == t,
                            onClick = { vm.tab.value = t },
                            selectedContentColor = c.gold2,
                            unselectedContentColor = c.border2,
                            text = { Text(t.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold) },
                        )
                    }
                }
                Spacer(Modifier.height(16.dp))

                when (tab) {
                    ReportTab.Overview -> OverviewTab(report, wide)
                    ReportTab.Conversations -> ReportTable(
                        header = "${report.convs.size} conversations in period",
                        cols = listOf("Customer", "Channel", "Status", "Mode", "Last Activity", "Agent"),
                        rows = report.convs.take(50).map { conv -> conversationRow(conv, agents) },
                        wide = wide,
                    )
                    ReportTab.Orders -> ReportTable(
                        header = "${report.orders.size} orders · ${Fmt.currency(report.revenue)} total",
                        cols = listOf("Customer", "Phone", "Amount", "Status", "Date"),
                        rows = report.orders.take(20).map { orderRow(it) },
                        wide = wide,
                    )
                    ReportTab.Agents -> ReportTable(
                        header = "Agent Performance",
                        cols = listOf("Agent", "Role", "Conversations", "Revenue", "Status"),
                        rows = report.agentStats.map { agentRow(it) },
                        wide = wide,
                    )
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

// ── Computation ─────────────────────────────────────────────────────────────

class AgentStat(val agent: Agent, val handled: Int, val revenue: Double)

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

private fun buildReport(
    all: List<Conversation>, orders: List<Order>, agents: List<Agent>,
    range: ReportRange, customFrom: LocalDate?, customTo: LocalDate?,
): Report {
    val zone = ZoneId.systemDefault()
    val now = System.currentTimeMillis()
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
    fun inRange(iso: String?): Boolean = Fmt.millis(iso)?.let { it in from..to } ?: false
    fun localDay(iso: String?): LocalDate? = Fmt.millis(iso)?.let { Instant.ofEpochMilli(it).atZone(zone).toLocalDate() }

    val convs = all.filter { inRange(it.lastMessageAt) }
    val fOrders = orders.filter { inRange(it.createdAt) }
    val revenue = fOrders.filter { it.status != "cancelled" }.sumOf { it.total }

    // Per-day charts: at most 14 bars ending on the range's last day.
    val days = when (range) { ReportRange.D7 -> 7; ReportRange.D30 -> 14; else -> 30 }
    val n = minOf(days, 14)
    val toDay = Instant.ofEpochMilli(to).atZone(zone).toLocalDate()
    val dayList = (0 until n).map { i -> toDay.minusDays((n - 1 - i).toLong()) }
    val convDays = convs.groupingBy { localDay(it.lastMessageAt) }.eachCount()
    val orderDays = fOrders.groupBy { localDay(it.createdAt) }
    fun wk(d: LocalDate) = d.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.ENGLISH)
    val convByDay = dayList.map { BarPoint(wk(it), (convDays[it] ?: 0).toDouble()) }
    val orderByDay = dayList.map { d -> BarPoint(wk(d), orderDays[d].orEmpty().sumOf { it.total }) }

    // Agent performance: threads they hold, and orders from those customers.
    val agentStats = agents.map { a ->
        val mine = convs.filter { it.assignedAgentId == a.id }
        val waIds = mine.mapNotNull { it.waId }.toSet()
        val rev = fOrders.filter { it.waId.isNotEmpty() && it.waId in waIds }.sumOf { it.total }
        AgentStat(a, mine.size, rev)
    }.sortedByDescending { it.handled }

    return Report(
        convs = convs, orders = fOrders, revenue = revenue,
        humanConvs = convs.count { it.interceptMode == "human" },
        aiConvs = convs.count { it.interceptMode == "ai" },
        pending = fOrders.count { it.status == "pending" },
        confirmed = fOrders.count { it.status == "confirmed" },
        delivered = fOrders.count { it.status == "delivered" },
        cancelled = fOrders.count { it.status == "cancelled" },
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
    canExport: Boolean,
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
                contentPadding = PaddingValues(horizontal = 12.dp), modifier = Modifier.height(38.dp),
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
        if (canExport) {
            Button(
                onClick = onExport, shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = c.gold, contentColor = Color.White),
                contentPadding = PaddingValues(horizontal = 14.dp), modifier = Modifier.height(38.dp),
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
        contentPadding = PaddingValues(horizontal = 10.dp), modifier = Modifier.height(38.dp),
    ) {
        Icon(Icons.Outlined.CalendarMonth, null, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text(date?.toString() ?: "dd/mm/yyyy", fontSize = 12.sp, color = if (date == null) Neema.colors.muted else Neema.colors.text)
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
        { StatBox("Pending Orders", r.pending.toString(), "Awaiting confirmation", Color(0xFFBCC13E), it) },
        { StatBox("Delivered Orders", r.delivered.toString(), "$deliveryRate% delivery rate", Color(0xFF2A48A2), it) },
    )
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        tiles.chunked(if (wide) 4 else 2).forEach { rowTiles ->
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                rowTiles.forEach { it(Modifier.weight(1f)) }
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
                MiniBar(r.orderByDay, Color(0xFF2A48A2)) { v -> Fmt.currency(v) }
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
                Triple("Pending", Color(0xFFBCC13E), r.pending),
                Triple("Confirmed", Color(0xFF2A48A2), r.confirmed),
                Triple("Delivered", Color(0xFF589B31), r.delivered),
                Triple("Cancelled", Color(0xFFC0392B), r.cancelled),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                items.forEach { (label, color, count) ->
                    Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(count.toString(), fontSize = 20.sp, fontWeight = FontWeight.Bold, color = color)
                        Text(label, fontSize = 11.sp, color = c.muted, maxLines = 1)
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

@Composable
private fun ChartTitle(text: String) {
    Text(
        text.uppercase(), fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.6.sp,
        color = Neema.colors.muted, modifier = Modifier.padding(bottom = 8.dp),
    )
}

// ── Table rows ──────────────────────────────────────────────────────────────

private fun conversationRow(conv: Conversation, agents: List<Agent>): List<Cell> = listOf(
    textCell(Fmt.displayName(conv.name, conv.waId)),
    { ChannelChip(conv.channel.ifEmpty { "whatsapp" }) },
    {
        val c = Neema.colors
        Pill(conv.status, if (conv.status == "open") c.gold2 else c.textDim)
    },
    {
        val c = Neema.colors
        Pill(
            conv.interceptMode,
            when (conv.interceptMode) { "human" -> Amber700; "ai" -> Blue700; else -> c.textDim },
        )
    },
    textCell(Fmt.timeAgo(conv.lastMessageAt)),
    textCell(agents.find { it.id == conv.assignedAgentId }?.name ?: "—"),
)

private fun orderStatusColor(status: String): Color = when (status) {
    "delivered" -> Emerald
    "confirmed" -> Blue700
    "cancelled" -> Red600
    else -> Amber700
}

private fun orderRow(o: Order): List<Cell> {
    val phone = o.contactPhone?.takeIf { it.isNotBlank() } ?: o.waId
    return listOf(
        textCell(Fmt.displayName(o.contactName, phone)),
        textCell(Fmt.formatPhone(phone)),
        textCell(Fmt.currency(o.total)),
        { Pill(o.status, orderStatusColor(o.status)) },
        textCell(Fmt.date(o.createdAt)),
    )
}

private fun agentRow(s: AgentStat): List<Cell> = listOf(
    textCell(s.agent.name),
    {
        val c = Neema.colors
        Text(
            s.agent.role.replaceFirstChar { it.uppercase() },
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
            Box(Modifier.size(6.dp).clip(CircleShape).background(if (on) c.gold else Color(0xFFD6D3D1)))
            Spacer(Modifier.width(4.dp))
            Text(if (on) "Online" else "Offline", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = if (on) c.gold else c.border2)
        }
    },
)

// ── CSV export ──────────────────────────────────────────────────────────────

/** "1500" not "1500.0" — the web prints the raw number. */
private fun plain(v: Double): String = if (v == Math.floor(v) && !v.isInfinite()) v.toLong().toString() else v.toString()

private fun csvField(s: String): String =
    if (s.any { it == ',' || it == '"' || it == '\n' }) "\"" + s.replace("\"", "\"\"") + "\"" else s

/**
 * The web downloads `neema-report-<range>.csv`; on a phone the same file is
 * written to the cache and handed to the share sheet (email, Drive, WhatsApp…).
 */
private fun exportCsv(context: Context, orders: List<Order>, range: ReportRange) {
    val header = "Date,Customer,Amount,Status\n"
    val rows = orders.joinToString("\n") { o ->
        val phone = o.contactPhone?.takeIf { it.isNotBlank() } ?: o.waId
        listOf(Fmt.date(o.createdAt), Fmt.displayName(o.contactName, phone), plain(o.total), o.status)
            .joinToString(",") { csvField(it) }
    }
    val dir = File(context.cacheDir, "reports").apply { mkdirs() }
    val file = File(dir, "neema-report-${range.key}.csv")
    file.writeText(header + rows)
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/csv"
        putExtra(Intent.EXTRA_STREAM, uri)
        putExtra(Intent.EXTRA_SUBJECT, "Neema report — ${range.label}")
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(Intent.createChooser(send, "Export report").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}
