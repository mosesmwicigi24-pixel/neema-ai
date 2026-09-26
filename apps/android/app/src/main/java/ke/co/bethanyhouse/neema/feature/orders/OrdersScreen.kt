package ke.co.bethanyhouse.neema.feature.orders

import androidx.compose.ui.semantics.Role
import androidx.compose.runtime.remember
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.unit.Dp
import androidx.compose.material.icons.filled.Close
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.Order
import ke.co.bethanyhouse.neema.core.model.OrderItem
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.Loading
import ke.co.bethanyhouse.neema.core.ui.components.channelStyle
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.util.Fmt

private const val PAGE_SIZE = 15

/**
 * `fmtCurrency`: "KES 1,234". An order's own figures carry its own currency
 * (admin.py `update_order`/`list_orders` rows have `currency` = the hub's
 * `currency_code`, so a Zambian order is ZMW) — the web prints every order as
 * KES, which misstates a USD/ZMW order; the revenue sums stay KES as on the web.
 */
private fun money(n: Double?, currency: String = "KES"): String = Fmt.currency(n ?: 0.0, currency.ifBlank { "KES" })

/** 2.0 → "2", 1.5 → "1.5". */
private fun qtyText(q: Double): String = if (q == Math.floor(q)) q.toLong().toString() else q.toString()


