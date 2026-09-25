package ke.co.bethanyhouse.neema.feature.conversations

import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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

private val Blue50 = Color(0xFFEFF6FF)
private val Blue200 = Color(0xFFBFDBFE)
private val Blue700 = Color(0xFF1D4ED8)
private val Amber = Color(0xFFF59E0B)

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
    Column(
        Modifier.fillMaxWidth().background(c.bg2).padding(horizontal = 12.dp).padding(top = 10.dp, bottom = 10.dp),
    ) {
        // ── AI draft: a pill when collapsed, the panel when expanded ──
        if (state.draftVisible && !state.draftExpanded) {
            Row(
                Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Blue50)
                    .border(1.dp, Blue200, RoundedCornerShape(12.dp)).clickable { vm.expandDraft(true) }.padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("🤖", fontSize = 14.sp)
                Spacer(Modifier.width(8.dp))
                Text("AI has a draft ready", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Blue700, modifier = Modifier.weight(1f))
                Text("Tap to review ↑", fontSize = 10.sp, color = Color(0xFF60A5FA))
            }
        }
        if (state.draftVisible && state.draftExpanded) DraftPanel(vm, state)
        // ── Generate draft — when no draft exists ──
        if (!state.draftVisible && humanMode) {
            Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), horizontalArrangement = Arrangement.End) {
                OutlinedButton(
                    onClick = vm::generateDraft, enabled = !state.generatingDraft, modifier = Modifier.height(30.dp),
                    contentPadding = PaddingValues(horizontal = 12.dp), shape = RoundedCornerShape(8.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Color(0xFF2563EB)),
                ) {
                    if (state.generatingDraft) {
                        CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp, color = Color(0xFF60A5FA))
                        Spacer(Modifier.width(6.dp)); Text("Generating…", fontSize = 12.sp)
                    } else Text("🤖 Generate AI draft", fontSize = 12.sp)
                }
            }
        }
        // ── The message being answered ──
        state.quoted?.let { q ->
            Row(
                Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(Color(0xFFF1F5F9)),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.width(2.dp).height(44.dp).background(Amber))
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
                        fontSize = 12.sp, color = Color(0xFF475569), maxLines = 1, overflow = TextOverflow.Ellipsis,
                    )
                }
                q.mediaUrl?.let { AsyncImage(it, "quoted", contentScale = ContentScale.Crop, modifier = Modifier.size(36.dp).clip(RoundedCornerShape(4.dp))) }
                IconButton(onClick = vm::clearQuote, modifier = Modifier.size(32.dp)) { Icon(Icons.Filled.Close, "Remove quote", tint = Color(0xFF94A3B8), modifier = Modifier.size(16.dp)) }
            }
        }
        // ── Messaging window — said BEFORE a reply is typed that Meta would refuse ──
        if (window != null && window.mode != "n/a") WindowStrip(window)
        // ── Translate-to-their-language toggle ──
        if (threadLang != null || txOn) {
            Row(Modifier.padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "🌐 " + if (txOn) "Sending in ${state.txPreview?.lang ?: threadLang ?: "their language"}" else "Translate: off",
                    fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
                    color = if (txOn) Color(0xFF427425) else Color(0xFF78716C),
                    modifier = Modifier.clip(RoundedCornerShape(50)).background(if (txOn) Color(0xFFE6F3D8) else Color(0xFFF5F5F4))
                        .border(1.dp, if (txOn) Color(0xFF427425).copy(alpha = 0.3f) else Color(0xFFE7E5E4), RoundedCornerShape(50))
                        .clickable(onClick = vm::toggleTx).padding(horizontal = 10.dp, vertical = 4.dp),
                )
                if (txOn && state.txBusy) Text("translating…", fontSize = 10.sp, color = Color(0xFFA8A29E), modifier = Modifier.padding(start = 8.dp))
            }
        }
        if (txOn && state.txPreview != null && state.replyText.trim().length > 1) {
            Column(
                Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Color(0xFFFAFAF9))
                    .border(1.dp, Color(0xFFE7E5E4), RoundedCornerShape(12.dp)).padding(horizontal = 12.dp, vertical = 8.dp),
            ) {
                Text(
                    ("They will receive" + (state.txPreview.lang?.let { " — $it" } ?: "")).uppercase(),
                    fontSize = 9.sp, fontWeight = FontWeight.SemiBold, color = Color(0xFFA8A29E), letterSpacing = 0.5.sp,
                )
                Text(state.txPreview.text, fontSize = 12.sp, fontStyle = FontStyle.Italic, color = Color(0xFF57534E))
            }
        }
        // ── Text box + attach + send ──
        Row(verticalAlignment = Alignment.Bottom) {
            AttachButton(vm)
            Spacer(Modifier.width(8.dp))
            OutlinedTextField(
                value = state.replyText, onValueChange = vm::setReplyText,
                placeholder = {
                    Text(if (window?.mode == "human_agent") "Type a reply — goes out under your name (human agent)…" else "Type a reply…", fontSize = 14.sp)
                },
                minLines = 1, maxLines = 5, shape = RoundedCornerShape(20.dp),
                modifier = Modifier.weight(1f),
                colors = OutlinedTextFieldDefaults.colors(focusedBorderColor = Amber.copy(alpha = 0.7f)),
            )
            Spacer(Modifier.width(8.dp))
            val closed = window?.mode == "closed"
            val enabled = state.replyText.isNotBlank() && !state.sending && !closed
            Box(
                Modifier.size(48.dp).clip(RoundedCornerShape(16.dp)).background(if (enabled) Amber else Amber.copy(alpha = 0.5f))
                    .clickable(enabled = enabled, onClickLabel = if (closed) (window?.reason ?: "Outside the messaging window") else "Send") { vm.sendReply() },
                contentAlignment = Alignment.Center,
            ) {
                if (state.sending) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp, color = Color.White)
                else Icon(Icons.AutoMirrored.Filled.Send, if (closed) (window?.reason ?: "Outside the messaging window") else "Send", tint = Color.White, modifier = Modifier.size(18.dp))
            }
        }
        if (state.media.isNotEmpty()) MediaTray(vm, state)
    }
}

