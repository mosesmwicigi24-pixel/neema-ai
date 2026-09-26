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
import androidx.compose.ui.draw.alpha
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
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaFont
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors

// ── Metadata (the web's STAGE_META / TIER_META / SOURCE_META / CH_META) ─────

data class StageMeta(val label: String, val color: Color, val dot: Color)

private val STAGE_META = mapOf(
    "new" to StageMeta("New", Palette.Stone500, Palette.Stone400),
    "contacted" to StageMeta("Contacted", Palette.Blue600, Palette.Blue500),
    "qualified" to StageMeta("Qualified", Palette.Violet600, Palette.Violet500),
    "proposal" to StageMeta("Proposal", Palette.Amber600, Palette.Amber500),
    "negotiation" to StageMeta("Negotiating", Palette.Orange600, Palette.Orange500),
    "won" to StageMeta("Won ✓", Palette.Emerald700, Palette.Emerald500),
    "lost" to StageMeta("Lost", Palette.Red500, Palette.Red400),
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
    "vip" to TierMeta("VIP", Palette.Amber800, Palette.Amber300, "Top spender / very frequent buyer", Palette.Amber100),
    "loyal" to TierMeta("Loyal", Palette.Emerald700, Palette.Emerald300, "Repeat customer", Palette.Emerald100),
    "regular" to TierMeta("Regular", Palette.Sky700, Palette.Sky300, "A few orders", Palette.Sky100),
    "new" to TierMeta("New", Palette.Stone600, Palette.Stone300, "First order", Palette.Stone100),
    "prospect" to TierMeta("Prospect", Palette.Stone400, Palette.Stone200, "No orders yet", Palette.Stone50),
    "at_risk" to TierMeta("At risk", Palette.Red700, Palette.Red300, "Good customer who's gone quiet — worth a nudge", Palette.Red100),
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
    "whatsapp" -> "WhatsApp" to ChannelColors.WhatsApp
    "messenger" -> "Messenger" to ChannelColors.Messenger
    "facebook" -> "Facebook" to ChannelColors.Facebook
    "instagram" -> "Instagram" to ChannelColors.Instagram
    "email" -> "Email" to ChannelColors.Email
    "sms" -> "SMS" to Palette.Slate500
    else -> channel.replaceFirstChar { it.uppercase() } to Palette.Slate500
}

// Goldenrod stepper palette (sampled by the web from its reference design).
val PIPE_GOLD = Palette.PipeGold
val PIPE_GOLD_SOLID = Palette.PipeGoldSolid
private val PIPE_IDLE = Palette.Stone200
private val PIPE_IDLE_TEXT = Palette.Stone400
private val PIPE_LOST = Palette.PipeLost
private val PIPE_LOST_ICON = Palette.PipeLostIcon
private val PIPE_LOST_TEXT = Palette.PipeLostText
private val LOST_RED = Palette.Red500