/**
 * Port of components/views/OrdersView.tsx: revenue header, status cards that
 * double as filters, search, a paginated list with hub linkage, and the order
 * detail (a bottom sheet) with the status moves.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrdersScreen(dash: DashboardViewModel) {
    // No permission gate, as on the web: page.tsx shows Orders to every agent
    // and OrdersView checks no permission (not view_orders, not manage_orders),
    // and routers/admin.py `list_orders` / `update_order` only require a
    // signed-in agent. A refusal the server does send is said in the toast.
    val vm: OrdersViewModel = viewModel { OrdersViewModel(dash) }
    ke.co.bethanyhouse.neema.feature.reports.TrackShown(vm.life)
    val orders by dash.orders.collectAsStateWithLifecycle()
    val filter by vm.filter.collectAsStateWithLifecycle()
    val search by vm.search.collectAsStateWithLifecycle()
    val pageRaw by vm.page.collectAsStateWithLifecycle()
    val selectedId by vm.selectedId.collectAsStateWithLifecycle()
    val updating by vm.updating.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val initialLoading by vm.initialLoading.collectAsStateWithLifecycle()
    val loadError by vm.loadError.collectAsStateWithLifecycle()
    val unknown = orders.isEmpty() && (initialLoading || loadError != null)
    val c = Neema.colors

    // Derived once per change of the list / filter / search, never per frame:
    // a thousand orders are one pass each, not one per status card per recomposition.
    val filtered = remember(orders, filter, search) { filterOrders(orders, filter, search) }
    val totalPages = maxOf(1, (filtered.size + PAGE_SIZE - 1) / PAGE_SIZE)
    val page = pageRaw.coerceIn(1, totalPages)
    val paginated = remember(filtered, page) { pageOf(filtered, page, PAGE_SIZE) }

    val stats = remember(orders) { orderStats(orders) }
    val statusCounts = stats.counts
    val totalRevenue = stats.revenue

    BoxWithConstraints(Modifier.fillMaxSize().background(c.bg)) {
        val wide = maxWidth >= 600.dp
        // A wide tablet shows the order beside the list instead of in a sheet over it.
        val twoPane = maxWidth >= 1000.dp
        // Phones (and big text): the row's amount moves up beside the name.
        val compactRows = textRoom(if (twoPane) maxWidth - PANE_WIDTH else maxWidth) < 480.dp
        val cols = statusColumns(maxWidth, if (wide) 24.dp else 16.dp, LocalDensity.current.fontScale)
        val selected = remember(orders, selectedId) { selectedId?.let { id -> orders.find { it.id == id } } }
        Row(Modifier.fillMaxSize()) {
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.weight(1f).fillMaxHeight()) {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(if (wide) 24.dp else 16.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {
                // ── Header ─────────────────────────────────────────────────
                item(key = "header", contentType = "header") {
                    SideOrStacked(
                        Modifier.fillMaxWidth().padding(bottom = 24.dp),
                        start = {
                            Column {
                                Text("Orders", fontSize = 20.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp, color = c.text)
                                val pending = statusCounts["pending"] ?: 0
                                // One run of text: "· 12 pending" wraps as a phrase, never letter by letter.
                                Text(
                                    buildAnnotatedString {
                                        // Never loaded: no counts — "0 total" would be a claim.
                                        append(if (unknown) (if (loadError != null) "Not loaded" else "Loading…") else "${orders.size} total")
                                        if (pending > 0) {
                                            withStyle(SpanStyle(color = c.amber, fontWeight = FontWeight.Medium)) {
                                                append("  · $pending pending")
                                            }
                                        }
                                    },
                                    fontSize = 14.sp, color = c.textDim, style = Tabular, modifier = Modifier.padding(top = 2.dp),
                                )
                            }
                        },
                        end = { stacked -> RevenueCard(if (unknown) "—" else money(totalRevenue), stacked) },
                    )
                }

                // ── Status summary cards (tap = filter) ────────────────────
                item(key = "cards", contentType = "cards") {
                    // 14dp + the search field's 6dp touch margin = the web's mb-5.
                    Column(Modifier.padding(bottom = 14.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        ORDER_STATUSES.chunked(cols).forEach { rowStatuses ->
                            Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                rowStatuses.forEach { s ->
                                    val meta = statusMeta(s)
                                    val rev = stats.revenueBy[s] ?: 0.0
                                    StatusCard(
                                        meta = meta, count = statusCounts[s] ?: 0, revenue = rev, known = !unknown,
                                        active = filter == s, onClick = { vm.toggleFilter(s) },
                                        modifier = Modifier.weight(1f).fillMaxHeight(),
                                    )
                                }
                            }
                        }
                    }
                }

                // ── Search + active filter ─────────────────────────────────
                item(key = "search", contentType = "search") {
                    // 10dp + the field's 6dp touch margin = the web's mb-4.
                    Row(Modifier.fillMaxWidth().padding(bottom = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        CompactSearchField(search, vm::setSearch, placeholder = "Search by name or phone…", modifier = Modifier.weight(1f))
                        if (filter != "all") {
                            Spacer(Modifier.width(8.dp))
                            val press = remember { MutableInteractionSource() }
                            Box(
                                Modifier.touchCell(press, onClickLabel = "Clear the status filter") { vm.setFilter("all") }
                                    .heightIn(min = 36.dp).clip(RoundedCornerShape(12.dp)).background(c.gold2).pressedOn(press).padding(horizontal = 12.dp),
                                contentAlignment = Alignment.Center,
                            ) {
                                Text("${STATUS_META[filter]?.label ?: filter} ✕", fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                                    color = if (c.isDark) c.bg else Color.White)
                            }
                        }
                    }
                }

                // ── The list ───────────────────────────────────────────────
                val err = loadError
                if (err != null && orders.isNotEmpty()) {
                    item(key = "stale") { StaleBanner(err, onRetry = vm::refresh, modifier = Modifier.padding(bottom = 12.dp)) }
                }
                if (initialLoading && orders.isEmpty()) {
                    item(key = "loading") { Box(Modifier.fillMaxWidth().height(200.dp)) { Loading() } }
                } else if (err != null && orders.isEmpty()) {
                    // Nothing was ever read: "No orders found" would be a lie.
                    item(key = "error") { ke.co.bethanyhouse.neema.core.ui.components.ErrorState(err, onRetry = vm::retry) }
                } else if (filtered.isEmpty()) {
                    item(key = "empty") {
                        Column(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.bg2)
                                .border(1.dp, c.bg4, RoundedCornerShape(12.dp)).padding(vertical = 64.dp),
                            horizontalAlignment = Alignment.CenterHorizontally,
                        ) {
                            Text("📦", fontSize = 30.sp)
                            Spacer(Modifier.height(12.dp))
                            Text("No orders found", fontSize = 14.sp, color = c.textDim)
                        }
                    }
                } else {
                    items(paginated, key = { it.id }, contentType = { "order" }) { order ->
                        val first = order.id == paginated.first().id
                        val last = order.id == paginated.last().id
                        // One bordered card around the whole list, drawn a slice per row
                        // so it stays whole as the rows scroll.
                        Column(Modifier.fillMaxWidth().listSegment(first, last, border = c.bg4, fill = c.bg2)) {
                            OrderRow(
                                dash, order, isUpdating = updating == order.id, compact = compactRows,
                                highlighted = twoPane && selected?.id == order.id,
                                onClick = { vm.select(order) },
                            )
                            if (!last) HorizontalDivider(color = if (c.isDark) c.bg3 else Palette.Moss50)
                        }
                    }
                }

                // ── Pagination ─────────────────────────────────────────────
                if (totalPages > 1) {
                    item(key = "pager") {
                        Pager(page, totalPages, filtered.size, onPage = vm::setPage)
                    }
                }
                item(key = "bottom-space") { Spacer(Modifier.height(24.dp)) }
            }
        }
        // ── Order detail, beside the list on a wide tablet ─────────────────
        if (twoPane && selected != null) {
            val shape = RoundedCornerShape(16.dp)
            Box(
                Modifier.width(PANE_WIDTH).fillMaxHeight().padding(top = 24.dp, bottom = 24.dp, end = 24.dp)
                    .clip(shape).background(c.bg2).border(1.dp, c.bg4, shape),
            ) {
                Column(Modifier.padding(top = 16.dp)) {
                    OrderDetail(
                        dash = dash, order = selected,
                        busy = updating == selected.id,
                        onStatus = { next -> vm.updateStatus(selected.id, next) },
                        onClose = { vm.select(null) },
                    )
                }
            }
        }
        }

    // ── Order detail ───────────────────────────────────────────────────────
    if (selectedId != null && selected == null) {
        // The row vanished under a refetch — nothing left to show.
        LaunchedEffect(selectedId) { vm.select(null) }
    }
    if (selected != null && !twoPane) {
        ModalBottomSheet(
            onDismissRequest = { vm.select(null) },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = c.bg2,
            dragHandle = { WebDragHandle() },
        ) {
            OrderDetail(
                dash = dash, order = selected,
                busy = updating == selected.id,
                onStatus = { next -> vm.updateStatus(selected.id, next) },
                onClose = { vm.select(null) },
            )
        }
    }
    }
}

/** How wide the order pane is beside the list on a wide tablet. */
private val PANE_WIDTH = 440.dp

