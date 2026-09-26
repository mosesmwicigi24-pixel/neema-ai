package ke.co.bethanyhouse.neema.feature.leads

import androidx.compose.ui.semantics.Role
import ke.co.bethanyhouse.neema.feature.orders.pressedOn
import ke.co.bethanyhouse.neema.feature.orders.touchCell
import androidx.compose.runtime.remember
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.activity.compose.BackHandler
import ke.co.bethanyhouse.neema.feature.orders.MinuteTicker
import ke.co.bethanyhouse.neema.feature.orders.RestoreUi
import ke.co.bethanyhouse.neema.feature.orders.liveAgo
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import ke.co.bethanyhouse.neema.app.DashboardViewModel
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.ErrorState
import ke.co.bethanyhouse.neema.feature.orders.InlineError
import ke.co.bethanyhouse.neema.feature.orders.StaleBanner
import ke.co.bethanyhouse.neema.core.ui.components.Loading
import ke.co.bethanyhouse.neema.feature.orders.BtnVariant
import ke.co.bethanyhouse.neema.feature.orders.ChannelGlyphs
import ke.co.bethanyhouse.neema.feature.orders.CompactSearchField
import ke.co.bethanyhouse.neema.feature.orders.WebBtn
import ke.co.bethanyhouse.neema.feature.orders.WebDragHandle
import ke.co.bethanyhouse.neema.feature.orders.Tabular
import ke.co.bethanyhouse.neema.feature.orders.unbroken
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.feature.orders.CH_BG
import ke.co.bethanyhouse.neema.feature.orders.SalesInk
import ke.co.bethanyhouse.neema.core.util.Fmt
import java.util.Locale

/** `fmtCurrency` — "KES 1,234", never split between "KES" and the digits. */
private fun money(n: Double): String = Fmt.currency(n).unbroken()

// Dark mode: the pale Tailwind tints would glare, so they become washes of the dot colour.
@Composable private fun LeadStage.bgC(): Color = if (Neema.colors.isDark) dot.copy(alpha = 0.14f) else bg
@Composable private fun LeadStage.borderC(): Color = if (Neema.colors.isDark) dot.copy(alpha = 0.35f) else border
@Composable private fun LeadStage.textC(): Color = if (Neema.colors.isDark) dot else text

/** Instagram's mark sits on its gradient (the web's `url(#igGrad)`, bottom-left → top-right). */
private val IG_GRADIENT = Brush.linearGradient(
    *SalesInk.InstagramGradient,
    start = Offset(0f, Float.POSITIVE_INFINITY), end = Offset(Float.POSITIVE_INFINITY, 0f),
)

/** ChannelIcon — the channel's white mark in a round badge of its colour. */
@Composable
private fun ChannelIcon(ch: String, size: Dp = 16.dp) {
    val key = ch.lowercase(Locale.ROOT)
    val known = key in CH_BG || key == "instagram"
    Box(
        Modifier.size(size).clip(CircleShape).then(
            if (key == "instagram") Modifier.background(IG_GRADIENT)
            else Modifier.background(CH_BG[key] ?: CH_BG.getValue("sms")),
        ),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            ChannelGlyphs.forLead(if (known) key else "sms"), contentDescription = key,
            tint = Color.White, modifier = Modifier.size(size * 0.6f),
        )
    }
}

