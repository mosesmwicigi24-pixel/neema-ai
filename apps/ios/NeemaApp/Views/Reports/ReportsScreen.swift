import SwiftUI
import UIKit
import NeemaCore

/// Port of components/views/ReportsView.tsx — admin reports over a date range (Android `ReportsScreen`).
struct ReportsScreen: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        if let m = app.reportsScreen {
            GeometryReader { g in ReportsBody(model: m, width: g.size.width) }
        } else {
            Color.clear
        }
    }
}

struct ShareItem: Identifiable, Equatable {
    let ready: ReadyExport
    var id: String { ready.file.path }
}

struct DatePick: Identifiable, Equatable {
    /// "from" | "to"
    let which: String
    var id: String { which }
}

struct ReportsBody: View {
    @ObservedObject var model: ReportsScreenModel
    let width: CGFloat
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @SceneStorage("reports.ui") private var savedUi: String = ""
    @State private var picking: DatePick? = nil

    private var vm: ReportsViewModel { model.vm }
    private var ui: ReportsUi { model.ui }
    private var wide: Bool { width >= 600 }
    private var pad: CGFloat { wide ? 24 : 16 }
    private var panelWidth: CGFloat { max(0, width - 2 * pad) }
    private var fontScale: CGFloat { UIFontMetrics.default.scaledValue(for: 100) / 100 }

    var body: some View {
        Group {
            if ui.allConvs == nil, let err = ui.loadError {
                // The first download failed: say why and offer another go — a report
                // of zeros here would read as the truth.
                ScrollView {
                    EmptyStateView(title: "Couldn't load the report", subtitle: err, icon: "icloud.slash") {
                        Button(action: { vm.retry() }) {
                            Text("Retry").font(NeemaFont.manrope(13, .semibold)).foregroundColor(.white)
                                .padding(.horizontal, 16).frame(minHeight: 40)
                                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.gold))
                        }
                    }
                    .frame(maxWidth: 420)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 48)
                }
            } else if let r = ui.report {
                content(r)
            } else {
                // Still downloading, or the first report is being built off the main thread.
                VStack(spacing: 10) {
                    ProgressView().progressViewStyle(.circular).tint(c.gold)
                    Text("Loading every conversation for the report…").font(NeemaFont.manrope(14)).foregroundColor(c.textDim).multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(16)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(c.bg)
        .onAppear {
            vm.restoreIfFresh(savedUi)
            vm.life.shown.update(true)
            if ui.exportInterrupted { vm.interruptionShown() }
        }
        .onDisappear { vm.life.shown.update(false) }
        .onChange(of: ui) { u in
            savedUi = vm.saveUi()
            if u.exportInterrupted { vm.interruptionShown() }
        }
        // A CSV that finished writing opens the share sheet from whichever screen
        // is on display: one written across a rotation reaches the new screen, one
        // finished in the background waits for the agent to come back.
        .sheet(item: shareItem) { item in
            ShareSheet(items: [item.ready.file], subject: "Neema report — \(item.ready.range.label)") { completed in
                vm.exportShown(item.ready)
                if completed { app.toast("Report exported", .success) }
            }
            .ignoresSafeArea()
        }
        .sheet(item: $picking) { pick in
            DatePickerSheet(title: pick.which == "from" ? "From" : "To", initial: pick.which == "from" ? ui.customFrom : ui.customTo,
                            onPick: { d in if pick.which == "from" { vm.setCustomFrom(d) } else { vm.setCustomTo(d) }; picking = nil },
                            onCancel: { picking = nil })
                .environment(\.neema, c)
                .presentationDetents([.medium, .large])
        }
    }

    private var shareItem: Binding<ShareItem?> {
        Binding(get: { ui.readyExport.map { ShareItem(ready: $0) } },
                set: { if $0 == nil, let r = ui.readyExport { vm.exportShown(r) } })
    }

    // ── The report ────────────────────────────────────────────────────────────

    private func content(_ r: Report) -> some View {
        // "3h ago" in the Conversations table keeps counting, and is fresh on return to the app.
        TimelineView(.periodic(from: .now, by: 60)) { ctx in
            let now = Int64(ctx.date.timeIntervalSince1970 * 1000)
            let table = ReportsRules.tableFor(ui.tab, r, agents: model.agents, now: now)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 0) {
                    header(r).padding(.bottom, wide ? 24 : 16)
                    tabs.padding(.bottom, 16)
                    if let t = table {
                        ReportTableView(model: t, wide: wide, width: panelWidth)
                    } else {
                        OverviewTab(r: r, wide: wide, width: panelWidth, fontScale: fontScale)
                    }
                    Color.clear.frame(height: 24)
                }
                .padding(pad)
            }
            .refreshable { await pullToRefresh() }
        }
    }

    /// Title left, range + export right (wide); stacked on a phone.
    private func header(_ r: Report) -> some View {
        let title = VStack(alignment: .leading, spacing: 2) {
            Text("Reports").font(NeemaFont.manrope(20, .bold)).foregroundColor(c.text)
            Text("\(ui.range.label) · \(r.convs.count) conversations").font(NeemaFont.manrope(14)).foregroundColor(c.textDim)
        }
        return Group {
            if wide {
                HStack(alignment: .top, spacing: 16) {
                    title.frame(maxWidth: .infinity, alignment: .leading)
                    controls
                }
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    title
                    controls
                }
            }
        }
    }

    private var controls: some View {
        FlowLayout(spacing: 8, lineSpacing: 8) {
            Menu {
                ForEach(ReportRange.allCases, id: \.self) { range in
                    Button(range.label) { vm.setRange(range) }
                }
            } label: {
                HStack(spacing: 4) {
                    Text(ui.range.label).font(NeemaFont.manrope(13)).foregroundColor(c.text)
                    Image(systemName: "chevron.down").font(.system(size: 12, weight: .medium)).foregroundColor(c.textDim)
                }
                .padding(.horizontal, 12).frame(minHeight: 38)
                .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.border))
            }
            if ui.range == .custom {
                DateButton(date: ui.customFrom) { picking = DatePick(which: "from") }
                Text("to").font(NeemaFont.manrope(12)).foregroundColor(c.border2)
                DateButton(date: ui.customTo) { picking = DatePick(which: "to") }
            }
            // The web shows Export CSV to everyone who can open Reports (it never
            // checks export_reports), so this does too. Writing the file: the button
            // stays itself, just quieter, while a second tap is ignored.
            Button(action: exportCsv) {
                HStack(spacing: 6) {
                    Image(systemName: "arrow.down.to.line").font(.system(size: 14, weight: .semibold))
                    Text("Export CSV").font(NeemaFont.manrope(12, .semibold))
                }
                .foregroundColor(.white)
                .padding(.horizontal, 14).frame(minHeight: 38)
                .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.gold.opacity(ui.exporting ? 0.7 : 1)))
            }
            .disabled(ui.exporting)
        }
    }

    /// Written off the main actor into the app's cache; only the share sheet opens here.
    private func exportCsv() {
        let caches = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first ?? FileManager.default.temporaryDirectory
        vm.exportCsv(dir: caches.appendingPathComponent("reports", isDirectory: true))
    }

    /// The web's tab strip: a hairline under the whole width, not just the tabs.
    private var tabs: some View {
        ZStack(alignment: .bottomLeading) {
            Hairline(color: c.bg4)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 0) {
                    ForEach(ReportTab.allCases, id: \.self) { t in
                        let on = ui.tab == t
                        Button(action: { vm.setTab(t) }) {
                            VStack(spacing: 0) {
                                Text(t.label).font(NeemaFont.manrope(12, .semibold)).foregroundColor(on ? c.gold2 : (c.isDark ? c.muted : c.border2))
                                    .padding(.horizontal, 16).padding(.vertical, 12)
                                Rectangle().fill(on ? c.gold2 : .clear).frame(height: 2)
                            }
                            .frame(minHeight: 44)
                        }
                        .buttonStyle(.plain)
                        .accessibilityAddTraits(on ? AccessibilityTraits.isSelected : AccessibilityTraits())
                    }
                }
            }
        }
    }

    private func pullToRefresh() async {
        vm.refresh()
        for _ in 0..<600 {
            try? await Task.sleep(nanoseconds: 50_000_000)
            if !vm.ui.refreshing { break }
        }
    }
}

