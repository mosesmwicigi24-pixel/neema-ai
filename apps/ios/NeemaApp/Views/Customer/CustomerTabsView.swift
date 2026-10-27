import SwiftUI
import NeemaCore

// ── Profile tab ─────────────────────────────────────────────────────────────

struct ProfileTab: View {
    @ObservedObject var model: CustomerPanelModel
    let ctx: PanelCtx
    let onNameChange: (String, String) -> Void
    let onOpenIdentity: (String, String) -> Void
    @Environment(\.neema) private var c

    private var vm: CustomerViewModel { model.vm }

    var body: some View {
        let p = ctx.profile
        let ui = model.ui
        VStack(alignment: .leading, spacing: 0) {
            NeemaBox(placeholder: "Ask Neema… “what were his sizes?”", actionLabel: "Ask", busy: ui.askBusy, result: ui.askAnswer,
                     text: Binding(get: { ui.askDraft }, set: { vm.setAskDraft($0) })) { vm.ask() }
            if ctx.canReply {
                NeemaBox(placeholder: "Team answer… “yes, we make it — KES 3,500, ~5 days”", actionLabel: "Neema delivers", busy: ui.answerBusy, result: ui.answerStatus,
                         text: Binding(get: { ui.answerDraft }, set: { vm.setAnswerDraft($0) })) { vm.answerViaNeema() }
            }
            CrmSection("Contact Details") {
                if let src = p.leadSource, !src.isEmpty {
                    let meta = CustomerWords.sourceMeta(src)
                    let icon = meta?.icon ?? "•"
                    // The web draws this row apart from the others: 13px, spread edge to edge, no rule under it.
                    HStack {
                        Text("Source").font(NeemaFont.manrope(13)).foregroundColor(c.muted)
                        Spacer()
                        Text("\(icon)  \(meta?.label ?? src)").font(NeemaFont.manrope(13, .medium)).foregroundColor(c.text)
                            .accessibilityHint("Where this lead first found us")
                    }
                    .padding(.vertical, 6)
                }
                if let ad = p.adRef {
                    let what = (ad.headline?.isEmpty == false ? ad.headline : nil) ?? (ad.adId?.isEmpty == false ? "Ad \(ad.adId!)" : nil) ?? (ad.sourceType?.isEmpty == false ? ad.sourceType : nil) ?? "ad"
                    InfoRow(label: "Came via", value: "📣 \(what)", hint: "First-touch ad attribution captured from the webhook")
                }
                field("Name", "name", p.name ?? "", "Full name") { vm.saveName($0, onNameChange: onNameChange) }
                field("Role", "role", p.role ?? "", "Bishop / Pastor / Founder…") { vm.saveContactField("role", $0) }
                field("Ministry", "organization", p.organization ?? "", "Church / ministry / organization") { vm.saveContactField("organization", $0) }
                field("Email", "email", p.email ?? "", "email@example.com", keyboard: .emailAddress) { vm.saveContactField("email", $0) }
                field("Phone", "phone", p.phone ?? "", "+254...", keyboard: .phonePad) { vm.saveContactField("phone", $0) }
                field("Country", "country", p.country ?? "", "Resolved from phone") { vm.saveContactField("country", $0) }
                field("Location", "location", p.location ?? "", "City / Estate") { vm.saveContactField("location", $0) }
                if let name = p.parish?.name, !name.isEmpty {
                    InfoRow(label: "Parish", value: "⛪ \(name)" + ((p.parish?.location?.isEmpty == false) ? " · \(p.parish!.location!)" : ""))
                }
                field("Age", "age", (p.age ?? 0) != 0 ? String(p.age!) : "", "e.g. 35", keyboard: .numberPad) { vm.saveAge($0) }
            }
            PipelineSection(model: model, ctx: ctx)
            TagsSection(model: model, ctx: ctx)
            NotesSection(model: model, ctx: ctx)
            IdentitySection(model: model, ctx: ctx, onOpenIdentity: onOpenIdentity)
        }
    }

    /// A field whose save failed reopens with what the agent typed.
    private func field(_ label: String, _ key: String, _ value: String, _ placeholder: String, keyboard: UIKeyboardType = .default, onSave: @escaping (String) -> Void) -> some View {
        EditableField(label: label, value: value, onSave: onSave, placeholder: placeholder, enabled: ctx.canEdit, keyboard: keyboard,
                      restore: model.ui.drafts[key], onRestored: { vm.takeDraft(key) })
    }
}

