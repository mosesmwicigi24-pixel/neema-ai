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
import ke.co.bethanyhouse.neema.core.ui.theme.Brand
import ke.co.bethanyhouse.neema.core.ui.theme.LightNeema
import ke.co.bethanyhouse.neema.core.ui.theme.LocalNeemaColors
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.ui.theme.scaledAtMost
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
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
    // The inbox runs from sign-in, whatever view is open (the web's useInbox lives
    // in page.tsx): its badge and summary stay live even if the app opened on
    // Orders. ConversationsScreen asks for the same default-keyed instance.
    androidx.lifecycle.viewmodel.compose.viewModel { ke.co.bethanyhouse.neema.feature.conversations.ConversationsViewModel(dash) }
    val summary by dash.inboxSummary.collectAsStateWithLifecycle()
    val orders by dash.orders.collectAsStateWithLifecycle()
    val me by dash.me.collectAsStateWithLifecycle()
    val agents by dash.agents.collectAsStateWithLifecycle()
    val session by dash.session.collectAsStateWithLifecycle()
    val dark by dash.dark.collectAsStateWithLifecycle()
    val immersive by dash.immersive.collectAsStateWithLifecycle()
    val notifications by dash.container.notifications.items.collectAsStateWithLifecycle()
    val connected by dash.container.socket.connected.collectAsStateWithLifecycle()
    val online by dash.online.collectAsStateWithLifecycle()
    val backOnline = rememberBackOnline(online)

    // Permissions resolve once the team list lands (and again on every agents
    // poll or 403 reread); re-derive the nav whenever they change.
    val access by dash.access.collectAsStateWithLifecycle()
    val items = remember(access, me, agents, summary, orders, session) { dash.navItems() }

    // Open overlays survive a configuration change (rotation, fold, dark mode,
    // font size) and the process being restored; the drawer's state is saveable too.
    var showBell by rememberSaveable { mutableStateOf(initialBellOpen) }
    var menuOpen by rememberSaveable { mutableStateOf(initialAccountMenu) }
    // A 600–840dp window (an unfolded foldable, a small tablet upright) opens on
    // the 60dp icon rail so the view keeps its width; the toggle still expands it.
    var collapsed by rememberSaveable { mutableStateOf(initialCollapsed || widthClass == WindowWidthSizeClass.Medium) }
    val unreadBell = notifications.count { !it.read }
    val wide = widthClass != WindowWidthSizeClass.Compact
    val drawer = rememberDrawerState(if (initialDrawerOpen) DrawerValue.Open else DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val canGoBack by dash.canGoBack.collectAsStateWithLifecycle()
    val signingOut by dash.signingOut.collectAsStateWithLifecycle()

    // System back, lowest priority first (see ShellBack.kt). The view history:
    // registered before any view composes, so every view's own handler wins.
    BackHandler(enabled = canGoBack) { dash.back() }
    // The shell's overlays: one handler, composed AFTER the view (in the
    // content, below) and re-registered whenever the topmost overlay
    // changes, so it sits above every view's handlers; views can also read
    // LocalShellOverlayOpen and stand down while one is open.
    val drawerShown = !wide && (drawer.isOpen || drawer.targetValue == DrawerValue.Open)
    val menuShown = menuOpen && !(wide && collapsed) && (wide || drawerShown)
    val overlay = shellBackTarget(bellPopupOpen = showBell && wide, accountMenuOpen = menuShown, drawerOpen = drawerShown)
    val overlayBack = @Composable {
        key(overlay) {
            BackHandler(enabled = overlay != null) {
                when (overlay) {
                    ShellOverlay.Bell -> showBell = false
                    ShellOverlay.AccountMenu -> menuOpen = false
                    ShellOverlay.Drawer -> scope.launch { drawer.close() }
                    null -> Unit
                }
            }
        }
    }
    // The phone's account menu lives in the drawer: it closes with it.
    LaunchedEffect(drawerShown) { if (!wide && !drawerShown && !initialAccountMenu) menuOpen = false }

    // One toast at a time, replaced by the next, gone after 3.5 s in front
    // (page.tsx showToast) — the dashboard holds it, so it survives recreation.
    val liveToast by dash.currentToast.collectAsStateWithLifecycle()
    val toast = initialToast ?: liveToast

    val openNotification: (AppNotification) -> Unit = { n ->
        dash.container.notifications.markRead(n.id)
        // The web only marks the row read; where the alert names a customer
        // (or an order) the app also takes the agent there — the same target
        // as tapping its phone notification.
        val view = ke.co.bethanyhouse.neema.core.notify.NotificationCenter.viewFor(n)?.let(ViewId::fromWeb)
        if (n.convKey != null || view != null) {
            showBell = false
            scope.launch { drawer.close() }
            if (n.convKey != null) dash.openConversationFor(n.convKey) else if (view != null) dash.navigate(view)
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

    // The docked sidebar widens with large text (up to 130%) so its labels keep their room.
    val dockedWidth = 208.dp * LocalDensity.current.fontScale.coerceIn(1f, 1.3f)
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
            bellCount = unreadBell, onBell = { showBell = !showBell }, bellOpen = showBell && wide,
            // Sidebar.tsx signs straight out — no confirmation step.
            onSignOut = { dash.logout() },
            expandedWidth = width,
            menuOpen = menuOpen, onMenuOpenChange = { menuOpen = it },
            signingOut = signingOut,
        )
    }

    val content = @Composable {
        Scaffold(
            topBar = {
                if (!wide && !immersive) MobileHeader(
                    title = view.label, connected = connected || !online, dark = dark, bell = unreadBell,
                    onMenu = { scope.launch { drawer.open() } },
                    onBell = { showBell = true }, onTheme = { dash.setDark(!dark) },
                )
            },
            bottomBar = {
                if (!wide && !immersive) MobileBottomNav(items.take(4), view, moreActive = items.drop(4).any { it.id == view },
                    onSelect = dash::navigate, onMore = { scope.launch { drawer.open() } })
            },
            containerColor = MaterialTheme.colorScheme.background,
            contentWindowInsets = when {
                immersive -> WindowInsets(0)
                // Docked: the sidebar owns the start edge (and a landscape cutout there).
                wide -> WindowInsets.systemBars.union(WindowInsets.displayCutout).only(WindowInsetsSides.Top + WindowInsetsSides.End + WindowInsetsSides.Bottom)
                else -> ScaffoldDefaults.contentWindowInsets
            },
        ) { pad ->
            // The views sit above the keyboard: the bars' padding counts towards
            // it (consumed), so a search field at the bottom is never covered and
            // a view's own imePadding (the thread's composer) is not added twice.
            Column(Modifier.fillMaxSize().padding(pad).consumeWindowInsets(pad).imePadding()) {
            // Immersive views (an open thread) run to the top edge and pad for the
            // status bar themselves: the banner takes that padding and the view
            // below is told the status bar is already accounted for.
            val banner = !online || backOnline
            ConnectivityBanner(online, backOnline, if (immersive) Modifier.statusBarsPadding() else Modifier)
            Box(
                Modifier.fillMaxWidth().weight(1f)
                    .then(if (immersive && banner) Modifier.consumeWindowInsets(WindowInsets.statusBars) else Modifier),
            ) {
                CompositionLocalProvider(LocalShellOverlayOpen provides (overlay != null)) {
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
                }
                // Online but the live socket is down: it is on its way back.
                if (wide && !connected && online) OfflineDot(Modifier.align(Alignment.TopEnd).padding(10.dp))
                // An incoming/active call takes over the content area.
                CallStage(dash)
                // Last of all, so the shell's overlays take back before the view does.
                overlayBack()
            }
            }
        }
    }

    Box(Modifier.fillMaxSize()) {
        if (wide) {
            // Navy runs under the status bar across the whole width (light status
            // icons over it — see MainActivity), framing the view like the web's
            // full-height sidebar does.
            Row(Modifier.fillMaxSize().background(Brand.Navy).windowInsetsPadding(WindowInsets.statusBars.only(WindowInsetsSides.Top))) {
                if (!immersive) Box(
                    Modifier.windowInsetsPadding(
                        WindowInsets.systemBars.union(WindowInsets.displayCutout).only(WindowInsetsSides.Start + WindowInsetsSides.Bottom),
                    ),
                ) { sidebar(collapsed, { collapsed = !collapsed }, dockedWidth) }
                Box(Modifier.weight(1f).background(MaterialTheme.colorScheme.background)) { content() }
            }
            // The web's bell popup (Notifications.tsx): 316dp and white in both themes.
            // Expanded, it drops 6dp below the bell (bell at x 130, bottom 46);
            // on the rail it opens 8dp right of the bell, level with its top (50, 50).
            // An outside tap closes it.
            if (showBell) {
                Box(Modifier.fillMaxSize().clickable(interactionSource = null, indication = null) { showBell = false })
                Box(
                    Modifier.windowInsetsPadding(WindowInsets.systemBars.union(WindowInsets.displayCutout).only(WindowInsetsSides.Top + WindowInsetsSides.Start))
                        .padding(start = if (collapsed) 58.dp else 130.dp, top = if (collapsed) 50.dp else 52.dp)
                        .width(316.dp)
                        .shadow(16.dp, RoundedCornerShape(14.dp))
                        .clip(RoundedCornerShape(14.dp))
                        .border(1.dp, Palette.Hairline, RoundedCornerShape(14.dp)),
                ) { CompositionLocalProvider(LocalNeemaColors provides LightNeema) { panel(Modifier, 360.dp) } }
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
                // Clear of the bottom nav, or of the keyboard / composer while typing.
                else Modifier.align(Alignment.BottomCenter)
                    .windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
                    .padding(start = 16.dp, end = 16.dp, bottom = 96.dp),
            )
        }
    }

    if (showBell && !wide) {
        ModalBottomSheet(
            onDismissRequest = { showBell = false },
            containerColor = Neema.chrome.bar,
        ) { panel(Modifier.navigationBarsPadding(), 520.dp) }
    }
}