/// The custom range's date button: the web's <input type="date"> in en-KE reads dd/mm/yyyy.
private struct DateButton: View {
    let date: LocalDay?
    let action: () -> Void
    @Environment(\.neema) private var c

    private var text: String { date.map { String(format: "%02d/%02d/%04d", $0.day, $0.month, $0.year) } ?? "dd/mm/yyyy" }

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: "calendar").font(.system(size: 14, weight: .medium)).foregroundColor(c.textDim)
                Text(text).font(NeemaFont.manrope(12)).foregroundColor(date == nil ? c.muted : c.text)
            }
            .padding(.horizontal, 10).frame(minHeight: 38)
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.border))
        }
        .buttonStyle(.plain)
    }
}

/// A day picker for the custom range, in the phone's own calendar.
struct DatePickerSheet: View {
    let title: String
    let initial: LocalDay?
    let onPick: (LocalDay) -> Void
    let onCancel: () -> Void
    @Environment(\.neema) private var c
    @State private var date: Date

    init(title: String, initial: LocalDay?, onPick: @escaping (LocalDay) -> Void, onCancel: @escaping () -> Void) {
        self.title = title
        self.initial = initial
        self.onPick = onPick
        self.onCancel = onCancel
        // Noon on the chosen day, so no zone shifts it to a neighbour.
        let ms = initial.map { $0.startMillis(zone: Fmt.timeZone) + 12 * 3_600_000 } ?? AppClock.now()
        _date = State(initialValue: Date(timeIntervalSince1970: TimeInterval(ms) / 1000))
    }

