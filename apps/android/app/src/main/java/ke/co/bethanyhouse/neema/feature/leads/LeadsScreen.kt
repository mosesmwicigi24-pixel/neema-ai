package ke.co.bethanyhouse.neema.feature.leads

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
import ke.co.bethanyhouse.neema.core.perm.Perms
import ke.co.bethanyhouse.neema.core.ui.components.Avatar
import ke.co.bethanyhouse.neema.core.ui.components.EmptyState
import ke.co.bethanyhouse.neema.core.ui.components.ErrorState
import ke.co.bethanyhouse.neema.feature.orders.InlineError
import ke.co.bethanyhouse.neema.feature.orders.StaleBanner
import ke.co.bethanyhouse.neema.core.ui.components.Loading
import ke.co.bethanyhouse.neema.feature.orders.BtnVariant
import ke.co.bethanyhouse.neema.feature.orders.ChannelGlyphs
import ke.co.bethanyhouse.neema.feature.orders.CompactSearchField
import ke.co.bethanyhouse.neema.feature.orders.WebBtn
import ke.co.bethanyhouse.neema.feature.orders.WebDragHandle
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import java.util.Locale

/** `fmtCurrency` — "KES 1,234". */
private fun money(n: Double): String = Fmt.currency(n)

// Dark mode: the pale Tailwind tints would glare, so they become washes of the dot colour.
@Composable private fun LeadStage.bgC(): Color = if (Neema.colors.isDark) dot.copy(alpha = 0.14f) else bg
@Composable private fun LeadStage.borderC(): Color = if (Neema.colors.isDark) dot.copy(alpha = 0.35f) else border
@Composable private fun LeadStage.textC(): Color = if (Neema.colors.isDark) dot else text

/** The Leads page's flat channel colours (CH_SVG); unknown channels fall back to SMS. */
private val CH_BG = mapOf(
    "whatsapp" to Color(0xFF25D366),
    "messenger" to Color(0xFF0099FF),
    "instagram" to Color(0xFFE1306C),
    "facebook" to Color(0xFF1877F2),
    "email" to Color(0xFF4D66B3),
    "sms" to Color(0xFF589B31),
)

