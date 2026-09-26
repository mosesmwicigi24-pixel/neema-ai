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
import ke.co.bethanyhouse.neema.core.ui.theme.Palette

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
    // One set per change, not per recomposition: a fresh set on every keystroke in the
    // composer made every visible bubble of a long thread recompose.
    val brokenSet by remember { derivedStateOf { brokenVideos.toSet() } }
    var customerOpen by remember { mutableStateOf(true) }      // wide side pane (open by default)
    var customerSheet by remember { mutableStateOf(false) }    // phone / narrow wide
    var activitySheet by remember { mutableStateOf(false) }
    var askDialog by remember { mutableStateOf(false) }
    var answerDialog by remember { mutableStateOf(false) }
    var inviteDialog by remember { mutableStateOf(false) }

    val threadPane: @Composable (Modifier) -> Unit = { mod ->
        if (active == null) {
            Box(mod.background(if (Neema.colors.isDark) Neema.colors.bg else Palette.Slate50), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("💬", fontSize = 36.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("Select a conversation", fontSize = 14.sp, color = if (Neema.colors.isDark) Neema.colors.muted else Hue.SagePale)
                }
            }
        } else {
            ThreadPane(
                vm = vm, dash = dash, conv = active, inbox = inbox, thread = thread, composer = composer, perms = perms,
                wide = wide, roomy = roomy, brokenVideos = brokenSet,
                onView = { viewer = it },
                onProfile = if (!wide || !roomy) ({ customerSheet = true }) else null,
                onActivity = if (!roomy) ({ activitySheet = true; vm.setActivityOpen(true) }) else null,
                onAsk = { askDialog = true }, onAnswer = { answerDialog = true }, onInvite = { inviteDialog = true },
                modifier = mod,
            )
        }
    }

    // Text reads in the theme's ink wherever it sits (the shell's Scaffold does the same).
    CompositionLocalProvider(LocalContentColor provides Neema.colors.text) { if (!wide) {
        if (phoneThread) threadPane(Modifier.fillMaxSize())
        else ConversationList(vm, inbox, listUi, rows, thread.activeId, perms, Modifier.fillMaxSize())
    } else {
        Row(Modifier.fillMaxSize()) {
            // The web's LIST_WIDTH, clamp(340px, 38vw, 436px) — except that a small
            // tablet keeps 320 so the thread still has room to breathe.
            val listWidth = if (widthDp < 840) 320f else (widthDp * 0.38f).coerceIn(340f, 436f)
            ConversationList(vm, inbox, listUi, rows, thread.activeId, perms, Modifier.width(listWidth.dp).fillMaxHeight())
            VerticalDivider(color = hairline())
            threadPane(Modifier.weight(1f).fillMaxHeight())
            // The web's ACTIVITY_WIDTH, clamp(196px, 16vw, 292px); the customer sidebar is w-80.
            if (roomy && active != null) {
                ActivityPane(thread.activity, thread.activityOpen, (widthDp * 0.16f).coerceIn(196f, 292f).dp) { vm.setActivityOpen(it) }
                if (customerOpen) {
                    VerticalDivider(color = hairline())
                    CustomerPanel(
                        dash = dash, conversation = active,
                        onClose = { customerOpen = false },
                        onOpenIdentity = vm::openIdentity,
                        onNameChange = vm::renameCustomer,
                        modifier = Modifier.width(320.dp).fillMaxHeight(),
                    )
                } else SideRail("Customer", flipArrow = true) { customerOpen = true }
            }
        }
    } }

    // ── Customer panel as a sheet (phones, narrower tablets) ──
    if (customerSheet && active != null) {
        ModalBottomSheet(onDismissRequest = { customerSheet = false }, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
            Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 8.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Customer Profile", fontSize = 15.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                IconButton(onClick = { customerSheet = false }) { Icon(Icons.Filled.Close, "Close", tint = Palette.Moss600) }
            }
            HorizontalDivider(color = hairline())
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
            Text("ACTIVITY LOG", fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp, color = Palette.Sage300, modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
            ActivityList(thread.activity, Modifier.fillMaxWidth().heightIn(min = 200.dp, max = 560.dp))
        }
    }

    // ── Dialogs ──
    if (dialogs.transfer) TransferDialog(dash, active, active != null && thread.busyFor(active.id).isNotEmpty(), onPick = { id, name -> vm.transfer(id, name) }) { vm.showTransfer(false) }
    if (dialogs.note) NoteDialog(dialogs.noteText, vm::setNoteText, vm::saveNote) { vm.showNote(false) }
    if (dialogs.clearConfirm) AlertDialog(
        onDismissRequest = { vm.showClear(false) },
        title = { Text("Clear Chat History") },
        text = {
            Text(
                "This will permanently delete all messages in this conversation. The conversation record and customer profile will be kept. This cannot be undone.",
                fontSize = 14.sp, color = if (Neema.colors.isDark) Neema.colors.textMid else Palette.Stone600, // text-sm text-stone-600
            )
        },
        // <Btn variant="danger"> then <Btn variant="outline">, medium size, as on the web.
        confirmButton = {
            ModalButtons {
                WebBtn(if (dialogs.clearing) "Clearing…" else "Yes, clear history", BtnVariant.Danger, vm::clearHistory, enabled = !dialogs.clearing, size = BtnSize.Md)
                WebBtn("Cancel", BtnVariant.Outline, { vm.showClear(false) }, size = BtnSize.Md)
            }
        },
    )
    if (askDialog) AskNeemaDialog(vm) { askDialog = false }
    if (answerDialog) AnswerViaNeemaDialog(vm) { answerDialog = false }
    if (inviteDialog && active != null) InviteDialog(dash, vm, active, inviteTarget(thread.reach, active.id)) { inviteDialog = false }
    viewer?.let { v -> ViewerDialog(v, onClose = { viewer = null }, onVideoError = { id -> if (id != null) brokenVideos += id }) }
}

