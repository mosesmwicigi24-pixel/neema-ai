import SwiftUI
import NeemaCore

/// The inbox — a port of components/views/ConversationsView.tsx (Android
/// `ConversationsScreen`). Phone: the list, and a full-screen thread over it
/// (the shell's bars hide while a thread is open). Wide: list and thread side
/// by side, with the activity log and the customer panel as collapsible side
/// panes when the window is roomy enough.
struct InboxScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.inboxScreen {
            // The panes follow the room the inbox really has (the window minus the
            // navigation): a 13" iPad full screen, Split View, Slide Over and a
            // Stage Manager window each get their own arrangement (Adaptive.swift).
            GeometryReader { g in
                InboxBody(model: m, panes: inboxPanes(contentWidth: Int(g.size.width)))
            }
        } else {
            Color.clear
        }
    }
}

/// What the inbox shows over its panes — one at a time.
enum InboxSheet: Identifiable {
    case customer, activity, transfer, note, clear, ask, answer, invite
    var id: Int { hashValue }
}

struct ViewerItem: Identifiable {
    let id = UUID()
    let viewer: Viewer
}

struct InboxBody: View {
    @ObservedObject var model: InboxScreenModel
    let panes: InboxPanes
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @State private var viewer: ViewerItem?
    @State private var brokenVideos: Set<String> = []
    // The panes a phone or a tablet had open come back after iOS reclaims the app (Android rememberSaveable).
    @SceneStorage("inbox.customerOpen") private var customerOpen = true      // wide side pane (open by default)
    @SceneStorage("inbox.customerSheet") private var customerSheet = false    // phone / narrow wide
    @SceneStorage("inbox.activitySheet") private var activitySheet = false
    // The reach-out dialogs remember WHICH conversation they were opened for: a
    // deep link or a notification tap that switches threads closes them, so a
    // team answer or an invite can never go to the next customer opened.
    @State private var askFor: String?
    @State private var answerFor: String?
    @State private var inviteFor: String?

    private var vm: InboxViewModel { model.vm }
    private var wide: Bool { panes.twoPane }
    /// The customer panel docks beside the thread only when the thread keeps its room.
    private var roomy: Bool { panes.customer == .docked }
    private var active: Conversation? { model.inbox.cache[model.thread.activeId] }
    private var phoneThread: Bool { !wide && model.thread.threadOpen && active != nil }