private struct PipelineSection: View {
    @ObservedObject var model: CustomerPanelModel
    let ctx: PanelCtx
    @Environment(\.neema) private var c
    private var vm: CustomerViewModel { model.vm }

    var body: some View {
        let p = ctx.profile
        let ui = model.ui
        let customs = ctx.customStages
        // Customs render between Proposal and Won, and count toward forward progress.
        let stages = ["new", "contacted", "qualified", "proposal"] + customs + ["won", "lost"]
        let forward = ["new", "contacted", "qualified", "proposal", "negotiation"] + customs + ["won"]
        CrmSection("Lead Pipeline") {
            if p.leadStageSource == "auto" {
                HStack(spacing: 0) {
                    Text("✦ Neema").font(NeemaFont.manrope(10, .semibold)).foregroundColor(Palette.violet600.themed(c.isDark))
                        .padding(.horizontal, 4).padding(.vertical, 1)
                        .background(RoundedRectangle(cornerRadius: 4).fill(Palette.violet600.dim(0.08)))
                        .roundedBorder(Palette.violet200, radius: 4)
                    Text(" set from the conversation — tap any stage to override.").font(NeemaFont.manrope(10)).foregroundColor(Palette.violet600.themed(c.isDark))
                }
                .padding(.bottom, 6)
            }
            // A move in flight: the next tap waits for it (the view model ignores it too).
            PipelineStepper(stages: stages, forward: forward, active: ctx.stage, enabled: ctx.canEdit && !ui.stageBusy) { vm.setStage($0) }
            Spacer().frame(height: 4)
            // Operator-added stage labels — global, admin-saved (the server refuses others).
            if ctx.isAdmin {
                if ui.stageEditorOpen {
                    if !customs.isEmpty {
                        FlowLayout(spacing: 4, lineSpacing: 4) {
                            ForEach(customs, id: \.self) { s in
                                RemovableChip(text: s, fg: c.isDark ? PIPE_GOLD : Palette.pipeGoldInk, bg: c.isDark ? PIPE_GOLD.dim(0.15) : Palette.pipeGoldWash,
                                              border: c.isDark ? PIPE_GOLD.dim(0.5) : Palette.pipeGoldRim, enabled: !ui.stagesSaving) {
                                    vm.saveCustomStages(customs.filter { $0 != s })
                                }
                            }
                        }
                        .padding(.bottom, 6)
                    }
                    // The label stays in the box until the server kept it (a refused save loses nothing).
                    HStack(spacing: 4) {
                        SmallInput(value: Binding(get: { ui.newStage }, set: { vm.setNewStage($0) }), placeholder: "Stage label (e.g. Sampling)…", fontSize: 10,
                                   onDone: { if !ui.stagesSaving { vm.addCustomStage() } })
                        TintButton(text: ui.stagesSaving ? "…" : "Add", color: PIPE_GOLD_SOLID, filled: true, enabled: !ui.stagesSaving) { vm.addCustomStage() }
                            .fixedSize(horizontal: true, vertical: false)
                        Button { vm.setStageEditorOpen(false) } label: { Text("Done").font(NeemaFont.manrope(10)).foregroundColor(c.muted).padding(8) }
                    }
                } else {
                    Button { vm.setStageEditorOpen(true) } label: {
                        Text("+ Add stage").font(NeemaFont.manrope(10, .semibold)).foregroundColor(PIPE_GOLD).padding(.vertical, 4).padding(.horizontal, 2)
                    }
                }
            }
        }
    }
}

private struct RemovableChip: View {
    let text: String
    let fg: Color
    let bg: Color
    let border: Color
    var enabled: Bool = true
    let onRemove: () -> Void
    @Environment(\.neema) private var c
    var body: some View {
        HStack(spacing: 0) {
            Text(text).font(NeemaFont.manrope(10)).foregroundColor(fg).padding(.vertical, 3).padding(.leading, 6).padding(.trailing, enabled ? 0 : 6)
            if enabled {
                Button(action: onRemove) { Image(systemName: "xmark").font(.system(size: 10, weight: .semibold)).foregroundColor(c.muted).frame(width: 24, height: 24) }
                    .accessibilityLabel("Remove \(text)")
            }
        }
        .background(RoundedRectangle(cornerRadius: 4).fill(bg))
        .roundedBorder(border, radius: 4)
    }
}