/**
 * The web's role rules (ConversationsView.tsx): `isAdminOrSuper = is_superuser
 * || role === "admin"`, `canHandleConversations = isAdminOrSuper || role ===
 * "agent"`. Deliberately the ROLE, not `can(PERMS.…)`: the web never consults
 * reply_conversations / intercept_release / transfer_conversations here, and
 * the server (admin.py) checks nothing but sign-in on these routes — only
 * DELETE /messages is admin-only. So a custom role keeps every control its
 * legacy role gives, and a readonly (or supervisor) agent gets none.
 *
 * Who the agent is comes from the freshest record: the team-list row (polled
 * every 180 s, refetched on any 403), else /admin/me — so an admin changing
 * this agent's role reaches the open inbox by itself. Never the sign-in
 * session: like the web (whose `currentAgent` is null until profileApi.me()
 * answers), no record yet means no controls yet.
 */
@Composable
private fun rememberInboxPerms(dash: DashboardViewModel): InboxPerms {
    val me by dash.me.collectAsStateWithLifecycle()
    val agents by dash.agents.collectAsStateWithLifecycle()
    val session by dash.session.collectAsStateWithLifecycle()
    return remember(me, agents, session) { inboxPermsOf(dash) }
}

internal fun inboxPermsOf(dash: DashboardViewModel): InboxPerms {
    val a = dash.currentAgent
    return inboxPermsOf(a?.role, a?.isSuperuser == true, dash.session.value?.agentId ?: a?.id)
}

