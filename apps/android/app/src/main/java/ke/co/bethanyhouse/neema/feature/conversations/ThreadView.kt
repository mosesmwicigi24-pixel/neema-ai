package ke.co.bethanyhouse.neema.feature.conversations

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyListState
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Reply
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.channelStyle
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import kotlin.math.roundToInt
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.core.ui.theme.ChannelColors

// ═══════════════════════════ Thread rows ═══════════════════════════

/** One rendered line of the thread (immutable: an unchanged row skips recomposition). */
internal sealed interface TRow { val key: String }
@Immutable internal data class TNewDivider(val n: Int, override val key: String = "new-divider") : TRow
@Immutable internal data class TPostHead(val ctx: PostContext, override val key: String) : TRow
@Immutable internal data class TEscalated(val msg: ThreadMsg, val reason: String, override val key: String = msg.id) : TRow
@Immutable internal data class TFlag(val msg: ThreadMsg, override val key: String = msg.id) : TRow
@Immutable internal data class TPill(val msg: ThreadMsg, override val key: String = msg.id) : TRow
@Immutable internal data class TNote(val msg: ThreadMsg, override val key: String = msg.id) : TRow
@Immutable internal data class TBubble(val msg: ThreadMsg, val album: List<ThreadMsg>?, override val key: String = msg.id) : TRow

/** Escalation-style events sort just after the inbound message that caused them. */
internal fun sortThread(list: List<ThreadMsg>): List<ThreadMsg> = list.sortedBy { m ->
    m.millis + if (m.isSystem && (m.eventKind == "escalated" || (m.eventKind == "intercept" && m.agentName == null))) 1 else 0
}

/**
 * The thread as the web renders it: handoff pills that live in the activity
 * log stay out, only the FIRST escalation shows, a comment run is headed by
 * its post once, consecutive photos collapse into an album, and the "N new"
 * divider sits before the first message that was unread on open.
 */
internal fun buildThreadRows(sorted: List<ThreadMsg>, unreadSnap: Int): List<TRow> {
    val rows = ArrayList<TRow>(sorted.size + 8)
    // "Before the first unread message" (the web's intent): the unread ones are the
    // customer's last N messages. Counting from the end of the WHOLE thread (as the
    // web does) slid the divider onto the agent's own replies the moment one was sent.
    val dividerIdx = if (unreadSnap > 0) {
        val inbound = sorted.indices.filter { sorted[it].inbound && !sorted[it].isSystem }
        when {
            inbound.size >= unreadSnap -> inbound[inbound.size - unreadSnap]
            inbound.isNotEmpty() -> inbound.first()
            else -> maxOf(0, sorted.size - unreadSnap)
        }
    } else -1

    // A comment thread reads like Facebook: the POST once, the comments under it.
    val postHeadFor = HashMap<String, PostContext>()
    var lastPostKey = ""
    for (m in sorted) {
        val c = m.commentContext ?: continue
        if (c.replyTo != null) continue // our public replies sit inside the run
        val key = c.postId ?: c.permalink ?: c.title ?: ""
        if (key.isEmpty()) continue
        if (key != lastPostKey) { postHeadFor[m.id] = c; lastPostKey = key }
    }

    // WhatsApp-style albums: runs of ≥2 consecutive photos from the same side.
    val albumOf = HashMap<String, Pair<Boolean, List<ThreadMsg>>>()
    var run = mutableListOf<ThreadMsg>()
    fun flush() {
        if (run.size >= 2) { val items = run.toList(); items.forEachIndexed { i, m -> albumOf[m.id] = (i == 0) to items } }
        run = mutableListOf()
    }
    for (m in sorted) {
        val isImg = !m.isSystem && !m.isNote && m.mediaType == "image" && m.mediaUrl != null
        val prev = run.lastOrNull()
        if (isImg && (prev == null || (prev.direction == m.direction && prev.sender == m.sender))) run += m
        else { flush(); if (isImg) run += m }
    }
    flush()

    var escalationShown = false
    sorted.forEachIndexed { idx, msg ->
        val showDivider = idx == dividerIdx
        val album = albumOf[msg.id]
        val row: TRow? = when {
            album != null && !album.first -> null
            msg.isSystem -> {
                val kind = msg.eventKind ?: ""
                val agentPickup = kind == "intercept" && msg.agentName != null
                when {
                    // Handoffs live in the Activity Log only — never duplicated inline.
                    kind == "release" || kind == "transfer" || kind == "approve_draft" || agentPickup -> null
                    kind == "escalated" -> if (escalationShown) null else {
                        escalationShown = true
                        TEscalated(msg, msg.eventReason ?: "AI could not continue — agent needed")
                    }
                    kind == "flag" -> TFlag(msg)
                    kind == "intercept" -> if (escalationShown) null else {
                        escalationShown = true
                        val hasInboundMedia = sorted.subList(0, idx).any { it.inbound && it.mediaType != null }
                        TEscalated(msg, msg.eventReason ?: if (hasInboundMedia) "Media received — AI cannot process" else "AI could not continue — agent needed")
                    }
                    else -> TPill(msg)
                }
            }
            msg.isNote -> TNote(msg)
            else -> TBubble(msg, album?.second)
        }
        if (showDivider && unreadSnap > 0) rows += TNewDivider(unreadSnap)
        if (row is TBubble) postHeadFor[msg.id]?.let { rows += TPostHead(it, "post-${msg.id}") }
        if (row != null) rows += row
    }
    return rows
}