/**
 * The header's revenue pill (`rounded-xl px-4 py-2.5 text-right`). Stacked
 * under the title on a narrow screen it spans the width: label left, figure right.
 */
@Composable
private fun RevenueCard(amount: String, stacked: Boolean) {
    val c = Neema.colors
    val shape = RoundedCornerShape(12.dp)
    val box = Modifier.clip(shape).background(c.bg2).border(1.dp, c.bg4, shape).padding(horizontal = 16.dp, vertical = 10.dp)
    val label: @Composable (Modifier) -> Unit = { m ->
        Text("Total Revenue", fontSize = 12.sp, fontWeight = FontWeight.Medium, color = c.textDim, modifier = m)
    }
    val figure: @Composable () -> Unit = {
        Text(amount.unbroken(), fontSize = 16.sp, fontWeight = FontWeight.Bold, color = c.gold2, style = Tabular, textAlign = TextAlign.End)
    }
    if (stacked) {
        Row(box.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            label(Modifier.weight(1f).padding(end = 12.dp))
            figure()
        }
    } else {
        Column(box, horizontalAlignment = Alignment.End) {
            label(Modifier.padding(bottom = 2.dp))
            figure()
        }
    }
}

@Composable
private fun StatusCard(meta: StatusMeta, count: Int, revenue: Double, active: Boolean, known: Boolean = true, onClick: () -> Unit, modifier: Modifier) {
    val c = Neema.colors
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier.clip(shape).background(c.bg2)
            .border(if (active) 2.dp else 1.dp, if (active) toneBorder(meta.tone) else c.bg3, shape)
            .clickable(onClick = onClick)
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(meta.tone.dot))
            Spacer(Modifier.width(6.dp))
            Text(meta.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = toneText(meta.tone))
        }
        Spacer(Modifier.height(8.dp))
        Text(if (known) count.toString() else "—", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = c.text, style = Tabular)
        if (revenue > 0) Text(money(revenue).unbroken(), fontSize = 12.sp, color = c.textDim, style = Tabular, modifier = Modifier.padding(top = 2.dp))
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun OrderRow(
    dash: DashboardViewModel,
    order: Order,
    isUpdating: Boolean,
    onClick: () -> Unit,
    /** A phone (or big text): the amount sits beside the name so the name keeps its room. */
    compact: Boolean = false,
    /** The order open in the tablet's side pane. */
    highlighted: Boolean = false,
) {
    val c = Neema.colors
    val uri = LocalUriHandler.current
    // The HUB is the authority once an order is pushed there; `status` is our
    // own triage flag, and showing it for a linked order is how a confirmed
    // sale kept reading "Pending".
    val meta = hubMeta(order) ?: statusMeta(order.status)
    val hubHref = hubOrderHref(order)
    val name = Fmt.displayName(order.contactName, order.waId)
    val itemSummary = remember(order.items) {
        order.items.take(2).joinToString(", ") { i -> i.name + if (i.effectiveQty > 1) " ×${qtyText(i.effectiveQty)}" else "" }
    }
    val extraItems = order.items.size - 2

    val hubNumber: @Composable (Modifier) -> Unit = { m ->
        // The REAL hub order number — never a slice of a timestamp.
        Text(
            order.hubOrderNumber?.takeIf { it.isNotBlank() } ?: "not in hub",
            modifier = m.clip(RoundedCornerShape(4.dp)).background(c.bg3).padding(horizontal = 4.dp, vertical = 2.dp),
            fontSize = 10.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, color = c.gold2,
        )
    }
    val hubLink: @Composable (Modifier) -> Unit = { m ->
        if (hubHref != null) {
            Text(
                "Open in hub ↗",
                modifier = m.clip(RoundedCornerShape(4.dp))
                    .border(1.dp, if (c.isDark) c.border else SalesInk.HubLinkBorder, RoundedCornerShape(4.dp))
                    .clickable { runCatching { uri.openUri(hubHref) } }
                    .padding(horizontal = 6.dp, vertical = 2.dp),
                fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = c.gold2,
            )
        }
    }
    val pushFailed: @Composable (Modifier) -> Unit = { m ->
        if (order.hubPushStatus == "failed") {
            // The web shows the error as a tooltip; a tap reads it out here.
            Badge(
                "push failed", Tones.Red,
                m.clickable {
                    dash.toast(order.hubLastError?.takeIf { it.isNotBlank() } ?: "The push to the hub failed", ToastType.Error)
                },
            )
        }
    }
    val summary: @Composable (Modifier) -> Unit = { m ->
        if (itemSummary.isNotEmpty()) {
            // The separator travels with the summary, so a wrap never leaves it dangling.
            Text(
                buildAnnotatedString {
                    withStyle(SpanStyle(color = if (c.isDark) c.border else Palette.Stone200)) { append("·  ") }
                    append(itemSummary + if (extraItems > 0) " +$extraItems more" else "")
                },
                fontSize = 12.sp, color = if (c.isDark) c.textMid else Palette.Stone500, maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = m,
            )
        }
    }
    val amount: @Composable () -> Unit = {
        Text(money(order.amount, order.currency).unbroken(), fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text,
            style = Tabular, maxLines = 1, textAlign = TextAlign.End)
    }
    val spinner: @Composable (Modifier) -> Unit = { m ->
        if (isUpdating) CircularProgressIndicator(m.size(16.dp), strokeWidth = 2.dp, color = c.gold2)
    }

    Row(
        Modifier.fillMaxWidth()
            .background(if (highlighted) (if (c.isDark) c.bg3 else SalesInk.PaneHighlight) else Color.Transparent)
            .clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = if (compact) Alignment.Top else Alignment.CenterVertically,
    ) {
        Avatar(name, size = 38.dp)
        Spacer(Modifier.width(12.dp))
        if (compact) {
            Column(Modifier.weight(1f)) {
                // Row 1: name … amount, the figure right-aligned. When both can't
                // fit whole, the amount takes its own line — a phone number is
                // never cut to "+254 711 2…" to make room for it.
                SideOrStacked(
                    gap = 2.dp,
                    start = {
                        Text(name.unbroken(), fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text, maxLines = 1,
                            overflow = TextOverflow.Ellipsis)
                    },
                    end = { stacked ->
                        Row(
                            if (stacked) Modifier.fillMaxWidth() else Modifier.padding(start = 8.dp),
                            horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically,
                        ) {
                            spinner(Modifier.padding(end = 6.dp))
                            amount()
                        }
                    },
                )
                // Row 2: channel, status, hub number, hub link, push failure.
                FlowRow(
                    Modifier.padding(top = 4.dp),
                    horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    if (order.channel.isNotBlank()) Box(Modifier.align(Alignment.CenterVertically)) { OrderChannelPill(order.channel) }
                    Badge(meta.label, meta.tone, Modifier.align(Alignment.CenterVertically))
                    hubNumber(Modifier.align(Alignment.CenterVertically))
                    hubLink(Modifier.align(Alignment.CenterVertically))
                    pushFailed(Modifier.align(Alignment.CenterVertically))
                }
                // Row 3: phone and the items, one line.
                val phone = phoneLine(order, name)
                if (phone != null || itemSummary.isNotEmpty()) {
                    Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                        phone?.let {
                            Text(it.unbroken(), fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = c.textDim, maxLines = 1)
                            Spacer(Modifier.width(6.dp))
                        }
                        summary(Modifier.weight(1f, fill = false))
                    }
                }
                // Row 4: time
                Text(Fmt.timeAgo(order.createdAt), fontSize = 10.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp))
            }
        } else {
            Column(Modifier.weight(1f)) {
                // Row 1: name + channel + status
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    Text(name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text, maxLines = 1,
                        overflow = TextOverflow.Ellipsis, modifier = Modifier.align(Alignment.CenterVertically))
                    if (order.channel.isNotBlank()) Box(Modifier.align(Alignment.CenterVertically)) { OrderChannelPill(order.channel) }
                    Badge(meta.label, meta.tone, Modifier.align(Alignment.CenterVertically))
                }
                Spacer(Modifier.height(3.dp))
                // Row 2: hub order number, hub link, push failure, phone, items
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                    hubNumber(Modifier.align(Alignment.CenterVertically))
                    hubLink(Modifier.align(Alignment.CenterVertically))
                    pushFailed(Modifier.align(Alignment.CenterVertically))
                    phoneLine(order, name)?.let { phone ->
                        Text(phone, fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = c.textDim,
                            modifier = Modifier.align(Alignment.CenterVertically))
                    }
                    summary(Modifier.widthIn(max = 232.dp).align(Alignment.CenterVertically))
                }
                // Row 3: time
                Text(Fmt.timeAgo(order.createdAt), fontSize = 10.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp))
            }
            Spacer(Modifier.width(12.dp))
            Column(horizontalAlignment = Alignment.End) {
                amount()
                Text(order.currency.ifBlank { "KES" }, fontSize = 10.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp))
                spinner(Modifier.padding(top = 4.dp))
            }
        }
    }
}

