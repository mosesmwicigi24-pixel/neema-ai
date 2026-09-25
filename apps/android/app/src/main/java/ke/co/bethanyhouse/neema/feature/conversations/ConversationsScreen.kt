package ke.co.bethanyhouse.neema.feature.conversations

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.app.ToastType
import ke.co.bethanyhouse.neema.core.model.ActivityEvent
import ke.co.bethanyhouse.neema.core.model.Conversation
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.conversations.customer.CustomerPanel
import kotlinx.coroutines.launch

/**
 * The inbox — a port of components/views/ConversationsView.tsx.
 *
 * Phone: the list, and a full-screen thread over it (the shell's bars hide
 * while a thread is open; system back returns to the list). Wide: list and
 * thread side by side, with the activity log and the customer panel as
 * collapsible side panes when the window is roomy enough.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ConversationsScreen(dash: DashboardViewModel) {
    val vm: ConversationsViewModel = viewModel { ConversationsViewModel(dash) }
    val inbox by vm.inbox.collectAsStateWithLifecycle()
    val listUi by vm.list.collectAsStateWithLifecycle()
    val rows by vm.rows.collectAsStateWithLifecycle()
    val thread by vm.thread.collectAsStateWithLifecycle()
    val composer by vm.composer.collectAsStateWithLifecycle()
    val dialogs by vm.dialogs.collectAsStateWithLifecycle()
    val perms = rememberInboxPerms(dash)

    val widthDp = LocalConfiguration.current.screenWidthDp
    val wide = widthDp >= 600
    // Side panes only when the thread would still have room to breathe.
    val roomy = widthDp >= 1100
    val active: Conversation? = inbox.cache[thread.activeId]
    val phoneThread = !wide && thread.threadOpen && active != null

    // The shell hides its bars while a thread owns the phone screen.
    LaunchedEffect(phoneThread) { dash.immersive.value = phoneThread }
    DisposableEffect(Unit) { onDispose { dash.immersive.value = false } }
    BackHandler(enabled = phoneThread) { vm.closeThread() }
    BackHandler(enabled = listUi.selectMode && !phoneThread) { vm.exitSelect() }

    // Wide: the first conversation opens on its own (the web's auto-select).
    LaunchedEffect(wide, rows.isNotEmpty(), thread.activeId.isEmpty()) {
        if (wide && thread.activeId.isEmpty()) rows.firstOrNull()?.let { vm.select(it.rep.id, openThread = false) }
    }

    var viewer by remember { mutableStateOf<Viewer?>(null) }
    val brokenVideos = remember { mutableStateListOf<String>() }
    var customerOpen by remember { mutableStateOf(true) }      // wide side pane (open by default)
    var customerSheet by remember { mutableStateOf(false) }    // phone / narrow wide
    var activitySheet by remember { mutableStateOf(false) }
    var askDialog by remember { mutableStateOf(false) }
    var answerDialog by remember { mutableStateOf(false) }
    var inviteDialog by remember { mutableStateOf(false) }
    var closeConfirm by remember { mutableStateOf(false) }

    val threadPane: @Composable (Modifier) -> Unit = { mod ->
        if (active == null) {
            Box(mod.background(if (Neema.colors.isDark) Neema.colors.bg else Color(0xFFF8FAFC)), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("💬", fontSize = 36.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("Select a conversation", fontSize = 14.sp, color = Color(0xFFC5D5BC))
                }
            }
        } else {
            ThreadPane(
                vm = vm, dash = dash, conv = active, inbox = inbox, thread = thread, composer = composer, perms = perms,
                wide = wide, roomy = roomy, brokenVideos = brokenVideos.toSet(),
                onView = { viewer = it },
                onProfile = if (!wide || !roomy) ({ customerSheet = true }) else null,
                onActivity = if (!roomy) ({ activitySheet = true; vm.setActivityOpen(true) }) else null,
                onAsk = { askDialog = true }, onAnswer = { answerDialog = true }, onInvite = { inviteDialog = true },
                onClose = { closeConfirm = true },
                modifier = mod,
            )
        }
    }

    if (!wide) {
        if (phoneThread) threadPane(Modifier.fillMaxSize())
        else ConversationList(vm, inbox, listUi, rows, thread.activeId, perms, Modifier.fillMaxSize())
    } else {
        Row(Modifier.fillMaxSize()) {
            ConversationList(vm, inbox, listUi, rows, thread.activeId, perms, Modifier.width(if (widthDp >= 900) 380.dp else 320.dp).fillMaxHeight())
            VerticalDivider(color = Color(0xFFEDF0EA))
            threadPane(Modifier.weight(1f).fillMaxHeight())
            if (roomy && active != null) {
                ActivityPane(thread.activity, thread.activityOpen) { vm.setActivityOpen(it) }
                if (customerOpen) {
                    VerticalDivider(color = Color(0xFFEDF0EA))
                    CustomerPanel(
                        dash = dash, conversation = active,
                        onClose = { customerOpen = false },
                        onOpenIdentity = vm::openIdentity,
                        onNameChange = vm::renameCustomer,
                        modifier = Modifier.width(340.dp).fillMaxHeight(),
                    )
                } else SideRail("Customer", flipArrow = true) { customerOpen = true }
            }
        }
    }

    // ── Customer panel as a sheet (phones, narrower tablets) ──
    if (customerSheet && active != null) {
        ModalBottomSheet(onDismissRequest = { customerSheet = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
            Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Customer Profile", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                IconButton(onClick = { customerSheet = false }) { Icon(Icons.Filled.Close, "Close", tint = Color(0xFF589B31)) }
            }
            HorizontalDivider(color = Color(0xFFEDF0EA))
            CustomerPanel(
                dash = dash, conversation = active,
                onClose = { customerSheet = false },
                onOpenIdentity = { ch, ext -> customerSheet = false; vm.openIdentity(ch, ext) },
                onNameChange = vm::renameCustomer,
                modifier = Modifier.fillMaxWidth().fillMaxHeight(0.9f),
                hideHeader = true,
            )
        }
    }
    if (activitySheet && active != null) {
        ModalBottomSheet(onDismissRequest = { activitySheet = false; vm.setActivityOpen(false) }) {
            Text("ACTIVITY LOG", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp, color = Color(0xFFB5C9A8), modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
            ActivityList(thread.activity, Modifier.fillMaxWidth().heightIn(min = 200.dp, max = 560.dp))
        }
    }

    // ── Dialogs ──
    if (dialogs.transfer) TransferDialog(dash, active, thread.convBusy.isNotEmpty(), onPick = { id, name -> vm.transfer(id, name) }) { vm.showTransfer(false) }
    if (dialogs.note) NoteDialog(dialogs.noteText, vm::setNoteText, vm::saveNote) { vm.showNote(false) }
    if (dialogs.clearConfirm) AlertDialog(
        onDismissRequest = { vm.showClear(false) },
        title = { Text("Clear Chat History") },
        text = {
            Text("This will permanently delete all messages in this conversation. The conversation record and customer profile will be kept. This cannot be undone.")
        },
        confirmButton = {
            TextButton(onClick = vm::clearHistory, enabled = !dialogs.clearing) {
                Text(if (dialogs.clearing) "Clearing…" else "Yes, clear history", color = Neema.colors.red)
            }
        },
        dismissButton = { TextButton(onClick = { vm.showClear(false) }) { Text("Cancel") } },
    )
    if (closeConfirm && active != null) AlertDialog(
        onDismissRequest = { closeConfirm = false },
        title = { Text("Close conversation") },
        text = { Text("Close this conversation? Neema takes it back and it leaves the live queue.") },
        confirmButton = { TextButton(onClick = { closeConfirm = false; vm.close(active.id) }) { Text("Close", color = Neema.colors.red) } },
        dismissButton = { TextButton(onClick = { closeConfirm = false }) { Text("Cancel") } },
    )
    if (askDialog) AskNeemaDialog(vm) { askDialog = false }
    if (answerDialog) AnswerViaNeemaDialog(vm) { answerDialog = false }
    if (inviteDialog && active != null) InviteDialog(dash, vm, active) { inviteDialog = false }
    viewer?.let { v -> ViewerDialog(v, onClose = { viewer = null }, onVideoError = { id -> if (id != null) brokenVideos += id }) }
}

/** The web's role rules (admin/superuser, agent) plus the matching permission for custom roles. */
@Composable
private fun rememberInboxPerms(dash: DashboardViewModel): InboxPerms {
    val me by dash.me.collectAsStateWithLifecycle()
    val session by dash.session.collectAsStateWithLifecycle()
    val agents by dash.agents.collectAsStateWithLifecycle()
    return remember(me, session, agents) {
        val role = me?.role ?: session?.role
        val isAdmin = me?.isSuperuser == true || session?.isSuperuser == true || role == "admin"
        val canHandle = isAdmin || role == "agent" || dash.can(Perms.INTERCEPT_RELEASE)
        InboxPerms(
            me = session?.agentId,
            isAdminOrSuper = isAdmin,
            canHandle = canHandle,
            canTransfer = isAdmin || dash.can(Perms.TRANSFER_CONVERSATIONS),
            canNote = canHandle && (isAdmin || dash.can(Perms.ADD_NOTES)),
            canClear = isAdmin || dash.can(Perms.CLEAR_CHAT_HISTORY),
            canClose = canHandle && (isAdmin || dash.can(Perms.CLOSE_CONVERSATIONS)),
            canRelease = isAdmin || dash.can(Perms.INTERCEPT_RELEASE),
            canReply = isAdmin || dash.can(Perms.REPLY_CONVERSATIONS),
        )
    }
}