// ═══════════════════════════ Thread list ═══════════════════════════

internal class ThreadCallbacks(
    val onView: (Viewer) -> Unit,
    val onRecover: (String, (Recovery) -> Unit) -> Unit,
    val onReply: (ThreadMsg) -> Unit,
    val fetchVideo: suspend (String, String?) -> String?,
    val onRetry: () -> Unit,
    val onLoadOlder: () -> Unit,
    /** A "Not sent" bubble: send it again / take the words back to edit. */
    val onRetrySend: (String) -> Unit = {},
    val onEditFailed: (String) -> Unit = {},
)

@Composable
internal fun ThreadMessages(
    convId: String,
    channel: String?,
    messages: List<ThreadMsg>,
    unreadSnap: Int,
    hasMore: Boolean,
    loading: Boolean,
    error: Boolean,
    loadingOlder: Boolean,
    recovered: Map<String, String>,
    brokenVideos: Set<String>,
    cb: ThreadCallbacks,
    modifier: Modifier = Modifier,
    /** Why the thread failed to load (no connection, server down…). */
    errorText: String? = null,
    /** The older page failed: offer a tap instead of waiting on a scroll that can't come. */
    olderError: Boolean = false,
) {
    val sorted = remember(messages) { sortThread(messages) }
    val rows = remember(sorted, unreadSnap) { buildThreadRows(sorted, unreadSnap).asReversed() }
    // Newest at the bottom (reverseLayout): prepending older pages never moves the reader.
    val state: LazyListState = remember(convId) { LazyListState() }
    val newest = sorted.lastOrNull()
    LaunchedEffect(convId, newest?.id) {
        if (rows.isNotEmpty() && (state.firstVisibleItemIndex <= 2 || newest?.isLocal == true)) state.animateScrollToItem(0)
    }
    val nearTop by remember(state, rows.size) {
        derivedStateOf { (state.layoutInfo.visibleItemsInfo.lastOrNull()?.index ?: 0) >= rows.size - 3 }
    }
    LaunchedEffect(nearTop, hasMore, rows.size) { if (nearTop && hasMore && rows.isNotEmpty() && !olderError) cb.onLoadOlder() }

    Box(modifier.background(if (Neema.colors.isDark) Neema.colors.bg else Palette.Mist)) {
        when {
            loading && messages.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = Neema.colors.gold)
            }
            error && messages.isEmpty() -> Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Text("Couldn't load this conversation.", fontSize = 14.sp, color = Palette.Amber700)
                errorText?.takeIf { it != "Couldn't load this conversation." }?.let {
                    Text(it, fontSize = 12.sp, color = Neema.colors.muted, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp, start = 24.dp, end = 24.dp))
                }
                Spacer(Modifier.height(8.dp))
                Button(onClick = cb.onRetry, colors = ButtonDefaults.buttonColors(containerColor = Palette.Amber500)) { Text("Try again", fontSize = 12.sp) }
            }
            messages.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("No messages yet", fontSize = 14.sp, color = Hue.SagePale)
            }
            else -> LazyColumn(
                state = state, reverseLayout = true, modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                items(rows, key = { it.key }, contentType = { it::class }) { row ->
                    ThreadRowView(row, channel, recovered, brokenVideos, cb)
                }
                if (hasMore) item(key = "older") {
                    Box(Modifier.fillMaxWidth().padding(4.dp), contentAlignment = Alignment.Center) {
                        if (loadingOlder) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Hue.SagePale)
                        else if (olderError) Text(
                            "Couldn't load older messages — tap to retry", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = Palette.Amber700,
                            modifier = Modifier.clip(RoundedCornerShape(50)).clickable(onClickLabel = "Retry loading older messages", onClick = cb.onLoadOlder).padding(horizontal = 10.dp, vertical = 4.dp),
                        )
                        else Text("↑ scroll for older messages", fontSize = 10.sp, color = Palette.Stone400)
                    }
                }
            }
        }
        if (loading && messages.isNotEmpty()) LinearProgressIndicator(Modifier.fillMaxWidth().height(2.dp).align(Alignment.TopCenter), color = Neema.colors.gold)
    }
}

