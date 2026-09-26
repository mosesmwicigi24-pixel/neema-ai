package ke.co.bethanyhouse.neema.app

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.theme.Brand
import ke.co.bethanyhouse.neema.core.ui.theme.LightNeema
import ke.co.bethanyhouse.neema.core.ui.theme.LocalNeemaColors
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupProperties
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.ui.theme.scaledAtMost
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.selection.selectableGroup
import androidx.compose.foundation.selection.toggleable
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics

data class NavItem(val id: ViewId, val icon: ImageVector, val badge: Int = 0)

/**
 * app/dashboard/page.tsx's nav: Inbox (human-held badge), Calls and Orders
 * (pending badge) for everyone; Reports behind view_reports; Deals + Leads
 * behind view_leads; Analytics behind view_analytics; Catalog behind
 * view_catalog; Team behind manage_agents; Settings behind manage_settings
 * (desktopNavItems puts it just before Profile); Profile for everyone.
 */
fun buildNavItems(can: (String) -> Boolean, humanConvs: Int, pendingOrders: Int): List<NavItem> = buildList {
    add(NavItem(ViewId.Conversations, iconFor(ViewId.Conversations), humanConvs))
    add(NavItem(ViewId.Calls, iconFor(ViewId.Calls)))
    add(NavItem(ViewId.Orders, iconFor(ViewId.Orders), pendingOrders))
    if (can(Perms.VIEW_REPORTS)) add(NavItem(ViewId.Reports, iconFor(ViewId.Reports)))
    if (can(Perms.VIEW_LEADS)) {
        add(NavItem(ViewId.Deals, iconFor(ViewId.Deals)))
        add(NavItem(ViewId.Leads, iconFor(ViewId.Leads)))
    }
    if (can(Perms.VIEW_ANALYTICS)) add(NavItem(ViewId.Overview, iconFor(ViewId.Overview)))
    if (can(Perms.VIEW_CATALOG)) add(NavItem(ViewId.Catalog, iconFor(ViewId.Catalog)))
    if (can(Perms.MANAGE_AGENTS)) add(NavItem(ViewId.Agents, iconFor(ViewId.Agents)))
    if (can(Perms.MANAGE_SETTINGS)) add(NavItem(ViewId.Settings, iconFor(ViewId.Settings)))
    add(NavItem(ViewId.Profile, iconFor(ViewId.Profile)))
}

fun iconFor(v: ViewId): ImageVector = when (v) {
    ViewId.Conversations -> WebIcons.Inbox
    ViewId.Calls -> WebIcons.Calls
    ViewId.Orders -> WebIcons.Orders
    ViewId.Reports -> WebIcons.Reports
    ViewId.Deals -> WebIcons.Deals
    ViewId.Leads -> WebIcons.Leads
    ViewId.Overview -> WebIcons.Analytics
    ViewId.Catalog -> WebIcons.Catalog
    ViewId.Agents -> WebIcons.Team
    ViewId.Settings -> WebIcons.Settings
    ViewId.Profile -> WebIcons.Profile
}

/**
 * The amber chat-bubble mark. The sidebar's is 32dp with 10dp corners and an
 * amber glow; the mobile header's (MobileNav.tsx) is 28dp, 8dp corners, flat.
 */
@Composable
fun NeemaLogo(size: Dp = 32.dp, corner: Dp = 10.dp, glow: Boolean = true) {
    val shape = RoundedCornerShape(corner)
    Box(
        Modifier.size(size)
            .then(if (glow) Modifier.shadow(6.dp, shape, ambientColor = Brand.Amber, spotColor = Brand.Amber) else Modifier)
            .clip(shape).background(Brand.Amber),
        contentAlignment = Alignment.Center,
    ) {
        Icon(WebIcons.Logo, null, tint = Color.White, modifier = Modifier.size(size * 0.5f))
    }
}

/**
 * components/ui/Sidebar.tsx: navy rail, "Neema AI · Admin Portal", the bell,
 * amber active pill with badges, and the account menu in the footer.
 * [collapsed] shows the 60dp icon rail; [onToggleCollapse] null hides the toggle
 * (the phone drawer is always expanded). Sizes are the web's, in dp.
 */