/**
 * Numbered pages, a window of at most five around the current one. Each
 * button is a 32dp square in a 48dp touch cell; where the row can't also hold
 * the "Showing" line (a phone), the buttons get their own centred row.
 */
@Composable
internal fun Pager(page: Int, totalPages: Int, total: Int, onPage: (Int) -> Unit) {
    val c = Neema.colors
    BoxWithConstraints(Modifier.fillMaxWidth().padding(top = 16.dp, start = 4.dp, end = 4.dp)) {
        val window = pageWindow(page, totalPages)
        val count = window.size + 2
        val inline = maxWidth >= 48.dp * count + 180.dp * LocalDensity.current.fontScale
        val cell = minOf(48.dp, maxWidth / count)
        val showing: @Composable (Modifier) -> Unit = { m ->
            Text(
                "Showing ${(page - 1) * PAGE_SIZE + 1}–${minOf(page * PAGE_SIZE, total)} of $total",
                fontSize = 12.sp, color = c.textDim, style = Tabular, modifier = m,
            )
        }
        val buttons: @Composable () -> Unit = {
            Row {
                PageButton("‹", "Previous page", cell, selected = false, enabled = page > 1) { onPage(maxOf(1, page - 1)) }
                for (pg in window) {
                    PageButton(pg.toString(), "Page $pg", cell, selected = page == pg, enabled = true) { onPage(pg) }
                }
                PageButton("›", "Next page", cell, selected = false, enabled = page < totalPages) { onPage(minOf(totalPages, page + 1)) }
            }
        }
        if (inline) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                showing(Modifier.weight(1f))
                buttons()
            }
        } else {
            Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.fillMaxWidth()) {
                showing(Modifier.padding(bottom = 4.dp))
                buttons()
            }
        }
    }
}