    var body: some View {
        let perms = app.inboxPerms
        ZStack {
            if !wide {
                if phoneThread, let a = active {
                    threadPane(a, perms)
                } else {
                    ConversationListView(model: model, perms: perms)
                }
            } else {
                HStack(spacing: 0) {
                    ConversationListView(model: model, perms: perms)
                        .frame(width: CGFloat(panes.listWidth))
                    Rectangle().fill(hairline(c)).frame(width: 1)
                    Group {
                        if let a = active { threadPane(a, perms) } else { emptyThread }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    // The activity log's rail and the customer panel dock only while the
                    // thread keeps its room; the log docks open only if it still does.
                    if roomy, let a = active {
                        if panes.activityDocks {
                            ActivityPane(events: model.thread.activity, open: model.thread.activityOpen, width: CGFloat(panes.activityWidth)) { vm.setActivityOpen($0) }
                        } else {
                            SideRail(label: "Activity", count: model.thread.activity.count) { activitySheet = true; vm.setActivityOpen(true) }
                        }
                        if customerOpen {
                            Rectangle().fill(hairline(c)).frame(width: 1)
                            CustomerPanelView(
                                conversation: a,
                                onClose: { customerOpen = false },
                                onOpenIdentity: { ch, ext in vm.openIdentity(channel: ch, externalId: ext) },
                                onNameChange: { w, n in vm.renameCustomer(waId: w, newName: n) }
                            )
                            .frame(width: CGFloat(panes.customerWidth))
                        } else {
                            SideRail(label: "Customer", flipArrow: true) { customerOpen = true }
                        }
                    }
                }
                // Tablet windows where the thread needs the room: the customer panel and
                // the activity log slide over the thread from the end edge instead of
                // docking — the conversation stays in view beside them.
                if let a = active {
                    SideSheet(open: $customerSheet, width: CGFloat(panes.customerWidth), title: "Customer profile") {
                        CustomerPanelView(
                            conversation: a,
                            onClose: { customerSheet = false },
                            onOpenIdentity: { ch, ext in customerSheet = false; vm.openIdentity(channel: ch, externalId: ext) },
                            onNameChange: { w, n in vm.renameCustomer(waId: w, newName: n) },
                            hideHeader: true
                        )
                    }
                    SideSheet(open: activitySheetBinding, width: CGFloat(max(300, panes.activityWidth)), title: "Activity log") {
                        Text("ACTIVITY LOG").font(NeemaFont.manrope(11, .semibold)).tracking(1).foregroundColor(Palette.sage300)
                            .padding(.horizontal, 16).padding(.vertical, 12)
                        ActivityList(events: model.thread.activity)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg2)
        // The shell hides its bars while a thread owns the phone screen.
        .onAppear { app.immersive = phoneThread; autoSelect() }
        .onDisappear { app.immersive = false }
        .onChange(of: phoneThread) { app.immersive = $0 }
        .onChange(of: wide) { _ in autoSelect() }
        .onChange(of: model.rows.isEmpty) { _ in autoSelect() }
        .onChange(of: model.thread.activeId) { id in
            if id.isEmpty { autoSelect(); return }
            if askFor != nil && askFor != id { askFor = nil }
            if answerFor != nil && answerFor != id { answerFor = nil }
            if inviteFor != nil && inviteFor != id { inviteFor = nil }
        }
        // Rotating or resizing into room for the docked pane: the slide-over one
        // closes (the docked one shows it) — never the panel twice. The activity
        // log that was open over the thread stays open, docked.
        .onChange(of: roomy) { r in if r && wide { customerSheet = false } }
        .onChange(of: panes.activityDocks) { docks in
            if docks && activitySheet { activitySheet = false; vm.setActivityOpen(true) }
        }
        .sheet(item: sheetBinding) { which in sheetContent(which) }
        .fullScreenCover(item: $viewer) { item in
            ViewerScreen(viewer: item.viewer, onClose: { viewer = nil }, onVideoError: { id in if let id = id { brokenVideos.insert(id) } })
        }
    }

    /// Wide: the first conversation opens on its own (the web's auto-select).
    private func autoSelect() {
        if wide && model.thread.activeId.isEmpty, let first = model.rows.first { vm.select(first.rep.id, openThread: false) }
    }

    private var activitySheetBinding: Binding<Bool> {
        Binding(get: { activitySheet }, set: { v in activitySheet = v; if !v { vm.setActivityOpen(false) } })
    }

    private var emptyThread: some View {
        VStack(spacing: 8) {
            Text("💬").font(.system(size: 36))
            Text("Select a conversation").font(NeemaFont.manrope(14)).foregroundColor(c.isDark ? c.muted : Palette.sagePale)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.isDark ? c.bg : Palette.slate50)
    }

    private func threadPane(_ conv: Conversation, _ perms: InboxPerms) -> some View {
        ThreadPaneView(
            model: model, conv: conv, perms: perms, wide: wide, roomy: roomy, roomyHeader: panes.roomyThread,
            brokenVideos: brokenVideos,
            onView: { viewer = ViewerItem(viewer: $0) },
            onProfile: (!wide || !roomy) ? { customerSheet = true } : nil,
            onActivity: !panes.activityRail ? { activitySheet = true; vm.setActivityOpen(true) } : nil,
            onAsk: { askFor = conv.id }, onAnswer: { answerFor = conv.id }, onInvite: { inviteFor = conv.id }
        )
    }

    // ── Sheets and dialogs ──────────────────────────────────────────────────

    private var sheet: InboxSheet? {
        let d = model.dialogs
        if d.transfer { return .transfer }
        if d.note { return .note }
        if d.clearConfirm { return .clear }
        if let a = active {
            if askFor == a.id { return .ask }
            if answerFor == a.id { return .answer }
            if inviteFor == a.id { return .invite }
            if !wide && customerSheet { return .customer }
            if !wide && activitySheet { return .activity }
        }
        return nil
    }

    private var sheetBinding: Binding<InboxSheet?> {
        Binding(get: { sheet }, set: { v in if v == nil { dismiss(sheet) } })
    }

    private func dismiss(_ s: InboxSheet?) {
        switch s {
        case .transfer: vm.showTransfer(false)
        case .note: vm.showNote(false)
        case .clear: vm.showClear(false)
        case .ask: askFor = nil
        case .answer: answerFor = nil
        case .invite: inviteFor = nil
        case .customer: customerSheet = false
        case .activity: activitySheet = false; vm.setActivityOpen(false)
        case nil: break
        }
    }

    @ViewBuilder
    private func sheetContent(_ which: InboxSheet) -> some View {
        switch which {
        case .customer:
            if let a = active {
                VStack(spacing: 0) {
                    HStack {
                        Text("Customer Profile").font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text)
                        Spacer()
                        Button { customerSheet = false } label: { Image(systemName: "xmark").foregroundColor(Palette.moss600).frame(width: 44, height: 44) }
                            .accessibilityLabel("Close")
                    }
                    .padding(.leading, 16)
                    Hairline(color: hairline(c))
                    CustomerPanelView(
                        conversation: a,
                        onClose: { customerSheet = false },
                        onOpenIdentity: { ch, ext in customerSheet = false; vm.openIdentity(channel: ch, externalId: ext) },
                        onNameChange: { w, n in vm.renameCustomer(waId: w, newName: n) },
                        hideHeader: true
                    )
                }
                .background(c.bg2)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
            }
        case .activity:
            VStack(alignment: .leading, spacing: 0) {
                Text("ACTIVITY LOG").font(NeemaFont.manrope(11, .semibold)).tracking(1).foregroundColor(Palette.sage300)
                    .padding(.horizontal, 16).padding(.vertical, 8)
                ActivityList(events: model.thread.activity)
            }
            .background(c.bg2)
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        case .transfer:
            TransferDialog(conv: active, busy: active.map { !model.thread.busyFor($0.id).isEmpty } ?? false,
                           onPick: { id, name in vm.transfer(agentId: id, agentName: name) }, onDismiss: { vm.showTransfer(false) })
        case .note:
            NoteDialog(text: model.dialogs.noteText, onText: { vm.setNoteText($0) }, onSave: { vm.saveNote() }, onDismiss: { vm.showNote(false) })
        case .clear:
            ClearHistoryDialog(clearing: model.dialogs.clearing, onClear: { vm.clearHistory() }, onDismiss: { vm.showClear(false) })
        case .ask:
            AskNeemaDialog(vm: vm, onDismiss: { askFor = nil })
        case .answer:
            AnswerViaNeemaDialog(vm: vm, onDismiss: { answerFor = nil })
        case .invite:
            if let a = active {
                InviteDialog(vm: vm, conv: a, profilePhone: Inbox.inviteTarget(model.thread.reach, a.id), onDismiss: { inviteFor = nil })
            }
        }
    }
}

// ═══════════════════════════ Side panes ═══════════════════════════

/// The collapsed side-pane rail ("Activity" / "Customer").
struct SideRail: View {
    let label: String
    var count: Int = 0
    var flipArrow: Bool = false
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Button(action: action) {
            VStack(spacing: 0) {
                Image(systemName: flipArrow ? "chevron.left" : "chevron.right").foregroundColor(Palette.sagePale)
                Spacer().frame(height: 12)
                Text(label.uppercased()).font(NeemaFont.fixed(9, .semibold)).tracking(2)
                    .foregroundColor(c.isDark ? c.muted : Palette.sagePale).fixedSize()
                    .rotationEffect(.degrees(-90))
                    .frame(width: 12, height: 80)
                if count > 0 {
                    Spacer().frame(height: 12)
                    Text(count > 20 ? "20+" : String(count)).font(NeemaFont.fixed(8, .bold)).foregroundColor(Palette.amber700)
                        .frame(width: 18, height: 18)
                        .background(Circle().fill(Palette.amber100))
                        .overlay(Circle().stroke(Palette.amber300))
                }
            }
            .frame(width: 32)
            .frame(maxHeight: .infinity)
            .background(c.bg2)
            .overlay(Rectangle().stroke(hairline(c), lineWidth: 0.5))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Show \(label.lowercased())")
    }
}

/// Activity Log — collapsible side pane (wide).
struct ActivityPane: View {
    let events: [ActivityEvent]
    let open: Bool
    let width: CGFloat
    let setOpen: (Bool) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        if !open {
            SideRail(label: "Activity", count: events.count) { setOpen(true) }
        } else {
            VStack(spacing: 0) {
                HStack {
                    Text("ACTIVITY LOG").font(NeemaFont.manrope(10, .semibold)).tracking(1).foregroundColor(Palette.sage300)
                    Spacer()
                    Button { setOpen(false) } label: { Image(systemName: "chevron.right").foregroundColor(Palette.sage300).frame(width: 28, height: 28) }
                        .accessibilityLabel("Collapse activity log")
                }
                .padding(.leading, 12).padding(.trailing, 4).padding(.top, 8).padding(.bottom, 4)
                Hairline(color: hairline(c))
                ActivityList(events: events)
            }
            .frame(width: width)
            .frame(maxHeight: .infinity)
            .background(c.bg2)
        }
    }
}

private let DOT_COLOR: [String: (Color, Color)] = [
    "escalated": (Palette.amber100, Palette.amber300),
    "flag": (Palette.red100, Palette.red300),
    "intercept": (Palette.purple100, Palette.purple300),
    "release": (Palette.blue100, Palette.blue300),
    "transfer": (Palette.indigo100, Palette.indigo300),
    "approve_draft": (Palette.green100, Palette.green300),
    "pause": (Palette.stone200, Palette.stone400),
    "checkin_planned": (Palette.sky100, Palette.sky300),
    "checkin_sent": (Palette.sky200, Palette.sky400),
    "checkin_vetoed": (Palette.stone100, Palette.stone300),
    "checkin_failed": (Palette.red100, Palette.red300),
    "deal": (Palette.emerald100, Palette.emerald300),
    "promise": (Palette.amber100, Palette.amber300),
    "order": (Palette.green100, Palette.green400),
    "call": (Palette.teal100, Palette.teal300),
    "tool": (Palette.lime50, Palette.lime300),
]

/// The person-scoped journey: pickups, check-ins, deals, orders and calls.
struct ActivityList: View {
    let events: [ActivityEvent]
    @Environment(\.neema) private var c

    var body: some View {
        if events.isEmpty {
            Text("No activity yet — pickups, check-ins, deals, orders and calls will appear here as the journey unfolds.")
                .font(NeemaFont.manrope(11)).foregroundColor(Palette.stone300).multilineTextAlignment(.center).lineSpacing(3)
                .padding(16)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(events.enumerated()), id: \.element.id) { i, e in
                        let (fill, ring) = DOT_COLOR[e.kind] ?? (Palette.stone100, Palette.stone300)
                        HStack(alignment: .top, spacing: 8) {
                            ZStack(alignment: .top) {
                                if i < events.count - 1 {
                                    Rectangle().fill(c.isDark ? c.border : Palette.stone100).frame(width: 1)
                                        .padding(.top, 16)
                                }
                                Circle().fill(fill).overlay(Circle().stroke(ring)).frame(width: 14, height: 14).padding(.top, 2)
                            }
                            .frame(width: 14)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(e.label).font(NeemaFont.manrope(11, .medium)).foregroundColor(c.text)
                                if let d = e.detail, !d.isEmpty { Text(d).font(NeemaFont.manrope(10)).foregroundColor(Palette.sageDetail) }
                                Text(Fmt.timeAgo(e.at)).font(NeemaFont.manrope(10)).foregroundColor(Palette.stone400)
                            }
                            .padding(.bottom, 12)
                        }
                        .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(12)
            }
        }
    }
}

