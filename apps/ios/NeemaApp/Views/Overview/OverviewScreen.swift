import SwiftUI
import UIKit
import NeemaCore

/// Port of components/views/OverviewView.tsx — the Analytics screen (Android `OverviewScreen`).
struct OverviewScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.overviewScreen {
            GeometryReader { g in OverviewBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}

struct OverviewBody: View {
    @ObservedObject var model: OverviewScreenModel
    let width: CGFloat
    @Environment(\.neema) private var c

    private var vm: OverviewViewModel { model.vm }
    private var ui: OverviewUi { model.ui }
    private var wide: Bool { width >= 600 }
    private var pad: CGFloat { wide ? 24 : 16 }
    /// The content width inside the page's padding.
    private var inner: CGFloat { max(0, width - 2 * pad) }
    /// How much larger than the design size the user's text is.
    private var fontScale: CGFloat { UIFontMetrics.default.scaledValue(for: 100) / 100 }

    // The web's STAT_COLORS, by accent. By day exactly the web's hexes
    // (#589b31 #427425 #2a48a2 #bcc13e #4d66b3); by night the theme's lifted hues.
    private var accentGreen: Color { c.gold }
    private var accentEmerald: Color { c.gold2 }
    private var accentBlue: Color { c.blue }
    private var accentOrange: Color { c.amber }
    private var accentViolet: Color { c.isDark ? c.indigo : Palette.indigo500 }

    var body: some View {
        // "4m ago" in the feed and today's bar follow the clock: re-read every minute on screen.
        TimelineView(.periodic(from: .now, by: 60)) { ctx in
            let now = Int64(ctx.date.timeIntervalSince1970 * 1000)
            let today = LocalDay.of(millis: now, zone: Fmt.timeZone)
            let stats = OverviewRules.headline(ui.stats, convs: ui.fallbackConvs, agents: model.agents, orders: model.orders, catalog: model.catalog)
            let channels = OverviewRules.channelRows(ui.stats, convs: ui.fallbackConvs)
            let activity = OverviewRules.activityFeed(orders: model.orders, human: ui.humanRows ?? ui.fallbackConvs, agents: model.agents)
            let bars = OverviewRules.sevenDayRevenue(model.orders, today: today, zone: Fmt.timeZone)
            let top = OverviewRules.topProducts(model.orders)
            let cardsLoading = ui.statsLoading && ui.stats == nil
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    header
                    // The server's counts didn't come: the cards below are the
                    // phone's own estimate (the web swaps them in silently).
                    if let why = ui.statsError {
                        LoadProblem(message: why, title: "Live figures unavailable — showing an estimate", retrying: ui.refreshing, onRetry: { vm.refresh() })
                    }
                    statGrid(stats, loading: cardsLoading)
                    // Attribution — which source/post drives leads + revenue.
                    if let a = ui.attrib, !a.sources.isEmpty {
                        AttributionPanel(a: a, wide: wide, width: inner)
                    }
                    chartsRow(bars: bars, stats: stats)
                    bottomRow(channels: channels, activity: activity, now: now)
                    if !top.isEmpty { TopProductsPanel(top: top, large: fontScale > 1.2) }
                    Color.clear.frame(height: 8)
                }
                .padding(pad)
            }
            .refreshable { await pullToRefresh() }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg)
        .onAppear { vm.life.shown.update(true) }
        .onDisappear { vm.life.shown.update(false) }
    }

    // ── Pieces ────────────────────────────────────────────────────────────────

    private var header: some View {
        HStack(alignment: .center, spacing: 6) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Overview").font(NeemaFont.manrope(20, .bold)).foregroundColor(c.text)
                Text("Real-time metrics and platform performance").font(NeemaFont.manrope(14)).foregroundColor(c.muted)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            if ui.statsLoading {
                ProgressView().progressViewStyle(.circular).scaleEffect(0.6).frame(width: 12, height: 12)
                Text("Refreshing…").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
            }
        }
    }

    /// The web's grid-cols-2 sm:grid-cols-3 — one a row when a large font would leave two cards no room for their figures.
    private func statGrid(_ s: Headline, loading: Bool) -> some View {
        let cards: [StatCardData] = [
            StatCardData(label: "Open Conversations", value: String(s.openConvs), sub: "\(s.humanConvs) with agents", icon: OverviewIcons.chat, accent: accentGreen),
            StatCardData(label: "Active Agents", value: String(s.activeAgents), sub: "of \(s.totalAgents) total", icon: OverviewIcons.team, accent: accentEmerald),
            StatCardData(label: "Total Revenue", value: Fmt.currency(s.revenue), sub: "\(s.totalOrders) orders", icon: OverviewIcons.money, accent: accentGreen),
            StatCardData(label: "Pending Orders", value: String(s.pendingOrders), sub: "Awaiting confirmation", icon: OverviewIcons.box, accent: accentOrange),
            StatCardData(label: "Neema's conversations", value: String(s.aiConvs), sub: "Fully automated", icon: OverviewIcons.robot, accent: accentBlue),
            StatCardData(label: "Catalog Items", value: String(s.totalItems), sub: "\(s.inStockItems) in stock", icon: OverviewIcons.box, accent: accentViolet),
        ]
        let cols = gridColumns(width: inner, max: wide ? 3 : 2, fontScale: fontScale)
        let rows = stride(from: 0, to: cards.count, by: cols).map { Array(cards[$0..<min($0 + cols, cards.count)]) }
        return VStack(spacing: 12) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                HStack(alignment: .top, spacing: 12) {
                    ForEach(row) { card in StatCard(data: card, loading: loading) }
                    ForEach(0..<(cols - row.count), id: \.self) { _ in Color.clear.frame(maxWidth: .infinity) }
                }
                .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func chartsRow(bars: [DayBar], stats: Headline) -> some View {
        Group {
            if wide {
                HStack(alignment: .top, spacing: 16) {
                    RevenueChart(bars: bars).frame(width: (inner - 16) * 3 / 5).frame(maxHeight: .infinity)
                    OrderStatusPanel(s: stats).frame(width: (inner - 16) * 2 / 5).frame(maxHeight: .infinity)
                }
                .fixedSize(horizontal: false, vertical: true)
            } else {
                RevenueChart(bars: bars)
                OrderStatusPanel(s: stats)
            }
        }
    }

    private func bottomRow(channels: [ChannelRow], activity: [ActivityEntry], now: Int64) -> some View {
        let lines = fontScale > 1.2 ? 4 : 2
        return Group {
            if wide {
                HStack(alignment: .top, spacing: 16) {
                    ChannelPanel(rows: channels, stats: ui.stats, localCount: ui.fallbackConvs.count).frame(width: (inner - 16) * 2 / 5).frame(maxHeight: .infinity)
                    ActivityPanel(feed: activity, now: now, lines: lines).frame(width: (inner - 16) * 3 / 5).frame(maxHeight: .infinity)
                }
                .fixedSize(horizontal: false, vertical: true)
            } else {
                ChannelPanel(rows: channels, stats: ui.stats, localCount: ui.fallbackConvs.count)
                ActivityPanel(feed: activity, now: now, lines: lines)
            }
        }
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<200 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }
}