private struct TagsSection: View {
    @ObservedObject var model: CustomerPanelModel
    let ctx: PanelCtx
    @Environment(\.neema) private var c
    var body: some View {
        let vm = model.vm
        // In the view model: a tag whose save failed comes back here.
        let tagInput = model.ui.tagInput
        CrmSection("Tags") {
            if !ctx.profile.tags.isEmpty {
                FlowLayout(spacing: 4, lineSpacing: 4) {
                    ForEach(ctx.profile.tags, id: \.self) { t in
                        RemovableChip(text: t, fg: c.text, bg: c.bg3, border: c.hairline, enabled: ctx.canEdit) { vm.removeTag(t) }
                    }
                }
                .padding(.bottom, 8)
            } else if !ctx.canEdit {
                Text("No tags").font(NeemaFont.manrope(11)).italic().foregroundColor(c.muted)
            }
            if ctx.canEdit {
                HStack(spacing: 4) {
                    SmallInput(value: Binding(get: { tagInput }, set: { vm.setTagInput($0) }), placeholder: "Add tag…", onDone: { vm.addTag() })
                    NeutralButton(text: "+", height: 36, fill: false) { vm.addTag() }.frame(width: 36)
                }
            }
        }
    }
}

private struct NotesSection: View {
    @ObservedObject var model: CustomerPanelModel
    let ctx: PanelCtx
    @Environment(\.neema) private var c
    var body: some View {
        let vm = model.vm
        let ui = model.ui
        let notes = ctx.profile.notes ?? ""
        CrmSection("Notes") {
            if ui.editNotes {
                // The draft lives in the view model: a live reload never resets what the agent is typing.
                SmallInput(value: Binding(get: { ui.noteDraft }, set: { vm.setNoteDraft($0) }), placeholder: "Internal notes about this customer…", lines: 4...12)
                // Something (a call summary) landed on the notes mid-edit; the server merges it in on save.
                if let base = ui.notesBase, base != notes {
                    Text("New notes arrived while you were typing — they'll be kept when you save.").font(NeemaFont.manrope(10)).italic().foregroundColor(c.muted).padding(.top, 4)
                }
                HStack(spacing: 4) {
                    Button { vm.saveNotes() } label: { Text("Save").font(NeemaFont.manrope(10, .semibold)).foregroundColor(Palette.emerald600).padding(8) }
                    Button { vm.cancelEditNotes() } label: { Text("Cancel").font(NeemaFont.manrope(10)).foregroundColor(c.muted).padding(8) }
                }
                .padding(.top, 4)
            } else {
                Button { if ctx.canEdit { vm.startEditNotes() } } label: {
                    Group {
                        if !notes.isEmpty { Text(notes).font(NeemaFont.manrope(12)).foregroundColor(c.text) }
                        else { Text(ctx.canEdit ? "Tap to add notes…" : "No notes").font(NeemaFont.manrope(12)).italic().foregroundColor(c.muted.opacity(0.7)) }
                    }
                    .frame(maxWidth: .infinity, minHeight: 40, alignment: .topLeading)
                    .padding(.horizontal, 10).padding(.vertical, 8)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg2))
                    .roundedBorder(c.hairline, radius: 8)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(!ctx.canEdit)
            }
        }
    }
}

private struct IdentitySection: View {
    @ObservedObject var model: CustomerPanelModel
    let ctx: PanelCtx
    let onOpenIdentity: (String, String) -> Void
    @Environment(\.neema) private var c
    @Environment(\.openURL) private var openURL