@Composable
private fun DraftPanel(vm: ConversationsViewModel, state: ComposerUi) {
    Column(Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Blue50).border(1.dp, Blue200, RoundedCornerShape(12.dp))) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("🤖", fontSize = 14.sp); Spacer(Modifier.width(6.dp))
            Text("AI Draft", fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = Blue700, modifier = Modifier.weight(1f))
            Text(
                if (state.draftEditing) "Preview" else "Edit", fontSize = 10.sp, color = Color(0xFF3B82F6),
                modifier = Modifier.clip(RoundedCornerShape(4.dp)).border(1.dp, Blue200, RoundedCornerShape(4.dp)).clickable(onClick = vm::toggleDraftEditing).padding(horizontal = 8.dp, vertical = 2.dp),
            )
            IconButton(onClick = { vm.expandDraft(false) }, modifier = Modifier.size(28.dp)) { Icon(Icons.Filled.KeyboardArrowDown, "Collapse", tint = Color(0xFF60A5FA), modifier = Modifier.size(16.dp)) }
            IconButton(onClick = vm::dismissDraft, modifier = Modifier.size(28.dp)) { Icon(Icons.Filled.Close, "Dismiss", tint = Color(0xFF60A5FA), modifier = Modifier.size(14.dp)) }
        }
        HorizontalDivider(color = Color(0xFFDBEAFE))
        Box(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
            if (state.draftEditing) {
                OutlinedTextField(
                    value = state.draftText, onValueChange = vm::setDraftText, minLines = 4, maxLines = 8,
                    placeholder = { Text("Edit the draft…", fontSize = 12.sp) },
                    textStyle = LocalTextStyle.current.copy(fontSize = 12.sp, color = Color(0xFF1E40AF)),
                    modifier = Modifier.fillMaxWidth(),
                )
            } else {
                Text(state.draftText.ifEmpty { "AI has a reply ready." }, fontSize = 12.sp, lineHeight = 18.sp, color = Blue700)
            }
        }
        Row(Modifier.padding(start = 12.dp, end = 12.dp, bottom = 10.dp).horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            SmallBtn("✓ Send", Color(0xFF589B31), Color.White, vm::approveDraft)
            SmallBtn("Edit & send manually", Color.White, Color(0xFF4F7425), vm::draftToComposer)
            SmallBtn("Dismiss", Color.Transparent, Color(0xFF78716C), vm::dismissDraft)
        }
    }
}