/// The web's #2c4e18 (totals, today, top-product revenue); the bright moss by night.
private func strong(_ c: NeemaColors) -> Color { c.isDark ? c.gold2 : Palette.moss800 }

struct StatCardData: Identifiable {
    let label: String
    let value: String
    let sub: String
    let icon: String
    let accent: Color
    var id: String { label }
}

/// The web's StatCard: accent strip, tinted icon tile, value (or a pulsing placeholder).
struct StatCard: View {
    let data: StatCardData
    let loading: Bool
    @Environment(\.neema) private var c
    @State private var pulse = false

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Rectangle().fill(data.accent).frame(height: 2)
            VStack(alignment: .leading, spacing: 0) {
                ZStack {
                    RoundedRectangle(cornerRadius: 10, style: .continuous).fill(data.accent.opacity(0.10))
                    SVGStrokeIcon(d: data.icon, size: 20, width: 1.8).foregroundColor(data.accent)
                }
                .frame(width: 36, height: 36)
                .padding(.bottom, 10)
                if loading {
                    RoundedRectangle(cornerRadius: 4, style: .continuous).fill(c.bg3)
                        .frame(width: 56, height: 26).padding(.vertical, 2)
                        .opacity(pulse ? 1 : 0.4)
                        .onAppear { withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) { pulse = true } }
                } else {
                    // The whole figure, always: it shrinks to fit rather than "KES 98,7…".
                    BigNumber(text: data.value, color: c.text, max: 24)
                }
                Text(data.label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(data.accent).lineLimit(2).padding(.top, 2)
                Text(data.sub).font(NeemaFont.manrope(12)).foregroundColor(c.muted).lineLimit(2).padding(.top, 2)
            }
            .padding(14)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.hairline))
    }
}