    var body: some View {
        let vm = model.vm
        let ui = model.ui
        let p = ctx.profile
        let slate = c.isDark ? c.textMid : Palette.slate800
        // The web's filled slate (#1e293b) buttons; on dark, the palette's deep blue keeps white text legible.
        let slateFill = c.isDark ? c.border2 : Palette.slate800
        CrmSection("Cross-channel Identity", action: {
            if ctx.canEdit {
                Button { vm.toggleMerge() } label: {
                    HStack(spacing: 4) {
                        Image(systemName: ui.showMerge ? "xmark" : "plus").font(.system(size: 10, weight: .semibold)).foregroundColor(slate)
                        Text(ui.showMerge ? "Cancel" : "Merge").font(NeemaFont.manrope(10, .semibold)).foregroundColor(slate)
                    }
                    .padding(.horizontal, 8).padding(.vertical, 4)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(ui.showMerge ? c.hairline : c.bg2))
                    .roundedBorder(ui.showMerge ? c.border2 : c.border, radius: 8)
                }
                .buttonStyle(.plain)
            }
        }) {
            ForEach(Array(p.channels.enumerated()), id: \.offset) { i, ch in
                HStack(spacing: 8) {
                    ChannelBadge(channel: Crm.badgeKey(ch.channel, identifier: ch.identifier))
                    VStack(alignment: .leading, spacing: 1) {
                        Text(Crm.channelLabel(ch.channel, identifier: ch.identifier)).font(NeemaFont.manrope(10, .semibold)).foregroundColor(c.text)
                        // formatPhone reads a web visitor's key as "Website visitor", never as a number.
                        Text(Fmt.formatPhone(ch.identifier)).font(Inbox.isWebVisitor(ch.identifier) ? NeemaFont.manrope(10) : NeemaFont.mono(10)).foregroundColor(c.muted).lineLimit(1)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 1) {
                        Text("\(ch.conversationCount) conv").font(NeemaFont.manrope(10)).foregroundColor(c.muted)
                        Text(Fmt.timeAgo(ch.lastSeen)).font(NeemaFont.manrope(10)).foregroundColor(c.muted)
                    }
                }
                .padding(.vertical, 6)
                if i < p.channels.count - 1 { CrmHairline() }
            }

            // Linked identities — the real cross-channel spine.
            if !p.linkedIdentities.isEmpty {
                VStack(spacing: 4) {
                    ForEach(Array(p.linkedIdentities.enumerated()), id: \.offset) { _, id in
                        let web = Inbox.isWebVisitor(id.externalId)
                        // A legacy web-visitor identity is not WhatsApp: no WhatsApp green.
                        let color = web ? Palette.slate500.themed(c.isDark) : chColor(id.channel)
                        let label = Crm.channelLabel(id.channel, identifier: id.externalId)
                        let digits = Crm.realPhoneDigits(id.externalId)
                        // A real WhatsApp number opens a wa.me chat; any other channel (and a legacy
                        // `web_<hash>` identity, which is no number) jumps to that thread in Neema.
                        let isRealPhone = id.channel == "whatsapp" && digits != nil
                        Button {
                            if isRealPhone, let u = URL(string: "https://wa.me/\(digits!)") { openURL(u) } else { onOpenIdentity(id.channel, id.externalId) }
                        } label: {
                            HStack(spacing: 8) {
                                Circle().fill(color).frame(width: 8, height: 8)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(label).font(NeemaFont.manrope(10, .semibold)).foregroundColor(color)
                                    Text(id.channel == "whatsapp" ? Fmt.formatPhone(id.externalId) : id.externalId)
                                        .font(web ? NeemaFont.manrope(10) : NeemaFont.mono(10)).foregroundColor(c.muted).lineLimit(1)
                                }
                                Spacer()
                                Text("↗").font(NeemaFont.manrope(11)).foregroundColor(color)
                                if let conf = id.confidence, !conf.isEmpty {
                                    Text(conf).font(NeemaFont.manrope(9)).foregroundColor(c.muted)
                                        .padding(.horizontal, 6).padding(.vertical, 2).background(Capsule().fill(c.bg3))
                                }
                            }
                            .padding(8)
                            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.surface))
                            .roundedBorder(c.hairline, radius: 8)
                        }
                        .buttonStyle(.plain)
                        .accessibilityHint(isRealPhone ? "Open WhatsApp chat" : "Open \(label) conversation")
                    }
                }
                .padding(.top, 8)
            }

            if !p.mergedIds.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Merged (\(p.mergedIds.count))").font(NeemaFont.manrope(10, .semibold)).foregroundColor(slate)
                    ForEach(p.mergedIds, id: \.self) { mid in
                        HStack {
                            Text(Fmt.formatPhone(mid)).font(NeemaFont.mono(10)).foregroundColor(c.text)
                            Spacer()
                            if ctx.canEdit {
                                let busy = ui.unmerging.contains(mid)
                                Button { vm.unmerge(mid) } label: {
                                    Text(busy ? "Unmerging…" : "Unmerge").font(NeemaFont.manrope(9, .semibold)).foregroundColor(busy ? c.muted : slate)
                                        .padding(.horizontal, 8).padding(.vertical, 4).roundedBorder(c.border2, radius: 4)
                                }
                                .buttonStyle(.plain)
                                .disabled(busy)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                }
                .padding(8)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg3))
                .roundedBorder(c.hairline, radius: 8)
                .padding(.top, 8)
            }

            if ui.showMerge && ctx.canEdit {
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 8) {
                        Text("⊕").font(NeemaFont.manrope(14)).foregroundColor(slate).frame(width: 28, height: 28)
                            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.hairline))
                        VStack(alignment: .leading, spacing: 1) {
                            Text("Merge Profiles").font(NeemaFont.manrope(12, .bold)).foregroundColor(slate)
                            Text("Combine duplicate customer records").font(NeemaFont.manrope(10)).foregroundColor(c.textMid)
                        }
                    }
                    .padding(.bottom, 8)
                    // Evidence-backed candidates — one tap, no typing.
                    if let err = ui.mergeSugsError {
                        // The scan failed (offline, a 5xx): say so, with a retry — never "no duplicates".
                        HStack {
                            Text("\(err) You can still merge manually below.").font(NeemaFont.manrope(10)).italic().foregroundColor(c.muted)
                            Spacer(minLength: 4)
                            Button { vm.retryMergeScan() } label: { Text("Retry").font(NeemaFont.manrope(10, .semibold)).foregroundColor(slate).padding(.horizontal, 8).padding(.vertical, 6) }
                        }
                        .padding(.bottom, 8)
                    } else if ui.mergeSugs == nil {
                        Text("Scanning for likely duplicates…").font(NeemaFont.manrope(10)).italic().foregroundColor(c.muted).padding(.bottom, 8)
                    } else if ui.mergeSugs!.isEmpty {
                        Text("No likely duplicates found — you can still merge manually below.").font(NeemaFont.manrope(10)).italic().foregroundColor(c.muted).padding(.bottom, 8)
                    } else {
                        VStack(spacing: 6) {
                            ForEach(Array(ui.mergeSugs!.enumerated()), id: \.offset) { _, s in
                                MergeCandidate(s: s, fill: slateFill, enabled: !ui.merging) { vm.merge(s.mergeWith) }
                            }
                        }
                        .padding(.bottom, 10)
                    }
                    (Text("Enter the phone / wa_id of the profile to merge ") + Text("into this one").italic() + Text(". Their orders and channels will be combined here."))
                        .font(NeemaFont.manrope(10)).lineSpacing(2).foregroundColor(c.text).padding(.bottom, 10)
                    SmallInput(value: Binding(get: { ui.mergeQuery }, set: { vm.setMergeQuery($0) }), placeholder: "e.g. 254700123456", keyboard: .phonePad, onDone: { vm.merge() })
                        .padding(.bottom, 10)
                    HStack(spacing: 6) {
                        TintButton(text: ui.merging ? "Merging…" : "⊕ Merge now", color: slateFill, filled: true, enabled: !ui.merging) { vm.merge() }
                        NeutralButton(text: "Cancel", fill: false) { vm.toggleMerge(false); vm.setMergeQuery("") }
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.surface))
                .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.border2, style: StrokeStyle(lineWidth: 2, dash: [10, 8])))
                .padding(.top, 12)
            }
        }
    }
}

