package ke.co.bethanyhouse.neema.core.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
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

@Composable
fun Avatar(name: String?, url: String? = null, size: Dp = 40.dp, modifier: Modifier = Modifier) {
    val initialsBox = @Composable {
        Box(
            Modifier.size(size).clip(CircleShape).background(avatarColor(name)),
            contentAlignment = Alignment.Center,
        ) {
            Text(Fmt.initials(name), color = Color.White, fontWeight = FontWeight.Bold, fontSize = (size.value * 0.36f).sp)
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
    "web" -> ChannelStyle("Web chat", Color(0xFF589B31))
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

/** Rounded status pill; [color] drives both text and tint. */
@Composable
fun Pill(text: String, color: Color, modifier: Modifier = Modifier, filled: Boolean = false) {
    Text(
        text,
        modifier = modifier.clip(RoundedCornerShape(50))
            .background(if (filled) color else color.copy(alpha = 0.13f))
            .padding(horizontal = 8.dp, vertical = 3.dp),
        color = if (filled) Color.White else color,
        fontSize = 11.sp, fontWeight = FontWeight.SemiBold, maxLines = 1,
    )
}

@Composable
fun statusColor(status: String?): Color {
    val c = Neema.colors
    return when (status?.lowercase()) {
        "delivered", "paid", "done", "completed", "won", "answered", "active", "open_window", "confirmed" -> c.green
        "cancelled", "canceled", "failed", "lost", "missed", "declined", "error" -> c.red
        "pending", "processing", "ringing", "partial", "awaiting" -> Color(0xFFD97706)
        "human" -> c.blue
        "paused" -> Color(0xFFD97706)
        else -> c.muted
    }
}

@Composable
fun Loading(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(strokeWidth = 2.5.dp, modifier = Modifier.size(32.dp))
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
        Text(label, fontSize = 12.sp, color = Neema.colors.muted, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Spacer(Modifier.height(4.dp))
        Text(value, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, color = accent ?: MaterialTheme.colorScheme.onSurface, maxLines = 1)
        if (hint != null) Text(hint, fontSize = 11.sp, color = Neema.colors.muted, maxLines = 2)
    }
}

@Composable
fun SearchField(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String = "Search…",
    modifier: Modifier = Modifier,
) {
    OutlinedTextField(
        value = value, onValueChange = onChange, singleLine = true,
        placeholder = { Text(placeholder) },
        leadingIcon = { Icon(Icons.Default.Search, null) },
        trailingIcon = if (value.isNotEmpty()) ({ IconButton(onClick = { onChange("") }) { Icon(Icons.Default.Close, "Clear") } }) else null,
        shape = RoundedCornerShape(12.dp),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
        modifier = modifier.fillMaxWidth(),
    )
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
        title = { Text(title) },
        text = { Text(message) },
        confirmButton = {
            TextButton(onClick = { onConfirm(); onDismiss() }) {
                Text(confirmLabel, color = if (destructive) Neema.colors.red else MaterialTheme.colorScheme.primary)
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
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
