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
import ke.co.bethanyhouse.neema.core.util.Fmt
import java.io.File
import java.time.Clock
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

private val EmeraldHue = Hue(Color(0xFF047857), Color(0xFFECFDF5), Color(0xFF34D399))
private val BlueHue = Hue(Color(0xFF1D4ED8), Color(0xFFEFF6FF), Color(0xFF60A5FA))
private val RedHue = Hue(Color(0xFFDC2626), Color(0xFFFEF2F2), Color(0xFFF87171))
private val AmberHue = Hue(Color(0xFFB45309), Color(0xFFFFFBEB), Color(0xFFFBBF24))
// The web's own greens: open #427425 on #f0f9ec; anything else #699a32 on #e6f3d8.
private val OpenHue = Hue(Color(0xFF427425), Color(0xFFF0F9EC), Color(0xFF9CCD65))
private val QuietHue = Hue(Color(0xFF699A32), Color(0xFFE6F3D8), Color(0xFF8A9E80))

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
    /** "Now" for the date range and the per-day charts (fixed in tests). */
    clock: Clock = Clock.systemDefaultZone(),
) {
    TrackShown(vm.life)
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
    val loadError by vm.loadError.collectAsStateWithLifecycle()
    if (convs == null && loadError != null) {
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

    val report = remember(convs, orders, agents, range, customFrom, customTo, clock) {
        buildReport(convs, orders, agents, range, customFrom, customTo, clock.millis(), clock.zone)
    }

    BoxWithConstraints(Modifier.fillMaxSize().background(c.bg)) {
        val wide = maxWidth >= 600.dp
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                    .padding(if (wide) 24.dp else 16.dp),
            ) {
                // ── Header ───────────────────────────────────────────────
                // Title left, range + export right (wide); stacked on a phone.
                val title: @Composable () -> Unit = {
                    Column {
                        Text("Reports", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = c.text)
                        Text(
                            "${range.label} · ${report.convs.size} conversations",
                            fontSize = 14.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }
                val controls: @Composable () -> Unit = {
                    RangeControls(
                        range = range,
                        customFrom = customFrom, customTo = customTo,
                        onRange = { vm.range.value = it },
                        onFrom = { vm.customFrom.value = it },
                        onTo = { vm.customTo.value = it },
                        onExport = {
                            runCatching { exportCsv(context, report.orders, range) }
                                .onSuccess { dash.toast("Report exported") }
                                .onFailure { dash.toast(exportFailureText(it), ToastType.Error) }
                        },
                    )
                }
                if (wide) Row(verticalAlignment = Alignment.Top) {
                    Box(Modifier.weight(1f)) { title() }
                    Spacer(Modifier.width(16.dp))
                    controls()
                } else {
                    title()
                    Spacer(Modifier.height(12.dp))
                    controls()
                }
                Spacer(Modifier.height(if (wide) 24.dp else 16.dp))

                // ── Tabs ─────────────────────────────────────────────────
                // The web's tab strip: a hairline under the whole width, not just the tabs.
                Box(Modifier.fillMaxWidth()) {
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
                Spacer(Modifier.height(16.dp))

                when (tab) {
                    ReportTab.Overview -> OverviewTab(report, wide)
                    ReportTab.Conversations -> ReportTable(
                        header = "${report.convs.size} conversations in period",
                        cols = listOf("Customer", "Channel", "Status", "Mode", "Last Activity", "Agent"),
                        rows = report.convs.take(50).map { conv -> conversationRow(conv, agents, clock.millis()) },
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
    fun inRange(iso: String?): Boolean = Fmt.millis(iso)?.let { it in from..to } ?: false
    fun localDay(iso: String?): LocalDate? = Fmt.millis(iso)?.let { Instant.ofEpochMilli(it).atZone(zone).toLocalDate() }

    val convs = all.filter { inRange(it.reportAt()) }
    val fOrders = orders.filter { inRange(it.createdAt) }
    val revenue = fOrders.filter { it.status != "cancelled" }.sumOf { it.total }

    // Per-day charts: at most 14 bars ending on the range's last day.
    val days = when (range) { ReportRange.D7 -> 7; ReportRange.D30 -> 14; else -> 30 }
    val n = minOf(days, 14)
    val toDay = Instant.ofEpochMilli(to).atZone(zone).toLocalDate()
    val dayList = (0 until n).map { i -> toDay.minusDays((n - 1 - i).toLong()) }
    val convDays = convs.groupingBy { localDay(it.reportAt()) }.eachCount()
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
        // The web shows Export CSV to everyone who can open Reports (it never
        // checks export_reports), so this does too.
        run {
            Button(
                onClick = onExport, shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = c.gold, contentColor = MaterialTheme.colorScheme.onPrimary),
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
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        tiles.chunked(if (wide) 4 else 2).forEach { rowTiles ->
            // Equal heights across a row, like the web's grid.
            Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                rowTiles.forEach { it(Modifier.weight(1f).fillMaxHeight()) }
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

private fun conversationRow(conv: Conversation, agents: List<Agent>, now: Long): List<Cell> = listOf(
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
    textCell(agents.find { it.id == conv.assignedAgentId }?.name?.takeIf { it.isNotEmpty() } ?: "—"),
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
            Box(Modifier.size(6.dp).clip(CircleShape).background(if (on) c.gold else Color(0xFFD6D3D1)))
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
internal fun reportCsv(orders: List<Order>): String {
    val header = "Date,Customer,Amount,Status\n"
    val rows = orders.joinToString("\n") { o ->
        val phone = o.contactPhone?.takeIf { it.isNotBlank() } ?: o.waId
        listOf(Fmt.date(o.createdAt), Fmt.displayName(o.contactName, phone), plain(o.total), o.status)
            .joinToString(",") { csvField(it) }
    }
    return header + rows
}

internal fun csvFileName(range: ReportRange) = "neema-report-${range.key}.csv"

/** Writes the CSV into [dir] (created if needed); throws an IOException when the phone can't store it. */
internal fun writeReportCsv(dir: File, orders: List<Order>, range: ReportRange): File {
    if (!dir.isDirectory && !dir.mkdirs()) throw java.io.IOException("can't create ${dir.name}")
    val file = File(dir, csvFileName(range))
    file.writeText(reportCsv(orders))
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

private fun exportCsv(context: Context, orders: List<Order>, range: ReportRange) {
    val file = writeReportCsv(File(context.cacheDir, "reports"), orders, range)
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", file)
    val send = Intent(Intent.ACTION_SEND).apply {
        type = "text/csv"
        putExtra(Intent.EXTRA_STREAM, uri)
        putExtra(Intent.EXTRA_SUBJECT, "Neema report — ${range.label}")
        addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    }
    context.startActivity(Intent.createChooser(send, "Export report").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
}
