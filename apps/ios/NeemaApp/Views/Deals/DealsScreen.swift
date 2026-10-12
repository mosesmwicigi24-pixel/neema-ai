import SwiftUI
import NeemaCore

/// Port of components/views/DealsView.tsx (Android `DealsScreen`) — the shared
/// board: what Neema owns right now, what's blocking each deal, whose move is
/// next and when she plans to act. On top, her planned-actions queue: send
/// (as drafted or edited) or veto anything before it fires.
///
/// No permission gate here: page.tsx hides the Deals nav item without
/// view_leads, but DealsView itself checks nothing, and crm.py's deals/actions
/// routes only require a signed-in agent. Send, Veto, Guidance, Won and Lost
/// show for everyone, as on the web.
struct DealsScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.dealsScreen {
            GeometryReader { g in DealsBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}

/// A board column's look.
private struct StageLook {
    let id: String
    let color: Color
    static func of(_ id: String) -> Color {
        switch id {
        case "qualified": return Palette.moss600
        case "proposal": return Palette.amber500
        default: return Palette.slate400
        }
    }
}

struct DraftSheetItem: Identifiable, Equatable { let id: String }

struct DealsBody: View {
    @ObservedObject var model: DealsScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @SceneStorage("deals.ui") private var savedUi: String = ""

    private var vm: DealsViewModel { model.vm }
    private var ui: DealsUi { model.ui }
    /// Three stage columns (and the queue's buttons beside its text) need a real tablet width.
    private var wide: Bool { width >= 840 }
    private var gutter: CGFloat { width >= 600 ? 24 : 16 }

    var body: some View {
        // Derived once per load, not on every tick of the queue's spinner.
        let open = (ui.deals ?? []).filter { $0.status == "open" }
        let columns = DealsRules.columns(open)
        let err = ui.loadError
        TimelineView(.periodic(from: .now, by: 60)) { ctx in
            let now = Int64(ctx.date.timeIntervalSince1970 * 1000)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    header(open: open.count).padding(.bottom, 16)
                    // A refresh failed with something on screen: it stays, and this says why.
                    if let e = err, ui.deals != nil || ui.actions != nil {
                        StaleBanner(reason: e, onRetry: { vm.refresh() }).padding(.bottom, 16)
                    }
                    queueCard(now: now, err: err).padding(.bottom, 20)
                    if ui.deals == nil, let e = err {
                        // Nothing was ever read: an empty board would claim there are no deals.
                        ErrorStateView(message: e, onRetry: { vm.reload() })
                    } else if ui.deals == nil {
                        LoadingView().frame(height: 160)
                    } else if wide {
                        HStack(alignment: .top, spacing: 16) {
                            ForEach(columns) { col in
                                StageColumn(stage: col.stage, deals: col.deals, now: now, card: { dealCard($0, now: now) })
                                    .frame(maxWidth: .infinity, alignment: .top)
                            }
                        }
                        .padding(.bottom, 16)
                    } else {
                        // A phone stacks the columns.
                        ForEach(columns) { col in
                            StageColumn(stage: col.stage, deals: col.deals, now: now, card: { dealCard($0, now: now) })
                                .padding(.bottom, 16)
                        }
                    }
                }
                .frame(maxWidth: 1100)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, gutter).padding(.vertical, 24)
            }
            .refreshable { await pullToRefresh() }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        // The page is the web's own #f6f7f2, a shade off the shell's parchment.
        .background(c.isDark ? c.surface : Palette.dealsPage)
        .sheet(item: draftItem) { item in
            if let a = ui.draftFor, a.id == item.id {
                DraftDialog(action: a, text: Binding(get: { ui.draftText }, set: { vm.setDraftText($0) }),
                            busy: ui.acting.contains(a.id), checking: ui.checking.contains(a.id), error: ui.draftError,
                            onDismiss: { vm.openDraft(nil) }, onSend: { vm.act(a.id, "approve", draft: ui.draftText) })
                    .environment(\.neema, c)
                    .presentationDetents([.medium, .large])
                    .presentationDragIndicator(.visible)
            }
        }
        .onAppear {
            vm.restoreIfFresh(JSONValue.parse(savedUi)?.objectValue)
            vm.life.shown.update(true)
        }
        .onDisappear { vm.life.shown.update(false) }
        .onChange(of: ui) { _ in savedUi = JSONValue.object(vm.saveUi()).text }
    }

    // ── Pieces ────────────────────────────────────────────────────────────────

    private func header(open: Int) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("Deals").font(NeemaFont.manrope(20, .semibold)).foregroundColor(c.text)
            // Never loaded: no counts — "0 open · 0 won" would be a claim.
            Text(ui.deals == nil ? "What Neema owns right now" : "What Neema owns right now · \(open) open · \(ui.wonCount) won")
                .font(NeemaFont.manrope(12)).foregroundColor(c.muted)
        }
    }

    /// One bordered card: the queue's heading, then a row per planned action.
    private func queueCard(now: Int64, err: String?) -> some View {
        let rows = ui.actions ?? []
        return VStack(alignment: .leading, spacing: 8) {
            Text("PLANNED ACTIONS — NEEMA'S NEXT MOVES").font(NeemaFont.manrope(11, .semibold)).tracking(0.275).foregroundColor(c.muted)
            if ui.actions == nil && err != nil {
                // The reason is in the banner / error state just below.
                Text("Couldn't load the queue.").font(NeemaFont.manrope(12)).foregroundColor(stone400)
            } else if ui.actions == nil {
                Text("Loading…").font(NeemaFont.manrope(12)).foregroundColor(stone400)
            } else if rows.isEmpty {
                Text("Nothing queued. Promises made in chat (hers or the customer's) land here automatically.").font(NeemaFont.manrope(12)).foregroundColor(stone400)
            }
            ForEach(rows) { a in
                ActionRow(action: a, busy: ui.acting.contains(a.id), checking: ui.checking.contains(a.id), wide: wide, now: now,
                          onSend: { vm.act(a.id, "approve") }, onEdit: { vm.openDraft(a) }, onVeto: { vm.act(a.id, "veto") },
                          onOpen: a.conversationId.map { id in { app.openConversationFor(id) } })
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(stone200))
    }

    private func dealCard(_ d: Deal, now: Int64) -> some View {
        DealCard(deal: d, busy: ui.patching.contains(d.id), isEditing: ui.editing == d.id,
                 guidanceError: ui.editing == d.id ? ui.guidanceError : nil,
                 guidanceDraft: Binding(get: { ui.guidanceDraft }, set: { vm.setGuidanceDraft($0) }), now: now,
                 onEdit: { vm.startGuidance(d) }, onCancel: { vm.cancelGuidance() }, onSave: { vm.saveGuidance(d.id) },
                 onWon: { vm.markWon(d.id) }, onLost: { vm.markLost(d.id) },
                 onOpen: { if let key = DealsRules.threadKey(d) { app.openConversationFor(key) } })
    }

    private var draftItem: Binding<DraftSheetItem?> {
        Binding(get: { ui.draftFor.map { DraftSheetItem(id: $0.id) } }, set: { if $0 == nil { vm.openDraft(nil) } })
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }

    /// Tailwind stone-200, the web's card border; the theme hairline in dark mode.
    private var stone200: Color { c.isDark ? c.hairline : Palette.stone200 }
    /// Tailwind stone-400, the queue's quiet text; the theme's muted in dark mode.
    private var stone400: Color { c.isDark ? c.muted : Palette.stone400 }
}

