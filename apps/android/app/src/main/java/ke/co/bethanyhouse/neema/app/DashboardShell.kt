package ke.co.bethanyhouse.neema.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Chat
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ke.co.bethanyhouse.neema.core.notify.AppNotification
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.CountBadge
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.agents.AgentsScreen
import ke.co.bethanyhouse.neema.feature.calls.CallStage
import ke.co.bethanyhouse.neema.feature.calls.CallsScreen
import ke.co.bethanyhouse.neema.feature.catalog.CatalogScreen
import ke.co.bethanyhouse.neema.feature.conversations.ConversationsScreen
import ke.co.bethanyhouse.neema.feature.deals.DealsScreen
import ke.co.bethanyhouse.neema.feature.leads.LeadsScreen
import ke.co.bethanyhouse.neema.feature.orders.OrdersScreen
import ke.co.bethanyhouse.neema.feature.overview.OverviewScreen
import ke.co.bethanyhouse.neema.feature.profile.ProfileScreen
import ke.co.bethanyhouse.neema.feature.reports.ReportsScreen
import ke.co.bethanyhouse.neema.feature.settings.SettingsScreen

data class NavItem(val id: ViewId, val icon: ImageVector, val badge: Int = 0)

private fun iconFor(v: ViewId): ImageVector = when (v) {
    ViewId.Conversations -> Icons.AutoMirrored.Outlined.Chat
    ViewId.Calls -> Icons.Outlined.Call
    ViewId.Orders -> Icons.Outlined.Inventory2
    ViewId.Reports -> Icons.Outlined.Description
    ViewId.Deals -> Icons.Outlined.Bolt
    ViewId.Leads -> Icons.Outlined.Flag
    ViewId.Overview -> Icons.Outlined.BarChart
    ViewId.Catalog -> Icons.Outlined.Menu
    ViewId.Agents -> Icons.Outlined.Groups
    ViewId.Settings -> Icons.Outlined.Settings
    ViewId.Profile -> Icons.Outlined.Person
}

