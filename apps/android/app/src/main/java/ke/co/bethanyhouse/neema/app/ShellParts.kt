package ke.co.bethanyhouse.neema.app

import ke.co.bethanyhouse.neema.core.util.AppClock

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.notify.AppNotification
import ke.co.bethanyhouse.neema.core.notify.NotificationCenter
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt

// ── Toast (components/ui/Toast.tsx) ─────────────────────────────────────────

private data class ToastLook(val bg: Color, val border: Color, val text: Color, val dot: Color, val icon: String)

private fun toastLook(type: ToastType, dark: Boolean): ToastLook = when (type) {
    ToastType.Error -> if (dark) ToastLook(Color(0xCC450A0A), Color(0xFF991B1B), Color(0xFFFCA5A5), Color(0xFFEF4444), "✕")
    else ToastLook(Color(0xFFFEF2F2), Color(0xFFFECACA), Color(0xFFB91C1C), Color(0xFFEF4444), "✕")
    ToastType.Warning -> if (dark) ToastLook(Color(0xCC451A03), Color(0xFF92400E), Color(0xFFFCD34D), Color(0xFFF59E0B), "!")
    else ToastLook(Color(0xFFFFFBEB), Color(0xFFFDE68A), Color(0xFFB45309), Color(0xFFF59E0B), "!")
    // success and info share the emerald look, as on the web.
    else -> if (dark) ToastLook(Color(0xCC022C22), Color(0xFF065F46), Color(0xFF6EE7B7), Color(0xFF10B981), "✓")
    else ToastLook(Color(0xFFECFDF5), Color(0xFFA7F3D0), Color(0xFF047857), Color(0xFF10B981), "✓")
}

/**
 * The web's single toast: a tinted pill with a round ✓ / ! / ✕ badge.
 * Phones show it 96dp up (above the bottom nav), full width less 16dp gutters; wider
 * screens pin it top-right (min 288dp, max 384dp). The caller clears it
 * after 3.5 s.
 */
@Composable
fun ToastView(toast: Toast, mobile: Boolean, modifier: Modifier = Modifier) {
    val look = toastLook(toast.type, Neema.colors.isDark)
    Row(
        modifier
            .then(if (mobile) Modifier.fillMaxWidth() else Modifier.widthIn(min = 288.dp, max = 384.dp))
            .shadow(8.dp, RoundedCornerShape(12.dp))
            .clip(RoundedCornerShape(12.dp))
            .background(look.bg)
            .border(1.dp, look.border, RoundedCornerShape(12.dp))
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(20.dp).clip(CircleShape).background(look.dot), contentAlignment = Alignment.Center) {
            Text(look.icon, color = Color.White, fontSize = 12.sp, lineHeight = 12.sp, fontWeight = FontWeight.Bold)
        }
        Spacer(Modifier.width(8.dp))
        Text(toast.message, color = look.text, fontSize = 14.sp, fontWeight = FontWeight.Medium, lineHeight = 20.sp)
    }
}

// ── Connectivity banner (app-only: the web leans on the browser's own) ──────

/**
 * A slim bar across the top of the content while the device has no network:
 * whatever is on screen stays (it's what was last loaded), and the bar says
 * so. When the network returns it turns moss, says "Back online" and folds
 * away after 2.5 s.
 */
@Composable
fun ConnectivityBanner(online: Boolean, backOnline: Boolean, modifier: Modifier = Modifier) {
    AnimatedVisibility(
        visible = !online || backOnline, modifier = modifier,
        enter = expandVertically() + fadeIn(), exit = shrinkVertically() + fadeOut(),
    ) { ConnectivityBar(offline = !online) }
}

/** True for 2.5 s after [online] turns true again (not on first composition). */
@Composable
fun rememberBackOnline(online: Boolean): Boolean {
    var wasOffline by remember { mutableStateOf(!online) }
    var backOnline by remember { mutableStateOf(false) }
    LaunchedEffect(online) {
        if (!online) { wasOffline = true; backOnline = false }
        else if (wasOffline) {
            wasOffline = false; backOnline = true
            kotlinx.coroutines.delay(2_500); backOnline = false
        }
    }
    return backOnline
}

