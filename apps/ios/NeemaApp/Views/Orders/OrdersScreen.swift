import SwiftUI
import UIKit
import NeemaCore

/// Port of components/views/OrdersView.tsx (Android `OrdersScreen`): revenue
/// header, status cards that double as filters, search, a paginated list with
/// hub linkage, and the order detail — a bottom sheet on a phone, a side sheet
/// in a split-screen window, a pane beside the list on a wide tablet — with
/// the status moves.
///
/// No permission gate, as on the web: page.tsx shows Orders to every agent and
/// OrdersView checks no permission (not view_orders, not manage_orders), and
/// routers/admin.py `list_orders` / `update_order` only require a signed-in
/// agent. A refusal the server does send is said in the toast.
struct OrdersScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.ordersScreen {
            GeometryReader { g in OrdersBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}

/// How wide the order pane is beside the list on a wide tablet.
let ORDER_PANE_WIDTH: CGFloat = 440

struct OrderSheetItem: Identifiable, Equatable { let id: String }

struct OrdersBody: View {
    @ObservedObject var model: OrdersScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @Environment(\.sizeCategory) private var sizeCategory
    /// The filter, search, page, open order and scroll, kept by the scene across a reclaim (Android's saved UI state).
    @SceneStorage("orders.ui") private var savedUi: String = ""
    @State private var visibleRows: Set<Int> = []

    private var vm: OrdersViewModel { model.vm }
    private var ui: OrdersUi { model.ui }
    private var wide: Bool { width >= 600 }
    /// A tablet shows the order beside the list instead of in a sheet over it —
    /// on its side and upright (a 13" iPad upright leaves room beside the rail).
    private var twoPane: Bool { width >= 840 }
    /// Split screen (600–840pt): the order slides in from the end edge, the list
    /// stays in view beside it; only phone-sized windows get the bottom sheet.
    private var sidePanel: Bool { wide && !twoPane }
    private var gutter: CGFloat { wide ? 24 : 16 }
    /// How much larger than the design size the user's text is.
    private var fontScale: Double { Double(UIFontMetrics.default.scaledValue(for: 100)) / 100 }
    private var pageSize: Int { OrdersViewModel.PAGE_SIZE }