/// The web's slate-500 secondary text; lifted in dark mode so it stays legible on navy.
private func slate(_ c: NeemaColors) -> Color { c.isDark ? Palette.slate400 : Palette.slate500 }

/// The web's compact button to the eye, a 44pt cell to the finger (Android `SmallButton`).
struct SmallButton: View {
    let label: String
    let bg: Color
    let fg: Color
    var border: Color? = nil
    var enabled: Bool = true
    var fontSize: CGFloat = 11
    var hPad: CGFloat = 12
    var vPad: CGFloat = 6
    var weight: NeemaFont.Weight = .semibold
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label).font(NeemaFont.manrope(fontSize, weight)).foregroundColor(fg.opacity(enabled ? 1 : 0.5)).lineLimit(1)
                .padding(.horizontal, hPad).padding(.vertical, vPad)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(enabled ? bg : bg.opacity(0.5)))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(border ?? .clear))
                .frame(minHeight: 44)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

/// One planned action in the queue (Android `ActionRow`).
struct ActionRow: View {
    let action: PlannedAction
    let busy: Bool
    let checking: Bool
    let wide: Bool
    let now: Int64
    let onSend: () -> Void
    let onEdit: () -> Void
    let onVeto: () -> Void
    let onOpen: (() -> Void)?
    @Environment(\.neema) private var c

    private var needs: Bool { action.status == "needs_approval" }