@Composable
private fun ThreadPane(
    vm: ConversationsViewModel,
    dash: DashboardViewModel,
    conv: Conversation,
    inbox: InboxUi,
    thread: ThreadUi,
    composer: ComposerUi,
    perms: InboxPerms,
    wide: Boolean,
    roomy: Boolean,
    brokenVideos: Set<String>,
    onView: (Viewer) -> Unit,
    onProfile: (() -> Unit)?,
    onActivity: (() -> Unit)?,
    onAsk: () -> Unit,
    onAnswer: () -> Unit,
    onInvite: () -> Unit,
    onClose: () -> Unit,
    modifier: Modifier,
) {
    val me = perms.me
    val mode = conv.interceptMode
    // isOwner: this agent intercepted it; ownedByOther: a different agent holds it.
    val isOwner = conv.assignedAgentId != null && conv.assignedAgentId == me
    val ownedByOther = mode == "human" && conv.assignedAgentId != null && conv.assignedAgentId != me
    // Pause / Resume / Transfer: owner, admin, or nobody human holds it.
    val canAct = perms.canHandle && (isOwner || perms.isAdminOrSuper || mode != "human")

    val actions = buildList {
        // Any agent can intercept an AI conversation — whoever picks it up owns it.
        if (mode == "ai" && perms.canHandle) add(HeaderAction("Intercept", "⚡", "intercept", primary = true) { vm.intercept(conv.id) })
        // Auto-escalated (media) but unclaimed: first one to tap gets it.
        if (mode == "human" && conv.assignedAgentId == null && perms.canHandle) add(HeaderAction("Pick up", "🙋", "intercept", primary = true) { vm.intercept(conv.id) })
        // Owner-restricted: only the intercepting agent or admin can release.
        if (mode == "human" && (isOwner || perms.isAdminOrSuper) && perms.canRelease)
            add(HeaderAction("Release", "↩", "release", primary = none { it.primary }) { vm.release(conv.id) })
        if (mode != "paused" && canAct) add(HeaderAction("Pause", "⏸", "pause") { vm.pause(conv.id) })
        if (mode == "paused" && canAct) add(HeaderAction("Resume", "▶", "release", primary = none { it.primary }) { vm.release(conv.id) })
        if (canAct && perms.canTransfer) add(HeaderAction(if (wide) "" else "Transfer", "⇄") { vm.showTransfer(true) })
        if (perms.canNote) add(HeaderAction(if (wide) "" else "Add note", "📝") { vm.showNote(true) })
        if (perms.canClear) add(HeaderAction(if (wide) "" else "Clear history", "🗑️", danger = true) { vm.showClear(true) })
    }
    val siblings = remember(inbox.cache, conv.personId, conv.id) {
        if (conv.personId == null) listOf(conv)
        else inbox.cache.values.filter { it.personId == conv.personId }
            .sortedBy { ConversationsViewModel.CHAN_ORDER.indexOf(it.channel).let { i -> if (i < 0) 99 else i } }
    }
    val digits = conv.waId?.filter { it.isDigit() }.orEmpty()
    val hasPhone = digits.length in 7..15
    val hasWaChannel = siblings.any { it.channel == "whatsapp" }
    val menu = buildList<Pair<String, () -> Unit>> {
        add("🔎 Ask Neema" to onAsk)
        if (perms.canHandle && perms.canReply) add("💬 Neema delivers a team answer" to onAnswer)
        if (perms.canHandle && !hasWaChannel) add("🟢 Invite to WhatsApp" to onInvite)
        if (perms.canClose && conv.status == "open") add("✓ Close conversation" to onClose)
        if (onActivity != null) add("🕘 Activity log" to onActivity)
    }
    // Phone (edge-to-edge, shell bars hidden): keep clear of the nav bar and the
    // keyboard without counting the nav bar twice when the keyboard is up.
    Column(modifier.then(if (!wide) Modifier.windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars)) else Modifier.imePadding())) {
        ThreadHeader(
            conv = conv, siblings = siblings, perms = perms, convBusy = thread.convBusy, wide = wide,
            actions = actions, menu = menu,
            // Regular agents see who holds it; admins never see the lock.
            locked = if (ownedByOther && !perms.isAdminOrSuper) conv.assignedAgentName?.split(" ")?.firstOrNull() ?: "Locked" else null,
            showBack = !wide, onBack = vm::closeThread,
            canCall = perms.canHandle && conv.channel == "whatsapp" && hasPhone,
            onCall = { vm.call(digits, conv.name) },
            onProfile = onProfile,
            onSwitch = { vm.select(it.id) },
            modifier = if (!wide) Modifier.statusBarsPadding() else Modifier,
        )
        HorizontalDivider(color = Color(0xFFEDF0EA))
        ThreadMessages(
            convId = conv.id, channel = conv.channel,
            messages = thread.messages[conv.id] ?: emptyList(),
            unreadSnap = thread.unreadSnapshot[conv.id] ?: 0,
            hasMore = thread.hasMore[conv.id] == true,
            loading = thread.loading, error = thread.error, loadingOlder = thread.loadingOlder,
            recovered = thread.recovered, brokenVideos = brokenVideos,
            cb = remember(vm) {
                ThreadCallbacks(
                    onView = onView,
                    onRecover = vm::recoverMedia,
                    onReply = vm::beginReplyTo,
                    fetchVideo = { postId, ch -> runCatching { dash.api.conversations.postVideo(postId, ch) }.getOrNull() },
                    onRetry = { vm.thread.value.activeId.takeIf { it.isNotEmpty() }?.let { vm.loadMessages(it) } },
                    onLoadOlder = vm::loadOlder,
                )
            },
            modifier = Modifier.weight(1f).fillMaxWidth(),
        )
        // Reply box — when the agent owns the conversation, or is admin/superuser.
        if (mode == "human" && (conv.assignedAgentId == me || perms.isAdminOrSuper)) {
            HorizontalDivider(color = Color(0xFFEDF0EA))
            Box { Composer(vm, composer, thread.window, humanMode = true, threadLang = threadLangOf(thread), txOn = txOnOf(thread, composer)) }
        } else if (ownedByOther && !perms.isAdminOrSuper) {
            // Lock banner
            HorizontalDivider(color = Color(0xFFEDF0EA))
            Row(
                Modifier.fillMaxWidth().background(Color(0xFFFAFBF8)).padding(16.dp),
                horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("🔒", fontSize = 16.sp); Spacer(Modifier.width(8.dp))
                Text(
                    androidx.compose.ui.text.buildAnnotatedString {
                        append("Handled by ")
                        pushStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.Bold, color = Color(0xFF589B31)))
                        append(conv.assignedAgentName ?: "another agent"); pop()
                        append(" — ask them to release or transfer it to you")
                    },
                    fontSize = 12.sp, color = Color(0xFF8A9E80),
                )
            }
        }
    }
}

