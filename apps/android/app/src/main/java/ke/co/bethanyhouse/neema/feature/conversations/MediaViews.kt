package ke.co.bethanyhouse.neema.feature.conversations

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.ui.PlayerView
import coil.compose.AsyncImage
import coil.compose.SubcomposeAsyncImage
import coil.decode.VideoFrameDecoder
import coil.request.ImageRequest
import coil.request.videoFrameMillis
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import ke.co.bethanyhouse.neema.core.ui.theme.Palette

// Bubble palette (the web's literal hex values).
internal val InboundTint: Color @androidx.compose.runtime.Composable get() = ink(Palette.Willow600)
internal val InboundTintBg: Color @androidx.compose.runtime.Composable get() = if (ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.isDark) Palette.Willow600.copy(alpha = 0.16f) else Hue.MossTint

/** The revealed transcript / analysis text inside an inbound bubble (light or dark page). */
@Composable
private fun revealInk(): Color =
    if (ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.isDark) Color.White.copy(alpha = 0.7f) else Hue.ForestInk.copy(alpha = 0.7f)

/** "Show transcript" / "Show image analysis" pill toggle. */
@Composable
internal fun RevealToggle(open: Boolean, showLabel: String, hideLabel: String, inbound: Boolean, onClick: () -> Unit) {
    Row(
        Modifier.clip(RoundedCornerShape(50))
            .background(if (inbound) InboundTintBg else Color.White.copy(alpha = 0.15f))
            .clickable(onClick = onClick).padding(horizontal = 8.dp, vertical = 3.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val c = if (inbound) InboundTint else Color.White.copy(alpha = 0.8f)
        Text(if (open) hideLabel else showLabel, fontSize = 10.sp, fontWeight = FontWeight.Medium, color = c)
        Icon(Icons.Filled.ExpandMore, null, tint = c, modifier = Modifier.size(12.dp).rotate(if (open) 180f else 0f))
    }
}

/**
 * Unrecoverable / expired media: Meta's signed CDN links expire, so an older
 * photo would render as an empty bubble. Say what was sent, and offer one tap
 * to fetch the original back from Meta.
 */
@Composable
internal fun MediaFallback(kind: String, messageId: String?, inbound: Boolean, onRecover: (String, (Recovery) -> Unit) -> Unit, onRecovered: (String) -> Unit) {
    var state by remember(messageId) { mutableStateOf("idle") }
    // A failed attempt (no connection, server trouble) says why and keeps the button.
    var why by remember(messageId) { mutableStateOf<String?>(null) }
    val label = if (kind == "video") "Video" else "Photo"
    // An inbound bubble is dark in dark mode: its ink flips to light.
    val dark = inbound && ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.isDark
    Column(
        Modifier.width(224.dp).clip(RoundedCornerShape(12.dp))
            .background(if (inbound && !dark) Color.Black.copy(alpha = 0.03f) else Color.White.copy(alpha = 0.06f))
            .dashedBorder(if (inbound && !dark) Color.Black.copy(alpha = 0.15f) else Color.White.copy(alpha = 0.3f), 12.dp)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Text("${if (kind == "video") "🎬" else "📷"} $label sent", fontSize = 12.sp, fontWeight = FontWeight.Medium)
        Text(
            when {
                state == "gone" -> "Meta no longer has this file — ask the customer to resend."
                why != null -> "Couldn't fetch it — $why"
                else -> "Preview link expired."
            },
            fontSize = 11.sp, color = if (inbound && !dark) Color.Black.copy(alpha = 0.5f) else Color.White.copy(alpha = 0.7f),
        )
        if (messageId != null && state != "gone") {
            Text(
                when { state == "loading" -> "Fetching…"; why != null -> "Try again"; else -> "Recover from Meta" },
                modifier = Modifier.alpha(if (state == "loading") 0.6f else 1f).clip(RoundedCornerShape(50))
                    .background(if (inbound) InboundTintBg else Color.White.copy(alpha = 0.2f))
                    .clickable(enabled = state != "loading") {
                        state = "loading"; why = null
                        onRecover(messageId) { r ->
                            when (r) {
                                is Recovery.Found -> { state = "idle"; onRecovered(r.url) }
                                Recovery.Gone -> state = "gone"
                                is Recovery.Failed -> { state = "idle"; why = r.why.replaceFirstChar { it.lowercase() } }
                            }
                        }
                    }
                    .padding(horizontal = 8.dp, vertical = 3.dp),
                fontSize = 10.sp, fontWeight = FontWeight.Medium,
                color = if (inbound) ink(Palette.Moss700) else Color.White,
            )
        }
    }
}

/** A customer photo: tap for the in-app viewer; collapsible AI image analysis; the caption. */
@Composable
internal fun ImageBubble(
    src: String, analysis: String?, caption: String?, inbound: Boolean, messageId: String?,
    onView: (Viewer) -> Unit, onRecover: (String, (Recovery) -> Unit) -> Unit,
) {
    var url by remember(src) { mutableStateOf(src) }
    var broken by remember(src) { mutableStateOf(false) }
    var open by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (broken) {
            MediaFallback("image", messageId, inbound, onRecover) { url = it; broken = false }
        } else {
            AsyncImage(
                model = url, contentDescription = caption ?: "image", contentScale = ContentScale.Crop,
                onError = { broken = true },
                modifier = Modifier.widthIn(max = 260.dp).heightIn(max = 240.dp).clip(RoundedCornerShape(12.dp))
                    .border(1.dp, Color.Black.copy(alpha = 0.1f), RoundedCornerShape(12.dp))
                    .clickable { onView(Viewer.Image(url)) },
            )
        }
        if (!analysis.isNullOrBlank()) {
            RevealToggle(open, "Show image analysis", "Hide image analysis", inbound) { open = !open }
            if (open) Text(
                analysis, fontSize = 11.sp, lineHeight = 16.sp, fontStyle = if (inbound) FontStyle.Italic else FontStyle.Normal,
                color = if (inbound) revealInk() else Color.White.copy(alpha = 0.8f),
                modifier = Modifier.padding(horizontal = 4.dp),
            )
        }
        if (!caption.isNullOrBlank() && !caption.startsWith("[")) {
            Text(
                caption, fontSize = 12.sp, lineHeight = 17.sp, modifier = Modifier.padding(horizontal = 4.dp),
                color = if (inbound) (if (ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.isDark) ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.text else Hue.ForestText) else Color.White.copy(alpha = 0.9f),
            )
        }
    }
}

