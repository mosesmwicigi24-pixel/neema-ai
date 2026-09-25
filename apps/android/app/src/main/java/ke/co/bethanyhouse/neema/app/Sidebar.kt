package ke.co.bethanyhouse.neema.app

import androidx.compose.animation.AnimatedVisibility
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
import ke.co.bethanyhouse.neema.core.ui.theme.Brand
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons

data class NavItem(val id: ViewId, val icon: ImageVector, val badge: Int = 0)

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

/** The amber chat-bubble mark (sidebar header, mobile header, login). */
@Composable
fun NeemaLogo(size: Dp = 32.dp) {
    Box(
        Modifier.size(size).shadow(6.dp, RoundedCornerShape(size * 0.31f), ambientColor = Brand.Amber, spotColor = Brand.Amber)
            .clip(RoundedCornerShape(size * 0.31f)).background(Brand.Amber),
        contentAlignment = Alignment.Center,
    ) {
        Icon(WebIcons.Logo, null, tint = Color.White, modifier = Modifier.size(size * 0.5f))
    }
}

/**
 * components/ui/Sidebar.tsx: navy rail, "Neema AI · Admin Portal", the bell,
 * amber active pill with badges, and the account menu in the footer.
 * [collapsed] shows the 60dp icon rail; [onToggleCollapse] null hides the toggle
 * (the phone drawer is always expanded).
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
    canSettings: Boolean,
    bellCount: Int,
    onBell: () -> Unit,
    onSignOut: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val width by animateDpAsState(if (collapsed) 60.dp else 232.dp, label = "sidebar")
    var menuOpen by remember { mutableStateOf(false) }

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
                BellButton(bellCount, onBell)
            }
        } else {
            Row(
                Modifier.fillMaxWidth().height(60.dp).padding(horizontal = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                NeemaLogo()
                Column(Modifier.weight(1f).padding(start = 10.dp)) {
                    Text("Neema AI", color = Brand.TextLight, fontWeight = FontWeight.SemiBold, fontSize = 14.sp, lineHeight = 15.sp)
                    Text("ADMIN PORTAL", color = Brand.TextMuted, fontWeight = FontWeight.Medium, fontSize = 10.sp, letterSpacing = 0.8.sp)
                }
                BellButton(bellCount, onBell)
                if (onToggleCollapse != null) NavyIconButton(WebIcons.Collapse, "Collapse sidebar", onToggleCollapse)
            }
        }
        HorizontalDivider(color = Brand.NavyBorder)

        // ── Nav ───────────────────────────────────────────────────────────
        Column(
            Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(8.dp),
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            if (collapsed && onToggleCollapse != null) {
                Box(Modifier.fillMaxWidth().padding(bottom = 6.dp), contentAlignment = Alignment.Center) {
                    NavyIconButton(WebIcons.Expand, "Expand sidebar", onToggleCollapse)
                }
            }
            items.forEach { item -> SidebarItem(item, item.id == view, collapsed) { onSelect(item.id) } }
        }

        // ── Footer: account ───────────────────────────────────────────────
        HorizontalDivider(color = Brand.NavyBorder)
        Column(Modifier.padding(8.dp)) {
            AnimatedVisibility(menuOpen && !collapsed) {
                AccountCard(
                    userName, userEmail, userRole, avatarUrl, dark, onToggleDark, canSettings,
                    onProfile = { menuOpen = false; onSelect(ViewId.Profile) },
                    onSettings = { menuOpen = false; onSelect(ViewId.Settings) },
                    onSignOut = { menuOpen = false; onSignOut() },
                )
            }
            val chevron by animateFloatAsState(if (menuOpen) 180f else 0f, label = "chevron")
            Row(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp))
                    .background(if (menuOpen) Brand.NavyHover else Color.Transparent)
                    .clickable { if (collapsed) onSelect(ViewId.Profile) else menuOpen = !menuOpen }
                    .padding(horizontal = if (collapsed) 0.dp else 8.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = if (collapsed) Arrangement.Center else Arrangement.Start,
            ) {
                Box {
                    Avatar(userName.ifBlank { "User" }, avatarUrl, size = 32.dp)
                    Box(Modifier.align(Alignment.BottomEnd).size(10.dp).clip(CircleShape).background(Brand.Navy).padding(2.dp).clip(CircleShape).background(Brand.Online))
                }
                if (!collapsed) {
                    Column(Modifier.weight(1f).padding(start = 10.dp)) {
                        Text(userName.ifBlank { "—" }, color = Brand.TextLight, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(userRole.replaceFirstChar { it.uppercase() }.ifBlank { userEmail }, color = Brand.TextMuted, fontSize = 11.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Icon(WebIcons.ChevronUp, null, tint = Brand.TextMuted, modifier = Modifier.size(16.dp).rotate(chevron))
                }
            }
        }
    }
}

@Composable
private fun SidebarItem(item: NavItem, active: Boolean, collapsed: Boolean, onClick: () -> Unit) {
    val fg = if (active) Color.White else Brand.TextMuted
    Box(
        Modifier.fillMaxWidth().height(44.dp).clip(RoundedCornerShape(12.dp))
            .background(if (active) Brand.Amber else Color.Transparent)
            .clickable(onClick = onClick),
    ) {
        Row(
            Modifier.fillMaxSize().padding(horizontal = if (collapsed) 0.dp else 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = if (collapsed) Arrangement.Center else Arrangement.Start,
        ) {
            Icon(item.icon, item.id.label, tint = fg, modifier = Modifier.size(20.dp))
            if (!collapsed) {
                Spacer(Modifier.width(12.dp))
                Text(
                    item.id.label, color = fg, fontSize = 14.sp,
                    fontWeight = if (active) FontWeight.SemiBold else FontWeight.Medium,
                    modifier = Modifier.weight(1f), maxLines = 1,
                )
                if (item.badge > 0) AmberBadge(item.badge, onActive = active)
            }
        }
        if (collapsed && item.badge > 0) {
            Box(Modifier.align(Alignment.TopEnd).padding(4.dp)) { AmberBadge(item.badge, small = true, onNavy = active) }
        }
    }
}

@Composable
fun AmberBadge(n: Int, onActive: Boolean = false, small: Boolean = false, onNavy: Boolean = false) {
    Box(
        Modifier.defaultMinSize(minWidth = if (small) 14.dp else 18.dp, minHeight = if (small) 14.dp else 18.dp)
            .clip(RoundedCornerShape(50))
            // On the amber pill an amber badge would vanish: navy when collapsed, translucent white when expanded.
            .background(if (onNavy) Brand.Navy else if (onActive) Color.White.copy(alpha = 0.3f) else Brand.Amber)
            .padding(horizontal = 4.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(if (n > 99) "99+" else "$n", color = Color.White, fontSize = if (small) 8.sp else 10.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun NavyIconButton(icon: ImageVector, label: String, onClick: () -> Unit) {
    Box(
        Modifier.size(32.dp).clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, label, tint = Brand.TextMuted, modifier = Modifier.size(16.dp)) }
}

@Composable
private fun BellButton(count: Int, onClick: () -> Unit) {
    Box(
        Modifier.size(34.dp).clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Icon(WebIcons.Bell, "Notifications", tint = Brand.TextMuted, modifier = Modifier.size(18.dp))
        if (count > 0) {
            Box(
                Modifier.align(Alignment.TopEnd).padding(top = 3.dp, end = 3.dp)
                    .defaultMinSize(minWidth = 15.dp, minHeight = 15.dp).clip(RoundedCornerShape(50))
                    .background(Color(0xFFEF4444)).padding(horizontal = 3.dp),
                contentAlignment = Alignment.Center,
            ) { Text(if (count > 9) "9+" else "$count", color = Color.White, fontSize = 9.sp, fontWeight = FontWeight.Bold) }
        }
    }
}

/** The account popup (Sidebar.tsx AccountPopup), shown inline above the footer. */
@Composable
private fun AccountCard(
    name: String, email: String, role: String, avatarUrl: String?,
    dark: Boolean, onToggleDark: () -> Unit, canSettings: Boolean,
    onProfile: () -> Unit, onSettings: () -> Unit, onSignOut: () -> Unit,
) {
    val hairline = Color(0xFFEDF0EA)
    Column(
        Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(RoundedCornerShape(14.dp)).background(Color.White)
            .border(1.dp, Color(0xFFE8EBE3), RoundedCornerShape(14.dp)),
    ) {
        Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Avatar(name.ifBlank { "User" }, avatarUrl, size = 38.dp)
            Column(Modifier.weight(1f).padding(start = 12.dp)) {
                Text(name.ifBlank { "—" }, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF1C2917), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(email.ifBlank { "—" }, fontSize = 11.sp, color = Color(0xFF8A9E80), maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (role.isNotBlank()) Text(
                    role.uppercase(), fontSize = 9.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.7.sp, color = Brand.Moss,
                    modifier = Modifier.padding(top = 6.dp).clip(RoundedCornerShape(50)).background(Color(0xFFF0F9EC))
                        .border(1.dp, Color(0xFFC5E7B1), RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 2.dp),
                )
            }
        }
        HorizontalDivider(color = hairline)
        Column(Modifier.padding(6.dp)) {
            MenuRow(WebIcons.Profile, "View Profile", onClick = onProfile)
            if (canSettings) MenuRow(WebIcons.Settings, "Settings", onClick = onSettings)
        }
        HorizontalDivider(color = hairline)
        Row(
            Modifier.fillMaxWidth().clickable(onClick = onToggleDark).padding(horizontal = 14.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(if (dark) WebIcons.Sun else WebIcons.Moon, null, tint = Color(0xFFA0AEC0), modifier = Modifier.size(15.dp))
            Text(if (dark) "Light mode" else "Dark mode", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = Color(0xFF4A5568), modifier = Modifier.weight(1f).padding(start = 8.dp))
            Switch(
                checked = dark, onCheckedChange = { onToggleDark() },
                colors = SwitchDefaults.colors(checkedTrackColor = Brand.Moss, uncheckedTrackColor = Color(0xFFDDE4D6), uncheckedBorderColor = Color.Transparent, uncheckedThumbColor = Color.White),
                modifier = Modifier.height(24.dp),
            )
        }
        HorizontalDivider(color = hairline)
        Column(Modifier.padding(6.dp)) { MenuRow(WebIcons.Logout, "Sign out", danger = true, onClick = onSignOut) }
    }
}

@Composable
private fun MenuRow(icon: ImageVector, label: String, danger: Boolean = false, onClick: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).clickable(onClick = onClick).padding(horizontal = 10.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val c = if (danger) Color(0xFFEF4444) else Color(0xFF4A5568)
        Icon(icon, null, tint = if (danger) c else Color(0xFF718096), modifier = Modifier.size(15.dp))
        Text(label, fontSize = 13.sp, fontWeight = FontWeight.Medium, color = c, modifier = Modifier.padding(start = 10.dp))
    }
}