/** The bar itself: amber while offline, moss once back. */
@Composable
internal fun ConnectivityBar(offline: Boolean, modifier: Modifier = Modifier) {
    val dark = Neema.colors.isDark
    val bg: Color; val line: Color; val title: Color; val body: Color; val iconBg: Color; val iconTint: Color
    if (offline) {
        bg = if (dark) Color(0xFF2A1805) else Color(0xFFFFFBEB)
        line = if (dark) Color(0xFF78350F) else Color(0xFFFDE68A)
        title = if (dark) Color(0xFFFCD34D) else Color(0xFF92400E)
        body = if (dark) Color(0xFFD6B26A) else Color(0xFFB45309)
        // A solid amber badge, the twin of "Back online"'s moss one.
        iconBg = Color(0xFFF59E0B)
        iconTint = Color.White
    } else {
        bg = if (dark) Color(0xFF12230B) else Color(0xFFF1F8EB)
        line = if (dark) Color(0xFF2F5A1A) else Color(0xFFCDE5BB)
        title = if (dark) Color(0xFF9CCD65) else Color(0xFF3F7A22)
        body = title
        iconBg = Color(0xFF589B31)
        iconTint = Color.White
    }
    Column(modifier.fillMaxWidth().background(bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(24.dp).clip(CircleShape).background(iconBg), contentAlignment = Alignment.Center) {
                androidx.compose.material3.Icon(
                    if (offline) ke.co.bethanyhouse.neema.core.ui.theme.WebIcons.WifiOff else ke.co.bethanyhouse.neema.core.ui.theme.WebIcons.Check,
                    null, tint = iconTint, modifier = Modifier.size(if (offline) 14.dp else 12.dp),
                )
            }
            Spacer(Modifier.width(10.dp))
            if (offline) {
                Column(Modifier.weight(1f)) {
                    Text("You're offline", color = title, fontSize = 13.sp, lineHeight = 17.sp, fontWeight = FontWeight.SemiBold)
                    Text(
                        "Showing what was last loaded. Check your connection.",
                        color = body, fontSize = 12.sp, lineHeight = 16.sp,
                    )
                }
            } else {
                Text("Back online", color = title, fontSize = 13.sp, lineHeight = 17.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            }
        }
        HorizontalDivider(color = line)
    }
}

// ── Notification centre (components/ui/Notifications.tsx) ───────────────────

private data class NotifLook(val emoji: String, val bg: Color)

/** META in Notifications.tsx, keyed by [NotificationCenter.kindOf]. */
private fun notifLook(type: String, dark: Boolean): NotifLook {
    val kind = NotificationCenter.kindOf(type)
    return when (kind) {
        "intercept" -> NotifLook("⚡", if (dark) Color(0x33D97706) else Color(0xFFFEF9EC))
        "new_message" -> NotifLook("💬", if (dark) Color(0x332563EB) else Color(0xFFEFF6FF))
        "order" -> NotifLook("📦", if (dark) Color(0x3316A34A) else Color(0xFFF0FDF4))
        // META's colours are never applied on the web: ⇄ is plain page text.
        "transfer" -> NotifLook("⇄", if (dark) Color(0x337C3AED) else Color(0xFFF5F3FF))
        else -> NotifLook("ℹ️", if (dark) Color(0x3364748B) else Color(0xFFF8FAFC))
    }
}

private data class PanelColors(
    val bg: Color, val divider: Color, val rowDivider: Color, val title: Color, val readTitle: Color,
    val body: Color, val faint: Color, val unreadBg: Color, val dismiss: Color, val emptyTile: Color,
)

private fun panelColors(dark: Boolean) = if (dark) PanelColors(
    bg = Color(0xFF0A1229), divider = Color(0xFF152451), rowDivider = Color(0xFF0F1A38),
    title = Color(0xFFF3F9EC), readTitle = Color(0xFF8A9E80), body = Color(0xFF8A9E80),
    faint = Color(0xFF5E7390), unreadBg = Color(0x1484C13E), dismiss = Color(0xFF3B4A6B), emptyTile = Color(0xFF0F1424),
) else PanelColors(
    bg = Color.White, divider = Color(0xFFEDF0EA), rowDivider = Color(0xFFF5F7F2),
    title = Color(0xFF1C2917), readTitle = Color(0xFF6B7E64), body = Color(0xFF8A9E80),
    faint = Color(0xFFB5C9A8), unreadBg = Color(0xFFFAFEF7), dismiss = Color(0xFFDDE4D6), emptyTile = Color(0xFFF5F7F2),
)