/** A video: a poster frame with a play button; plays full-screen in ExoPlayer. */
@Composable
internal fun VideoBubble(
    src: String, caption: String?, inbound: Boolean, messageId: String?, brokenIds: Set<String>,
    onView: (Viewer) -> Unit, onRecover: (String, (Recovery) -> Unit) -> Unit,
) {
    var url by remember(src) { mutableStateOf(src) }
    val context = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        if (messageId != null && messageId in brokenIds && url == src) {
            MediaFallback("video", messageId, inbound, onRecover) { url = it }
        } else {
            Box(
                Modifier.width(240.dp).height(180.dp).clip(RoundedCornerShape(12.dp)).background(Palette.Ink)
                    .clickable { onView(Viewer.Video(url, messageId)) },
                contentAlignment = Alignment.Center,
            ) {
                AsyncImage(
                    model = ImageRequest.Builder(context).data(url).decoderFactory(VideoFrameDecoder.Factory()).videoFrameMillis(1000).build(),
                    contentDescription = null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize(),
                )
                PlayBadge(loading = false, video = true)
            }
        }
        if (!caption.isNullOrBlank()) Text(rememberWa(caption), fontSize = 12.sp, lineHeight = 17.sp, modifier = Modifier.padding(horizontal = 4.dp))
    }
}

