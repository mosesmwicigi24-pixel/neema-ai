package ke.co.bethanyhouse.neema.feature.calls

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.NotificationsActive
import androidx.compose.material.icons.filled.Pause
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.LifecycleResumeEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.media3.common.MediaItem
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import ke.co.bethanyhouse.neema.BuildConfig
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Call
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerPanel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive

// The console's palette (CallsView.tsx inline styles).
private val Green = Color(0xFF2AD17F)
private val RedC = Color(0xFFF2555A)
private val AmberC = Color(0xFFF5A623)
private val Muted = Color(0xFF7F9B8B)
private val Dim = Color(0xFF6B8577)
private val TextC = Color(0xFFE9EDEF)
private val Soft = Color(0xFFCFE9D9)
private val Sage = Color(0xFF9FB3A8)
private val Ink = Color(0xFF0B1410)

private enum class Dir { In, Back }
private data class Outcome(val label: String, val color: Color, val dir: Dir)

private val OUTCOME = mapOf(
    "answered" to Outcome("Answered", Green, Dir.In),
    "ended" to Outcome("Answered", Green, Dir.In),
    "missed" to Outcome("Missed", RedC, Dir.In),
    "declined" to Outcome("Declined", AmberC, Dir.In),
    "callback" to Outcome("Callback", AmberC, Dir.Back),
    "ringing" to Outcome("Ringing…", Green, Dir.In),
)

private val AV = listOf(0xFF3B6EA5, 0xFFA5417D, 0xFFB5892F, 0xFF3C8C5A, 0xFF8A4FC4, 0xFFB24A4A)

/**
 * The web's `avatarColor`: `[...s].reduce((a, c) => a + c.charCodeAt(0))` —
 * one term per code point, taking its FIRST UTF-16 unit (so an emoji adds its
 * high surrogate once, not both halves).
 */
internal fun avatarIndex(s: String): Int {
    val src = s.ifEmpty { "?" }
    var sum = 0
    var i = 0
    while (i < src.length) {
        sum += src[i].code
        i += Character.charCount(src.codePointAt(i))
    }
    return sum % AV.size
}
private fun avatarColor(s: String) = Color(AV[avatarIndex(s)])

/** The row's `who`: name, else +wa_id, else "Unknown" (a blank name falls through too). */
internal fun rowWho(c: Call): String =
    c.name?.takeIf { it.isNotBlank() } ?: c.waId?.takeIf { it.isNotEmpty() }?.let { "+$it" } ?: "Unknown"

/**
 * The row's initials: who minus its first "+", first letter of the first two
 * words, upper-cased. A word starting with an emoji keeps the whole emoji (the
 * web's w[0] takes half a surrogate pair and draws a broken glyph).
 */
internal fun initialsOf(who: String): String =
    who.replaceFirst("+", "").split(Regex("\\s+")).filter { it.isNotEmpty() }
        .map { firstGlyph(it) }.take(2).joinToString("").uppercase()

internal fun firstGlyph(s: String): String = if (s.isEmpty()) "" else s.substring(0, Character.charCount(s.codePointAt(0)))

private fun fmtDur(s: Int?): String = if (s == null || s == 0) "" else "${s / 60}:${(s % 60).toString().padStart(2, '0')}"

/** A recording_url is absolute when the server knows its public base, else a bare filename under /api/admin/media. */
private fun recordingUrl(raw: String): String =
    if (raw.startsWith("http://") || raw.startsWith("https://")) raw
    else "${BuildConfig.NEEMA_BASE_URL.trimEnd('/')}/api/admin/media/${raw.substringAfterLast('/')}"