    var body: some View {
        VStack(spacing: 0) {
            ModalTitleBar(title: title, onClose: onCancel).padding(.top, 16)
            DatePicker("", selection: $date, displayedComponents: .date)
                .datePickerStyle(.graphical)
                .environment(\.timeZone, Fmt.timeZone)
                .tint(c.gold)
                .padding(.horizontal, 12)
            HStack(spacing: 8) {
                Spacer()
                WebBtn(label: "Cancel", variant: .outline, size: .md, action: onCancel)
                WebBtn(label: "OK", variant: .primary, size: .md) {
                    onPick(LocalDay.of(millis: Int64(date.timeIntervalSince1970 * 1000), zone: Fmt.timeZone))
                }
            }
            .padding(.horizontal, 20).padding(.vertical, 16)
        }
        .background(c.bg2)
    }
}

// ── Overview tab ─────────────────────────────────────────────────────────────

struct OverviewTab: View {
    let r: Report
    let wide: Bool
    let width: CGFloat
    let fontScale: CGFloat
    @Environment(\.neema) private var c

    var body: some View {
        let deliveryRate = r.orders.isEmpty ? 0 : Int((Double(r.delivered) * 100.0 / Double(r.orders.count)).rounded())
        let tiles: [(String, String, String, Color)] = [
            ("Total Conversations", String(r.convs.count), "\(r.humanConvs) human · \(r.aiConvs) Neema", c.gold),
            ("Revenue", Fmt.currency(r.revenue), "\(r.orders.count) orders", c.gold2),
            ("Pending Orders", String(r.pending), "Awaiting confirmation", c.amber),
            ("Delivered Orders", String(r.delivered), "\(deliveryRate)% delivery rate", c.blue),
        ]
        // The web's grid-cols-2 / grid-cols-4, fewer when the cards would be
        // too narrow for their figures (a foldable, or a large font).
        let cols = gridColumns(width: width, max: wide ? 4 : 2, fontScale: fontScale)
        let rows = stride(from: 0, to: tiles.count, by: cols).map { Array(tiles[$0..<min($0 + cols, tiles.count)]) }
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(rows.enumerated()), id: \.offset) { _, row in
                // Equal heights across a row, like the web's grid.
                HStack(alignment: .top, spacing: 12) {
                    ForEach(Array(row.enumerated()), id: \.offset) { _, t in StatBox(label: t.0, value: t.1, sub: t.2, accent: t.3) }
                    ForEach(0..<(cols - row.count), id: \.self) { _ in Color.clear.frame(maxWidth: .infinity) }
                }
                .fixedSize(horizontal: false, vertical: true)
            }
            if wide {
                HStack(alignment: .top, spacing: 12) {
                    convChart.frame(maxWidth: .infinity)
                    revChart.frame(maxWidth: .infinity)
                }
            } else {
                convChart
                revChart
            }
            statusBreakdown
        }
    }

    private var convChart: some View {
        PanelCard(padding: 14) {
            ChartTitle(text: "Conversations over time")
            MiniBar(data: r.convByDay, color: c.gold)
        }
    }

    private var revChart: some View {
        PanelCard(padding: 14) {
            ChartTitle(text: "Revenue over time (KES)")
            MiniBar(data: r.orderByDay, color: c.blue, format: { ReportsRules.plain($0) })
        }
    }

    private var statusBreakdown: some View {
        // The web's #bcc13e / #2a48a2 / #589b31 / #c0392b — the theme's own hues, lifted by night.
        let items: [(String, Color, Int)] = [("Pending", c.amber, r.pending), ("Confirmed", c.blue, r.confirmed), ("Delivered", c.green, r.delivered), ("Cancelled", c.red, r.cancelled)]
        // The web's grid-cols-4; two by two when "Confirmed" wouldn't fit a quarter.
        let perRow = gridColumns(width: width - 28, max: 4, minCell: 64, minWideCell: 72, fontScale: fontScale) > 2 ? 4 : 2
        let lines = stride(from: 0, to: items.count, by: perRow).map { Array(items[$0..<min($0 + perRow, items.count)]) }
        return PanelCard(padding: 14) {
            ChartTitle(text: "Order Status Breakdown").padding(.bottom, 4)
            VStack(spacing: 16) {
                ForEach(Array(lines.enumerated()), id: \.offset) { _, line in
                    HStack(alignment: .top, spacing: 12) {
                        ForEach(Array(line.enumerated()), id: \.offset) { _, item in
                            VStack(spacing: 0) {
                                BigNumber(text: String(item.2), color: item.1, max: 20)
                                Text(item.0).font(NeemaFont.manrope(11)).foregroundColor(c.muted).lineLimit(1)
                                ThinBar(fraction: r.orders.isEmpty ? 0 : Double(item.2) / Double(r.orders.count), color: item.1)
                                    .frame(height: 4).padding(.top, 8)
                            }
                            .frame(maxWidth: .infinity)
                        }
                    }
                }
            }
        }
    }
}

private struct ChartTitle: View {
    let text: String
    @Environment(\.neema) private var c
    var body: some View {
        Text(text.uppercased()).font(NeemaFont.manrope(11, .bold)).tracking(0.6).foregroundColor(c.muted).padding(.bottom, 8)
    }
}
