package ke.co.bethanyhouse.neema.app

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.material3.windowsizeclass.WindowWidthSizeClass
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import ke.co.bethanyhouse.neema.core.notify.AppNotification
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.ConfirmDialog
import ke.co.bethanyhouse.neema.core.ui.theme.Brand
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons
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
import androidx.compose.foundation.border
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.unit.Dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/**
 * app/dashboard/page.tsx. Tablets get the web's docked navy sidebar
 * (collapsible to an icon rail). Phones get the same sidebar as a drawer
 * (☰, swipe, or "More"), the web's mobile header, and a bottom bar with the
 * four most-used views one tap away. The call card overlays the content.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardShell(
    dash: DashboardViewModel,
    widthClass: WindowWidthSizeClass,
    /** Screenshot tests: open the phone drawer / the bell on first frame. */
    initialDrawerOpen: Boolean = false,
    initialBellOpen: Boolean = false,
    initialToast: Toast? = null,
    initialAccountMenu: Boolean = false,
    initialCollapsed: Boolean = false,
) {
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

    // Permissions resolve once /me and the team list land; re-derive the nav then.
    val items = remember(me, agents, summary, orders, session) { dash.navItems() }
    val canSettings = remember(me, agents, session) { dash.can(Perms.MANAGE_SETTINGS) }

    var showBell by remember { mutableStateOf(initialBellOpen) }
    var confirmSignOut by remember { mutableStateOf(false) }
    var collapsed by rememberSaveable { mutableStateOf(initialCollapsed) }
    val unreadBell = notifications.count { !it.read }
    val wide = widthClass != WindowWidthSizeClass.Compact
    val drawer = rememberDrawerState(if (initialDrawerOpen) DrawerValue.Open else DrawerValue.Closed)
    val scope = rememberCoroutineScope()

    BackHandler(enabled = drawer.isOpen) { scope.launch { drawer.close() } }
    BackHandler(enabled = showBell && wide) { showBell = false }
    // Back from any view returns to the inbox before leaving the app.
    BackHandler(enabled = !drawer.isOpen && view != ViewId.Conversations && !immersive) { dash.navigate(ViewId.Conversations) }

    // One toast at a time, replaced by the next, gone after 3.5 s (page.tsx showToast).
    var toast by remember { mutableStateOf(initialToast) }
    LaunchedEffect(Unit) { dash.toasts.collect { toast = it } }
    LaunchedEffect(toast) { if (toast != null && initialToast == null) { delay(3_500); toast = null } }

    val openNotification: (AppNotification) -> Unit = { n ->
        dash.container.notifications.markRead(n.id)
        // The web only marks the row read; where the alert names a customer
        // (or an order) the app also takes the agent there.
        val target = n.convKey != null || n.type == "order_update"
        if (target) {
            showBell = false
            scope.launch { drawer.close() }
            if (n.convKey != null) dash.openConversationFor(n.convKey) else dash.navigate(ViewId.Orders)
        }
    }
    val panel = @Composable { modifier: Modifier, maxList: Dp ->
        NotificationsPanel(
            items = notifications,
            onOpen = openNotification,
            onMarkAllRead = { dash.container.notifications.markAllRead() },
            onDismissItem = { dash.container.notifications.dismiss(it) },
            onClear = { dash.container.notifications.clear() },
            modifier = modifier, listMaxHeight = maxList,
        )
    }

    val sidebar = @Composable { isCollapsed: Boolean, onToggle: (() -> Unit)?, width: Dp ->
        NeemaSidebar(
            items = items, view = view,
            onSelect = { dash.navigate(it); scope.launch { drawer.close() } },
            collapsed = isCollapsed, onToggleCollapse = onToggle,
            userName = me?.name?.ifBlank { null } ?: session?.name.orEmpty(),
            userEmail = me?.email?.ifBlank { null } ?: session?.email.orEmpty(),
            userRole = session?.role ?: me?.role.orEmpty(),
            avatarUrl = me?.avatarUrl,
            dark = dark, onToggleDark = { dash.setDark(!dark) },
            canSettings = canSettings,
            bellCount = unreadBell, onBell = { showBell = !showBell },
            onSignOut = { confirmSignOut = true },
            expandedWidth = width, initialMenuOpen = initialAccountMenu,
        )
    }

    val content = @Composable {
        Scaffold(
            topBar = {
                if (!wide && !immersive) MobileHeader(
                    title = view.label, connected = connected, dark = dark, bell = unreadBell,
                    onMenu = { scope.launch { drawer.open() } },
                    onBell = { showBell = true }, onTheme = { dash.setDark(!dark) },
                )
            },
            bottomBar = {
                if (!wide && !immersive) MobileBottomNav(items.take(4), view, moreActive = items.drop(4).any { it.id == view },
                    onSelect = dash::navigate, onMore = { scope.launch { drawer.open() } })
            },
            containerColor = MaterialTheme.colorScheme.background,
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
                if (wide && !connected) OfflineDot(Modifier.align(Alignment.TopEnd).padding(10.dp))
                // An incoming/active call takes over the content area.
                CallStage(dash)
            }
        }
    }

    Box(Modifier.fillMaxSize()) {
        if (wide) {
            val railWidth = if (collapsed) 60.dp else 208.dp
            Row(Modifier.fillMaxSize().background(Brand.Navy)) {
                if (!immersive) Box(Modifier.statusBarsPadding().navigationBarsPadding()) { sidebar(collapsed, { collapsed = !collapsed }, 208.dp) }
                Box(Modifier.weight(1f)) { content() }
            }
            // The web's bell popup: 316dp, beside the rail, closes on an outside tap.
            if (showBell) {
                Box(Modifier.fillMaxSize().clickable(interactionSource = null, indication = null) { showBell = false })
                Box(
                    Modifier.statusBarsPadding()
                        .padding(start = if (collapsed) railWidth + 8.dp else 132.dp, top = if (collapsed) 50.dp else 62.dp)
                        .width(316.dp)
                        .shadow(16.dp, RoundedCornerShape(14.dp))
                        .clip(RoundedCornerShape(14.dp))
                        .border(1.dp, if (dark) Color(0xFF152451) else Color(0xFFE8EBE3), RoundedCornerShape(14.dp)),
                ) { panel(Modifier, 360.dp) }
            }
        } else {
            ModalNavigationDrawer(
                drawerState = drawer,
                gesturesEnabled = !immersive || drawer.isOpen,
                drawerContent = {
                    ModalDrawerSheet(
                        drawerContainerColor = Brand.Navy, drawerShape = RoundedCornerShape(topEnd = 18.dp, bottomEnd = 18.dp),
                        modifier = Modifier.width(272.dp),
                    ) {
                        Box(Modifier.statusBarsPadding().navigationBarsPadding()) { sidebar(false, null, 272.dp) }
                    }
                },
            ) { content() }
        }

        toast?.let { t ->
            ToastView(
                t, mobile = !wide,
                modifier = if (wide) Modifier.align(Alignment.TopEnd).statusBarsPadding().padding(top = 20.dp, end = 20.dp)
                else Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(start = 16.dp, end = 16.dp, bottom = 84.dp),
            )
        }
    }

    if (confirmSignOut) ConfirmDialog(
        title = "Sign out?", message = "You'll stop receiving alerts and calls on this phone until you sign in again.",
        confirmLabel = "Sign out", destructive = true,
        onConfirm = { dash.logout() }, onDismiss = { confirmSignOut = false },
    )

    if (showBell && !wide) {
        ModalBottomSheet(
            onDismissRequest = { showBell = false },
            containerColor = if (dark) Color(0xFF0A1229) else Color.White,
        ) { panel(Modifier.navigationBarsPadding(), 520.dp) }
    }
}