    var body: some View {
        let bg: Color = c.isDark ? (needs ? c.amber.opacity(0.15) : c.bg3) : (needs ? Palette.needsBg : Palette.queuedBg)
        let border: Color = c.isDark ? (needs ? c.amber.opacity(0.4) : c.border) : (needs ? Palette.needsBorder : Palette.queuedBorder)
        Group {
            if wide {
                // The web's row: the text takes the room, the buttons sit on the right.
                HStack(alignment: .top, spacing: 12) {
                    textBlock.frame(maxWidth: .infinity, alignment: .leading)
                    buttons.frame(maxWidth: 320, alignment: .trailing)
                }
            } else {
                // A phone has no room beside the text for three buttons: they go beneath it.
                VStack(alignment: .leading, spacing: 8) {
                    textBlock
                    buttons
                }
            }
        }
        .padding(.horizontal, 12).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(bg))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(border))
    }

    private var textBlock: some View {
        VStack(alignment: .leading, spacing: 2) {
            (Text(DealsRules.rowLead(action, now: now)).fontWeight(.medium).foregroundColor(c.text)
                + Text(" · \(action.kind == "customer_promise" ? "their timeline" : "her promise")").foregroundColor(slate(c)))
                .font(NeemaFont.manrope(12))
            if let r = action.reason, !r.isEmpty {
                Text(r).font(NeemaFont.manrope(12)).foregroundColor(c.isDark ? c.textMid : Palette.slate600).lineLimit(2)
            }
            if let d = action.draft, !d.isEmpty {
                Text("“\(d)”").font(NeemaFont.manrope(11)).foregroundColor(c.text).lineLimit(3)
                    .padding(.horizontal, 8).padding(.vertical, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg2))
                    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.isDark ? c.hairline : Palette.stone100))
                    .padding(.top, 2)
            }
        }
    }

    private var buttons: some View {
        VStack(alignment: .leading, spacing: 0) {
            FlowLayout(spacing: 6, lineSpacing: 2) {
                SmallButton(label: "Send", bg: Palette.moss600, fg: .white, enabled: !busy, action: onSend)
                SmallButton(label: "Edit & send", bg: c.bg2, fg: c.gold2, border: c.border, enabled: !busy, action: onEdit)
                SmallButton(label: "Veto", bg: c.isDark ? c.bg4 : Palette.stone100, fg: slate(c), enabled: !busy, action: onVeto)
                if let open = onOpen { SmallButton(label: "Open chat", bg: .clear, fg: c.gold2, enabled: true, action: open) }
            }
            // In flight, or its answer lost and being checked: say which, under the (locked) buttons.
            if busy {
                HStack(spacing: 6) {
                    ProgressView().progressViewStyle(.circular).scaleEffect(0.6).frame(width: 12, height: 12)
                    Text(checking ? "No answer yet — checking whether it went…" : "Working…").font(NeemaFont.manrope(11)).foregroundColor(slate(c))
                }
                .padding(.top, 4)
            }
        }
    }
}

/// A stage column: its header, then its deals (Android `StageColumn`).
struct StageColumn<Card: View>: View {
    let stage: DealStage
    let deals: [Deal]
    let now: Int64
    @ViewBuilder let card: (Deal) -> Card
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Circle().fill(StageLook.of(stage.id)).frame(width: 8, height: 8)
                Text(stage.label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
                Text(String(deals.count)).font(NeemaFont.manrope(10)).foregroundColor(c.muted)
            }
            .padding(.horizontal, 4).padding(.bottom, 8)
            VStack(spacing: 8) {
                ForEach(deals) { d in card(d) }
                if deals.isEmpty {
                    Text("—").font(NeemaFont.manrope(11)).foregroundColor(c.isDark ? c.border : Palette.stone300)
                        .frame(maxWidth: .infinity).padding(.vertical, 16)
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: 120, alignment: .top)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(c.isDark ? c.hairline : Palette.stone200))
    }
}

/// One deal on the board, with its guidance editor (Android `DealCard`).
struct DealCard: View {
    let deal: Deal
    let busy: Bool
    let isEditing: Bool
    let guidanceError: String?
    @Binding var guidanceDraft: String
    let now: Int64
    let onEdit: () -> Void
    let onCancel: () -> Void
    let onSave: () -> Void
    let onWon: () -> Void
    let onLost: () -> Void
    let onOpen: () -> Void
    @Environment(\.neema) private var c