@Composable
private fun OfflineDot(modifier: Modifier = Modifier) {
    Row(
        modifier.clip(RoundedCornerShape(50)).background(Palette.Amber100).padding(horizontal = 8.dp, vertical = 3.dp)
            .semantics(mergeDescendants = true) { contentDescription = "Reconnecting to live updates" },
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(6.dp).clip(RoundedCornerShape(50)).background(Palette.Amber600))
        Text("  Reconnecting…", fontSize = 10.sp.scaledAtMost(1.3f), color = Palette.Amber800, fontWeight = FontWeight.SemiBold, maxLines = 1)
    }
}

/**
 * components/ui/MobileNav.tsx MobileHeader, plus ☰ for the sidebar drawer:
 * a flat 28dp amber mark, "Neema · <view>", then the bell and the theme
 * switch as 48dp touch targets around the web's 16dp glyphs. White by day;
 * the Prussian surface by night. At very large text sizes the "Neema ·"
 * wordmark gives its room to the view's name. The web's bell here only
 * zeroes the count; the app's opens the bell's list.
 */
@Composable
internal fun MobileHeader(
    title: String, connected: Boolean, dark: Boolean, bell: Int,
    onMenu: () -> Unit, onBell: () -> Unit, onTheme: () -> Unit,
) {
    val chrome = Neema.chrome
    val roomy = LocalDensity.current.fontScale < 1.5f
    Column(Modifier.background(chrome.bar).windowInsetsPadding(WindowInsets.statusBars.union(WindowInsets.displayCutout).only(WindowInsetsSides.Top + WindowInsetsSides.Horizontal))) {
        Row(Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(start = 4.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(48.dp).clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onMenu),
                contentAlignment = Alignment.Center,
            ) { Icon(WebIcons.Menu, "Open navigation menu", tint = chrome.icon, modifier = Modifier.size(20.dp)) }
            NeemaLogo(28.dp, corner = 8.dp, glow = false)
            Spacer(Modifier.width(12.dp))
            if (roomy) {
                Text("Neema", fontWeight = FontWeight.SemiBold, fontSize = 14.sp, color = chrome.title, maxLines = 1)
                Spacer(Modifier.width(12.dp))
                Text("·", fontSize = 14.sp, color = chrome.separator)
                Spacer(Modifier.width(12.dp))
            }
            Text(
                title, fontSize = 14.sp, fontWeight = if (roomy) FontWeight.Medium else FontWeight.SemiBold,
                color = if (roomy) chrome.subtitle else chrome.title,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f).semantics { heading() },
            )
            if (!connected) OfflineDot(Modifier.padding(end = 4.dp))
            Box(
                Modifier.size(48.dp).clip(RoundedCornerShape(12.dp))
                    .clickable(role = Role.Button, onClickLabel = "Open notifications", onClick = onBell)
                    .semantics(mergeDescendants = true) {
                        contentDescription = if (bell > 0) "Notifications, $bell unread" else "Notifications"
                    },
                contentAlignment = Alignment.Center,
            ) {
                Icon(WebIcons.Bell, null, tint = chrome.icon, modifier = Modifier.size(18.dp))
                if (bell > 0) {
                    val size = 10.sp.scaledAtMost(1.2f)
                    Box(
                        Modifier.align(Alignment.TopEnd).padding(top = 6.dp, end = 6.dp).defaultMinSize(16.dp, 16.dp)
                            .clip(RoundedCornerShape(50)).background(Palette.Red500).padding(horizontal = 4.dp),
                        contentAlignment = Alignment.Center,
                    ) { Text(if (bell > 9) "9+" else "$bell", color = Color.White, fontSize = size, lineHeight = size, fontWeight = FontWeight.SemiBold) }
                }
            }
            Box(
                Modifier.size(48.dp).clip(RoundedCornerShape(12.dp)).clickable(role = Role.Button, onClick = onTheme),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    if (dark) WebIcons.Sun else WebIcons.Moon, if (dark) "Switch to light mode" else "Switch to dark mode",
                    tint = chrome.icon, modifier = Modifier.size(18.dp),
                )
            }
        }
        HorizontalDivider(color = chrome.barLine)
    }
}

