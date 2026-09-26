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

// ═══════════════════════════ Thread rows ═══════════════════════════

/** One rendered line of the thread. */
internal sealed interface TRow { val key: String }
internal data class TNewDivider(val n: Int, override val key: String = "new-divider") : TRow
internal data class TPostHead(val ctx: PostContext, override val key: String) : TRow
internal data class TEscalated(val msg: ThreadMsg, val reason: String, override val key: String = msg.id) : TRow
internal data class TFlag(val msg: ThreadMsg, override val key: String = msg.id) : TRow
internal data class TPill(val msg: ThreadMsg, override val key: String = msg.id) : TRow
internal data class TNote(val msg: ThreadMsg, override val key: String = msg.id) : TRow
internal data class TBubble(val msg: ThreadMsg, val album: List<ThreadMsg>?, override val key: String = msg.id) : TRow

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

    Box(modifier.background(if (Neema.colors.isDark) Neema.colors.bg else Color(0xFFF5F7F2))) {
        when {
            loading && messages.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator(Modifier.size(22.dp), strokeWidth = 2.dp, color = Neema.colors.gold)
            }
            error && messages.isEmpty() -> Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Text("Couldn't load this conversation.", fontSize = 14.sp, color = Color(0xFFB45309))
                errorText?.takeIf { it != "Couldn't load this conversation." }?.let {
                    Text(it, fontSize = 12.sp, color = Neema.colors.muted, textAlign = TextAlign.Center, modifier = Modifier.padding(top = 4.dp, start = 24.dp, end = 24.dp))
                }
                Spacer(Modifier.height(8.dp))
                Button(onClick = cb.onRetry, colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFF59E0B))) { Text("Try again", fontSize = 12.sp) }
            }
            messages.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Text("No messages yet", fontSize = 14.sp, color = Color(0xFFC5D5BC))
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
                        if (loadingOlder) CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Color(0xFFC5D5BC))
                        else if (olderError) Text(
                            "Couldn't load older messages — tap to retry", fontSize = 11.sp, fontWeight = FontWeight.Medium, color = Color(0xFFB45309),
                            modifier = Modifier.clip(RoundedCornerShape(50)).clickable(onClickLabel = "Retry loading older messages", onClick = cb.onLoadOlder).padding(horizontal = 10.dp, vertical = 4.dp),
                        )
                        else Text("↑ scroll for older messages", fontSize = 10.sp, color = Color(0xFFA8A29E))
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
            line = Color(0xFF427425).copy(alpha = 0.3f), bg = Color(0xFFE6F3D8), fg = Color(0xFF427425),
        )
        is TPostHead -> Box(Modifier.fillMaxWidth(0.8f).padding(top = 8.dp)) {
            CommentContextCard(row.ctx, true, channel, "Your post — their comments below", cb.onView, cb.fetchVideo)
        }
        is TEscalated -> Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                HorizontalDivider(Modifier.weight(1f), color = Color(0xFFFDE68A))
                Row(
                    Modifier.padding(horizontal = 8.dp).clip(RoundedCornerShape(50)).background(Color(0xFFFFFBEB))
                        .border(1.dp, Color(0xFFFDE68A), RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(Modifier.size(6.dp).clip(CircleShape).background(Color(0xFFFBBF24)))
                    Spacer(Modifier.width(6.dp))
                    Text("Escalated to agent", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFB45309))
                    Text(" · ${if (row.msg.createdAt != null) Fmt.timeAgo(row.msg.createdAt) else ""}", fontSize = 9.sp, color = Color(0xFFFBBF24))
                }
                HorizontalDivider(Modifier.weight(1f), color = Color(0xFFFDE68A))
            }
            Text(row.reason, fontSize = 10.sp, color = Color(0xFFD97706), textAlign = TextAlign.Center, lineHeight = 14.sp, modifier = Modifier.fillMaxWidth(0.72f).padding(top = 4.dp))
        }
        is TFlag -> DividerPill(
            "🚩 Flagged: Needs Attention" + (row.msg.createdAt?.let { " · ${Fmt.timeAgo(it)}" } ?: ""),
            line = Color(0xFFFEE2E2), bg = Color(0xFFFEE2E2), fg = Color(0xFFB91C1C),
        )
        is TPill -> {
            val (bg, bd, fg) = when (row.msg.eventKind) {
                "release" -> Triple(Color(0xFFEFF6FF), Color(0xFFBFDBFE), Color(0xFF1D4ED8))
                "transfer" -> Triple(Color(0xFFEEF2FF), Color(0xFFC7D2FE), Color(0xFF4338CA))
                "approve_draft" -> Triple(Color(0xFFF0FDF4), Color(0xFFBBF7D0), Color(0xFF15803D))
                else -> Triple(Color(0xFFF5F5F4), Color(0xFFE7E5E4), Color(0xFF57534E))
            }
            DividerPill(row.msg.body + (row.msg.createdAt?.let { " · ${Fmt.timeAgo(it)}" } ?: ""), line = Color(0xFFE7E5E4), bg = bg, fg = fg, border = bd)
        }
        is TNote -> Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            Column(
                Modifier.fillMaxWidth(0.85f).clip(RoundedCornerShape(12.dp)).background(Color(0xFFFFFBEB))
                    .dashedBorder(Color(0xFFFDE68A), 12.dp).padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("📝", fontSize = 12.sp)
                    Spacer(Modifier.width(6.dp))
                    Text("INTERNAL NOTE", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.5.sp, color = Color(0xFFD97706))
                }
                Spacer(Modifier.height(4.dp))
                Text(row.msg.body, fontSize = 12.sp, lineHeight = 17.sp, color = Color(0xFF92400E))
                Row(Modifier.padding(top = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (row.msg.sendState == "sending") { Icon(Icons.Filled.Schedule, "Saving", Modifier.size(10.dp), tint = Color(0xFFFBBF24)); Spacer(Modifier.width(4.dp)) }
                    Text(if (row.msg.sendState == "sending") "Saving…" else row.msg.createdAt?.let { Fmt.timeAgo(it) } ?: "", fontSize = 10.sp, color = Color(0xFFFBBF24))
                }
                if (row.msg.sendState == "failed") FailedLine(row.msg, Color(0xFFB91C1C), cb, Modifier.padding(top = 4.dp))
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
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        HorizontalDivider(Modifier.weight(1f), color = line)
        Text(
            text, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = fg, maxLines = 2, textAlign = TextAlign.Center,
            modifier = Modifier.padding(horizontal = 8.dp).widthIn(max = 280.dp).clip(RoundedCornerShape(50)).background(bg)
                .then(if (border != null) Modifier.border(1.dp, border, RoundedCornerShape(50)) else Modifier)
                .padding(horizontal = 10.dp, vertical = 4.dp),
        )
        HorizontalDivider(Modifier.weight(1f), color = line)
    }
}

