@file:OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)

package ke.co.bethanyhouse.neema.feature.conversations.customer

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ke.co.bethanyhouse.neema.core.ui.theme.Neema
import ke.co.bethanyhouse.neema.core.util.Fmt
import ke.co.bethanyhouse.neema.feature.conversations.isWebVisitor
import kotlin.math.roundToInt
import ke.co.bethanyhouse.neema.core.ui.theme.Palette
import ke.co.bethanyhouse.neema.feature.conversations.Hue

/** What every tab needs, computed once by the panel. */
class PanelCtx(
    val profile: CustomerProfile,
    val orders: List<PanelOrder>,
    val totalSpent: Double,
    val lastOrder: PanelOrder?,
    val customStages: List<String>,
    val canEdit: Boolean,
    val canReply: Boolean,
    val isAdmin: Boolean,
) {
    val orderCount: Int get() = profile.totalOrders.takeIf { it > 0 } ?: orders.size

    /** The profile's stage matched to the pipeline's own spelling (see [canonicalStage]). */
    val stage: String = canonicalStage(profile.leadStage, customStages)
}


// ── Profile tab ─────────────────────────────────────────────────────────────

@Composable
fun ProfileTab(
    vm: CustomerViewModel,
    ctx: PanelCtx,
    onNameChange: (String, String) -> Unit,
    onOpenIdentity: (String, String) -> Unit,
) {
    val p = ctx.profile
    val c = Neema.colors
    val askBusy by vm.askBusy.collectAsState()
    val askAnswer by vm.askAnswer.collectAsState()
    val answerBusy by vm.answerBusy.collectAsState()
    val answerStatus by vm.answerStatus.collectAsState()
    val askDraft by vm.askDraft.collectAsState()
    val answerDraft by vm.answerDraft.collectAsState()
    val drafts by vm.drafts.collectAsState()

    NeemaBox("Ask Neema… “what were his sizes?”", "Ask", askBusy, askAnswer, askDraft, { vm.askDraft.value = it }) { vm.ask() }
    if (ctx.canReply) {
        NeemaBox("Team answer… “yes, we make it — KES 3,500, ~5 days”", "Neema delivers", answerBusy, answerStatus,
            answerDraft, { vm.answerDraft.value = it }) { vm.answerViaNeema() }
    }
    // A field whose save failed reopens with what the agent typed.
    @Composable
    fun Field(label: String, field: String, value: String, onSave: (String) -> Unit, placeholder: String,
              keyboardType: KeyboardType = KeyboardType.Text) =
        EditableField(label, value, onSave, placeholder, ctx.canEdit, keyboardType,
            restore = drafts[field], onRestored = { vm.takeDraft(field) })

    CrmSection("Contact Details") {
        p.leadSource?.takeIf { it.isNotEmpty() }?.let { src ->
            val meta = sourceMeta(src)
            val icon = (meta ?: SOURCE_META.getValue("other")).second
            // The web draws this row apart from the others: 13px, spread edge to edge, no rule under it.
            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Source", fontSize = 13.sp, color = c.muted, modifier = Modifier.weight(1f))
                Hint("Where this lead first found us") {
                    Text("$icon  ${meta?.first ?: src}", fontSize = 13.sp, fontWeight = FontWeight.Medium, color = c.text)
                }
            }
        }
        p.adRef?.let { ad ->
            val what = ad.headline?.ifEmpty { null } ?: ad.adId?.ifEmpty { null }?.let { "Ad $it" }
                ?: ad.sourceType?.ifEmpty { null } ?: "ad"
            InfoRow("Came via", "📣 $what", hint = "First-touch ad attribution captured from the webhook")
        }
        Field("Name", "name", p.name ?: "", { vm.saveName(it, onNameChange) }, "Full name")
        Field("Role", "role", p.role ?: "", { v -> vm.saveField("role", v) { it.copy(role = v) } }, "Bishop / Pastor / Founder…")
        Field("Ministry", "organization", p.organization ?: "", { v -> vm.saveField("organization", v) { it.copy(organization = v) } },
            "Church / ministry / organization")
        Field("Email", "email", p.email ?: "", { v -> vm.saveField("email", v) { it.copy(email = v) } }, "email@example.com",
            KeyboardType.Email)
        Field("Phone", "phone", p.phone ?: "", { v -> vm.saveField("phone", v) { it.copy(phone = v) } }, "+254...",
            KeyboardType.Phone)
        Field("Country", "country", p.country ?: "", { v -> vm.saveField("country", v) { it.copy(country = v) } }, "Resolved from phone")
        Field("Location", "location", p.location ?: "", { v -> vm.saveField("location", v) { it.copy(location = v) } }, "City / Estate")
        p.parish?.name?.takeIf { it.isNotEmpty() }?.let { name ->
            InfoRow("Parish", "⛪ $name" + (p.parish.location?.takeIf { it.isNotEmpty() }?.let { " · $it" } ?: ""))
        }
        Field("Age", "age", p.age?.takeIf { it != 0 }?.toString() ?: "", { vm.saveAge(it) }, "e.g. 35", KeyboardType.Number)
    }

    PipelineSection(vm, ctx)
    TagsSection(vm, ctx)
    NotesSection(vm, ctx)
    IdentitySection(vm, ctx, onOpenIdentity)
}