    private var canOpen: Bool { DealsRules.threadKey(deal) != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 8) {
                Button(action: onOpen) {
                    Text(deal.customer.isEmpty ? "Unknown" : deal.customer).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text)
                        .underline(canOpen).lineLimit(1)
                }
                .buttonStyle(.plain)
                .disabled(!canOpen)
                Spacer(minLength: 0)
                Text(Fmt.timeAgo(deal.updatedAt, now: now)).font(NeemaFont.manrope(10)).foregroundColor(c.isDark ? c.muted : Palette.sage300)
            }
            if let t = deal.title, !t.isEmpty {
                Text(t).font(NeemaFont.manrope(11)).foregroundColor(c.isDark ? c.textMid : Palette.slate600).lineLimit(2).padding(.top, 4)
            }
            if let b = deal.blocking, !b.isEmpty {
                Text("⛔ \(b)").font(NeemaFont.manrope(10)).foregroundColor(c.isDark ? Palette.amber500 : Palette.amber700).lineLimit(2).padding(.top, 6)
            }
            if let due = deal.nextAction?.dueAt, !due.isEmpty {
                Text("→ \(deal.nextAction?.owner == "ai" ? "Neema" : "You") · \(DealsRules.fmtDue(due, now: now))")
                    .font(NeemaFont.manrope(10)).foregroundColor(c.isDark ? c.green : Palette.moss600).padding(.top, 4)
            }
            if isEditing {
                editor
            } else {
                // The web shows the guidance as a hover title; on a phone it is printed.
                if let g = deal.guidance, !g.isEmpty {
                    Text("📌 \(g)").font(NeemaFont.manrope(10)).italic().foregroundColor(c.textMid).lineLimit(3).padding(.top, 6)
                }
                FlowLayout(spacing: 8, lineSpacing: 2) {
                    SmallButton(label: (deal.guidance ?? "").isEmpty ? "＋ Guidance" : "📌 Guidance", bg: c.isDark ? c.bg4 : Palette.stone50, fg: slate(c),
                                enabled: !busy, fontSize: 10, hPad: 8, vPad: 4, weight: .regular, action: onEdit)
                    SmallButton(label: "Won", bg: c.isDark ? c.green.opacity(0.15) : Palette.wonBg, fg: c.isDark ? c.green : Palette.moss700,
                                enabled: !busy, fontSize: 10, hPad: 8, vPad: 4, weight: .regular, action: onWon)
                    SmallButton(label: "Lost", bg: c.isDark ? c.bg4 : Palette.stone50, fg: c.isDark ? c.muted : Palette.slate400,
                                enabled: !busy, fontSize: 10, hPad: 8, vPad: 4, weight: .regular, action: onLost)
                }
                .padding(.top, 2)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.isDark ? c.hairline : Palette.stone100))
    }

    private var editor: some View {
        VStack(alignment: .leading, spacing: 4) {
            TextField("e.g. \"No discount on this one\"", text: $guidanceDraft, axis: .vertical)
                .font(NeemaFont.manrope(12)).foregroundColor(c.text).lineLimit(2...5)
                .padding(8)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.border))
                .padding(.top, 8)
            Text("\(guidanceDraft.count)/400").font(NeemaFont.manrope(10)).foregroundColor(c.muted)
            if let e = guidanceError { InlineError(message: e) }
            FlowLayout(spacing: 6, lineSpacing: 2) {
                SmallButton(label: busy ? "Saving…" : "Save", bg: Palette.slate800, fg: .white, enabled: !busy, fontSize: 10, hPad: 10, vPad: 4, action: onSave)
                SmallButton(label: "Cancel", bg: .clear, fg: slate(c), enabled: true, fontSize: 10, hPad: 8, vPad: 4, weight: .regular, action: onCancel)
            }
        }
    }
}

/// Approve with an edited draft. Empty text lets Neema compose from the reason (Android `DraftDialogCard`).
struct DraftDialog: View {
    let action: PlannedAction
    @Binding var text: String
    let busy: Bool
    let checking: Bool
    let error: String?
    let onDismiss: () -> Void
    let onSend: () -> Void
    @Environment(\.neema) private var c

    private var sendLabel: String {
        if checking { return "Checking…" }
        if busy { return "Sending…" }
        return text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "Let Neema write & send" : "Send"
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("Edit before sending").font(NeemaFont.manrope(20, .semibold)).foregroundColor(c.text)
                if let r = action.reason, !r.isEmpty {
                    Text(r).font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                }
                TextField("Leave empty and Neema writes it from the reason", text: $text, axis: .vertical)
                    .font(NeemaFont.manrope(14)).foregroundColor(c.text).lineLimit(4...10)
                    .disabled(busy)
                    .padding(10)
                    .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.bg))
                    .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.border))
                // The dialog stays up until the send is known to have gone: a failure
                // shows its reason here, with every word the operator typed.
                if let e = error { InlineError(message: e, pending: checking) }
                HStack(spacing: 8) {
                    Spacer()
                    Button(action: onDismiss) {
                        Text(busy ? "Close" : "Cancel").font(NeemaFont.manrope(14, .medium)).foregroundColor(c.gold2).padding(.horizontal, 12).frame(minHeight: 44)
                    }
                    Button(action: onSend) {
                        HStack(spacing: 8) {
                            if busy { ProgressView().progressViewStyle(.circular).tint(.white).scaleEffect(0.7) }
                            Text(sendLabel).font(NeemaFont.manrope(14, .medium)).foregroundColor(.white)
                        }
                        .padding(.horizontal, 16).frame(minHeight: 44)
                        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Palette.moss600.opacity(busy ? 0.5 : 1)))
                    }
                    .disabled(busy)
                }
                .padding(.top, 4)
            }
            .padding(24)
        }
        .background(c.bg2)
    }
}
