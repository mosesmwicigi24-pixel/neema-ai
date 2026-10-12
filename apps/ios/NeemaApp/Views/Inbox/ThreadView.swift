import SwiftUI
import NeemaCore

// ═══════════════════════════ Thread pane ═══════════════════════════

/// The thread's header actions (web `<Btn>`s): one state-changing action stays pinned beside the badges on a phone.
struct HeaderAction: Identifiable {
    let id: String
    let label: String
    let emoji: String
    var busyKey: String? = nil
    /// The web Btn variant: primary (amber) vs secondary.
    var primary: Bool = false
    /// Phone: the one state-changing action kept one tap away beside the badges.
    var pin: Bool
    var danger: Bool = false
    let action: () -> Void

    init(_ id: String, _ label: String, _ emoji: String, busyKey: String? = nil, primary: Bool = false, pin: Bool? = nil, danger: Bool = false, action: @escaping () -> Void) {
        self.id = id; self.label = label; self.emoji = emoji; self.busyKey = busyKey; self.primary = primary; self.pin = pin ?? primary; self.danger = danger; self.action = action
    }
}

/// What the message rows can ask of the screen.
struct ThreadCallbacks {
    let onView: (Viewer) -> Void
    let onRecover: (String, @escaping @MainActor (Recovery) -> Void) -> Void
    let onReply: (ThreadMsg) -> Void
    let fetchVideo: (String, String?) async -> String?
    let onRetry: () -> Void
    let onLoadOlder: () -> Void
    /// A "Not sent" bubble: send it again / take the words back to edit.
    let onRetrySend: (String) -> Void
    let onEditFailed: (String) -> Void
    /// A call card's "Use as reply": the AI's follow-up into the composer (never sent by itself).
    let onUseAsReply: (String) -> Void
}

struct ThreadPaneView: View {
    @ObservedObject var model: InboxScreenModel
    let conv: Conversation
    let perms: InboxPerms
    let wide: Bool
    let roomy: Bool
    /// The thread has room for its actions beside the badges (no second row of buttons).
    let roomyHeader: Bool
    let brokenVideos: Set<String>
    let onView: (Viewer) -> Void
    let onProfile: (() -> Void)?
    let onActivity: (() -> Void)?
    let onAsk: () -> Void
    let onAnswer: () -> Void
    let onInvite: () -> Void
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    private var vm: InboxViewModel { model.vm }