@Composable
private fun PipelineSection(vm: CustomerViewModel, ctx: PanelCtx) {
    val p = ctx.profile
    val c = Neema.colors
    val editorOpen by vm.stageEditorOpen.collectAsState()
    val newStage by vm.newStage.collectAsState()
    val stagesSaving by vm.stagesSaving.collectAsState()
    val stageBusy by vm.stageBusy.collectAsState()
    val customs = ctx.customStages
    // Customs render between Proposal and Won, and count toward forward progress.
    val stages = listOf("new", "contacted", "qualified", "proposal") + customs + listOf("won", "lost")
    val forward = listOf("new", "contacted", "qualified", "proposal", "negotiation") + customs + "won"

    CrmSection("Lead Pipeline") {
        if (p.leadStageSource == "auto") {
            Row(Modifier.padding(bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "✦ AI", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = Palette.Violet600.themed(),
                    modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(Palette.Violet600.dim(0.08f))
                        .border(1.dp, Palette.Violet200, RoundedCornerShape(4.dp)).padding(horizontal = 4.dp, vertical = 1.dp),
                )
                Text(
                    " set from the conversation — tap any stage to override.",
                    fontSize = 10.sp, color = Palette.Violet600.themed(),
                )
            }
        }
        // A move in flight: the next tap waits for it (the VM ignores it too).
        PipelineStepper(stages, forward, ctx.stage, ctx.canEdit && !stageBusy) { vm.setStage(it) }
        Spacer(Modifier.height(4.dp))
        // Operator-added stage labels — global, admin-saved (the server refuses others).
        if (!ctx.isAdmin) return@CrmSection
        if (editorOpen) {
            if (customs.isNotEmpty()) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
                    modifier = Modifier.padding(bottom = 6.dp)) {
                    customs.forEach { s ->
                        RemovableChip(
                            s, if (c.isDark) PIPE_GOLD else Hue.PipeGoldInk, if (c.isDark) PIPE_GOLD.dim(0.15f) else Hue.PipeGoldWash,
                            if (c.isDark) PIPE_GOLD.dim(0.5f) else Hue.PipeGoldRim, enabled = !stagesSaving,
                        ) {
                            vm.saveCustomStages(customs.filter { it != s })
                        }
                    }
                }
            }
            // The label stays in the box until the server kept it (a refused save loses nothing).
            val add = { if (!stagesSaving) vm.addCustomStage() }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                SmallInput(newStage, { vm.newStage.value = it.take(18) }, "Stage label (e.g. Sampling)…", Modifier.weight(1f),
                    fontSize = 10.sp, onDone = add)
                TintButton(if (stagesSaving) "…" else "Add", PIPE_GOLD_SOLID, add, filled = true, enabled = !stagesSaving)
                TextButton(onClick = { vm.stageEditorOpen.value = false }) { Text("Done", fontSize = 10.sp, color = c.muted) }
            }
        } else {
            Text(
                "+ Add stage", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = PIPE_GOLD,
                modifier = Modifier.clip(RoundedCornerShape(4.dp)).clickable { vm.stageEditorOpen.value = true }.padding(vertical = 4.dp, horizontal = 2.dp),
            )
        }
    }
}