internal fun inboxPermsOf(role: String?, superuser: Boolean, me: String?): InboxPerms {
    val isAdmin = superuser || role == "admin"
    return InboxPerms(me = me, isAdminOrSuper = isAdmin, canHandle = isAdmin || role == "agent")
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
    modifier: Modifier,
) {
    val can = threadControls(conv, perms)

    val actions = buildList {
        if (can.intercept) add(HeaderAction("Intercept", "⚡", "intercept", primary = true) { vm.intercept(conv.id) })
        if (can.pickUp) add(HeaderAction("Pick up", "🙋", "intercept", primary = true) { vm.intercept(conv.id) })
        if (can.release) add(HeaderAction("Release", "↩", "release", pin = none { it.pin }) { vm.release(conv.id) })
        if (can.pause) add(HeaderAction("Pause", "⏸", "pause") { vm.pause(conv.id) })
        if (can.resume) add(HeaderAction("Resume", "▶", "release", primary = true, pin = none { it.pin }) { vm.release(conv.id) })
        if (can.transfer) add(HeaderAction(if (wide) "" else "Transfer", "⇄") { vm.showTransfer(true) })
        if (can.note) add(HeaderAction(if (wide) "" else "Add note", "📝") { vm.showNote(true) })
        if (can.clearHistory) add(HeaderAction(if (wide) "" else "Clear history", "🗑️", danger = true) { vm.showClear(true) })
    }
    val siblings = remember(inbox.cache, conv.personId, conv.id) {
        if (conv.personId == null) listOf(conv)
        else inbox.cache.values.filter { it.personId == conv.personId }
            .sortedBy { ConversationsViewModel.CHAN_ORDER.indexOf(it.channel).let { i -> if (i < 0) 99 else i } }
    }
    // A backwards scan of the thread (2,000 rows at worst): once per change, not per keystroke.
    val threadLang = remember(thread.messages, thread.activeId) { threadLangOf(thread) }
    val txOn = remember(threadLang, composer.txMode, thread.activeId) { txOnOf(thread, composer) }
    val digits = phoneDigits(conv).orEmpty()
    val hasPhone = digits.isNotEmpty()
    // CustomerSidebar's rule: the invite exists only for a person with a real
    // 7–15-digit phone on their profile and no WhatsApp thread yet.
    val invitePhone = inviteTarget(thread.reach, conv.id)
    val menu = buildList<Pair<String, () -> Unit>> {
        // Shortcuts to the customer panel's Ask Neema / Answer-via-Neema boxes and
        // Invite button (CustomerSidebar.tsx), which the web shows to everyone.
        add("🔎 Ask Neema" to onAsk)
        add("💬 Neema delivers a team answer" to onAnswer)
        if (invitePhone != null) add("🟢 Invite to WhatsApp" to onInvite)
        if (onActivity != null) add("🕘 Activity log" to onActivity)
    }
    // Phone (edge-to-edge, shell bars hidden): keep clear of the nav bar and the
    // keyboard without counting the nav bar twice when the keyboard is up.
    BoxWithConstraints(modifier.then(if (!wide) Modifier.windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars)) else Modifier.imePadding())) {
    // With the keyboard up (or at a large font scale) the composer's extras — the AI
    // draft, the quote, the window strip — scroll inside it; the text box never leaves.
    val composerMax = maxHeight * 0.6f
    Column(Modifier.fillMaxSize()) {
        ThreadHeader(
            conv = conv, siblings = siblings, perms = perms, convBusy = thread.busyFor(conv.id), wide = wide,
            actions = actions, menu = menu,
            // Regular agents see who holds it; admins never see the lock.
            locked = if (can.locked) conv.assignedAgentName?.split(" ")?.firstOrNull() ?: "Locked" else null,
            showBack = !wide, onBack = vm::closeThread,
            // A shortcut to the customer panel's Call button, which the web shows to
            // every signed-in agent (CustomerSidebar.tsx) — so no role gate here either.
            canCall = conv.channel == "whatsapp" && hasPhone,
            onCall = { vm.call(digits, conv.name) },
            onProfile = onProfile,
            onSwitch = { vm.select(it.id) },
            modifier = if (!wide) Modifier.statusBarsPadding() else Modifier,
        )
        HorizontalDivider(color = hairline())
        ThreadMessages(
            convId = conv.id, channel = conv.channel,
            messages = thread.messages[conv.id] ?: emptyList(),
            unreadSnap = thread.unreadSnapshot[conv.id] ?: 0,
            hasMore = thread.hasMore[conv.id] == true,
            loading = thread.loading, error = thread.error, loadingOlder = thread.olderLoading == conv.id,
            errorText = thread.errorText, olderError = thread.olderError == conv.id,
            recovered = thread.recovered, brokenVideos = brokenVideos,
            cb = remember(vm) {
                ThreadCallbacks(
                    onView = onView,
                    onRecover = vm::recoverMedia,
                    onReply = vm::beginReplyTo,
                    fetchVideo = { postId, ch -> runCatching { dash.api.conversations.postVideo(postId, ch) }.getOrNull() },
                    onRetry = { vm.thread.value.activeId.takeIf { it.isNotEmpty() }?.let { vm.loadMessages(it) } },
                    onLoadOlder = vm::loadOlder,
                    onRetrySend = vm::retrySend,
                    onEditFailed = vm::editFailed,
                )
            },
            modifier = Modifier.weight(1f).fillMaxWidth(),
        )
        // Reply box — when the agent owns the conversation, or is admin/superuser.
        if (can.composer) {
            HorizontalDivider(color = hairline())
            Box(Modifier.heightIn(max = composerMax)) { Composer(vm, composer, thread.window, humanMode = true, threadLang = threadLang, txOn = txOn) }
        } else if (can.locked) {
            // Lock banner
            val dark = Neema.colors.isDark
            HorizontalDivider(color = hairline())
            Row(
                Modifier.fillMaxWidth().background(if (dark) Neema.colors.bg2 else Hue.SageBanner).padding(16.dp),
                horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("🔒", fontSize = 16.sp); Spacer(Modifier.width(8.dp))
                Text(
                    androidx.compose.ui.text.buildAnnotatedString {
                        append("Handled by ")
                        pushStyle(androidx.compose.ui.text.SpanStyle(fontWeight = FontWeight.Bold, color = if (dark) Hue.MossNight else Palette.Moss600))
                        append(conv.assignedAgentName ?: "another agent"); pop()
                        append(" — ask them to release or transfer it to you")
                    },
                    fontSize = 12.sp, color = Palette.Sage400,
                )
            }
        }
    }
    }
}