@Composable
internal fun PlayBadge(loading: Boolean, video: Boolean) {
    Box(Modifier.size(40.dp).clip(CircleShape).background(Color.White.copy(alpha = 0.9f)), contentAlignment = Alignment.Center) {
        when {
            loading -> CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Palette.Moss700)
            video -> Icon(Icons.Filled.PlayArrow, "Play", tint = Palette.Ink)
            else -> Icon(Icons.Filled.ZoomOutMap, "View", tint = Palette.Ink, modifier = Modifier.size(18.dp))
        }
    }
}

/** Voice note / audio: an in-bubble player plus the collapsible transcript (and the AI's cart text). */
@Composable
internal fun AudioBubble(src: String, transcription: String?, cartText: String?, inbound: Boolean) {
    val context = LocalContext.current
    var player by remember(src) { mutableStateOf<ExoPlayer?>(null) }
    var playing by remember(src) { mutableStateOf(false) }
    var pos by remember(src) { mutableLongStateOf(0L) }
    var dur by remember(src) { mutableLongStateOf(0L) }
    var failed by remember(src) { mutableStateOf(false) }
    var open by remember { mutableStateOf(false) }
    DisposableEffect(src) { onDispose { player?.release(); player = null } }
    LaunchedEffect(playing) {
        while (playing) {
            player?.let { pos = it.currentPosition; dur = it.duration.coerceAtLeast(0L) }
            delay(250)
        }
    }
    val nc = ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors
    val fg = if (inbound) (if (nc.isDark) nc.textMid else Palette.Moss700) else Color.White
    Column(Modifier.widthIn(min = 220.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = {
                val p = player ?: ExoPlayer.Builder(context).build().also { p ->
                    p.setMediaItem(MediaItem.fromUri(src))
                    p.addListener(object : Player.Listener {
                        override fun onIsPlayingChanged(isPlaying: Boolean) { playing = isPlaying }
                        override fun onPlaybackStateChanged(state: Int) {
                            if (state == Player.STATE_READY) dur = p.duration.coerceAtLeast(0L)
                            if (state == Player.STATE_ENDED) { p.pause(); p.seekTo(0); pos = 0 }
                        }
                        override fun onPlayerError(error: PlaybackException) { failed = true; playing = false }
                    })
                    p.prepare()
                    player = p
                }
                if (p.isPlaying) p.pause() else p.play()
            }, modifier = Modifier.size(36.dp)) {
                Icon(if (playing) Icons.Filled.Pause else Icons.Filled.PlayArrow, if (playing) "Pause" else "Play", tint = fg)
            }
            Slider(
                value = if (dur > 0) (pos.toFloat() / dur).coerceIn(0f, 1f) else 0f,
                onValueChange = { f -> player?.let { p -> if (dur > 0) { p.seekTo((f * dur).toLong()); pos = (f * dur).toLong() } } },
                modifier = Modifier.weight(1f).height(24.dp),
                colors = SliderDefaults.colors(thumbColor = fg, activeTrackColor = fg, inactiveTrackColor = fg.copy(alpha = 0.25f)),
            )
            Text(
                ke.co.bethanyhouse.neema.core.util.Fmt.duration(((if (playing || pos > 0) pos else dur) / 1000).toInt()),
                fontSize = 10.sp, color = fg.copy(alpha = 0.8f), modifier = Modifier.padding(start = 6.dp),
            )
        }
        if (failed) Text("Couldn't play this audio.", fontSize = 10.sp, color = fg.copy(alpha = 0.7f))
        if (!transcription.isNullOrBlank()) {
            RevealToggle(open, "Show transcript", "Hide transcript", inbound) { open = !open }
            if (open) Text(
                transcription, fontSize = 11.sp, lineHeight = 16.sp, fontStyle = if (inbound) FontStyle.Italic else FontStyle.Normal,
                color = if (inbound) revealInk() else Color.White.copy(alpha = 0.8f),
                modifier = Modifier.padding(horizontal = 4.dp),
            )
        }
        if (!inbound && !cartText.isNullOrBlank()) {
            Text(
                cartText, fontSize = 11.sp, fontWeight = FontWeight.Medium, lineHeight = 16.sp,
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(Color.White.copy(alpha = 0.2f)).padding(horizontal = 8.dp, vertical = 6.dp),
            )
        }
    }
}