/// Where sales come from: a table on a wide screen, a card per source on a phone.
struct AttributionPanel: View {
    let a: Attribution
    let wide: Bool
    /// The panel's outer width (its table columns are weighted from it).
    let width: CGFloat
    @Environment(\.neema) private var c

    private static let weights: [CGFloat] = [1.2, 2, 0.7, 0.7, 1.2]
    private var unit: CGFloat { max(0, width - 32) / Self.weights.reduce(0, +) }
    private func col(_ i: Int) -> CGFloat { Self.weights[i] * unit }

    var body: some View {
        PanelCard {
            PanelHeadline(title: { PanelTitle(text: "Where Sales Come From") },
                        trailing: { Text("\(a.totals.leads) attributed lead\(a.totals.leads == 1 ? "" : "s")").font(NeemaFont.manrope(11)).foregroundColor(c.muted) })
                .padding(.bottom, 10)
            if wide { table } else { cards }
        }
    }

    private var table: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 0) {
                ForEach(Array(["Source", "Post", "Leads", "Orders", "Revenue (KES)"].enumerated()), id: \.offset) { i, h in
                    Text(h.uppercased()).font(NeemaFont.manrope(10, .semibold)).foregroundColor(c.muted)
                        .frame(width: col(i), alignment: i >= 2 ? .trailing : .leading)
                }
            }
            .padding(.vertical, 6)
            Hairline(color: c.hairline)
            ForEach(Array(a.sources.prefix(8).enumerated()), id: \.offset) { _, r in
                HStack(spacing: 0) {
                    Text(OverviewRules.capitalizeWords(r.source)).font(NeemaFont.manrope(12, .medium)).foregroundColor(c.text).frame(width: col(0), alignment: .leading)
                    postText(r).frame(width: col(1), alignment: .leading)
                    Text(String(r.leads)).font(NeemaFont.manrope(12)).foregroundColor(c.text).frame(width: col(2), alignment: .trailing)
                    Text(String(r.orders)).font(NeemaFont.manrope(12)).foregroundColor(c.text).frame(width: col(3), alignment: .trailing)
                    Text(Fmt.currency(r.revenue)).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text).frame(width: col(4), alignment: .trailing)
                }
                .padding(.vertical, 8)
                Hairline(color: c.hairline.opacity(0.5))
            }
            if a.unattributed.orders > 0 {
                let grey = Palette.slate400
                HStack(spacing: 0) {
                    Text("unattributed").font(NeemaFont.manrope(12)).italic().foregroundColor(grey).frame(width: col(0), alignment: .leading)
                    Text("—").font(NeemaFont.manrope(12)).foregroundColor(grey).frame(width: col(1), alignment: .leading)
                    Text("—").font(NeemaFont.manrope(12)).foregroundColor(grey).frame(width: col(2), alignment: .trailing)
                    Text(String(a.unattributed.orders)).font(NeemaFont.manrope(12)).foregroundColor(grey).frame(width: col(3), alignment: .trailing)
                    Text(Fmt.currency(a.unattributed.revenue)).font(NeemaFont.manrope(12)).foregroundColor(grey).frame(width: col(4), alignment: .trailing)
                }
                .padding(.vertical, 8)
            }
        }
    }

    private func postText(_ r: AttributionRow) -> some View {
        let mono = (r.postTitle ?? "").isEmpty
        return Text(r.postTitle ?? r.post ?? "—").font(mono ? NeemaFont.mono(10) : NeemaFont.manrope(10)).foregroundColor(Palette.slate500).lineLimit(1)
    }

    private var cards: some View {
        VStack(spacing: 8) {
            ForEach(Array(a.sources.prefix(8).enumerated()), id: \.offset) { _, r in
                AttributionCard(source: OverviewRules.capitalizeWords(r.source), post: r.postTitle ?? r.post ?? "—", mono: (r.postTitle ?? "").isEmpty,
                                leads: String(r.leads), orders: String(r.orders), revenue: Fmt.currency(r.revenue), dim: false)
            }
            if a.unattributed.orders > 0 {
                AttributionCard(source: "unattributed", post: "—", mono: false, leads: "—", orders: String(a.unattributed.orders),
                                revenue: Fmt.currency(a.unattributed.revenue), dim: true)
            }
        }
    }
}

private struct AttributionCard: View {
    let source: String
    let post: String
    let mono: Bool
    let leads: String
    let orders: String
    let revenue: String
    let dim: Bool
    @Environment(\.neema) private var c