/**
 * Calls — the "Calls · History" console (components/views/CallsView.tsx): a
 * dark call log with a live missed badge (tap to filter), colour-coded
 * outcomes, duration, the agent who took it, the transcript/summary expander
 * with recording playback, a chat shortcut, and the caller's CRM panel.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CallsScreen(
    dash: DashboardViewModel,
    /** Tests only: fixes what the system allows instead of asking it. */
    readinessOverride: CallReadiness? = null,
) {
    val vm: CallsViewModel = viewModel { CallsViewModel(dash) }
    val calls by vm.calls.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val loadError by vm.loadError.collectAsStateWithLifecycle()
    val missedOnly by vm.missedOnly.collectAsStateWithLifecycle()
    val selected by vm.selected.collectAsStateWithLifecycle()
    val transcript by vm.transcript.collectAsStateWithLifecycle()
    val focusKey by dash.callsFocusKey.collectAsStateWithLifecycle()

    LaunchedEffect(focusKey, calls) { focusKey?.let { if (calls != null) vm.consumeFocus(it) } }

    val list = calls
    val missed = list.orEmpty().count { it.status == "missed" }
    val shown = if (missedOnly) list?.filter { it.status == "missed" } else list
    val sel = selected?.takeIf { !it.waId.isNullOrEmpty() }
    val ctx = LocalContext.current
    var readiness by remember { mutableStateOf(readinessOverride ?: CallReadiness.of(ctx)) }
    // Re-check on return from the system settings page.
    LifecycleResumeEffect(readinessOverride) {
        readiness = readinessOverride ?: CallReadiness.of(ctx)
        onPauseOrDispose {}
    }

    BoxWithConstraints(Modifier.fillMaxSize().background(Neema.colors.surface)) {
        val wide = maxWidth >= 840.dp
        val sidePad = if (maxWidth >= 640.dp) 24.dp else 16.dp   // px-4 sm:px-6
        // Phone: the caller panel replaces the log; back returns to it.
        BackHandler(enabled = sel != null && !wide) { vm.select(null) }

        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            Row(
                Modifier.fillMaxSize().padding(horizontal = sidePad),
                horizontalArrangement = Arrangement.spacedBy(24.dp, Alignment.CenterHorizontally),
            ) {
                if (wide || sel == null) {
                    CallLog(
                        modifier = Modifier.widthIn(max = 560.dp).weight(1f, fill = false).fillMaxWidth(),
                        vm = vm, shown = shown, total = list?.size ?: 0, missed = missed, missedOnly = missedOnly,
                        selectedId = sel?.id, openTranscript = transcript,
                        readiness = readiness, loadError = loadError, refreshing = refreshing,
                        onOpenConversation = { dash.openConversationFor(it) },
                    )
                }
                if (sel != null) {
                    CallerPanel(
                        dash = dash, vm = vm, sel = sel, calls = list.orEmpty(),
                        modifier = if (wide) Modifier.width(400.dp) else Modifier.fillMaxWidth(),
                    )
                }
            }
        }
    }
}

