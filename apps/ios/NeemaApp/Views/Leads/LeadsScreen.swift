import SwiftUI
import NeemaCore

/// `fmtCurrency` — "KES 1,234", never split between "KES" and the digits.
func leadMoney(_ n: Double) -> String { Fmt.currency(n).unbroken }

/// A stage's colours (LeadsView STAGES' Tailwind classes; Android `LeadStage`'s
/// text / bg / border / dot). Dark mode: the pale tints would glare, so they
/// become washes of the dot colour.
struct LeadStageLook {
    let text: Color
    let bg: Color
    let border: Color
    let dot: Color

    static func of(_ s: LeadStage) -> LeadStageLook {
        if s.custom { return LeadStageLook(text: Palette.yellow700, bg: Palette.yellow50, border: Palette.yellow200, dot: Palette.yellow500) }
        switch s.id {
        case "contacted": return LeadStageLook(text: Palette.blue700, bg: Palette.blue50, border: Palette.blue200, dot: Palette.blue500)
        case "qualified": return LeadStageLook(text: Palette.violet700, bg: Palette.violet50, border: Palette.violet200, dot: Palette.violet500)
        case "proposal": return LeadStageLook(text: Palette.amber700, bg: Palette.amber50, border: Palette.amber200, dot: Palette.amber500)
        case "negotiation": return LeadStageLook(text: Palette.orange700, bg: Palette.orange50, border: Palette.orange200, dot: Palette.orange500)
        case "won": return LeadStageLook(text: Palette.emerald700, bg: Palette.emerald50, border: Palette.emerald200, dot: Palette.emerald500)
        case "lost": return LeadStageLook(text: Palette.red600, bg: Palette.red50, border: Palette.red200, dot: Palette.red400)
        default: return LeadStageLook(text: Palette.stone600, bg: Palette.stone50, border: Palette.stone200, dot: Palette.stone400)
        }
    }

    func bgC(_ dark: Bool) -> Color { dark ? dot.opacity(0.14) : bg }
    func borderC(_ dark: Bool) -> Color { dark ? dot.opacity(0.35) : border }
    func textC(_ dark: Bool) -> Color { dark ? dot : text }
}

/// ChannelIcon — the channel's white mark in a round badge of its colour
/// (Instagram's on its gradient, the web's `url(#igGrad)`, bottom-left → top-right).
struct LeadChannelIcon: View {
    let channel: String
    var size: CGFloat = 16

    private static let igGradient = LinearGradient(
        stops: [
            .init(color: Color(hex: 0xF09433), location: 0), .init(color: Color(hex: 0xE6683C), location: 0.25),
            .init(color: Color(hex: 0xDC2743), location: 0.5), .init(color: Color(hex: 0xCC2366), location: 0.75),
            .init(color: Color(hex: 0xBC1888), location: 1),
        ],
        startPoint: .bottomLeading, endPoint: .topTrailing
    )

    private var key: String { channel.lowercased() }

    /// nil: Instagram's gradient.
    private var fill: Color? {
        switch key {
        case "whatsapp": return ChannelColors.whatsApp
        case "messenger": return ChannelColors.messenger
        case "facebook": return ChannelColors.facebook
        case "email": return ChannelColors.email
        case "instagram": return nil
        default: return ChannelColors.sms
        }
    }

    private var glyph: String {
        switch key {
        case "email": return "@"
        default: return "✉"
        }
    }