@Composable
private fun RemovableChip(text: String, fg: Color, bg: Color, border: Color, enabled: Boolean = true, onRemove: () -> Unit) {
    Row(
        Modifier.clip(RoundedCornerShape(4.dp)).background(bg).border(1.dp, border, RoundedCornerShape(4.dp))
            .padding(start = 6.dp, end = if (enabled) 0.dp else 6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(text, fontSize = 10.sp, color = fg, modifier = Modifier.padding(vertical = 3.dp))
        if (enabled) {
            Box(Modifier.size(24.dp).clickable(onClick = onRemove), contentAlignment = Alignment.Center) {
                Icon(Icons.Default.Close, "Remove $text", tint = Neema.colors.muted, modifier = Modifier.size(12.dp))
            }
        }
    }
}

@Composable
private fun TagsSection(vm: CustomerViewModel, ctx: PanelCtx) {
    val c = Neema.colors
    // In the ViewModel: a tag whose save failed comes back here.
    val tagInput by vm.tagInput.collectAsState()
    CrmSection("Tags") {
        if (ctx.profile.tags.isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp),
                modifier = Modifier.padding(bottom = 8.dp)) {
                ctx.profile.tags.forEach { t ->
                    RemovableChip(t, c.text, c.bg3, c.hairline, enabled = ctx.canEdit) { vm.removeTag(t) }
                }
            }
        } else if (!ctx.canEdit) {
            Text("No tags", fontSize = 11.sp, color = c.muted, fontStyle = FontStyle.Italic)
        }
        if (ctx.canEdit) {
            val add = { vm.addTag() }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                SmallInput(tagInput, { vm.tagInput.value = it }, "Add tag…", Modifier.weight(1f), onDone = add)
                NeutralButton("+", add, Modifier.width(36.dp), height = 36.dp)
            }
        }
    }
}

@Composable
private fun NotesSection(vm: CustomerViewModel, ctx: PanelCtx) {
    val c = Neema.colors
    val notes = ctx.profile.notes ?: ""
    val editing by vm.editNotes.collectAsState()
    // The draft lives in the ViewModel: a live reload never resets what the agent is typing.
    val draft by vm.noteDraft.collectAsState()
    val base by vm.notesBase.collectAsState()
    CrmSection("Notes") {
        if (editing) {
            SmallInput(draft, { vm.noteDraft.value = it }, "Internal notes about this customer…", Modifier.fillMaxWidth(), singleLine = false, minLines = 4)
            // Something (a call summary) landed on the notes mid-edit; the server merges it in on save.
            if (base != null && base != notes) {
                Text("New notes arrived while you were typing — they'll be kept when you save.",
                    fontSize = 10.sp, color = c.muted, fontStyle = FontStyle.Italic, modifier = Modifier.padding(top = 4.dp))
            }
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                TextButton(onClick = { vm.saveNotes() }) {
                    Text("Save", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = Palette.Emerald600)
                }
                TextButton(onClick = { vm.cancelEditNotes() }) { Text("Cancel", fontSize = 10.sp, color = c.muted) }
            }
        } else {
            Box(
                Modifier.fillMaxWidth().heightIn(min = 40.dp).clip(RoundedCornerShape(8.dp)).background(c.bg2)
                    .border(1.dp, c.hairline, RoundedCornerShape(8.dp))
                    .then(if (ctx.canEdit) Modifier.clickable { vm.startEditNotes() } else Modifier)
                    .padding(horizontal = 10.dp, vertical = 8.dp),
            ) {
                if (notes.isNotEmpty()) Text(notes, fontSize = 12.sp, color = c.text)
                else Text(if (ctx.canEdit) "Tap to add notes…" else "No notes", fontSize = 12.sp,
                    color = c.muted.copy(alpha = 0.7f), fontStyle = FontStyle.Italic)
            }
        }
    }
}

