package ke.co.bethanyhouse.neema.core.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.text.TextAutoSize
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material3.*
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.layout
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.SubcomposeAsyncImage
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaFont
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.ui.theme.asFixedSp
import ke.co.bethanyhouse.neema.core.ui.theme.TabularNums
import ke.co.bethanyhouse.neema.core.ui.theme.contentOn
import ke.co.bethanyhouse.neema.core.ui.theme.WebIcons
import ke.co.bethanyhouse.neema.core.util.Fmt

/** Stable hue per name, for initials avatars. */
fun avatarColor(seed: String?): Color {
    val palette = listOf(
        0xFF589B31, 0xFF2A48A2, 0xFF3D528F, 0xFFC0392B, 0xFF0E7490,
        0xFF9333EA, 0xFFD97706, 0xFF0F766E, 0xFFBE185D, 0xFF4F7425,
    )
    val h = (seed ?: "?").fold(0) { a, ch -> (a * 31 + ch.code) and 0x7fffffff }
    return Color(palette[h % palette.size])
}

/**
 * True when a "name" is really a phone number, a Meta id or a website-chat
 * visitor (an unnamed contact shown as "+254 712 345 678" / "Messenger ID
 * 2589…" / "Website visitor", or the raw "web_3f9a…" id): its initials would
 * read "+7", "MI" or "WV", so the avatar shows a person glyph instead.
 */
fun isPhoneLike(name: String?): Boolean {
    val n = name?.trim().orEmpty()
    if (n.isEmpty()) return false
    if (n.startsWith("Messenger ID", ignoreCase = true)) return true
    if (n.equals(WEBSITE_VISITOR, ignoreCase = true) || n.startsWith("web_")) return true
    val digits = n.filterNot { it == ' ' || it == '+' || it == '-' || it == '(' || it == ')' || it == '.' }
    return digits.isNotEmpty() && digits.all { it.isDigit() }
}

/** What Fmt.formatPhone calls a website-chat visitor (ids "web_…"). */
private const val WEBSITE_VISITOR = "Website visitor"

/**
 * components/ui/Avatar.tsx: one neutral stone-green disc with dark-green
 * initials (a Prussian-night twin in dark mode), the photo when there is one
 * (falling back to the disc if it fails to load), and a person glyph for an
 * unnamed contact whose "name" is only a phone number.
 */
@Composable
fun Avatar(name: String?, url: String? = null, size: Dp = 40.dp, modifier: Modifier = Modifier) {
    val dark = Neema.colors.isDark
    val bg = if (dark) Palette.Indigo900 else Palette.AvatarDisc
    val fg = if (dark) Palette.Willow300 else Palette.AvatarInk
    val ring = if (dark) Palette.Prussian700 else Palette.AvatarRing
    val initialsBox = @Composable {
        Box(
            Modifier.size(size).clip(CircleShape).background(bg).border(1.dp, ring, CircleShape),
            contentAlignment = Alignment.Center,
        ) {
            if (name.isNullOrBlank() || isPhoneLike(name)) {
                Icon(WebIcons.Profile, contentDescription = null, tint = fg, modifier = Modifier.size(size * 0.5f))
            } else {
                // Sized to the disc, not the font scale: at 200% text "MM" would overflow it.
                val initials = (size * 0.36f).asFixedSp()
                Text(
                    Fmt.initials(name), color = fg, fontWeight = FontWeight.Bold,
                    fontSize = initials, letterSpacing = initials * 0.02f, maxLines = 1,
                )
            }
        }
    }
    Box(modifier.size(size)) {
        if (url.isNullOrBlank()) initialsBox()
        else SubcomposeAsyncImage(
            model = url, contentDescription = name, contentScale = ContentScale.Crop,
            modifier = Modifier.size(size).clip(CircleShape),
            loading = { initialsBox() }, error = { initialsBox() },
        )
    }
}

data class ChannelStyle(val label: String, val color: Color)

fun channelStyle(channel: String?): ChannelStyle = when (channel?.lowercase()) {
    "messenger" -> ChannelStyle("Messenger", ChannelColors.Messenger)
    "facebook" -> ChannelStyle("Facebook", ChannelColors.Facebook)
    "instagram" -> ChannelStyle("Instagram", ChannelColors.Instagram)
    "tiktok" -> ChannelStyle("TikTok", ChannelColors.TikTok)
    "email" -> ChannelStyle("Email", ChannelColors.Email)
    "sms" -> ChannelStyle("SMS", ChannelColors.Sms)
    "web" -> ChannelStyle("Web chat", ChannelColors.Web)
    else -> ChannelStyle("WhatsApp", ChannelColors.WhatsApp)
}

