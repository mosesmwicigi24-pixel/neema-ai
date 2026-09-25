package ke.co.bethanyhouse.neema.feature.conversations.customer

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Language
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.takeOrElse
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.ui.theme.Neema

// ── Metadata (the web's STAGE_META / TIER_META / SOURCE_META / CH_META) ─────

data class StageMeta(val label: String, val color: Color, val dot: Color)

private val STAGE_META = mapOf(
    "new" to StageMeta("New", Color(0xFF78716C), Color(0xFFA8A29E)),
    "contacted" to StageMeta("Contacted", Color(0xFF2563EB), Color(0xFF3B82F6)),
    "qualified" to StageMeta("Qualified", Color(0xFF7C3AED), Color(0xFF8B5CF6)),
    "proposal" to StageMeta("Proposal", Color(0xFFD97706), Color(0xFFF59E0B)),
    "negotiation" to StageMeta("Negotiating", Color(0xFFEA580C), Color(0xFFF97316)),
    "won" to StageMeta("Won ✓", Color(0xFF047857), Color(0xFF10B981)),
    "lost" to StageMeta("Lost", Color(0xFFEF4444), Color(0xFFF87171)),
)

/** A custom (operator-added) stage shows its own label in the pipeline's gold, not "New". */
fun stageMeta(stage: String): StageMeta =
    STAGE_META[stage] ?: StageMeta(stageLabel(stage), PIPE_GOLD_SOLID, PIPE_GOLD)

private val PIPE_LABEL = mapOf(
    "new" to "New", "contacted" to "Contacted", "qualified" to "Qualified", "proposal" to "Proposal",
    "negotiation" to "Negotiating", "won" to "Won", "lost" to "Lost",
)

fun stageLabel(s: String): String = PIPE_LABEL[s] ?: s.replaceFirstChar { it.uppercase() }

/** [bg] is the web's light Tailwind fill (amber-100, emerald-100, …); dark mode tints [color] instead. */
data class TierMeta(val label: String, val color: Color, val border: Color, val title: String, val bg: Color)

val TIER_META = mapOf(
    "vip" to TierMeta("VIP", Color(0xFF92400E), Color(0xFFFCD34D), "Top spender / very frequent buyer", Color(0xFFFEF3C7)),
    "loyal" to TierMeta("Loyal", Color(0xFF047857), Color(0xFF6EE7B7), "Repeat customer", Color(0xFFD1FAE5)),
    "regular" to TierMeta("Regular", Color(0xFF0369A1), Color(0xFF7DD3FC), "A few orders", Color(0xFFE0F2FE)),
    "new" to TierMeta("New", Color(0xFF57534E), Color(0xFFD6D3D1), "First order", Color(0xFFF5F5F4)),
    "prospect" to TierMeta("Prospect", Color(0xFFA8A29E), Color(0xFFE7E5E4), "No orders yet", Color(0xFFFAFAF9)),
    "at_risk" to TierMeta("At risk", Color(0xFFB91C1C), Color(0xFFFCA5A5), "Good customer who's gone quiet — worth a nudge", Color(0xFFFEE2E2)),
)

/** Where a lead first found us (captured by the AI or set by an operator). */
val SOURCE_META = mapOf(
    "facebook" to ("Facebook" to "📘"),
    "instagram" to ("Instagram" to "📸"),
    "tiktok" to ("TikTok" to "🎵"),
    "youtube" to ("YouTube" to "▶️"),
    "whatsapp" to ("WhatsApp" to "💬"),
    "referral" to ("Referral" to "🤝"),
    "walk_in" to ("Walk-in" to "🚶"),
    "website" to ("Website" to "🌐"),
    "google" to ("Google" to "🔍"),
    "other" to ("Other" to "•"),
)

/**
 * A lead source's label + icon. Besides SOURCE_META's keys the webhooks write
 * "<base>_ad" for a click-to-message ad (wa_native._capture_referral →
 * "facebook_ad", meta_webhook → "facebook_ad" / "instagram_ad"); the web prints
 * those raw ("• facebook_ad"), here they read "📘 Facebook ad".
 */
