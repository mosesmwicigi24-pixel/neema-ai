package ke.co.bethanyhouse.neema.feature.conversations

import ke.co.bethanyhouse.neema.core.util.AppClock

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.collectIsFocusedAsState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import coil.compose.AsyncImage
import ke.co.bethanyhouse.neema.core.model.ConversationWindow
import ke.co.bethanyhouse.neema.core.util.Fmt
import kotlinx.coroutines.delay
import java.io.File
import ke.co.bethanyhouse.neema.core.ui.theme.NeemaFont
import ke.co.bethanyhouse.neema.core.ui.theme.Palette

private val Blue50 = Palette.Blue50
private val Blue200 = Palette.Blue200
private val Blue700 = Palette.Blue700
private val Amber = Palette.Amber500

/**
 * The reply box — shown when the agent owns the thread, or is admin: AI
 * drafts, the quoted message, the 24h window, the translate toggle, the
 * text box, and attachments with per-file captions.
 */
@Composable
internal fun Composer(
    vm: ConversationsViewModel, state: ComposerUi, window: ConversationWindow?, humanMode: Boolean,
    threadLang: String?, txOn: Boolean,
) {
    val c = ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors
    val blue = tint(Blue50, Blue700, Blue200)
    Column(
        Modifier.fillMaxWidth().background(c.bg2).padding(horizontal = 12.dp).padding(top = 10.dp, bottom = 10.dp),
    ) {
        // Everything above the text box scrolls within whatever height the thread
        // pane leaves the composer (keyboard up, font scale 2.0): the box never leaves.
        Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState())) {
        // ── AI draft: a pill when collapsed, the panel when expanded ──
        if (state.draftVisible && !state.draftExpanded) {
            Row(
                Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(blue.bg)
                    .border(1.dp, blue.border, RoundedCornerShape(12.dp)).clickable(onClickLabel = "Review the AI draft") { vm.expandDraft(true) }.padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("🤖", fontSize = 14.sp)
                Spacer(Modifier.width(8.dp))
                Text("AI has a draft ready", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = blue.fg, modifier = Modifier.weight(1f))
                Text("Tap to review ↑", fontSize = 10.sp, color = ink(Palette.Blue500))
            }
        }
        if (state.draftVisible && state.draftExpanded) DraftPanel(vm, state)
        // ── Generate draft — when no draft exists ──
        if (!state.draftVisible && humanMode) {
            Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.End) {
                OutlinedButton(
                    onClick = vm::generateDraft, enabled = !state.generatingDraft, modifier = Modifier.webHeight(28.dp),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp), shape = RoundedCornerShape(8.dp),
                    border = androidx.compose.foundation.BorderStroke(1.dp, if (state.generatingDraft) blue.border.copy(alpha = 0.5f) else blue.border),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = ink(Palette.Blue600), disabledContentColor = ink(Palette.Blue600).copy(alpha = 0.5f)),
                ) {
                    if (state.generatingDraft) {
                        CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp, color = Palette.Blue400)
                        Spacer(Modifier.width(6.dp)); Text("Generating…", fontSize = 12.sp)
                    } else Text("🤖 Generate AI draft", fontSize = 12.sp)
                }
            }
        }
        // ── The message being answered ──
        state.quoted?.let { q ->
            Row(
                Modifier.padding(bottom = 8.dp).fillMaxWidth().height(IntrinsicSize.Min).clip(RoundedCornerShape(8.dp)).background(if (c.isDark) c.bg3 else Hue.Slate100),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.width(2.dp).fillMaxHeight().heightIn(min = 44.dp).background(Amber))
                Column(Modifier.weight(1f).padding(horizontal = 10.dp, vertical = 6.dp)) {
                    Text(
                        (if (q.msgId != null) "Replying to ${when (q.sender) { "user" -> "Customer"; "ai" -> "Neema"; else -> "you" }}"
                        else "Replying to ${channelLabel(q.channel)}").uppercase(),
                        fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = Amber, letterSpacing = 0.5.sp,
                    )
                    Text(
                        when {
                            q.text.isNotBlank() && q.text.trim() != "[image]" -> q.text
                            q.mediaUrl != null -> "📷 Photo"
                            q.mediaType != null -> "[${q.mediaType}]"
                            else -> q.text
                        },
                        fontSize = 12.sp, color = if (c.isDark) c.textMid else Hue.Slate600, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                }
                q.mediaUrl?.let { AsyncImage(it, "quoted", contentScale = ContentScale.Crop, modifier = Modifier.size(36.dp).clip(RoundedCornerShape(4.dp))) }
                IconButton(onClick = vm::clearQuote, modifier = Modifier.size(32.dp)) { Icon(Icons.Filled.Close, "Remove quote", tint = Palette.Slate400, modifier = Modifier.size(16.dp)) }
            }
        }
        // ── Messaging window — said BEFORE a reply is typed that Meta would refuse ──
        if (window != null && window.mode != "n/a") WindowStrip(window)
        // ── Translate-to-their-language toggle ──
        if (threadLang != null || txOn) {
            Row(Modifier.padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                val tx = if (txOn) tint(Palette.Willow100, Palette.Moss700, Palette.Moss700.copy(alpha = 0.3f)) else tint(Palette.Stone100, Palette.Stone500, Palette.Stone200)
                Text(
                    "🌐 " + if (txOn) "Sending in ${state.txPreview?.lang ?: threadLang ?: "their language"}" else "Translate: off",
                    fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = tx.fg,
                    modifier = Modifier.clip(RoundedCornerShape(50)).background(tx.bg)
                        .border(1.dp, tx.border, RoundedCornerShape(50))
                        .clickable(onClick = vm::toggleTx).padding(horizontal = 10.dp, vertical = 4.dp),
                )
                if (txOn && state.txBusy) Text("translating…", fontSize = 10.sp, color = Palette.Stone400, modifier = Modifier.padding(start = 8.dp))
            }
        }
        if (txOn && state.txPreview != null && state.replyText.trim().length > 1) {
            Column(
                Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(if (c.isDark) c.bg3 else Palette.Stone50)
                    .border(1.dp, if (c.isDark) c.border else Palette.Stone200, RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(
                    ("They will receive" + (state.txPreview.lang?.let { " — $it" } ?: "")).uppercase(),
                    fontSize = 9.sp, fontWeight = FontWeight.SemiBold, color = Palette.Stone400, letterSpacing = 0.5.sp,
                )
                Text(state.txPreview.text, fontSize = 12.sp, fontStyle = FontStyle.Italic, color = if (c.isDark) c.textMid else Palette.Stone600)
            }
        }
        if (state.lostMedia.isNotEmpty()) LostMediaNote(state.lostMedia, vm::dismissLostMedia)
        }
        // ── Text box + attach + send ──
        Row(verticalAlignment = Alignment.Bottom) {
            AttachButton(vm)
            Spacer(Modifier.width(8.dp))
            // The web's box: 44 tall, rounded-2xl, #f6f7f5 on a #e5e8e2 hairline, an
            // amber ring on focus, stone-400 placeholder; grows to ~5 lines, then scrolls.
            val focus = remember { androidx.compose.foundation.interaction.MutableInteractionSource() }
            val focused by focus.collectIsFocusedAsState()
            val boxShape = RoundedCornerShape(16.dp)
            androidx.compose.foundation.text.BasicTextField(
                value = state.replyText, onValueChange = vm::setReplyText, interactionSource = focus,
                textStyle = androidx.compose.ui.text.TextStyle(fontFamily = NeemaFont, fontSize = 14.sp, lineHeight = 19.sp, color = c.text),
                cursorBrush = androidx.compose.ui.graphics.SolidColor(Amber),
                maxLines = 6,
                modifier = Modifier.weight(1f).heightIn(min = 44.dp, max = 132.dp)
                    .clip(boxShape).background(if (c.isDark) c.bg3 else Hue.SageFieldBg)
                    .border(if (focused) 2.dp else 1.dp, if (focused) Amber.copy(alpha = 0.7f) else if (c.isDark) c.border else Hue.SageField, boxShape),
                decorationBox = { inner ->
                    Box(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), contentAlignment = Alignment.CenterStart) {
                        if (state.replyText.isEmpty()) Text(
                            if (window?.mode == "human_agent") "Type a reply — goes out under your name (human agent)…" else "Type a reply…",
                            fontSize = 14.sp, lineHeight = 19.sp, color = if (c.isDark) c.muted else Palette.Stone400, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                        inner()
                    }
                },
            )
            Spacer(Modifier.width(8.dp))
            val closed = window?.mode == "closed"
            // The box clears the moment a reply is sent, so an empty box is the
            // double-tap guard; the reply's own bubble shows it on its way.
            val enabled = state.replyText.isNotBlank() && !closed
            Box(
                Modifier.size(44.dp).clip(RoundedCornerShape(16.dp)).background(if (enabled) Amber else Amber.copy(alpha = 0.5f))
                    .clickable(enabled = enabled, onClickLabel = if (closed) (window?.reason ?: "Outside the messaging window") else "Send") { vm.sendReply() },
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.AutoMirrored.Filled.Send, if (closed) (window?.reason ?: "Outside the messaging window") else "Send", tint = Color.White, modifier = Modifier.size(18.dp))
            }
        }
        if (state.media.isNotEmpty()) MediaTray(vm, state, Modifier.weight(3f, fill = false))
    }
}

