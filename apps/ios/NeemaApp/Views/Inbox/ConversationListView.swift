import SwiftUI
import NeemaCore

/// Email + SMS hidden for now — no traffic on those channels yet (as on the web).
private let CHANNEL_TABS: [(id: String, label: String, short: String)] = [
    ("all", "All", "All"), ("whatsapp", "WhatsApp", "WA"), ("facebook", "Facebook", "FB"), ("messenger", "Messenger", "MSG"), ("instagram", "Instagram", "IG"),
]
private let ALL_TAB_ACCENT = Palette.amber500
private let ROW_ACCENT = Palette.amber500
private let Green = Palette.moss600

/// Lead-stage row chip palette (matches the sidebar pipeline): bg, fg, border.
private let STAGE_CHIP: [String: (Color, Color, Color)] = [
    "contacted": (Palette.sky100, Palette.sky700, Palette.sky200),
    "qualified": (Palette.amber100, Palette.amber700, Palette.amber200),
    "negotiation": (Palette.violet100, Palette.violet700, Palette.violet200),
    "proposal": (Palette.violet100, Palette.violet700, Palette.violet200),
    "won": (Palette.green100, Palette.green700, Palette.green200),
    "lost": (Palette.red100, Palette.red700, Palette.red200),
]

/// The tab and chip counts from the loaded rows, for the moment before the server's summary answers.
struct LocalBadges {
    let unread: Int, human: Int, yours: Int
    let tags: [String]
    let channels: [String: Int]
}

func localBadges<S: Sequence>(_ all: S, me: String?) -> LocalBadges where S.Element == Conversation {
    var unread = 0, human = 0, yours = 0
    var tags = Set<String>()
    // The chips sum unread MESSAGES; the Unread tab counts conversations.
    var channels: [String: Int] = [:]
    for c in all {
        if c.unread > 0 {
            unread += 1
            channels["all", default: 0] += c.unread
            channels[c.channel, default: 0] += c.unread
        }
        if c.interceptMode == "human" { human += 1; if c.assignedAgentId == me { yours += 1 } }
        tags.formUnion(c.tags)
    }
    return LocalBadges(unread: unread, human: human, yours: yours, tags: tags.sorted(), channels: channels)
}

/// Tabs that share a row: each keeps its whole label, spare room is shared out (`fitWidths`).
struct FitRowLayout: Layout {
    var room: CGFloat
    var spacing: CGFloat = 4

    private func widths(_ subviews: Subviews) -> [CGFloat] {
        let natural = subviews.map { Int($0.sizeThatFits(.unspecified).width.rounded(.up)) }
        let usable = Int(room) - Int(spacing) * max(0, natural.count - 1)
        return fitWidths(natural, room: max(0, usable)).map { CGFloat($0) }
    }

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let w = widths(subviews)
        let h = subviews.map { $0.sizeThatFits(.unspecified).height }.max() ?? 0
        let total = w.reduce(0, +) + spacing * CGFloat(max(0, subviews.count - 1))
        return CGSize(width: max(total, room), height: h)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let w = widths(subviews)
        var x = bounds.minX
        for (i, s) in subviews.enumerated() {
            s.place(at: CGPoint(x: x, y: bounds.midY), anchor: .leading, proposal: ProposedViewSize(width: w[i], height: bounds.height))
            x += w[i] + spacing
        }
    }
}

struct ConversationListView: View {
    @ObservedObject var model: InboxScreenModel
    let perms: InboxPerms
    @Environment(\.neema) private var c
    @FocusState private var searchFocused: Bool

    private var vm: InboxViewModel { model.vm }