/**
 * Port of components/views/LeadsView.tsx — the leads pipeline as a kanban:
 * one column per stage (canonical + the operator's own from Settings), stage
 * filter pills with counts, search, cards with score bars and stage moves, and
 * the lead detail (stage, tags, notes) as a bottom sheet.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LeadsScreen(dash: DashboardViewModel) {
    // No permission gate here: page.tsx hides the Leads nav item without
    // view_leads, but LeadsView itself checks nothing (a ?view=leads link still
    // opens it) — no manage_leads test on the stage moves or the detail's
    // Save — and crm.py `list_leads` / `update_lead` only require a signed-in
    // agent. A refusal the server does send is said where the save failed.
    val vm: LeadsViewModel = viewModel { LeadsViewModel(dash) }
    RestoreUi(vm)
    ke.co.bethanyhouse.neema.feature.reports.TrackShown(vm.life)
    val leads by vm.leads.collectAsStateWithLifecycle()
    val loading by vm.loading.collectAsStateWithLifecycle()
    val refreshing by vm.refreshing.collectAsStateWithLifecycle()
    val stages by vm.stages.collectAsStateWithLifecycle()
    val filterStage by vm.filterStage.collectAsStateWithLifecycle()
    val search by vm.search.collectAsStateWithLifecycle()
    val selectedId by vm.selectedId.collectAsStateWithLifecycle()
    val loadError by vm.loadError.collectAsStateWithLifecycle()
    val saving by vm.saving.collectAsStateWithLifecycle()
    val sheetError by vm.sheetError.collectAsStateWithLifecycle()
    val sheet by vm.sheet.collectAsStateWithLifecycle()
    val c = Neema.colors
    // Back clears the search before it leaves the view (the sheet is its own window and takes back first).
    BackHandler(enabled = search.isNotEmpty()) { vm.search.value = "" }

    // Everything the board shows, derived once per change (not per frame, not per column):
    // 500 leads across seven columns is one pass, not seven filters and seven counts per recomposition.
    val filtered = remember(leads, filterStage, search) { filterLeads(leads, filterStage, search) }
    val board = remember(leads, filtered, stages) { buildBoard(leads, filtered, stages) }
    val pipelineValue = board.pipelineValue
    val wonValue = board.wonValue
    // Never loaded: no counts or totals — zeros would be a claim.
    val unknown = leads.isEmpty() && (loading || loadError != null)

    MinuteTicker {
    BoxWithConstraints(Modifier.fillMaxSize().background(c.bg)) {
        val wide = maxWidth >= 600.dp
        val boardWidth = maxWidth
        Column(Modifier.fillMaxSize()) {
            // ── Header ─────────────────────────────────────────────────────
            val headerText: @Composable () -> Unit = {
                Column {
                    Text("Leads Pipeline", fontSize = 20.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp, color = c.text)
                    Text(
                        if (unknown) (if (loadError != null) "Not loaded" else "Loading…")
                        else "${leads.size} leads · Pipeline ${money(pipelineValue)} · Won ${money(wonValue)}",
                        fontSize = 14.sp, color = c.textDim, style = Tabular, modifier = Modifier.padding(top = 2.dp),
                    )
                }
            }
            Column(Modifier.fillMaxWidth().background(c.bg2)) {
                if (wide) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.weight(1f)) { headerText() }
                        LeadsSearch(search, { vm.search.value = it }, Modifier.width(220.dp))
                    }
                } else {
                    // The search field's 48dp touch cell adds 8dp above and below its h-8 box.
                    Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp, bottom = 4.dp)) {
                        headerText()
                        Spacer(Modifier.height(2.dp))
                        LeadsSearch(search, { vm.search.value = it }, Modifier.fillMaxWidth())
                    }
                }
                HorizontalDivider(color = c.bg4)

                // ── Stage filter pills ─────────────────────────────────────
                LazyRow(
                    // px-6 py-3 as the web has it; the pills' 48dp touch cells carry most of the py-3.
                    contentPadding = PaddingValues(horizontal = 24.dp, vertical = 2.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    item(key = "all", contentType = "pill") {
                        StagePill(label = if (unknown) "All" else "All (${leads.size})", selected = filterStage == "all", stage = null) {
                            vm.filterStage.value = "all"
                        }
                    }
                    items(stages, key = { it.id }, contentType = { "pill" }) { s ->
                        val count = board.counts[s.id] ?: 0
                        StagePill(label = if (unknown) s.label else "${s.label} ($count)", selected = filterStage.equals(s.id, ignoreCase = true), stage = s) {
                            vm.filterStage.value = s.id
                        }
                    }
                }
                HorizontalDivider(color = c.bg4)
            }

            // A refresh failed with leads on screen: they stay, and this says why.
            val err = loadError
            if (err != null && leads.isNotEmpty() && !loading) {
                StaleBanner(err, onRetry = vm::refresh, modifier = Modifier.padding(start = 16.dp, end = 16.dp, top = 12.dp))
            }

            // ── Kanban board ───────────────────────────────────────────────
            PullToRefreshBox(isRefreshing = refreshing, onRefresh = vm::refresh, modifier = Modifier.weight(1f).fillMaxWidth()) {
                if (loading) {
                    // w-6 h-6 border-2, moss
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp, color = Palette.Moss600)
                    }
                } else if (err != null && leads.isEmpty()) {
                    // Never read: seven empty columns would claim there are no leads.
                    Box(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), contentAlignment = Alignment.TopCenter) {
                        ErrorState(err, onRetry = vm::load, modifier = Modifier.padding(top = 32.dp))
                    }
                } else {
                    // Columns fill the width: as many whole ~260dp columns as fit plus a
                    // third of the next (so it reads as "scroll for more"); all of them
                    // edge to edge when they fit.
                    val avail = boardWidth - 32.dp
                    val gap = 12.dp
                    val target = 260.dp
                    val whole = ((avail + gap) / (target + gap)).toInt().coerceAtLeast(1)
                    val colWidth = if (stages.size <= whole) (avail - gap * (stages.size - 1)) / stages.size.coerceAtLeast(1)
                        else (avail - gap * whole) / (whole + 0.35f)
                    LazyRow(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        items(stages, key = { it.id }, contentType = { "column" }) { stage ->
                            StageColumn(
                                stage = stage, stageLeads = board.columns[stage.id].orEmpty(),
                                stageValue = board.columnValue[stage.id] ?: 0.0, stages = stages, width = colWidth,
                                saving = saving,
                                onSelect = { vm.select(it.id) },
                                onMove = { lead, to -> vm.moveTo(lead, to) },
                            )
                        }
                    }
                }
            }
        }
    }

    }

    // ── Lead detail ────────────────────────────────────────────────────────
    val selected = remember(leads, selectedId) { selectedId?.let { id -> leads.find { it.id == id } } }
    if (selectedId != null && selected == null && !loading) {
        // Gone from the board (deleted, merged). Not before the first read: a
        // lead restored after process death waits for the board to load.
        LaunchedEffect(selectedId) { vm.select(null) }
    }
    if (selected != null) {
        // Started once per open lead (as the lead is then), kept as typed.
        LaunchedEffect(selected.id) { vm.sheetFor(selected) }
        val draft = sheet?.takeIf { it.leadId == selected.id }
        ModalBottomSheet(
            // A swipe or back closes the sheet but keeps what was typed for this lead.
            onDismissRequest = { vm.dismissSheet() },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = c.bg2,
            dragHandle = { WebDragHandle() },
        ) {
            LeadDetail(
                lead = selected, stages = stages,
                saving = selected.id in saving, error = sheetError,
                onClose = { vm.select(null) },
                onOpenChat = { dash.openConversationFor(selected.handle) },
                // The sheet closes when the server has the change; a failure keeps it open, fields as typed.
                onSave = { edit -> vm.save(selected, edit) },
                draft = draft, onDraft = vm::editSheet,
            )
        }
    }
}

@Composable
private fun StagePill(label: String, selected: Boolean, stage: LeadStage?, onClick: () -> Unit) {
    val c = Neema.colors
    val shape = RoundedCornerShape(8.dp)
    // "All" has no colour classes of its own: selected it is a bare `border`
    // (currentColor) over the white bar; unselected it keeps the page's text colour.
    val bg = when {
        selected && stage != null -> stage.bgC()
        else -> c.bg2
    }
    val border = when {
        selected && stage != null -> stage.borderC()
        selected -> c.text
        c.isDark -> c.hairline
        else -> Palette.Stone200
    }
    val fg = when {
        selected && stage != null -> stage.textC()
        stage == null -> c.text
        c.isDark -> c.textMid
        else -> Palette.Stone500
    }
    val press = remember { MutableInteractionSource() }
    Row(
        // 28dp to the eye (h-7), 48dp to the finger; grows with large text.
        Modifier.touchCell(press, role = Role.Tab, onClick = onClick)
            .heightIn(min = 28.dp).clip(shape).background(bg).border(1.dp, border, shape)
            .pressedOn(press).padding(horizontal = 12.dp, vertical = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (stage != null) {
            Box(Modifier.size(6.dp).clip(CircleShape).background(stage.dot))
            Spacer(Modifier.width(6.dp))
        }
        Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = fg, style = Tabular, maxLines = 1)
    }
}

@Composable
private fun StageColumn(
    stage: LeadStage,
    stageLeads: List<Lead>,
    stageValue: Double,
    stages: List<LeadStage>,
    width: Dp,
    saving: Set<String>,
    onSelect: (Lead) -> Unit,
    onMove: (Lead, String) -> Unit,
) {
    val c = Neema.colors
    Column(Modifier.width(width).fillMaxHeight()) {
        // Column header
        val shape = RoundedCornerShape(12.dp)
        Row(
            Modifier.fillMaxWidth().clip(shape).background(stage.bgC()).border(1.dp, stage.borderC(), shape)
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(8.dp).clip(CircleShape).background(stage.dot))
            Spacer(Modifier.width(6.dp))
            Text(stage.label, fontSize = 12.sp, fontWeight = FontWeight.Bold, color = stage.textC(),
                modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
            Column(horizontalAlignment = Alignment.End) {
                Text(stageLeads.size.toString(), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = stage.textC(), style = Tabular)
                if (stageValue > 0) Text(money(stageValue), fontSize = 10.sp, color = stage.textC().copy(alpha = 0.7f), style = Tabular, maxLines = 1)
            }
        }
        Spacer(Modifier.height(8.dp))
        if (stageLeads.isEmpty()) {
            Text("No leads", fontSize = 12.sp, color = c.border2, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp))
        } else {
            LazyColumn(Modifier.fillMaxWidth().weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(stageLeads, key = { it.id }, contentType = { "lead" }) { lead ->
                    LeadCard(lead, stages, busy = lead.id in saving, onSelect = { onSelect(lead) }, onMove = { onMove(lead, it) })
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun LeadCard(
    lead: Lead,
    stages: List<LeadStage>,
    busy: Boolean,
    onSelect: () -> Unit,
    onMove: (String) -> Unit,
) {
    val c = Neema.colors
    val shape = RoundedCornerShape(12.dp)
    val stageIdx = stages.indexOfFirst { it.matches(lead.leadStage) }
    Column(
        Modifier.fillMaxWidth().clip(shape).background(c.bg2).border(1.dp, c.bg3, shape)
            .clickable(onClick = onSelect).padding(12.dp),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Avatar(Fmt.displayName(lead.name, lead.handle), size = 32.dp)
            Spacer(Modifier.width(8.dp))
            Column(Modifier.weight(1f)) {
                if (!lead.name.isNullOrBlank()) {
                    Text(lead.name, fontSize = 14.sp, fontWeight = FontWeight.SemiBold, color = c.text,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                } else {
                    Text("Unknown", fontSize = 12.sp, fontStyle = FontStyle.Italic, color = if (c.isDark) c.muted else Palette.Stone400)
                }
                Text(Fmt.formatPhone(lead.handle), fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = c.textDim,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Text("${lead.leadScore}/100", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = c.textDim, style = Tabular, maxLines = 1)
        }
        Spacer(Modifier.height(8.dp))

        // Score bar
        Box(Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(50)).background(c.bg3)) {
            val barColor = when {
                lead.leadScore >= 70 -> Palette.Emerald500
                lead.leadScore >= 40 -> Palette.Amber500
                else -> Palette.Stone300
            }
            Box(Modifier.fillMaxWidth(lead.leadScore / 100f).fillMaxHeight().clip(RoundedCornerShape(50)).background(barColor))
        }
        Spacer(Modifier.height(8.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                lead.channels.take(3).forEach { ChannelIcon(it) }
            }
            if (lead.totalSpent > 0) {
                Text(money(lead.totalSpent), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = c.gold2, style = Tabular, maxLines = 1)
            }
        }

        if (lead.tags.isNotEmpty()) {
            FlowRow(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                lead.tags.take(3).forEach { tag ->
                    Text(tag, fontSize = 9.sp, color = c.gold2,
                        modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(c.bg3).padding(horizontal = 4.dp, vertical = 2.dp))
                }
            }
        }

        if (!lead.lastSeenAt.isNullOrBlank()) {
            Text(liveAgo(lead.lastSeenAt), fontSize = 10.sp, color = c.textDim, modifier = Modifier.padding(top = 6.dp))
        }

        // Stage moves. Hover-only on the web; always shown on a touch screen.
        val prev = if (stageIdx > 0) stages[stageIdx - 1] else null
        val next = if (stageIdx != -1 && stageIdx < stages.size - 1 && stages[stageIdx + 1].id != "lost") stages[stageIdx + 1] else null
        if (prev != null || next != null) {
            HorizontalDivider(color = c.bg3, modifier = Modifier.padding(top = 8.dp))
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (prev != null) {
                    MoveButton("← ${prev.label}", bg = if (c.isDark) c.bg else Palette.Moss50, fg = c.textDim, Modifier.weight(1f), enabled = !busy) { onMove(prev.id) }
                }
                if (next != null) {
                    MoveButton("${next.label} →", bg = c.bg3, fg = c.gold2, Modifier.weight(1f), enabled = !busy) { onMove(next.id) }
                }
            }
        }
    }
}

@Composable
private fun MoveButton(label: String, bg: Color, fg: Color, modifier: Modifier, enabled: Boolean = true, onClick: () -> Unit) {
    // The web's rounded py-1 chip, but a touch-sized one: the web shows it on
    // hover at 9px; here it is always there and is the card's main action, so
    // it reads at 11sp and takes a 48dp touch cell (32dp to the eye).
    val shape = RoundedCornerShape(6.dp)
    val press = remember { MutableInteractionSource() }
    Text(
        label,
        modifier = modifier.touchCell(press, enabled = enabled, role = Role.Button, onClick = onClick)
            .fillMaxWidth().heightIn(min = 32.dp).clip(shape).background(bg)
            .border(1.dp, Neema.colors.border, shape)
            .pressedOn(press).wrapContentHeight(Alignment.CenterVertically)
            .padding(horizontal = 4.dp, vertical = 6.dp),
        fontSize = 11.sp, lineHeight = 15.sp, color = fg.copy(alpha = if (enabled) 1f else 0.45f), textAlign = TextAlign.Center, maxLines = 1, overflow = TextOverflow.Ellipsis,
    )
}

// ── Detail sheet ────────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun LeadDetail(
    lead: Lead,
    stages: List<LeadStage>,
    onClose: () -> Unit,
    onOpenChat: () -> Unit,
    /** A save is in flight: the fields wait and Save shows progress. */
    saving: Boolean = false,
    /** Why the last save failed — shown above the buttons; the fields keep what was typed. */
    error: String? = null,
    /** Only the fields that changed are set — an untouched stage must not lock the AI out. */
    onSave: (LeadEdit) -> Unit,
    /**
     * The fields as typed and the lead as the sheet opened (the ViewModel's, so
     * they outlive a rotation or process death); null keeps them here (previews).
     */
    draft: LeadSheetDraft? = null,
    onDraft: (LeadSheetDraft) -> Unit = {},
) {
    val c = Neema.colors
    var local by remember(lead.id) { mutableStateOf(LeadSheetDraft.of(lead, stages)) }
    val d = draft ?: local
    val set: (LeadSheetDraft) -> Unit = { local = it; onDraft(it) }
    val stage = d.stage
    val notes = d.notes
    val tags = d.tags
    val fieldColors = OutlinedTextFieldDefaults.colors(
        unfocusedContainerColor = c.bg, focusedContainerColor = c.bg,
        unfocusedBorderColor = c.border, focusedBorderColor = c.gold,
    )

    // The fields scroll; Save / Cancel stay pinned under them, so with the
    // keyboard up (the sheet shrinks to the space above it) they are still
    // one tap away instead of scrolled out of sight.
    Column(Modifier.fillMaxWidth().imePadding()) {
    Column(
        Modifier.fillMaxWidth().weight(1f, fill = false).verticalScroll(rememberScrollState()).padding(horizontal = 20.dp),
    ) {
        Row(verticalAlignment = Alignment.Top) {
            Avatar(Fmt.displayName(lead.name, lead.handle), size = 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f).padding(top = 2.dp)) {
                Text(lead.name?.takeIf { it.isNotBlank() } ?: "Unknown customer", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text)
                Text(Fmt.formatPhone(lead.handle).unbroken(), fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = c.textDim)
                val extra = listOfNotNull(lead.email?.takeIf { it.isNotBlank() }, lead.location?.takeIf { it.isNotBlank() })
                if (extra.isNotEmpty()) Text(extra.joinToString(" · "), fontSize = 11.sp, color = c.muted)
                TextButton(
                    onClick = onOpenChat, contentPadding = PaddingValues(horizontal = 0.dp, vertical = 4.dp),
                    colors = ButtonDefaults.textButtonColors(contentColor = c.gold2),
                ) { Text("Open chat →", fontSize = 13.sp, fontWeight = FontWeight.SemiBold) }
            }
            // A plain ✕ as on the web, in a 48dp touch target that TalkBack names.
            IconButton(onClick = onClose, modifier = Modifier.offset(x = 12.dp, y = (-8).dp)) {
                Icon(Icons.Filled.Close, contentDescription = "Close", tint = if (c.isDark) c.muted else Palette.Stone400, modifier = Modifier.size(20.dp))
            }
        }
        Spacer(Modifier.height(12.dp))

        FieldLabel("Lead Stage")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            stages.forEach { s ->
                val on = s.id == stage
                val shape = RoundedCornerShape(8.dp)
                val press = remember { MutableInteractionSource() }
                Text(
                    s.label,
                    // 48dp to the finger; the chips keep the web's px-2.5 py-1.5 look.
                    modifier = Modifier.touchCell(press, enabled = !saving, role = Role.RadioButton) { set(d.copy(stage = s.id)) }
                        .clip(shape)
                        .background(if (on) s.bgC() else c.bg2)
                        .border(1.dp, if (on) s.borderC() else if (c.isDark) c.hairline else Palette.Stone200, shape)
                        .pressedOn(press)
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                    color = if (on) s.textC() else if (c.isDark) c.muted else Palette.Stone400,
                )
            }
        }
        Spacer(Modifier.height(16.dp))

        FieldLabel("Tags (comma separated)")
        OutlinedTextField(
            value = tags, onValueChange = { set(d.copy(tags = it)) }, readOnly = saving, singleLine = true,
            placeholder = { Text("church, wholesale, repeat-buyer") },
            colors = fieldColors, shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))

        FieldLabel("Notes")
        OutlinedTextField(
            value = notes, onValueChange = { set(d.copy(notes = it)) }, readOnly = saving,
            placeholder = { Text("Internal notes about this lead…") }, minLines = 3, maxLines = 8,
            colors = fieldColors, shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))

        // Stats
        val shape = RoundedCornerShape(12.dp)
        // grid-cols-2 gap-3 p-3
        Column(
            Modifier.fillMaxWidth().clip(shape).background(c.bg).border(1.dp, c.bg3, shape).padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            listOf(
                "Orders" to lead.totalOrders.toString(),
                "Total spent" to money(lead.totalSpent),
                "Lead score" to "${lead.leadScore}/100",
                "Channels" to lead.channels.size.toString(),
            ).chunked(2).forEach { pair ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    pair.forEach { (label, value) ->
                        Column(Modifier.weight(1f)) {
                            Text(label, fontSize = 10.sp, color = c.textDim)
                            Text(value, fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text, style = Tabular)
                        }
                    }
                }
            }
            val rhythm = lead.buyingRhythm
            val facts = listOfNotNull(
                lead.tierLabel?.takeIf { it.isNotBlank() },
                rhythm?.cadenceLabel?.takeIf { it.isNotBlank() }?.let { "buys $it" },
                if (rhythm?.overdue == true) "overdue" else null,
            )
            if (facts.isNotEmpty()) {
                Text(facts.joinToString(" · "), fontSize = 11.sp, color = c.textMid)
            }
        }
        Spacer(Modifier.height(12.dp))
    }
    // ── Pinned footer: the save error and the buttons ──────────────────────
    HorizontalDivider(color = if (c.isDark) c.hairline else Palette.Gray100)
    Column(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 8.dp, bottom = 20.dp)) {
        if (error != null) {
            InlineError(error, Modifier.padding(bottom = 4.dp))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            WebBtn(
                if (saving) "Saving…" else "Save Changes", BtnVariant.Primary, Modifier.weight(1f),
                enabled = !saving, busy = saving,
                onClick = { onSave(d.edit()) },
            )
            WebBtn("Cancel", BtnVariant.Outline, onClick = onClose)
        }
    }
    }
}

@Composable
private fun FieldLabel(text: String) {
    Text(
        text.uppercase(), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.6.sp,
        color = Neema.colors.textDim, modifier = Modifier.padding(bottom = 6.dp),
    )
}

/** The header's search: h-8, 14px text, rounded-lg, a stone-400 magnifier. */
@Composable
private fun LeadsSearch(value: String, onChange: (String) -> Unit, modifier: Modifier) =
    CompactSearchField(
        value, onChange, placeholder = "Search leads…", modifier = modifier,
        height = 32.dp, radius = 8.dp, fontSize = 14, iconSize = 14.dp, iconStart = 10.dp, textStart = 32.dp,
        iconTint = Palette.Stone400,
    )