@Composable
private fun IdentitySection(vm: CustomerViewModel, ctx: PanelCtx, onOpenIdentity: (String, String) -> Unit) {
    val p = ctx.profile
    val c = Neema.colors
    val uri = LocalUriHandler.current
    val showMerge by vm.showMerge.collectAsState()
    val sugs by vm.mergeSugs.collectAsState()
    val sugsError by vm.mergeSugsError.collectAsState()
    val merging by vm.merging.collectAsState()
    val unmerging by vm.unmerging.collectAsState()
    // In the ViewModel: kept through a failed merge, cleared once it went through.
    val mergeQuery by vm.mergeQuery.collectAsState()
    val slate = if (c.isDark) c.textMid else Hue.Slate800
    // The web's filled slate (#1e293b) buttons; on dark, the palette's deep blue keeps white text legible.
    val slateFill = if (c.isDark) c.border2 else Hue.Slate800

    CrmSection(
        "Cross-channel Identity",
        action = if (!ctx.canEdit) null else ({
            Row(
                Modifier.clip(RoundedCornerShape(8.dp))
                    .background(if (showMerge) c.hairline else c.bg2)
                    .border(1.dp, if (showMerge) c.border2 else c.border, RoundedCornerShape(8.dp))
                    .clickable { vm.toggleMerge() }.padding(horizontal = 8.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(if (showMerge) Icons.Default.Close else Icons.Default.Add, null, tint = slate, modifier = Modifier.size(12.dp))
                Spacer(Modifier.width(4.dp))
                Text(if (showMerge) "Cancel" else "Merge", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = slate)
            }
        }),
    ) {
        p.channels.forEachIndexed { i, ch ->
            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                ChannelBadge(badgeKey(ch.channel, ch.identifier))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text(channelLabel(ch.channel, ch.identifier), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                    // formatPhone reads a web visitor's key as "Website visitor", never as a number.
                    Text(Fmt.formatPhone(ch.identifier), fontSize = 10.sp, color = c.muted,
                        fontFamily = if (isWebVisitor(ch.identifier)) null else FontFamily.Monospace,
                        maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text("${ch.conversationCount} conv", fontSize = 10.sp, color = c.muted)
                    Text(Fmt.timeAgo(ch.lastSeen), fontSize = 10.sp, color = c.muted)
                }
            }
            if (i < p.channels.size - 1) Hairline()
        }

        // Linked identities — the real cross-channel spine.
        if (p.linkedIdentities.isNotEmpty()) {
            Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                p.linkedIdentities.forEach { id ->
                    val web = isWebVisitor(id.externalId)
                    // A legacy web-visitor identity is not WhatsApp: no WhatsApp green.
                    val color = if (web) Palette.Slate500.themed() else chMeta(id.channel).second
                    val label = channelLabel(id.channel, id.externalId)
                    val digits = realPhoneDigits(id.externalId)
                    // A real WhatsApp number opens a wa.me chat; any other channel (and a legacy
                    // `web_<hash>` identity, which is no number) jumps to that thread in Neema.
                    val isRealPhone = id.channel == "whatsapp" && digits != null
                    Hint(if (isRealPhone) "Open WhatsApp chat" else "Open $label conversation") {
                        Row(
                            Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(c.surface)
                                .border(1.dp, c.hairline, RoundedCornerShape(8.dp))
                                .clickable {
                                    if (isRealPhone) runCatching { uri.openUri("https://wa.me/$digits") }
                                    else onOpenIdentity(id.channel, id.externalId)
                                }
                                .padding(8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Box(Modifier.size(8.dp).clip(RoundedCornerShape(50)).background(color))
                            Spacer(Modifier.width(8.dp))
                            Column(Modifier.weight(1f)) {
                                Text(label, fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = color)
                                Text(
                                    if (id.channel == "whatsapp") Fmt.formatPhone(id.externalId) else id.externalId,
                                    fontSize = 10.sp, color = c.muted, fontFamily = if (web) null else FontFamily.Monospace,
                                    maxLines = 1, overflow = TextOverflow.Ellipsis,
                                )
                            }
                            Text("↗", fontSize = 11.sp, color = color)
                            id.confidence?.takeIf { it.isNotEmpty() }?.let {
                                Spacer(Modifier.width(6.dp))
                                Text(it, fontSize = 9.sp, color = c.muted,
                                    modifier = Modifier.clip(RoundedCornerShape(50)).background(c.bg3).padding(horizontal = 6.dp, vertical = 2.dp))
                            }
                        }
                    }
                }
            }
        }

        if (p.mergedIds.isNotEmpty()) {
            Column(
                Modifier.padding(top = 8.dp).fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(c.bg3)
                    .border(1.dp, c.hairline, RoundedCornerShape(8.dp)).padding(8.dp),
            ) {
                Text("Merged (${p.mergedIds.size})", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = slate,
                    modifier = Modifier.padding(bottom = 4.dp))
                p.mergedIds.forEach { mid ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(Fmt.formatPhone(mid), fontSize = 10.sp, fontFamily = FontFamily.Monospace, color = c.text, modifier = Modifier.weight(1f))
                        if (ctx.canEdit) {
                            val busy = mid in unmerging
                            Text(
                                if (busy) "Unmerging…" else "Unmerge", fontSize = 9.sp, fontWeight = FontWeight.SemiBold,
                                color = if (busy) c.muted else slate,
                                modifier = Modifier.clip(RoundedCornerShape(4.dp)).border(1.dp, c.border2, RoundedCornerShape(4.dp))
                                    .clickable(enabled = !busy) { vm.unmerge(mid) }.padding(horizontal = 8.dp, vertical = 4.dp),
                            )
                        }
                    }
                }
            }
        }

        if (showMerge && ctx.canEdit) {
            val dash = c.border2
            Column(
                Modifier.padding(top = 12.dp).fillMaxWidth()
                    .drawBehind {
                        drawRoundRect(dash, cornerRadius = CornerRadius(12.dp.toPx()),
                            style = Stroke(2.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(10f, 8f))))
                    }
                    .clip(RoundedCornerShape(12.dp)).background(c.surface).padding(12.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(bottom = 8.dp)) {
                    Box(Modifier.size(28.dp).clip(RoundedCornerShape(8.dp)).background(c.hairline), contentAlignment = Alignment.Center) {
                        Text("⊕", fontSize = 14.sp, color = slate)
                    }
                    Spacer(Modifier.width(8.dp))
                    Column {
                        Text("Merge Profiles", fontSize = 12.sp, fontWeight = FontWeight.Bold, color = slate)
                        Text("Combine duplicate customer records", fontSize = 10.sp, color = c.textMid)
                    }
                }
                // Evidence-backed candidates — one tap, no typing.
                when {
                    // The scan failed (offline, a 5xx): say so, with a retry — never "no duplicates".
                    sugsError != null -> Row(Modifier.fillMaxWidth().padding(bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("$sugsError You can still merge manually below.", fontSize = 10.sp, fontStyle = FontStyle.Italic,
                            color = c.muted, modifier = Modifier.weight(1f))
                        Text("Retry", fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = slate,
                            modifier = Modifier.clip(RoundedCornerShape(4.dp)).clickable { vm.retryMergeScan() }
                                .padding(horizontal = 8.dp, vertical = 6.dp))
                    }
                    sugs == null -> Text("Scanning for likely duplicates…", fontSize = 10.sp, fontStyle = FontStyle.Italic,
                        color = c.muted, modifier = Modifier.padding(bottom = 8.dp))
                    sugs!!.isEmpty() -> Text("No likely duplicates found — you can still merge manually below.", fontSize = 10.sp,
                        fontStyle = FontStyle.Italic, color = c.muted, modifier = Modifier.padding(bottom = 8.dp))
                    else -> Column(Modifier.padding(bottom = 10.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                        sugs!!.forEach { s -> MergeCandidate(s, slateFill, enabled = !merging) { vm.merge(s.mergeWith) } }
                    }
                }
                Text(
                    buildAnnotatedString {
                        append("Enter the phone / wa_id of the profile to merge ")
                        withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { append("into this one") }
                        append(". Their orders and channels will be combined here.")
                    },
                    fontSize = 10.sp, lineHeight = 15.sp, color = c.text, modifier = Modifier.padding(bottom = 10.dp),
                )
                SmallInput(mergeQuery, { vm.mergeQuery.value = it }, "e.g. 254700123456", Modifier.fillMaxWidth().padding(bottom = 10.dp),
                    keyboardType = KeyboardType.Phone, onDone = { vm.merge() })
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    TintButton(if (merging) "Merging…" else "⊕ Merge now", slateFill, { vm.merge() }, Modifier.weight(1f), filled = true,
                        enabled = !merging)
                    NeutralButton("Cancel", { vm.toggleMerge(false); vm.mergeQuery.value = "" })
                }
            }
        }
    }
}