    var body: some View {
        let inbox = model.inbox
        let listUi = model.list
        let rows = model.rows
        let summary = inbox.summary
        let f = inbox.filters
        let me = perms.me
        // Badges are counted by the SERVER over every conversation; a count over a
        // paged list would be a count of one page. Fallbacks only before it answers.
        let fallback = summary == nil ? localBadges(inbox.cache.values, me: me) : nil
        let unreadCount = summary?.unread ?? fallback?.unread ?? 0
        let humanCount = summary?.human ?? fallback?.human ?? 0
        let yoursCount = summary?.yours ?? fallback?.yours ?? 0
        let allTags = summary?.tags ?? fallback?.tags ?? []
        let heldIds = vm.selectedHeldIds()

        VStack(spacing: 0) {
            // ── Header ──
            VStack(spacing: 0) {
                HStack(spacing: 0) {
                    Text(listUi.selectMode ? "\(listUi.selected.count) selected" : "Chats")
                        .font(NeemaFont.manrope(14, .semibold)).tracking(-0.14).foregroundColor(c.text)
                    Spacer()
                    if listUi.selectMode {
                        Button { vm.selectAllOrClear() } label: {
                            Text(listUi.selected.count == rows.count && !rows.isEmpty ? "Clear" : "Select all")
                                .font(NeemaFont.manrope(11, .medium)).foregroundColor(c.isDark ? Green : Palette.moss700).padding(8)
                        }
                        Button { vm.exitSelect() } label: {
                            Text("Cancel").font(NeemaFont.manrope(11, .medium)).foregroundColor(c.muted).padding(8)
                        }
                    } else {
                        if humanCount > 0 {
                            let lt = tintOf(Palette.livePill, Palette.livePillInk, dark: c.isDark)
                            Text("\(humanCount) live").font(NeemaFont.manrope(10, .semibold)).foregroundColor(lt.fg).lineLimit(1).fixedSize()
                                .padding(.horizontal, 8).padding(.vertical, 2)
                                .background(Capsule().fill(lt.bg))
                        }
                        Button { vm.enterSelect() } label: {
                            Image(systemName: "checklist").font(.system(size: 16)).foregroundColor(c.muted).frame(width: 36, height: 36)
                        }
                        .accessibilityLabel("Select several (or press and hold a chat)")
                    }
                    Button { vm.toggleFilters() } label: {
                        Image(systemName: "line.3.horizontal.decrease").font(.system(size: 14, weight: .semibold))
                            .foregroundColor(listUi.showFilters ? .white : c.muted)
                            .frame(width: 30, height: 30)
                            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(listUi.showFilters ? Green : .clear))
                    }
                    .accessibilityLabel("Filters")
                }
                Spacer().frame(height: 10)
                // ── All / Unread / Read / Human / Yours ──
                // Every tab keeps its whole label; spare room is shared out (a 320 pt
                // pane shows all five); at a large text size the row scrolls sideways.
                GeometryReader { g in
                    ScrollView(.horizontal, showsIndicators: false) {
                        FitRowLayout(room: g.size.width, spacing: 4) {
                            ForEach(["all", "unread", "read", "human", "yours"], id: \.self) { t in
                                let active = f.tab == t
                                let accent: Color = t == "unread" ? Palette.moss700 : t == "human" ? Palette.amber700 : t == "yours" ? Green : Palette.ink
                                let count = t == "unread" ? unreadCount : t == "human" ? humanCount : t == "yours" ? yoursCount : 0
                                Button { vm.setTab(t) } label: {
                                    HStack(spacing: 3) {
                                        Text(t.prefix(1).uppercased() + t.dropFirst()).font(NeemaFont.manrope(12, .medium))
                                            .foregroundColor(active ? .white : (c.isDark ? c.textMid : Palette.sage500)).lineLimit(1).fixedSize()
                                        if count > 0 {
                                            Text(count > 999 ? "999+" : String(count)).font(NeemaFont.manrope(10, .bold)).foregroundColor(.white).lineLimit(1).fixedSize()
                                                .padding(.horizontal, 5).padding(.vertical, 2)
                                                .background(Capsule().fill(active ? Color.white.opacity(0.25) : accent))
                                        }
                                    }
                                    .padding(.horizontal, 6).padding(.vertical, 2)
                                    .frame(maxWidth: .infinity, minHeight: 28)
                                    .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(active ? accent : (c.isDark ? c.bg3 : Palette.stoneGreen)))
                                }
                                .buttonStyle(.plain)
                                .accessibilityAddTraits(active ? .isSelected : [])
                            }
                        }
                    }
                }
                .frame(height: 30)
                Spacer().frame(height: 8)
                // ── Search (the server searches names, phones and everything said) ──
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").font(.system(size: 13)).foregroundColor(Palette.sage300)
                    ZStack(alignment: .leading) {
                        if listUi.search.isEmpty {
                            Text("Start typing to search").font(NeemaFont.manrope(13)).foregroundColor(c.isDark ? c.muted : Palette.sage300).lineLimit(1)
                        }
                        TextField("", text: Binding(get: { listUi.search }, set: { vm.setSearch($0) }))
                            .font(NeemaFont.manrope(13)).foregroundColor(c.text).tint(Green)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                            .focused($searchFocused)
                            .accessibilityLabel("Search conversations")
                    }
                    if !listUi.search.isEmpty {
                        Button { vm.setSearch("") } label: { Image(systemName: "xmark").font(.system(size: 12, weight: .semibold)).foregroundColor(c.muted).frame(width: 24, height: 24) }
                            .accessibilityLabel("Clear")
                    }
                }
                .padding(.horizontal, 10).padding(.vertical, 4)
                .frame(minHeight: 32)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.isDark ? c.bg3 : Palette.stoneGreen))
                .roundedBorder(c.isDark ? c.border : Palette.hairline2, radius: 8)
                Spacer().frame(height: 10)
                // ── Channel tabs — each in its own brand hue, with unread-message counts ──
                HStack(spacing: 6) {
                    ForEach(CHANNEL_TABS, id: \.id) { tab in
                        let active = f.channel == tab.id
                        let accent = tab.id == "all" ? ALL_TAB_ACCENT : channelStyle(tab.id).color
                        let count = summary?.unreadMessages[tab.id] ?? fallback?.channels[tab.id] ?? 0
                        Button { vm.setChannel(tab.id) } label: {
                            VStack(spacing: 2) {
                                if let d = ChannelIcons.of(tab.id) {
                                    SVGIcon(d: d, size: 14).foregroundColor(active ? .white : accent)
                                } else {
                                    Circle().fill(active ? Color.white : accent).frame(width: 10, height: 10)
                                }
                                Text(tab.short).font(NeemaFont.fixed(8, .bold)).foregroundColor(active ? .white : ink(accent, dark: c.isDark)).lineLimit(1).fixedSize()
                            }
                            .padding(.vertical, 2)
                            .frame(maxWidth: .infinity, minHeight: 40)
                            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(active ? accent : accent.opacity(c.isDark ? 0.14 : 0.08)))
                            .roundedBorder(active ? accent : accent.opacity(0.2), radius: 8)
                            .overlay(alignment: .topTrailing) {
                                if count > 0 {
                                    Text(count > 999 ? "999+" : String(count)).font(NeemaFont.fixed(8, .bold)).foregroundColor(.white).lineLimit(1).fixedSize()
                                        .padding(.horizontal, 3).frame(minWidth: 14, minHeight: 14)
                                        .background(Capsule().fill(active ? Palette.red500 : accent))
                                        .offset(x: 4, y: -4)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(count > 0 ? "\(tab.label), \(count) unread" : tab.label)
                        .accessibilityAddTraits(active ? .isSelected : [])
                    }
                }
                // ── Extra filters: tags, then mode ──
                if listUi.showFilters {
                    Spacer().frame(height: 8)
                    if !allTags.isEmpty {
                        FlowLayout(spacing: 6, lineSpacing: 6) {
                            FilterPill(label: "All tags", active: f.tag == nil) { vm.setTag(nil) }
                            ForEach(allTags, id: \.self) { tag in
                                FilterPill(label: tag, active: f.tag == tag) { vm.setTag(f.tag == tag ? nil : tag) }
                            }
                        }
                        Spacer().frame(height: 6)
                    }
                    FlowLayout(spacing: 6, lineSpacing: 6) {
                        ForEach(["all", "ai", "human", "paused"], id: \.self) { m in
                            FilterPill(label: m.prefix(1).uppercased() + m.dropFirst(), active: f.mode == m) { vm.setMode(m) }
                        }
                    }
                }
            }
            .padding(.leading, 16).padding(.trailing, 16).padding(.top, 12).padding(.bottom, 10)
            Hairline(color: c.isDark ? c.border : Palette.hairline2)

            // Rows on screen but the refresh failed: they stay, and the list says it's showing saved rows.
            if inbox.loadError && !rows.isEmpty {
                HStack(spacing: 8) {
                    Text(inbox.errorText?.hasPrefix("No connection") == true ? "No connection — showing saved conversations." : "Couldn't refresh — showing saved conversations.")
                        .font(NeemaFont.manrope(12)).foregroundColor(c.isDark ? Palette.amber400 : Palette.amber800)
                    Spacer()
                    Button { vm.refresh() } label: { Text("Retry").font(NeemaFont.manrope(12, .semibold)).foregroundColor(Green).padding(.horizontal, 8).padding(.vertical, 4) }
                        .accessibilityLabel("Retry loading conversations")
                }
                .padding(.leading, 16).padding(.trailing, 8).padding(.vertical, 6)
                .background(c.isDark ? Palette.amber950.opacity(0.35) : Palette.amber50)
            }

            // ── The list — paged: the next page loads as it nears its end ──
            ScrollView {
                LazyVStack(spacing: 0) {
                    if rows.isEmpty {
                        VStack(spacing: 4) {
                            if inbox.loading {
                                // A filter's first page is on its way — "none found" would be a claim the server has not made yet.
                                EmptyText(text: "Loading…")
                            } else if inbox.loadError {
                                HStack(spacing: 0) {
                                    EmptyText(text: "Couldn't load — ")
                                    Button { vm.refresh() } label: { Text("Retry").font(NeemaFont.manrope(14, .medium)).foregroundColor(Green).padding(.horizontal, 4).padding(.vertical, 2) }
                                        .accessibilityLabel("Retry loading conversations")
                                }
                                if let e = inbox.errorText {
                                    Text(e).font(NeemaFont.manrope(12)).foregroundColor(Palette.sage400).multilineTextAlignment(.center).padding(.horizontal, 24)
                                }
                            } else if !inbox.freshLoaded {
                                EmptyText(text: "Loading…")
                            } else {
                                EmptyText(text: "No conversations found")
                            }
                        }
                        .frame(maxWidth: .infinity).padding(.vertical, 64)
                    }
                    ForEach(Array(rows.enumerated()), id: \.element.key) { i, g in
                        // The ACTIVE conversation is whichever sibling is open.
                        let act = !model.thread.activeId.isEmpty && g.siblings.contains { $0.id == model.thread.activeId } ? model.thread.activeId : ""
                        ConversationRowView(
                            g: g, activeId: act, me: me, selectMode: listUi.selectMode, picked: listUi.selected.contains(g.key),
                            onOpen: { id in vm.select(id) }, onToggle: { vm.toggleRow(g.key) }, onHold: { vm.enterSelect(g.key) }
                        )
                        .onAppear {
                            if i >= rows.count - 6 && inbox.hasMore && !inbox.loadingMore && !inbox.moreError { vm.loadMore() }
                        }
                    }
                    if !rows.isEmpty && (inbox.loadingMore || inbox.hasMore) {
                        Group {
                            if inbox.loadingMore {
                                Text("Loading more…").font(NeemaFont.manrope(12)).foregroundColor(Palette.sage300)
                            } else if inbox.moreError {
                                Button { vm.loadMore(force: true) } label: { Text("Couldn't load more — Retry").font(NeemaFont.manrope(12)).foregroundColor(Green) }
                            } else {
                                Button { vm.loadMore() } label: { Text("Load more conversations").font(NeemaFont.manrope(12)).foregroundColor(Green) }
                            }
                        }
                        .frame(maxWidth: .infinity).padding(.vertical, 16)
                        // Also tops up a page that doesn't fill the pane (nothing to scroll).
                        .onAppear { if inbox.hasMore && !inbox.loadingMore && !inbox.moreError { vm.loadMore() } }
                    }
                }
            }
            .refreshable {
                vm.refresh()
                try? await Task.sleep(nanoseconds: 700_000_000)
            }

            // ── Bulk action bar — only while selecting ──
            if listUi.selectMode {
                Hairline(color: c.isDark ? c.border : Palette.hairline2)
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 1) {
                        Text(listUi.selected.isEmpty ? "Tap chats to select" : "\(listUi.selected.count) chat\(listUi.selected.count == 1 ? "" : "s") selected")
                            .font(NeemaFont.manrope(11, .medium)).foregroundColor(c.isDark ? c.text : Palette.sageDeep)
                        if !listUi.selected.isEmpty {
                            Text(heldIds.isEmpty ? "none are human-held" : "\(heldIds.count) to hand back to Neema").font(NeemaFont.manrope(10)).foregroundColor(c.muted)
                        }
                    }
                    Spacer()
                    Button { vm.releaseSelected() } label: {
                        Text(listUi.bulkBusy ? "Releasing…" : "Release" + (heldIds.isEmpty ? "" : " \(heldIds.count)"))
                            .font(NeemaFont.manrope(12, .semibold)).foregroundColor(.white)
                            .padding(.horizontal, 12).padding(.vertical, 4).frame(minHeight: 32)
                            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Green.opacity(!listUi.bulkBusy && !heldIds.isEmpty ? 1 : 0.4)))
                    }
                    .disabled(listUi.bulkBusy || heldIds.isEmpty)
                }
                .padding(.horizontal, 12).padding(.vertical, 10)
                .background(c.isDark ? c.bg3 : Palette.sageStrip)
            }
        }
        .background(c.bg2)
    }
}