fun sourceMeta(src: String): Pair<String, String>? =
    SOURCE_META[src] ?: src.removeSuffix("_ad").takeIf { src.endsWith("_ad") }?.let { SOURCE_META[it] }
        ?.let { (label, icon) -> "$label ad" to icon }

/** Channel label + brand colour for the linked-identities list. */
fun chMeta(channel: String): Pair<String, Color> = when (channel) {
    "whatsapp" -> "WhatsApp" to Color(0xFF25D366)
    "messenger" -> "Messenger" to Color(0xFF0084FF)
    "facebook" -> "Facebook" to Color(0xFF1877F2)
    "instagram" -> "Instagram" to Color(0xFFE1306C)
    "email" -> "Email" to Color(0xFF6366F1)
    "sms" -> "SMS" to Color(0xFF64748B)
    else -> channel.replaceFirstChar { it.uppercase() } to Color(0xFF64748B)
}

// Goldenrod stepper palette (sampled by the web from its reference design).
val PIPE_GOLD = Color(0xFFC89B3C)
val PIPE_GOLD_SOLID = Color(0xFFA97C14)
private val PIPE_IDLE = Color(0xFFE7E5E4)
private val PIPE_IDLE_TEXT = Color(0xFFA8A29E)
private val PIPE_LOST = Color(0xFFF4CCCC)
private val PIPE_LOST_ICON = Color(0xFFEFA3A3)
private val PIPE_LOST_TEXT = Color(0xFFE08A8A)
private val LOST_RED = Color(0xFFEF4444)

val WA_GREEN = Color(0xFF25D366)

fun Color.dim(a: Float = 0.12f) = copy(alpha = a)

/** The web's Tailwind tints are tuned for white; on the Prussian-blue night they're lifted toward white to stay legible. */
@Composable
fun Color.themed(): Color = if (Neema.colors.isDark) androidx.compose.ui.graphics.lerp(this, Color.White, 0.45f) else this

// ── Small building blocks ───────────────────────────────────────────────────

/** Long-press hint: the web's `title=` tooltips, for touch. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun Hint(text: String?, content: @Composable () -> Unit) {
    if (text.isNullOrEmpty()) { content(); return }
    TooltipBox(
        positionProvider = TooltipDefaults.rememberPlainTooltipPositionProvider(),
        tooltip = { PlainTooltip { Text(text) } },
        state = rememberTooltipState(),
    ) { content() }
}

/** A coloured circle standing in for the channel's logo (CHANNEL_ICON_SVG backgrounds). */
@Composable
fun ChannelBadge(channel: String, size: Dp = 20.dp) {
    val bg: Brush = when (channel) {
        "whatsapp" -> SolidColor(WA_GREEN)
        "messenger" -> SolidColor(Color(0xFF0099FF))
        "facebook" -> SolidColor(Color(0xFF1877F2))
        "instagram" -> Brush.linearGradient(
            listOf(Color(0xFFF09433), Color(0xFFE6683C), Color(0xFFDC2743), Color(0xFFCC2366), Color(0xFFBC1888)),
        )
        "email" -> SolidColor(Color(0xFF4D66B3))
        "web" -> SolidColor(Color(0xFF64748B))
        else -> SolidColor(Color(0xFF2C4E18))
    }
    if (channel == "web") {
        // A website visitor: a globe, never WhatsApp's mark.
        Box(Modifier.size(size).clip(CircleShape).background(bg), contentAlignment = Alignment.Center) {
            Icon(Icons.Default.Language, null, tint = Color.White, modifier = Modifier.size(size * 0.62f))
        }
        return
    }
    val glyph = when (channel) {
        "whatsapp" -> "W"; "messenger" -> "m"; "facebook" -> "f"; "instagram" -> "◎"
        "email" -> "@"; "tiktok" -> "♪"; else -> "…"
    }
    Box(Modifier.size(size).clip(CircleShape).background(bg), contentAlignment = Alignment.Center) {
        Text(glyph, color = Color.White, fontSize = (size.value * 0.5f).sp, fontWeight = FontWeight.Bold, lineHeight = (size.value * 0.5f).sp)
    }
}