@Composable
private fun PageButton(label: String, description: String, cell: Dp, selected: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val c = Neema.colors
    val shape = RoundedCornerShape(8.dp)
    // disabled:opacity-30 fades the whole button, border and fill included.
    Box(
        Modifier.size(cell).clip(RoundedCornerShape(12.dp))
            .clickable(enabled = enabled, onClick = onClick)
            .semantics { contentDescription = description; if (selected) this.selected = true },
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier.size(32.dp).alpha(if (enabled) 1f else 0.3f).clip(shape)
                .background(if (selected) c.gold else c.bg2)
                .border(1.dp, if (selected) c.gold else c.border, shape),
            contentAlignment = Alignment.Center,
        ) {
            Text(label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = if (selected) Color.White else c.gold2,
                style = Tabular, maxLines = 1)
        }
    }
}

// ── Detail sheet ────────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun OrderDetail(
    dash: DashboardViewModel,
    order: Order,
    busy: Boolean,
    onStatus: (String) -> Unit,
    onClose: () -> Unit = {},
) {
    val c = Neema.colors
    val uri = LocalUriHandler.current
    val clipboard = LocalClipboardManager.current
    val meta = statusMeta(order.status)
    val actions = STATUS_ACTIONS[order.status] ?: emptyList()
    val name = Fmt.displayName(order.contactName, order.waId)
    val hubHref = hubOrderHref(order)
    val hub = hubMeta(order)
    val soft = RoundedCornerShape(12.dp)

    // The web Modal: a title bar (text-base semibold, a ✕ on the right, a
    // hairline under it), then the body with px-5 pt-4 pb-6.
    Column(Modifier.fillMaxWidth().verticalScrollable()) {
        ModalTitleBar("Order — $name", onClose)
    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(top = 16.dp, bottom = 24.dp)) {

        // Customer
        Row(
            Modifier.fillMaxWidth().clip(soft).background(c.bg).border(1.dp, c.bg3, soft).padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Avatar(name, size = 40.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                // The badge sits at the right while the name fits beside it, else under it —
                // a phone number never splits across lines to make room.
                FlowRow(
                    Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween, verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        if (order.contactName.isNullOrBlank()) name.unbroken() else name,
                        fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text,
                        modifier = Modifier.align(Alignment.CenterVertically).padding(end = 8.dp),
                    )
                    Badge(meta.label, meta.tone, Modifier.align(Alignment.CenterVertically), fontSize = 12, radius = 8.dp, hPad = 8.dp, vPad = 4.dp)
                }
                phoneLine(order, name)?.let { Text(it.unbroken(), fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = c.textDim) }
            }
        }
        Spacer(Modifier.height(16.dp))

        // Meta grid
        val cells = listOf(
            "Order ID" to order.id.takeLast(8).uppercase(),
            "Date" to Fmt.date(order.createdAt),
            "Channel" to channelStyle(order.channel.ifBlank { null }).label,
            "Currency" to order.currency.ifBlank { "KES" },
        )
        cells.chunked(2).forEach { pair ->
            Row(Modifier.padding(bottom = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                pair.forEach { (label, value) -> MetaCell(label, value, Modifier.weight(1f)) }
            }
        }
        Spacer(Modifier.height(8.dp))

        // Hub linkage
        SectionLabel("Hub")
        Column(
            Modifier.fillMaxWidth().clip(soft).background(c.bg).border(1.dp, c.bg3, soft).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    order.hubOrderNumber?.takeIf { it.isNotBlank() } ?: "not in hub",
                    modifier = Modifier.align(Alignment.CenterVertically).clip(RoundedCornerShape(4.dp))
                        .background(c.bg3).padding(horizontal = 6.dp, vertical = 2.dp),
                    fontSize = 12.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, color = c.gold2,
                )
                if (hub != null) Badge(hub.label, hub.tone, Modifier.align(Alignment.CenterVertically))
                order.hubPaymentStatus?.takeIf { it.isNotBlank() }?.let {
                    Text("Payment: ${it.replaceFirstChar { ch -> ch.uppercase() }}", fontSize = 12.sp, color = c.textMid,
                        modifier = Modifier.align(Alignment.CenterVertically))
                }
                order.hubPushStatus?.takeIf { it.isNotBlank() && it != "failed" }?.let {
                    Text("Push: $it", fontSize = 12.sp, color = c.textDim, modifier = Modifier.align(Alignment.CenterVertically))
                }
            }
            if (order.hubPushStatus == "failed") {
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(toneBg(Tones.Red))
                        .border(1.dp, toneBorder(Tones.Red), RoundedCornerShape(8.dp)).padding(8.dp),
                ) {
                    Text("PUSH FAILED", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = toneText(Tones.Red))
                    Text(order.hubLastError?.takeIf { it.isNotBlank() } ?: "The push to the hub failed",
                        fontSize = 12.sp, color = toneText(Tones.Red))
                }
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (hubHref != null) {
                    OutlinedButton(onClick = { runCatching { uri.openUri(hubHref) } }) { Text("Open in hub ↗", fontSize = 12.sp) }
                }
                val publicUrl = order.hubPublicUrl?.takeIf { it.isNotBlank() }
                if (publicUrl != null) {
                    OutlinedButton(onClick = { runCatching { uri.openUri(publicUrl) } }) { Text("Customer's order page ↗", fontSize = 12.sp) }
                    TextButton(onClick = {
                        clipboard.setText(AnnotatedString(publicUrl))
                        dash.toast("Order link copied")
                    }) { Text("Copy link", fontSize = 12.sp) }
                }
            }
        }
        Spacer(Modifier.height(16.dp))

        // Items
        SectionLabel("Items")
        Column(
            Modifier.fillMaxWidth().clip(soft).background(c.bg).border(1.dp, c.bg3, soft).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            if (order.items.isEmpty()) {
                Text("No items recorded", fontSize = 12.sp, color = c.muted, textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 8.dp))
            } else {
                order.items.forEach { item ->
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                        // The SKU follows the name, or drops under it when the line is full.
                        FlowRow(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            Text(item.name, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = c.text)
                            if (!item.sku.isNullOrBlank()) {
                                Text(item.sku, fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = c.textDim,
                                    modifier = Modifier.align(Alignment.CenterVertically))
                            }
                        }
                        Spacer(Modifier.width(8.dp))
                        Column(horizontalAlignment = Alignment.End) {
                            // A line whose price this build can't read shows its
                            // quantity alone, never a made-up "KES 0".
                            if (item.priceKnown) {
                                Text(money(item.lineTotal, order.currency).unbroken(), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text, style = Tabular)
                                Text("${money(item.effectiveUnit, order.currency).unbroken()} × ${qtyText(item.effectiveQty)}", fontSize = 10.sp, color = c.textDim, style = Tabular)
                            } else {
                                Text("× ${qtyText(item.effectiveQty)}", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text, style = Tabular)
                            }
                        }
                    }
                }
            }
            // pt-2.5 mt-2 over a #cee6b2 rule
            HorizontalDivider(color = c.bg4)
            Row(Modifier.fillMaxWidth().padding(top = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Total", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text, modifier = Modifier.weight(1f))
                Text(money(order.amount, order.currency).unbroken(), fontSize = 16.sp, fontWeight = FontWeight.Bold, color = c.gold2, style = Tabular)
            }
        }
        Spacer(Modifier.height(16.dp))

        // Note (the reply Neema sent with the order): amber-600 label, amber-800 text.
        if (!order.replyText.isNullOrBlank()) {
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(toneBg(Tones.Amber))
                    .border(1.dp, toneBorder(Tones.Amber), RoundedCornerShape(8.dp)).padding(10.dp),
            ) {
                Text("📝 NOTE", fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.25.sp,
                    color = if (c.isDark) Tones.Amber.dot else Palette.Amber600)
                Spacer(Modifier.height(4.dp))
                Text(order.replyText, fontSize = 12.sp, color = if (c.isDark) Palette.Amber200 else Palette.Amber800)
            }
            Spacer(Modifier.height(16.dp))
        }

        // Customer thread shortcut
        OutlinedButton(onClick = { dash.openConversationFor(order.waId) }, modifier = Modifier.fillMaxWidth()) {
            Text("Open conversation")
        }
        Spacer(Modifier.height(10.dp))

        // Status moves
        // Shown to every agent, as OrdersView does (it has no manage_orders check).
        if (actions.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                actions.forEach { next ->
                    WebBtn(
                        "Mark as ${statusMeta(next).label}",
                        variant = if (next == "cancelled") BtnVariant.Danger else BtnVariant.Primary,
                        enabled = !busy, busy = busy, onClick = { onStatus(next) },
                    )
                }
            }
        }
    }
    }
}