val ALL_CHANNELS = listOf("whatsapp", "messenger", "facebook", "instagram", "tiktok", "email", "sms")

/** Small coloured dot + label, the channel chip used across lists. */
@Composable
fun ChannelChip(channel: String?, modifier: Modifier = Modifier, showLabel: Boolean = true) {
    val s = channelStyle(channel)
    Row(
        modifier.clip(RoundedCornerShape(50)).background(s.color.copy(alpha = 0.12f)).padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(7.dp).clip(CircleShape).background(s.color))
        if (showLabel) {
            Spacer(Modifier.width(5.dp))
            Text(s.label, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = s.color)
        }
    }
}

/** Rounded status pill; [color] drives both text and tint. Filled, the text is white or ink, whichever reads on [color]. */
@Composable
fun Pill(text: String, color: Color, modifier: Modifier = Modifier, filled: Boolean = false) {
    Text(
        text,
        modifier = modifier.clip(RoundedCornerShape(50))
            .background(if (filled) color else color.copy(alpha = 0.13f))
            .padding(horizontal = 8.dp, vertical = 3.dp),
        color = if (filled) contentOn(color) else color,
        fontSize = 11.sp, fontWeight = FontWeight.SemiBold, maxLines = 1,
    )
}

@Composable
fun statusColor(status: String?): Color {
    val c = Neema.colors
    return when (status?.lowercase()) {
        "delivered", "paid", "done", "completed", "won", "answered", "active", "open_window", "confirmed" -> c.green
        "cancelled", "canceled", "failed", "lost", "missed", "declined", "error" -> c.red
        "pending", "processing", "ringing", "partial", "awaiting" -> Palette.Amber600
        "human" -> c.blue
        "paused" -> Palette.Amber600
        else -> c.muted
    }
}

@Composable
fun Loading(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(
            strokeWidth = 2.5.dp,
            modifier = Modifier.size(32.dp).semantics { contentDescription = "Loading" },
        )
    }
}

@Composable
fun EmptyState(
    title: String,
    subtitle: String? = null,
    icon: ImageVector = Icons.Outlined.Inbox,
    modifier: Modifier = Modifier,
    action: (@Composable () -> Unit)? = null,
) {
    Column(
        modifier.fillMaxWidth().padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Icon(icon, null, tint = Neema.colors.muted, modifier = Modifier.size(40.dp))
        Spacer(Modifier.height(10.dp))
        Text(title, style = MaterialTheme.typography.titleSmall, textAlign = TextAlign.Center)
        if (subtitle != null) {
            Spacer(Modifier.height(4.dp))
            Text(subtitle, style = MaterialTheme.typography.bodySmall, color = Neema.colors.muted, textAlign = TextAlign.Center)
        }
        if (action != null) { Spacer(Modifier.height(12.dp)); action() }
    }
}

@Composable
fun ErrorState(message: String, onRetry: (() -> Unit)? = null, modifier: Modifier = Modifier) {
    EmptyState(
        title = "Couldn't load",
        subtitle = message,
        icon = Icons.Outlined.ErrorOutline,
        modifier = modifier,
        action = onRetry?.let { { OutlinedButton(onClick = it) { Text("Retry") } } },
    )
}

/** White rounded card with a hairline border — the dashboard's panel. */
@Composable
fun Panel(
    modifier: Modifier = Modifier,
    padding: PaddingValues = PaddingValues(14.dp),
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val c = Neema.colors
    Column(
        modifier
            .clip(RoundedCornerShape(14.dp))
            .background(c.bg2)
            .border(1.dp, c.hairline, RoundedCornerShape(14.dp))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(padding),
        content = content,
    )
}

@Composable
fun SectionTitle(text: String, modifier: Modifier = Modifier, trailing: (@Composable () -> Unit)? = null) {
    Row(modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(
            text.uppercase(), modifier = Modifier.weight(1f),
            fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.8.sp, color = Neema.colors.muted,
        )
        trailing?.invoke()
    }
}