@Composable
private fun MergeCandidate(s: MergeSuggestion, fill: Color, enabled: Boolean = true, onMerge: () -> Unit) {
    val c = Neema.colors
    val strong = s.strength == "strong"
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(c.bg2)
            .border(if (strong) 1.5.dp else 1.dp, if (strong) Hue.MossBright else c.hairline, RoundedCornerShape(8.dp))
            .padding(horizontal = 10.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(
                buildAnnotatedString {
                    append(s.name?.ifEmpty { null } ?: s.phone?.ifEmpty { null } ?: s.mergeWith)
                    s.country?.ifEmpty { null }?.let {
                        withStyle(SpanStyle(fontWeight = FontWeight.Normal, color = c.muted)) { append(" · $it") }
                    }
                },
                fontSize = 11.sp, fontWeight = FontWeight.SemiBold, color = c.text, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(2.dp),
                modifier = Modifier.padding(top = 2.dp)) {
                s.evidence.forEach { ev ->
                    Text(ev, fontSize = 9.sp, color = if (strong) (if (c.isDark) c.gold2 else Palette.Moss700) else c.textMid,
                        modifier = Modifier.clip(RoundedCornerShape(50))
                            .background(if (strong) (if (c.isDark) c.greenDim else Hue.MossWash) else c.bg3).padding(horizontal = 6.dp, vertical = 2.dp))
                }
            }
        }
        Spacer(Modifier.width(8.dp))
        TintButton("Merge", fill, onMerge, filled = true, enabled = enabled)
    }
}