    var body: some View {
        // Derived per change of the list / filter / search — one pass each, never one per status card.
        let orders = model.orders
        let filtered = OrderUi.filterOrders(orders, filter: ui.filter, search: ui.search)
        let totalPages = max(1, (filtered.count + pageSize - 1) / pageSize)
        let page = min(max(ui.page, 1), totalPages)
        let paginated = OrderUi.pageOf(filtered, page: page, size: pageSize)
        let stats = OrderUi.orderStats(orders)
        let selected = model.selected
        let unknown = model.unknown
        // Phones (and big text): the row's amount moves up beside the name. The
        // order pane's width counts only while it is open beside the list.
        let compactRows = Double(twoPane && selected != nil ? width - ORDER_PANE_WIDTH : width) / fontScale < 480
        let cols = OrderUi.statusColumns(width: Double(width), gutter: Double(gutter), fontScale: fontScale)

        TimelineView(.periodic(from: .now, by: 60)) { ctx in
            HStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 0) {
                            header(stats: stats, total: orders.count, unknown: unknown)
                            statusCards(stats: stats, cols: cols, known: !unknown)
                            searchRow
                            if let err = ui.loadError, !orders.isEmpty {
                                StaleBanner(reason: err, onRetry: { vm.refresh() }).padding(.bottom, 12)
                            }
                            if ui.initialLoading && orders.isEmpty {
                                LoadingView().frame(height: 200)
                            } else if let err = ui.loadError, orders.isEmpty {
                                // Nothing was ever read: "No orders found" would be a lie.
                                ErrorStateView(message: err, onRetry: { vm.retry() })
                            } else if filtered.isEmpty {
                                emptyCard
                            } else {
                                listCard(paginated, compact: compactRows, selected: selected, now: ctx.date)
                            }
                            if totalPages > 1 {
                                PagerView(page: page, totalPages: totalPages, total: filtered.count, pageSize: pageSize, fontScale: fontScale) { vm.setPage($0) }
                                    .padding(.top, 16)
                            }
                            Color.clear.frame(height: 24)
                        }
                        .padding(gutter)
                    }
                    .refreshable { await pullToRefresh() }
                    .onChange(of: ui.pendingScroll) { p in applyPendingScroll(p, paginated, proxy) }
                    .onChange(of: orders.count) { _ in applyPendingScroll(ui.pendingScroll, paginated, proxy) }
                }
                // ── Order detail, beside the list on a wide tablet ─────────────
                if twoPane, let o = selected {
                    OrderDetailView(order: o, busy: ui.updating == o.id, onStatus: { Haptics.tap(); vm.updateStatus(id: o.id, status: $0) }, onClose: { vm.select(nil) })
                        .frame(width: ORDER_PANE_WIDTH)
                        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(c.bg2))
                        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(c.bg4))
                        .padding(.top, 24).padding(.bottom, 24).padding(.trailing, 24)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg)
        .overlay {
            if sidePanel {
                SideSheet(open: sideOpen, width: min(ORDER_PANE_WIDTH, width * 0.8), title: "Order") {
                    if let o = selected {
                        OrderDetailView(order: o, busy: ui.updating == o.id, onStatus: { Haptics.tap(); vm.updateStatus(id: o.id, status: $0) }, onClose: { vm.select(nil) }, titleBar: false)
                    }
                }
            }
        }
        .sheet(item: phoneSheet) { item in
            if let o = orders.first(where: { $0.id == item.id }) {
                OrderDetailView(order: o, busy: ui.updating == o.id, onStatus: { Haptics.tap(); vm.updateStatus(id: o.id, status: $0) }, onClose: { vm.select(nil) })
                    .background(c.bg2)
                    .environment(\.neema, c)
                    .environmentObject(app)
                    .presentationDetents([.large])
                    .presentationDragIndicator(.visible)
            }
        }
        .onAppear {
            vm.restoreIfFresh(JSONValue.parse(savedUi)?.objectValue)
            vm.life.shown.update(true)
        }
        .onDisappear { vm.life.shown.update(false) }
        .onChange(of: ui) { _ in persist() }
        // The row vanished under a refetch — nothing left to show. (Not before
        // the first read: an order restored after a reclaim waits for it.)
        .onChange(of: orders) { list in
            if let id = ui.selectedId, !list.contains(where: { $0.id == id }), model.loaded { vm.select(nil) }
        }
    }

    // ── Pieces ────────────────────────────────────────────────────────────────

    private func header(stats: OrderStats, total: Int, unknown: Bool) -> some View {
        let pending = stats.counts["pending"] ?? 0
        let title = VStack(alignment: .leading, spacing: 2) {
            Text("Orders").font(NeemaFont.manrope(20, .bold)).tracking(-0.5).foregroundColor(c.text)
            // One run of text: "· 12 pending" wraps as a phrase, never letter by letter.
            (Text(unknown ? (ui.loadError != nil ? "Not loaded" : "Loading…") : "\(total) total")
                + Text(pending > 0 ? "  · \(pending) pending" : "").foregroundColor(c.amber).fontWeight(.medium))
                .font(NeemaFont.manrope(14)).foregroundColor(c.textDim).monospacedDigit()
        }
        let amount = unknown ? "—" : OrderUi.money(stats.revenue)
        return ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 12) {
                title
                Spacer(minLength: 12)
                RevenueCard(amount: amount, stacked: false)
            }
            VStack(alignment: .leading, spacing: 12) {
                title
                RevenueCard(amount: amount, stacked: true)
            }
        }
        .padding(.bottom, 24)
    }

    private func statusCards(stats: OrderStats, cols: Int, known: Bool) -> some View {
        let statuses = OrderUi.ORDER_STATUSES
        let rows = stride(from: 0, to: statuses.count, by: max(1, cols)).map { Array(statuses[$0..<min($0 + cols, statuses.count)]) }
        return VStack(spacing: 12) {
            ForEach(rows, id: \.self) { row in
                HStack(spacing: 12) {
                    ForEach(row, id: \.self) { s in
                        StatusCard(meta: OrderUi.statusMeta(s), count: stats.counts[s] ?? 0, revenue: stats.revenueBy[s] ?? 0, known: known,
                                   active: ui.filter == s) { vm.toggleFilter(s) }
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        // 14pt + the search field's touch margin = the web's mb-5.
        .padding(.bottom, 14)
    }

    private var searchRow: some View {
        HStack(spacing: 8) {
            CompactSearchField(value: Binding(get: { ui.search }, set: { vm.setSearch($0) }), placeholder: "Search by name or phone…")
            if ui.filter != "all" {
                Button { vm.setFilter("all") } label: {
                    Text("\(OrderUi.STATUS_META[ui.filter]?.label ?? ui.filter) ✕").font(NeemaFont.manrope(12, .semibold))
                        .foregroundColor(c.isDark ? c.bg : .white)
                        .padding(.horizontal, 12).frame(minHeight: 36)
                        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.gold2))
                }
                .accessibilityLabel("Clear the status filter")
            }
        }
        .padding(.bottom, 10)
    }

    private var emptyCard: some View {
        VStack(spacing: 12) {
            Text("📦").font(.system(size: 30))
            Text("No orders found").font(NeemaFont.manrope(14)).foregroundColor(c.textDim)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 64)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.bg4))
    }

    /// One bordered card around the whole page of rows.
    private func listCard(_ paginated: [Order], compact: Bool, selected: Order?, now: Date) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(paginated.enumerated()), id: \.element.id) { i, order in
                OrderRowView(order: order, isUpdating: ui.updating == order.id, compact: compact,
                             highlighted: twoPane && selected?.id == order.id, now: now,
                             onTap: { vm.select(order) },
                             onPushFailed: { app.toast(order.hubLastError.flatMap { $0.isEmpty ? nil : $0 } ?? "The push to the hub failed", .error) })
                    .id(order.id)
                    .onAppear { visibleRows.insert(i); trackScroll() }
                    .onDisappear { visibleRows.remove(i); trackScroll() }
                if i < paginated.count - 1 { Hairline(color: c.isDark ? c.bg3 : Palette.moss50) }
            }
        }
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.bg4))
    }

    // ── Sheets ────────────────────────────────────────────────────────────────

    private var sideOpen: Binding<Bool> {
        Binding(get: { sidePanel && model.selected != nil }, set: { if !$0 { vm.select(nil) } })
    }

    private var phoneSheet: Binding<OrderSheetItem?> {
        Binding(get: { (!wide && model.selected != nil) ? OrderSheetItem(id: model.selected!.id) : nil },
                set: { if $0 == nil { vm.select(nil) } })
    }

    // ── Scroll and scene state ────────────────────────────────────────────────

    /// Where the list is scrolled (the first row on screen), kept current for the scene.
    private func trackScroll() {
        let first = visibleRows.min() ?? 0
        if vm.scroll.index != first { vm.scroll = ScrollPos(first, 0); persist() }
    }

    /// A scroll restored after a reclaim, applied once the orders are in.
    private func applyPendingScroll(_ p: ScrollPos?, _ paginated: [Order], _ proxy: ScrollViewProxy) {
        guard let p = p, !model.unknown, !paginated.isEmpty else { return }
        let target = paginated[min(p.index, paginated.count - 1)].id
        DispatchQueue.main.async { proxy.scrollTo(target, anchor: .top) }
        vm.scrollRestored()
    }

    private func persist() { savedUi = JSONValue.object(vm.saveUi()).text }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }
}

