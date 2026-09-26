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
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons
import ke.co.bethanyhouse.neema.core.ui.theme.asFixedSp
import ke.co.bethanyhouse.neema.core.ui.theme.scaledAtMost
import androidx.compose.material3.Icon
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import ke.co.bethanyhouse.neema.core.util.Fmt

// ── Toast (components/ui/Toast.tsx) ─────────────────────────────────────────

/**
 * The web's single toast: a tinted pill with a round ✓ / ! / ✕ badge.
 * Phones show it 96dp up (above the bottom nav, or the keyboard when it is
 * open), full width less 16dp gutters; wider screens pin it top-right
 * (min 288dp, max 384dp). The caller clears it after 3.5 s. TalkBack
 * announces it (a polite live region).
 */
@Composable
fun ToastView(toast: Toast, mobile: Boolean, modifier: Modifier = Modifier) {
    val tones = Neema.tones
    // success and info share the emerald look, as on the web.
    val look = when (toast.type) {
        ToastType.Error -> tones.error
        ToastType.Warning -> tones.warning
        else -> tones.success
    }
    val glyph = when (toast.type) {
        ToastType.Error -> WebIcons.Close
        ToastType.Warning -> WebIcons.Exclamation
        else -> WebIcons.Check
    }
    Row(
        modifier
            .then(if (mobile) Modifier.fillMaxWidth() else Modifier.widthIn(min = 288.dp, max = 384.dp))
            .shadow(8.dp, RoundedCornerShape(12.dp))
            .clip(RoundedCornerShape(12.dp))
            .background(look.bg)
            .border(1.dp, look.border, RoundedCornerShape(12.dp))
            .semantics { liveRegion = LiveRegionMode.Polite }
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(20.dp).clip(CircleShape).background(look.accent), contentAlignment = Alignment.Center) {
            Icon(glyph, null, tint = Color.White, modifier = Modifier.size(12.dp))
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
    val tone = if (offline) Neema.tones.warning else Neema.tones.moss
    Column(
        modifier.fillMaxWidth().background(tone.bg)
            .semantics(mergeDescendants = true) { liveRegion = LiveRegionMode.Polite },
    ) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            // A solid badge: amber while offline, the twin of "Back online"'s moss one.
            Box(Modifier.size(24.dp).clip(CircleShape).background(tone.accent), contentAlignment = Alignment.Center) {
                Icon(
                    if (offline) WebIcons.WifiOff else WebIcons.Check,
                    null, tint = Color.White, modifier = Modifier.size(if (offline) 14.dp else 12.dp),
                )
            }
            Spacer(Modifier.width(10.dp))
            if (offline) {
                Column(Modifier.weight(1f)) {
                    Text("You're offline", color = tone.text, fontSize = 13.sp, lineHeight = 17.sp, fontWeight = FontWeight.SemiBold)
                    Text(
                        "Showing what was last loaded. Check your connection.",
                        color = tone.text, fontSize = 12.sp, lineHeight = 16.sp,
                    )
                }
            } else {
                Text("Back online", color = tone.text, fontSize = 13.sp, lineHeight = 17.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
            }
        }
        HorizontalDivider(color = tone.border)
    }
}

// ── Notification centre (components/ui/Notifications.tsx) ───────────────────

private data class NotifLook(val emoji: String, val bg: Color)

/** META in Notifications.tsx, keyed by [NotificationCenter.kindOf]. */
private fun notifLook(type: String, dark: Boolean): NotifLook {
    val kind = NotificationCenter.kindOf(type)
    return when (kind) {
        "intercept" -> NotifLook("⚡", if (dark) Palette.Amber600.copy(alpha = 0.2f) else Palette.AmberTint)
        "new_message" -> NotifLook("💬", if (dark) Palette.Blue600.copy(alpha = 0.2f) else Palette.Blue50)
        "order" -> NotifLook("📦", if (dark) Palette.Green600.copy(alpha = 0.2f) else Palette.Green50)
        // META's colours are never applied on the web: ⇄ is plain page text.
        "transfer" -> NotifLook("⇄", if (dark) Palette.Violet600.copy(alpha = 0.2f) else Palette.Violet50)
        else -> NotifLook("ℹ️", if (dark) Palette.Slate500.copy(alpha = 0.2f) else Palette.Slate50)
    }
}

private data class PanelColors(
    val bg: Color, val divider: Color, val rowDivider: Color, val title: Color, val readTitle: Color,
    val body: Color, val faint: Color, val unreadBg: Color, val dismiss: Color, val emptyTile: Color, val action: Color,
)

/**
 * Notifications.tsx's colours, with its faintest greys (`#b5c9a8` times,
 * `#dde4d6` ✕ — 1.8:1 and 1.3:1 on white) lifted to the sage that clears
 * 4.3:1, so the time and the dismiss button can actually be read.
 */