private struct EmptyText: View {
    let text: String
    @Environment(\.neema) private var c
    var body: some View { Text(text).font(NeemaFont.manrope(14)).foregroundColor(c.isDark ? c.muted : Palette.sage300) }
}

private struct FilterPill: View {
    let label: String
    let active: Bool
    let action: () -> Void
    @Environment(\.neema) private var c
    var body: some View {
        let t = tintOf(Palette.willow100, Palette.willow600, dark: c.isDark)
        Button(action: action) {
            Text(label).font(NeemaFont.manrope(12, .medium)).foregroundColor(active ? .white : t.fg)
                .padding(.horizontal, 10).padding(.vertical, 4)
                .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(active ? Green : t.bg))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(active ? .isSelected : [])
    }
}

struct ConversationRowView: View {
    let g: RowGroup
    let activeId: String
    let me: String?
    let selectMode: Bool
    let picked: Bool
    let onOpen: (String) -> Void
    let onToggle: () -> Void
    let onHold: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        // The row shows the person; the ACTIVE conversation is whichever sibling is open.
        let conv = g.siblings.first { $0.id == activeId } ?? g.rep
        let isActive = g.siblings.contains { $0.id == activeId }
        let hasUnread = g.unread > 0
        let multi = g.siblings.count > 1
        let name = Inbox.inboxName(conv)
        // Human pickup on ANY of this person's channels shows on the row.
        let chipConv = g.siblings.first { $0.interceptMode == "human" } ?? conv
        let stage = g.siblings.compactMap { $0.leadStage?.trimmingCharacters(in: .whitespaces) }.first { !$0.isEmpty }
        let orders = max(0, g.siblings.map { $0.ordersCount }.max() ?? 0)
        let heldHere = g.siblings.contains { $0.interceptMode == "human" }
        let bg: Color = picked ? Palette.pickedRow : isActive ? Palette.activeRow : .clear
        let edge: Color = picked ? Green : isActive ? ROW_ACCENT : hasUnread ? Palette.unreadEdge : .clear
        let shown: Color = bg == .clear ? .clear : (c.isDark ? bg.opacity(0.12) : bg)