/** The collapsed side-pane rail ("Activity" / "Customer"). */
@Composable
private fun SideRail(label: String, count: Int = 0, flipArrow: Boolean = false, onClick: () -> Unit) {
    Column(
        Modifier.width(32.dp).fillMaxHeight().background(Neema.colors.bg2).border(0.5.dp, Color(0xFFEDF0EA)).clickable(onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        Icon(if (flipArrow) Icons.AutoMirrored.Filled.KeyboardArrowLeft else Icons.AutoMirrored.Filled.KeyboardArrowRight, "Show ${label.lowercase()}", tint = Color(0xFFC5D5BC))
        Spacer(Modifier.height(4.dp))
        Text(label.uppercase(), fontSize = 9.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 2.sp, color = Color(0xFFC5D5BC), modifier = Modifier.rotate(-90f).width(80.dp), textAlign = TextAlign.Center)
        if (count > 0) {
            Spacer(Modifier.height(24.dp))
            Box(Modifier.size(18.dp).clip(CircleShape).background(Color(0xFFFEF3C7)).border(1.dp, Color(0xFFFCD34D), CircleShape), contentAlignment = Alignment.Center) {
                Text(if (count > 20) "20+" else "$count", fontSize = 8.sp, fontWeight = FontWeight.Bold, color = Color(0xFFB45309))
            }
        }
    }
}

/** Activity Log — collapsible side pane (wide). */
@Composable
private fun ActivityPane(events: List<ActivityEvent>, open: Boolean, setOpen: (Boolean) -> Unit) {
    if (!open) { SideRail("Activity", events.size) { setOpen(true) }; return }
    Column(Modifier.width(260.dp).fillMaxHeight().background(Neema.colors.bg2)) {
        Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("ACTIVITY LOG", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp, color = Color(0xFFB5C9A8), modifier = Modifier.weight(1f))
            IconButton(onClick = { setOpen(false) }, modifier = Modifier.size(28.dp)) {
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, "Collapse activity log", tint = Color(0xFFB5C9A8))
            }
        }
        HorizontalDivider(color = Color(0xFFEDF0EA))
        ActivityList(events, Modifier.weight(1f).fillMaxWidth())
    }
}