/**
 * components/ui/MobileNav.tsx MobileBottomNav: 56dp, 20dp icons over 10sp
 * labels, amber when active with a 2dp indicator across the middle half, an
 * amber count 8dp right of centre. The web shows the first five views; the
 * app shows four and a "More" that opens the drawer, so every view is reachable.
 * Labels and counts grow with the font size up to 130% so they stay inside
 * the bar; TalkBack reads each tab as "Inbox, 2 new, tab, selected".
 */
@Composable
internal fun MobileBottomNav(
    items: List<NavItem>, view: ViewId, moreActive: Boolean,
    onSelect: (ViewId) -> Unit, onMore: () -> Unit,
) {
    val chrome = Neema.chrome
    Column(Modifier.background(chrome.bar)) {
        HorizontalDivider(color = chrome.barLine)
        Row(
            Modifier.fillMaxWidth()
                .windowInsetsPadding(WindowInsets.navigationBars.union(WindowInsets.displayCutout).only(WindowInsetsSides.Bottom + WindowInsetsSides.Horizontal))
                .height(56.dp)
                .selectableGroup(),
        ) {
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
    val chrome = Neema.chrome
    val tint = if (active) chrome.active else chrome.subtitle
    Box(
        modifier.fillMaxHeight()
            .selectable(selected = active, role = Role.Tab, onClick = onClick)
            .semantics(mergeDescendants = true) { contentDescription = if (badge > 0) "$label, $badge new" else label },
        contentAlignment = Alignment.Center,
    ) {
        if (active) Box(Modifier.align(Alignment.TopCenter).fillMaxWidth(0.5f).height(2.dp).clip(RoundedCornerShape(bottomStart = 2.dp, bottomEnd = 2.dp)).background(Brand.Amber))
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Icon(icon, null, tint = tint, modifier = Modifier.size(20.dp))
            Spacer(Modifier.height(4.dp))
            val size = 10.sp.scaledAtMost(1.3f)
            Text(
                label, fontSize = size, lineHeight = size * 1.4f, fontWeight = if (active) FontWeight.SemiBold else FontWeight.Medium,
                color = tint, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        // top-2 left-1/2 ml-2: the count starts 8dp right of the tab's centre, 8dp down.
        if (badge > 0) Row(Modifier.align(Alignment.TopStart).fillMaxWidth().padding(top = 6.dp)) {
            Spacer(Modifier.weight(1f))
            Box(Modifier.weight(1f).padding(start = 6.dp)) { AmberBadge(badge, bottomNav = true) }
        }
    }
}