/** Documents open through the system (the URL), like the web's download link. */
@Composable
internal fun DocumentTile(url: String, name: String, inbound: Boolean) {
    val uri = LocalUriHandler.current
    val nc = ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors
    Row(
        Modifier.clip(RoundedCornerShape(12.dp))
            .background(if (inbound) (if (nc.isDark) nc.bg3 else Color.White) else Color.White.copy(alpha = 0.2f))
            .border(1.dp, if (inbound) (if (nc.isDark) nc.border else Palette.Hairline2) else Color.White.copy(alpha = 0.3f), RoundedCornerShape(12.dp))
            .clickable { runCatching { uri.openUri(url) } }
            .padding(horizontal = 12.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        val c = if (inbound) nc.text else Color.White
        Icon(Icons.Filled.Description, null, tint = c.copy(alpha = 0.7f), modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(8.dp))
        Text(name, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = c, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.widthIn(max = 160.dp))
        Spacer(Modifier.width(8.dp))
        Icon(Icons.Filled.Download, "Open", tint = c.copy(alpha = 0.6f), modifier = Modifier.size(16.dp))
    }
}

/** WhatsApp-style album: ≥2 consecutive photos from one side in one collage bubble. */
@Composable
internal fun AlbumGrid(items: List<AlbumItem>, onOpen: (Int) -> Unit) {
    val n = items.size
    val shown = items.take(4)
    val extra = n - 4
    Column(Modifier.width(256.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        var i = 0
        if (n == 3) {
            // 3 photos: the big one on top.
            AlbumCell(shown[0], 0, false, extra, Modifier.fillMaxWidth().height(160.dp), onOpen)
            i = 1
        }
        while (i < shown.size) {
            Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                for (j in i until minOf(i + 2, shown.size)) {
                    AlbumCell(shown[j], j, j == 3 && extra > 0, extra, Modifier.weight(1f).height(128.dp), onOpen)
                }
            }
            i += 2
        }
    }
}

@Composable
private fun AlbumCell(it: AlbumItem, index: Int, more: Boolean, extra: Int, modifier: Modifier, onOpen: (Int) -> Unit) {
    Box(modifier.clip(RoundedCornerShape(8.dp)).clickable { onOpen(index) }) {
        AsyncImage(model = it.src, contentDescription = it.caption ?: "photo ${index + 1}", contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
        if (more) Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.55f)), contentAlignment = Alignment.Center) {
            Text("+$extra", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

/**
 * A Facebook/Instagram comment is meaningless without the post it is on.
 * This shows the post/reel: tapping PLAYS it in-app (fresh video URL fetched
 * on demand via postVideo), or opens the photo, or falls back to the permalink.
 */
@Composable
internal fun CommentContextCard(
    ctx: PostContext, inbound: Boolean, channel: String?, heading: String?,
    onView: (Viewer) -> Unit, fetchVideo: suspend (postId: String, channel: String?) -> String?,
) {
    val title = ctx.title?.trim().orEmpty().ifEmpty { "a post" }
    val permalink = ctx.permalink.orEmpty()
    val thumb = ctx.thumb.orEmpty()
    val postId = ctx.postId.orEmpty()
    // Unknown media_type (old rows) → still try to play; the endpoint 404s for a photo.
    val maybeVideo = ctx.hasVideo == true || ctx.mediaType == "video" || ctx.mediaType == null
    var loading by remember { mutableStateOf(false) }
    var thumbOk by remember(thumb) { mutableStateOf(true) }
    val uri = LocalUriHandler.current
    val scope = rememberCoroutineScope()
    val open: () -> Unit = {
        if (!loading) scope.launch {
            if (postId.isNotEmpty() && maybeVideo) {
                loading = true
                val v = runCatching { fetchVideo(postId, channel) }.getOrNull()
                loading = false
                if (!v.isNullOrBlank()) { onView(Viewer.Video(v)); return@launch }
            }
            when {
                thumb.isNotEmpty() -> onView(Viewer.Image(thumb))
                permalink.isNotEmpty() -> runCatching { uri.openUri(permalink) }
            }
        }
    }
    val dark = inbound && ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.isDark
    Column(
        Modifier.clip(RoundedCornerShape(8.dp))
            .background(if (dark) Palette.Moss600.copy(alpha = 0.10f) else if (inbound) Palette.Leaf else Color.White.copy(alpha = 0.15f))
            .border(1.dp, if (dark) ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.border else if (inbound) Hue.SageRing else Color.White.copy(alpha = 0.2f), RoundedCornerShape(8.dp))
            .padding(8.dp),
    ) {
        Text(
            (heading ?: "Commented on your post").uppercase(), fontSize = 9.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.4.sp,
            color = if (inbound) InboundTint else Color.White.copy(alpha = 0.7f),
        )
        Spacer(Modifier.height(4.dp))
        Text(title, fontSize = 11.sp, lineHeight = 15.sp, maxLines = 2, overflow = TextOverflow.Ellipsis, color = if (dark) ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.text else if (inbound) Hue.ForestInk else Color.White.copy(alpha = 0.9f))
        Spacer(Modifier.height(6.dp))
        if (thumb.isNotEmpty() && thumbOk) {
            Box(
                Modifier.widthIn(max = 260.dp).fillMaxWidth().aspectRatio(16f / 9f).clip(RoundedCornerShape(8.dp)).clickable(onClick = open),
                contentAlignment = Alignment.Center,
            ) {
                AsyncImage(model = thumb, contentDescription = null, contentScale = ContentScale.Crop, onError = { thumbOk = false }, modifier = Modifier.fillMaxSize())
                Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.2f)))
                PlayBadge(loading, maybeVideo)
            }
        } else if (postId.isNotEmpty() && maybeVideo) {
            TextButton(onClick = open, contentPadding = PaddingValues(horizontal = 4.dp)) {
                if (loading) CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp) else Icon(Icons.Filled.PlayArrow, null, Modifier.size(16.dp))
                Spacer(Modifier.width(4.dp)); Text("Play reel", fontSize = 11.sp)
            }
        }
        if (permalink.isNotEmpty()) {
            Row(
                Modifier.padding(top = 6.dp).clickable { runCatching { uri.openUri(permalink) } },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val c = if (inbound) InboundTint else Color.White.copy(alpha = 0.7f)
                Text("View on Facebook", fontSize = 10.sp, fontWeight = FontWeight.Medium, color = c)
                Spacer(Modifier.width(3.dp))
                Icon(Icons.AutoMirrored.Filled.OpenInNew, null, tint = c, modifier = Modifier.size(10.dp))
            }
        }
    }
}