/** The inbox's hairline: `#edf0ea` in light, the theme's border in dark. */
@Composable
internal fun hairline(): Color = if (Neema.colors.isDark) Neema.colors.border else Palette.Hairline2

/** The collapsed side-pane rail ("Activity" / "Customer"). */
@Composable
private fun SideRail(label: String, count: Int = 0, flipArrow: Boolean = false, onClick: () -> Unit) {
    Column(
        Modifier.width(32.dp).fillMaxHeight().background(Neema.colors.bg2).border(0.5.dp, hairline()).clickable(onClickLabel = "Show ${label.lowercase()}", onClick = onClick),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center,
    ) {
        Icon(if (flipArrow) Icons.AutoMirrored.Filled.KeyboardArrowLeft else Icons.AutoMirrored.Filled.KeyboardArrowRight, "Show ${label.lowercase()}", tint = Hue.SagePale)
        Spacer(Modifier.height(4.dp))
        Spacer(Modifier.height(8.dp))
        Text(label.uppercase(), fontSize = 9.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 2.sp, color = if (Neema.colors.isDark) Neema.colors.muted else Hue.SagePale, maxLines = 1, softWrap = false, modifier = Modifier.verticalLabel())
        if (count > 0) {
            Spacer(Modifier.height(12.dp))
            Box(Modifier.size(18.dp).clip(CircleShape).background(Palette.Amber100).border(1.dp, Palette.Amber300, CircleShape), contentAlignment = Alignment.Center) {
                Text(if (count > 20) "20+" else "$count", fontSize = 8.sp, fontWeight = FontWeight.Bold, color = Palette.Amber700)
            }
        }
    }
}

/** Activity Log — collapsible side pane (wide). */
@Composable
private fun ActivityPane(events: List<ActivityEvent>, open: Boolean, width: androidx.compose.ui.unit.Dp, setOpen: (Boolean) -> Unit) {
    if (!open) { SideRail("Activity", events.size) { setOpen(true) }; return }
    Column(Modifier.width(width).fillMaxHeight().background(Neema.colors.bg2)) {
        Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp, top = 8.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("ACTIVITY LOG", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.sp, color = Palette.Sage300, modifier = Modifier.weight(1f))
            IconButton(onClick = { setOpen(false) }, modifier = Modifier.size(28.dp)) {
                Icon(Icons.AutoMirrored.Filled.KeyboardArrowRight, "Collapse activity log", tint = Palette.Sage300)
            }
        }
        HorizontalDivider(color = hairline())
        ActivityList(events, Modifier.weight(1f).fillMaxWidth())
    }
}

private val DOT_COLOR = mapOf(
    "escalated" to (Palette.Amber100 to Palette.Amber300),
    "flag" to (Palette.Red100 to Palette.Red300),
    "intercept" to (Hue.Purple100 to Hue.Purple300),
    "release" to (Hue.Blue100 to Hue.Blue300),
    "transfer" to (Hue.Indigo100 to Hue.Indigo300),
    "approve_draft" to (Hue.Green100 to Hue.Green300),
    "pause" to (Palette.Stone200 to Palette.Stone400),
    "checkin_planned" to (Hue.Sky100 to Hue.Sky300),
    "checkin_sent" to (Hue.Sky200 to Hue.Sky400),
    "checkin_vetoed" to (Palette.Stone100 to Palette.Stone300),
    "checkin_failed" to (Palette.Red100 to Palette.Red300),
    "deal" to (Hue.Emerald100 to Palette.Emerald300),
    "promise" to (Palette.Amber100 to Palette.Amber300),
    "order" to (Hue.Green100 to Hue.Green400),
    "call" to (Hue.Teal100 to Hue.Teal300),
    "tool" to (Hue.Lime50 to Hue.Lime300),
)