private struct MergeCandidate: View {
    let s: MergeSuggestion
    let fill: Color
    var enabled: Bool = true
    let onMerge: () -> Void
    @Environment(\.neema) private var c
    var body: some View {
        let strong = s.strength == "strong"
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                (Text((s.name?.isEmpty == false ? s.name : nil) ?? (s.phone?.isEmpty == false ? s.phone : nil) ?? s.mergeWith).bold()
                 + Text((s.country?.isEmpty == false) ? " · \(s.country!)" : "").foregroundColor(c.muted))
                    .font(NeemaFont.manrope(11)).foregroundColor(c.text).lineLimit(1)
                FlowLayout(spacing: 4, lineSpacing: 2) {
                    ForEach(s.evidence, id: \.self) { ev in
                        Text(ev).font(NeemaFont.manrope(9)).foregroundColor(strong ? (c.isDark ? c.gold2 : Palette.moss700) : c.textMid)
                            .padding(.horizontal, 6).padding(.vertical, 2)
                            .background(Capsule().fill(strong ? (c.isDark ? c.goldDim : Palette.mossWash) : c.bg3))
                    }
                }
            }
            Spacer(minLength: 0)
            TintButton(text: "Merge", color: fill, filled: true, enabled: enabled, action: onMerge).fixedSize(horizontal: true, vertical: false)
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg2))
        .roundedBorder(strong ? Palette.mossBright : c.hairline, radius: 8, width: strong ? 1.5 : 1)
    }
}