@Composable
fun NeemaSidebar(
    items: List<NavItem>,
    view: ViewId,
    onSelect: (ViewId) -> Unit,
    collapsed: Boolean,
    onToggleCollapse: (() -> Unit)?,
    userName: String,
    userEmail: String,
    userRole: String,
    avatarUrl: String?,
    dark: Boolean,
    onToggleDark: () -> Unit,
    bellCount: Int,
    onBell: () -> Unit,
    onSignOut: () -> Unit,
    modifier: Modifier = Modifier,
    /** The bell's popup is open: the button keeps its highlighted look. */
    bellOpen: Boolean = false,
    /** 208dp docked (the web's width); the phone drawer passes its own. */
    expandedWidth: Dp = 208.dp,
    /** Screenshot tests: start with the account menu open (when the menu's state is not hoisted). */
    initialMenuOpen: Boolean = false,
    /**
     * The account menu's state, hoisted by the shell (which closes it on
     * system back, above the drawer); null keeps it here.
     */
    menuOpen: Boolean? = null,
    onMenuOpenChange: ((Boolean) -> Unit)? = null,
    /** Signing out (waiting for a live call's hang-up): the account button spins, as on the web. */
    signingOut: Boolean = false,
) {
    val width by animateDpAsState(if (collapsed) 60.dp else expandedWidth, label = "sidebar")
    var ownMenuOpen by rememberSaveable { mutableStateOf(initialMenuOpen) }
    val open = menuOpen ?: ownMenuOpen
    val setOpen: (Boolean) -> Unit = { v -> if (onMenuOpenChange != null) onMenuOpenChange(v) else ownMenuOpen = v }
    // Not hoisted: back closes the inline menu here (the rail's popup closes itself).
    if (onMenuOpenChange == null && open && !collapsed) BackHandler { setOpen(false) }

    Column(
        modifier.width(width).fillMaxHeight().background(Brand.Navy),
    ) {
        // ── Header ────────────────────────────────────────────────────────
        if (collapsed) {
            Column(
                Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(6.dp),
            ) {
                NeemaLogo()
                BellButton(bellCount, bellOpen, compact = true, onClick = onBell)
            }
        } else {
            Row(
                Modifier.fillMaxWidth().heightIn(min = 56.dp).padding(horizontal = 10.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                NeemaLogo()
                Column(Modifier.weight(1f).padding(start = 6.dp)) {
                    // The wordmark is a logo: it grows with the font size only to 130%.
                    val mark = 13.sp.scaledAtMost(1.3f)
                    val tag = 10.sp.scaledAtMost(1.3f)
                    Text("Neema AI", color = Brand.TextLight, fontWeight = FontWeight.SemiBold, fontSize = mark, lineHeight = mark * 1.25f, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    // Like the web's (no overflow: hidden), the tag may run into the bell's empty margin rather than be cut.
                    Text("ADMIN PORTAL", color = Brand.TextMuted, fontWeight = FontWeight.Medium, fontSize = tag, lineHeight = tag * 1.4f, letterSpacing = 0.8.sp, maxLines = 1, softWrap = false, overflow = TextOverflow.Visible, modifier = Modifier.padding(top = 2.dp))
                }
                BellButton(bellCount, bellOpen, compact = false, onClick = onBell)
                if (onToggleCollapse != null) NavyIconButton(WebIcons.Collapse, "Collapse sidebar", onToggleCollapse)
            }
        }
        HorizontalDivider(color = Brand.NavyBorder)

        // ── Nav ───────────────────────────────────────────────────────────
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(horizontal = if (collapsed) 6.dp else 8.dp, vertical = 8.dp),
        ) {
            if (collapsed && onToggleCollapse != null) {
                // The web's full-width 36dp "Expand sidebar" button above the items.
                Box(
                    Modifier.fillMaxWidth().padding(bottom = 6.dp).height(48.dp).clip(RoundedCornerShape(10.dp))
                        .clickable(role = Role.Button, onClick = onToggleCollapse),
                    contentAlignment = Alignment.Center,
                ) { Icon(WebIcons.Expand, "Expand sidebar", tint = Brand.TextMuted, modifier = Modifier.size(14.dp)) }
            }
            Column(Modifier.selectableGroup(), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                items.forEach { item -> SidebarItem(item, item.id == view, collapsed) { onSelect(item.id) } }
            }
        }

        // ── Footer: account ───────────────────────────────────────────────
        HorizontalDivider(color = Brand.NavyBorder)
        Column(Modifier.padding(horizontal = if (collapsed) 6.dp else 8.dp, vertical = 8.dp)) {
            val card = @Composable {
                AccountCard(
                    userName, userEmail, userRole, avatarUrl, dark, onToggleDark,
                    onProfile = { setOpen(false); onSelect(ViewId.Profile) },
                    onSettings = { setOpen(false); onSelect(ViewId.Settings) },
                    onSignOut = { setOpen(false); onSignOut() },
                )
            }
            // Expanded: the popup opens above the footer row, as wide as it, 8dp clear.
            AnimatedVisibility(open && !collapsed) { Box(Modifier.padding(bottom = 8.dp)) { card() } }
            // Collapsed rail: it opens to the right (8dp past the button), bottom-aligned with the avatar.
            if (open && collapsed) {
                // Anchored to this padded column's content (x = 6dp on the rail): 6 + 54 = the web's 60dp.
                val dx = with(LocalDensity.current) { 54.dp.roundToPx() }
                Popup(
                    alignment = Alignment.BottomStart, offset = IntOffset(dx, 0),
                    onDismissRequest = { setOpen(false) },
                    properties = PopupProperties(focusable = true),
                ) { Box(Modifier.width(252.dp)) { card() } }
            }
            val chevron by animateFloatAsState(if (open) 180f else 0f, label = "chevron")
            Box {
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                    .background(if (open) Brand.NavyHover else Color.Transparent)
                    .clickable(enabled = !signingOut, role = Role.Button, onClickLabel = if (open) "Close account menu" else "Open account menu") { setOpen(!open) }
                    .clearAndSetSemantics {
                        contentDescription = "Account: ${userName.ifBlank { userEmail }}, ${userRole.ifBlank { "agent" }}"
                        role = Role.Button
                        onClick(if (open) "Close account menu" else "Open account menu") { setOpen(!open); true }
                    }
                    .heightIn(min = 48.dp)
                    .padding(horizontal = if (collapsed) 0.dp else 8.dp, vertical = if (collapsed) 4.dp else 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = if (collapsed) Arrangement.Center else Arrangement.Start,
            ) {
                Box {
                    // The web's light avatar sits on the navy rail in both themes.
                    CompositionLocalProvider(LocalNeemaColors provides LightNeema) {
                        Avatar(userName.ifBlank { "User" }, avatarUrl, size = 32.dp)
                    }
                    // 9dp online dot with a 2dp navy ring.
                    Box(Modifier.align(Alignment.BottomEnd).size(9.dp).clip(CircleShape).background(Brand.Navy).padding(2.dp).clip(CircleShape).background(Brand.Online))
                }
                if (!collapsed) {
                    Column(Modifier.weight(1f).padding(start = 10.dp)) {
                        Text(userName.ifBlank { "—" }, color = Brand.TextLight, fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        // text-transform: capitalize — each word's first letter.
                        Text(
                            userRole.ifBlank { userEmail }.ifBlank { "—" }.split(" ").joinToString(" ") { w -> w.replaceFirstChar { it.uppercase() } },
                            color = Brand.TextMuted, fontSize = 10.sp, lineHeight = 13.sp, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(top = 1.dp),
                        )
                    }
                    Icon(WebIcons.ChevronUp, null, tint = Brand.TextMuted, modifier = Modifier.padding(start = 10.dp).size(14.dp).rotate(chevron))
                }
            }
            // Sidebar.tsx while logging out: navy over the button, a 14dp amber ring spinning.
            if (signingOut) Box(
                Modifier.matchParentSize().clip(RoundedCornerShape(12.dp)).background(Brand.Navy.copy(alpha = 0.85f))
                    .semantics { contentDescription = "Signing out…" },
                contentAlignment = Alignment.Center,
            ) { CircularProgressIndicator(Modifier.size(14.dp), color = Brand.Amber, strokeWidth = 2.dp, trackColor = Color.Transparent) }
            }
        }
    }
}

@Composable
private fun SidebarItem(item: NavItem, active: Boolean, collapsed: Boolean, onClick: () -> Unit) {
    // Navy on the amber pill: the web's white is 2.1:1 there, navy 8.3:1.
    val fg = if (active) Brand.Navy else Brand.TextMuted
    Box(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(RoundedCornerShape(12.dp))
            .background(if (active) Brand.Amber else Color.Transparent)
            .selectable(selected = active, role = Role.Tab, onClick = onClick)
            .semantics(mergeDescendants = true) {
                contentDescription = if (item.badge > 0) "${item.id.label}, ${item.badge} new" else item.id.label
            },
    ) {
        Row(
            Modifier.fillMaxWidth().heightIn(min = 48.dp).padding(horizontal = if (collapsed) 0.dp else 12.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = if (collapsed) Arrangement.Center else Arrangement.Start,
        ) {
            Icon(item.icon, null, tint = fg, modifier = Modifier.size(20.dp))
            if (!collapsed) {
                Spacer(Modifier.width(10.dp))
                Text(
                    item.id.label, color = fg, fontSize = 13.sp,
                    fontWeight = if (active) FontWeight.SemiBold else FontWeight.Medium,
                    modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis,
                )
                if (item.badge > 0) AmberBadge(item.badge, onActive = active)
            }
        }
        if (collapsed && item.badge > 0) {
            Box(Modifier.align(Alignment.TopEnd).padding(4.dp)) { AmberBadge(item.badge, small = true, onNavy = active) }
        }
    }
}

/**
 * The nav count (Sidebar.tsx / MobileNav.tsx): the full number, as the web
 * prints it. 18dp/10sp beside a label; 14dp/8sp on the collapsed rail;
 * [bottomNav] is the phone bar's 14dp/9sp. Navy numerals on amber (the
 * web's white is 2.1:1); on the amber active pill the badge turns navy.
 * The count grows with the font size only to 130%, so it stays a badge.
 */
@Composable
fun AmberBadge(n: Int, onActive: Boolean = false, small: Boolean = false, onNavy: Boolean = false, bottomNav: Boolean = false) {
    val min = if (small || bottomNav) 14.dp else 18.dp
    val onPill = onNavy || onActive
    val size = (if (bottomNav) 9.sp else if (small) 8.sp else 10.sp).scaledAtMost(1.3f)
    Box(
        Modifier.defaultMinSize(minWidth = min, minHeight = min)
            .clip(RoundedCornerShape(50))
            // On the amber pill an amber badge would vanish: navy there.
            .background(if (onPill) Brand.Navy else Brand.Amber)
            .padding(horizontal = if (bottomNav) 3.dp else if (small) 2.dp else 5.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text("$n", color = if (onPill) Brand.Amber else Brand.Navy, fontWeight = FontWeight.Bold, fontSize = size, lineHeight = size)
    }
}

@Composable
private fun NavyIconButton(icon: ImageVector, label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(36.dp).clip(RoundedCornerShape(10.dp)).clickable(role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, label, tint = Brand.TextMuted, modifier = Modifier.size(14.dp)) }
}

/**
 * Notifications.tsx's bell: 36dp (40dp on the collapsed rail), 12dp corners,
 * a sage 16dp glyph that turns moss on a pale tile while the popup is open,
 * and a red count with a white ring sitting just off the top-right corner.
 */
@Composable
private fun BellButton(count: Int, open: Boolean, compact: Boolean, onClick: () -> Unit) {
    Box(Modifier.size(if (compact) 40.dp else 36.dp)) {
        Box(
            Modifier.fillMaxSize().clip(RoundedCornerShape(12.dp))
                .background(if (open) Palette.Leaf else Color.Transparent)
                .clickable(role = Role.Button, onClick = onClick)
                .semantics { contentDescription = if (count > 0) "Notifications, $count unread" else "Notifications" },
            contentAlignment = Alignment.Center,
        ) {
            Icon(WebIcons.Bell, null, tint = if (open) Palette.Moss700 else Palette.Sage400, modifier = Modifier.size(16.dp))
        }
        if (count > 0) {
            val size = 9.sp.scaledAtMost(1.2f)
            Box(
                Modifier.align(Alignment.TopEnd).offset(x = 2.dp, y = (-2).dp)
                    .defaultMinSize(minWidth = 16.dp, minHeight = 16.dp).clip(RoundedCornerShape(50))
                    .background(Palette.Red500).border(2.dp, Brand.Navy, RoundedCornerShape(50))
                    .padding(horizontal = 4.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (count > 9) "9+" else "$count", color = Color.White, fontSize = size, lineHeight = size, fontWeight = FontWeight.Bold,
                    modifier = Modifier.clearAndSetSemantics {},
                )
            }
        }
    }
}

/**
 * The account popup (Sidebar.tsx AccountPopup) — white in both themes, as on
 * the web. Settings is always offered, as there: the page itself decides what
 * someone without manage_settings may do.
 */
@Composable
private fun AccountCard(
    name: String, email: String, role: String, avatarUrl: String?,
    dark: Boolean, onToggleDark: () -> Unit,
    onProfile: () -> Unit, onSettings: () -> Unit, onSignOut: () -> Unit,
) {
    val hairline = Palette.Hairline2
    val shape = RoundedCornerShape(14.dp)
    Column(
        Modifier.fillMaxWidth().shadow(12.dp, shape).clip(shape).background(Color.White)
            .border(1.dp, Palette.Hairline, shape),
    ) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
            CompositionLocalProvider(LocalNeemaColors provides LightNeema) {
                Avatar(name.ifBlank { "User" }, avatarUrl, size = 40.dp)
            }
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(name.ifBlank { "—" }, fontSize = 13.sp, lineHeight = 17.sp, fontWeight = FontWeight.SemiBold, color = Palette.Ink, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(email.ifBlank { "—" }, fontSize = 11.sp, lineHeight = 15.sp, color = Palette.Sage500, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
                Text(
                    role.uppercase(), fontSize = 9.sp, lineHeight = 12.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.72.sp, color = Brand.Moss,
                    modifier = Modifier.padding(top = 6.dp).clip(RoundedCornerShape(50)).background(Palette.Moss50)
                        .border(1.dp, Palette.Moss200, RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 2.dp),
                )
            }
        }
        HorizontalDivider(color = hairline)
        Column(Modifier.padding(6.dp)) {
            MenuRow(WebIcons.Profile, "View Profile", onClick = onProfile)
            MenuRow(WebIcons.Settings, "Settings", onClick = onSettings)
        }
        HorizontalDivider(color = hairline)
        // One switch for TalkBack: the row and its pill toggle together.
        Row(
            Modifier.fillMaxWidth().toggleable(value = dark, role = Role.Switch, onValueChange = { onToggleDark() })
                .heightIn(min = 48.dp).padding(horizontal = 14.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(if (dark) WebIcons.Sun else WebIcons.Moon, null, tint = Palette.Pewter600, modifier = Modifier.size(14.dp))
            Text(if (dark) "Light mode" else "Dark mode", fontSize = 12.sp, fontWeight = FontWeight.Medium, color = Palette.Pewter700, modifier = Modifier.weight(1f).padding(start = 8.dp))
            ThemePill(dark)
        }
        HorizontalDivider(color = hairline)
        Column(Modifier.padding(6.dp)) { MenuRow(WebIcons.Logout, "Sign out", danger = true, onClick = onSignOut) }
    }
}

/** The popup's 32×18 toggle: moss when dark, sage otherwise, a 14dp white knob. Its row is the switch. */
@Composable
private fun ThemePill(on: Boolean) {
    val knob by animateDpAsState(if (on) 14.dp else 2.dp, label = "knob")
    Box(
        Modifier.size(32.dp, 18.dp).clip(RoundedCornerShape(50))
            .background(if (on) Palette.Moss600 else Palette.Sage300),
    ) {
        Box(
            Modifier.padding(start = knob, top = 2.dp).size(14.dp)
                .shadow(1.5.dp, CircleShape).clip(CircleShape).background(Color.White),
        )
    }
}

@Composable
private fun MenuRow(icon: ImageVector, label: String, danger: Boolean = false, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp).clip(RoundedCornerShape(8.dp)).clickable(role = Role.Button, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // red-600 for the destructive row: the web's red-500 is 3.8:1 on white.
        val c = if (danger) Palette.Red600 else Palette.Pewter700
        Icon(icon, null, tint = if (danger) c else Palette.Pewter600, modifier = Modifier.size(14.dp).alpha(if (danger) 1f else 0.65f))
        Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = c, modifier = Modifier.padding(start = 10.dp))
    }
}