/**
 * The bell's panel: header with the unread count and "Mark all read", the
 * list (unread rows tinted, time top-right, a ✕ per row), the empty state,
 * and a footer with the count and "Clear all". Rendered in a bottom sheet
 * on phones and as the web's 316dp popup beside the sidebar on tablets.
 */
@Composable
fun NotificationsPanel(
    items: List<AppNotification>,
    onOpen: (AppNotification) -> Unit,
    onMarkAllRead: () -> Unit,
    onDismissItem: (String) -> Unit,
    onClear: () -> Unit,
    modifier: Modifier = Modifier,
    listMaxHeight: Dp = 360.dp,
    now: Long = AppClock.now(),
) {
    val dark = Neema.colors.isDark
    val c = panelColors(dark)
    val unread = items.count { !it.read }
    Column(modifier.background(c.bg)) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Notifications", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.title)
            if (unread > 0) {
                Spacer(Modifier.width(8.dp))
                Text(
                    "$unread", color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold,
                    lineHeight = 12.sp,
                    modifier = Modifier.clip(RoundedCornerShape(50)).background(Color(0xFFEF4444)).padding(horizontal = 6.dp, vertical = 2.dp),
                )
            }
            Spacer(Modifier.weight(1f))
            if (unread > 0) Text(
                "Mark all read", color = if (dark) Color(0xFF84C13E) else Color(0xFF589B31), fontSize = 10.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClick = onMarkAllRead).padding(horizontal = 6.dp, vertical = 4.dp),
            )
        }
        HorizontalDivider(color = c.divider)
        if (items.isEmpty()) {
            Column(
                Modifier.fillMaxWidth().padding(vertical = 48.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(Modifier.size(48.dp).clip(RoundedCornerShape(16.dp)).background(c.emptyTile), contentAlignment = Alignment.Center) {
                    Text("🔔", fontSize = 24.sp)
                }
                Spacer(Modifier.height(12.dp))
                Text("All caught up", fontSize = 14.sp, fontWeight = FontWeight.Medium, color = c.title)
                Spacer(Modifier.height(2.dp))
                Text("No new notifications", fontSize = 12.sp, color = c.faint)
            }
        } else {
            LazyColumn(Modifier.heightIn(max = listMaxHeight)) {
                items(items, key = { it.id }) { n ->
                    val look = notifLook(n.type, dark)
                    Column {
                        Row(
                            Modifier.fillMaxWidth()
                                .background(if (!n.read) c.unreadBg else Color.Transparent)
                                .clickable { onOpen(n) }
                                .padding(start = 16.dp, end = 4.dp, top = 12.dp, bottom = 12.dp),
                        ) {
                            Box(
                                Modifier.padding(top = 2.dp).size(32.dp).clip(RoundedCornerShape(12.dp)).background(look.bg),
                                contentAlignment = Alignment.Center,
                            ) { Text(look.emoji, fontSize = 14.sp, color = c.title) }
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Row(verticalAlignment = Alignment.Top) {
                                    Text(
                                        n.title, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, lineHeight = 15.sp,
                                        color = if (!n.read) c.title else c.readTitle, modifier = Modifier.weight(1f),
                                    )
                                    Spacer(Modifier.width(8.dp))
                                    Text(
                                        Fmt.timeAgo(java.time.Instant.ofEpochMilli(n.at).toString(), now),
                                        fontSize = 10.sp, color = c.faint, modifier = Modifier.padding(top = 2.dp),
                                    )
                                }
                                if (n.body.isNotBlank()) Text(
                                    n.body, fontSize = 11.sp, lineHeight = 18.sp, color = c.body,
                                    maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp),
                                )
                            }
                            Box(
                                Modifier.size(32.dp).clip(CircleShape).clickable { onDismissItem(n.id) },
                                contentAlignment = Alignment.Center,
                            ) { Text("✕", fontSize = 11.sp, color = c.dismiss, textAlign = TextAlign.Center) }
                        }
                        HorizontalDivider(color = c.rowDivider)
                    }
                }
            }
            HorizontalDivider(color = c.divider)
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "${items.size} notification${if (items.size != 1) "s" else ""}",
                    fontSize = 10.sp, color = c.faint, modifier = Modifier.weight(1f),
                )
                Text(
                    "Clear all", fontSize = 10.sp, color = c.faint,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClick = onClear).padding(horizontal = 6.dp, vertical = 6.dp),
                )
            }
        }
    }
}