/** A titled block in the tab body (the web's <Section>). */
@Composable
fun CrmSection(title: String, action: (@Composable () -> Unit)? = null, content: @Composable ColumnScope.() -> Unit) {
    Column(Modifier.fillMaxWidth().padding(bottom = 20.dp)) {
        Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(
                title.uppercase(), modifier = Modifier.weight(1f),
                fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp, color = Neema.colors.textMid,
            )
            action?.invoke()
        }
        content()
    }
}

@Composable
fun Hairline() = HorizontalDivider(color = Neema.colors.hairline, thickness = 1.dp)

/** Label + value row in the Insights tab. */
@Composable
fun KvRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, fontSize = 12.sp, color = Neema.colors.textMid, modifier = Modifier.weight(1f))
        Text(value, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Neema.colors.text)
    }
}

/** Read-only row in Contact Details (Source, Came via, Parish). */
@Composable
fun InfoRow(label: String, value: String, hint: String? = null) {
    Hint(hint) {
        Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.Top) {
            Text(label, fontSize = 10.sp, color = Neema.colors.muted, modifier = Modifier.width(80.dp).padding(top = 1.dp))
            Text(value, fontSize = 11.sp, color = Neema.colors.text, modifier = Modifier.weight(1f), textAlign = androidx.compose.ui.text.style.TextAlign.End)
        }
    }
    Hairline()
}

@Composable
fun SmallInput(
    value: String,
    onChange: (String) -> Unit,
    placeholder: String,
    modifier: Modifier = Modifier,
    keyboardType: KeyboardType = KeyboardType.Text,
    singleLine: Boolean = true,
    minLines: Int = 1,
    fontSize: TextUnit = 12.sp,
    focusRequester: FocusRequester? = null,
    onDone: (() -> Unit)? = null,
) {
    val c = Neema.colors
    BasicTextField(
        value = value,
        onValueChange = onChange,
        singleLine = singleLine,
        minLines = minLines,
        textStyle = TextStyle(fontSize = fontSize, color = c.text),
        cursorBrush = SolidColor(c.gold),
        keyboardOptions = KeyboardOptions(keyboardType = keyboardType, imeAction = if (singleLine) ImeAction.Done else ImeAction.Default),
        keyboardActions = KeyboardActions(onDone = { onDone?.invoke() }),
        modifier = modifier
            .then(if (focusRequester != null) Modifier.focusRequester(focusRequester) else Modifier)
            .clip(RoundedCornerShape(8.dp))
            .background(c.bg2)
            .border(1.dp, c.border, RoundedCornerShape(8.dp))
            .padding(horizontal = 10.dp, vertical = 8.dp),
        decorationBox = { inner ->
            Box {
                if (value.isEmpty()) Text(placeholder, fontSize = fontSize, color = c.muted, maxLines = if (singleLine) 1 else Int.MAX_VALUE)
                inner()
            }
        },
    )
}

/** Tap to edit, ✓ / Done saves, ✕ cancels (the web's EditableField). Read-only when [enabled] is false. */
@Composable
fun EditableField(
    label: String,
    value: String,
    onSave: (String) -> Unit,
    placeholder: String,
    enabled: Boolean,
    keyboardType: KeyboardType = KeyboardType.Text,
) {
    val c = Neema.colors
    var editing by remember { mutableStateOf(false) }
    var draft by remember(value) { mutableStateOf(value) }
    val focus = remember { FocusRequester() }
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp).heightIn(min = 32.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, fontSize = 10.sp, color = c.textMid, modifier = Modifier.width(64.dp))
        if (editing) {
            LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
            val commit = { onSave(draft); editing = false }
            SmallInput(
                draft, { draft = it }, placeholder, Modifier.weight(1f),
                keyboardType = keyboardType, focusRequester = focus, onDone = commit,
            )
            IconButton(onClick = commit, modifier = Modifier.size(32.dp)) {
                Icon(Icons.Default.Check, "Save", tint = Color(0xFF059669), modifier = Modifier.size(16.dp))
            }
            IconButton(onClick = { draft = value; editing = false }, modifier = Modifier.size(32.dp)) {
                Icon(Icons.Default.Close, "Cancel", tint = c.muted, modifier = Modifier.size(16.dp))
            }
        } else {
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(6.dp))
                    .then(if (enabled) Modifier.clickable { editing = true } else Modifier)
                    .padding(vertical = 6.dp, horizontal = 2.dp),
            ) {
                if (value.isNotEmpty()) Text(value, fontSize = 12.sp, color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                else Text(placeholder.ifEmpty { "—" }, fontSize = 12.sp, color = c.muted.copy(alpha = 0.6f), fontStyle = FontStyle.Italic, maxLines = 1)
            }
        }
    }
    Hairline()
}