/// A pane sliding over the thread from the end edge, with a scrim (Android `SideSheet`).
struct SideSheet<Content: View>: View {
    @Binding var open: Bool
    let width: CGFloat
    let title: String
    @ViewBuilder let content: () -> Content
    @Environment(\.neema) private var c

    var body: some View {
        ZStack(alignment: .trailing) {
            if open {
                Color.black.opacity(0.4).ignoresSafeArea()
                    .onTapGesture { open = false }
                    .transition(.opacity)
                    .accessibilityLabel("Close \(title.lowercased())")
                VStack(spacing: 0) {
                    HStack {
                        Text(title).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text)
                        Spacer()
                        Button { open = false } label: { Image(systemName: "xmark").foregroundColor(Palette.moss600).frame(width: 44, height: 44) }
                            .accessibilityLabel("Close")
                    }
                    .padding(.leading, 16).padding(.trailing, 4)
                    Hairline(color: hairline(c))
                    content()
                }
                .frame(width: width)
                .frame(maxHeight: .infinity)
                .background(c.bg2)
                .shadow(color: .black.opacity(0.18), radius: 16)
                .transition(.move(edge: .trailing))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: open)
    }
}

// ═══════════════════════════ Dialogs ═══════════════════════════

/// The web's modal: a card with a title, the body, and `flex gap-2` buttons (the action first, then Cancel).
struct WebModal<Content: View, Buttons: View>: View {
    let title: String
    @ViewBuilder let content: () -> Content
    @ViewBuilder let buttons: () -> Buttons
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title).font(NeemaFont.manrope(16, .semibold)).foregroundColor(c.text)
            content()
            HStack(spacing: 8) { buttons() }
        }
        .padding(20)
        .frame(maxWidth: 480, alignment: .leading)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(c.bg2.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

/// The answer / status under the Ask and Answer boxes (CustomerSidebar.tsx).
struct ResultBox: View {
    let text: String
    @Environment(\.neema) private var c
    var body: some View {
        Text(text).font(NeemaFont.manrope(13)).foregroundColor(c.text)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? c.bg3 : Palette.sageResult))
            .roundedBorder(c.isDark ? c.border : Palette.sageResultRim, radius: 8)
            .textSelection(.enabled)
    }
}