/** The person-scoped journey: pickups, check-ins, deals, orders and calls. */
@Composable
private fun ActivityList(events: List<ActivityEvent>, modifier: Modifier) {
    if (events.isEmpty()) {
        Box(modifier.padding(16.dp), contentAlignment = Alignment.Center) {
            Text(
                "No activity yet — pickups, check-ins, deals, orders and calls will appear here as the journey unfolds.",
                fontSize = 11.sp, color = Palette.Stone300, textAlign = TextAlign.Center, lineHeight = 16.sp,
            )
        }
        return
    }
    LazyColumn(modifier, contentPadding = PaddingValues(12.dp)) {
        itemsIndexed(events, key = { _, e -> e.id }) { i, e ->
            val (fill, ring) = DOT_COLOR[e.kind] ?: (Palette.Stone100 to Palette.Stone300)
            Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                Box(Modifier.width(14.dp).fillMaxHeight()) {
                    if (i < events.size - 1) Box(Modifier.padding(start = 6.5.dp, top = 16.dp).width(1.dp).fillMaxHeight().background(if (Neema.colors.isDark) Neema.colors.border else Palette.Stone100))
                    Box(Modifier.padding(top = 2.dp).size(14.dp).clip(CircleShape).background(fill).border(1.dp, ring, CircleShape))
                }
                Spacer(Modifier.width(8.dp))
                Column(Modifier.padding(bottom = 12.dp)) {
                    Text(e.label, fontSize = 11.sp, fontWeight = FontWeight.Medium, lineHeight = 15.sp)
                    e.detail?.takeIf { it.isNotEmpty() }?.let { Text(it, fontSize = 10.sp, color = Hue.SageDetail, lineHeight = 14.sp, modifier = Modifier.padding(top = 2.dp)) }
                    Text(Fmt.timeAgo(e.at), fontSize = 10.sp, color = Palette.Stone400, modifier = Modifier.padding(top = 2.dp))
                }
            }
        }
    }
}

// ═══════════════════════════ Dialogs ═══════════════════════════

@Composable
internal fun TransferDialog(dash: DashboardViewModel, conv: Conversation?, busy: Boolean, onPick: (String, String?) -> Unit, onDismiss: () -> Unit) {
    val agents by dash.agents.collectAsStateWithLifecycle()
    LaunchedEffect(Unit) { dash.refetchAgents() }
    val available = agents.filter { it.isAvailable && it.id != conv?.assignedAgentId }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Transfer Conversation") },
        text = {
            Column {
                Text("Select an agent to transfer this conversation to:", fontSize = 14.sp, color = Palette.Sage400)
                Spacer(Modifier.height(12.dp))
                LazyColumn(Modifier.heightIn(max = 280.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    items(available, key = { it.id }) { a ->
                        Row(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).border(1.dp, hairline(), RoundedCornerShape(12.dp))
                                .clickable(enabled = !busy) { onPick(a.id, a.name) }.padding(12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Avatar(a.name, a.avatarUrl, size = 32.dp)
                            Spacer(Modifier.width(12.dp))
                            Column {
                                Text(a.name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = Neema.colors.text)
                                Text("${a.activeConvs} active conversations", fontSize = 12.sp, color = Palette.Sage300)
                            }
                        }
                    }
                    if (agents.none { it.isAvailable }) item {
                        Text("No available agents", fontSize = 14.sp, color = Palette.Sage300, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp))
                    }
                }
            }
        },
        confirmButton = { ModalButtons { WebBtn("Cancel", BtnVariant.Outline, onDismiss, size = BtnSize.Md) } },
    )
}

/** The web modal footer: `flex gap-2` — left-aligned, the action first, then Cancel. */
@Composable
internal fun ModalButtons(content: @Composable RowScope.() -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically, content = content)
}

@Composable
internal fun NoteDialog(text: String, onText: (String) -> Unit, onSave: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Add Note") },
        text = {
            OutlinedTextField(
                value = text, onValueChange = onText, label = { Text("Note") }, minLines = 4,
                placeholder = { Text("Internal note (not sent to customer)…") }, modifier = Modifier.fillMaxWidth(),
            )
        },
        // <Btn variant="primary"> (amber) then <Btn variant="outline">, medium size, as on the web.
        confirmButton = {
            ModalButtons {
                WebBtn("Save Note", BtnVariant.Primary, onSave, enabled = text.isNotBlank(), size = BtnSize.Md)
                WebBtn("Cancel", BtnVariant.Outline, onDismiss, size = BtnSize.Md)
            }
        },
    )
}

