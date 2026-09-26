package ke.co.bethanyhouse.neema.feature.deals

import androidx.compose.ui.semantics.Role
import ke.co.bethanyhouse.neema.feature.orders.pressedOn
import ke.co.bethanyhouse.neema.feature.orders.touchCell
import androidx.compose.runtime.remember
import androidx.compose.foundation.interaction.MutableInteractionSource
import ke.co.bethanyhouse.neema.core.util.AppClock

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.model.Deal
import ke.co.bethanyhouse.neema.core.model.PlannedAction
import ke.co.bethanyhouse.neema.core.ui.components.ErrorState
import ke.co.bethanyhouse.neema.feature.orders.InlineError
import ke.co.bethanyhouse.neema.feature.orders.StaleBanner
import ke.co.bethanyhouse.neema.core.ui.components.Loading
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.feature.orders.SalesInk
import ke.co.bethanyhouse.neema.feature.orders.listSegment
import androidx.compose.foundation.lazy.itemsIndexed
import ke.co.bethanyhouse.neema.core.util.Fmt

private data class Stage(val id: String, val label: String, val color: Color)

/** The board's columns. A deal in any other stage is shown under New. */
private val STAGES = listOf(
    Stage("new", "New", Palette.Slate400),
    Stage("qualified", "Qualified", Palette.Moss600),
    Stage("proposal", "Proposal", Palette.Amber500),
)

/**
 * The open deals by board column ("new" / "qualified" / "proposal"), in their
 * order, in one pass: a deal in any other stage lands under New. Every column
 * is present, empty or not.
 */
internal fun groupByStage(open: List<Deal>): Map<String, List<Deal>> {
    val ids = STAGES.map { it.id }
    val out = ids.associateWith { ArrayList<Deal>() }
    for (d in open) out.getValue(d.stage.takeIf { it in ids } ?: "new").add(d)
    return out
}