@Composable
private fun CallLog(
    modifier: Modifier,
    vm: CallsViewModel,
    shown: List<Call>?,
    total: Int,
    missed: Int,
    missedOnly: Boolean,
    selectedId: String?,
    openTranscript: TranscriptUi?,
    readiness: CallReadiness,
    loadError: String?,
    refreshing: Boolean,
    onOpenConversation: (String) -> Unit,
) {
    // One card, as the web draws it: the log is at most 200 rows (the API's
    // cap; the web asks for the default 50), so a plain scrolling column keeps
    // the card's gradient, outline and shadow whole instead of slicing them
    // across lazy items.
    val cardShape = RoundedCornerShape(16.dp)
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(vertical = 24.dp)) {
        Column(
            Modifier
                .fillMaxWidth()
                // box-shadow: 0 20px 50px rgba(0,0,0,0.25)
                .shadow(20.dp, cardShape, ambientColor = Color.Black.copy(alpha = 0.25f), spotColor = Color.Black.copy(alpha = 0.25f))
                .clip(cardShape)
                .drawBehind {
                    // radial-gradient(120% 60% at 50% 0%, #123626 0%, #0b1410 60%)
                    drawTopEllipseGradient(1.2f, 0.6f, 0f to Color(0xFF123626), 0.6f to Ink, 1f to Ink)
                }
                // border: 1px solid rgba(37,211,102,0.14)
                .border(1.dp, Color(0x2425D366), cardShape),
        ) {
            // Header: title, total, and the missed badge (a filter toggle).
            Row(Modifier.fillMaxWidth().padding(start = 24.dp, end = 24.dp, top = 24.dp, bottom = 16.dp), verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    Text("Calls", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(2.dp))
                    Text("WhatsApp voice calls · $total total", color = Muted, fontSize = 13.sp)
                }
                if (missed > 0) {
                    Text(
                        "$missed missed" + if (missedOnly) " ✕" else "",
                        color = Color(0xFFFF8A8D), fontSize = 12.sp, fontWeight = FontWeight.Medium,
                        modifier = Modifier
                            .clip(RoundedCornerShape(50))
                            .background(if (missedOnly) Color(0x59F2555A) else Color(0x29F2555A))
                            .border(1.dp, if (missedOnly) Color(0x99F2555A) else Color.Transparent, RoundedCornerShape(50))
                            .clickable(onClickLabel = if (missedOnly) "Show all calls" else "Show only missed calls") {
                                vm.missedOnly.value = !missedOnly
                            }
                            .padding(horizontal = 11.dp, vertical = 5.dp),
                    )
                }
            }
            if (!readiness.ready) ReadinessBanner(readiness)
            // The log couldn't be refreshed: what we had stays, with the reason and a way to try again.
            if (loadError != null && !shown.isNullOrEmpty()) LoadErrorBanner(loadError, refreshing, vm::refresh)
            when {
                shown == null -> Text(
                    "Loading…", color = Muted, fontSize = 14.sp, textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 40.dp),
                )
                shown.isEmpty() && loadError != null -> Column(
                    Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 48.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("Couldn't load calls", color = Soft, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(6.dp))
                    Text(loadError, color = Muted, fontSize = 13.sp, textAlign = TextAlign.Center)
                    Spacer(Modifier.height(16.dp))
                    RetryButton(refreshing, vm::refresh)
                }
                shown.isEmpty() -> Column(
                    Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 56.dp),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Text("No calls yet", color = Soft, fontSize = 15.sp, fontWeight = FontWeight.Medium)
                    Spacer(Modifier.height(6.dp))
                    Text(
                        "Incoming WhatsApp voice calls appear here. Keep the dashboard open — a call takes over the screen when it rings.",
                        color = Muted, fontSize = 13.sp, textAlign = TextAlign.Center,
                    )
                }
                else -> shown.forEach { c ->
                    key(c.id.ifEmpty { c.callId }) {
                        // borderTop: 1px solid rgba(255,255,255,0.05)
                        Box(Modifier.fillMaxWidth().height(1.dp).background(Color(0x0DFFFFFF)))
                        CallRow(
                            c = c, selected = selectedId == c.id,
                            open = openTranscript?.callId == c.callId,
                            onSelect = { if (!c.waId.isNullOrEmpty()) vm.select(c) },
                            onToggleTranscript = { vm.toggleTranscript(c.callId) },
                            onOpenConversation = onOpenConversation,
                            ago = vm.ago(c.startedAt),
                        )
                        if (openTranscript?.callId == c.callId) TranscriptPanel(openTranscript, vm)
                    }
                }
            }
        }
    }
}