@Composable
internal fun SmallBtn(label: String, bg: Color, fg: Color, onClick: () -> Unit, enabled: Boolean = true) {
    Text(
        label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = fg.copy(alpha = if (enabled) 1f else 0.5f), maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(bg)
            .then(if (bg == Color.White) Modifier.border(1.dp, Color(0xFFE8EBE3), RoundedCornerShape(8.dp)) else Modifier)
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
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(Unit) { while (true) { delay(60_000); now = System.currentTimeMillis() } }
    fun left(iso: String?): String {
        val t = Fmt.millis(iso) ?: return ""
        val ms = t - now
        if (ms <= 0) return ""
        val h = ms / 3_600_000
        val m = (ms % 3_600_000) / 60_000
        return if (h >= 24) "${h / 24}d ${h % 24}h" else if (h > 0) "${h}h ${m}m" else "${m}m"
    }
    val (bg, bd, fg, icon) = when (win.mode) {
        "open" -> Quad(Color(0xFFF0F9E8), Color(0xFFD6E9C2), Color(0xFF427425), "🟢")
        "human_agent" -> Quad(Color(0xFFFFF7ED), Color(0xFFFED7AA), Color(0xFFB45309), "🟠")
        "closed" -> Quad(Color(0xFFFEF2F2), Color(0xFFFECACA), Color(0xFFB91C1C), "🔴")
        else -> Quad(Color(0xFFF5F6F3), Color(0xFFE8EBE3), Color(0xFF6B7E64), "•")
    }
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
    var cameraUri by remember { mutableStateOf<Uri?>(null) }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia()) { vm.addMedia(it) }
    val docs = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { vm.addMedia(it) }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok -> if (ok) cameraUri?.let { vm.addMedia(listOf(it)) } }
    fun launchCamera() {
        val dir = File(context.cacheDir, "camera").apply { mkdirs() }
        val file = File(dir, "photo_${System.currentTimeMillis()}.jpg")
        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
        cameraUri = uri
        camera.launch(uri)
    }
    val camPerm = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted -> if (granted) launchCamera() }
    Box {
        Box(
            Modifier.size(48.dp).clip(RoundedCornerShape(16.dp)).background(if (ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.isDark) ke.co.bethanyhouse.neema.core.ui.theme.Neema.colors.bg3 else Color(0xFFF1F3F5)).clickable { menu = true },
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Filled.AttachFile, "Attach images or files (up to 5 MB each for images)", tint = Color(0xFF64748B), modifier = Modifier.size(18.dp)) }
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
private fun MediaTray(vm: ConversationsViewModel, state: ComposerUi) {
    val more = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { vm.addMedia(it) }
    Column(
        Modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Color(0xFFF5F7F2))
            .border(1.dp, Color(0xFFE8EBE3), RoundedCornerShape(12.dp)).padding(10.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        state.media.forEach { it ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box {
                    if (it.isImage) AsyncImage(it.bytes ?: it.uri, it.name, contentScale = ContentScale.Crop, modifier = Modifier.size(56.dp).clip(RoundedCornerShape(8.dp)).border(1.dp, Color(0xFFEDF0EA), RoundedCornerShape(8.dp)))
                    else Column(
                        Modifier.size(56.dp).clip(RoundedCornerShape(8.dp)).background(Color(0xFFE8EBE3)).padding(2.dp),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
                    ) {
                        Icon(if (it.mime.startsWith("video/")) Icons.Filled.Movie else Icons.Filled.Description, null, tint = Color(0xFF8A9E80), modifier = Modifier.size(20.dp))
                        Text(it.name, fontSize = 9.sp, color = Color(0xFF5F6F57), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                    Box(
                        Modifier.align(Alignment.TopEnd).offset(6.dp, (-6).dp).size(20.dp).clip(CircleShape).background(Color(0xFF1C2917))
                            .clickable(enabled = !state.uploading) { vm.removeMedia(it.id) },
                        contentAlignment = Alignment.Center,
                    ) { Icon(Icons.Filled.Close, "Remove", tint = Color.White, modifier = Modifier.size(12.dp)) }
                }
                Spacer(Modifier.width(10.dp))
                OutlinedTextField(
                    value = it.caption, onValueChange = { v -> vm.setMediaCaption(it.id, v) }, enabled = !state.uploading, singleLine = true,
                    placeholder = { Text("Add a caption (optional)…", fontSize = 12.sp) },
                    textStyle = LocalTextStyle.current.copy(fontSize = 12.sp), modifier = Modifier.weight(1f),
                )
            }
        }
        // Add-more tile
        Box(
            Modifier.size(56.dp).clip(RoundedCornerShape(8.dp)).border(1.dp, Color(0xFFC7CEC0), RoundedCornerShape(8.dp))
                .clickable(enabled = !state.uploading) { more.launch(ACCEPT_TYPES) },
            contentAlignment = Alignment.Center,
        ) { Icon(Icons.Filled.Add, "Add more", tint = Color(0xFF8A9E80)) }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Button(
                onClick = vm::sendMedia, enabled = !state.uploading, modifier = Modifier.height(32.dp),
                contentPadding = PaddingValues(horizontal = 12.dp), shape = RoundedCornerShape(8.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF589B31)),
            ) {
                if (state.uploading) CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 2.dp, color = Color.White)
                else {
                    Icon(Icons.AutoMirrored.Filled.Send, null, Modifier.size(12.dp)); Spacer(Modifier.width(4.dp))
                    Text(if (state.media.size > 1) "Send ${state.media.size}" else "Send", fontSize = 12.sp)
                }
            }
            OutlinedButton(onClick = vm::clearMedia, enabled = !state.uploading, modifier = Modifier.height(32.dp), contentPadding = PaddingValues(horizontal = 12.dp), shape = RoundedCornerShape(8.dp)) {
                Text("Cancel", fontSize = 12.sp, color = Color(0xFF8A9E80))
            }
            Spacer(Modifier.weight(1f))
            Text("Images up to 5 MB each", fontSize = 10.sp, color = Color(0xFF8A9E80))
        }
    }
}