val WA_GREEN = ChannelColors.WhatsApp

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
        "messenger" -> SolidColor(Palette.MessengerSky)
        "facebook" -> SolidColor(ChannelColors.Facebook)
        "instagram" -> Brush.linearGradient(
            listOf(Palette.InstaOrange, Palette.InstaCoral, Palette.InstaRed, Palette.InstaMagenta, Palette.InstaPurple),
        )
        "email" -> SolidColor(Palette.Indigo500)
        "web" -> SolidColor(Palette.Slate500)
        else -> SolidColor(Palette.Moss800)
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
        textStyle = TextStyle(fontFamily = NeemaFont, fontSize = fontSize, color = c.text),
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
    /** Text of a save that did not land: the editor reopens with it (then [onRestored] takes it). */
    restore: String? = null,
    onRestored: () -> Unit = {},
) {
    val c = Neema.colors
    // Saveable: a half-typed edit survives rotation and Android reclaiming the app.
    var editing by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(false) }
    // Seeded when the edit starts, never re-keyed on [value]: a live reload that
    // brings a new value mid-edit must not wipe what the agent is typing.
    var draft by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(value) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(restore) {
        if (restore != null) {
            draft = restore
            editing = true
            onRestored()
        }
    }
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
                Icon(Icons.Default.Check, "Save", tint = Palette.Emerald600, modifier = Modifier.size(16.dp))
            }
            IconButton(onClick = { draft = value; editing = false }, modifier = Modifier.size(32.dp)) {
                Icon(Icons.Default.Close, "Cancel", tint = c.muted, modifier = Modifier.size(16.dp))
            }
        } else {
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(6.dp))
                    .then(if (enabled) Modifier.clickable { draft = value; editing = true } else Modifier)
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
        score >= 70 -> Palette.Emerald500
        score >= 40 -> Palette.Amber500
        else -> Palette.Stone300
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
        modifier.heightIn(min = height).alpha(if (enabled || filled) 1f else 0.55f).clip(RoundedCornerShape(8.dp))
            .background(if (filled) (if (enabled) color else color.copy(alpha = 0.55f)) else color.dim(0.1f))
            .then(if (filled) Modifier else Modifier.border(1.dp, color.dim(0.35f), RoundedCornerShape(8.dp)))
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 10.dp, vertical = 4.dp),
        contentAlignment = Alignment.Center,
    ) {
        // Grows (and wraps) with the font scale rather than clipping the label.
        Text(text, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = if (filled) Color.White else color, maxLines = 2, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}

/** The web's quiet outline button (#f8fafc fill, #b5da8b border, slate text): Advance Stage, add-tag "+". */
@Composable
fun NeutralButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    height: Dp = 32.dp,
    textColor: Color = Color.Unspecified,
    enabled: Boolean = true,
) {
    val c = Neema.colors
    Box(
        modifier.heightIn(min = height).alpha(if (enabled) 1f else 0.55f).clip(RoundedCornerShape(8.dp)).background(c.surface)
            .border(1.dp, c.border, RoundedCornerShape(8.dp)).clickable(enabled = enabled, onClick = onClick).padding(horizontal = 10.dp, vertical = 4.dp),
        contentAlignment = Alignment.Center,
    ) {
        Text(text, fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = textColor.takeOrElse { c.text }, maxLines = 2, textAlign = androidx.compose.ui.text.style.TextAlign.Center)
    }
}

/** A single-line input + action, with a result bubble underneath (Ask Neema / Answer via Neema). */
@Composable
fun NeemaBox(
    placeholder: String,
    actionLabel: String,
    busy: Boolean,
    result: String?,
    /** Held by the ViewModel: a failure, a tab switch or a reload never loses it. */
    text: String,
    onText: (String) -> Unit,
    onSubmit: () -> Unit,
) {
    val c = Neema.colors
    val submit = { onSubmit() }
    Column(
        Modifier.fillMaxWidth().padding(bottom = 16.dp).clip(RoundedCornerShape(12.dp)).background(c.bg2)
            .border(1.dp, c.hairline, RoundedCornerShape(12.dp)).padding(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            SmallInput(text, onText, placeholder, Modifier.weight(1f), onDone = { if (!busy && text.isNotBlank()) submit() })
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
        // Each label gets its node's share of the row (less a hair of air), so two
        // neighbours never run together ("ContactedQualified") in a wide font.
        val labelMax = (if (fits) (maxWidth - 16.dp) / stages.size else 38.dp) - 3.dp
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
                    // Full size (9sp) where it fits its slot; a long label in a crowded row
                    // steps down to 7sp rather than running into its neighbour.
                    androidx.compose.foundation.text.BasicText(
                        stageLabel(stage), maxLines = 1, softWrap = false,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                        style = androidx.compose.ui.text.TextStyle(
                            fontFamily = NeemaFont, color = labelColor,
                            textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                            fontWeight = if (state == StepState.Active) FontWeight.Bold else FontWeight.SemiBold,
                        ),
                        autoSize = androidx.compose.foundation.text.TextAutoSize.StepBased(minFontSize = 7.sp, maxFontSize = 9.sp, stepSize = 0.5.sp),
                        modifier = Modifier.wrapContentSize(Alignment.TopCenter, unbounded = true).offset(x = (-12).dp, y = 15.dp).widthIn(max = labelMax),
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