private val DOT_COLOR = mapOf(
    "escalated" to (Color(0xFFFEF3C7) to Color(0xFFFCD34D)),
    "flag" to (Color(0xFFFEE2E2) to Color(0xFFFCA5A5)),
    "intercept" to (Color(0xFFF3E8FF) to Color(0xFFD8B4FE)),
    "release" to (Color(0xFFDBEAFE) to Color(0xFF93C5FD)),
    "transfer" to (Color(0xFFE0E7FF) to Color(0xFFA5B4FC)),
    "approve_draft" to (Color(0xFFDCFCE7) to Color(0xFF86EFAC)),
    "pause" to (Color(0xFFE7E5E4) to Color(0xFFA8A29E)),
    "checkin_planned" to (Color(0xFFE0F2FE) to Color(0xFF7DD3FC)),
    "checkin_sent" to (Color(0xFFBAE6FD) to Color(0xFF38BDF8)),
    "checkin_vetoed" to (Color(0xFFF5F5F4) to Color(0xFFD6D3D1)),
    "checkin_failed" to (Color(0xFFFEE2E2) to Color(0xFFFCA5A5)),
    "deal" to (Color(0xFFD1FAE5) to Color(0xFF6EE7B7)),
    "promise" to (Color(0xFFFEF3C7) to Color(0xFFFCD34D)),
    "order" to (Color(0xFFDCFCE7) to Color(0xFF4ADE80)),
    "call" to (Color(0xFFCCFBF1) to Color(0xFF5EEAD4)),
    "tool" to (Color(0xFFF7FEE7) to Color(0xFFBEF264)),
)