// ═══════════════════════════ Message bubble ═══════════════════════════

@Composable
private fun MessageBubble(msg: ThreadMsg, album: List<ThreadMsg>?, channel: String?, recovered: Map<String, String>, brokenVideos: Set<String>, cb: ThreadCallbacks) {
    val inbound = msg.inbound
    val c = Neema.colors
    val bg = when {
        inbound -> if (c.isDark) c.bg2 else Color.White
        msg.sender == "ai" -> Color(0xFF1E293B)
        else -> Color(0xFF2AD113)
    }
    val fg = when {
        inbound -> if (c.isDark) c.text else Color(0xFF1C2917)
        msg.sender == "ai" -> Color.White
        else -> Color(0xFF0A2E05)
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
                    .clip(shape).background(bg)
                    .then(if (inbound || (c.isDark && msg.sender == "ai")) Modifier.border(1.dp, if (c.isDark) c.border else Color(0xFFEDF0EA), shape) else Modifier)
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
                    val tc = when { inbound -> Color(0xFF78716C); msg.sender == "ai" -> Color.White.copy(alpha = 0.7f); else -> Color(0xFF0A2E05).copy(alpha = 0.7f) }
                    // `border-t border-dashed`: stone-200 / white/25 / #0a2e05/25.
                    val line = when {
                        inbound -> if (c.isDark) c.border else Color(0xFFE7E5E4)
                        msg.sender == "ai" -> Color.White.copy(alpha = 0.25f)
                        else -> Color(0xFF0A2E05).copy(alpha = 0.25f)
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
                        msg.sendState == "failed" -> Icon(Icons.Filled.ErrorOutline, "Not sent", Modifier.size(12.dp), tint = if (msg.sender == "ai") Color(0xFFFCA5A5) else Color(0xFF991B1B))
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
                            msg.sendState == "failed" -> if (msg.sender == "ai") Color(0xFFFCA5A5) else Color(0xFF991B1B)
                            inbound -> Color(0xFFB5C9A8)
                            else -> fg.copy(alpha = 0.6f)
                        },
                    )
                    // Reply to this message — a threaded quote (native on WhatsApp).
                    if (inbound && msg.body.isNotBlank()) {
                        Text("↩ Reply", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = Color(0xFFB5C9A8), modifier = Modifier.clickable { cb.onReply(msg) })
                    }
                }
            }
        }
    }
    // Under a bubble that didn't go: why, and what to do about it. Nothing is lost.
    if (msg.sendState == "failed") FailedLine(msg, if (c.isDark) Color(0xFFF87171) else Color(0xFFB91C1C), cb, Modifier.fillMaxWidth().padding(top = 2.dp), end = true)
    }
}