// ── Insights tab ────────────────────────────────────────────────────────────

struct InsightsTab: View {
    let ctx: PanelCtx
    @Environment(\.neema) private var c

    private struct Agg { let name: String; var qty: Double = 0; var total: Double = 0 }

    var body: some View {
        let p = ctx.profile
        VStack(alignment: .leading, spacing: 0) {
            CrmSection("Purchase Summary") {
                let n = ctx.orderCount
                KvRow(label: "Total orders", value: String(n))
                KvRow(label: "Total spent", value: Fmt.currency(ctx.totalSpent))
                KvRow(label: "Avg order value", value: {
                    if let a = p.avgOrderValue, a != 0 { return Fmt.currency(a.rounded()) }
                    if n > 0 { return Fmt.currency((ctx.totalSpent / Double(n)).rounded()) }
                    return "—"
                }())
                KvRow(label: "Last order", value: {
                    if let iso = ctx.lastOrder?.createdIso, Fmt.millis(iso) != nil { return Fmt.timeAgo(iso) }
                    if let l = p.lastOrderAt { return Fmt.timeAgo(l) }
                    return "—"
                }())
                KvRow(label: "Customer since", value: p.firstSeenAt.map { Fmt.date($0) } ?? "—")
            }
            if let r = p.buyingRhythm {
                CrmSection("Buying Rhythm") {
                    KvRow(label: "Buys", value: (r.cadenceLabel?.isEmpty == false ? r.cadenceLabel : nil) ?? "—")
                    KvRow(label: "Avg gap between orders", value: (r.avgIntervalDays ?? 0) != 0 ? "\(Fmt.number(r.avgIntervalDays)) days" : "—")
                    // crm.py `_buying_rhythm` floors (now − last order).days; a hub order stamped in local time but read as UTC can come back as -1.
                    KvRow(label: "Since last order", value: r.daysSinceLast.map { "\(max(0, $0)) days" } ?? "—")
                    if r.overdue {
                        Text("⏰ Overdue — it's been longer than their usual gap. A good moment to check in.")
                            .font(NeemaFont.manrope(11)).foregroundColor(Palette.amber700.themed(c.isDark))
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.horizontal, 8).padding(.vertical, 6)
                            .background(RoundedRectangle(cornerRadius: 4).fill(Palette.amber500.dim(0.1)))
                            .roundedBorder(Palette.amber200, radius: 4)
                            .padding(.top, 4)
                    }
                }
            }
            if !ctx.orders.isEmpty {
                CrmSection("Top Products") {
                    let top = topProducts()
                    ForEach(Array(top.enumerated()), id: \.offset) { idx, item in
                        HStack {
                            Text(item.name).font(NeemaFont.manrope(12)).foregroundColor(c.textMid).lineLimit(1).padding(.trailing, 8)
                            Spacer()
                            VStack(alignment: .trailing, spacing: 1) {
                                Text(Fmt.currency(item.total)).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
                                Text("×\(Fmt.number(item.qty))").font(NeemaFont.manrope(10)).foregroundColor(c.muted)
                            }
                        }
                        .padding(.vertical, 6)
                        if idx < top.count - 1 { CrmHairline() }
                    }
                }
            }
            // Straight from the API — the server owns the scoring, so this can never drift from the ranking.
            CrmSection("Lead Score Breakdown") {
                ForEach(Array(p.leadScoreBreakdown.enumerated()), id: \.offset) { _, row in
                    VStack(spacing: 2) {
                        HStack {
                            Text(row.label).font(NeemaFont.manrope(10)).foregroundColor(c.textMid)
                            Spacer()
                            Text("\(Fmt.number(row.pts))/\(Fmt.number(row.max))").font(NeemaFont.manrope(10)).foregroundColor(c.textMid)
                        }
                        ProgressBar(fraction: row.max != 0 ? row.pts / row.max : 0, color: Palette.green500).frame(height: 4)
                    }
                    .padding(.bottom, 8)
                }
            }
        }
    }

    private func topProducts() -> [Agg] {
        var order: [String] = []
        var map: [String: Agg] = [:]
        for o in ctx.orders {
            for i in o.items {
                if map[i.name] == nil { map[i.name] = Agg(name: i.name); order.append(i.name) }
                let q = (i.qty ?? 0) != 0 ? i.qty! : ((i.quantity ?? 0) != 0 ? i.quantity! : 1)
                map[i.name]!.qty += q
                map[i.name]!.total += i.total ?? 0
            }
        }
        return Array(order.compactMap { map[$0] }.sorted { $0.total > $1.total }.prefix(4))
    }
}