/// The web's `<input>` / `<textarea>` in a modal.
struct ModalField: View {
    let placeholder: String
    @Binding var text: String
    var lines: ClosedRange<Int> = 1...1
    var submit: (() -> Void)? = nil
    @Environment(\.neema) private var c

    var body: some View {
        TextField(placeholder, text: $text, axis: lines.upperBound > 1 ? .vertical : .horizontal)
            .lineLimit(lines)
            .font(NeemaFont.manrope(14))
            .foregroundColor(c.text)
            .padding(.horizontal, 12).padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? c.bg3 : Color.white))
            .roundedBorder(c.isDark ? c.border : Palette.gray300, radius: 8)
            .submitLabel(submit == nil ? .done : .send)
            .onSubmit { submit?() }
    }
}

struct TransferDialog: View {
    let conv: Conversation?
    let busy: Bool
    let onPick: (String, String?) -> Void
    let onDismiss: () -> Void
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    var body: some View {
        let available = app.agents.filter { $0.isAvailable && $0.id != conv?.assignedAgentId }
        WebModal(title: "Transfer Conversation") {
            VStack(alignment: .leading, spacing: 12) {
                Text("Select an agent to transfer this conversation to:").font(NeemaFont.manrope(14)).foregroundColor(Palette.sage400)
                ScrollView {
                    VStack(spacing: 8) {
                        ForEach(available) { a in
                            Button { onPick(a.id, a.name) } label: {
                                HStack(spacing: 12) {
                                    AvatarView(name: a.name, url: a.avatarUrl, size: 32)
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(a.name).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text)
                                        Text("\(a.activeConvs) active conversations").font(NeemaFont.manrope(12)).foregroundColor(Palette.sage300)
                                    }
                                    Spacer()
                                }
                                .padding(12)
                                .roundedBorder(hairline(c), radius: 12)
                            }
                            .buttonStyle(.plain)
                            .disabled(busy)
                        }
                        if !app.agents.contains(where: { $0.isAvailable }) {
                            Text("No available agents").font(NeemaFont.manrope(14)).foregroundColor(Palette.sage300)
                                .frame(maxWidth: .infinity).padding(.vertical, 16)
                        }
                    }
                }
                .frame(maxHeight: 280)
            }
        } buttons: {
            WebBtn(label: "Cancel", variant: .outline, size: .md, action: onDismiss)
        }
        .onAppear { app.refetchAgents() }
    }
}