/** Instagram's mark sits on its gradient (the web's `url(#igGrad)`, bottom-left → top-right). */
private val IG_GRADIENT = Brush.linearGradient(
    0f to Color(0xFFF09433), 0.25f to Color(0xFFE6683C), 0.5f to Color(0xFFDC2743),
    0.75f to Color(0xFFCC2366), 1f to Color(0xFFBC1888),
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
    // Permissions come from /me; observing it recomposes the gate once it lands.
    dash.me.collectAsStateWithLifecycle().value
    if (!dash.can(Perms.VIEW_LEADS)) {
        EmptyState(
            title = "No access to leads",
            subtitle = "Your role doesn't include the leads pipeline. Ask an admin if you need it.",
            icon = Icons.Outlined.Lock,
        )
        return
    }
    val vm: LeadsViewModel = viewModel { LeadsViewModel(dash) }
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
    val canManage = dash.can(Perms.MANAGE_LEADS)
    val c = Neema.colors

    val filtered = remember(leads, filterStage, search) { filterLeads(leads, filterStage, search) }
    val pipelineValue = leads.filter { it.leadStage.lowercase() !in setOf("lost", "won") }.sumOf { it.totalSpent }
    val wonValue = leads.filter { it.leadStage.equals("won", ignoreCase = true) }.sumOf { it.totalSpent }
    // Never loaded: no counts or totals — zeros would be a claim.
    val unknown = leads.isEmpty() && (loading || loadError != null)

    BoxWithConstraints(Modifier.fillMaxSize().background(c.bg)) {
        val wide = maxWidth >= 600.dp
        Column(Modifier.fillMaxSize()) {
            // ── Header ─────────────────────────────────────────────────────
            val headerText: @Composable () -> Unit = {
                Column {
                    Text("Leads Pipeline", fontSize = 20.sp, fontWeight = FontWeight.Bold, letterSpacing = (-0.5).sp, color = c.text)
                    Text(
                        if (unknown) (if (loadError != null) "Not loaded" else "Loading…")
                        else "${leads.size} leads · Pipeline ${money(pipelineValue)} · Won ${money(wonValue)}",
                        fontSize = 14.sp, color = c.textDim, modifier = Modifier.padding(top = 2.dp),
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
                    Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp)) {
                        headerText()
                        Spacer(Modifier.height(10.dp))
                        LeadsSearch(search, { vm.search.value = it }, Modifier.fillMaxWidth())
                    }
                }
                HorizontalDivider(color = c.bg4)

                // ── Stage filter pills ─────────────────────────────────────
                LazyRow(
                    // px-6 py-3 on every width, as the web has it.
                    contentPadding = PaddingValues(horizontal = 24.dp, vertical = 12.dp),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    item(key = "all") {
                        StagePill(label = if (unknown) "All" else "All (${leads.size})", selected = filterStage == "all", stage = null) {
                            vm.filterStage.value = "all"
                        }
                    }
                    items(stages, key = { it.id }) { s ->
                        val count = leads.count { s.matches(it.leadStage) }
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
                        CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp, color = Color(0xFF589B31))
                    }
                } else if (err != null && leads.isEmpty()) {
                    // Never read: seven empty columns would claim there are no leads.
                    Box(Modifier.fillMaxSize().verticalScroll(rememberScrollState()), contentAlignment = Alignment.TopCenter) {
                        ErrorState(err, onRetry = vm::load, modifier = Modifier.padding(top = 32.dp))
                    }
                } else {
                    val colWidth = 210.dp
                    LazyRow(
                        Modifier.fillMaxSize(),
                        contentPadding = PaddingValues(16.dp),
                        horizontalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        items(stages, key = { it.id }) { stage ->
                            val stageLeads = filtered.filter { stage.matches(it.leadStage) }
                            StageColumn(
                                stage = stage, stageLeads = stageLeads, stages = stages, width = colWidth,
                                canManage = canManage, saving = saving,
                                onSelect = { vm.select(it.id) },
                                onMove = { lead, to -> vm.moveTo(lead, to) },
                            )
                        }
                    }
                }
            }
        }
    }

    // ── Lead detail ────────────────────────────────────────────────────────
    val selected = selectedId?.let { id -> leads.find { it.id == id } }
    if (selected != null) {
        ModalBottomSheet(
            onDismissRequest = { vm.select(null) },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
            containerColor = c.bg2,
            dragHandle = { WebDragHandle() },
        ) {
            LeadDetail(
                lead = selected, stages = stages, canManage = canManage,
                saving = selected.id in saving, error = sheetError,
                onClose = { vm.select(null) },
                onOpenChat = { dash.openConversationFor(selected.handle) },
                // The sheet closes when the server has the change; a failure keeps it open, fields as typed.
                onSave = { edit -> vm.save(selected, edit) },
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
        else -> Color(0xFFE7E5E4)
    }
    val fg = when {
        selected && stage != null -> stage.textC()
        stage == null -> c.text
        c.isDark -> c.textMid
        else -> Color(0xFF78716C)
    }
    Row(
        Modifier.height(28.dp).clip(shape).background(bg).border(1.dp, border, shape)
            .clickable(onClick = onClick).padding(horizontal = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (stage != null) {
            Box(Modifier.size(6.dp).clip(CircleShape).background(stage.dot))
            Spacer(Modifier.width(6.dp))
        }
        Text(label, fontSize = 12.sp, fontWeight = FontWeight.Medium, color = fg)
    }
}

@Composable
private fun StageColumn(
    stage: LeadStage,
    stageLeads: List<Lead>,
    stages: List<LeadStage>,
    width: Dp,
    canManage: Boolean,
    saving: Set<String>,
    onSelect: (Lead) -> Unit,
    onMove: (Lead, String) -> Unit,
) {
    val c = Neema.colors
    val stageValue = stageLeads.sumOf { it.totalSpent }
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
                Text(stageLeads.size.toString(), fontSize = 12.sp, fontWeight = FontWeight.Bold, color = stage.textC())
                if (stageValue > 0) Text(money(stageValue), fontSize = 10.sp, color = stage.textC().copy(alpha = 0.7f))
            }
        }
        Spacer(Modifier.height(8.dp))
        if (stageLeads.isEmpty()) {
            Text("No leads", fontSize = 12.sp, color = c.border2, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth().padding(vertical = 32.dp))
        } else {
            LazyColumn(Modifier.fillMaxWidth().weight(1f), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(stageLeads, key = { it.id }) { lead ->
                    LeadCard(lead, stages, canManage, busy = lead.id in saving, onSelect = { onSelect(lead) }, onMove = { onMove(lead, it) })
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
    canManage: Boolean,
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
                    Text("Unknown", fontSize = 12.sp, fontStyle = FontStyle.Italic, color = if (c.isDark) c.muted else Color(0xFFA8A29E))
                }
                Text(Fmt.formatPhone(lead.handle), fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = c.textDim,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Text("${lead.leadScore}/100", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = c.textDim)
        }
        Spacer(Modifier.height(8.dp))

        // Score bar
        Box(Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(50)).background(c.bg3)) {
            val barColor = when {
                lead.leadScore >= 70 -> Color(0xFF10B981)
                lead.leadScore >= 40 -> Color(0xFFF59E0B)
                else -> Color(0xFFD6D3D1)
            }
            Box(Modifier.fillMaxWidth(lead.leadScore / 100f).fillMaxHeight().clip(RoundedCornerShape(50)).background(barColor))
        }
        Spacer(Modifier.height(8.dp))

        Row(verticalAlignment = Alignment.CenterVertically) {
            Row(Modifier.weight(1f), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                lead.channels.take(3).forEach { ChannelIcon(it) }
            }
            if (lead.totalSpent > 0) {
                Text(money(lead.totalSpent), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = c.gold2)
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
            Text(Fmt.timeAgo(lead.lastSeenAt), fontSize = 10.sp, color = c.textDim, modifier = Modifier.padding(top = 6.dp))
        }

        // Stage moves. Hover-only on the web; always shown on a touch screen.
        if (canManage) {
            val prev = if (stageIdx > 0) stages[stageIdx - 1] else null
            val next = if (stageIdx != -1 && stageIdx < stages.size - 1 && stages[stageIdx + 1].id != "lost") stages[stageIdx + 1] else null
            if (prev != null || next != null) {
                HorizontalDivider(color = c.bg3, modifier = Modifier.padding(top = 8.dp))
                Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (prev != null) {
                        MoveButton("← ${prev.label}", bg = if (c.isDark) c.bg else Color(0xFFF0F9EC), fg = c.textDim, Modifier.weight(1f), enabled = !busy) { onMove(prev.id) }
                    }
                    if (next != null) {
                        MoveButton("${next.label} →", bg = c.bg3, fg = c.gold2, Modifier.weight(1f), enabled = !busy) { onMove(next.id) }
                    }
                }
            }
        }
    }
}