/** "Not delivered — … · Retry · Edit" under a send that didn't go. */
@Composable
private fun FailedLine(msg: ThreadMsg, color: Color, cb: ThreadCallbacks, modifier: Modifier = Modifier, end: Boolean = false) {
    Row(modifier, horizontalArrangement = if (end) Arrangement.End else Arrangement.Start, verticalAlignment = Alignment.CenterVertically) {
        Text(msg.sendError ?: "Not sent", fontSize = 11.sp, lineHeight = 15.sp, color = color, modifier = Modifier.weight(1f, fill = false), textAlign = if (end) TextAlign.End else TextAlign.Start)
        Spacer(Modifier.width(8.dp))
        Text(
            "Retry", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFF589B31),
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
            .background(if (inbound) (if (Neema.colors.isDark) Color(0xFF589B31).copy(alpha = 0.16f) else Color(0xFFF2F7EE)) else Color.White.copy(alpha = 0.14f))
            .border(width = 0.dp, color = Color.Transparent),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.width(2.dp).height(40.dp).background(if (inbound) Color(0xFF589B31) else Color.White.copy(alpha = 0.55f)))
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
    val link = if (inbound) (if (Neema.colors.isDark) Color(0xFF93C5FD) else Color(0xFF2563EB)) else if (msg.sender == "ai") Color(0xFF93C5FD) else Color(0xFF064E3B)
    // Our public reply to a comment: threaded (↳ indented) under the comment.
    if (cctx?.replyTo != null) {
        Row(Modifier.height(IntrinsicSize.Min)) {
            Box(Modifier.width(2.dp).fillMaxHeight().background(Color(0xFFFCD34D).copy(alpha = 0.6f)))
            Text("↳ ", color = Color(0xFFFBBF24), modifier = Modifier.padding(start = 6.dp))
            Text(formatWa(raw, link), fontSize = 12.sp, lineHeight = 19.5.sp)
        }
        return
    }
    // An inbound comment: its post heads the run; the comment itself here.
    val isComment = (cctx != null && (cctx.title != null || cctx.postId != null)) || raw.startsWith("[comment]")
    if (isComment) {
        val body = raw.replace(Regex("^\\[comment]\\s*"), "")
        if (body.isNotEmpty()) Text(formatWa(body, link), fontSize = 12.sp, lineHeight = 19.5.sp)
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
                fontSize = 12.sp, lineHeight = 19.5.sp, fontStyle = FontStyle.Italic, color = Color(0xFFA8A29E),
            )
            return
        }
        Text(formatWa(raw, link), fontSize = 12.sp, lineHeight = 19.5.sp)
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
                    Text(h, fontSize = 12.sp, color = Color(0xFFB5C9A8), fontFamily = if (isWebVisitor(conv.waId)) null else FontFamily.Monospace, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            if (canCall) IconButton(onClick = onCall) { Icon(Icons.Filled.Call, "Call on WhatsApp", tint = Color(0xFF25D366)) }
            if (onProfile != null) IconButton(onClick = onProfile) { Icon(Icons.Filled.Person, "View customer profile", tint = Color(0xFF427425)) }
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
                Text("→ ${conv.assignedAgentName}", fontSize = 12.sp, color = Color(0xFFB5C9A8))
            }
            if (locked != null) {
                Text(
                    "🔒 $locked", fontSize = 12.sp, color = Color(0xFFA8A29E),
                    modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Color(0xFFF5F5F4)).padding(horizontal = 8.dp, vertical = 3.dp),
                )
            }
            // The same person on other channels: one tap switches the thread.
            if (siblings.size > 1) siblings.forEach { s ->
                val st = channelStyle(s.channel)
                val open = s.id == conv.id
                Text(
                    CH_SHORT[s.channel] ?: st.label, fontSize = 10.sp, fontWeight = FontWeight.Bold,
                    color = if (open) Color.White else st.color,
                    modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(if (open) st.color else st.color.copy(alpha = 0.08f))
                        .border(1.dp, if (open) st.color else st.color.copy(alpha = 0.2f), RoundedCornerShape(4.dp))
                        .clickable(enabled = !open) { onSwitch(s) }.padding(horizontal = 6.dp, vertical = 2.dp),
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
        BtnVariant.Primary -> Triple(Color(0xFFF59E0B), Color.White, Color(0xFFF59E0B))
        BtnVariant.Secondary -> if (dark) Triple(Color(0xFF1F2937), Color(0xFFE5E7EB), Color(0xFF374151)) else Triple(Color.White, Color(0xFF374151), Color(0xFFE5E7EB))
        BtnVariant.Danger -> if (dark) Triple(Color(0xFF450A0A).copy(alpha = 0.3f), Color(0xFFF87171), Color(0xFF991B1B)) else Triple(Color(0xFFFEF2F2), Color(0xFFDC2626), Color(0xFFFECACA))
        BtnVariant.Ghost -> Triple(Color.Transparent, if (dark) Color(0xFF9CA3AF) else Color(0xFF6B7280), Color.Transparent)
        BtnVariant.Outline -> Triple(Color.Transparent, if (dark) Color(0xFFE5E7EB) else Color(0xFF374151), if (dark) Color(0xFF4B5563) else Color(0xFFD1D5DB))
    }
    val shape = RoundedCornerShape(8.dp)
    Row(
        modifier.height(size.height).alpha(if (enabled) 1f else 0.4f).clip(shape).background(bg).border(1.dp, bd, shape)
            .clickable(enabled = enabled && !busy, onClick = onClick).padding(horizontal = size.padX),
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
        "human" -> if (dark) Quad(Color(0xFF451A03).copy(alpha = 0.4f), Color(0xFFFBBF24), Color(0xFF92400E), "Human")
        else Quad(Color(0xFFFFFBEB), Color(0xFFB45309), Color(0xFFFDE68A), "Human")
        "paused" -> if (dark) Quad(Color(0xFF1F2937), Color(0xFF9CA3AF), Color(0xFF374151), "Paused")
        else Quad(Color(0xFFF3F4F6), Color(0xFF6B7280), Color(0xFFE5E7EB), "Paused")
        else -> if (dark) Quad(Color(0xFF172554).copy(alpha = 0.4f), Color(0xFF60A5FA), Color(0xFF1E40AF), "AI")
        else Quad(Color(0xFFEFF6FF), Color(0xFF1D4ED8), Color(0xFFBFDBFE), "AI")
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