// ── Activity tab ────────────────────────────────────────────────────────────

func orderStatusColor(_ status: String?) -> Color {
    switch status {
    case "delivered": return Palette.emerald700
    case "confirmed": return Palette.blue700
    case "cancelled": return Palette.red600
    default: return Palette.amber700
    }
}

struct ActivityTab: View {
    let ctx: PanelCtx
    @Environment(\.neema) private var c

    var body: some View {
        let p = ctx.profile
        VStack(alignment: .leading, spacing: 0) {
            CrmSection("Recent Orders") {
                if p.hubLinked {
                    HStack(alignment: .top, spacing: 0) {
                        Text("📇 ").font(NeemaFont.manrope(11))
                        Text("Same customer in the shop" + ((p.hubCustomerName?.isEmpty == false) ? " · \(p.hubCustomerName!)" : "") + " — showing full in-shop + WhatsApp history")
                            .font(NeemaFont.manrope(11)).foregroundColor(c.isDark ? c.gold2 : Palette.lime800)
                    }
                    .padding(.horizontal, 8).padding(.vertical, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(c.goldDim))
                    .roundedBorder(c.hairline, radius: 6)
                    .padding(.bottom, 8)
                    .accessibilityHint("Matched to a shop customer by phone number — same person across the counter and WhatsApp")
                }
                if ctx.orders.isEmpty {
                    Text("No orders yet").font(NeemaFont.manrope(12)).foregroundColor(c.muted).frame(maxWidth: .infinity).padding(.vertical, 12)
                } else {
                    VStack(spacing: 8) {
                        ForEach(Array(ctx.orders.prefix(5).enumerated()), id: \.offset) { _, o in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack {
                                    let sc = orderStatusColor(o.status).themed(c.isDark)
                                    Text(o.status ?? "—").font(NeemaFont.manrope(10, .bold)).foregroundColor(sc)
                                        .padding(.horizontal, 6).padding(.vertical, 2).background(RoundedRectangle(cornerRadius: 4).fill(sc.dim(0.1)))
                                    Spacer()
                                    Text(Fmt.timeAgo(o.createdIso)).font(NeemaFont.manrope(10)).foregroundColor(c.muted)
                                }
                                .padding(.bottom, 2)
                                Text(Fmt.currency(o.total ?? o.subtotal ?? 0, o.displayCurrency)).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
                                Text(o.items.map { $0.name }.joined(separator: ", ").isEmpty ? "—" : o.items.map { $0.name }.joined(separator: ", "))
                                    .font(NeemaFont.manrope(10)).foregroundColor(c.textMid).lineLimit(1)
                            }
                            .padding(10)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg2))
                            .roundedBorder(c.hairline, radius: 8)
                        }
                    }
                }
            }
            CrmSection("Channel History") {
                ForEach(Array(p.channels.enumerated()), id: \.offset) { i, ch in
                    HStack(alignment: .top, spacing: 8) {
                        ChannelBadge(channel: Crm.badgeKey(ch.channel, identifier: ch.identifier))
                        VStack(alignment: .leading, spacing: 1) {
                            Text(Crm.channelLabel(ch.channel, identifier: ch.identifier)).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
                            Text("\(ch.conversationCount) conversation\(ch.conversationCount != 1 ? "s" : "")").font(NeemaFont.manrope(10)).foregroundColor(c.muted)
                            Text("First: \(ch.firstSeen.map { Fmt.date($0) } ?? "—") · Last: \(ch.lastSeen.map { Fmt.timeAgo($0) } ?? "—")").font(NeemaFont.manrope(10)).foregroundColor(c.muted)
                        }
                    }
                    .padding(.vertical, 8)
                    if i < p.channels.count - 1 { CrmHairline() }
                }
            }
        }
    }
}