// ═══════════════════════════ Full-screen viewers ═══════════════════════════

/** In-app viewer: photos (pinch to zoom), videos (ExoPlayer) and albums (swipe ‹ ›). */
@Composable
internal fun ViewerDialog(viewer: Viewer, onClose: () -> Unit, onVideoError: (String?) -> Unit) {
    Dialog(onDismissRequest = onClose, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Box(Modifier.fillMaxSize().background(Color.Black.copy(alpha = 0.9f))) {
            when (viewer) {
                is Viewer.Image -> ZoomableImage(viewer.url, onClose, Modifier.fillMaxSize())
                is Viewer.Video -> VideoPlayer(viewer.url, Modifier.fillMaxSize().padding(vertical = 48.dp)) {
                    onVideoError(viewer.messageId); onClose()
                }
                is Viewer.Album -> {
                    val pager = rememberPagerState(initialPage = viewer.start.coerceIn(0, (viewer.items.size - 1).coerceAtLeast(0))) { viewer.items.size }
                    val scope = rememberCoroutineScope()
                    HorizontalPager(pager, Modifier.fillMaxSize()) { page ->
                        Column(Modifier.fillMaxSize(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                            ZoomableImage(viewer.items[page].src, onClose, Modifier.weight(1f, fill = false).fillMaxWidth())
                            viewer.items[page].caption?.let {
                                Text(it, color = Color.White.copy(alpha = 0.9f), fontSize = 14.sp, textAlign = TextAlign.Center, modifier = Modifier.padding(16.dp))
                            }
                        }
                    }
                    Text(
                        "${pager.currentPage + 1} / ${viewer.items.size}", color = Color.White.copy(alpha = 0.7f), fontSize = 14.sp,
                        modifier = Modifier.align(Alignment.TopCenter).statusBarsPadding().padding(top = 16.dp),
                    )
                    if (viewer.items.size > 1) {
                        IconButton(
                            onClick = { scope.launch { pager.animateScrollToPage((pager.currentPage + viewer.items.size - 1) % viewer.items.size) } },
                            modifier = Modifier.align(Alignment.CenterStart),
                        ) { Icon(Icons.Filled.ChevronLeft, "Previous", tint = Color.White.copy(alpha = 0.8f), modifier = Modifier.size(36.dp)) }
                        IconButton(
                            onClick = { scope.launch { pager.animateScrollToPage((pager.currentPage + 1) % viewer.items.size) } },
                            modifier = Modifier.align(Alignment.CenterEnd),
                        ) { Icon(Icons.Filled.ChevronRight, "Next", tint = Color.White.copy(alpha = 0.8f), modifier = Modifier.size(36.dp)) }
                    }
                }
            }
            IconButton(onClick = onClose, modifier = Modifier.align(Alignment.TopEnd).statusBarsPadding().padding(8.dp)) {
                Icon(Icons.Filled.Close, "Close", tint = Color.White.copy(alpha = 0.9f), modifier = Modifier.size(28.dp))
            }
        }
    }
}

@Composable
private fun ZoomableImage(url: String, onBackdrop: () -> Unit, modifier: Modifier) {
    var scale by remember(url) { mutableFloatStateOf(1f) }
    var offset by remember(url) { mutableStateOf(Offset.Zero) }
    SubcomposeAsyncImage(
        model = url, contentDescription = null, contentScale = ContentScale.Fit,
        loading = { Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator(color = Color.White) } },
        modifier = modifier
            .pointerInput(url + "zoom") {
                detectTransformGestures { _, pan, zoom, _ ->
                    scale = (scale * zoom).coerceIn(1f, 5f)
                    offset = if (scale == 1f) Offset.Zero else offset + pan
                }
            }
            .pointerInput(url + "tap") {
                detectTapGestures(
                    onDoubleTap = { if (scale > 1f) { scale = 1f; offset = Offset.Zero } else scale = 2.5f },
                    onTap = { if (scale == 1f) onBackdrop() },
                )
            }
            .graphicsLayer(scaleX = scale, scaleY = scale, translationX = offset.x, translationY = offset.y),
    )
}

/** ExoPlayer in a PlayerView; released when it leaves composition. */
@Composable
internal fun VideoPlayer(url: String, modifier: Modifier = Modifier, onError: () -> Unit = {}) {
    val context = LocalContext.current
    val player = remember(url) {
        ExoPlayer.Builder(context).build().apply {
            setMediaItem(MediaItem.fromUri(url)); prepare(); playWhenReady = true
        }
    }
    val errorCb by rememberUpdatedState(onError)
    DisposableEffect(player) {
        val l = object : Player.Listener { override fun onPlayerError(error: PlaybackException) { errorCb() } }
        player.addListener(l)
        onDispose { player.removeListener(l); player.release() }
    }
    AndroidView(factory = { PlayerView(it).apply { this.player = player; useController = true } }, modifier = modifier)
}