/** "due now" / "in 12m" / "in 5h" / "in 3d". */
internal fun fmtDue(iso: String?, now: Long = AppClock.now()): String {
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
    // No permission gate here: page.tsx hides the Deals nav item without
    // view_leads, but DealsView itself checks nothing (a ?view=deals link still
    // opens it), and crm.py's deals/actions routes only require a signed-in
    // agent. Send, Veto, Guidance, Won and Lost show for everyone, as on the web.
    val vm: DealsViewModel = viewModel { DealsViewModel(dash) }
    ke.co.bethanyhouse.neema.feature.reports.TrackShown(vm.life)
    val deals by vm.deals.collectAsStateWithLifecycle()
    val wonCount by vm.wonCount.collectAsStateWithLifecycle()
    val actions by vm.actions.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val acting by vm.acting.collectAsStateWithLifecycle()
    val checking by vm.checking.collectAsStateWithLifecycle()
    val patching by vm.patching.collectAsStateWithLifecycle()
    val loadError by vm.loadError.collectAsStateWithLifecycle()
    val guidanceError by vm.guidanceError.collectAsStateWithLifecycle()
    val c = Neema.colors

    // Derived once per load, not on every recomposition (a tick of the queue's spinner, a keystroke in the guidance).
    val open = remember(deals) { deals.orEmpty().filter { it.status == "open" } }
    val columns = remember(open) { groupByStage(open).let { g -> STAGES.map { it to g.getValue(it.id) } } }
    val editing by vm.editing.collectAsStateWithLifecycle()
    val guidanceDraft by vm.guidanceDraft.collectAsStateWithLifecycle()
    val draftFor by vm.draftFor.collectAsStateWithLifecycle()

    val openThread: (Deal) -> Unit = { d ->
        val key = d.waId?.takeIf { it.isNotBlank() } ?: d.conversationId
        if (key != null) dash.openConversationFor(key)
    }

    // The page is the web's own #f6f7f2, a shade off the shell's parchment.
    BoxWithConstraints(Modifier.fillMaxSize().background(if (c.isDark) c.surface else SalesInk.DealsPage)) {
        // Three stage columns (and the queue's buttons beside its text) need a
        // real tablet width: at ~600dp they squeezed a card's buttons to nothing.
        val wide = maxWidth >= 840.dp
        val gutter = if (maxWidth >= 600.dp) 24.dp else 16.dp
        PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.fillMaxSize()) {
            // No imePadding here: the shell pads the whole content area above the keyboard.
            // Every block carries its own 16dp gap beneath it (the web's space-y-4), so a
            // card drawn a slice per item (the queue, a phone's stage columns) stays whole.
            LazyColumn(
                Modifier.fillMaxSize().widthIn(max = 1100.dp).align(Alignment.TopCenter),
                contentPadding = PaddingValues(horizontal = gutter, vertical = 24.dp),
            ) {
                item(key = "header", contentType = "header") {
                    Column(Modifier.padding(bottom = 16.dp)) {
                        Text("Deals", fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                        Text(
                            // Never loaded: no counts — "0 open · 0 won" would be a claim.
                            if (deals == null) "What Neema owns right now"
                            else "What Neema owns right now · ${open.size} open · $wonCount won",
                            fontSize = 12.sp, color = c.muted, modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }

                // A refresh failed with something on screen: it stays, and this says why.
                val err = loadError
                if (err != null && (deals != null || actions != null)) {
                    item(key = "stale", contentType = "stale") { StaleBanner(err, onRetry = vm::refresh, modifier = Modifier.padding(bottom = 16.dp)) }
                }

                // ── Initiative queue ───────────────────────────────────────
                // One bordered card, drawn a slice per item: a queue of 200
                // follow-ups composes only the rows on screen.
                val pending = actions
                val rows = pending.orEmpty()
                item(key = "queue", contentType = "queue-head") {
                    QueueSlice(first = true, last = rows.isEmpty()) {
                        Text(
                            "PLANNED ACTIONS — NEEMA'S NEXT MOVES",
                            fontSize = 11.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.275.sp, color = c.muted,
                        )
                        Spacer(Modifier.height(8.dp))
                        when {
                            // The reason is in the banner / error state just below.
                            pending == null && err != null -> Text("Couldn't load the queue.", fontSize = 12.sp, color = stone400())
                            pending == null -> Text("Loading…", fontSize = 12.sp, color = stone400())
                            pending.isEmpty() -> Text(
                                "Nothing queued. Promises made in chat (hers or the customer's) land here automatically.",
                                fontSize = 12.sp, color = stone400(),
                            )
                        }
                    }
                }
                itemsIndexed(rows, key = { _, a -> "action-${a.id}" }, contentType = { _, _ -> "action" }) { i, a ->
                    QueueSlice(first = false, last = i == rows.lastIndex) {
                        ActionRow(
                            a, busy = a.id in acting, checking = a.id in checking, wide = wide,
                            onSend = { vm.act(a.id, "approve") },
                            onEdit = { vm.openDraft(a) },
                            onVeto = { vm.act(a.id, "veto") },
                            onOpen = a.conversationId?.let { id -> { dash.openConversationFor(id) } },
                        )
                    }
                }

                // ── The board ──────────────────────────────────────────────
                if (deals == null && err != null) {
                    // Nothing was ever read: an empty board would claim there are no deals.
                    item(key = "error", contentType = "error") { ErrorState(err, onRetry = vm::reload) }
                } else if (deals == null) {
                    item(key = "loading", contentType = "loading") { Box(Modifier.fillMaxWidth().height(160.dp)) { Loading() } }
                } else {
                    val cardFor: @Composable (Deal) -> Unit = { d ->
                        DealCard(
                            d, busy = d.id in patching, isEditing = editing == d.id,
                            guidanceError = guidanceError.takeIf { editing == d.id },
                            guidanceDraft = guidanceDraft, onGuidanceDraft = vm::setGuidanceDraft,
                            onEdit = { vm.startGuidance(d) }, onCancel = vm::cancelGuidance, onSave = { vm.saveGuidance(d.id) },
                            onWon = { vm.markWon(d.id) }, onLost = { vm.markLost(d.id) }, onOpen = { openThread(d) },
                        )
                    }
                    if (wide) {
                        item(key = "board", contentType = "board") {
                            Row(Modifier.padding(bottom = 16.dp), horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.Top) {
                                columns.forEach { (stage, col) -> StageColumn(stage, col, Modifier.weight(1f), cardFor) }
                            }
                        }
                    } else {
                        // A phone stacks the columns; each is a card drawn a slice per deal.
                        columns.forEach { (stage, col) ->
                            if (col.isEmpty()) {
                                item(key = "col-${stage.id}", contentType = "col-empty") {
                                    StageColumn(stage, col, Modifier.fillMaxWidth().padding(bottom = 16.dp), cardFor)
                                }
                            } else {
                                item(key = "col-${stage.id}", contentType = "col-head") {
                                    ColumnSlice(first = true, last = false) { StageHeader(stage, col.size) }
                                }
                                itemsIndexed(col, key = { _, d -> "deal-${stage.id}-${d.id}" }, contentType = { _, _ -> "deal" }) { i, d ->
                                    val last = i == col.lastIndex
                                    ColumnSlice(first = false, last = last) {
                                        Box(Modifier.padding(bottom = if (last) 0.dp else 8.dp)) { cardFor(d) }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    draftFor?.let { a ->
        val text by vm.draftText.collectAsStateWithLifecycle()
        val error by vm.draftError.collectAsStateWithLifecycle()
        // The dialog stays up until the send is known to have gone: a failure
        // shows its reason here, with every word the operator typed.
        DraftDialog(
            action = a, text = text, onText = vm::setDraftText,
            busy = a.id in acting, checking = a.id in checking, error = error,
            onDismiss = { vm.openDraft(null) },
            onSend = { vm.act(a.id, "approve", text) },
        )
    }
}

/**
 * One slice of the queue's card (`rounded-2xl border border-stone-200 p-4`,
 * mb-5): the first carries the rounded top and the padding above, the last
 * the rounded bottom, the padding below and the card's margin; rows sit 8dp apart.
 */
@Composable
private fun QueueSlice(first: Boolean, last: Boolean, content: @Composable ColumnScope.() -> Unit) {
    val c = Neema.colors
    Column(
        Modifier.padding(bottom = if (last) 20.dp else 0.dp).fillMaxWidth()
            .listSegment(first, last, border = stone200(), fill = c.bg2, radius = 16.dp)
            .padding(start = 16.dp, end = 16.dp, top = if (first) 16.dp else 0.dp, bottom = when { last -> 16.dp; first -> 0.dp; else -> 8.dp }),
        content = content,
    )
}

/** One slice of a phone's stage column card (`rounded-2xl border p-3`, 16dp beneath). */
@Composable
private fun ColumnSlice(first: Boolean, last: Boolean, content: @Composable ColumnScope.() -> Unit) {
    val c = Neema.colors
    Column(
        Modifier.padding(bottom = if (last) 16.dp else 0.dp).fillMaxWidth()
            .listSegment(first, last, border = stone200(), fill = c.bg2, radius = 16.dp)
            .padding(start = 12.dp, end = 12.dp, top = if (first) 12.dp else 0.dp, bottom = if (last) 12.dp else 0.dp),
        content = content,
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ActionRow(
    a: PlannedAction,
    busy: Boolean,
    checking: Boolean,
    wide: Boolean,
    onSend: () -> Unit,
    onEdit: () -> Unit,
    onVeto: () -> Unit,
    onOpen: (() -> Unit)?,
) {
    val c = Neema.colors
    val needs = a.status == "needs_approval"
    val bg = when {
        c.isDark -> if (needs) c.amberDim else c.bg3
        needs -> SalesInk.NeedsBg
        else -> SalesInk.QueuedBg
    }
    val border = when {
        c.isDark -> if (needs) c.amber.copy(alpha = 0.4f) else c.border
        needs -> SalesInk.NeedsBorder
        else -> SalesInk.QueuedBorder
    }
    val shape = RoundedCornerShape(12.dp)
    val body: @Composable ColumnScope.() -> Unit = {
        Text(
            buildAnnotatedString {
                withStyle(SpanStyle(fontWeight = FontWeight.Medium, color = c.text)) {
                    append(if (needs) "⏳ Needs your approval" else "🕐 ${fmtDue(a.dueAt)}")
                }
                withStyle(SpanStyle(color = slate())) {
                    append(" · ")
                    append(if (a.kind == "customer_promise") "their timeline" else "her promise")
                }
            },
            fontSize = 12.sp,
        )
        if (!a.reason.isNullOrBlank()) {
            Text(a.reason, fontSize = 12.sp, color = if (c.isDark) c.textMid else SalesInk.Slate600,
                maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 2.dp))
        }
        if (!a.draft.isNullOrBlank()) {
            Text(
                "“${a.draft}”",
                fontSize = 11.sp, color = c.text, maxLines = 3, overflow = TextOverflow.Ellipsis,
                modifier = Modifier.padding(top = 4.dp).fillMaxWidth().clip(RoundedCornerShape(8.dp))
                    .background(c.bg2).border(1.dp, if (c.isDark) c.hairline else Palette.Stone100, RoundedCornerShape(8.dp))
                    .padding(horizontal = 8.dp, vertical = 6.dp),
            )
        }
    }
    val buttons: @Composable () -> Unit = { Column {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            SmallButton("Send", bg = Palette.Moss600, fg = Color.White, enabled = !busy, onClick = onSend)
            SmallButton("Edit & send", bg = c.bg2, fg = c.gold2, border = c.border, enabled = !busy, onClick = onEdit)
            SmallButton("Veto", bg = if (c.isDark) c.bg4 else Palette.Stone100, fg = slate(), enabled = !busy, onClick = onVeto)
            if (onOpen != null) {
                SmallButton("Open chat", bg = Color.Transparent, fg = c.gold2, enabled = true, onClick = onOpen)
            }
        }
        // In flight, or its answer lost and being checked: say which, under the (locked) buttons.
        if (busy) {
            Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(Modifier.size(12.dp), strokeWidth = 1.5.dp, color = slate())
                Text(
                    if (checking) "No answer yet — checking whether it went…" else "Working…",
                    fontSize = 11.sp, color = slate(), modifier = Modifier.padding(start = 6.dp),
                )
            }
        }
    } }
    val box = Modifier.fillMaxWidth().clip(shape).background(bg).border(1.dp, border, shape).padding(horizontal = 12.dp, vertical = 10.dp)
    if (wide) {
        // The web's row: the text takes the room, the buttons sit on the right (gap-3).
        Row(box, verticalAlignment = Alignment.Top) {
            Column(Modifier.weight(1f), content = body)
            Spacer(Modifier.width(12.dp))
            Box(Modifier.widthIn(max = 320.dp)) { buttons() }
        }
    } else {
        // A phone has no room beside the text for three buttons: they go beneath it.
        Column(box) {
            body()
            Spacer(Modifier.height(8.dp))
            buttons()
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
    hPad: Dp = 12.dp,
    vPad: Dp = 6.dp,
    weight: FontWeight = FontWeight.SemiBold,
    onClick: () -> Unit,
) {
    val shape = RoundedCornerShape(8.dp)
    val press = remember { MutableInteractionSource() }
    Text(
        label,
        // The web's compact button to the eye, a 48dp cell to the finger (and to TalkBack).
        modifier = Modifier.touchCell(press, enabled = enabled, role = Role.Button, onClick = onClick)
            .clip(shape).background(if (enabled) bg else bg.copy(alpha = bg.alpha * 0.5f))
            .then(if (border != null) Modifier.border(1.dp, border, shape) else Modifier)
            .pressedOn(press)
            .padding(horizontal = hPad, vertical = vPad),
        // The web's inherited 1.5 line height, not the theme's body 21sp.
        color = fg.copy(alpha = if (enabled) 1f else 0.5f), fontSize = fontSize.sp, lineHeight = (fontSize * 1.5).sp,
        fontWeight = weight, maxLines = 1,
    )
}

@Composable
private fun StageColumn(stage: Stage, col: List<Deal>, modifier: Modifier, card: @Composable (Deal) -> Unit) {
    val c = Neema.colors
    Column(
        // min-h-[120px] counts the padding, as a border-box does.
        modifier.heightIn(min = 120.dp).clip(RoundedCornerShape(16.dp)).background(c.bg2)
            .border(1.dp, stone200(), RoundedCornerShape(16.dp)).padding(12.dp),
    ) {
        StageHeader(stage, col.size)
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            col.forEach { d -> key(d.id) { card(d) } }
            if (col.isEmpty()) {
                Text("—", fontSize = 11.sp, color = if (c.isDark) c.border else Palette.Stone300, textAlign = TextAlign.Center,
                    modifier = Modifier.fillMaxWidth().padding(vertical = 16.dp))
            }
        }
    }
}

/** A stage column's title row: its dot, name and count. */
@Composable
private fun StageHeader(stage: Stage, count: Int) {
    val c = Neema.colors
    Row(Modifier.padding(horizontal = 4.dp).padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(stage.color))
        Spacer(Modifier.width(8.dp))
        Text(stage.label, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
        Spacer(Modifier.width(8.dp))
        Text(count.toString(), fontSize = 10.sp, color = c.muted)
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun DealCard(
    d: Deal,
    busy: Boolean,
    guidanceError: String?,
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
    Column(Modifier.fillMaxWidth().clip(shape).border(1.dp, if (c.isDark) c.hairline else Palette.Stone100, shape).padding(12.dp)) {
        Row(verticalAlignment = Alignment.Top) {
            Text(
                d.customer.ifBlank { "Unknown" },
                fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text,
                maxLines = 1, overflow = TextOverflow.Ellipsis,
                textDecoration = if (canOpen) TextDecoration.Underline else null,
                modifier = Modifier.weight(1f).clickable(enabled = canOpen, onClick = onOpen),
            )
            Spacer(Modifier.width(8.dp))
            Text(Fmt.timeAgo(d.updatedAt), fontSize = 10.sp, color = if (c.isDark) c.muted else Palette.Sage300)
        }
        if (!d.title.isNullOrBlank()) {
            Text(d.title, fontSize = 11.sp, color = if (c.isDark) c.textMid else SalesInk.Slate600,
                maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 4.dp))
        }
        if (!d.blocking.isNullOrBlank()) {
            Text("⛔ ${d.blocking}", fontSize = 10.sp, color = if (c.isDark) Palette.Amber500 else Palette.Amber700,
                maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
        }
        d.nextAction?.dueAt?.takeIf { it.isNotBlank() }?.let { due ->
            Text(
                "→ ${if (d.nextAction.owner == "ai") "Neema" else "You"} · ${fmtDue(due)}",
                fontSize = 10.sp, color = if (c.isDark) c.green else Palette.Moss600, modifier = Modifier.padding(top = 4.dp),
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
            if (guidanceError != null) InlineError(guidanceError, Modifier.padding(top = 4.dp))
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                SmallButton(if (busy) "Saving…" else "Save", bg = SalesInk.Slate800, fg = Color.White, enabled = !busy, fontSize = 10, hPad = 10.dp, vPad = 4.dp, onClick = onSave)
                SmallButton("Cancel", bg = Color.Transparent, fg = slate(), enabled = true, fontSize = 10, hPad = 8.dp, vPad = 4.dp,
                    weight = FontWeight.Normal, onClick = onCancel)
            }
        } else {
            // The web shows the guidance as a hover title; on a phone it is printed.
            if (!d.guidance.isNullOrBlank()) {
                Text("📌 ${d.guidance}", fontSize = 10.sp, fontStyle = FontStyle.Italic, color = c.textMid,
                    maxLines = 3, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(top = 6.dp))
            }
            // A flow, not a row: a narrow column wraps Lost instead of crushing it.
            FlowRow(Modifier.padding(top = 2.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                SmallButton(
                    if (!d.guidance.isNullOrBlank()) "📌 Guidance" else "＋ Guidance",
                    bg = if (c.isDark) c.bg4 else Palette.Stone50, fg = slate(), enabled = !busy, fontSize = 10,
                    hPad = 8.dp, vPad = 4.dp, weight = FontWeight.Normal, onClick = onEdit,
                )
                SmallButton("Won", bg = if (c.isDark) c.greenDim else SalesInk.WonBg, fg = if (c.isDark) c.green else Palette.Moss700,
                    enabled = !busy, fontSize = 10, hPad = 8.dp, vPad = 4.dp, weight = FontWeight.Normal, onClick = onWon)
                SmallButton("Lost", bg = if (c.isDark) c.bg4 else Palette.Stone50, fg = if (c.isDark) c.muted else Palette.Slate400, enabled = !busy, fontSize = 10,
                    hPad = 8.dp, vPad = 4.dp, weight = FontWeight.Normal, onClick = onLost)
            }
        }
    }
}

/** Approve with an edited draft. Empty text lets Neema compose from the reason. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun DraftDialog(
    action: PlannedAction, text: String, onText: (String) -> Unit,
    busy: Boolean, checking: Boolean, error: String?,
    onDismiss: () -> Unit, onSend: () -> Unit,
) {
    BasicAlertDialog(onDismissRequest = onDismiss) {
        DraftDialogCard(action, text, onText, busy, checking, error, onDismiss, onSend)
    }
}

/** The edit-and-send dialog's card (internal so it can be rendered without a dialog window). */
@Composable
internal fun DraftDialogCard(
    action: PlannedAction,
    text: String,
    onText: (String) -> Unit,
    busy: Boolean,
    checking: Boolean,
    error: String?,
    onDismiss: () -> Unit,
    onSend: () -> Unit,
) {
    val c = Neema.colors
    Surface(shape = RoundedCornerShape(24.dp), color = c.bg2, shadowElevation = 6.dp) {
        Column(Modifier.padding(24.dp)) {
            Text("Edit before sending", fontSize = 20.sp, fontWeight = FontWeight.SemiBold, color = c.text)
            Spacer(Modifier.height(12.dp))
            if (!action.reason.isNullOrBlank()) {
                Text(action.reason, fontSize = 12.sp, color = c.muted, modifier = Modifier.padding(bottom = 8.dp))
            }
            OutlinedTextField(
                value = text, onValueChange = onText, enabled = !busy,
                placeholder = { Text("Leave empty and Neema writes it from the reason") },
                minLines = 4, maxLines = 10, modifier = Modifier.fillMaxWidth(),
            )
            if (error != null) InlineError(error, Modifier.padding(top = 12.dp), pending = checking)
            Row(Modifier.fillMaxWidth().padding(top = 16.dp), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onDismiss) { Text(if (busy) "Close" else "Cancel") }
                Spacer(Modifier.width(8.dp))
                Button(
                    onClick = onSend, enabled = !busy,
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Palette.Moss600, contentColor = Color.White,
                        disabledContainerColor = Palette.Moss600.copy(alpha = 0.5f), disabledContentColor = Color.White,
                    ),
                ) {
                    if (busy) {
                        CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = Color.White)
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(
                        when {
                            checking -> "Checking…"
                            busy -> "Sending…"
                            text.isBlank() -> "Let Neema write & send"
                            else -> "Send"
                        },
                    )
                }
            }
        }
    }
}

/** The web's slate-500 secondary text; lifted in dark mode so it stays legible on navy. */
@Composable
private fun slate(): Color = if (Neema.colors.isDark) Palette.Slate400 else Palette.Slate500

/** Tailwind stone-200, the web's card border; the theme hairline in dark mode. */
@Composable
private fun stone200(): Color = if (Neema.colors.isDark) Neema.colors.hairline else Palette.Stone200

/** Tailwind stone-400, the queue's quiet text; the theme's muted in dark mode. */
@Composable
private fun stone400(): Color = if (Neema.colors.isDark) Neema.colors.muted else Palette.Stone400