@Composable
private fun ThreadRowView(row: TRow, channel: String?, recovered: Map<String, String>, brokenVideos: Set<String>, cb: ThreadCallbacks) {
    when (row) {
        is TNewDivider -> DividerPill(
            "${row.n} new ${if (row.n == 1) "message" else "messages"}",
            line = Palette.Moss700.copy(alpha = 0.3f), bg = Palette.Willow100, fg = Palette.Moss700,
        )
        is TPostHead -> Box(Modifier.fillMaxWidth(0.8f).padding(top = 8.dp)) {
            CommentContextCard(row.ctx, true, channel, "Your post — their comments below", cb.onView, cb.fetchVideo)
        }
        is TEscalated -> Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            val t = tint(Palette.Amber50, Palette.Amber700, Palette.Amber200)
            val rule = if (Neema.colors.isDark) t.border else Palette.Amber200
            Row(verticalAlignment = Alignment.CenterVertically) {
                HorizontalDivider(Modifier.weight(1f), color = rule)
                Row(
                    Modifier.padding(horizontal = 8.dp).clip(RoundedCornerShape(50)).background(t.bg)
                        .border(1.dp, t.border, RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(Modifier.size(6.dp).clip(CircleShape).background(Palette.Amber400))
                    Spacer(Modifier.width(6.dp))
                    Text(
                        androidx.compose.ui.text.buildAnnotatedString {
                            append("Escalated to agent")
                            if (row.msg.createdAt != null) {
                                pushStyle(androidx.compose.ui.text.SpanStyle(fontSize = 9.sp, fontWeight = FontWeight.Normal, color = ink(Palette.Amber600)))
                                append(" · ${Fmt.timeAgo(row.msg.createdAt)}")
                                pop()
                            }
                        },
                        fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = t.fg, textAlign = TextAlign.Center,
                    )
                }
                HorizontalDivider(Modifier.weight(1f), color = rule)
            }
            Text(row.reason, fontSize = 10.sp, color = ink(Palette.Amber600), textAlign = TextAlign.Center, lineHeight = 14.sp, modifier = Modifier.fillMaxWidth(0.72f).padding(top = 4.dp))
        }
        is TFlag -> DividerPill(
            "🚩 Flagged: Needs Attention" + (row.msg.createdAt?.let { " · ${Fmt.timeAgo(it)}" } ?: ""),
            line = Palette.Red100, bg = Palette.Red100, fg = Palette.Red700,
        )
        is TPill -> {
            val (bg, bd, fg) = when (row.msg.eventKind) {
                "release" -> Triple(Palette.Blue50, Palette.Blue200, Palette.Blue700)
                "transfer" -> Triple(Hue.Indigo50, Hue.Indigo200, Hue.Indigo700)
                "approve_draft" -> Triple(Palette.Green50, Hue.Green200, Hue.Green700)
                else -> Triple(Palette.Stone100, Palette.Stone200, Palette.Stone600)
            }
            DividerPill(row.msg.body + (row.msg.createdAt?.let { " · ${Fmt.timeAgo(it)}" } ?: ""), line = Palette.Stone200, bg = bg, fg = fg, border = bd)
        }
        is TNote -> Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            val t = tint(Palette.Amber50, Palette.Amber800, Palette.Amber200)
            Column(
                Modifier.fillMaxWidth(0.85f).widthIn(max = 560.dp).clip(RoundedCornerShape(12.dp)).background(t.bg)
                    .dashedBorder(t.border, 12.dp).padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("📝", fontSize = 12.sp)
                    Spacer(Modifier.width(6.dp))
                    Text("INTERNAL NOTE", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.5.sp, color = ink(Palette.Amber600))
                }
                Spacer(Modifier.height(4.dp))
                Text(row.msg.body, fontSize = 12.sp, lineHeight = 17.sp, color = t.fg)
                Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (row.msg.sendState == "sending") { Icon(Icons.Filled.Schedule, "Saving", Modifier.size(10.dp), tint = Palette.Amber400); Spacer(Modifier.width(4.dp)) }
                    Text(if (row.msg.sendState == "sending") "Saving…" else row.msg.createdAt?.let { Fmt.timeAgo(it) } ?: "", fontSize = 10.sp, color = Palette.Amber400)
                }
                if (row.msg.sendState == "failed") FailedLine(row.msg, Palette.Red700, cb, Modifier.padding(top = 4.dp))
            }
        }
        is TBubble -> MessageBubble(row.msg, row.album, channel, recovered, brokenVideos, cb)
    }
}

/** CSS `border border-dashed`: a 1dp dashed outline following the rounded shape. */
internal fun Modifier.dashedBorder(color: Color, radius: androidx.compose.ui.unit.Dp): Modifier = drawBehind {
    val w = 1.dp.toPx()
    val r = radius.toPx()
    drawRoundRect(
        color = color, topLeft = androidx.compose.ui.geometry.Offset(w / 2, w / 2),
        size = androidx.compose.ui.geometry.Size(size.width - w, size.height - w),
        cornerRadius = androidx.compose.ui.geometry.CornerRadius(r, r),
        style = Stroke(width = w, pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 3.dp.toPx()))),
    )
}

/** CSS `border-t border-dashed`: a 1dp dashed hairline across the full width. */
@Composable
internal fun DashedRule(color: Color, modifier: Modifier = Modifier) {
    Box(
        modifier.fillMaxWidth().height(1.dp).drawBehind {
            val y = size.height / 2
            drawLine(
                color, androidx.compose.ui.geometry.Offset(0f, y), androidx.compose.ui.geometry.Offset(size.width, y),
                strokeWidth = 1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(3.dp.toPx(), 3.dp.toPx())),
            )
        },
    )
}

@Composable
private fun DividerPill(text: String, line: Color, bg: Color, fg: Color, border: Color? = null) {
    val dark = Neema.colors.isDark
    val t = tint(bg, fg, border ?: bg)
    val rule = if (dark) Neema.colors.border else line
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        HorizontalDivider(Modifier.weight(1f), color = rule)
        Text(
            text, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = t.fg, maxLines = 3, overflow = TextOverflow.Ellipsis, textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 8.dp).widthIn(max = 280.dp).clip(RoundedCornerShape(50)).background(t.bg)
                .then(if (border != null || dark) Modifier.border(1.dp, t.border, RoundedCornerShape(50)) else Modifier)
                .padding(horizontal = 10.dp, vertical = 4.dp),
        )
        HorizontalDivider(Modifier.weight(1f), color = rule)
    }
}