    var body: some View {
        ZStack {
            if let f = fill { Circle().fill(f) } else { Circle().fill(Self.igGradient) }
            if let d = ChannelIcons.of(key) {
                SVGIcon(d: d, size: size * 0.6).foregroundColor(.white)
            } else {
                Text(glyph).font(NeemaFont.fixed(size * 0.55, .bold)).foregroundColor(.white)
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel(channelStyle(key).label)
    }
}

/// Port of components/views/LeadsView.tsx (Android `LeadsScreen`) — the leads
/// pipeline as a kanban: one column per stage (canonical + the operator's own
/// from Settings), stage filter pills with counts, search, cards with score
/// bars and stage moves, and the lead detail (stage, tags, notes) as a sheet.
///
/// No permission gate here: page.tsx hides the Leads nav item without
/// view_leads, but LeadsView itself checks nothing (a ?view=leads link still
/// opens it) — no manage_leads test on the stage moves or the detail's Save —
/// and crm.py `list_leads` / `update_lead` only require a signed-in agent. A
/// refusal the server does send is said where the save failed.
struct LeadsScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.leadsScreen {
            GeometryReader { g in LeadsBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}


struct LeadsBody: View {
    @ObservedObject var model: LeadsScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @SceneStorage("leads.ui") private var savedUi: String = ""

    private var vm: LeadsViewModel { model.vm }
    private var ui: LeadsUi { model.ui }
    /// A phone's bottom sheet; on a tablet window the lead opens beside the pipeline.
    private var wide: Bool { width >= 600 }
    private var selectedLead: Lead? { ui.selectedId.flatMap { id in ui.leads.first { $0.id == id } } }

    var body: some View {
        // Everything the board shows, derived once per change (not per column):
        // 500 leads across seven columns is one pass, not seven filters and seven counts.
        let leads = ui.leads
        let filtered = LeadsRules.filterLeads(leads, filterStage: ui.filterStage, search: ui.search)
        let board = LeadsRules.buildBoard(leads, filtered: filtered, stages: ui.stages)
        // Never loaded: no counts or totals — zeros would be a claim.
        let unknown = leads.isEmpty && (ui.loading || ui.loadError != nil)
        let selected = selectedLead
        TimelineView(.periodic(from: .now, by: 60)) { ctx in
            let now = Int64(ctx.date.timeIntervalSince1970 * 1000)
            VStack(spacing: 0) {
                headerBlock(board: board, unknown: unknown)
                // A refresh failed with leads on screen: they stay, and this says why.
                if let e = ui.loadError, !leads.isEmpty, !ui.loading {
                    StaleBanner(reason: e, onRetry: { vm.refresh() }).padding(.horizontal, 16).padding(.top, 12)
                }
                boardArea(board: board, now: now)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg)
        // A phone sheet, or a 480 pt panel beside the board from 600 pt (Android `AdaptiveSheet`); the detail brings its own header.
        .adaptiveSheet(item: sheetItem, width: width, panelWidth: 480, maxFraction: 0.8, titleBar: false, title: { sheetTitle($0) }) { l in detail(l) }
        .onAppear {
            vm.restoreIfFresh(JSONValue.parse(savedUi)?.objectValue)
            vm.life.shown.update(true)
        }
        .onDisappear { vm.life.shown.update(false) }
        .onChange(of: ui) { u in
            savedUi = JSONValue.object(vm.saveUi()).text
            // Gone from the board (deleted, merged). Not before the first read: a
            // lead restored after the app was reclaimed waits for the board to load.
            if let id = u.selectedId, !u.loading, !u.leads.contains(where: { $0.id == id }) { vm.select(nil) }
        }
    }

    // ── Header ────────────────────────────────────────────────────────────────

    private func headerBlock(board: LeadBoard, unknown: Bool) -> some View {
        VStack(spacing: 0) {
            if wide {
                HStack(alignment: .center, spacing: 12) {
                    headerText(board: board, unknown: unknown).frame(maxWidth: .infinity, alignment: .leading)
                    search.frame(width: 220)
                }
                .padding(.horizontal, 24).padding(.vertical, 16)
            } else {
                // The search field's touch cell adds its own room above and below its h-8 box.
                VStack(alignment: .leading, spacing: 2) {
                    headerText(board: board, unknown: unknown)
                    search
                }
                .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 4)
            }
            Hairline(color: c.bg4)
            pills(board: board, unknown: unknown)
            Hairline(color: c.bg4)
        }
        .background(c.bg2)
    }

    private func headerText(board: LeadBoard, unknown: Bool) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Leads Pipeline").font(NeemaFont.manrope(20, .bold)).tracking(-0.5).foregroundColor(c.text)
            Text(subtitle(board: board, unknown: unknown)).font(NeemaFont.manrope(14)).foregroundColor(c.textDim).monospacedDigit()
        }
    }

    private func subtitle(board: LeadBoard, unknown: Bool) -> String {
        if unknown { return ui.loadError != nil ? "Not loaded" : "Loading…" }
        return "\(ui.leads.count) leads · Pipeline \(leadMoney(board.pipelineValue)) · Won \(leadMoney(board.wonValue))"
    }

    /// The header's search: h-8, 14px text, rounded-lg.
    private var search: some View {
        CompactSearchField(value: Binding(get: { ui.search }, set: { vm.setSearch($0) }), placeholder: "Search leads…", height: 32, radius: 8, fontSize: 14)
    }

    /// The stage filter pills: "All" and one per column, each with its count.
    private func pills(board: LeadBoard, unknown: Bool) -> some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                StagePill(label: unknown ? "All" : "All (\(ui.leads.count))", selected: ui.filterStage == "all", stage: nil) { vm.setFilterStage("all") }
                ForEach(ui.stages) { s in
                    StagePill(label: unknown ? s.label : "\(s.label) (\(board.counts[s.id] ?? 0))",
                              selected: ui.filterStage.caseInsensitiveCompare(s.id) == .orderedSame, stage: s) { vm.setFilterStage(s.id) }
                }
            }
            // px-6 py-3 as the web has it; the pills' touch cells carry most of the py-3.
            .padding(.horizontal, 24).padding(.vertical, 2)
        }
    }

    // ── Board ─────────────────────────────────────────────────────────────────

    private func boardArea(board: LeadBoard, now: Int64) -> some View {
        Group {
            if ui.loading {
                // w-6 h-6 border-2, moss
                LoadingView()
            } else if let e = ui.loadError, ui.leads.isEmpty {
                // Never read: seven empty columns would claim there are no leads.
                ScrollView { ErrorStateView(message: e, onRetry: { vm.load() }).padding(.top, 32) }
            } else {
                GeometryReader { g in
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(alignment: .top, spacing: 12) {
                            ForEach(ui.stages) { stage in
                                LeadStageColumn(stage: stage, leads: board.columns[stage.id] ?? [], value: board.columnValue[stage.id] ?? 0,
                                                stages: ui.stages, width: columnWidth(g.size.width), saving: ui.saving, now: now,
                                                onSelect: { vm.select($0.id) }, onMove: { l, to in Haptics.tap(); vm.moveTo(l, to) },
                                                onRefresh: { await pullToRefresh() })
                            }
                        }
                        .padding(16)
                        .frame(height: g.size.height)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// Columns fill the width: as many whole ~260pt columns as fit plus a third
    /// of the next (so it reads as "scroll for more"); all of them edge to edge
    /// when they fit.
    private func columnWidth(_ boardWidth: CGFloat) -> CGFloat {
        let avail = boardWidth - 32
        let gap: CGFloat = 12
        let target: CGFloat = 260
        let whole = max(1, Int((avail + gap) / (target + gap)))
        let n = max(1, ui.stages.count)
        if n <= whole { return (avail - gap * CGFloat(n - 1)) / CGFloat(n) }
        return (avail - gap * CGFloat(whole)) / (CGFloat(whole) + 0.35)
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }

    // ── The lead detail ───────────────────────────────────────────────────────

    private func sheetTitle(_ lead: Lead?) -> String {
        if let n = lead?.name, !n.trimmingCharacters(in: .whitespaces).isEmpty { return n }
        return "Lead"
    }

    /// The sheet's fields as typed (the model's, so they outlive a reclaim),
    /// started from the lead as it is until the sheet has shown once for it.
    private func draftFor(_ lead: Lead) -> LeadSheetDraft {
        if let d = ui.sheet, d.leadId == lead.id { return d }
        return LeadSheetDraft.of(lead, ui.stages)
    }

    private func detail(_ lead: Lead) -> some View {
        LeadDetailView(lead: lead, stages: ui.stages, draft: draftFor(lead), saving: ui.saving.contains(lead.id), error: ui.sheetError,
                       onDraft: { vm.editSheet($0) },
                       onClose: { vm.select(nil) },
                       onOpenChat: { app.openConversationFor(lead.handle) },
                       // The sheet closes when the server has the change; a failure keeps it open, fields as typed.
                       onSave: { vm.save(lead, $0) })
            // Started once per open lead (as the lead is then), kept as typed.
            .id(lead.id)
            .onAppear { _ = vm.sheetFor(lead) }
    }

    /// The open lead; a swipe or a tap outside closes the sheet but keeps what was typed for this lead.
    private var sheetItem: Binding<Lead?> {
        Binding(get: { selectedLead }, set: { if $0 == nil { vm.dismissSheet() } })
    }
}

// ── Pieces ────────────────────────────────────────────────────────────────────

/// A stage filter pill: 28pt to the eye (h-7), 44pt to the finger (Android `StagePill`).
private struct StagePill: View {
    let label: String
    let selected: Bool
    let stage: LeadStage?
    let action: () -> Void
    @Environment(\.neema) private var c

    private var look: LeadStageLook? { stage.map(LeadStageLook.of) }

    // "All" has no colour classes of its own: selected it is a bare `border`
    // (currentColor) over the white bar; unselected it keeps the page's text colour.
    private var bg: Color {
        if selected, let l = look { return l.bgC(c.isDark) }
        return c.bg2
    }

    private var border: Color {
        if selected, let l = look { return l.borderC(c.isDark) }
        if selected { return c.text }
        return c.isDark ? c.hairline : Palette.stone200
    }

    private var fg: Color {
        if selected, let l = look { return l.textC(c.isDark) }
        if stage == nil { return c.text }
        return c.isDark ? c.textMid : Palette.stone500
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let l = look { Circle().fill(l.dot).frame(width: 6, height: 6) }
                Text(label).font(NeemaFont.manrope(12, .medium)).foregroundColor(fg).monospacedDigit().lineLimit(1)
            }
            .padding(.horizontal, 12).padding(.vertical, 2)
            .frame(minHeight: 28)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(bg))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(border))
            .frame(minHeight: 44)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selected ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}

/// A stage column: its header, then its cards (Android `StageColumn`). Pull
/// down on any column to re-read the board.
struct LeadStageColumn: View {
    let stage: LeadStage
    let leads: [Lead]
    let value: Double
    let stages: [LeadStage]
    let width: CGFloat
    let saving: Set<String>
    let now: Int64
    let onSelect: (Lead) -> Void
    let onMove: (Lead, String) -> Void
    let onRefresh: () async -> Void
    @Environment(\.neema) private var c

    private var look: LeadStageLook { LeadStageLook.of(stage) }

    var body: some View {
        VStack(spacing: 0) {
            header.padding(.bottom, 8)
            ScrollView(showsIndicators: false) {
                if leads.isEmpty {
                    Text("No leads").font(NeemaFont.manrope(12)).foregroundColor(c.border2)
                        .frame(maxWidth: .infinity).padding(.vertical, 32)
                } else {
                    LazyVStack(spacing: 8) {
                        ForEach(leads) { lead in
                            LeadCard(lead: lead, stages: stages, busy: saving.contains(lead.id), now: now,
                                     onSelect: { onSelect(lead) }, onMove: { onMove(lead, $0) })
                        }
                    }
                }
            }
            .refreshable { await onRefresh() }
        }
        .frame(width: width)
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private var header: some View {
        HStack(spacing: 6) {
            Circle().fill(look.dot).frame(width: 8, height: 8)
            Text(stage.label).font(NeemaFont.manrope(12, .bold)).foregroundColor(look.textC(c.isDark)).lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            VStack(alignment: .trailing, spacing: 0) {
                Text(String(leads.count)).font(NeemaFont.manrope(12, .bold)).foregroundColor(look.textC(c.isDark)).monospacedDigit()
                if value > 0 {
                    Text(leadMoney(value)).font(NeemaFont.manrope(10)).foregroundColor(look.textC(c.isDark).opacity(0.7)).monospacedDigit().lineLimit(1)
                }
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(look.bgC(c.isDark)))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(look.borderC(c.isDark)))
    }
}

/// One lead on the board: who, their score, channels, money, tags, when they
/// were last seen, and the moves to the neighbouring columns (Android `LeadCard`).
struct LeadCard: View {
    let lead: Lead
    let stages: [LeadStage]
    let busy: Bool
    let now: Int64
    let onSelect: () -> Void
    let onMove: (String) -> Void
    @Environment(\.neema) private var c

    private var stageIdx: Int? { stages.firstIndex { $0.matches(lead.leadStage) } }
    private var prev: LeadStage? {
        guard let i = stageIdx, i > 0 else { return nil }
        return stages[i - 1]
    }
    /// Never "lost": a lead is only lost from the detail, as on the web.
    private var next: LeadStage? {
        guard let i = stageIdx, i < stages.count - 1, stages[i + 1].id != "lost" else { return nil }
        return stages[i + 1]
    }
    private var barColor: Color {
        if lead.leadScore >= 70 { return Palette.emerald500 }
        if lead.leadScore >= 40 { return Palette.amber500 }
        return Palette.stone300
    }
    private var hasName: Bool { !(lead.name ?? "").trimmingCharacters(in: .whitespaces).isEmpty }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 8) {
                AvatarView(name: Fmt.displayName(lead.name, lead.handle), size: 32)
                VStack(alignment: .leading, spacing: 0) {
                    if hasName {
                        Text(lead.name ?? "").font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text).lineLimit(1)
                    } else {
                        Text("Unknown").font(NeemaFont.manrope(12)).italic().foregroundColor(c.isDark ? c.muted : Palette.stone400)
                    }
                    Text(Fmt.formatPhone(lead.handle)).font(NeemaFont.mono(10)).foregroundColor(c.textDim).lineLimit(1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                Text("\(lead.leadScore)/100").font(NeemaFont.manrope(10, .bold)).foregroundColor(c.textDim).monospacedDigit().lineLimit(1)
            }
            // Score bar
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(c.bg3)
                    Capsule().fill(barColor).frame(width: g.size.width * CGFloat(lead.leadScore) / 100)
                }
            }
            .frame(height: 4)
            .padding(.top, 8)
            HStack(spacing: 4) {
                ForEach(Array(lead.channels.prefix(3).enumerated()), id: \.offset) { _, ch in LeadChannelIcon(channel: ch) }
                Spacer(minLength: 0)
                if lead.totalSpent > 0 {
                    Text(leadMoney(lead.totalSpent)).font(NeemaFont.manrope(10, .semibold)).foregroundColor(c.gold2).monospacedDigit().lineLimit(1)
                }
            }
            .padding(.top, 8)
            if !lead.tags.isEmpty {
                FlowLayout(spacing: 4, lineSpacing: 4) {
                    ForEach(Array(lead.tags.prefix(3).enumerated()), id: \.offset) { _, tag in
                        Text(tag).font(NeemaFont.manrope(9)).foregroundColor(c.gold2)
                            .padding(.horizontal, 4).padding(.vertical, 2)
                            .background(RoundedRectangle(cornerRadius: 4, style: .continuous).fill(c.bg3))
                    }
                }
                .padding(.top, 6)
            }
            if let seen = lead.lastSeenAt, !seen.isEmpty {
                Text(Fmt.timeAgo(seen, now: now)).font(NeemaFont.manrope(10)).foregroundColor(c.textDim).padding(.top, 6)
            }
            // Stage moves. Hover-only on the web; always shown on a touch screen.
            if prev != nil || next != nil {
                Hairline(color: c.bg3).padding(.top, 8)
                HStack(spacing: 6) {
                    if let p = prev {
                        MoveButton(label: "← \(p.label)", bg: c.isDark ? c.bg : Palette.moss50, fg: c.textDim, enabled: !busy) { onMove(p.id) }
                    }
                    if let n = next {
                        MoveButton(label: "\(n.label) →", bg: c.bg3, fg: c.gold2, enabled: !busy) { onMove(n.id) }
                    }
                }
                .padding(.top, 4)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.bg3))
        .contentShape(Rectangle())
        .onTapGesture(perform: onSelect)
    }
}

/// The web's rounded py-1 chip, but a touch-sized one: the web shows it on
/// hover at 9px; here it is always there and is the card's main action, so it
/// reads at 11pt and takes a 44pt touch cell (32pt to the eye).
private struct MoveButton: View {
    let label: String
    let bg: Color
    let fg: Color
    var enabled: Bool = true
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Button(action: action) {
            Text(label).font(NeemaFont.manrope(11)).foregroundColor(fg.opacity(enabled ? 1 : 0.45)).lineLimit(1)
                .padding(.horizontal, 4).padding(.vertical, 6)
                .frame(maxWidth: .infinity, minHeight: 32)
                .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(bg))
                .overlay(RoundedRectangle(cornerRadius: 6, style: .continuous).stroke(c.border))
                .frame(minHeight: 44)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}