private fun panelColors(dark: Boolean) = if (dark) PanelColors(
    bg = Palette.Prussian900, divider = Palette.Prussian800, rowDivider = Palette.Prussian850,
    title = Palette.Willow50, readTitle = Palette.Sage400, body = Palette.Sage400,
    faint = Palette.NightMuted, unreadBg = Palette.Willow500.copy(alpha = 0.08f), dismiss = Palette.NightMuted,
    emptyTile = Palette.Indigo900, action = Palette.Willow500,
) else PanelColors(
    bg = Color.White, divider = Palette.Hairline2, rowDivider = Palette.Mist,
    title = Palette.Ink, readTitle = Palette.Sage500, body = Palette.Sage500,
    faint = Palette.Sage500, unreadBg = Palette.SproutTint, dismiss = Palette.Sage500, emptyTile = Palette.Mist,
    action = Palette.Moss700,
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
            Modifier.fillMaxWidth().heightIn(min = 48.dp).padding(start = 16.dp, end = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("Notifications", fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.title, modifier = Modifier.semantics { heading() })
            if (unread > 0) {
                Spacer(Modifier.width(8.dp))
                val badge = 10.sp.scaledAtMost(1.3f)
                Text(
                    "$unread", color = Color.White, fontSize = badge, fontWeight = FontWeight.Bold,
                    lineHeight = badge,
                    modifier = Modifier.clip(RoundedCornerShape(50)).background(Palette.Red500).padding(horizontal = 6.dp, vertical = 2.dp)
                        .semantics { contentDescription = "$unread unread" },
                )
            }
            Spacer(Modifier.weight(1f))
            if (unread > 0) Text(
                "Mark all read", color = c.action, fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(role = Role.Button, onClick = onMarkAllRead)
                    .heightIn(min = 48.dp).wrapContentHeight(Alignment.CenterVertically).padding(horizontal = 8.dp),
            )
        }
        HorizontalDivider(color = c.divider)
        if (items.isEmpty()) {
            Column(
                Modifier.fillMaxWidth().padding(vertical = 48.dp, horizontal = 16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Box(Modifier.size(48.dp).clip(RoundedCornerShape(16.dp)).background(c.emptyTile), contentAlignment = Alignment.Center) {
                    Text("🔔", fontSize = 24.dp.asFixedSp())
                }
                Spacer(Modifier.height(12.dp))
                Text("All caught up", fontSize = 14.sp, fontWeight = FontWeight.Medium, color = c.title, textAlign = TextAlign.Center)
                Spacer(Modifier.height(2.dp))
                Text("No new notifications", fontSize = 12.sp, color = c.faint, textAlign = TextAlign.Center)
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
                            ) { Text(look.emoji, fontSize = 14.dp.asFixedSp(), color = c.title) }
                            Spacer(Modifier.width(12.dp))
                            Column(Modifier.weight(1f)) {
                                Row(verticalAlignment = Alignment.Top) {
                                    Text(
                                        n.title, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, lineHeight = 16.sp,
                                        color = if (!n.read) c.title else c.readTitle, modifier = Modifier.weight(1f),
                                    )
                                    Spacer(Modifier.width(8.dp))
                                    Text(
                                        Fmt.timeAgo(java.time.Instant.ofEpochMilli(n.at).toString(), now),
                                        fontSize = 10.sp, color = c.faint, maxLines = 1, modifier = Modifier.padding(top = 2.dp),
                                    )
                                }
                                if (n.body.isNotBlank()) Text(
                                    n.body, fontSize = 11.sp, lineHeight = 16.sp, color = c.body,
                                    maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp),
                                )
                            }
                            Box(
                                Modifier.size(48.dp).clip(CircleShape)
                                    .clickable(role = Role.Button, onClickLabel = "Dismiss") { onDismissItem(n.id) },
                                contentAlignment = Alignment.Center,
                            ) { Icon(WebIcons.Close, "Dismiss notification", tint = c.dismiss, modifier = Modifier.size(12.dp)) }
                        }
                        HorizontalDivider(color = c.rowDivider)
                    }
                }
            }
            HorizontalDivider(color = c.divider)
            Row(
                Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "${items.size} notification${if (items.size != 1) "s" else ""}",
                    fontSize = 11.sp, color = c.faint, modifier = Modifier.weight(1f),
                )
                Text(
                    "Clear all", fontSize = 11.sp, color = c.faint, fontWeight = FontWeight.Medium,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(role = Role.Button, onClick = onClear)
                        .heightIn(min = 48.dp).wrapContentHeight(Alignment.CenterVertically).padding(horizontal = 8.dp),
                )
            }
        }
    }
}