/** A KPI tile: label, big number, optional hint. */
@Composable
fun StatTile(label: String, value: String, modifier: Modifier = Modifier, hint: String? = null, accent: Color? = null) {
    Panel(modifier) {
        // Two lines each, so large text wraps instead of cutting a label or an
        // amount — between words only: a one-word label ("Permissions") that
        // is wider than a narrow tile at large text steps its size down to
        // fit on one line rather than breaking as "Permission / s".
        val oneWord = label.none { it.isWhitespace() }
        BasicText(
            label,
            style = LocalTextStyle.current.merge(androidx.compose.ui.text.TextStyle(fontSize = 12.sp, color = Neema.colors.muted)),
            maxLines = if (oneWord) 1 else 2, overflow = TextOverflow.Ellipsis,
            autoSize = if (oneWord) TextAutoSize.StepBased(minFontSize = 8.sp, maxFontSize = 12.sp, stepSize = 0.5.sp) else null,
        )
        Spacer(Modifier.height(4.dp))
        // The same for the figure: "20/20" or "Online" shrinks rather than split as "20/2 / 0".
        val oneToken = value.none { it.isWhitespace() }
        BasicText(
            value,
            style = TabularNums.merge(
                androidx.compose.ui.text.TextStyle(fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, color = accent ?: MaterialTheme.colorScheme.onSurface),
            ),
            maxLines = if (oneToken) 1 else 2, overflow = TextOverflow.Ellipsis,
            autoSize = if (oneToken) TextAutoSize.StepBased(minFontSize = 12.sp, maxFontSize = 22.sp, stepSize = 1.sp) else null,
        )
        if (hint != null) Text(hint, fontSize = 11.sp, color = Neema.colors.muted, maxLines = 2)
    }
}

/**
 * The web's search box (OrdersView / CatalogView / LeadsView): a white field
 * with a willow `#b5da8b` hairline, 12dp corners, a pale magnifier inside
 * on the left, moss-900 text and a moss border on focus. Dark mode swaps
 * in the Prussian surface. [height] and [fontSize] default to Orders'
 * 40dp/16sp; a screen passes its own where the web's differs. The ✕ that
 * clears a typed query is the app's own addition.
 */
@Composable
fun SearchField(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String = "Search…",
    modifier: Modifier = Modifier,
    height: Dp = 40.dp,
    fontSize: androidx.compose.ui.unit.TextUnit = 16.sp,
    /** Catalog's field uses `#cee6b2`; the others `#b5da8b`. */
    borderColor: Color? = null,
) {
    val c = Neema.colors
    val source = remember { androidx.compose.foundation.interaction.MutableInteractionSource() }
    val focused by source.collectIsFocusedAsState()
    val text = if (c.isDark) c.text else Palette.Moss900
    val line = when {
        focused -> Palette.Moss600
        c.isDark -> c.border
        else -> borderColor ?: Palette.Willow300
    }
    val shape = RoundedCornerShape(12.dp)
    androidx.compose.foundation.text.BasicTextField(
        value = value, onValueChange = onChange, singleLine = true,
        textStyle = androidx.compose.ui.text.TextStyle(color = text, fontSize = fontSize, fontFamily = NeemaFont),
        cursorBrush = androidx.compose.ui.graphics.SolidColor(Palette.Moss600),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        interactionSource = source,
        // The field takes taps over a 48dp band (the minimum touch target);
        // the box drawn inside it keeps the web's own height.
        modifier = modifier.fillMaxWidth().heightIn(min = 48.dp),
        decorationBox = { inner ->
          Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.CenterStart) {
            // At least [height]; taller only when large text needs a second placeholder line.
            Row(
                Modifier.fillMaxWidth().heightIn(min = height).clip(shape)
                    .background(if (c.isDark) c.bg2 else Color.White)
                    .border(if (focused) 2.dp else 1.dp, line, shape)
                    .padding(start = 12.dp, end = if (value.isNotEmpty()) 2.dp else 12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(WebIcons.Search, null, tint = if (c.isDark) c.muted else Palette.Stone300, modifier = Modifier.size(16.dp))
                Spacer(Modifier.width(8.dp))
                Box(Modifier.weight(1f).padding(vertical = 4.dp)) {
                    if (value.isEmpty()) Text(
                        placeholder, color = text.copy(alpha = 0.5f), fontSize = fontSize,
                        maxLines = 2, overflow = TextOverflow.Ellipsis,
                    )
                    inner()
                }
                // A 36dp slot in the row, answering taps (and TalkBack) over 48dp.
                if (value.isNotEmpty()) Box(
                    Modifier.touchTargetOver(36.dp).clip(CircleShape).clickable { onChange("") },
                    contentAlignment = Alignment.Center,
                ) { Icon(Icons.Default.Close, "Clear", tint = c.muted, modifier = Modifier.size(16.dp)) }
            }
          }
        },
    )
}

/**
 * A control that takes [slot] of room in its row but is [target] (48dp) for
 * touch and for TalkBack: it measures [target] square, reports [slot] to its
 * parent, and sits centred on that slot, overhanging it evenly.
 */