    var body: some View {
        let thread = model.thread
        let composer = model.composer
        let can = threadControls(conv, perms)
        let inline = wide && roomyHeader
        var actions: [HeaderAction] = []
        if can.intercept { actions.append(HeaderAction("intercept", "Intercept", "⚡", busyKey: "intercept", primary: true) { vm.intercept(conv.id) }) }
        if can.pickUp { actions.append(HeaderAction("pickup", "Pick up", "🙋", busyKey: "intercept", primary: true) { vm.intercept(conv.id) }) }
        if can.release { actions.append(HeaderAction("release", "Release", "↩", busyKey: "release", pin: !actions.contains { $0.pin }) { vm.release(conv.id) }) }
        if can.pause { actions.append(HeaderAction("pause", "Pause", "⏸", busyKey: "pause") { vm.pause(conv.id) }) }
        if can.resume { actions.append(HeaderAction("resume", "Resume", "▶", busyKey: "release", primary: true, pin: !actions.contains { $0.pin }) { vm.release(conv.id) }) }
        if can.transfer { actions.append(HeaderAction("transfer", inline ? "" : "Transfer", "⇄") { vm.showTransfer(true) }) }
        if can.note { actions.append(HeaderAction("note", inline ? "" : "Add note", "📝") { vm.showNote(true) }) }
        if can.clearHistory { actions.append(HeaderAction("clear", inline ? "" : "Clear history", "🗑️", danger: true) { vm.showClear(true) }) }
        let siblings: [Conversation] = conv.personId == nil ? [conv] :
            model.inbox.cache.values.filter { $0.personId == conv.personId }
                .sorted { a, b in (Inbox.CHAN_ORDER.firstIndex(of: a.channel) ?? 99) < (Inbox.CHAN_ORDER.firstIndex(of: b.channel) ?? 99) }
        let threadLang = Inbox.threadLang(of: thread)
        let txOn = Inbox.txOn(thread, composer)
        let digits = Inbox.phoneDigits(conv) ?? ""
        // CustomerSidebar's rule: the invite exists only for a person with a real
        // 7–15-digit phone on their profile and no WhatsApp thread yet.
        let invitePhone = Inbox.inviteTarget(thread.reach, conv.id)
        var menu: [(String, () -> Void)] = []
        // Shortcuts to the customer panel's Ask Neema / Answer-via-Neema boxes and
        // Invite button (CustomerSidebar.tsx), which the web shows to everyone.
        menu.append(("🔎 Ask Neema", onAsk))
        menu.append(("💬 Neema delivers a team answer", onAnswer))
        if invitePhone != nil { menu.append(("🟢 Invite to WhatsApp", onInvite)) }
        if let a = onActivity { menu.append(("🕘 Activity log", a)) }
        let callbacks = ThreadCallbacks(
            onView: onView,
            onRecover: { id, done in vm.recoverMedia(id, onDone: done) },
            onReply: { vm.beginReplyTo($0) },
            fetchVideo: { postId, ch in try? await app.container.api.conversations.postVideo(postId: postId, channel: ch) },
            onRetry: { let id = vm.thread.value.activeId; if !id.isEmpty { vm.loadMessages(id) } },
            onLoadOlder: { vm.loadOlder() },
            onRetrySend: { vm.retrySend($0) },
            onEditFailed: { vm.editFailed($0) },
            onUseAsReply: { vm.useAsReply($0) }
        )

        GeometryReader { g in
            VStack(spacing: 0) {
                ThreadHeader(
                    conv: conv, siblings: siblings, convBusy: thread.busyFor(conv.id), wide: wide, roomy: roomyHeader,
                    actions: actions, menu: menu,
                    // Regular agents see who holds it; admins never see the lock.
                    locked: can.locked ? (conv.assignedAgentName?.split(whereSeparator: { $0.isWhitespace }).first.map(String.init) ?? "Locked") : nil,
                    showBack: !wide, onBack: { vm.closeThread() },
                    // A shortcut to the customer panel's Call button, which the web shows to
                    // every signed-in agent (CustomerSidebar.tsx) — so no role gate here either.
                    canCall: conv.channel == "whatsapp" && !digits.isEmpty,
                    onCall: { vm.call(waId: digits, name: conv.name) },
                    onProfile: onProfile,
                    onSwitch: { vm.select($0.id) }
                )
                Hairline(color: hairline(c))
                ThreadMessagesView(
                    convId: conv.id, channel: conv.channel,
                    messages: thread.messages[conv.id] ?? [],
                    unreadSnap: thread.unreadSnapshot[conv.id] ?? 0,
                    hasMore: thread.hasMore[conv.id] == true,
                    loading: thread.loading, error: thread.error, loadingOlder: thread.olderLoading == conv.id,
                    errorText: thread.errorText, olderError: thread.olderError == conv.id,
                    recovered: thread.recovered, brokenVideos: brokenVideos, cb: callbacks
                )
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                // Reply box — when the agent owns the conversation, or is admin/superuser.
                if can.composer {
                    Hairline(color: hairline(c))
                    // With the keyboard up (or at a large text size) the composer's extras — the AI
                    // draft, the quote, the window strip — scroll inside it; the text box never leaves.
                    ComposerView(model: model, window: thread.window, humanMode: true, threadLang: threadLang, txOn: txOn)
                        .frame(maxHeight: g.size.height * 0.6)
                } else if can.locked {
                    Hairline(color: hairline(c))
                    HStack(spacing: 8) {
                        Text("🔒").font(.system(size: 16))
                        (Text("Handled by ") + Text(conv.assignedAgentName ?? "another agent").bold().foregroundColor(c.isDark ? Palette.mossNight : Palette.moss600) + Text(" — ask them to release or transfer it to you"))
                            .font(NeemaFont.manrope(12)).foregroundColor(Palette.sage400)
                    }
                    .frame(maxWidth: .infinity).padding(16)
                    .background(c.isDark ? c.bg2 : Palette.sageBanner)
                }
            }
        }
        .background(c.isDark ? c.bg : Palette.mist)
    }
}

// ═══════════════════════════ Header ═══════════════════════════