struct NoteDialog: View {
    let text: String
    let onText: (String) -> Void
    let onSave: () -> Void
    let onDismiss: () -> Void

    var body: some View {
        WebModal(title: "Add Note") {
            ModalField(placeholder: "Internal note (not sent to customer)…", text: Binding(get: { text }, set: onText), lines: 4...8)
        } buttons: {
            // <Btn variant="primary"> (amber) then <Btn variant="outline">, medium size, as on the web.
            WebBtn(label: "Save Note", variant: .primary, enabled: !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, size: .md, action: onSave)
            WebBtn(label: "Cancel", variant: .outline, size: .md, action: onDismiss)
        }
    }
}

struct ClearHistoryDialog: View {
    let clearing: Bool
    let onClear: () -> Void
    let onDismiss: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        WebModal(title: "Clear Chat History") {
            Text("This will permanently delete all messages in this conversation. The conversation record and customer profile will be kept. This cannot be undone.")
                .font(NeemaFont.manrope(14)).foregroundColor(c.isDark ? c.textMid : Palette.stone600)
        } buttons: {
            // <Btn variant="danger"> then <Btn variant="outline">, medium size, as on the web.
            WebBtn(label: clearing ? "Clearing…" : "Yes, clear history", variant: .danger, enabled: !clearing, size: .md, action: onClear)
            WebBtn(label: "Cancel", variant: .outline, size: .md, action: onDismiss)
        }
    }
}