fun Modifier.touchTargetOver(slot: Dp, target: Dp = 48.dp): Modifier = this.layout { measurable, _ ->
    val t = target.roundToPx()
    val s = slot.roundToPx()
    val p = measurable.measure(androidx.compose.ui.unit.Constraints.fixed(t, t))
    layout(s, s) { p.place((s - t) / 2, (s - t) / 2) }
}

/** Horizontal filter chips with an optional count badge. */
@Composable
fun FilterChips(
    options: List<Pair<String, String>>,
    selected: String,
    onSelect: (String) -> Unit,
    modifier: Modifier = Modifier,
    counts: Map<String, Int> = emptyMap(),
) {
    androidx.compose.foundation.lazy.LazyRow(
        modifier, horizontalArrangement = Arrangement.spacedBy(6.dp),
        contentPadding = PaddingValues(horizontal = 12.dp),
    ) {
        items(options.size) { i ->
            val (key, label) = options[i]
            val n = counts[key]
            FilterChip(
                selected = key == selected,
                onClick = { onSelect(key) },
                label = { Text(if (n != null && n > 0) "$label · $n" else label) },
            )
        }
    }
}

/**
 * The web's modal overlay: `bg-black/50`. Call it inside any dialog's
 * content: the platform's own dim comes from the window theme (0.6), not the
 * web's value. Pass 0 where the dialog draws the web's overlay itself
 * (SessionExpiredDialog's bg-black/40, the media viewer's black/90). It also
 * lays the window flat ([FlatDialogWindow]). Screenshot tests render the dim
 * as the device does (testing/Harness.kt settleDialogWindows).
 */
@Composable
fun WebModalDim(amount: Float = 0.5f) {
    val view = androidx.compose.ui.platform.LocalView.current
    androidx.compose.runtime.SideEffect {
        (view.parent as? androidx.compose.ui.window.DialogWindowProvider)?.window?.let { w ->
            w.addFlags(android.view.WindowManager.LayoutParams.FLAG_DIM_BEHIND)
            w.setDimAmount(amount)
        }
    }
    FlatDialogWindow()
}

/**
 * Call inside a dialog's content (WebModalDim does). Compose raises its
 * dialog window's root (DialogLayout) to 8dp and the window's decor to the
 * theme's 16dp, both over transparent outlines, so a phone draws no shadow
 * from them — the card's own look over the web's plain overlay is all there
 * is. The screenshot renderer ignores the outline's alpha and casts a dark
 * halo over the whole screen from them — cast or not depending on which
 * tests ran before in the same JVM (it is kept from the first frame that
 * draws it), which is what made dialog goldens flake. At elevation 0 it can
 * never appear, and nothing changes on a device.
 */
@Composable
fun FlatDialogWindow() {
    val view = androidx.compose.ui.platform.LocalView.current
    androidx.compose.runtime.SideEffect {
        (view.parent as? androidx.compose.ui.window.DialogWindowProvider)?.let { p ->
            (p as? android.view.View)?.elevation = 0f
            p.window.setElevation(0f)
            p.window.peekDecorView()?.elevation = 0f
        }
    }
}

@Composable
fun ConfirmDialog(
    title: String,
    message: String,
    confirmLabel: String = "Confirm",
    destructive: Boolean = false,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { WebModalDim(); Text(title) },
        text = { Text(message) },
        confirmButton = {
            TextButton(onClick = { onConfirm(); onDismiss() }) {
                Text(confirmLabel, color = if (destructive) Neema.colors.red else MaterialTheme.colorScheme.primary)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/**
 * The theme's switch, legible in both modes: M3's default unchecked switch
 * is navy-on-navy on the Prussian surfaces. Use `Switch(colors = neemaSwitchColors())`.
 */
@Composable
fun neemaSwitchColors(): SwitchColors {
    val c = Neema.colors
    return SwitchDefaults.colors(
        checkedThumbColor = Color.White, checkedTrackColor = c.gold, checkedBorderColor = c.gold,
        uncheckedThumbColor = if (c.isDark) c.textMid else Palette.Sage400,
        uncheckedTrackColor = if (c.isDark) c.bg4 else Palette.Mist,
        uncheckedBorderColor = if (c.isDark) c.border2 else Palette.Sage300,
    )
}

/** Unread / count badge. */
@Composable
fun CountBadge(n: Int, modifier: Modifier = Modifier, color: Color = Neema.colors.gold) {
    if (n <= 0) return
    Box(
        modifier.defaultMinSize(minWidth = 18.dp, minHeight = 18.dp).clip(RoundedCornerShape(50)).background(color)
            .padding(horizontal = 5.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(if (n > 99) "99+" else n.toString(), color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold)
    }
}