    var body: some View {
        let fg = dim ? Palette.slate400 : c.text
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .center) {
                Text(source).font(NeemaFont.manrope(13, dim ? .regular : .semibold)).italic(dim).foregroundColor(fg).frame(maxWidth: .infinity, alignment: .leading)
                Text(revenue).font(NeemaFont.manrope(13, dim ? .regular : .semibold)).foregroundColor(fg)
            }
            Text(post).font(mono ? NeemaFont.mono(11) : NeemaFont.manrope(11)).foregroundColor(dim ? fg : Palette.slate500).lineLimit(1)
            Text("Leads \(leads)  ·  Orders \(orders)").font(NeemaFont.manrope(11)).foregroundColor(dim ? fg : c.muted).padding(.top, 4)
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.bg))
    }
}

/// 7-day revenue bars; today's bar in the dark green. Tap a bar for its amount.
struct RevenueChart: View {
    let bars: [DayBar]
    @Environment(\.neema) private var c
    @State private var picked: Int? = nil

    private var maxValue: Double { max(1, bars.map { $0.value }.max() ?? 0) }

    var body: some View {
        // Web: today #427425, other days #cee6b2, hover green-400.
        let todayColor = c.isDark ? c.gold : c.gold2
        // By night a wash of the moss strong enough to read against the navy panel.
        let restColor = c.isDark ? c.gold.opacity(0.45) : c.bg4
        PanelCard {
            PanelHeadline(title: { PanelTitle(text: "7-Day Revenue (KES)") },
                        trailing: { Text(Fmt.currency(bars.reduce(0) { $0 + $1.value })).font(NeemaFont.manrope(12, .bold)).foregroundColor(strong(c)).monospacedDigit() })
            Text(picked.map { "\(bars[$0].label): \(Fmt.currency(bars[$0].value))" } ?? " ").font(NeemaFont.manrope(11)).foregroundColor(c.textDim).padding(.top, 8)
            GeometryReader { g in
                HStack(alignment: .bottom, spacing: 8) {
                    ForEach(Array(bars.enumerated()), id: \.offset) { i, d in
                        VStack(spacing: 0) {
                            Spacer(minLength: 0)
                            if d.value > 0 {
                                TopRoundedBar(radius: 6)
                                    .fill(d.isToday ? todayColor : (picked == i ? Palette.green400 : restColor))
                                    .frame(height: max(4, g.size.height * CGFloat(d.value / maxValue)))
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .contentShape(Rectangle())
                        .onTapGesture { picked = picked == i ? nil : i }
                    }
                }
            }
            .frame(height: 104)
            .padding(.top, 4)
            AxisLabels(labels: bars.map { $0.label }, fontSize: 10, weight: { _ in .medium }, color: { i in bars[i].isToday ? strong(c) : c.muted })
            if bars.allSatisfy({ $0.value == 0 }) {
                Text("No orders in the last 7 days").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                    .frame(maxWidth: .infinity).padding(.top, 8)
            }
        }
        .onChange(of: bars) { _ in picked = nil }
    }
}

struct OrderStatusPanel: View {
    let s: Headline
    @Environment(\.neema) private var c

    private var items: [(String, Int, Color, Color)] {
        [("Delivered", s.deliveredOrders, Palette.emerald500, Palette.emerald600),
         ("Confirmed", s.confirmedOrders, Palette.blue500, Palette.blue600),
         ("Pending", s.pendingOrders, Palette.amber400, Palette.amber600),
         ("Cancelled", s.cancelledOrders, Palette.red400, Palette.red500)]
    }

    var body: some View {
        PanelCard {
            PanelTitle(text: "Order Status").padding(.bottom, 14)
            VStack(spacing: 14) {
                ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                    VStack(spacing: 6) {
                        HStack {
                            Text(item.0).font(NeemaFont.manrope(12, .medium)).foregroundColor(c.textDim).frame(maxWidth: .infinity, alignment: .leading)
                            Text(String(item.1)).font(NeemaFont.manrope(12, .bold)).foregroundColor(item.3).monospacedDigit()
                        }
                        ThinBar(fraction: s.totalOrders > 0 ? Double(item.1) / Double(s.totalOrders) : 0, color: item.2)
                    }
                }
            }
        }
    }
}

struct ChannelPanel: View {
    let rows: [ChannelRow]
    let stats: Stats?
    let localCount: Int
    @Environment(\.neema) private var c