@Composable
private fun DraftPanel(vm: ConversationsViewModel, state: ComposerUi) {
    val blue = tint(Blue50, Blue700, Blue200)
    val soft = ink(Palette.Blue500)
    Column(Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(blue.bg).border(1.dp, blue.border, RoundedCornerShape(12.dp))) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("🤖", fontSize = 14.sp); Spacer(Modifier.width(6.dp))
            Text("AI Draft", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = blue.fg, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                if (state.draftEditing) "Preview" else "Edit", fontSize = 10.sp, color = soft, maxLines = 1,
                modifier = Modifier.clip(RoundedCornerShape(4.dp)).border(1.dp, blue.border, RoundedCornerShape(4.dp)).clickable(onClick = vm::toggleDraftEditing).padding(horizontal = 8.dp, vertical = 2.dp),
            )
            // Web-sized (28 dp) glyph buttons; Compose widens their hit area to 48 dp.
            IconButton(onClick = { vm.expandDraft(false) }, modifier = Modifier.size(28.dp)) { Icon(Icons.Filled.KeyboardArrowDown, "Collapse the AI draft", tint = soft, modifier = Modifier.size(16.dp)) }
            IconButton(onClick = vm::dismissDraft, modifier = Modifier.size(28.dp)) { Icon(Icons.Filled.Close, "Dismiss the AI draft", tint = soft, modifier = Modifier.size(14.dp)) }
        }
        HorizontalDivider(color = if (ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.isDark) blue.border else Hue.Blue100)
        Box(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            if (state.draftEditing) {
                OutlinedTextField(
                    value = state.draftText, onValueChange = vm::setDraftText, minLines = 4, maxLines = 8,
                    placeholder = { Text("Edit the draft…", fontSize = 12.sp) },
                    textStyle = LocalTextStyle.current.copy(fontSize = 12.sp, color = ink(Hue.Blue800)),
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                Text(state.draftText.ifEmpty { "AI has a reply ready." }, fontSize = 12.sp, lineHeight = 18.sp, color = blue.fg)
            }
        }
        Row(Modifier.padding(start = 12.dp, end = 12.dp, bottom = 10.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            // <Btn small> primary (amber) / secondary / ghost, as on the web.
            WebBtn("✓ Send", BtnVariant.Primary, vm::approveDraft)
            WebBtn("Edit & send manually", BtnVariant.Secondary, vm::draftToComposer)
            WebBtn("Dismiss", BtnVariant.Ghost, vm::dismissDraft)
        }
    }
}

