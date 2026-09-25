package ke.co.bethanyhouse.neema.feature.deals

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Deal
import ke.co.bethanyhouse.neema.core.model.PlannedAction
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.EmptyState
import ke.co.bethanyhouse.neema.core.ui.components.Loading
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt

private data class Stage(val id: String, val label: String, val color: Color)

/** The board's columns. A deal in any other stage is shown under New. */
private val STAGES = listOf(
    Stage("new", "New", Color(0xFF94A3B8)),
    Stage("qualified", "Qualified", Color(0xFF589B31)),
    Stage("proposal", "Proposal", Color(0xFFF59E0B)),
)

/** "due now" / "in 12m" / "in 5h" / "in 3d". */
internal fun fmtDue(iso: String?, now: Long = System.currentTimeMillis()): String {
    if (iso.isNullOrBlank()) return ""
    val t = Fmt.millis(iso) ?: return ""
    val d = t - now
    if (d <= 0) return "due now"
    val h = d / 3_600_000
    if (h < 1) return "in ${maxOf(1, d / 60_000)}m"
    if (h < 48) return "in ${h}h"
    return "in ${h / 24}d"
}

/**
 * Port of components/views/DealsView.tsx — the shared board: what Neema owns
 * right now, what's blocking each deal, whose move is next and when she plans
 * to act. On top, her planned-actions queue: send (as drafted or edited) or
 * veto anything before it fires.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DealsScreen(dash: DashboardViewModel) {
    // Permissions come from /me; observing it recomposes the gate once it lands.
    dash.me.collectAsStateWithLifecycle().value
    if (!dash.can(Perms.VIEW_LEADS)) {
        EmptyState(
            title = "No access to deals",
            subtitle = "Your role doesn't include the sales pipeline. Ask an admin if you need it.",
            icon = Icons.Outlined.Lock,
        )
        return
    }
    val vm: DealsViewModel = viewModel { DealsViewModel(dash) }
    val deals by vm.deals.collectAsStateWithLifecycle()
    val wonCount by vm.wonCount.collectAsStateWithLifecycle()
    val actions by vm.actions.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val acting by vm.acting.collectAsStateWithLifecycle()
    // Deals are the pipeline: editing them is lead management. Sending a
    // follow-up puts words in front of a customer, so it follows the reply right.
    val canManage = dash.can(Perms.MANAGE_LEADS)
    val canSend = dash.can(Perms.REPLY_CONVERSATIONS)
    val c = Neema.colors

    val open = deals.orEmpty().filter { it.status == "open" }
    var editing by rememberSaveable { mutableStateOf<String?>(null) }
    var guidanceDraft by rememberSaveable { mutableStateOf("") }
    var draftFor by remember { mutableStateOf<PlannedAction?>(null) }

    val openThread: (Deal) -> Unit = { d ->
        val key = d.waId?.takeIf { it.isNotBlank() } ?: d.conversationId
        if (key != null) dash.openConversationFor(key)
    }

    BoxWithConstraints(Modifier.fillMaxSize().background(c.surface)) {
        val wide = maxWidth >= 600.dp
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            LazyColumn(
                Modifier.fillMaxSize().widthIn(max = 1100.dp).align(Alignment.TopCenter),
                contentPadding = PaddingValues(horizontal = if (wide) 24.dp else 16.dp, vertical = 24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                item(key = "header") {
                    Column {
                        Text("Deals", fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                        Text(
                            "What Neema owns right now · ${open.size} open · $wonCount won",
                            fontSize = 12.sp, color = c.muted, modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }

                // ── Initiative queue ───────────────────────────────────────
                item(key = "queue") {
                    Card16 {
                        Text(
                            "PLANNED ACTIONS — NEEMA'S NEXT MOVES",
                            fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.5.sp, color = c.muted,
                        )
                        Spacer(Modifier.height(8.dp))
                        val pending = actions
                        when {
                            pending == null -> Text("Loading…", fontSize = 12.sp, color = c.muted)
                            pending.isEmpty() -> Text(
                                "Nothing queued. Promises made in chat (hers or the customer's) land here automatically.",
                                fontSize = 12.sp, color = c.muted,
                            )
                            else -> Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                pending.forEach { a ->
                                    ActionRow(
                                        a, busy = a.id in acting, canSend = canSend,
                                        onSend = { vm.act(a.id, "approve") },
                                        onEdit = { draftFor = a },
                                        onVeto = { vm.act(a.id, "veto") },
                                        onOpen = a.conversationId?.let { id -> { dash.openConversationFor(id) } },
                                    )
                                }
                            }
                        }
                    }
                }

                // ── The board ──────────────────────────────────────────────
                if (deals == null) {
                    item(key = "loading") { Box(Modifier.fillMaxWidth().height(160.dp)) { Loading() } }
                } else {
                    val columns = STAGES.map { stage ->
                        stage to open.filter { d ->
                            d.stage == stage.id || (stage.id == "new" && STAGES.none { it.id == d.stage })
                        }
                    }
                    val column: @Composable (Stage, List<Deal>, Modifier) -> Unit = { stage, col, mod ->
                        StageColumn(
                            stage, col, mod,
                            canManage = canManage,
                            editing = editing,
                            guidanceDraft = guidanceDraft,
                            onGuidanceDraft = { guidanceDraft = it.take(400) },
                            onEdit = { d -> editing = d.id; guidanceDraft = d.guidance.orEmpty() },
                            onCancel = { editing = null },
                            onSave = { d -> vm.saveGuidance(d.id, guidanceDraft); editing = null },
                            onWon = { vm.markWon(it.id) },
                            onLost = { vm.markLost(it.id) },
                            onOpen = openThread,
                        )
                    }
                    if (wide) {
                        item(key = "board") {
                            Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.Top) {
                                columns.forEach { (stage, col) -> column(stage, col, Modifier.weight(1f)) }
                            }
                        }
                    } else {
                        columns.forEach { (stage, col) ->
                            item(key = "col-${stage.id}") { column(stage, col, Modifier.fillMaxWidth()) }
                        }
                    }
                }
            }
        }
    }

    draftFor?.let { a ->
        DraftDialog(
            action = a,
            onDismiss = { draftFor = null },
            onSend = { text -> vm.act(a.id, "approve", text); draftFor = null },
        )
    }
}

@Composable
private fun Card16(modifier: Modifier = Modifier, content: @Composable ColumnScope.() -> Unit) {
    val c = Neema.colors
    Column(
        modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(c.bg2)
            .border(1.dp, c.hairline, RoundedCornerShape(16.dp)).padding(16.dp),
        content = content,
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ActionRow(
    a: PlannedAction,
    busy: Boolean,
    canSend: Boolean,
    onSend: () -> Unit,
    onEdit: () -> Unit,
    onVeto: () -> Unit,
    onOpen: (() -> Unit)?,
) {
    val c = Neema.colors
    val needs = a.status == "needs_approval"
    val bg = when {
        c.isDark -> if (needs) c.amberDim else c.bg3
        needs -> Color(0xFFFDF6E9)
        else -> Color(0xFFF8FAF6)
    }
    val border = when {
        c.isDark -> if (needs) c.amber.copy(alpha = 0.4f) else c.border
        needs -> Color(0xFFF0DDB0)
        else -> Color(0xFFE8EDE4)
    }
    val shape = RoundedCornerShape(12.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(bg).border(1.dp, border, shape).padding(horizontal = 12.dp, vertical = 10.dp)) {
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(fontWeight = FontWeight.Medium, color = c.text)) {
                    append(if (needs) "⏳ Needs your approval" else "🕐 ${fmtDue(a.dueAt)}")
                }
                withStyle(SpanStyle(color = Color(0xFF64748B))) {
                    append(" · ")
                    append(if (a.kind == "customer_promise") "their timeline" else "her promise")
                }
            },
            fontSize = 12.sp,
        )
        if (!a.reason.isNullOrBlank()) {
            Text(a.reason, fontSize = 12.sp, color = if (c.isDark) c.textMid else Color(0xFF475569),
                maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
        }
        if (!a.draft.isNullOrBlank()) {
            Text(
                "“${a.draft}”",
                fontSize = 11.sp, color = c.text, maxLines = 3, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 4.dp).fillMaxWidth().clip(RoundedCornerShape(8.dp))
                    .background(c.bg2).border(1.dp, c.hairline, RoundedCornerShape(8.dp))
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            )
        }
        Spacer(Modifier.height(8.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            if (canSend) {
                SmallButton("Send", bg = Color(0xFF589B31), fg = Color.White, enabled = !busy, onClick = onSend)
                SmallButton("Edit & send", bg = c.bg2, fg = c.gold2, border = c.border, enabled = !busy, onClick = onEdit)
                SmallButton("Veto", bg = if (c.isDark) c.bg4 else Color(0xFFF5F5F4), fg = Color(0xFF64748B), enabled = !busy, onClick = onVeto)
            }
            if (onOpen != null) {
                SmallButton("Open chat", bg = Color.Transparent, fg = c.gold2, enabled = true, onClick = onOpen)
            }
            if (busy) CircularProgressIndicator(Modifier.size(18.dp).align(Alignment.CenterVertically), strokeWidth = 2.dp)
        }
    }
}

@Composable
private fun SmallButton(
    label: String,
    bg: Color,
    fg: Color,
    enabled: Boolean,
    border: Color? = null,
    fontSize: Int = 11,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(8.dp)
    Text(
        label,
        modifier = Modifier.clip(shape).background(bg)
            .then(if (border != null) Modifier.border(1.dp, border, shape) else Modifier)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
        color = fg.copy(alpha = if (enabled) 1f else 0.5f), fontSize = fontSize.sp, fontWeight = FontWeight.SemiBold,
    )
}

@Composable
private fun StageColumn(
    stage: Stage,
    col: List<Deal>,
    modifier: Modifier,
    canManage: Boolean,
    editing: String?,
    guidanceDraft: String,
    onGuidanceDraft: (String) -> Unit,
    onEdit: (Deal) -> Unit,
    onCancel: () -> Unit,
    onSave: (Deal) -> Unit,
    onWon: (Deal) -> Unit,
    onLost: (Deal) -> Unit,
    onOpen: (Deal) -> Unit,
) {
    val c = Neema.colors
    Column(
        modifier.clip(RoundedCornerShape(16.dp)).background(c.bg2)
            .border(1.dp, c.hairline, RoundedCornerShape(16.dp)).padding(12.dp)
            .heightIn(min = 120.dp),
    ) {
        Row(Modifier.padding(horizontal = 4.dp).padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(stage.color))
            Spacer(Modifier.width(8.dp))
            Text(stage.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
            Spacer(Modifier.width(8.dp))
            Text(col.size.toString(), fontSize = 10.sp, color = c.muted)
        }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            col.forEach { d ->
                DealCard(
                    d, canManage = canManage, isEditing = editing == d.id,
                    guidanceDraft = guidanceDraft, onGuidanceDraft = onGuidanceDraft,
                    onEdit = { onEdit(d) }, onCancel = onCancel, onSave = { onSave(d) },
                    onWon = { onWon(d) }, onLost = { onLost(d) }, onOpen = { onOpen(d) },
                )
            }
            if (col.isEmpty()) {
                Text("—", fontSize = 11.sp, color = c.border, textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp))
            }
        }
    }
}

@Composable
private fun DealCard(
    d: Deal,
    canManage: Boolean,
    isEditing: Boolean,
    guidanceDraft: String,
    onGuidanceDraft: (String) -> Unit,
    onEdit: () -> Unit,
    onCancel: () -> Unit,
    onSave: () -> Unit,
    onWon: () -> Unit,
    onLost: () -> Unit,
    onOpen: () -> Unit,
) {
    val c = Neema.colors
    val shape = RoundedCornerShape(12.dp)
    val canOpen = !d.waId.isNullOrBlank() || !d.conversationId.isNullOrBlank()
    Column(Modifier.fillMaxWidth().clip(shape).border(1.dp, c.hairline, shape).padding(12.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Text(
                d.customer.ifBlank { "Unknown" },
                fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                textDecoration = if (canOpen) TextDecoration.Underline else null,
                modifier = Modifier.weight(1f).clickable(enabled = canOpen, onClick = onOpen),
            )
            Spacer(Modifier.width(8.dp))
            Text(Fmt.timeAgo(d.updatedAt), fontSize = 10.sp, color = Color(0xFFB5C9A8))
        }
        if (!d.title.isNullOrBlank()) {
            Text(d.title, fontSize = 11.sp, color = if (c.isDark) c.textMid else Color(0xFF475569),
                maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 4.dp))
        }
        if (!d.blocking.isNullOrBlank()) {
            Text("⛔ ${d.blocking}", fontSize = 10.sp, color = Color(0xFFB45309),
                maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
        }
        d.nextAction?.dueAt?.takeIf { it.isNotBlank() }?.let { due ->
            Text(
                "→ ${if (d.nextAction.owner == "ai") "Neema" else "You"} · ${fmtDue(due)}",
                fontSize = 10.sp, color = Color(0xFF589B31), modifier = Modifier.padding(top = 4.dp),
            )
        }
        if (isEditing) {
            OutlinedTextField(
                value = guidanceDraft, onValueChange = onGuidanceDraft,
                placeholder = { Text("e.g. \"No discount on this one\"", fontSize = 11.sp) },
                textStyle = LocalTextStyle.current.copy(fontSize = 12.sp),
                minLines = 2, maxLines = 5,
                supportingText = { Text("${guidanceDraft.length}/400", fontSize = 10.sp) },
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
            )
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                SmallButton("Save", bg = Color(0xFF1E293B), fg = Color.White, enabled = true, fontSize = 10, onClick = onSave)
                SmallButton("Cancel", bg = Color.Transparent, fg = Color(0xFF64748B), enabled = true, fontSize = 10, onClick = onCancel)
            }
        } else {
            // The web shows the guidance as a hover title; on a phone it is printed.
            if (!d.guidance.isNullOrBlank()) {
                Text("📌 ${d.guidance}", fontSize = 10.sp, fontStyle = FontStyle.Italic, color = c.textMid,
                    maxLines = 3, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
            }
            if (canManage) {
                Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SmallButton(
                        if (!d.guidance.isNullOrBlank()) "📌 Guidance" else "＋ Guidance",
                        bg = if (c.isDark) c.bg4 else Color(0xFFFAFAF9), fg = Color(0xFF64748B), enabled = true, fontSize = 10, onClick = onEdit,
                    )
                    SmallButton("Won", bg = if (c.isDark) c.greenDim else Color(0xFFE9F6DF), fg = if (c.isDark) c.green else Color(0xFF427425),
                        enabled = true, fontSize = 10, onClick = onWon)
                    SmallButton("Lost", bg = if (c.isDark) c.bg4 else Color(0xFFFAFAF9), fg = Color(0xFF94A3B8), enabled = true, fontSize = 10, onClick = onLost)
                }
            }
        }
    }
}

/** Approve with an edited draft. Empty text lets Neema compose from the reason. */
@Composable
private fun DraftDialog(action: PlannedAction, onDismiss: () -> Unit, onSend: (String) -> Unit) {
    var text by rememberSaveable(action.id) { mutableStateOf(action.draft.orEmpty()) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Edit before sending") },
        text = {
            Column {
                if (!action.reason.isNullOrBlank()) {
                    Text(action.reason, fontSize = 12.sp, color = Neema.colors.muted, modifier = Modifier.padding(bottom = 8.dp))
                }
                OutlinedTextField(
                    value = text, onValueChange = { text = it },
                    placeholder = { Text("Leave empty and Neema writes it from the reason") },
                    minLines = 4, maxLines = 10, modifier = Modifier.fillMaxWidth(),
                )
            }
        },
        confirmButton = { TextButton(onClick = { onSend(text) }) { Text("Send") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