@Composable
private fun OfflineDot(modifier: Modifier = Modifier) {
    Row(
        modifier.clip(RoundedCornerShape(50)).background(Color(0xFFFEF3C7)).padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(6.dp).clip(RoundedCornerShape(50)).background(Color(0xFFD97706)))
        Text("  Reconnecting…", fontSize = 10.sp, color = Color(0xFF92400E), fontWeight = FontWeight.SemiBold)
    }
}

/** components/ui/MobileNav.tsx MobileHeader, plus ☰ for the sidebar drawer. */
@Composable
internal fun MobileHeader(
    title: String, connected: Boolean, dark: Boolean, bell: Int,
    onMenu: () -> Unit, onBell: () -> Unit, onTheme: () -> Unit,
) {
    val c = Neema.colors
    Column(Modifier.background(c.bg2).statusBarsPadding()) {
        Row(Modifier.fillMaxWidth().height(56.dp).padding(start = 4.dp, end = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onMenu) { Icon(WebIcons.Menu, "Menu", tint = c.muted, modifier = Modifier.size(20.dp)) }
            NeemaLogo(28.dp)
            Text("Neema", fontWeight = FontWeight.SemiBold, fontSize = 15.sp, modifier = Modifier.padding(start = 10.dp), color = c.text)
            Text("  ·  ", color = c.muted)
            Text(title, fontSize = 14.sp, fontWeight = FontWeight.Medium, color = c.muted, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
            if (!connected) OfflineDot(Modifier.padding(end = 4.dp))
            Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).clickable(onClick = onBell), contentAlignment = Alignment.Center) {
                Icon(WebIcons.Bell, "Notifications", tint = c.muted, modifier = Modifier.size(18.dp))
                if (bell > 0) Box(
                    Modifier.align(Alignment.TopEnd).padding(top = 5.dp, end = 5.dp).defaultMinSize(16.dp, 16.dp)
                        .clip(RoundedCornerShape(50)).background(Color(0xFFEF4444)).padding(horizontal = 3.dp),
                    contentAlignment = Alignment.Center,
                ) { Text(if (bell > 9) "9+" else "$bell", color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.SemiBold) }
            }
            Box(Modifier.size(40.dp).clip(RoundedCornerShape(10.dp)).clickable(onClick = onTheme), contentAlignment = Alignment.Center) {
                Icon(if (dark) WebIcons.Sun else WebIcons.Moon, "Theme", tint = c.muted, modifier = Modifier.size(18.dp))
            }
        }
        HorizontalDivider(color = c.hairline)
    }
}