// ── Header and cards ──────────────────────────────────────────────────────────

/// The header's revenue pill (`rounded-xl px-4 py-2.5 text-right`). Stacked
/// under the title on a narrow screen it spans the width: label left, figure right.
struct RevenueCard: View {
    let amount: String
    let stacked: Bool
    @Environment(\.neema) private var c

    var body: some View {
        Group {
            if stacked {
                HStack(spacing: 12) {
                    label
                    Spacer(minLength: 0)
                    figure
                }
                .frame(maxWidth: .infinity)
            } else {
                VStack(alignment: .trailing, spacing: 2) {
                    label
                    figure
                }
            }
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.bg4))
    }

    private var label: some View { Text("Total Revenue").font(NeemaFont.manrope(12, .medium)).foregroundColor(c.textDim) }
    private var figure: some View {
        Text(amount.unbroken).font(NeemaFont.manrope(16, .bold)).foregroundColor(c.gold2).monospacedDigit().multilineTextAlignment(.trailing)
    }
}

/// One status's count and money; tapping it filters the list (the web's status cards).
struct StatusCard: View {
    let meta: StatusMeta
    let count: Int
    let revenue: Double
    var known: Bool = true
    let active: Bool
    let onTap: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let look = ToneLook.of(meta.tone)
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 6) {
                    Circle().fill(look.dot).frame(width: 8, height: 8)
                    Text(meta.label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(look.text(c.isDark)).lineLimit(1)
                }
                Text(known ? String(count) : "—").font(NeemaFont.manrope(20, .bold)).foregroundColor(c.text).monospacedDigit().padding(.top, 8)
                if revenue > 0 {
                    Text(OrderUi.money(revenue).unbroken).font(NeemaFont.manrope(12)).foregroundColor(c.textDim).monospacedDigit().padding(.top, 2)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
            .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(active ? look.border(c.isDark) : c.bg3, lineWidth: active ? 2 : 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(meta.label): \(known ? String(count) : "not loaded")")
        .accessibilityAddTraits(active ? AccessibilityTraits.isSelected : AccessibilityTraits())
        .accessibilityHint(active ? "Clears the filter" : "Shows only \(meta.label.lowercased()) orders")
    }
}

/// The web's compact search input: a fixed-height box with a 1px `#b5da8b`
/// border and the magnifier inside on the left (Android `CompactSearchField`).
struct CompactSearchField: View {
    @Binding var value: String
    let placeholder: String
    var height: CGFloat = 36
    var radius: CGFloat = 12
    var fontSize: CGFloat = 16
    @Environment(\.neema) private var c

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").font(.system(size: 14, weight: .medium)).foregroundColor(c.isDark ? c.muted : Palette.stone300)
            TextField(placeholder, text: $value)
                .font(NeemaFont.manrope(fontSize)).foregroundColor(c.text)
                .textInputAutocapitalization(.never).autocorrectionDisabled()
                .submitLabel(.search)
            if !value.isEmpty {
                Button { value = "" } label: {
                    Image(systemName: "xmark.circle.fill").font(.system(size: 14)).foregroundColor(c.muted)
                }
                .accessibilityLabel("Clear search")
            }
        }
        .padding(.leading, 12).padding(.trailing, 8)
        .frame(minHeight: height)
        .background(RoundedRectangle(cornerRadius: radius, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous).stroke(c.border))
        // 48pt to the finger, the web's h-9 box to the eye.
        .frame(minHeight: 48)
    }
}