// ═══════════════════════════ Message bubble ═══════════════════════════

@Composable
private fun MessageBubble(msg: ThreadMsg, album: List<ThreadMsg>?, channel: String?, recovered: Map<String, String>, brokenVideos: Set<String>, cb: ThreadCallbacks) {
    val inbound = msg.inbound
    val c = Neema.colors
    val bg = when {
        inbound -> if (c.isDark) c.bg2 else Color.White
        msg.sender == "ai" -> Hue.Slate800
        else -> Hue.BubbleGreen
    }
    val fg = when {
        inbound -> if (c.isDark) c.text else Palette.Ink
        msg.sender == "ai" -> Color.White
        else -> Hue.BubbleInk
    }
    val mediaUrl = recovered[msg.id] ?: msg.mediaUrl
    val isMedia = msg.mediaType != null && msg.mediaType != "note" && mediaUrl != null
    val shape = if (inbound) RoundedCornerShape(topStart = 4.dp, topEnd = 16.dp, bottomEnd = 16.dp, bottomStart = 16.dp)
    else RoundedCornerShape(topStart = 16.dp, topEnd = 4.dp, bottomEnd = 16.dp, bottomStart = 16.dp)

    // Swipe a bubble left→right (like WhatsApp) to reply to it.
    val density = LocalDensity.current
    val threshold = with(density) { 55.dp.toPx() }
    var drag by remember { mutableFloatStateOf(0f) }
    Column(Modifier.fillMaxWidth()) {
    Row(
        Modifier.fillMaxWidth()
            .pointerInput(msg.id) {
                detectHorizontalDragGestures(
                    onDragEnd = { if (drag > threshold) cb.onReply(msg); drag = 0f },
                    onDragCancel = { drag = 0f },
                ) { _, d -> drag = (drag + d).coerceIn(0f, threshold * 1.5f) }
            },
        horizontalArrangement = if (inbound) Arrangement.Start else Arrangement.End,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (drag > 8f) Icon(Icons.AutoMirrored.Filled.Reply, null, tint = c.muted.copy(alpha = (drag / threshold).coerceIn(0f, 1f)), modifier = Modifier.size(18.dp))
        CompositionLocalProvider(LocalContentColor provides fg) {
            Column(
                Modifier.offset { IntOffset(drag.roundToInt(), 0) }
                    .fillMaxWidth(if (isMedia) 0.65f else 0.75f).wrapContentWidth(if (inbound) Alignment.Start else Alignment.End)
                    .widthIn(max = if (isMedia) 360.dp else 560.dp)
                    .clip(shape).background(bg)
                    .then(if (inbound || (c.isDark && msg.sender == "ai")) Modifier.border(1.dp, if (c.isDark) c.border else Palette.Hairline2, shape) else Modifier)
                    .padding(if (isMedia) PaddingValues(6.dp) else PaddingValues(horizontal = 16.dp, vertical = 10.dp)),
            ) {
                if (!inbound) {
                    Text(
                        (if (msg.sender == "ai") "AI" else msg.agentName ?: "Agent").uppercase(),
                        fontSize = 10.sp, fontWeight = FontWeight.Medium, letterSpacing = 0.5.sp, color = fg.copy(alpha = 0.7f),
                        modifier = Modifier.padding(bottom = 4.dp, start = if (isMedia) 4.dp else 0.dp),
                    )
                }
                msg.replyTo?.let { QuoteStrip(it, inbound, fg) }
                BubbleBody(msg, mediaUrl, album, channel, inbound, fg, brokenVideos, cb)
                // Reading glass: the English under a foreign message (both directions).
                if (!msg.translation.isNullOrBlank()) {
                    val tc = when { inbound -> Palette.Stone500; msg.sender == "ai" -> Color.White.copy(alpha = 0.7f); else -> Hue.BubbleInk.copy(alpha = 0.7f) }
                    // `border-t border-dashed`: stone-200 / white/25 / #0a2e05/25.
                    val line = when {
                        inbound -> if (c.isDark) c.border else Palette.Stone200
                        msg.sender == "ai" -> Color.White.copy(alpha = 0.25f)
                        else -> Hue.BubbleInk.copy(alpha = 0.25f)
                    }
                    DashedRule(line, Modifier.padding(top = 6.dp))
                    Row(Modifier.padding(top = 4.dp)) {
                        Text("🌐 ", fontSize = 11.sp)
                        Text(msg.translation, fontSize = 11.sp, lineHeight = 16.sp, fontStyle = FontStyle.Italic, color = tc, modifier = Modifier.weight(1f, fill = false))
                        msg.translatedFrom?.let { Text(" ${it.uppercase()}", fontSize = 9.sp, color = tc.copy(alpha = 0.6f), letterSpacing = 0.5.sp) }
                    }
                }
                Row(
                    Modifier.padding(top = 4.dp, start = if (isMedia) 4.dp else 0.dp, end = if (isMedia) 4.dp else 0.dp).align(if (inbound) Alignment.Start else Alignment.End),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    when {
                        msg.sendState == "failed" -> Icon(Icons.Filled.ErrorOutline, "Not sent", Modifier.size(12.dp), tint = if (msg.sender == "ai") Palette.Red300 else Palette.Red800)
                        msg.id.startsWith("optimistic-") -> Icon(Icons.Filled.Schedule, "Sending", Modifier.size(10.dp), tint = fg.copy(alpha = 0.6f))
                    }
                    Text(
                        when (msg.sendState) {
                            "sending" -> "Sending…"
                            "failed" -> "Not sent"
                            else -> msg.createdAt?.let { Fmt.timeAgo(it) } ?: ""
                        },
                        fontSize = 10.sp, fontWeight = if (msg.sendState == "failed") FontWeight.SemiBold else null,
                        color = when {
                            msg.sendState == "failed" -> if (msg.sender == "ai") Palette.Red300 else Palette.Red800
                            inbound -> if (c.isDark) c.muted else Palette.Sage300
                            else -> fg.copy(alpha = 0.6f)
                        },
                    )
                    // Reply to this message — a threaded quote (native on WhatsApp).
                    if (inbound && msg.body.isNotBlank()) {
                        Text(
                            "↩ Reply", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = if (c.isDark) c.textMid else Palette.Sage300,
                            modifier = Modifier.clip(RoundedCornerShape(4.dp)).clickable(onClickLabel = "Reply to this message") { cb.onReply(msg) },
                        )
                    }
                }
            }
        }
    }
    // Under a bubble that didn't go: why, and what to do about it. Nothing is lost.
    if (msg.sendState == "failed") FailedLine(msg, if (c.isDark) Palette.Red400 else Palette.Red700, cb, Modifier.fillMaxWidth().padding(top = 2.dp), end = true)
    }
}