@Composable
fun ScoreBar(score: Int) {
    val color = when {
        score >= 70 -> Color(0xFF10B981)
        score >= 40 -> Color(0xFFF59E0B)
        else -> Color(0xFFD6D3D1)
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        ProgressBar(score / 100f, color, Modifier.weight(1f).height(6.dp))
        Text("$score", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Neema.colors.textMid,
            modifier = Modifier.width(24.dp), textAlign = androidx.compose.ui.text.style.TextAlign.End)
    }
}

@Composable
fun ProgressBar(fraction: Float, color: Color, modifier: Modifier) {
    Box(modifier.clip(RoundedCornerShape(50)).background(Neema.colors.hairline)) {
        Box(Modifier.fillMaxHeight().fillMaxWidth(fraction.coerceIn(0f, 1f)).clip(RoundedCornerShape(50)).background(color))
    }
}

/** Filled small action button with the web's tints. */
@Composable
fun TintButton(
    text: String,
    color: Color,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    filled: Boolean = false,
    enabled: Boolean = true,
    height: Dp = 32.dp,
) {
    Box(
        modifier.height(height).clip(RoundedCornerShape(8.dp))
            .background(if (filled) (if (enabled) color else color.copy(alpha = 0.55f)) else color.dim(0.1f))
            .then(if (filled) Modifier else Modifier.border(1.dp, color.dim(0.35f), RoundedCornerShape(8.dp)))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = if (filled) Color.White else color, maxLines = 1)
    }
}

/** The web's quiet outline button (#f8fafc fill, #b5da8b border, slate text): Advance Stage, add-tag "+". */
@Composable
fun NeutralButton(text: String, onClick: () -> Unit, modifier: Modifier = Modifier, height: Dp = 32.dp, textColor: Color = Color.Unspecified) {
    val c = Neema.colors
    Box(
        modifier.height(height).clip(RoundedCornerShape(8.dp)).background(c.surface)
            .border(1.dp, c.border, RoundedCornerShape(8.dp)).clickable(onClick = onClick).padding(horizontal = 10.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = textColor.takeOrElse { c.text }, maxLines = 1)
    }
}

/** A single-line input + action, with a result bubble underneath (Ask Neema / Answer via Neema). */
@Composable
fun NeemaBox(
    placeholder: String,
    actionLabel: String,
    busy: Boolean,
    result: String?,
    onSubmit: (String, clear: () -> Unit) -> Unit,
) {
    val c = Neema.colors
    var text by remember { mutableStateOf("") }
    val submit = { onSubmit(text) { text = "" } }
    Column(
        Modifier.fillMaxWidth().padding(bottom = 16.dp).clip(RoundedCornerShape(12.dp)).background(c.bg2)
            .border(1.dp, c.hairline, RoundedCornerShape(12.dp)).padding(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            SmallInput(text, { text = it }, placeholder, Modifier.weight(1f), onDone = { if (!busy && text.isNotBlank()) submit() })
            TintButton(if (busy) "…" else actionLabel, c.gold, { submit() }, filled = true, enabled = !busy && text.isNotBlank())
        }
        if (result != null) {
            Text(
                result, fontSize = 12.sp, color = c.text,
                modifier = Modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(8.dp))
                    .background(c.surface).border(1.dp, c.hairline, RoundedCornerShape(8.dp))
                    .padding(horizontal = 10.dp, vertical = 8.dp),
            )
        }
    }
}

// ── Lead-pipeline stepper ───────────────────────────────────────────────────

private enum class StepState { Active, Done, Future }

private fun stepState(stage: String, active: String, forward: List<String>): StepState {
    if (stage == active) return StepState.Active
    if (stage == "lost") return StepState.Future // Lost is only ever active when current
    if (active == "lost") return if (stage == "won") StepState.Future else StepState.Done
    val a = forward.indexOf(active)
    val s = forward.indexOf(stage)
    return if (s > -1 && a > -1 && s < a) StepState.Done else StepState.Future
}