        VStack(spacing: 0) {
            HStack(alignment: .top, spacing: 0) {
                Rectangle().fill(edge).frame(width: 3)
                HStack(alignment: .top, spacing: 0) {
                    if selectMode {
                        // As on the web: faded whenever nobody human holds the row — picked or not —
                        // so the Release count never surprises; a little smaller until picked.
                        ZStack {
                            RoundedRectangle(cornerRadius: 6, style: .continuous).fill(picked ? Green : c.bg2)
                            RoundedRectangle(cornerRadius: 6, style: .continuous).stroke(picked ? Green : Palette.sageRim)
                            if picked { Image(systemName: "checkmark").font(.system(size: 10, weight: .bold)).foregroundColor(.white) }
                        }
                        .frame(width: 18, height: 18)
                        .scaleEffect(picked ? 1 : 0.92)
                        .opacity(heldHere ? 1 : 0.45)
                        .padding(.top, 12).padding(.trailing, 12)
                    }
                    ZStack(alignment: .topTrailing) {
                        AvatarView(name: name, url: conv.avatarUrl, size: 38)
                        if let iso = conv.countryIso, iso.count == 2, let u = URL(string: "https://flagcdn.com/w20/\(iso.lowercased()).png") {
                            AsyncImage(url: u) { img in img.resizable().scaledToFill() } placeholder: { Color.clear }
                                .frame(width: 16, height: 12)
                                .clipShape(RoundedRectangle(cornerRadius: 2))
                                .overlay(RoundedRectangle(cornerRadius: 2).stroke(c.bg2))
                                .offset(x: 3, y: -2)
                                .accessibilityLabel(Fmt.countryName(iso))
                        }
                        if hasUnread {
                            Circle().fill(c.bg2).frame(width: 10, height: 10)
                                .overlay(Circle().fill(ROW_ACCENT).padding(2))
                                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                                .offset(x: -2, y: -2)
                        }
                    }
                    .frame(width: 38, height: 38)
                    Spacer().frame(width: 12)
                    VStack(alignment: .leading, spacing: 3) {
                        HStack(spacing: 6) {
                            Text(name).font(NeemaFont.manrope(14, hasUnread ? .semibold : .medium)).foregroundColor(c.text).lineLimit(1)
                            Spacer(minLength: 0)
                            // Repeat-buyer badge: completed (paid) orders.
                            if orders > 0 {
                                Text(orders > 99 ? "99+" : String(orders)).font(NeemaFont.fixed(9, .bold)).foregroundColor(.white).lineLimit(1)
                                    .padding(.horizontal, 4).padding(.vertical, 3.5).frame(minWidth: 16)
                                    .background(Capsule().fill(LinearGradient(colors: [Palette.amber500, Palette.amber600], startPoint: .topLeading, endPoint: .bottomTrailing)))
                                    .accessibilityLabel("\(orders) orders")
                            }
                            Text(g.lastAt.map { Fmt.timeAgo($0) } ?? "").font(NeemaFont.manrope(10, hasUnread ? .semibold : .regular))
                                .foregroundColor(hasUnread ? ink(Palette.moss700, dark: c.isDark) : (c.isDark ? c.muted : Palette.sage300)).lineLimit(1).fixedSize()
                        }
                        FlowLayout(spacing: 4, lineSpacing: 4) {
                            // One chip per linked channel; tapping opens THAT channel's thread.
                            ForEach(g.siblings) { s in
                                let open = s.id == activeId
                                ChannelCodeChip(channel: s.channel, open: open, dotted: multi && s.unread > 0 && !open)
                                    .contentShape(Rectangle())
                                    .onTapGesture { if multi && !selectMode { onOpen(s.id) } }
                                    .accessibilityLabel("Open \(channelStyle(s.channel).label)")
                            }
                            if let st = stage, st != "new" {
                                let (sbg, sfg, sbd) = STAGE_CHIP[st] ?? STAGE_CHIP["contacted"]!
                                let t = tintOf(sbg, sfg, sbd, dark: c.isDark)
                                Text(st.prefix(1).uppercased() + st.dropFirst()).font(NeemaFont.manrope(10, .semibold)).foregroundColor(t.fg).lineLimit(1)
                                    .padding(.horizontal, 6).padding(.vertical, 1)
                                    .background(RoundedRectangle(cornerRadius: 4).fill(t.bg)).roundedBorder(t.border, radius: 4)
                            }
                            if let iso = conv.countryIso, !iso.trimmingCharacters(in: .whitespaces).isEmpty {
                                let ct = tintOf(Palette.orange100, Palette.orange700, Palette.orange300, dark: c.isDark)
                                Text(Fmt.countryName(iso)).font(NeemaFont.manrope(10, .semibold)).foregroundColor(ct.fg).lineLimit(1)
                                    .frame(maxWidth: 110)
                                    .padding(.horizontal, 6).padding(.vertical, 1)
                                    .background(RoundedRectangle(cornerRadius: 4).fill(ct.bg)).roundedBorder(ct.border, radius: 4)
                            }
                            if chipConv.interceptMode != "ai" {
                                InterceptBadge(mode: chipConv.interceptMode)
                                if chipConv.interceptMode == "human", chipConv.assignedAgentId != nil {
                                    let mine = chipConv.assignedAgentId == me
                                    let first = chipConv.assignedAgentName?.split(whereSeparator: { $0.isWhitespace }).first.map(String.init)
                                    Text(mine ? "● Yours" : "🔒 \(first ?? "Agent")").font(NeemaFont.manrope(10, .medium)).lineLimit(1)
                                        .foregroundColor(ink(mine ? Palette.moss700 : Palette.amber600, dark: c.isDark))
                                        .frame(maxWidth: 100)
                                }
                            }
                            if hasUnread {
                                CountCapsule(n: g.unread, color: Green)
                                    .accessibilityLabel("\(g.unread) unread")
                            }
                        }
                        Text((conv.lastMessagePreview?.trimmingCharacters(in: .whitespaces)).flatMap { $0.isEmpty ? nil : $0 } ?? "No messages yet")
                            .font(NeemaFont.manrope(12, hasUnread ? .medium : .regular)).lineLimit(2).lineSpacing(2)
                            .foregroundColor(hasUnread ? (c.isDark ? c.textMid : Palette.sageDeep) : c.muted)
                    }
                }
                .padding(.leading, 13).padding(.trailing, 16).padding(.vertical, 12)
            }
            .background(shown)
            .contentShape(Rectangle())
            // Press and hold to start selecting — the WhatsApp gesture.
            .onTapGesture { if selectMode { onToggle() } else { onOpen(conv.id) } }
            .onLongPressGesture { if !selectMode { onHold() } }
            .accessibilityElement(children: .combine)
            .accessibilityAddTraits(.isButton)
            .accessibilityLabel("\(name), \(hasUnread ? "\(g.unread) unread, " : "")\(conv.lastMessagePreview ?? "")")
            Hairline(color: c.isDark ? c.border : Palette.sageRule)
        }
    }
}