/** "Not delivered — … · Retry · Edit" under a send that didn't go. */
@Composable
private fun FailedLine(msg: ThreadMsg, color: Color, cb: ThreadCallbacks, modifier: Modifier = Modifier, end: Boolean = false) {
    Row(modifier, horizontalArrangement = if (end) Arrangement.End else Arrangement.Start, verticalAlignment = Alignment.CenterVertically) {
        Text(msg.sendError ?: "Not sent", fontSize = 11.sp, lineHeight = 15.sp, color = color, modifier = Modifier.weight(1f, fill = false), textAlign = if (end) TextAlign.End else TextAlign.Start)
        Spacer(Modifier.width(8.dp))
        Text(
            "Retry", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Palette.Moss600,
            modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClickLabel = "Send it again") { cb.onRetrySend(msg.id) }.padding(horizontal = 6.dp, vertical = 4.dp),
        )
        Text(
            "Edit", fontSize = 12.sp, fontWeight = FontWeight.Medium, color = Neema.colors.muted,
            modifier = Modifier.clip(RoundedCornerShape(6.dp)).clickable(onClickLabel = "Edit the message") { cb.onEditFailed(msg.id) }.padding(horizontal = 6.dp, vertical = 4.dp),
        )
    }
}

/** WhatsApp-style quote: text left, the quoted photo's real thumbnail right. */
@Composable
private fun QuoteStrip(q: QuotedRef, inbound: Boolean, fg: Color) {
    val img = if (q.mediaType == "image" && q.mediaUrl != null) q.mediaUrl else null
    val raw = q.text?.trim().orEmpty()
    val text = when {
        raw.isNotEmpty() && raw != "[image]" -> raw
        img != null -> "📷 Photo"
        q.mediaType != null -> "[${q.mediaType}]"
        else -> "(media)"
    }
    Row(
        Modifier.padding(bottom = 6.dp).clip(RoundedCornerShape(3.dp))
            .background(if (inbound) (if (Neema.colors.isDark) Palette.Moss600.copy(alpha = 0.16f) else Hue.SageQuote) else Color.White.copy(alpha = 0.14f))
            .border(width = 0.dp, color = Color.Transparent),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.width(2.dp).height(40.dp).background(if (inbound) Palette.Moss600 else Color.White.copy(alpha = 0.55f)))
        Column(Modifier.weight(1f, fill = false).padding(horizontal = 6.dp, vertical = 2.dp)) {
            Text(
                when (q.sender) { "user" -> "CUSTOMER"; "ai" -> "NEEMA"; else -> "YOU" },
                fontSize = 9.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.5.sp, color = fg.copy(alpha = 0.7f),
            )
            Text(text, fontSize = 11.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, color = fg.copy(alpha = 0.8f))
        }
        if (img != null) AsyncImage(img, "quoted", contentScale = ContentScale.Crop, modifier = Modifier.padding(4.dp).size(40.dp).clip(RoundedCornerShape(4.dp)))
    }
}