struct ThreadHeader: View {
    let conv: Conversation
    let siblings: [Conversation]
    let convBusy: String
    let wide: Bool
    /// Beside other panes with room to spare: every action inline (icon-only ones in the top row).
    let roomy: Bool
    let actions: [HeaderAction]
    let menu: [(String, () -> Void)]
    let locked: String?
    let showBack: Bool
    let onBack: () -> Void
    let canCall: Bool
    let onCall: () -> Void
    let onProfile: (() -> Void)?
    let onSwitch: (Conversation) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let name = Inbox.inboxName(conv)
        let inline = wide && roomy
        let items: [(String, () -> Void)] = (inline ? [] : actions.filter { !$0.pin }.map { a in ("\(a.emoji) \(a.label)", a.action) }) + menu
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 0) {
                if showBack {
                    Button(action: onBack) { Image(systemName: "chevron.left").font(.system(size: 18, weight: .semibold)).foregroundColor(c.muted).frame(width: 44, height: 44) }
                        .accessibilityLabel("Back")
                } else {
                    Spacer().frame(width: 8)
                }
                AvatarView(name: name, url: conv.avatarUrl, size: 32)
                Spacer().frame(width: 10)
                VStack(alignment: .leading, spacing: 1) {
                    Text(name).font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.text).lineLimit(1)
                    // A Meta thread has no wa_id (its key is a PSID): no empty second line under the name.
                    let h = Inbox.inboxHandle(conv)
                    if !h.trimmingCharacters(in: .whitespaces).isEmpty {
                        Text(h).font(Inbox.isWebVisitor(conv.waId) ? NeemaFont.manrope(12) : NeemaFont.mono(12)).foregroundColor(Palette.sage300).lineLimit(1)
                    }
                }
                Spacer(minLength: 4)
                // A roomy tablet thread: the icon-only actions (transfer, note, clear)
                // sit up here with the call and profile buttons, so the badge row
                // below never wraps into a second line of buttons.
                if inline {
                    ForEach(actions.filter { $0.label.isEmpty }) { a in HeaderButton(action: a, convBusy: convBusy).padding(.horizontal, 2) }
                }
                if canCall {
                    Button(action: onCall) { Image(systemName: "phone.fill").font(.system(size: 17)).foregroundColor(ChannelColors.whatsApp).frame(width: 44, height: 44) }
                        .accessibilityLabel("Call on WhatsApp")
                }
                if let p = onProfile {
                    Button(action: p) { Image(systemName: "person.fill").font(.system(size: 17)).foregroundColor(Palette.moss700).frame(width: 44, height: 44) }
                        .accessibilityLabel("View customer profile")
                }
                if !items.isEmpty {
                    Menu {
                        ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                            Button(item.0, action: item.1)
                        }
                    } label: {
                        Image(systemName: "ellipsis").font(.system(size: 17, weight: .semibold)).foregroundColor(c.muted).frame(width: 44, height: 44)
                    }
                    .accessibilityLabel("More")
                }
            }
            HStack(alignment: .center, spacing: 8) {
                FlowLayout(spacing: 6, lineSpacing: 6) {
                    InterceptBadge(mode: conv.interceptMode)
                    // The web shows "→ agent" only on large screens (hidden lg:block).
                    if wide, conv.assignedAgentId != nil, let n = conv.assignedAgentName {
                        Text("→ \(n)").font(NeemaFont.manrope(12)).foregroundColor(Palette.sage300)
                    }
                    if let l = locked {
                        Text("🔒 \(l)").font(NeemaFont.manrope(12)).foregroundColor(c.isDark ? c.muted : Palette.stone400)
                            .padding(.horizontal, 8).padding(.vertical, 3)
                            .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(c.isDark ? c.bg3 : Palette.stone100))
                    }
                    // The same person on other channels: one tap switches the thread.
                    if siblings.count > 1 {
                        ForEach(siblings) { s in
                            let open = s.id == conv.id
                            ChannelCodeChip(channel: s.channel, open: open)
                                .contentShape(Rectangle())
                                .onTapGesture { if !open { onSwitch(s) } }
                                .accessibilityLabel("Open the \(channelStyle(s.channel).label) thread")
                        }
                    }
                    if inline {
                        ForEach(actions.filter { !$0.label.isEmpty }) { a in HeaderButton(action: a, convBusy: convBusy) }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                // Phone / a narrow thread: the one state-changing action stays one tap away, beside the badges.
                if !inline, let a = actions.first(where: { $0.pin }) {
                    HeaderButton(action: a, convBusy: convBusy)
                }
            }
            .padding(.leading, 8)
        }
        .padding(.horizontal, 8).padding(.vertical, 8)
        .background(c.bg2)
    }
}

private struct HeaderButton: View {
    let action: HeaderAction
    let convBusy: String
    var body: some View {
        WebBtn(
            label: action.label.isEmpty ? nil : action.label,
            variant: action.primary ? .primary : action.danger ? .danger : .secondary,
            lead: action.emoji,
            // Exactly-once: while one control is in flight every control that changes state waits.
            enabled: action.busyKey == nil || convBusy.isEmpty,
            busy: action.busyKey != nil && convBusy == action.busyKey,
            action: action.action
        )
        .accessibilityLabel(action.label.isEmpty ? action.id : action.label)
    }
}

// ═══════════════════════════ Thread list ═══════════════════════════

extension View {
    /// A list that grows upward: the scroll view and each row are flipped, so the newest row sits at the bottom
    /// and prepending older pages never moves the reader (Compose's `reverseLayout`).
    func flipped() -> some View { scaleEffect(x: 1, y: -1) }
}