/// Ask Neema: the junior fetches — sizes, past orders, call context. Read-only.
struct AskNeemaDialog: View {
    let vm: InboxViewModel
    let onDismiss: () -> Void
    @State private var q = ""
    @State private var answer: String?
    @State private var busy = false

    private func ask() {
        let question = q.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !busy else { return }
        busy = true; answer = nil
        Task { answer = await vm.askNeema(question); busy = false }
    }

    var body: some View {
        WebModal(title: "Ask Neema") {
            VStack(alignment: .leading, spacing: 8) {
                ModalField(placeholder: "Ask Neema… “what were his sizes?”", text: $q, submit: ask)
                if let a = answer { ResultBox(text: a) }
            }
        } buttons: {
            WebBtn(label: "Ask", variant: .primary, enabled: !q.trimmingCharacters(in: .whitespaces).isEmpty, busy: busy, size: .md, action: ask)
            WebBtn(label: "Close", variant: .outline, size: .md, action: onDismiss)
        }
    }
}

/// Answer via Neema: type the confirmed FACTS; Neema delivers them in her own
/// voice and language, and the thread stays in AI mode.
struct AnswerViaNeemaDialog: View {
    let vm: InboxViewModel
    let onDismiss: () -> Void
    @State private var facts = ""
    @State private var status: String?
    @State private var busy = false