@Composable
private fun BubbleBody(
    msg: ThreadMsg, mu: String?, album: List<ThreadMsg>?, channel: String?, inbound: Boolean, fg: Color,
    brokenVideos: Set<String>, cb: ThreadCallbacks,
) {
    val cctx = msg.commentContext
    val raw = msg.body
    val link = if (inbound) (if (Neema.colors.isDark) Hue.Blue300 else Palette.Blue600) else if (msg.sender == "ai") Hue.Blue300 else Hue.Emerald900
    // Our public reply to a comment: threaded (↳ indented) under the comment.
    if (cctx?.replyTo != null) {
        Row(Modifier.height(IntrinsicSize.Min)) {
            Box(Modifier.width(2.dp).fillMaxHeight().background(Palette.Amber300.copy(alpha = 0.6f)))
            Text("↳ ", color = Palette.Amber400, modifier = Modifier.padding(start = 6.dp))
            Text(rememberWa(raw, link), fontSize = 12.sp, lineHeight = 19.5.sp)
        }
        return
    }
    // An inbound comment: its post heads the run; the comment itself here.
    val isComment = (cctx != null && (cctx.title != null || cctx.postId != null)) || raw.startsWith("[comment]")
    if (isComment) {
        val body = raw.replace(Regex("^\\[comment]\\s*"), "")
        if (body.isNotEmpty()) Text(rememberWa(body, link), fontSize = 12.sp, lineHeight = 19.5.sp)
        return
    }
    val mt = msg.mediaType
    if (mt == null || mu == null) {
        // A media message whose URL never landed: say what was sent, offer to fetch it back.
        val kind = when (mt) { "video" -> "video"; "image" -> "image"; else -> null }
        if (kind != null && mu == null) { MediaFallback(kind, msg.id, inbound, cb.onRecover) { }; return }
        if (raw.isBlank()) {
            Text(
                "Message can't be displayed (unsupported type) — ask them to resend as text.",
                fontSize = 12.sp, lineHeight = 19.5.sp, fontStyle = FontStyle.Italic, color = Palette.Stone400,
            )
            return
        }
        Text(rememberWa(raw, link), fontSize = 12.sp, lineHeight = 19.5.sp)
        return
    }
    when {
        mt == "image" || mt.startsWith("image/") -> {
            if (album != null) {
                val items = album.map { m ->
                    AlbumItem(m.mediaUrl ?: "", m.body.trim().takeIf { it.isNotEmpty() && !it.startsWith("[") })
                }
                AlbumGrid(items) { i -> cb.onView(Viewer.Album(items, i)) }
                return
            }
            // media_caption = the AI's image analysis; text = the customer's own caption.
            // Legacy rows leaked the analysis into text — never show it as a caption.
            val analysis = msg.mediaCaption
            val caption = when {
                raw.isEmpty() || raw.startsWith("[") -> null
                analysis != null && raw.trim() == analysis.trim() -> null
                analysis != null && raw.trim().startsWith(analysis.trim().take(40)) -> null
                else -> raw
            }
            ImageBubble(mu, analysis, caption, inbound, msg.id, cb.onView, cb.onRecover)
        }
        mt == "sticker" -> AsyncImage(mu, "sticker", contentScale = ContentScale.Fit, modifier = Modifier.size(120.dp).clickable { cb.onView(Viewer.Image(mu)) })
        mt == "video" || mt.startsWith("video/") ->
            VideoBubble(mu, raw.takeIf { it.isNotEmpty() && !it.startsWith("[") }, inbound, msg.id, brokenVideos, cb.onView, cb.onRecover)
        mt == "audio" || mt.startsWith("audio/") -> {
            // inbound: the Whisper transcript lands in text; outbound: text = the AI's
            // spoken reply, media_caption = the cart summary.
            val transcription = raw.takeIf { it.isNotEmpty() && !it.startsWith("[") }
            AudioBubble(mu, transcription, if (!inbound) msg.mediaCaption else null, inbound)
        }
        else -> {
            val name = raw.takeIf { it.isNotBlank() && !it.startsWith("[") } ?: msg.filename ?: mu.substringAfterLast('/').substringBefore('?').ifBlank { "file" }
            DocumentTile(mu, name, inbound)
        }
    }
}

// ═══════════════════════════ Header ═══════════════════════════

/**
 * Who may do what in the open thread — exactly the web's rules
 * (ConversationsView.tsx): admin/superuser, or the "agent" role, handles
 * conversations; ownership decides the rest per thread.
 */
data class InboxPerms(
    val me: String?,
    val isAdminOrSuper: Boolean,
    val canHandle: Boolean,
)

/**
 * Which of the open thread's controls this agent sees — ConversationsView.tsx
 * line for line. Everything else in the thread (the per-message Reply, Ask
 * Neema, the team answer, invite, call, the whole customer panel) the web
 * shows to every signed-in agent, and so does the app.
 */
internal data class ThreadControls(
    val intercept: Boolean,
    val pickUp: Boolean,
    val release: Boolean,
    val pause: Boolean,
    val resume: Boolean,
    val transfer: Boolean,
    val note: Boolean,
    val clearHistory: Boolean,
    /** The reply box (with the AI draft, attachments, translation). */
    val composer: Boolean,
    /** The 🔒 header badge and the "Handled by …" banner. */
    val locked: Boolean,
)

internal fun threadControls(conv: Conversation, perms: InboxPerms): ThreadControls {
    val mode = conv.interceptMode
    // isOwner: this agent intercepted it; ownedByOther: a different agent holds it.
    val isOwner = conv.assignedAgentId != null && conv.assignedAgentId == perms.me
    val ownedByOther = mode == "human" && conv.assignedAgentId != null && conv.assignedAgentId != perms.me
    // canActOnThisConv — Pause / Resume / Transfer: owner, admin, or nobody human holds it.
    val canAct = perms.canHandle && (isOwner || perms.isAdminOrSuper || mode != "human")
    return ThreadControls(
        // Any agent can intercept an AI conversation — whoever picks it up owns it.
        intercept = mode == "ai" && perms.canHandle,
        // Auto-escalated (media) but unclaimed: first one to tap gets it.
        pickUp = mode == "human" && conv.assignedAgentId == null && perms.canHandle,
        // Owner-restricted: only the intercepting agent or admin can release.
        release = mode == "human" && (isOwner || perms.isAdminOrSuper),
        pause = mode != "paused" && canAct,
        resume = mode == "paused" && canAct,
        transfer = canAct,
        note = perms.canHandle,
        // Admin/superuser only — and the server (DELETE /messages) refuses anyone else.
        clearHistory = perms.isAdminOrSuper,
        composer = mode == "human" && (isOwner || perms.isAdminOrSuper),
        // Regular agents see who holds it; admins never see the lock.
        locked = ownedByOther && !perms.isAdminOrSuper,
    )
}