/// ChannelPill — a solid pill with the channel's mark and name, white on brand colour (Android `OrderChannelPill`).
struct OrderChannelPill: View {
    let channel: String?

    private var ch: String { (channel?.isEmpty == false ? channel! : "whatsapp").lowercased() }

    private var bg: Color {
        switch ch {
        case "whatsapp": return ChannelColors.whatsApp
        case "messenger": return ChannelColors.messenger
        case "instagram": return ChannelColors.instagram
        case "facebook": return ChannelColors.facebook
        case "email": return Palette.indigo500
        case "sms": return Palette.moss600
        default: return Palette.willow600
        }
    }

    private var glyph: String? {
        switch ch {
        case "whatsapp": return "W"
        case "messenger": return "m"
        case "facebook": return "f"
        case "instagram": return "◎"
        case "email": return "@"
        case "sms": return "✉"
        default: return nil
        }
    }

    var body: some View {
        HStack(spacing: 4) {
            // The app's own mark for WhatsApp and Messenger (Android `ChannelGlyphs.forOrder`), a letter for the rest.
            if ch == "whatsapp" || ch == "messenger" {
                ChannelGlyph(channel: ch, size: 10, waTint: .white)
            } else if let g = glyph {
                Text(g).font(NeemaFont.fixed(9, .bold)).foregroundColor(.white)
            }
            Text(ch.prefix(1).uppercased() + ch.dropFirst()).font(NeemaFont.manrope(10, .medium)).foregroundColor(.white).lineLimit(1)
        }
        .padding(.horizontal, 6).padding(.vertical, 2)
        .background(Capsule().fill(bg))
        .accessibilityLabel(channelStyle(ch).label)
    }
}

// ── Pagination ────────────────────────────────────────────────────────────────

/// Numbered pages, a window of at most five around the current one. Each
/// button is a 32pt square in a 48pt touch cell; where the row can't also hold
/// the "Showing" line (a phone), the buttons get their own centred row.
struct PagerView: View {
    let page: Int
    let totalPages: Int
    let total: Int
    let pageSize: Int
    let fontScale: Double
    let onPage: (Int) -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let window = OrderUi.pageWindow(page: page, totalPages: totalPages)
        let showing = Text("Showing \((page - 1) * pageSize + 1)–\(min(page * pageSize, total)) of \(total)")
            .font(NeemaFont.manrope(12)).foregroundColor(c.textDim).monospacedDigit()
        let buttons = HStack(spacing: 0) {
            PageButton(label: "‹", description: "Previous page", selected: false, enabled: page > 1) { onPage(max(1, page - 1)) }
            ForEach(window, id: \.self) { pg in
                PageButton(label: String(pg), description: "Page \(pg)", selected: page == pg, enabled: true) { onPage(pg) }
            }
            PageButton(label: "›", description: "Next page", selected: false, enabled: page < totalPages) { onPage(min(totalPages, page + 1)) }
        }
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 8) {
                showing
                Spacer(minLength: 8)
                buttons
            }
            VStack(spacing: 4) {
                showing
                buttons
            }
            .frame(maxWidth: .infinity)
        }
        .padding(.horizontal, 4)
    }
}

struct PageButton: View {
    let label: String
    let description: String
    let selected: Bool
    let enabled: Bool
    let onTap: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        Button(action: onTap) {
            // disabled:opacity-30 fades the whole button, border and fill included.
            Text(label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(selected ? .white : c.gold2).monospacedDigit().lineLimit(1)
                .frame(width: 32, height: 32)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(selected ? c.gold : c.bg2))
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(selected ? c.gold : c.border))
                .opacity(enabled ? 1 : 0.3)
                .frame(width: 44, height: 44)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityLabel(description)
        .accessibilityAddTraits(selected ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}
