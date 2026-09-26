package ke.co.bethanyhouse.neema.feature.orders

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
import androidx.compose.material.icons.outlined.Lock
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
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.EmptyState
import ke.co.bethanyhouse.neema.core.ui.components.Loading
import ke.co.bethanyhouse.neema.core.ui.components.channelStyle
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
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
    // Permissions come from /me; observing it recomposes the gate once it lands.
    dash.me.collectAsStateWithLifecycle().value
    if (!dash.can(Perms.VIEW_ORDERS)) {
        EmptyState(
            title = "No access to orders",
            subtitle = "Your role doesn't include viewing orders. Ask an admin if you need it.",
            icon = Icons.Outlined.Lock,
        )
        return
    }

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
    val canManage = dash.can(Perms.MANAGE_ORDERS)
    val unknown = orders.isEmpty() && (initialLoading || loadError != null)
    val c = Neema.colors

    val filtered = remember(orders, filter, search) { filterOrders(orders, filter, search) }
    val totalPages = maxOf(1, (filtered.size + PAGE_SIZE - 1) / PAGE_SIZE)
    val page = pageRaw.coerceIn(1, totalPages)
    val paginated = filtered.drop((page - 1) * PAGE_SIZE).take(PAGE_SIZE)

    val statusCounts = remember(orders) { ORDER_STATUSES.associateWith { s -> orders.count { it.status == s } } }
    val totalRevenue = remember(orders) { orders.filter { it.status != "cancelled" }.sumOf { it.amount } }

    BoxWithConstraints(Modifier.fillMaxSize().background(c.bg)) {
        val wide = maxWidth >= 600.dp
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            LazyColumn(
                Modifier.fillMaxSize(),
                contentPadding = PaddingValues(if (wide) 24.dp else 16.dp),
                verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {
                // ── Header ─────────────────────────────────────────────────
                item(key = "header") {
                    Row(Modifier.fillMaxWidth().padding(bottom = 24.dp), verticalAlignment = Alignment.Top) {
                        Column(Modifier.weight(1f)) {
                            Text("Orders", fontSize = 20.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp, color = c.text)
                            Row(Modifier.padding(top = 2.dp)) {
                                // Never loaded: no counts — "0 total" would be a claim.
                                Text(if (unknown) (if (loadError != null) "Not loaded" else "Loading…") else "${orders.size} total", fontSize = 14.sp, color = c.textDim)
                                val pending = statusCounts["pending"] ?: 0
                                if (pending > 0) {
                                    Text("· $pending pending", fontSize = 14.sp, fontWeight = FontWeight.Medium, color = c.amber,
                                        modifier = Modifier.padding(start = 6.dp))
                                }
                            }
                        }
                        Column(
                            Modifier.clip(RoundedCornerShape(12.dp)).background(c.bg2)
                                .border(1.dp, c.bg4, RoundedCornerShape(12.dp))
                                .padding(horizontal = 16.dp, vertical = 10.dp),
                            horizontalAlignment = Alignment.End,
                        ) {
                            Text("Total Revenue", fontSize = 12.sp, fontWeight = FontWeight.Medium, color = c.textDim, modifier = Modifier.padding(bottom = 2.dp))
                            Text(if (unknown) "—" else money(totalRevenue), fontSize = 16.sp, fontWeight = FontWeight.Bold, color = c.gold2)
                        }
                    }
                }

                // ── Status summary cards (tap = filter) ────────────────────
                item(key = "cards") {
                    val cols = if (wide) 4 else 2
                    Column(Modifier.padding(bottom = 20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        ORDER_STATUSES.chunked(cols).forEach { rowStatuses ->
                            Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                rowStatuses.forEach { s ->
                                    val meta = statusMeta(s)
                                    val rev = orders.filter { it.status == s }.sumOf { it.amount }
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
                item(key = "search") {
                    Row(Modifier.fillMaxWidth().padding(bottom = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                        CompactSearchField(search, vm::setSearch, placeholder = "Search by name or phone…", modifier = Modifier.weight(1f))
                        if (filter != "all") {
                            Spacer(Modifier.width(8.dp))
                            Box(
                                Modifier.height(36.dp).clip(RoundedCornerShape(12.dp)).background(c.gold2)
                                    .clickable { vm.setFilter("all") }.padding(horizontal = 12.dp),
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
                    items(paginated, key = { it.id }) { order ->
                        val first = order.id == paginated.first().id
                        val last = order.id == paginated.last().id
                        // One bordered card around the whole list, drawn a slice per row
                        // so it stays whole as the rows scroll.
                        Column(Modifier.fillMaxWidth().listSegment(first, last, border = c.bg4, fill = c.bg2)) {
                            OrderRow(dash, order, isUpdating = updating == order.id, onClick = { vm.select(order) })
                            if (!last) HorizontalDivider(color = if (c.isDark) c.bg3 else Color(0xFFF0F9EC))
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
    }

    // ── Order detail ───────────────────────────────────────────────────────
    val selected = selectedId?.let { id -> orders.find { it.id == id } }
    if (selectedId != null && selected == null) {
        // The row vanished under a refetch — nothing left to show.
        LaunchedEffect(selectedId) { vm.select(null) }
    }
    if (selected != null) {
        ModalBottomSheet(
            onDismissRequest = { vm.select(null) },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = c.bg2,
            dragHandle = { WebDragHandle() },
        ) {
            OrderDetail(
                dash = dash, order = selected, canManage = canManage,
                busy = updating == selected.id,
                onStatus = { next -> vm.updateStatus(selected.id, next) },
                onClose = { vm.select(null) },
            )
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
        Text(if (known) count.toString() else "—", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = c.text)
        if (revenue > 0) Text(money(revenue), fontSize = 12.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp))
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun OrderRow(dash: DashboardViewModel, order: Order, isUpdating: Boolean, onClick: () -> Unit) {
    val c = Neema.colors
    val uri = LocalUriHandler.current
    // The HUB is the authority once an order is pushed there; `status` is our
    // own triage flag, and showing it for a linked order is how a confirmed
    // sale kept reading "Pending".
    val meta = hubMeta(order) ?: statusMeta(order.status)
    val hubHref = hubOrderHref(order)
    val name = Fmt.displayName(order.contactName, order.waId)
    val itemSummary = order.items.take(2).joinToString(", ") { i ->
        i.name + if (i.effectiveQty > 1) " ×${qtyText(i.effectiveQty)}" else ""
    }
    val extraItems = order.items.size - 2

    Row(
        Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Avatar(name, size = 38.dp)
        Spacer(Modifier.width(12.dp))
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
                // The REAL hub order number — never a slice of a timestamp.
                Text(
                    order.hubOrderNumber?.takeIf { it.isNotBlank() } ?: "not in hub",
                    modifier = Modifier.align(Alignment.CenterVertically).clip(RoundedCornerShape(4.dp))
                        .background(c.bg3).padding(horizontal = 4.dp, vertical = 2.dp),
                    fontSize = 10.sp, fontFamily = FontFamily.Monospace, fontWeight = FontWeight.Bold, color = c.gold2,
                )
                if (hubHref != null) {
                    Text(
                        "Open in hub ↗",
                        modifier = Modifier.align(Alignment.CenterVertically).clip(RoundedCornerShape(4.dp))
                            .border(1.dp, if (c.isDark) c.border else Color(0xFFCFE3BD), RoundedCornerShape(4.dp))
                            .clickable { runCatching { uri.openUri(hubHref) } }
                            .padding(horizontal = 6.dp, vertical = 2.dp),
                        fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = c.gold2,
                    )
                }
                if (order.hubPushStatus == "failed") {
                    // The web shows the error as a tooltip; a tap reads it out here.
                    Badge(
                        "push failed", Tones.Red,
                        Modifier.align(Alignment.CenterVertically).clickable {
                            dash.toast(order.hubLastError?.takeIf { it.isNotBlank() } ?: "The push to the hub failed", ToastType.Error)
                        },
                    )
                }
                phoneLine(order, name)?.let { phone ->
                    Text(phone, fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = c.textDim,
                        modifier = Modifier.align(Alignment.CenterVertically))
                }
                if (itemSummary.isNotEmpty()) {
                    // The separator travels with the summary, so a wrap never leaves it dangling.
                    Text(
                        buildAnnotatedString {
                            withStyle(SpanStyle(color = if (c.isDark) c.border else Color(0xFFE7E5E4))) { append("·  ") }
                            append(itemSummary + if (extraItems > 0) " +$extraItems more" else "")
                        },
                        fontSize = 12.sp, color = if (c.isDark) c.textMid else Color(0xFF78716C), maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.widthIn(max = 232.dp).align(Alignment.CenterVertically),
                    )
                }
            }
            // Row 3: time
            Text(Fmt.timeAgo(order.createdAt), fontSize = 10.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp))
        }
        Spacer(Modifier.width(12.dp))
        Column(horizontalAlignment = Alignment.End) {
            Text(money(order.amount, order.currency), fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text)
            Text(order.currency.ifBlank { "KES" }, fontSize = 10.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp))
            if (isUpdating) {
                CircularProgressIndicator(Modifier.padding(top = 4.dp).size(16.dp), strokeWidth = 2.dp, color = c.gold2)
            }
        }
    }
}

/** Numbered pages, a window of at most five around the current one. */
@Composable
internal fun Pager(page: Int, totalPages: Int, total: Int, onPage: (Int) -> Unit) {
    val c = Neema.colors
    Row(Modifier.fillMaxWidth().padding(top = 16.dp, start = 4.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(
            "Showing ${(page - 1) * PAGE_SIZE + 1}–${minOf(page * PAGE_SIZE, total)} of $total",
            fontSize = 12.sp, color = c.textDim, modifier = Modifier.weight(1f),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            PageButton("‹", selected = false, enabled = page > 1) { onPage(maxOf(1, page - 1)) }
            for (pg in pageWindow(page, totalPages)) {
                PageButton(pg.toString(), selected = page == pg, enabled = true) { onPage(pg) }
            }
            PageButton("›", selected = false, enabled = page < totalPages) { onPage(minOf(totalPages, page + 1)) }
        }
    }
}

@Composable
private fun PageButton(label: String, selected: Boolean, enabled: Boolean, onClick: () -> Unit) {
    val c = Neema.colors
    val shape = RoundedCornerShape(8.dp)
    // disabled:opacity-30 fades the whole button, border and fill included.
    Box(
        Modifier.size(28.dp).alpha(if (enabled) 1f else 0.3f).clip(shape)
            .background(if (selected) c.gold else c.bg2)
            .border(1.dp, if (selected) c.gold else c.border, shape)
            .clickable(enabled = enabled, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Text(label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = if (selected) Color.White else c.gold2)
    }
}

// ── Detail sheet ────────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun OrderDetail(
    dash: DashboardViewModel,
    order: Order,
    canManage: Boolean,
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
                Text(name, fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text)
                phoneLine(order, name)?.let { Text(it, fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = c.textDim) }
            }
            Spacer(Modifier.width(12.dp))
            Badge(meta.label, meta.tone, fontSize = 12, radius = 8.dp, hPad = 8.dp, vPad = 4.dp)
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
                        Row(Modifier.weight(1f)) {
                            Text(item.name, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = c.text, modifier = Modifier.weight(1f, fill = false))
                            if (!item.sku.isNullOrBlank()) {
                                Spacer(Modifier.width(6.dp))
                                Text(item.sku, fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = c.textDim)
                            }
                        }
                        Spacer(Modifier.width(8.dp))
                        Column(horizontalAlignment = Alignment.End) {
                            // A line whose price this build can't read shows its
                            // quantity alone, never a made-up "KES 0".
                            if (item.priceKnown) {
                                Text(money(item.lineTotal, order.currency), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                                Text("${money(item.effectiveUnit, order.currency)} × ${qtyText(item.effectiveQty)}", fontSize = 10.sp, color = c.textDim)
                            } else {
                                Text("× ${qtyText(item.effectiveQty)}", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                            }
                        }
                    }
                }
            }
            // pt-2.5 mt-2 over a #cee6b2 rule
            HorizontalDivider(color = c.bg4)
            Row(Modifier.fillMaxWidth().padding(top = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Total", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text, modifier = Modifier.weight(1f))
                Text(money(order.amount, order.currency), fontSize = 16.sp, fontWeight = FontWeight.Bold, color = c.gold2)
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
                    color = if (c.isDark) Tones.Amber.dot else Color(0xFFD97706))
                Spacer(Modifier.height(4.dp))
                Text(order.replyText, fontSize = 12.sp, color = if (c.isDark) Color(0xFFFDE68A) else Color(0xFF92400E))
            }
            Spacer(Modifier.height(16.dp))
        }

        // Customer thread shortcut
        OutlinedButton(onClick = { dash.openConversationFor(order.waId) }, modifier = Modifier.fillMaxWidth()) {
            Text("Open conversation")
        }
        Spacer(Modifier.height(10.dp))

        // Status moves
        if (actions.isNotEmpty()) {
            if (canManage) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    actions.forEach { next ->
                        WebBtn(
                            "Mark as ${statusMeta(next).label}",
                            variant = if (next == "cancelled") BtnVariant.Danger else BtnVariant.Primary,
                            enabled = !busy, busy = busy, onClick = { onStatus(next) },
                        )
                    }
                }
            } else {
                Text(
                    "You can view this order but your role can't change its status.",
                    fontSize = 12.sp, color = c.muted,
                )
            }
        }
    }
    }
}

/** The web Modal's header: `text-base font-semibold` title, a ✕ button, a hairline beneath. */
@Composable
internal fun ModalTitleBar(title: String, onClose: () -> Unit) {
    val c = Neema.colors
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, bottom = 12.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(title, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, color = c.text, modifier = Modifier.weight(1f))
        Box(
            Modifier.size(32.dp).clip(RoundedCornerShape(8.dp)).clickable(onClick = onClose),
            contentAlignment = Alignment.Center,
        ) {
            Icon(Icons.Default.Close, contentDescription = "Close", tint = Color(0xFF9CA3AF), modifier = Modifier.size(16.dp))
        }
    }
    HorizontalDivider(color = if (c.isDark) c.hairline else Color(0xFFF3F4F6))
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
        BtnVariant.Primary -> Triple(Color(0xFFF59E0B), Color.White, Color(0xFFF59E0B))
        BtnVariant.Danger -> if (dark) Triple(Color(0x4D450A0A), Color(0xFFF87171), Color(0xFF991B1B))
            else Triple(Color(0xFFFEF2F2), Color(0xFFDC2626), Color(0xFFFECACA))
        BtnVariant.Outline -> if (dark) Triple(Color.Transparent, Color(0xFFE5E7EB), Color(0xFF4B5563))
            else Triple(Color.Transparent, Color(0xFF374151), Color(0xFFD1D5DB))
    }
    val shape = RoundedCornerShape(8.dp)
    Row(
        modifier.height(36.dp).alpha(if (enabled) 1f else 0.4f).clip(shape).background(bg).border(1.dp, border, shape)
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 16.dp),
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
            .background(if (Neema.colors.isDark) Color(0xFF374151) else Color(0xFFE5E7EB)),
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