// ── Insights tab ────────────────────────────────────────────────────────────

@Composable
fun InsightsTab(ctx: PanelCtx) {
    val p = ctx.profile
    val c = Neema.colors
    CrmSection("Purchase Summary") {
        val n = ctx.orderCount
        KvRow("Total orders", "$n")
        KvRow("Total spent", Fmt.currency(ctx.totalSpent))
        KvRow(
            "Avg order value",
            when {
                (p.avgOrderValue ?: 0.0) != 0.0 -> Fmt.currency(p.avgOrderValue!!.roundToInt())
                n > 0 -> Fmt.currency((ctx.totalSpent / n).roundToInt())
                else -> "—"
            },
        )
        KvRow(
            "Last order",
            ctx.lastOrder?.createdIso?.takeIf { Fmt.millis(it) != null }?.let { Fmt.timeAgo(it) }
                ?: p.lastOrderAt?.let { Fmt.timeAgo(it) } ?: "—",
        )
        KvRow("Customer since", p.firstSeenAt?.let { Fmt.date(it) } ?: "—")
    }

    p.buyingRhythm?.let { r ->
        CrmSection("Buying Rhythm") {
            KvRow("Buys", r.cadenceLabel?.ifEmpty { null } ?: "—")
            KvRow("Avg gap between orders", r.avgIntervalDays?.takeIf { it != 0.0 }?.let { "${Fmt.number(it)} days" } ?: "—")
            // crm.py `_buying_rhythm` floors (now − last order).days; a hub order stamped in local
            // time but read as UTC lands a few hours in the future and comes back as -1.
            KvRow("Since last order", r.daysSinceLast?.let { "${maxOf(0, it)} days" } ?: "—")
            if (r.overdue) {
                Text(
                    "⏰ Overdue — it's been longer than their usual gap. A good moment to check in.",
                    fontSize = 11.sp, color = Palette.Amber700.themed(),
                    modifier = Modifier.padding(top = 4.dp).fillMaxWidth().clip(RoundedCornerShape(4.dp))
                        .background(Palette.Amber500.dim(0.1f)).border(1.dp, Palette.Amber200, RoundedCornerShape(4.dp))
                        .padding(horizontal = 8.dp, vertical = 6.dp),
                )
            }
        }
    }

    if (ctx.orders.isNotEmpty()) {
        CrmSection("Top Products") {
            data class Agg(val name: String, var qty: Double = 0.0, var total: Double = 0.0)
            val map = linkedMapOf<String, Agg>()
            ctx.orders.forEach { o ->
                o.items.forEach { i ->
                    val a = map.getOrPut(i.name) { Agg(i.name) }
                    a.qty += (i.qty?.takeIf { it != 0.0 } ?: i.quantity?.takeIf { it != 0.0 } ?: 1.0)
                    a.total += i.total ?: 0.0
                }
            }
            val top = map.values.sortedByDescending { it.total }.take(4)
            top.forEachIndexed { idx, item ->
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(item.name, fontSize = 12.sp, color = c.textMid, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.weight(1f).padding(end = 8.dp))
                    Column(horizontalAlignment = Alignment.End) {
                        Text(Fmt.currency(item.total), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                        Text("×${Fmt.number(item.qty)}", fontSize = 10.sp, color = c.muted)
                    }
                }
                if (idx < top.size - 1) Hairline()
            }
        }
    }

    // Straight from the API — the server owns the scoring, so this can never drift from the ranking.
    CrmSection("Lead Score Breakdown") {
        p.leadScoreBreakdown.forEach { row ->
            Column(Modifier.padding(bottom = 8.dp)) {
                Row(Modifier.fillMaxWidth().padding(bottom = 2.dp)) {
                    Text(row.label, fontSize = 10.sp, color = c.textMid, modifier = Modifier.weight(1f))
                    Text("${Fmt.number(row.pts)}/${Fmt.number(row.max)}", fontSize = 10.sp, color = c.textMid)
                }
                ProgressBar(if (row.max != 0.0) (row.pts / row.max).toFloat() else 0f, Palette.Green500, Modifier.fillMaxWidth().height(4.dp))
            }
        }
    }
}