/** The person-scoped journey: pickups, check-ins, deals, orders and calls. */
@Composable
private fun ActivityList(events: List<ActivityEvent>, modifier: Modifier) {
    if (events.isEmpty()) {
        Box(modifier.padding(16.dp), contentAlignment = Alignment.Center) {
            Text(
                "No activity yet — pickups, check-ins, deals, orders and calls will appear here as the journey unfolds.",
                fontSize = 11.sp, color = Color(0xFFD6D3D1), textAlign = TextAlign.Center, lineHeight = 16.sp,
            )
        }
        return
    }
    LazyColumn(modifier, contentPadding = PaddingValues(12.dp)) {
        itemsIndexed(events, key = { _, e -> e.id }) { i, e ->
            val (fill, ring) = DOT_COLOR[e.kind] ?: (Color(0xFFF5F5F4) to Color(0xFFD6D3D1))
            Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                Box(Modifier.width(14.dp).fillMaxHeight()) {
                    if (i < events.size - 1) Box(Modifier.padding(start = 6.5.dp, top = 16.dp).width(1.dp).fillMaxHeight().background(Color(0xFFF5F5F4)))
                    Box(Modifier.padding(top = 2.dp).size(14.dp).clip(CircleShape).background(fill).border(1.dp, ring, CircleShape))
                }
                Spacer(Modifier.width(8.dp))
                Column(Modifier.padding(bottom = 12.dp)) {
                    Text(e.label, fontSize = 11.sp, fontWeight = FontWeight.Medium, lineHeight = 15.sp)
                    e.detail?.let { Text(it, fontSize = 10.sp, color = Color(0xFF8FA383), lineHeight = 14.sp, modifier = Modifier.padding(top = 2.dp)) }
                    Text(Fmt.timeAgo(e.at), fontSize = 10.sp, color = Color(0xFFA8A29E), modifier = Modifier.padding(top = 2.dp))
                }
            }
        }
    }
}