/** components/ui/MobileNav.tsx MobileBottomNav: amber active label with a top indicator. */
@Composable
internal fun MobileBottomNav(
    items: List<NavItem>, view: ViewId, moreActive: Boolean,
    onSelect: (ViewId) -> Unit, onMore: () -> Unit,
) {
    val c = Neema.colors
    Column(Modifier.background(c.bg2)) {
        HorizontalDivider(color = c.hairline)
        Row(Modifier.fillMaxWidth().navigationBarsPadding().height(60.dp)) {
            items.forEach { item ->
                BottomTab(item.icon, item.id.label, item.badge, item.id == view, Modifier.weight(1f)) { onSelect(item.id) }
            }
            BottomTab(WebIcons.More, "More", 0, moreActive, Modifier.weight(1f), onClick = onMore)
        }
    }
}

@Composable
private fun BottomTab(
    icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, badge: Int, active: Boolean,
    modifier: Modifier, onClick: () -> Unit,
) {
    val tint = if (active) Brand.Amber else Color(0xFF9CA3AF)
    Box(modifier.fillMaxHeight().clickable(onClick = onClick), contentAlignment = Alignment.Center) {
        if (active) Box(Modifier.align(Alignment.TopCenter).fillMaxWidth(0.5f).height(2.dp).clip(RoundedCornerShape(bottomStart = 2.dp, bottomEnd = 2.dp)).background(Brand.Amber))
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, label, tint = tint, modifier = Modifier.size(22.dp))
            Spacer(Modifier.height(4.dp))
            Text(label, fontSize = 10.sp, fontWeight = FontWeight.Medium, color = tint, maxLines = 1)
        }
        if (badge > 0) Box(Modifier.align(Alignment.TopCenter).padding(top = 5.dp, start = 34.dp)) { AmberBadge(badge, small = true) }
    }
}