@Composable
internal fun SmallBtn(label: String, bg: Color, fg: Color, onClick: () -> Unit, enabled: Boolean = true) {
    Text(
        label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg.copy(alpha = if (enabled) 1f else 0.5f), maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(bg)
            .then(if (bg == Color.White) Modifier.border(1.dp, Palette.Hairline, RoundedCornerShape(8.dp)) else Modifier)
            .clickable(enabled = enabled, onClick = onClick).padding(horizontal = 12.dp, vertical = 7.dp),
    )
}

/**
 * Meta and WhatsApp shut free-form replies 24h after the customer's last
 * message. Say so up front — and, on a Meta DM, that a human still has seven
 * days. The countdown ticks each minute.
 */
@Composable
internal fun WindowStrip(win: ConversationWindow) {
    var now by remember { mutableLongStateOf(AppClock.now()) }
    LaunchedEffect(Unit) { while (true) { delay(60_000); now = AppClock.now() } }
    fun left(iso: String?): String {
        val t = Fmt.millis(iso) ?: return ""
        val ms = t - now
        if (ms <= 0) return ""
        val h = ms / 3_600_000
        val m = (ms % 3_600_000) / 60_000
        return if (h >= 24) "${h / 24}d ${h % 24}h" else if (h > 0) "${h}h ${m}m" else "${m}m"
    }
    val (bg0, bd0, fg0, icon) = when (win.mode) {
        "open" -> Quad(Hue.MossTint, Hue.MossRim, Palette.Moss700, "🟢")
        "human_agent" -> Quad(Hue.Orange50, Hue.Orange200, Palette.Amber700, "🟠")
        "closed" -> Quad(Palette.Red50, Palette.Red200, Palette.Red700, "🔴")
        else -> Quad(Hue.StoneGreen, Palette.Hairline, Palette.Sage500, "•")
    }
    val (bg, fg, bd) = tint(bg0, fg0, bd0)
    val text = when (win.mode) {
        "open" -> "Reply window open — ${left(win.expiresAt)} left"
        "human_agent" -> "24h window closed — you can still reply as a human agent for ${left(win.humanAgentUntil)}. Neema cannot."
        else -> win.reason ?: "Messaging window closed — only an approved template can reach them now."
    }
    Row(
        Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(bg).border(1.dp, bd, RoundedCornerShape(8.dp))
            .padding(horizontal = 12.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(icon, fontSize = 11.sp); Spacer(Modifier.width(8.dp))
        Text(text, fontSize = 11.sp, fontWeight = FontWeight.Medium, color = fg, lineHeight = 15.sp)
    }
}

/** Camera, gallery (photos/videos) and documents through the system pickers. */
@Composable
private fun AttachButton(vm: ConversationsViewModel) {
    val context = LocalContext.current
    var menu by remember { mutableStateOf(false) }
    // Saveable: Android often kills the app while the camera is open, and the
    // photo it took comes back to a fresh process — which must still know where.
    var cameraUri by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf<Uri?>(null) }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) { vm.addMedia(it) }
    val docs = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { vm.addMedia(it) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok -> if (ok) cameraUri?.let { vm.addMedia(listOf(it)) } }
    fun launchCamera() {
        val dir = File(context.cacheDir, "camera").apply { mkdirs() }
        val file = File(dir, "photo_${AppClock.now()}.jpg")
        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
        cameraUri = uri
        camera.launch(uri)
    }
    val camPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> if (granted) launchCamera() }
    Box {
        Box(
            Modifier.size(44.dp).clip(RoundedCornerShape(16.dp)).background(if (ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.isDark) ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.bg3 else Hue.CoolGray).clickable { menu = true },
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Filled.AttachFile, "Attach images or files (up to 5 MB each for images)", tint = Palette.Slate500, modifier = Modifier.size(18.dp)) }
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(text = { Text("Camera") }, leadingIcon = { Icon(Icons.Filled.PhotoCamera, null) }, onClick = {
                menu = false
                if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) launchCamera()
                else camPerm.launch(Manifest.permission.CAMERA)
            })
            DropdownMenuItem(text = { Text("Photos & videos") }, leadingIcon = { Icon(Icons.Filled.PhotoLibrary, null) }, onClick = {
                menu = false
                gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageAndVideo))
            })
            DropdownMenuItem(text = { Text("Document") }, leadingIcon = { Icon(Icons.Filled.Description, null) }, onClick = {
                menu = false
                docs.launch(ACCEPT_TYPES)
            })
        }
    }
}