    var body: some View {
        // Divide by the SERVER's total, never the handful of rows the app holds.
        let serverTotal = stats?.channelBreakdown.reduce(0) { $0 + $1.count } ?? 0
        let total = max(serverTotal > 0 ? serverTotal : localCount, 1)
        // Only the channels the web knows (CHANNEL_CONFIG); anything else is skipped.
        let known = rows.filter { OverviewRules.ALL_CHANNELS.contains($0.ch) }
        PanelCard {
            PanelTitle(text: "By Channel").padding(.bottom, 14)
            if rows.isEmpty {
                Text("No channel data yet").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                    .frame(maxWidth: .infinity).padding(.vertical, 24)
            } else {
                VStack(spacing: 14) {
                    ForEach(Array(known.enumerated()), id: \.offset) { _, r in
                        HStack(alignment: .center, spacing: 12) {
                            ChannelTile(channel: r.ch)
                            VStack(spacing: 6) {
                                // Counts drop under the name when a large font leaves no room beside it.
                                PanelHeadline(title: { Text(channelStyle(r.ch).label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.gold2) },
                                            trailing: { Text("\(r.count) · \(r.open) open").font(NeemaFont.manrope(12)).foregroundColor(c.muted).monospacedDigit() })
                                ThinBar(fraction: Double(r.count) / Double(total), color: channelStyle(r.ch).color)
                            }
                        }
                    }
                }
            }
        }
    }
}

struct ActivityPanel: View {
    let feed: [ActivityEntry]
    let now: Int64
    /// Two lines, more at a large font, so the order amount is never the part cut off.
    let lines: Int
    @Environment(\.neema) private var c

    var body: some View {
        PanelCard {
            PanelTitle(text: "Recent Activity").padding(.bottom, 8)
            if feed.isEmpty {
                Text("No activity yet").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                    .frame(maxWidth: .infinity).padding(.vertical, 24)
            } else {
                ForEach(Array(feed.enumerated()), id: \.element.id) { i, e in
                    if i > 0 { Hairline(color: c.bg) }
                    HStack(alignment: .center, spacing: 12) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg)
                            RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.bg3)
                            Text(e.icon).font(.system(size: 13))
                        }
                        .frame(width: 28, height: 28)
                        line(e).font(NeemaFont.manrope(12)).foregroundColor(c.gold2).lineLimit(lines)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Text(Fmt.timeAgo(e.at, now: now)).font(NeemaFont.manrope(10)).foregroundColor(c.muted)
                    }
                    .padding(.vertical, 10)
                }
            }
        }
    }

    private func line(_ e: ActivityEntry) -> Text {
        let who = Text(e.user).fontWeight(.semibold).foregroundColor(c.text)
        let what = Text(" \(e.action)")
        if let t = e.target, !t.isEmpty { return who + what + Text(" · \(t)") }
        return who + what
    }
}

struct TopProductsPanel: View {
    let top: [TopProduct]
    /// A large font: the name gets its own lines, the amount sits under it.
    let large: Bool
    @Environment(\.neema) private var c

    var body: some View {
        let maxRev = (top.first?.revenue ?? 0) != 0 ? top.first!.revenue : 1
        PanelCard {
            PanelTitle(text: "Top Products by Revenue").padding(.bottom, 14)
            VStack(spacing: 10) {
                ForEach(Array(top.enumerated()), id: \.offset) { i, p in
                    HStack(alignment: .center, spacing: 8) {
                        // Rank numbers: the web's #b5da8b is too faint to read, so both themes use the muted text colour.
                        Text(String(i + 1)).font(NeemaFont.manrope(12, .bold)).foregroundColor(c.muted).frame(width: 16, alignment: .leading)
                        VStack(alignment: .leading, spacing: 4) {
                            if large {
                                Text(p.name).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text).lineLimit(3)
                                revenue(p)
                            } else {
                                HStack(spacing: 8) {
                                    Text(p.name).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text).lineLimit(1).frame(maxWidth: .infinity, alignment: .leading)
                                    revenue(p)
                                }
                            }
                            ThinBar(fraction: p.revenue / maxRev, color: c.gold)
                        }
                        Text("×\(OverviewRules.qtyText(p.qty))").font(NeemaFont.manrope(10)).foregroundColor(c.muted).frame(width: 44, alignment: .trailing)
                    }
                }
            }
        }
    }

    private func revenue(_ p: TopProduct) -> some View {
        Text(Fmt.currency(p.revenue)).font(NeemaFont.manrope(12, .bold)).foregroundColor(strong(c)).monospacedDigit()
    }
}