@Composable
private fun MoveButton(label: String, bg: Color, fg: Color, modifier: Modifier, enabled: Boolean = true, onClick: () -> Unit) {
    // text-[9px] rounded py-1
    val shape = RoundedCornerShape(4.dp)
    Text(
        label,
        modifier = modifier.clip(shape).background(bg).border(1.dp, Neema.colors.border, shape)
            .clickable(enabled = enabled, onClick = onClick).padding(vertical = 4.dp),
        fontSize = 9.sp, lineHeight = 13.5.sp, color = fg.copy(alpha = if (enabled) 1f else 0.45f), textAlign = TextAlign.Center, maxLines = 1, overflow = TextOverflow.Ellipsis,
    )
}

// ── Detail sheet ────────────────────────────────────────────────────────────

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun LeadDetail(
    lead: Lead,
    stages: List<LeadStage>,
    canManage: Boolean,
    onClose: () -> Unit,
    onOpenChat: () -> Unit,
    /** A save is in flight: the fields wait and Save shows progress. */
    saving: Boolean = false,
    /** Why the last save failed — shown above the buttons; the fields keep what was typed. */
    error: String? = null,
    /** Only the fields that changed are set — an untouched stage must not lock the AI out. */
    onSave: (LeadEdit) -> Unit,
) {
    val c = Neema.colors
    // The lead as the sheet opened: what "changed" means, and the notes base for the server's merge.
    val base = remember(lead.id) { lead }
    var stage by rememberSaveable(lead.id) { mutableStateOf(stages.firstOrNull { it.matches(lead.leadStage) }?.id ?: lead.leadStage) }
    var notes by rememberSaveable(lead.id) { mutableStateOf(lead.notes.orEmpty()) }
    var tags by rememberSaveable(lead.id) { mutableStateOf(lead.tags.joinToString(", ")) }
    val fieldColors = OutlinedTextFieldDefaults.colors(
        unfocusedContainerColor = c.bg, focusedContainerColor = c.bg,
        unfocusedBorderColor = c.border, focusedBorderColor = c.gold,
    )

    Column(
        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp).padding(bottom = 28.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Avatar(Fmt.displayName(lead.name, lead.handle), size = 44.dp)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f)) {
                Text(lead.name?.takeIf { it.isNotBlank() } ?: "Unknown customer", fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text)
                Text(Fmt.formatPhone(lead.handle), fontSize = 12.sp, fontFamily = FontFamily.Monospace, color = c.textDim)
                val extra = listOfNotNull(lead.email?.takeIf { it.isNotBlank() }, lead.location?.takeIf { it.isNotBlank() })
                if (extra.isNotEmpty()) Text(extra.joinToString(" · "), fontSize = 11.sp, color = c.muted)
            }
            TextButton(onClick = onOpenChat) { Text("Open chat") }
            Text(
                "✕", fontSize = 18.sp, color = Color(0xFFA8A29E),
                modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClick = onClose).padding(horizontal = 8.dp, vertical = 4.dp),
            )
        }
        Spacer(Modifier.height(16.dp))

        FieldLabel("Lead Stage")
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            stages.forEach { s ->
                val on = s.id == stage
                val shape = RoundedCornerShape(8.dp)
                Text(
                    s.label,
                    modifier = Modifier.clip(shape)
                        .background(if (on) s.bgC() else c.bg2)
                        .border(1.dp, if (on) s.borderC() else if (c.isDark) c.hairline else Color(0xFFE7E5E4), shape)
                        .clickable(enabled = canManage && !saving) { stage = s.id }
                        .padding(horizontal = 10.dp, vertical = 6.dp),
                    fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                    color = if (on) s.textC() else if (c.isDark) c.muted else Color(0xFFA8A29E),
                )
            }
        }
        Spacer(Modifier.height(16.dp))

        FieldLabel("Tags (comma separated)")
        OutlinedTextField(
            value = tags, onValueChange = { tags = it }, enabled = canManage, readOnly = saving, singleLine = true,
            placeholder = { Text("church, wholesale, repeat-buyer") },
            colors = fieldColors, shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))

        FieldLabel("Notes")
        OutlinedTextField(
            value = notes, onValueChange = { notes = it }, enabled = canManage, readOnly = saving,
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
                            Text(value, fontSize = 14.sp, fontWeight = FontWeight.Bold, color = c.text)
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
        Spacer(Modifier.height(16.dp))

        if (error != null) {
            InlineError(error, Modifier.padding(bottom = 12.dp))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (canManage) {
                WebBtn(
                    if (saving) "Saving…" else "Save Changes", BtnVariant.Primary, Modifier.weight(1f),
                    enabled = !saving, busy = saving,
                    onClick = { onSave(diffLead(base, stage, tags, notes)) },
                )
                WebBtn("Cancel", BtnVariant.Outline, onClick = onClose)
            } else {
                Text("Your role can view leads but not change them.", fontSize = 12.sp, color = c.muted,
                    modifier = Modifier.weight(1f).align(Alignment.CenterVertically))
                WebBtn("Close", BtnVariant.Outline, onClick = onClose)
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
        iconTint = Color(0xFFA8A29E),
    )