// ── Activity tab ────────────────────────────────────────────────────────────

@Composable
fun orderStatusColor(status: String?): Color = when (status) {
    "delivered" -> Palette.Emerald700
    "confirmed" -> Palette.Blue700
    "cancelled" -> Palette.Red600
    else -> Palette.Amber700
}

@Composable
fun ActivityTab(ctx: PanelCtx) {
    val p = ctx.profile
    val c = Neema.colors
    CrmSection("Recent Orders") {
        if (p.hubLinked) {
            Hint("Matched to a shop customer by phone number — same person across the counter and WhatsApp") {
                Row(
                    Modifier.padding(bottom = 8.dp).fillMaxWidth().clip(RoundedCornerShape(6.dp)).background(c.greenDim)
                        .border(1.dp, c.hairline, RoundedCornerShape(6.dp)).padding(horizontal = 8.dp, vertical = 6.dp),
                ) {
                    Text("📇 ", fontSize = 11.sp)
                    Text(
                        "Same customer in the shop" + (p.hubCustomerName?.ifEmpty { null }?.let { " · $it" } ?: "") +
                            " — showing full in-shop + WhatsApp history",
                        fontSize = 11.sp, color = if (c.isDark) c.gold2 else Hue.Lime800,
                    )
                }
            }
        }
        if (ctx.orders.isEmpty()) {
            Text("No orders yet", fontSize = 12.sp, color = c.muted, modifier = Modifier.fillMaxWidth().padding(vertical = 12.dp),
                textAlign = androidx.compose.ui.text.style.TextAlign.Center)
        } else {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                ctx.orders.take(5).forEach { o ->
                    Column(
                        Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(c.bg2)
                            .border(1.dp, c.hairline, RoundedCornerShape(8.dp)).padding(10.dp),
                    ) {
                        Row(Modifier.fillMaxWidth().padding(bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                            val sc = orderStatusColor(o.status).themed()
                            Text(o.status ?: "—", fontSize = 10.sp, fontWeight = FontWeight.Bold, color = sc,
                                modifier = Modifier.clip(RoundedCornerShape(4.dp)).background(sc.dim(0.1f)).padding(horizontal = 6.dp, vertical = 2.dp))
                            Spacer(Modifier.weight(1f))
                            Text(Fmt.timeAgo(o.createdIso), fontSize = 10.sp, color = c.muted)
                        }
                        Text(Fmt.currency(o.total ?: o.subtotal ?: 0.0, o.displayCurrency), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                        Text(
                            o.items.joinToString(", ") { it.name }.ifEmpty { "—" },
                            fontSize = 10.sp, color = c.textMid, maxLines = 1, overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.padding(top = 2.dp),
                        )
                    }
                }
            }
        }
    }

    CrmSection("Channel History") {
        p.channels.forEachIndexed { i, ch ->
            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.Top) {
                ChannelBadge(badgeKey(ch.channel, ch.identifier))
                Spacer(Modifier.width(8.dp))
                Column(Modifier.weight(1f)) {
                    Text(channelLabel(ch.channel, ch.identifier), fontSize = 12.sp, fontWeight = FontWeight.SemiBold, color = c.text)
                    Text("${ch.conversationCount} conversation${if (ch.conversationCount != 1) "s" else ""}", fontSize = 10.sp, color = c.muted)
                    Text(
                        "First: ${ch.firstSeen?.let { Fmt.date(it) } ?: "—"} · Last: ${ch.lastSeen?.let { Fmt.timeAgo(it) } ?: "—"}",
                        fontSize = 10.sp, color = c.muted,
                    )
                }
            }
            if (i < p.channels.size - 1) Hairline()
        }
    }
}