struct ThreadMessagesView: View {
    let convId: String
    let channel: String?
    let messages: [ThreadMsg]
    let unreadSnap: Int
    let hasMore: Bool
    let loading: Bool
    let error: Bool
    let loadingOlder: Bool
    /// Why the thread failed to load (no connection, server down…).
    let errorText: String?
    /// The older page failed: offer a tap instead of waiting on a scroll that can't come.
    let olderError: Bool
    let recovered: [String: String]
    let brokenVideos: Set<String>
    let cb: ThreadCallbacks
    @Environment(\.neema) private var c

    var body: some View {
        let sorted = ThreadRows.sort(messages)
        let rows = ThreadRows.build(sorted, unreadSnap: unreadSnap)
        ZStack(alignment: .top) {
            (c.isDark ? c.bg : Palette.mist).ignoresSafeArea(edges: .bottom)
            if loading && messages.isEmpty {
                ProgressView().tint(c.gold).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if error && messages.isEmpty {
                VStack(spacing: 8) {
                    Text("Couldn't load this conversation.").font(NeemaFont.manrope(14)).foregroundColor(Palette.amber700)
                    if let e = errorText, e != "Couldn't load this conversation." {
                        Text(e).font(NeemaFont.manrope(12)).foregroundColor(c.muted).multilineTextAlignment(.center).padding(.horizontal, 24)
                    }
                    Button(action: cb.onRetry) {
                        Text("Try again").font(NeemaFont.manrope(12, .medium)).foregroundColor(.white).padding(.horizontal, 16).padding(.vertical, 8)
                            .background(Capsule().fill(Palette.amber500))
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if messages.isEmpty {
                Text("No messages yet").font(NeemaFont.manrope(14)).foregroundColor(Palette.sagePale).frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                ScrollView {
                    LazyVStack(spacing: 8) {
                        ForEach(rows.reversed()) { row in
                            ThreadRowView(row: row, channel: channel, recovered: recovered, brokenVideos: brokenVideos, cb: cb)
                                .flipped()
                        }
                        if hasMore {
                            Group {
                                if loadingOlder {
                                    ProgressView().tint(Palette.sagePale).scaleEffect(0.8)
                                } else if olderError {
                                    Button(action: cb.onLoadOlder) {
                                        Text("Couldn't load older messages — tap to retry").font(NeemaFont.manrope(11, .medium)).foregroundColor(Palette.amber700)
                                            .padding(.horizontal, 10).padding(.vertical, 4)
                                    }
                                    .accessibilityLabel("Retry loading older messages")
                                } else {
                                    Text("↑ scroll for older messages").font(NeemaFont.manrope(10)).foregroundColor(Palette.stone400)
                                }
                            }
                            .frame(maxWidth: .infinity).padding(4)
                            .flipped()
                            .onAppear { if !olderError && !loadingOlder { cb.onLoadOlder() } }
                        }
                    }
                    .padding(.horizontal, 12).padding(.vertical, 12)
                }
                .flipped()
            }
            if loading && !messages.isEmpty {
                ProgressView().progressViewStyle(.linear).tint(c.gold).frame(height: 2)
            }
        }
    }
}

private struct ThreadRowView: View {
    let row: ThreadRow
    let channel: String?
    let recovered: [String: String]
    let brokenVideos: Set<String>
    let cb: ThreadCallbacks
    @Environment(\.neema) private var c

    var body: some View {
        switch row {
        case .newDivider(let n):
            DividerPill(text: "\(n) new \(n == 1 ? "message" : "messages")", line: Palette.moss700.opacity(0.3), bg: Palette.willow100, fg: Palette.moss700)
        case .postHead(let ctx, _):
            HStack {
                CommentContextCard(ctx: ctx, inbound: true, channel: channel, heading: "Your post — their comments below", onView: cb.onView, fetchVideo: cb.fetchVideo)
                    .frame(maxWidth: 420)
                Spacer(minLength: 0)
            }
            .padding(.top, 8)
        case .escalated(let msg, let reason):
            let t = tint(Palette.amber50, Palette.amber700, Palette.amber200, dark: c.isDark)
            let rule = c.isDark ? t.border : Palette.amber200
            VStack(spacing: 4) {
                HStack(spacing: 0) {
                    Rectangle().fill(rule).frame(height: 1)
                    HStack(spacing: 6) {
                        Circle().fill(Palette.amber400).frame(width: 6, height: 6)
                        (Text("Escalated to agent") + (msg.createdAt != nil ? Text(" · \(Fmt.timeAgo(msg.createdAt))").font(NeemaFont.manrope(9)).foregroundColor(ink(Palette.amber600, dark: c.isDark)) : Text("")))
                            .font(NeemaFont.manrope(10, .semibold)).foregroundColor(t.fg).multilineTextAlignment(.center)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background(Capsule().fill(t.bg)).overlay(Capsule().stroke(t.border))
                    .padding(.horizontal, 8)
                    Rectangle().fill(rule).frame(height: 1)
                }
                Text(reason).font(NeemaFont.manrope(10)).foregroundColor(ink(Palette.amber600, dark: c.isDark)).multilineTextAlignment(.center).lineSpacing(2)
                    .frame(maxWidth: 360)
            }
            .padding(.vertical, 4)
        case .flag(let msg):
            DividerPill(text: "🚩 Flagged: Needs Attention" + (msg.createdAt.map { " · \(Fmt.timeAgo($0))" } ?? ""), line: Palette.red100, bg: Palette.red100, fg: Palette.red700)
        case .pill(let msg):
            let (bg, bd, fg): (Color, Color, Color) = {
                switch msg.eventKind {
                case "release": return (Palette.blue50, Palette.blue200, Palette.blue700)
                case "transfer": return (Palette.indigo50, Palette.indigo200, Palette.indigo700)
                case "approve_draft": return (Palette.green50, Palette.green200, Palette.green700)
                default: return (Palette.stone100, Palette.stone200, Palette.stone600)
                }
            }()
            DividerPill(text: msg.body + (msg.createdAt.map { " · \(Fmt.timeAgo($0))" } ?? ""), line: Palette.stone200, bg: bg, fg: fg, border: bd)
        case .note(let msg):
            let t = tint(Palette.amber50, Palette.amber800, Palette.amber200, dark: c.isDark)
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text("📝").font(.system(size: 12))
                    Text("INTERNAL NOTE").font(NeemaFont.manrope(10, .semibold)).tracking(0.5).foregroundColor(ink(Palette.amber600, dark: c.isDark))
                }
                Text(msg.body).font(NeemaFont.manrope(12)).lineSpacing(3).foregroundColor(t.fg).textSelection(.enabled)
                HStack(spacing: 4) {
                    if msg.sendState == "sending" { Image(systemName: "clock").font(.system(size: 9)).foregroundColor(Palette.amber400) }
                    Text(msg.sendState == "sending" ? "Saving…" : (msg.createdAt.map { Fmt.timeAgo($0) } ?? "")).font(NeemaFont.manrope(10)).foregroundColor(Palette.amber400)
                }
                if msg.sendState == "failed" { FailedLine(msg: msg, color: Palette.red700, cb: cb) }
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .frame(maxWidth: 560)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(t.bg))
            .dashedBorder(t.border, radius: 12)
            .frame(maxWidth: .infinity)
        case .bubble(let msg, let album):
            MessageBubble(msg: msg, album: album, channel: channel, recovered: recovered, brokenVideos: brokenVideos, cb: cb)
        case .call(let msg):
            ThreadCallEventView(msg: msg, onUseAsReply: cb.onUseAsReply)
        }
    }
}

private struct DividerPill: View {
    let text: String
    let line: Color
    let bg: Color
    let fg: Color
    var border: Color? = nil
    @Environment(\.neema) private var c

    var body: some View {
        let t = tint(bg, fg, border ?? bg, dark: c.isDark)
        let rule = c.isDark ? c.border : line
        HStack(spacing: 0) {
            Rectangle().fill(rule).frame(height: 1)
            Text(text).font(NeemaFont.manrope(10, .semibold)).foregroundColor(t.fg).lineLimit(3).multilineTextAlignment(.center)
                .padding(.horizontal, 10).padding(.vertical, 4)
                .frame(maxWidth: 280)
                .background(Capsule().fill(t.bg))
                .overlay(Capsule().stroke((border != nil || c.isDark) ? t.border : .clear))
                .padding(.horizontal, 8)
            Rectangle().fill(rule).frame(height: 1)
        }
        .padding(.vertical, 2)
    }
}

// ═══════════════════════════ Message bubble ═══════════════════════════

private struct MessageBubble: View {
    let msg: ThreadMsg
    let album: [ThreadMsg]?
    let channel: String?
    let recovered: [String: String]
    let brokenVideos: Set<String>
    let cb: ThreadCallbacks
    @Environment(\.neema) private var c
    @State private var drag: CGFloat = 0

    private let threshold: CGFloat = 55

    var body: some View {
        let inbound = msg.inbound
        let bg: Color = inbound ? (c.isDark ? c.bg2 : .white) : msg.sender == "ai" ? Palette.slate800 : Palette.bubbleGreen
        let fg: Color = inbound ? (c.isDark ? c.text : Palette.ink) : msg.sender == "ai" ? .white : Palette.bubbleInk
        let mediaUrl = recovered[msg.id] ?? msg.mediaUrl
        let isMedia = msg.mediaType != nil && msg.mediaType != "note" && mediaUrl != nil
        let shape = BubbleShape(inbound: inbound)
        VStack(spacing: 2) {
            HStack(spacing: 6) {
                if inbound && drag > 8 {
                    Image(systemName: "arrowshape.turn.up.left").font(.system(size: 15)).foregroundColor(c.muted.opacity(min(1, drag / threshold)))
                }
                if !inbound { Spacer(minLength: 0) }
                VStack(alignment: inbound ? .leading : .trailing, spacing: 0) {
                    VStack(alignment: .leading, spacing: 0) {
                        if !inbound {
                            Text((msg.sender == "ai" ? "AI" : (msg.agentName ?? "Agent")).uppercased())
                                .font(NeemaFont.manrope(10, .medium)).tracking(0.5).foregroundColor(fg.opacity(0.7))
                                .padding(.bottom, 4).padding(.leading, isMedia ? 4 : 0)
                        }
                        if let q = msg.replyTo { QuoteStrip(q: q, inbound: inbound, fg: fg) }
                        BubbleBody(msg: msg, mediaUrl: mediaUrl, album: album, channel: channel, inbound: inbound, fg: fg, brokenVideos: brokenVideos, cb: cb)
                        // Reading glass: the English under a foreign message (both directions).
                        if let tr = msg.translation, !tr.trimmingCharacters(in: .whitespaces).isEmpty {
                            let tc: Color = inbound ? Palette.stone500 : msg.sender == "ai" ? Color.white.opacity(0.7) : Palette.bubbleInk.opacity(0.7)
                            let line: Color = inbound ? (c.isDark ? c.border : Palette.stone200) : msg.sender == "ai" ? Color.white.opacity(0.25) : Palette.bubbleInk.opacity(0.25)
                            DashedRule(color: line).padding(.top, 6)
                            HStack(alignment: .top, spacing: 0) {
                                Text("🌐 ").font(NeemaFont.manrope(11))
                                Text(tr).font(NeemaFont.manrope(11)).italic().lineSpacing(3).foregroundColor(tc)
                                if let from = msg.translatedFrom {
                                    Text(" \(from.uppercased())").font(NeemaFont.manrope(9)).tracking(0.5).foregroundColor(tc.opacity(0.6))
                                }
                            }
                            .padding(.top, 4)
                        }
                        HStack(spacing: 8) {
                            if msg.sendState == "failed" {
                                Image(systemName: "exclamationmark.circle").font(.system(size: 11)).foregroundColor(msg.sender == "ai" ? Palette.red300 : Palette.red800)
                                    .accessibilityLabel("Not sent")
                            } else if msg.id.hasPrefix("optimistic-") {
                                Image(systemName: "clock").font(.system(size: 9)).foregroundColor(fg.opacity(0.6)).accessibilityLabel("Sending")
                            }
                            Text(msg.sendState == "sending" ? "Sending…" : msg.sendState == "failed" ? "Not sent" : (msg.createdAt.map { Fmt.timeAgo($0) } ?? ""))
                                .font(NeemaFont.manrope(10, msg.sendState == "failed" ? .semibold : .regular))
                                .foregroundColor(msg.sendState == "failed" ? (msg.sender == "ai" ? Palette.red300 : Palette.red800) : inbound ? (c.isDark ? c.muted : Palette.sage300) : fg.opacity(0.6))
                            // Reply to this message — a threaded quote (native on WhatsApp).
                            if inbound && !msg.body.trimmingCharacters(in: .whitespaces).isEmpty {
                                Button { cb.onReply(msg) } label: {
                                    Text("↩ Reply").font(NeemaFont.manrope(10, .medium)).foregroundColor(c.isDark ? c.textMid : Palette.sage300)
                                }
                                .accessibilityLabel("Reply to this message")
                            }
                        }
                        .padding(.top, 4).padding(.horizontal, isMedia ? 4 : 0)
                        .frame(maxWidth: .infinity, alignment: inbound ? .leading : .trailing)
                    }
                    .padding(isMedia ? EdgeInsets(top: 6, leading: 6, bottom: 6, trailing: 6) : EdgeInsets(top: 10, leading: 16, bottom: 10, trailing: 16))
                    .background(shape.fill(bg))
                    .overlay(Group { if inbound || (c.isDark && msg.sender == "ai") { shape.stroke(c.isDark ? c.border : Palette.hairline2) } })
                    .frame(maxWidth: isMedia ? 360 : 520, alignment: inbound ? .leading : .trailing)
                    .fixedSize(horizontal: false, vertical: true)
                }
                .offset(x: drag)
                if inbound { Spacer(minLength: 0) }
            }
            // Swipe a bubble left→right (like WhatsApp) to reply to it.
            .gesture(
                DragGesture(minimumDistance: 20)
                    .onChanged { v in if inbound && v.translation.width > 0 && abs(v.translation.width) > abs(v.translation.height) { drag = min(v.translation.width, threshold * 1.5) } }
                    .onEnded { _ in if drag > threshold { cb.onReply(msg) }; withAnimation(.easeOut(duration: 0.15)) { drag = 0 } }
            )
            // Under a bubble that didn't go: why, and what to do about it. Nothing is lost.
            if msg.sendState == "failed" {
                FailedLine(msg: msg, color: c.isDark ? Palette.red400 : Palette.red700, cb: cb, end: true).padding(.top, 2)
            }
        }
        .frame(maxWidth: .infinity)
    }
}

/// WhatsApp's bubble: a tight corner on the side it came from.
private struct BubbleShape: Shape {
    let inbound: Bool
    func path(in rect: CGRect) -> Path {
        let r: CGFloat = 16, tight: CGFloat = 4
        let tl = inbound ? tight : r, tr = inbound ? r : tight
        var p = Path()
        p.move(to: CGPoint(x: rect.minX + tl, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX - tr, y: rect.minY))
        p.addArc(center: CGPoint(x: rect.maxX - tr, y: rect.minY + tr), radius: tr, startAngle: .degrees(-90), endAngle: .degrees(0), clockwise: false)
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - r))
        p.addArc(center: CGPoint(x: rect.maxX - r, y: rect.maxY - r), radius: r, startAngle: .degrees(0), endAngle: .degrees(90), clockwise: false)
        p.addLine(to: CGPoint(x: rect.minX + r, y: rect.maxY))
        p.addArc(center: CGPoint(x: rect.minX + r, y: rect.maxY - r), radius: r, startAngle: .degrees(90), endAngle: .degrees(180), clockwise: false)
        p.addLine(to: CGPoint(x: rect.minX, y: rect.minY + tl))
        p.addArc(center: CGPoint(x: rect.minX + tl, y: rect.minY + tl), radius: tl, startAngle: .degrees(180), endAngle: .degrees(270), clockwise: false)
        p.closeSubpath()
        return p
    }
}

/// "Not delivered — … · Retry · Edit" under a send that didn't go.
private struct FailedLine: View {
    let msg: ThreadMsg
    let color: Color
    let cb: ThreadCallbacks
    var end: Bool = false
    @Environment(\.neema) private var c