/** The web Modal's header: `text-base font-semibold` title, a ✕ button, a hairline beneath. */
@Composable
internal fun ModalTitleBar(title: String, onClose: () -> Unit) {
    val c = Neema.colors
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 4.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = c.text, modifier = Modifier.weight(1f).padding(vertical = 8.dp))
        // A 16dp ✕ in a 48dp touch target.
        Box(
            Modifier.size(48.dp).clip(CircleShape).clickable(onClick = onClose),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.Close, contentDescription = "Close", tint = if (c.isDark) c.muted else Palette.Gray400, modifier = Modifier.size(16.dp))
        }
    }
    HorizontalDivider(color = if (c.isDark) c.hairline else Palette.Gray100)
}

/** components/ui/Btn variants the order and lead views use. */
enum class BtnVariant { Primary, Danger, Outline }

/**
 * The web `Btn` at its default `md` size: h-9, px-4, text-sm medium,
 * rounded-lg; primary amber-500, danger red-50 / red-600 / red-200, outline
 * gray-300 / gray-700. Disabled fades the whole button to 40%.
 */
@Composable
fun WebBtn(
    label: String,
    variant: BtnVariant,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    busy: Boolean = false,
    onClick: () -> Unit,
) {
    val dark = Neema.colors.isDark
    val (bg, fg, border) = when (variant) {
        BtnVariant.Primary -> Triple(Palette.Amber500, Color.White, Palette.Amber500)
        BtnVariant.Danger -> if (dark) Triple(SalesInk.Red950.copy(alpha = 0.3f), Palette.Red400, Palette.Red800)
            else Triple(Palette.Red50, Palette.Red600, Palette.Red200)
        BtnVariant.Outline -> if (dark) Triple(Color.Transparent, Palette.Gray200, Palette.Gray600)
            else Triple(Color.Transparent, Palette.Gray700, Palette.Gray300)
    }
    val shape = RoundedCornerShape(8.dp)
    val press = remember { MutableInteractionSource() }
    Row(
        // 36dp to the eye (the web's h-9), 48dp to the finger.
        modifier.touchCell(press, enabled = enabled, role = Role.Button, onClick = onClick)
            .heightIn(min = 36.dp).alpha(if (enabled) 1f else 0.4f).clip(shape).background(bg).border(1.dp, border, shape)
            .pressedOn(press).padding(horizontal = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        if (busy) {
            CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp, color = fg)
            Spacer(Modifier.width(6.dp))
        }
        Text(label, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = fg, maxLines = 1)
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp,
        color = Neema.colors.textDim, modifier = Modifier.padding(bottom = 8.dp),
    )
}