@Composable
private fun CallRow(
    c: Call,
    selected: Boolean,
    open: Boolean,
    onSelect: () -> Unit,
    onToggleTranscript: () -> Unit,
    onOpenConversation: (String) -> Unit,
    ago: String,
) {
    val o = OUTCOME[c.status] ?: OUTCOME.getValue("ended")
    val who = rowWho(c)
    val initials = initialsOf(who)
    val hasNote = !c.summary.isNullOrEmpty()
    Row(
        Modifier
            .fillMaxWidth()
            .background(if (selected) Color(0x1425D366) else Color.Transparent)
            .then(if (!c.waId.isNullOrEmpty()) Modifier.clickable(onClick = onSelect) else Modifier)
            .padding(horizontal = 24.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Box(Modifier.size(40.dp).clip(CircleShape).background(avatarColor(who)), contentAlignment = Alignment.Center) {
            Text(initials.ifEmpty { "?" }, color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.Medium)
        }
        Column(Modifier.weight(1f)) {
            Text(who, color = TextC, fontSize = 14.sp, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            // flex items-center gap-1.5
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.padding(top = 1.dp),
            ) {
                Icon(if (o.dir == Dir.Back) CallIcons.DirBack else CallIcons.DirIn, null, tint = o.color, modifier = Modifier.size(13.dp))
                // One run of text so a tight row trims the end ("· Mo…") rather
                // than dropping a whole part; an en space is the web's 6px gap at 12px.
                Text(statusLine(o, c), fontSize = 12.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
        Text(ago, color = Dim, fontSize = 11.sp)
        if (c.hasRecording) {
            RoundIcon(
                icon = CallIcons.Transcript, iconSize = 15.dp,
                label = if (hasNote) "Call summary & transcript" else "Call recording — transcribe & summarise",
                bg = when { open -> Color(0x3825D366); hasNote -> Color(0x1F25D366); else -> Color(0x0FFFFFFF) },
                tint = if (open || hasNote) Green else Sage,
                border = Color(0x1AFFFFFF),
                onClick = onToggleTranscript,
            )
        }
        if (!c.waId.isNullOrEmpty()) {
            RoundIcon(
                icon = CallIcons.Chat, iconSize = 16.dp,
                label = "Open the conversation in Neema",
                bg = Color(0x2925D366), tint = Green, border = Color(0x4D25D366),
                onClick = { onOpenConversation(c.waId!!) },
            )
        }
    }
}

/** "Answered · 3:04 · Moses": the outcome in its colour, duration and the agent's first name muted. */
private fun statusLine(o: Outcome, c: Call) = buildAnnotatedString {
    withStyle(SpanStyle(color = o.color)) { append(o.label) }
    withStyle(SpanStyle(color = Muted)) {
        fmtDur(c.duration).takeIf { it.isNotEmpty() }?.let { append("\u2002· $it") }
        c.agentName?.takeIf { it.isNotEmpty() }?.let { append("\u2002· ${it.split(" ").first()}") }
    }
}

@Composable
private fun RoundIcon(icon: ImageVector, iconSize: Dp, label: String, bg: Color, tint: Color, border: Color, onClick: () -> Unit) {
    Box(
        Modifier.size(34.dp).clip(CircleShape).background(bg).border(1.dp, border, CircleShape).clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) { Icon(icon, label, tint = tint, modifier = Modifier.size(iconSize)) }
}

/**
 * The expandable transcript + AI summary panel under a call row: summary,
 * full transcript toggle (with language), status lines, on-demand
 * transcription (the free path — CPU is spent only when you ask) and retry,
 * plus playback of the recording.
 */
@Composable
private fun TranscriptPanel(t: TranscriptUi, vm: CallsViewModel) {
    val pad = Modifier.padding(start = 68.dp, end = 24.dp, bottom = 16.dp)
    val data = t.data
    if (data == null) {
        val err = t.loadErr
        if (err == null) Text("Loading…", color = Muted, fontSize = 12.sp, modifier = pad)
        else Row(pad, verticalAlignment = Alignment.CenterVertically) {
            Text("$err ", color = RedC, fontSize = 12.sp, modifier = Modifier.weight(1f, fill = false))
            Text(
                "Retry", color = Green, fontSize = 12.sp, textDecoration = TextDecoration.Underline,
                modifier = Modifier.clickable { vm.retryTranscript() }.padding(vertical = 4.dp),
            )
        }
        return
    }
    val st = data.status
    Column(pad) {
        data.summary?.takeIf { it.isNotEmpty() }?.let { s ->
            Column(
                Modifier.fillMaxWidth().padding(bottom = 8.dp).clip(RoundedCornerShape(10.dp))
                    .background(Color(0x0F25D366)).border(1.dp, Color(0x2625D366), RoundedCornerShape(10.dp))
                    .padding(horizontal = 12.dp, vertical = 10.dp),
            ) {
                Text("CALL SUMMARY", color = Green, fontSize = 11.sp, letterSpacing = 0.6.sp)
                Spacer(Modifier.height(4.dp))
                Text(s, color = Soft, fontSize = 13.sp, lineHeight = 19.sp)
            }
        }
        if (st == "done" && !data.transcript.isNullOrEmpty()) {
            Text(
                (if (t.showFull) "Hide" else "Show") + " full transcript" + (data.language?.takeIf { it.isNotEmpty() }?.let { " · $it" } ?: ""),
                color = Muted, fontSize = 11.sp, modifier = Modifier.clickable { vm.toggleFull() }.padding(vertical = 2.dp),
            )
            if (t.showFull) Text(data.transcript!!, color = Sage, fontSize = 12.sp, lineHeight = 19.sp, modifier = Modifier.padding(top = 6.dp))
        }
        if (st == "pending" || st == "processing") {
            Text("Transcribing… this runs on our server, usually ~1–2 min.", color = Color(0xFFF5C451), fontSize = 12.sp)
        }
        if (st == "recorded") {
            Text(
                if (t.busy) "Starting…" else "Transcribe & summarise",
                color = Ink, fontSize = 12.sp, fontWeight = FontWeight.Medium,
                // opacity: busy ? 0.6 : 1 — the whole button, label included.
                modifier = Modifier.alpha(if (t.busy) 0.6f else 1f).clip(RoundedCornerShape(8.dp)).background(Green)
                    .clickable(enabled = !t.busy) { vm.runTranscribe() }
                    .padding(horizontal = 14.dp, vertical = 7.dp),
            )
        }
        if (st == "failed") {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Transcription failed. ", color = RedC, fontSize = 12.sp)
                Text(
                    "Retry", color = Green, fontSize = 12.sp, textDecoration = TextDecoration.Underline,
                    modifier = Modifier.clickable(enabled = !t.busy) { vm.runTranscribe() },
                )
            }
        }
        if (st == "none" && !data.hasRecording) {
            Text("No recording was captured for this call.", color = Muted, fontSize = 12.sp)
        }
        t.err?.let { Text(it, color = RedC, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp)) }
        data.recordingUrl?.takeIf { data.hasRecording && it.isNotEmpty() }?.let {
            Spacer(Modifier.height(8.dp))
            RecordingPlayer(recordingUrl(it))
        }
    }
}

/** The log is showing what it last had because a refresh failed. */
@Composable
private fun LoadErrorBanner(message: String, refreshing: Boolean, onRetry: () -> Unit) {
    Row(
        Modifier
            .padding(start = 24.dp, end = 24.dp, bottom = 12.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Color(0x1AF2555A))
            .border(1.dp, Color(0x40F2555A), RoundedCornerShape(12.dp))
            .padding(start = 14.dp, end = 8.dp, top = 8.dp, bottom = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text("Showing the last call log", color = TextC, fontSize = 13.sp, fontWeight = FontWeight.Medium)
            Text(message, color = Sage, fontSize = 12.sp, lineHeight = 17.sp)
        }
        Spacer(Modifier.width(8.dp))
        RetryButton(refreshing, onRetry)
    }
}

/** A small pill that retries a failed load; a spinner while it runs (no double taps). */
@Composable
private fun RetryButton(busy: Boolean, onClick: () -> Unit) {
    Box(
        Modifier.clip(RoundedCornerShape(50)).background(Color(0x2925D366))
            .border(1.dp, Color(0x4D25D366), RoundedCornerShape(50))
            .clickable(enabled = !busy, onClickLabel = "Retry", onClick = onClick)
            .padding(horizontal = 14.dp, vertical = 6.dp),
        contentAlignment = Alignment.Center,
    ) {
        if (busy) CircularProgressIndicator(Modifier.size(14.dp), color = Green, strokeWidth = 2.dp)
        else Text("Retry", color = Green, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

/**
 * Play / pause + scrubber for the call recording (ExoPlayer). The player is
 * only built on the first tap of Play, so opening a transcript costs nothing.
 */
@Composable
private fun RecordingPlayer(url: String) {
    val ctx = LocalContext.current
    var player by remember(url) { mutableStateOf<ExoPlayer?>(null) }
    var playing by remember { mutableStateOf(false) }
    var buffering by remember { mutableStateOf(false) }
    var failed by remember { mutableStateOf(false) }
    var pos by remember { mutableLongStateOf(0L) }
    var dur by remember { mutableLongStateOf(0L) }
    var scrub by remember { mutableFloatStateOf(-1f) }
    val p = player
    DisposableEffect(p) {
        if (p == null) return@DisposableEffect onDispose {}
        val l = object : Player.Listener {
            override fun onIsPlayingChanged(isPlaying: Boolean) { playing = isPlaying }
            override fun onPlaybackStateChanged(state: Int) {
                buffering = state == Player.STATE_BUFFERING
                if (state == Player.STATE_READY) dur = p.duration.coerceAtLeast(0)
                if (state == Player.STATE_ENDED) { p.pause(); p.seekTo(0) }
            }
            override fun onPlayerError(error: androidx.media3.common.PlaybackException) { failed = true }
        }
        p.addListener(l)
        onDispose { p.removeListener(l); p.release() }
    }
    LaunchedEffect(p, playing) {
        if (p == null) return@LaunchedEffect
        while (isActive && playing) { pos = p.currentPosition; delay(250) }
        pos = p.currentPosition
    }
    if (failed) {
        Text("Couldn't play the recording.", color = RedC, fontSize = 12.sp)
        return
    }
    PlayerBar(
        playing = playing, buffering = buffering,
        progress = if (scrub >= 0f) scrub else if (dur > 0) pos.toFloat() / dur else 0f,
        label = if (dur > 0) "${fmtMs(pos)} / ${fmtMs(dur)}" else fmtMs(pos),
        onToggle = {
            val cur = player ?: runCatching {
                ExoPlayer.Builder(ctx).build().apply { setMediaItem(MediaItem.fromUri(url)); prepare() }
            }.getOrElse { failed = true; null }.also { player = it }
            if (cur != null) { if (playing) cur.pause() else cur.play() }
        },
        onScrub = { scrub = it },
        onScrubDone = { if (dur > 0) { player?.seekTo((scrub * dur).toLong()); pos = (scrub * dur).toLong() }; scrub = -1f },
    )
}

@Composable
private fun PlayerBar(
    playing: Boolean,
    buffering: Boolean,
    progress: Float,
    label: String,
    onToggle: () -> Unit,
    onScrub: (Float) -> Unit,
    onScrubDone: () -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Color(0x0FFFFFFF)).padding(horizontal = 8.dp, vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(30.dp).clip(CircleShape).background(Green).clickable(onClick = onToggle),
            contentAlignment = Alignment.Center,
        ) {
            if (buffering) CircularProgressIndicator(Modifier.size(14.dp), color = Ink, strokeWidth = 2.dp)
            else Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (playing) "Pause" else "Play recording", tint = Ink, modifier = Modifier.size(18.dp))
        }
        Slider(
            value = progress,
            onValueChange = onScrub,
            onValueChangeFinished = onScrubDone,
            colors = SliderDefaults.colors(thumbColor = Green, activeTrackColor = Green, inactiveTrackColor = Color(0x33FFFFFF)),
            modifier = Modifier.weight(1f).padding(horizontal = 8.dp).heightIn(max = 32.dp),
        )
        Text(label, color = Muted, fontSize = 11.sp)
    }
}

private fun fmtMs(ms: Long): String { val s = (ms / 1000).toInt(); return "${s / 60}:${(s % 60).toString().padStart(2, '0')}" }

/** The caller panel: this caller's call-history strip, then the full CRM profile. */
@Composable
private fun CallerPanel(
    dash: DashboardViewModel,
    vm: CallsViewModel,
    sel: Call,
    calls: List<Call>,
    modifier: Modifier,
) {
    val wa = sel.waId!!
    val callerCalls = calls.filter { it.waId == wa }
    val callerMissed = callerCalls.count { it.status == "missed" }
    // A synthetic conversation handle is enough — the panel fetches the real CRM profile by wa_id itself.
    val conv = remember(sel.callId, wa, sel.name) {
        Conversation(
            id = "call:${sel.callId}", waId = wa, externalId = wa, channel = "whatsapp",
            name = sel.name, lastMessageAt = sel.startedAt,
        )
    }
    Column(modifier.fillMaxSize().padding(vertical = 24.dp)) {
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(Ink)
                .border(1.dp, Color(0x2425D366), RoundedCornerShape(16.dp))
                .padding(horizontal = 16.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Row(Modifier.weight(1f)) {
                Text(
                    "${callerCalls.size} call${if (callerCalls.size == 1) "" else "s"}",
                    color = TextC, fontSize = 12.sp, fontWeight = FontWeight.Medium,
                )
                if (callerMissed > 0) Text(" · $callerMissed missed", color = Color(0xFFFF8A8D), fontSize = 12.sp)
                callerCalls.firstOrNull()?.startedAt?.let { Text(" · last ${vm.ago(it)}", color = Sage, fontSize = 12.sp, maxLines = 1) }
            }
            StripButton("Open chat →") { dash.openConversationFor(wa) }
        }
        Spacer(Modifier.height(12.dp))
        Box(
            Modifier.fillMaxWidth().weight(1f).clip(RoundedCornerShape(16.dp))
                .border(1.dp, if (Neema.colors.isDark) Neema.colors.border else Color(0xFFE7E5E4), RoundedCornerShape(16.dp))
                .background(Neema.colors.bg2),
        ) {
            CustomerPanel(
                dash = dash,
                conversation = conv,
                onClose = { vm.select(null) },
                onOpenIdentity = { _, externalId -> dash.openConversationFor(externalId) },
                onNameChange = { _, _ -> vm.load() },
                modifier = Modifier.fillMaxSize(),
            )
        }
    }
}

@Composable
private fun StripButton(text: String, onClick: () -> Unit) {
    Row(
        Modifier.clip(RoundedCornerShape(50)).background(Color(0x2425D366))
            .border(1.dp, Color(0x4D25D366), RoundedCornerShape(50))
            .clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, color = Green, fontSize = 12.sp, fontWeight = FontWeight.Medium)
    }
}

/**
 * Why a call might not ring this phone like the web's take-over card, and the
 * one tap that fixes it: notifications off (nothing rings in the background)
 * or, on Android 14+, full-screen notifications not allowed (a call shows as a
 * heads-up instead of waking the lock screen).
 */
@Composable
private fun ReadinessBanner(r: CallReadiness) {
    val ctx = LocalContext.current
    val (title, body, button) = if (!r.notifications) Triple(
        "Calls can't ring in the background",
        "Turn on notifications so a WhatsApp call rings this phone when Neema isn't open.",
        "Turn on",
    ) else Triple(
        "Let calls take over the lock screen",
        "Allow full-screen notifications so a ringing WhatsApp call wakes the phone, the way the dashboard takes over when it rings.",
        "Allow",
    )
    fun open() {
        val first = if (!r.notifications) notificationSettings(ctx) else fullScreenIntentSettings(ctx)
        val tries = listOf(
            first,
            notificationSettings(ctx),
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:${ctx.packageName}")),
        )
        for (i in tries) {
            if (runCatching { ctx.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }.isSuccess) return
        }
    }
    Row(
        Modifier
            .padding(start = 24.dp, end = 24.dp, bottom = 16.dp)
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Color(0x1AF5A623))
            .border(1.dp, Color(0x4DF5A623), RoundedCornerShape(12.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Filled.NotificationsActive, null, tint = Color(0xFFF5C451), modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(title, color = TextC, fontSize = 13.sp, fontWeight = FontWeight.Medium)
            Spacer(Modifier.height(2.dp))
            Text(body, color = Sage, fontSize = 12.sp, lineHeight = 17.sp)
        }
        Spacer(Modifier.width(12.dp))
        Text(
            button, color = Ink, fontSize = 12.sp, fontWeight = FontWeight.Medium,
            modifier = Modifier.clip(RoundedCornerShape(50)).background(Color(0xFFF5A623))
                .clickable { open() }.padding(horizontal = 14.dp, vertical = 7.dp),
        )
    }
}