/** app/dashboard/page.tsx: nav, header, the current view, the call overlay, toasts. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardShell(dash: DashboardViewModel, widthClass: WindowWidthSizeClass) {
    val view by dash.view.collectAsStateWithLifecycle()
    val summary by dash.inboxSummary.collectAsStateWithLifecycle()
    val orders by dash.orders.collectAsStateWithLifecycle()
    val me by dash.me.collectAsStateWithLifecycle()
    val agents by dash.agents.collectAsStateWithLifecycle()
    val session by dash.session.collectAsStateWithLifecycle()
    val dark by dash.dark.collectAsStateWithLifecycle()
    val immersive by dash.immersive.collectAsStateWithLifecycle()
    val notifications by dash.container.notifications.items.collectAsStateWithLifecycle()
    val connected by dash.container.socket.connected.collectAsStateWithLifecycle()
    @Suppress("UNUSED_VARIABLE") val permsKey = me to agents  // recompute nav when permissions arrive

    val humanConvs = summary?.human ?: 0
    val pendingOrders = orders.count { it.status == "pending" }

    val items = buildList {
        add(NavItem(ViewId.Conversations, iconFor(ViewId.Conversations), humanConvs))
        add(NavItem(ViewId.Calls, iconFor(ViewId.Calls)))
        add(NavItem(ViewId.Orders, iconFor(ViewId.Orders), pendingOrders))
        if (dash.can(Perms.VIEW_REPORTS)) add(NavItem(ViewId.Reports, iconFor(ViewId.Reports)))
        if (dash.can(Perms.VIEW_LEADS)) {
            add(NavItem(ViewId.Deals, iconFor(ViewId.Deals)))
            add(NavItem(ViewId.Leads, iconFor(ViewId.Leads)))
        }
        if (dash.can(Perms.VIEW_ANALYTICS)) add(NavItem(ViewId.Overview, iconFor(ViewId.Overview)))
        if (dash.can(Perms.VIEW_CATALOG)) add(NavItem(ViewId.Catalog, iconFor(ViewId.Catalog)))
        if (dash.can(Perms.MANAGE_AGENTS)) add(NavItem(ViewId.Agents, iconFor(ViewId.Agents)))
        if (dash.can(Perms.MANAGE_SETTINGS)) add(NavItem(ViewId.Settings, iconFor(ViewId.Settings)))
        add(NavItem(ViewId.Profile, iconFor(ViewId.Profile)))
    }

    var showBell by remember { mutableStateOf(false) }
    var showMore by remember { mutableStateOf(false) }
    val unreadBell = notifications.count { !it.read }

    // Back from any view returns to the inbox before leaving the app.
    BackHandler(enabled = view != ViewId.Conversations && !immersive) { dash.navigate(ViewId.Conversations) }

    val wide = widthClass != WindowWidthSizeClass.Compact
    val snackbar = remember { SnackbarHostState() }
    LaunchedEffect(Unit) {
        dash.toasts.collect { t ->
            snackbar.currentSnackbarData?.dismiss()
            snackbar.showSnackbar(t.message, duration = SnackbarDuration.Short)
        }
    }

    Row(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
        if (wide && !immersive) {
            NavigationRail(
                containerColor = Neema.colors.bg2,
                header = {
                    Box(Modifier.padding(vertical = 8.dp).size(36.dp).clip(RoundedCornerShape(10.dp)).background(Neema.colors.gold), contentAlignment = Alignment.Center) {
                        Text("N", color = Color.White, fontWeight = FontWeight.ExtraBold)
                    }
                },
            ) {
                LazyColumn(horizontalAlignment = Alignment.CenterHorizontally) {
                    items(items, key = { it.id }) { item ->
                        NavigationRailItem(
                            selected = view == item.id,
                            onClick = { dash.navigate(item.id) },
                            icon = { BadgedBox(badge = { if (item.badge > 0) Badge { Text(badgeText(item.badge)) } }) { Icon(item.icon, item.id.label) } },
                            label = { Text(item.id.label, fontSize = 11.sp) },
                        )
                    }
                }
            }
        }
        Scaffold(
            modifier = Modifier.weight(1f),
            snackbarHost = { SnackbarHost(snackbar) },
            topBar = {
                if (!immersive) TopAppBar(
                    title = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            if (!wide) {
                                Box(Modifier.size(28.dp).clip(RoundedCornerShape(8.dp)).background(Neema.colors.gold), contentAlignment = Alignment.Center) {
                                    Icon(Icons.AutoMirrored.Outlined.Chat, null, tint = Color.White, modifier = Modifier.size(16.dp))
                                }
                                Spacer(Modifier.width(8.dp))
                                Text("Neema", fontWeight = FontWeight.Bold, fontSize = 15.sp)
                                Text("  ·  ", color = Neema.colors.muted)
                            }
                            Text(view.label, fontSize = 15.sp, color = if (wide) MaterialTheme.colorScheme.onSurface else Neema.colors.muted, fontWeight = FontWeight.SemiBold)
                            if (!connected) {
                                Spacer(Modifier.width(8.dp))
                                Box(Modifier.size(8.dp).clip(RoundedCornerShape(50)).background(Color(0xFFD97706)))
                            }
                        }
                    },
                    actions = {
                        IconButton(onClick = { showBell = true }) {
                            BadgedBox(badge = { if (unreadBell > 0) Badge { Text(if (unreadBell > 9) "9+" else "$unreadBell") } }) {
                                Icon(Icons.Outlined.Notifications, "Notifications")
                            }
                        }
                        IconButton(onClick = { dash.setDark(!dark) }) {
                            Icon(if (dark) Icons.Outlined.LightMode else Icons.Outlined.DarkMode, "Theme")
                        }
                        if (wide) {
                            Box(Modifier.padding(end = 8.dp).clickable { dash.navigate(ViewId.Profile) }) {
                                Avatar(me?.name ?: session?.name, me?.avatarUrl, size = 32.dp)
                            }
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = Neema.colors.bg2),
                )
            },
            bottomBar = {
                if (!wide && !immersive) {
                    val primary = items.take(4)
                    val overflow = items.drop(4)
                    NavigationBar(containerColor = Neema.colors.bg2, tonalElevation = 0.dp) {
                        primary.forEach { item ->
                            NavigationBarItem(
                                selected = view == item.id,
                                onClick = { dash.navigate(item.id) },
                                icon = { BadgedBox(badge = { if (item.badge > 0) Badge { Text(badgeText(item.badge)) } }) { Icon(item.icon, item.id.label) } },
                                label = { Text(item.id.label, fontSize = 11.sp, maxLines = 1) },
                            )
                        }
                        if (overflow.isNotEmpty()) {
                            NavigationBarItem(
                                selected = overflow.any { it.id == view },
                                onClick = { showMore = true },
                                icon = { Icon(Icons.Outlined.MoreHoriz, "More") },
                                label = { Text(if (overflow.any { it.id == view }) view.label else "More", fontSize = 11.sp, maxLines = 1) },
                            )
                        }
                    }
                }
            },
            contentWindowInsets = if (immersive) WindowInsets(0) else ScaffoldDefaults.contentWindowInsets,
        ) { pad ->
            Box(Modifier.fillMaxSize().padding(pad)) {
                when (view) {
                    ViewId.Conversations -> ConversationsScreen(dash)
                    ViewId.Calls -> CallsScreen(dash)
                    ViewId.Orders -> OrdersScreen(dash)
                    ViewId.Reports -> ReportsScreen(dash)
                    ViewId.Deals -> DealsScreen(dash)
                    ViewId.Leads -> LeadsScreen(dash)
                    ViewId.Overview -> OverviewScreen(dash)
                    ViewId.Catalog -> CatalogScreen(dash)
                    ViewId.Agents -> AgentsScreen(dash)
                    ViewId.Settings -> SettingsScreen(dash)
                    ViewId.Profile -> ProfileScreen(dash)
                }
                // An incoming/active call takes over the content area.
                CallStage(dash)
            }
        }
    }

    if (showMore) {
        ModalBottomSheet(onDismissRequest = { showMore = false }) {
            Column(Modifier.padding(bottom = 24.dp)) {
                items.drop(4).forEach { item ->
                    ListItem(
                        headlineContent = { Text(item.id.label, fontWeight = if (item.id == view) FontWeight.Bold else FontWeight.Normal) },
                        leadingContent = { Icon(item.icon, null, tint = if (item.id == view) Neema.colors.gold else LocalContentColor.current) },
                        trailingContent = { CountBadge(item.badge) },
                        modifier = Modifier.clickable { dash.navigate(item.id); showMore = false },
                    )
                }
            }
        }
    }

    if (showBell) {
        NotificationsSheet(
            items = notifications,
            onDismiss = { showBell = false; dash.container.notifications.markAllRead() },
            onOpen = { n ->
                dash.container.notifications.markRead(n.id)
                showBell = false
                when {
                    n.convKey != null -> dash.openConversationFor(n.convKey)
                    n.type == "order_update" -> dash.navigate(ViewId.Orders)
                }
            },
            onClear = { dash.container.notifications.clear() },
        )
    }
}

private fun badgeText(n: Int) = if (n > 99) "99+" else "$n"

private fun notifMeta(type: String): Pair<String, Color> = when (type) {
    "intercept", "human_transfer" -> "🙋" to Color(0xFF2A48A2)
    "new_message", "new_conversation" -> "💬" to Color(0xFF589B31)
    "order", "order_update" -> "📦" to Color(0xFFD97706)
    "transfer" -> "🔀" to Color(0xFF3D528F)
    "media_escalation" -> "📎" to Color(0xFFC0392B)
    "daily_summary" -> "📊" to Color(0xFF0E7490)
    else -> "🔔" to Color(0xFF8A9E80)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun NotificationsSheet(
    items: List<AppNotification>,
    onDismiss: () -> Unit,
    onOpen: (AppNotification) -> Unit,
    onClear: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Notifications", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            if (items.isNotEmpty()) TextButton(onClick = onClear) { Text("Clear all") }
        }
        if (items.isEmpty()) {
            Box(Modifier.fillMaxWidth().padding(40.dp), contentAlignment = Alignment.Center) {
                Text("You're all caught up", color = Neema.colors.muted)
            }
        } else LazyColumn(Modifier.heightIn(max = 520.dp), contentPadding = PaddingValues(bottom = 24.dp)) {
            items(items, key = { it.id }) { n ->
                val (emoji, color) = notifMeta(n.type)
                Row(
                    Modifier.fillMaxWidth().clickable { onOpen(n) }
                        .background(if (!n.read) color.copy(alpha = 0.06f) else Color.Transparent)
                        .padding(horizontal = 20.dp, vertical = 10.dp),
                ) {
                    Box(Modifier.size(34.dp).clip(RoundedCornerShape(10.dp)).background(color.copy(alpha = 0.14f)), contentAlignment = Alignment.Center) {
                        Text(emoji)
                    }
                    Spacer(Modifier.width(12.dp))
                    Column(Modifier.weight(1f)) {
                        Text(n.title, fontWeight = if (n.read) FontWeight.Medium else FontWeight.Bold, fontSize = 14.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(n.body, fontSize = 13.sp, color = Neema.colors.muted, maxLines = 2, overflow = TextOverflow.Ellipsis)
                        Text(Fmt.timeAgo(java.time.Instant.ofEpochMilli(n.at).toString()), fontSize = 11.sp, color = Neema.colors.muted)
                    }
                    if (!n.read) Box(Modifier.padding(top = 6.dp).size(8.dp).clip(RoundedCornerShape(50)).background(color))
                }
            }
        }
    }
}