    var body: some View {
        HStack(spacing: 8) {
            if end { Spacer(minLength: 0) }
            Text(msg.sendError ?? "Not sent").font(NeemaFont.manrope(11)).lineSpacing(2).foregroundColor(color).multilineTextAlignment(end ? .trailing : .leading)
            Button { cb.onRetrySend(msg.id) } label: { Text("Retry").font(NeemaFont.manrope(12, .semibold)).foregroundColor(Palette.moss600).padding(.horizontal, 6).padding(.vertical, 4) }
                .accessibilityLabel("Send it again")
            Button { cb.onEditFailed(msg.id) } label: { Text("Edit").font(NeemaFont.manrope(12, .medium)).foregroundColor(c.muted).padding(.horizontal, 6).padding(.vertical, 4) }
                .accessibilityLabel("Edit the message")
            if !end { Spacer(minLength: 0) }
        }
        .frame(maxWidth: .infinity)
    }
}

/// WhatsApp-style quote: text left, the quoted photo's real thumbnail right.
private struct QuoteStrip: View {
    let q: QuotedRef
    let inbound: Bool
    let fg: Color
    @Environment(\.neema) private var c

    var body: some View {
        let img = q.mediaType == "image" ? q.mediaUrl : nil
        let raw = (q.text ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let text: String = !raw.isEmpty && raw != "[image]" ? raw : img != nil ? "📷 Photo" : q.mediaType.map { "[\($0)]" } ?? "(media)"
        HStack(spacing: 0) {
            Rectangle().fill(inbound ? Palette.moss600 : Color.white.opacity(0.55)).frame(width: 2, height: 40)
            VStack(alignment: .leading, spacing: 1) {
                Text(q.sender == "user" ? "CUSTOMER" : q.sender == "ai" ? "NEEMA" : "YOU").font(NeemaFont.manrope(9, .semibold)).tracking(0.5).foregroundColor(fg.opacity(0.7))
                Text(text).font(NeemaFont.manrope(11)).lineLimit(2).foregroundColor(fg.opacity(0.8))
            }
            .padding(.horizontal, 6).padding(.vertical, 2)
            if let i = img, let u = URL(string: i) {
                AsyncImage(url: u) { im in im.resizable().scaledToFill() } placeholder: { Color.clear }
                    .frame(width: 40, height: 40).clipShape(RoundedRectangle(cornerRadius: 4)).padding(4)
            }
        }
        .background(RoundedRectangle(cornerRadius: 3).fill(inbound ? (c.isDark ? Palette.moss600.opacity(0.16) : Palette.sageQuote) : Color.white.opacity(0.14)))
        .padding(.bottom, 6)
    }
}

private struct BubbleBody: View {
    let msg: ThreadMsg
    let mediaUrl: String?
    let album: [ThreadMsg]?
    let channel: String?
    let inbound: Bool
    let fg: Color
    let brokenVideos: Set<String>
    let cb: ThreadCallbacks
    @Environment(\.neema) private var c