    private func deliver() {
        let f = facts.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !f.isEmpty, !busy else { return }
        busy = true; status = nil
        Task {
            let (ok, s) = await vm.answerViaNeema(f)
            status = s
            if ok { facts = "" }
            busy = false
        }
    }

    var body: some View {
        WebModal(title: "Neema delivers") {
            VStack(alignment: .leading, spacing: 8) {
                ModalField(placeholder: "Team answer… “yes, we make it — KES 3,500, ~5 days”", text: $facts, lines: 2...6)
                if let s = status { ResultBox(text: s) }
            }
        } buttons: {
            WebBtn(label: "Neema delivers", variant: .primary, enabled: !facts.trimmingCharacters(in: .whitespaces).isEmpty, busy: busy, size: .md, action: deliver)
            WebBtn(label: "Close", variant: .outline, size: .md, action: onDismiss)
        }
    }
}

/// Send the approved WhatsApp invite template to the phone on the customer's
/// profile; if that fails (not configured, Meta refused), open WhatsApp with a
/// prefilled message instead — CustomerSidebar's invite button, behind one confirmation.
struct InviteDialog: View {
    let vm: InboxViewModel
    let conv: Conversation
    let profilePhone: String?
    let onDismiss: () -> Void
    @EnvironmentObject private var app: AppModel
    @Environment(\.openURL) private var openURL
    @State private var phone = ""
    @State private var busy = false

    private var digits: String { phone.filter { $0.isNumber } }

    private func send() {
        busy = true
        Task {
            let r = await vm.invite(phone: digits, name: conv.name)
            switch r {
            case .sent:
                app.toast("WhatsApp invite sent ✓")
            case .unknown(let message):
                // It may have gone: opening WhatsApp too would invite them twice.
                app.toast(message, .warning)
            case .refused:
                // Fallback: open WhatsApp manually if the template send fails.
                let first = (conv.name ?? "").split(whereSeparator: { $0.isWhitespace }).first.map(String.init) ?? ""
                let text = "Hello\(first.isEmpty ? "" : " \(first)"), this is Bethany House. Continuing our chat here on WhatsApp so we can finalise your order."
                var allowed = CharacterSet.urlQueryAllowed
                allowed.remove(charactersIn: "+&=")
                if let encoded = text.addingPercentEncoding(withAllowedCharacters: allowed), let u = URL(string: "https://wa.me/\(digits)?text=\(encoded)") {
                    openURL(u)
                } else {
                    app.toast("Couldn't send the invite", .error)
                }
            }
            busy = false
            onDismiss()
        }
    }

    var body: some View {
        WebModal(title: "Invite to WhatsApp") {
            VStack(alignment: .leading, spacing: 8) {
                Text("Send this customer a WhatsApp invite (delivers the approved template to their number).")
                    .font(NeemaFont.manrope(13)).foregroundColor(Palette.sage400)
                ModalField(placeholder: "Phone (with country code)", text: $phone)
                    .keyboardType(.phonePad)
            }
        } buttons: {
            WebBtn(label: busy ? "Sending…" : "Send invite", variant: .primary, enabled: !busy && (7...15).contains(digits.count), size: .md, action: send)
            WebBtn(label: "Cancel", variant: .outline, size: .md, action: onDismiss)
        }
        .onAppear { if phone.isEmpty { phone = profilePhone ?? Inbox.phoneDigits(conv) ?? "" } }
    }
}