// ═══════════════════════════ Dialogs ═══════════════════════════

@Composable
private fun TransferDialog(dash: DashboardViewModel, conv: Conversation?, busy: Boolean, onPick: (String, String?) -> Unit, onDismiss: () -> Unit) {
    val agents by dash.agents.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { dash.refetchAgents() }
    val available = agents.filter { it.isAvailable && it.id != conv?.assignedAgentId }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Transfer Conversation") },
        text = {
            Column {
                Text("Select an agent to transfer this conversation to:", fontSize = 14.sp, color = Color(0xFF8A9E80))
                Spacer(Modifier.height(12.dp))
                LazyColumn(Modifier.heightIn(max = 280.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(available, key = { it.id }) { a ->
                        Row(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).border(1.dp, Color(0xFFEDF0EA), RoundedCornerShape(12.dp))
                                .clickable(enabled = !busy) { onPick(a.id, a.name) }.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Avatar(a.name, a.avatarUrl, size = 32.dp)
                            Spacer(Modifier.width(12.dp))
                            Column {
                                Text(a.name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold)
                                Text("${a.activeConvs} active conversations", fontSize = 12.sp, color = Color(0xFFB5C9A8))
                            }
                        }
                    }
                    if (agents.none { it.isAvailable }) item {
                        Text("No available agents", fontSize = 14.sp, color = Color(0xFFB5C9A8), textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp))
                    }
                }
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

@Composable
private fun NoteDialog(text: String, onText: (String) -> Unit, onSave: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add Note") },
        text = {
            OutlinedTextField(
                value = text, onValueChange = onText, label = { Text("Note") }, minLines = 4,
                placeholder = { Text("Internal note (not sent to customer)…") }, modifier = Modifier.fillMaxWidth(),
            )
        },
        confirmButton = { Button(onClick = onSave, enabled = text.isNotBlank()) { Text("Save Note") } },
        dismissButton = { OutlinedButton(onClick = onDismiss) { Text("Cancel") } },
    )
}

/** Ask Neema: the junior fetches — sizes, past orders, call context. Read-only. */
@Composable
private fun AskNeemaDialog(vm: ConversationsViewModel, onDismiss: () -> Unit) {
    var q by remember { mutableStateOf("") }
    var answer by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val ask = {
        val question = q.trim()
        if (question.isNotEmpty() && !busy) {
            busy = true; answer = null
            scope.launch { answer = vm.askNeema(question); busy = false }
        }
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Ask Neema") },
        text = {
            Column {
                OutlinedTextField(q, { q = it }, placeholder = { Text("Ask Neema… “what were his sizes?”") }, singleLine = true, modifier = Modifier.fillMaxWidth())
                answer?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(Color(0xFFF8FAF6)).border(1.dp, Color(0xFFE8EDE4), RoundedCornerShape(8.dp)).padding(10.dp))
                }
            }
        },
        confirmButton = { Button(onClick = { ask() }, enabled = !busy && q.isNotBlank()) { Text(if (busy) "…" else "Ask") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
}

/**
 * Answer via Neema: type the confirmed FACTS; Neema delivers them in her own
 * voice and language, and the thread stays in AI mode.
 */
@Composable
private fun AnswerViaNeemaDialog(vm: ConversationsViewModel, onDismiss: () -> Unit) {
    var facts by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Neema delivers") },
        text = {
            Column {
                OutlinedTextField(facts, { facts = it }, placeholder = { Text("Team answer… “yes, we make it — KES 3,500, ~5 days”") }, minLines = 2, modifier = Modifier.fillMaxWidth())
                status?.let {
                    Spacer(Modifier.height(8.dp))
                    Text(it, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(Color(0xFFF8FAF6)).border(1.dp, Color(0xFFE8EDE4), RoundedCornerShape(8.dp)).padding(10.dp))
                }
            }
        },
        confirmButton = {
            Button(onClick = {
                val f = facts.trim()
                if (f.isNotEmpty() && !busy) {
                    busy = true; status = null
                    scope.launch { val (ok, s) = vm.answerViaNeema(f); status = s; if (ok) facts = ""; busy = false }
                }
            }, enabled = !busy && facts.isNotBlank()) { Text(if (busy) "…" else "Neema delivers") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Close") } },
    )
}

/** Send the approved WhatsApp invite template; if that fails, open WhatsApp with a prefilled message. */
@Composable
private fun InviteDialog(dash: DashboardViewModel, vm: ConversationsViewModel, conv: Conversation, onDismiss: () -> Unit) {
    val guess = conv.waId?.filter { it.isDigit() }?.takeIf { it.length in 7..15 }.orEmpty()
    var phone by remember { mutableStateOf(guess) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val uri = LocalUriHandler.current
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Invite to WhatsApp") },
        text = {
            Column {
                Text("Send this customer a WhatsApp invite (delivers the approved template to their number).", fontSize = 13.sp, color = Color(0xFF8A9E80))
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(phone, { phone = it }, label = { Text("Phone (with country code)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            Button(enabled = !busy && phone.filter { it.isDigit() }.length in 7..15, onClick = {
                val digits = phone.filter { it.isDigit() }
                busy = true
                scope.launch {
                    if (vm.invite(digits, conv.name)) {
                        dash.toast("WhatsApp invite sent ✓")
                    } else {
                        // Fallback: open WhatsApp manually if the template send fails.
                        val first = conv.name?.trim()?.split(Regex("\\s+"))?.firstOrNull().orEmpty()
                        val text = "Hello${if (first.isNotEmpty()) " $first" else ""}, this is Bethany House. " +
                            "Continuing our chat here on WhatsApp so we can finalise your order."
                        runCatching { uri.openUri("https://wa.me/$digits?text=${java.net.URLEncoder.encode(text, "UTF-8").replace("+", "%20")}") }
                            .onFailure { dash.toast("Couldn't send the invite", ToastType.Error) }
                    }
                    busy = false
                    onDismiss()
                }
            }) { Text(if (busy) "Sending…" else "Send invite") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