    var body: some View {
        let cctx = msg.commentContext
        let raw = msg.body
        let link: Color = inbound ? (c.isDark ? Palette.blue300 : Palette.blue600) : msg.sender == "ai" ? Palette.blue300 : Palette.emerald900
        let mt = msg.mediaType
        // Our public reply to a comment: threaded (↳ indented) under the comment.
        if cctx?.replyTo != nil {
            HStack(alignment: .top, spacing: 0) {
                Rectangle().fill(Palette.amber300.opacity(0.6)).frame(width: 2)
                Text("↳ ").foregroundColor(Palette.amber400).padding(.leading, 6)
                WaTextView(text: raw, color: fg, link: link)
            }
            .fixedSize(horizontal: false, vertical: true)
        } else if (cctx != nil && (cctx?.title != nil || cctx?.postId != nil)) || raw.hasPrefix("[comment]") {
            // An inbound comment: its post heads the run; the comment itself here.
            let body = raw.replacingOccurrences(of: "^\\[comment\\]\\s*", with: "", options: .regularExpression)
            if !body.isEmpty { WaTextView(text: body, color: fg, link: link) }
        } else if mt == nil || mediaUrl == nil {
            // A media message whose URL never landed: say what was sent, offer to fetch it back.
            if let kind = (mt == "video" ? "video" : mt == "image" ? "image" : nil), mediaUrl == nil {
                MediaFallback(kind: kind, messageId: msg.id, inbound: inbound, onRecover: cb.onRecover, onRecovered: { _ in })
            } else if raw.trimmingCharacters(in: .whitespaces).isEmpty {
                Text("Message can't be displayed (unsupported type) — ask them to resend as text.")
                    .font(NeemaFont.manrope(12)).italic().lineSpacing(3).foregroundColor(Palette.stone400)
            } else {
                WaTextView(text: raw, color: fg, link: link)
            }
        } else if let mu = mediaUrl, let mt = mt {
            if mt == "image" || mt.hasPrefix("image/") {
                if let album = album {
                    let items = album.map { m in AlbumItem(src: m.mediaUrl ?? "", caption: { let t = m.body.trimmingCharacters(in: .whitespaces); return t.isEmpty || t.hasPrefix("[") ? nil : t }()) }
                    AlbumGrid(items: items) { i in cb.onView(.album(items: items, start: i)) }
                } else {
                    // media_caption = the AI's image analysis; text = the customer's own caption.
                    // Legacy rows leaked the analysis into text — never show it as a caption.
                    let analysis = msg.mediaCaption
                    let trimmed = raw.trimmingCharacters(in: .whitespaces)
                    let caption: String? = {
                        if raw.isEmpty || raw.hasPrefix("[") { return nil }
                        if let a = analysis?.trimmingCharacters(in: .whitespaces) {
                            if trimmed == a { return nil }
                            if trimmed.hasPrefix(String(a.prefix(40))) { return nil }
                        }
                        return raw
                    }()
                    ImageBubble(src: mu, analysis: analysis, caption: caption, inbound: inbound, messageId: msg.id, onView: cb.onView, onRecover: cb.onRecover)
                }
            } else if mt == "sticker" {
                RemoteImage(url: mu, contentMode: .fit) {}
                    .frame(width: 120, height: 120)
                    .onTapGesture { cb.onView(.image(url: mu)) }
            } else if mt == "video" || mt.hasPrefix("video/") {
                VideoBubble(src: mu, caption: raw.isEmpty || raw.hasPrefix("[") ? nil : raw, inbound: inbound, messageId: msg.id, brokenIds: brokenVideos, fg: fg, onView: cb.onView, onRecover: cb.onRecover)
            } else if mt == "audio" || mt.hasPrefix("audio/") {
                // inbound: the Whisper transcript lands in text; outbound: text = the AI's
                // spoken reply, media_caption = the cart summary.
                AudioBubble(src: mu, transcription: raw.isEmpty || raw.hasPrefix("[") ? nil : raw, cartText: inbound ? nil : msg.mediaCaption, inbound: inbound)
            } else {
                let fromUrl = mu.split(separator: "/").last.map { String($0).split(separator: "?").first.map(String.init) ?? "" } ?? ""
                let name = (!raw.trimmingCharacters(in: .whitespaces).isEmpty && !raw.hasPrefix("[")) ? raw : (msg.filename ?? (fromUrl.isEmpty ? "file" : fromUrl))
                DocumentTile(url: mu, name: name, inbound: inbound)
            }
        }
    }
}