@Composable
private fun MetaCell(label: String, value: String, modifier: Modifier) {
    val c = Neema.colors
    Column(
        modifier.clip(RoundedCornerShape(8.dp)).background(c.bg).border(BorderStroke(1.dp, c.bg3), RoundedCornerShape(8.dp))
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) {
        Text(label.uppercase(), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.25.sp, color = c.textDim)
        Text(value, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text, modifier = Modifier.padding(top = 2.dp))
    }
}

/** The web Modal's mobile drag handle: a 40×4 gray-200 bar, 12dp from the top, 16dp above the title. */
@Composable
internal fun WebDragHandle() {
    Box(
        Modifier.padding(top = 12.dp, bottom = 16.dp).size(width = 40.dp, height = 4.dp).clip(RoundedCornerShape(50))
            .background(if (Neema.colors.isDark) Palette.Gray700 else Palette.Gray200),
    )
}

/**
 * One slice of a bordered, rounded card that a lazy list draws row by row:
 * the first slice carries the rounded top, the last the rounded bottom, and
 * every slice its share of the left and right edges — so the web's single
 * `rounded-xl border` box around the list survives scrolling.
 */
internal fun Modifier.listSegment(first: Boolean, last: Boolean, border: Color, fill: Color, radius: Dp = 12.dp): Modifier {
    val shape = RoundedCornerShape(
        topStart = if (first) radius else 0.dp, topEnd = if (first) radius else 0.dp,
        bottomStart = if (last) radius else 0.dp, bottomEnd = if (last) radius else 0.dp,
    )
    return this.clip(shape).background(fill).drawWithContent {
        drawContent()
        val stroke = 1.dp.toPx()
        val r = radius.toPx()
        // Past a slice's open ends the rounded rect runs out of bounds, so only straight edges show.
        val top = if (first) 0f else -2 * r
        val bottom = if (last) size.height else size.height + 2 * r
        drawRoundRect(
            color = border,
            topLeft = Offset(stroke / 2, top + stroke / 2),
            size = Size(size.width - stroke, bottom - top - stroke),
            cornerRadius = CornerRadius(r - stroke / 2),
            style = Stroke(stroke),
        )
    }
}

@Composable
private fun Modifier.verticalScrollable(): Modifier =
    this.verticalScroll(rememberScrollState())