/** The answer / status under the Ask and Answer boxes (CustomerSidebar.tsx). */
@Composable
private fun ResultBox(text: String) {
    val c = Neema.colors
    Text(
        text, fontSize = 13.sp, color = c.text,
        modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(if (c.isDark) c.bg3 else Hue.SageResult)
            .border(1.dp, if (c.isDark) c.border else Hue.SageResultRim, RoundedCornerShape(8.dp)).padding(10.dp),
    )
}

/** Ask Neema: the junior fetches — sizes, past orders, call context. Read-only. */
@Composable
internal fun AskNeemaDialog(vm: ConversationsViewModel, initialQuestion: String = "", initialAnswer: String? = null, onDismiss: () -> Unit) {
    var q by remember { mutableStateOf(initialQuestion) }
    var answer by remember { mutableStateOf(initialAnswer) }
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
                OutlinedTextField(
                    q, { q = it }, placeholder = { Text("Ask Neema… “what were his sizes?”") }, singleLine = true, modifier = Modifier.fillMaxWidth(),
                    // Enter asks, as on the web.
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Send),
                    keyboardActions = androidx.compose.foundation.text.KeyboardActions(onSend = { ask() }),
                )
                answer?.let {
                    Spacer(Modifier.height(8.dp))
                    ResultBox(it)
                }
            }
        },
        confirmButton = {
            ModalButtons {
                WebBtn("Ask", BtnVariant.Primary, { ask() }, enabled = q.isNotBlank(), busy = busy, size = BtnSize.Md)
                WebBtn("Close", BtnVariant.Outline, onDismiss, size = BtnSize.Md)
            }
        },
    )
}

/**
 * Answer via Neema: type the confirmed FACTS; Neema delivers them in her own
 * voice and language, and the thread stays in AI mode.
 */
@Composable
internal fun AnswerViaNeemaDialog(vm: ConversationsViewModel, initialFacts: String = "", initialStatus: String? = null, onDismiss: () -> Unit) {
    var facts by remember { mutableStateOf(initialFacts) }
    var status by remember { mutableStateOf(initialStatus) }
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
                    ResultBox(it)
                }
            }
        },
        confirmButton = {
            ModalButtons {
                WebBtn("Neema delivers", BtnVariant.Primary, {
                    val f = facts.trim()
                    if (f.isNotEmpty() && !busy) {
                        busy = true; status = null
                        scope.launch { val (ok, s) = vm.answerViaNeema(f); status = s; if (ok) facts = ""; busy = false }
                    }
                }, enabled = facts.isNotBlank(), busy = busy, size = BtnSize.Md)
                WebBtn("Close", BtnVariant.Outline, onDismiss, size = BtnSize.Md)
            }
        },
    )
}

/**
 * Send the approved WhatsApp invite template (POST /admin/whatsapp-invite
 * {phone, name}) to the phone on the customer's profile; if that fails (not
 * configured, Meta refused), open WhatsApp with a prefilled message instead —
 * CustomerSidebar's invite button, behind one confirmation.
 */
@Composable
internal fun InviteDialog(dash: DashboardViewModel, vm: ConversationsViewModel, conv: Conversation, profilePhone: String?, onDismiss: () -> Unit) {
    val guess = profilePhone ?: phoneDigits(conv).orEmpty()
    var phone by remember { mutableStateOf(guess) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val uri = LocalUriHandler.current
    val digits = phone.filter { it.isDigit() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Invite to WhatsApp") },
        text = {
            Column {
                Text("Send this customer a WhatsApp invite (delivers the approved template to their number).", fontSize = 13.sp, color = Palette.Sage400)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(phone, { phone = it }, label = { Text("Phone (with country code)") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            }
        },
        confirmButton = {
            ModalButtons {
                WebBtn(if (busy) "Sending…" else "Send invite", BtnVariant.Primary, {
                    busy = true
                    scope.launch {
                        val r = vm.invite(digits, conv.name)
                        if (r == ConversationsViewModel.InviteResult.Sent) {
                            dash.toast("WhatsApp invite sent ✓")
                        } else if (r is ConversationsViewModel.InviteResult.Unknown) {
                            // It may have gone: opening WhatsApp too would invite them twice.
                            dash.toast(r.message, ToastType.Warning)
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
                }, enabled = !busy && digits.length in 7..15, size = BtnSize.Md)
                WebBtn("Cancel", BtnVariant.Outline, onDismiss, size = BtnSize.Md)
            }
        },
    )
}