internal data class HeaderAction(
    val label: String,
    val emoji: String,
    val busyKey: String? = null,
    /** The web Btn variant: primary (amber) vs secondary. */
    val primary: Boolean = false,
    /** Phone: the one state-changing action kept one tap away beside the badges. */
    val pin: Boolean = primary,
    val danger: Boolean = false,
    val onClick: () -> Unit,
)

@Composable
internal fun ThreadHeader(
    conv: Conversation,
    siblings: List<Conversation>,
    perms: InboxPerms,
    convBusy: String,
    wide: Boolean,
    actions: List<HeaderAction>,
    menu: List<Pair<String, () -> Unit>>,
    locked: String?,
    showBack: Boolean,
    onBack: () -> Unit,
    canCall: Boolean,
    onCall: () -> Unit,
    onProfile: (() -> Unit)?,
    onSwitch: (Conversation) -> Unit,
    modifier: Modifier = Modifier,
) {
    val c = Neema.colors
    val name = inboxName(conv)
    Column(Modifier.fillMaxWidth().background(c.bg2).then(modifier).padding(horizontal = 8.dp, vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (showBack) IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "Back", tint = c.muted) }
            else Spacer(Modifier.width(8.dp))
            Avatar(name, conv.avatarUrl, size = 32.dp)
            Spacer(Modifier.width(10.dp))
            Column(Modifier.weight(1f)) {
                Text(name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                // A Meta thread has no wa_id (its key is a PSID): no empty second line under the name.
                inboxHandle(conv).takeIf { it.isNotBlank() }?.let { h ->
                    Text(h, fontSize = 12.sp, color = Palette.Sage300, fontFamily = if (isWebVisitor(conv.waId)) null else FontFamily.Monospace, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            if (canCall) IconButton(onClick = onCall) { Icon(Icons.Filled.Call, "Call on WhatsApp", tint = ChannelColors.WhatsApp) }
            if (onProfile != null) IconButton(onClick = onProfile) { Icon(Icons.Filled.Person, "View customer profile", tint = Palette.Moss700) }
            var open by remember { mutableStateOf(false) }
            val items = (if (wide) emptyList() else actions.filterNot { it.pin }.map { a -> "${a.emoji} ${a.label}" to a.onClick }) + menu
            if (items.isNotEmpty()) Box {
                IconButton(onClick = { open = true }) { Icon(Icons.Filled.MoreVert, "More", tint = c.muted) }
                DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
                    items.forEach { (label, act) ->
                        DropdownMenuItem(text = { Text(label, fontSize = 14.sp) }, onClick = { open = false; act() })
                    }
                }
            }
        }
        Row(Modifier.padding(start = 8.dp, top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        FlowRowCompat(Modifier.weight(1f)) {
            InterceptBadge(conv.interceptMode)
            // The web shows "→ agent" only on large screens (hidden lg:block).
            if (wide && conv.assignedAgentId != null && conv.assignedAgentName != null) {
                Text("→ ${conv.assignedAgentName}", fontSize = 12.sp, color = Palette.Sage300)
            }
            if (locked != null) {
                Text(
                    "🔒 $locked", fontSize = 12.sp, color = if (Neema.colors.isDark) Neema.colors.muted else Palette.Stone400,
                    modifier = Modifier.clip(RoundedCornerShape(6.dp))
                        .background(if (Neema.colors.isDark) Neema.colors.bg3 else Palette.Stone100).padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
            // The same person on other channels: one tap switches the thread.
            if (siblings.size > 1) siblings.forEach { s ->
                val st = channelStyle(s.channel)
                val open = s.id == conv.id
                Text(
                    CH_SHORT[s.channel] ?: st.label, fontSize = 10.sp, fontWeight = FontWeight.Bold,
                    color = if (open) Color.White else ink(st.color), maxLines = 1,
                    modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(if (open) st.color else st.color.copy(alpha = if (c.isDark) 0.16f else 0.08f))
                        .border(1.dp, if (open) st.color else st.color.copy(alpha = if (c.isDark) 0.45f else 0.2f), RoundedCornerShape(4.dp))
                        .clickable(enabled = !open, onClickLabel = "Open the ${st.label} thread") { onSwitch(s) }.padding(horizontal = 6.dp, vertical = 2.dp),
                )
            }
            if (wide) actions.forEach { HeaderButton(it, convBusy, compact = false) }
        }
        // Phone: the one state-changing action stays one tap away, beside the badges.
        if (!wide) actions.firstOrNull { it.pin }?.let { a -> Spacer(Modifier.width(8.dp)); HeaderButton(a, convBusy, compact = true) }
        }
    }
}

@Composable
private fun HeaderButton(a: HeaderAction, convBusy: String, @Suppress("UNUSED_PARAMETER") compact: Boolean) {
    WebBtn(
        label = a.label.ifEmpty { null }, lead = a.emoji,
        variant = when { a.primary -> BtnVariant.Primary; a.danger -> BtnVariant.Danger; else -> BtnVariant.Secondary },
        // Exactly-once: while one control is in flight every control that changes state waits.
        enabled = a.busyKey == null || convBusy.isEmpty(),
        busy = a.busyKey != null && convBusy == a.busyKey,
        onClick = a.onClick,
    )
}

/** components/ui/Btn.tsx variants — primary is AMBER there, not moss. */
internal enum class BtnVariant { Primary, Secondary, Danger, Ghost, Outline }

/** components/ui/Btn.tsx sizes: `sm` (h-8, px-3, text-xs) and the default `md` (h-9, px-4, text-sm). */
internal enum class BtnSize(val height: androidx.compose.ui.unit.Dp, val padX: androidx.compose.ui.unit.Dp, val font: androidx.compose.ui.unit.TextUnit) {
    Sm(32.dp, 12.dp, 12.sp),
    /** What the web's modals use (`<Btn>` with no size): 36 high, 14sp. */
    Md(36.dp, 16.dp, 14.sp),
}

/**
 * The web's `<Btn>`: rounded-lg, medium weight, gap-1.5, disabled at 40 % —
 * in each variant's own light and dark colours. [BtnSize.Sm] is `<Btn small>`
 * (thread header, draft panel); modals use the default [BtnSize.Md].
 */
@Composable
internal fun WebBtn(
    label: String?,
    variant: BtnVariant,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    lead: String? = null,
    enabled: Boolean = true,
    busy: Boolean = false,
    size: BtnSize = BtnSize.Sm,
) {
    val dark = Neema.colors.isDark
    val (bg, fg, bd) = when (variant) {
        BtnVariant.Primary -> Triple(Palette.Amber500, Color.White, Palette.Amber500)
        BtnVariant.Secondary -> if (dark) Triple(Hue.Gray800, Palette.Gray200, Palette.Gray700) else Triple(Color.White, Palette.Gray700, Palette.Gray200)
        BtnVariant.Danger -> if (dark) Triple(Hue.Red950.copy(alpha = 0.3f), Palette.Red400, Palette.Red800) else Triple(Palette.Red50, Palette.Red600, Palette.Red200)
        BtnVariant.Ghost -> Triple(Color.Transparent, if (dark) Palette.Gray400 else Palette.Gray500, Color.Transparent)
        BtnVariant.Outline -> Triple(Color.Transparent, if (dark) Palette.Gray200 else Palette.Gray700, if (dark) Palette.Gray600 else Palette.Gray300)
    }
    val shape = RoundedCornerShape(8.dp)
    Row(
        modifier.heightIn(min = size.height).alpha(if (enabled) 1f else 0.4f).clip(shape).background(bg).border(1.dp, bd, shape)
            .clickable(enabled = enabled && !busy, onClick = onClick).padding(horizontal = size.padX, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        if (busy) CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp, color = fg)
        else if (lead != null) Text(lead, fontSize = size.font, color = fg, maxLines = 1)
        if (label != null) Text(label, fontSize = size.font, fontWeight = FontWeight.Medium, color = fg, maxLines = 1)
    }
}

/** AI / Human / Paused (components/ui/Badges.tsx InterceptBadge), light and dark. */
@Composable
internal fun InterceptBadge(mode: String) {
    val dark = Neema.colors.isDark
    val (bg, fg, bd, label) = when (mode) {
        "human" -> if (dark) Quad(Hue.Amber950.copy(alpha = 0.4f), Palette.Amber400, Palette.Amber800, "Human")
        else Quad(Palette.Amber50, Palette.Amber700, Palette.Amber200, "Human")
        "paused" -> if (dark) Quad(Hue.Gray800, Palette.Gray400, Palette.Gray700, "Paused")
        else Quad(Palette.Gray100, Palette.Gray500, Palette.Gray200, "Paused")
        else -> if (dark) Quad(Hue.Blue950.copy(alpha = 0.4f), Palette.Blue400, Hue.Blue800, "AI")
        else Quad(Palette.Blue50, Palette.Blue700, Palette.Blue200, "AI")
    }
    Text(
        label, fontSize = 11.sp, lineHeight = 14.sp, fontWeight = FontWeight.Medium, color = fg, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(bg).border(1.dp, bd, RoundedCornerShape(4.dp)).padding(horizontal = 8.dp, vertical = 2.dp),
    )
}

internal data class Quad<A, B, C, D>(val a: A, val b: B, val c: C, val d: D)

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun FlowRowCompat(modifier: Modifier = Modifier, spacing: androidx.compose.ui.unit.Dp = 6.dp, content: @Composable () -> Unit) {
    FlowRow(modifier, horizontalArrangement = Arrangement.spacedBy(spacing), verticalArrangement = Arrangement.spacedBy(spacing), itemVerticalAlignment = Alignment.CenterVertically) { content() }
}

internal val CH_SHORT = mapOf(
    "whatsapp" to "WA", "messenger" to "MSG", "facebook" to "FB", "instagram" to "IG",
    "tiktok" to "TT", "email" to "Email", "sms" to "SMS",
)