/**
 * New → Contacted → Qualified → Proposal → (custom…) → Won, with Lost as a
 * faded terminal branch — laid out like the web's: fixed 24dp nodes, flexible
 * gold connectors between them, each label centred under its node. Tapping a
 * node sets the stage. Only when a narrow pane can't give every node ~38dp
 * (up to 4 custom stages) does it scroll sideways instead.
 */
@Composable
fun PipelineStepper(
    stages: List<String>,
    forward: List<String>,
    active: String,
    enabled: Boolean,
    onSelect: (String) -> Unit,
) {
    val c = Neema.colors
    fun reached(s: StepState) = s == StepState.Done || s == StepState.Active
    BoxWithConstraints(Modifier.fillMaxWidth()) {
        val needed = 38.dp * stages.size + 16.dp
        val fits = maxWidth >= needed
        Row(
            (if (fits) Modifier.fillMaxWidth() else Modifier.horizontalScroll(rememberScrollState()).width(needed))
                .padding(start = 8.dp, end = 8.dp, bottom = 18.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            stages.forEachIndexed { i, stage ->
                val state = stepState(stage, active, forward)
                val isLost = stage == "lost"
                if (i > 0) {
                    // The segment into this node takes this node's colour, as on the web.
                    val conn = if (isLost) PIPE_LOST else if (reached(state)) PIPE_GOLD else if (c.isDark) c.border2 else PIPE_IDLE
                    Box(Modifier.weight(1f).height(2.dp).clip(RoundedCornerShape(50)).background(conn))
                }
                val (fill, border, icon) = when {
                    state == StepState.Active && isLost -> Triple(LOST_RED, LOST_RED, Color.White)
                    state == StepState.Active -> Triple(PIPE_GOLD_SOLID, PIPE_GOLD_SOLID, Color.White)
                    state == StepState.Done -> Triple(c.bg2, PIPE_GOLD, PIPE_GOLD)
                    isLost -> Triple(c.bg2, PIPE_LOST, PIPE_LOST_ICON)
                    else -> Triple(c.bg2, if (c.isDark) c.border2 else PIPE_IDLE, Color.Transparent)
                }
                val labelColor = when {
                    state == StepState.Active -> if (isLost) LOST_RED else PIPE_GOLD_SOLID
                    state == StepState.Done -> PIPE_GOLD
                    isLost -> PIPE_LOST_TEXT
                    else -> PIPE_IDLE_TEXT
                }
                val showCheck = reached(state) && !isLost
                val showX = isLost && (state == StepState.Active || state == StepState.Future)
                Box(
                    Modifier.size(24.dp).clip(CircleShape).background(fill).border(2.dp, border, CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    if (showCheck) Icon(Icons.Default.Check, stageLabel(stage), tint = icon, modifier = Modifier.size(13.dp))
                    if (showX) Icon(Icons.Default.Close, stageLabel(stage), tint = icon, modifier = Modifier.size(13.dp))
                }
                // The label hangs under the node and may be wider than it (whitespace-nowrap).
                Box(Modifier.size(0.dp), contentAlignment = Alignment.TopCenter) {
                    Text(
                        stageLabel(stage), fontSize = 9.sp, color = labelColor, maxLines = 1, softWrap = false,
                        fontWeight = if (state == StepState.Active) FontWeight.Bold else FontWeight.SemiBold,
                        modifier = Modifier.wrapContentSize(Alignment.TopCenter, unbounded = true).offset(x = (-12).dp, y = 15.dp),
                    )
                }
                // A finger-sized target over node + label, without changing the layout.
                if (enabled) {
                    Box(Modifier.size(0.dp), contentAlignment = Alignment.Center) {
                        Box(
                            Modifier.wrapContentSize(Alignment.Center, unbounded = true).offset(x = (-12).dp, y = 7.dp)
                                .size(40.dp, 44.dp).clip(RoundedCornerShape(8.dp)).clickable { onSelect(stage) },
                        )
                    }
                }
            }
        }
    }
}