/**
 * Files picked before Android closed the app that it no longer lets the app
 * read (a picker's permission lapses with the process): named, so the agent
 * attaches them again instead of wondering where they went.
 */
@Composable
private fun LostMediaNote(names: List<String>, onDismiss: () -> Unit) {
    val t = tint(Palette.Amber50, Palette.Amber800, Palette.Amber200)
    Row(
        Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(t.bg).border(1.dp, t.border, RoundedCornerShape(8.dp))
            .padding(start = 12.dp, top = 4.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text("📎", fontSize = 11.sp); Spacer(Modifier.width(8.dp))
        val list = names.take(3).joinToString(", ") + if (names.size > 3) " and ${names.size - 3} more" else ""
        Text(
            "The app closed before ${if (names.size == 1) "this file was" else "these files were"} sent — attach again: $list",
            fontSize = 11.sp, lineHeight = 15.sp, fontWeight = FontWeight.Medium, color = t.fg, modifier = Modifier.weight(1f),
        )
        IconButton(onClick = onDismiss, modifier = Modifier.size(32.dp)) {
            Icon(Icons.Filled.Close, "Dismiss", tint = t.fg, modifier = Modifier.size(14.dp))
        }
    }
}

/** The web's ACCEPT_TYPES: what upload-media takes. */
private val ACCEPT_TYPES = arrayOf(
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/*",
    "application/pdf", "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "video/mp4", "video/3gpp", "video/quicktime", "video/hevc", "video/x-m4v",
    "audio/ogg", "audio/aac", "audio/mpeg",
)

/** Picked files, each with its OWN caption, then Send N / Cancel. */
@Composable
private fun MediaTray(vm: ConversationsViewModel, state: ComposerUi, modifier: Modifier = Modifier) {
    val more = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { vm.addMedia(it) }
    val nc0 = ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors
    val retry = state.media.any { it.error != null }
    Column(
        modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(if (nc0.isDark) nc0.bg3 else Palette.Mist)
            .border(1.dp, if (nc0.isDark) nc0.border else Palette.Hairline, RoundedCornerShape(12.dp)).padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        // The files scroll when the keyboard leaves little room; Send / Cancel never do.
        Column(Modifier.weight(1f, fill = false).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        state.media.forEach { it ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box {
                    if (it.isImage) AsyncImage(it.bytes ?: it.uri, it.name, contentScale = ContentScale.Crop, modifier = Modifier.size(56.dp).clip(RoundedCornerShape(8.dp)).border(1.dp, hairline(), RoundedCornerShape(8.dp)))
                    else Column(
                        Modifier.size(56.dp).clip(RoundedCornerShape(8.dp)).background(if (nc0.isDark) nc0.bg4 else Palette.Hairline).padding(2.dp),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
                    ) {
                        Icon(if (it.mime.startsWith("video/")) Icons.Filled.Movie else Icons.Filled.Description, null, tint = Palette.Sage400, modifier = Modifier.size(20.dp))
                        Text(it.name, fontSize = 9.sp, color = if (nc0.isDark) nc0.textMid else Hue.SageCaption, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Box(
                        Modifier.align(Alignment.TopEnd).offset(6.dp, (-6).dp).size(20.dp).clip(CircleShape).background(Palette.Ink)
                            .clickable(enabled = !state.uploading) { vm.removeMedia(it.id) },
                        contentAlignment = Alignment.Center,
                    ) { Icon(Icons.Filled.Close, "Remove", tint = Color.White, modifier = Modifier.size(12.dp)) }
                }
                Spacer(Modifier.width(10.dp))
                // The web's compact caption input: white, #e8ebe3 hairline, text-xs.
                val nc = ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors
                androidx.compose.foundation.text.BasicTextField(
                    value = it.caption, onValueChange = { v -> vm.setMediaCaption(it.id, v) }, enabled = !state.uploading, singleLine = true,
                    textStyle = androidx.compose.ui.text.TextStyle(fontFamily = NeemaFont, fontSize = 12.sp, color = nc.text),
                    cursorBrush = androidx.compose.ui.graphics.SolidColor(Palette.Moss600),
                    modifier = Modifier.weight(1f).alpha(if (state.uploading) 0.5f else 1f).clip(RoundedCornerShape(8.dp))
                        .background(if (nc.isDark) nc.bg2 else Color.White).border(1.dp, if (nc.isDark) nc.border else Palette.Hairline, RoundedCornerShape(8.dp)),
                    decorationBox = { inner ->
                        Box(Modifier.padding(horizontal = 8.dp, vertical = 7.dp)) {
                            if (it.caption.isEmpty()) Text("Add a caption (optional)…", fontSize = 12.sp, color = if (nc.isDark) nc.muted else Palette.Stone400, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            inner()
                        }
                    },
                )
            }
            // A file that didn't go says why, under its own row; it stays for a retry.
            it.error?.let { why ->
                Text(
                    "⚠ Not sent — $why", fontSize = 11.sp, lineHeight = 15.sp, color = if (nc0.isDark) Palette.Red400 else Palette.Red700,
                    modifier = Modifier.padding(start = 66.dp),
                )
            }
        }
        // Add-more tile
        Box(
            Modifier.size(56.dp).clip(RoundedCornerShape(8.dp)).dashedBorder(Hue.SageDash, 8.dp)
                .clickable(enabled = !state.uploading) { more.launch(ACCEPT_TYPES) },
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Filled.Add, "Add more", tint = Palette.Sage400) }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Button(
                onClick = vm::sendMedia, enabled = !state.uploading, modifier = Modifier.webHeight(28.dp),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp), shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Palette.Moss600, contentColor = Color.White, disabledContainerColor = Palette.Moss600.copy(alpha = 0.5f), disabledContentColor = Color.White),
            ) {
                if (state.uploading) {
                    CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp, color = Color.White)
                    Spacer(Modifier.width(6.dp)); Text("Sending…", fontSize = 12.sp)
                } else {
                    Icon(Icons.AutoMirrored.Filled.Send, null, Modifier.size(12.dp)); Spacer(Modifier.width(4.dp))
                    Text(
                        when {
                            retry -> if (state.media.size > 1) "Retry ${state.media.size}" else "Retry"
                            state.media.size > 1 -> "Send ${state.media.size}"
                            else -> "Send"
                        },
                        fontSize = 12.sp,
                    )
                }
            }
            OutlinedButton(onClick = vm::clearMedia, enabled = !state.uploading, modifier = Modifier.webHeight(28.dp), contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp), shape = RoundedCornerShape(8.dp), border = androidx.compose.foundation.BorderStroke(1.dp, if (nc0.isDark) nc0.border else Palette.Hairline)) {
                Text("Cancel", fontSize = 12.sp, color = Palette.Sage400)
            }
            Text("Images up to 5 MB each", fontSize = 10.sp, color = Palette.Sage400, textAlign = androidx.compose.ui.text.style.TextAlign.End, modifier = Modifier.weight(1f))
        }
    }
}
