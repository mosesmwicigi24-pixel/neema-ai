import SwiftUI
import UIKit
import NeemaCore

/// A badge as the web draws it: `px-1.5 py-0.5 rounded text-[10px] font-semibold`
/// on a Tailwind -50 tint. By night the text takes the -400 shade and the tint
/// becomes a wash of it, so the badges read on navy (Android `Badge`).
struct ReportBadge: View {
    let text: String
    let hue: ReportHue
    @Environment(\.neema) private var c

    private var colors: (text: Color, bg: Color, night: Color) {
        switch hue {
        case .emerald: return (Palette.emerald700, Palette.emerald50, Palette.emerald400)
        case .blue: return (Palette.blue700, Palette.blue50, Palette.blue400)
        case .red: return (Palette.red600, Palette.red50, Palette.red400)
        case .amber: return (Palette.amber700, Palette.amber50, Palette.amber400)
        // The web's own greens: open #427425 on #f0f9ec; anything else #699a32 on #e6f3d8.
        case .open: return (Palette.moss700, Palette.moss50, Palette.willow400)
        case .quiet: return (Palette.willow600, Palette.willow100, Palette.sage400)
        }
    }

    var body: some View {
        let col = colors
        let fg = c.isDark ? col.night : col.text
        Text(text).font(NeemaFont.manrope(10, .semibold)).foregroundColor(fg).lineLimit(1)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 4, style: .continuous).fill(c.isDark ? fg.opacity(0.14) : col.bg))
    }
}

/// The web's StatBox: a KPI card with a coloured left edge (Android `StatBox`).
struct StatBox: View {
    let label: String
    let value: String
    let sub: String?
    let accent: Color
    @Environment(\.neema) private var c

    var body: some View {
        HStack(spacing: 0) {
            Rectangle().fill(accent).frame(width: 4)
            VStack(alignment: .leading, spacing: 0) {
                Text(label.uppercased()).font(NeemaFont.manrope(10, .semibold)).tracking(0.6).foregroundColor(c.muted).lineLimit(2)
                BigNumber(text: value, color: c.text).padding(.top, 6)
                if let s = sub { Text(s).font(NeemaFont.manrope(11)).foregroundColor(c.muted).lineLimit(2) }
            }
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.hairline))
    }
}

/// The web's MiniBar: bar height ∝ value, a 3pt floor for any non-zero day,
/// opacity rising with the value. Tapping a bar shows its "label: value" (the
/// web's hover title) (Android `MiniBar`).
struct MiniBar: View {
    let data: [BarPoint]
    let color: Color
    var format: (Double) -> String = { String(Int64($0)) }
    @Environment(\.neema) private var c
    @State private var picked: Int? = nil

    private var maxValue: Double { max(1, data.map { $0.value }.max() ?? 0) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(picked.map { "\(data[$0].label): \(format(data[$0].value))" } ?? " ").font(NeemaFont.manrope(11)).foregroundColor(c.textDim).frame(height: 16)
            GeometryReader { g in
                HStack(alignment: .bottom, spacing: 4) {
                    ForEach(Array(data.enumerated()), id: \.offset) { i, d in
                        VStack(spacing: 0) {
                            Spacer(minLength: 0)
                            if d.value > 0 {
                                let ratio = d.value / maxValue
                                TopRoundedBar(radius: 4).fill(color.opacity(0.7 + ratio * 0.3))
                                    .frame(height: max(3, g.size.height * CGFloat(ratio)))
                            }
                        }
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .contentShape(Rectangle())
                        .onTapGesture { picked = picked == i ? nil : i }
                    }
                }
            }
            .frame(height: 72)
            AxisLabels(labels: data.map { $0.label }, fontSize: 9, color: { _ in c.muted })
        }
        .onChange(of: data) { picked = nil }
    }
}

/// A bar with only its top corners rounded.
struct TopRoundedBar: Shape {
    let radius: CGFloat
    func path(in rect: CGRect) -> Path {
        let r = min(radius, rect.height / 2, rect.width / 2)
        var p = Path()
        p.move(to: CGPoint(x: rect.minX, y: rect.maxY))
        p.addLine(to: CGPoint(x: rect.minX, y: rect.minY + r))
        p.addArc(center: CGPoint(x: rect.minX + r, y: rect.minY + r), radius: r, startAngle: .degrees(180), endAngle: .degrees(270), clockwise: false)
        p.addLine(to: CGPoint(x: rect.maxX - r, y: rect.minY))
        p.addArc(center: CGPoint(x: rect.maxX - r, y: rect.minY + r), radius: r, startAngle: .degrees(270), endAngle: .degrees(0), clockwise: false)
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY))
        p.closeSubpath()
        return p
    }
}

/// One cell of a report table, drawn.
struct ReportCellView: View {
    let cell: ReportCell
    /// How many lines a text cell may take: one in a table row, two in a phone card (a phone number must not be cut).
    var lines: Int = 1
    var bold: Bool = false
    @Environment(\.neema) private var c

    var body: some View {
        switch cell {
        case .text(let s):
            Text(s).font(NeemaFont.manrope(12, bold ? .bold : .regular)).foregroundColor(c.text).lineLimit(lines)
        case .badge(let s, let hue):
            ReportBadge(text: s, hue: hue)
        case .role(let s):
            Text(s).font(NeemaFont.manrope(10, .semibold)).foregroundColor(c.gold2)
                .padding(.horizontal, 6).padding(.vertical, 2)
                .background(RoundedRectangle(cornerRadius: 4, style: .continuous).fill(c.goldDim))
                .overlay(RoundedRectangle(cornerRadius: 4, style: .continuous).stroke(c.border))
        case .presence(let on):
            HStack(spacing: 4) {
                Circle().fill(on ? c.gold : Palette.stone300).frame(width: 6, height: 6)
                Text(on ? "Online" : "Offline").font(NeemaFont.manrope(10, .medium)).foregroundColor(on ? c.gold : c.border2)
            }
        }
    }
}

/// The web's Table, in a panel: on a wide screen a real table; on a phone each
/// row becomes a card — the first column as its title, the rest as label/value
/// lines (Android `reportTable`). `width` is the panel's width.
struct ReportTableView: View {
    let model: TableModel
    let wide: Bool
    let width: CGFloat
    var emptyText: String = "No data"
    @Environment(\.neema) private var c

    private var fontScale: CGFloat { UIFontMetrics.default.scaledValue(for: 100) / 100 }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(model.header.uppercased()).font(NeemaFont.manrope(11, .bold)).tracking(0.6).foregroundColor(c.textDim)
                .padding(.horizontal, 16).padding(.vertical, 12)
            Hairline(color: c.bg3)
            if model.rows.isEmpty {
                Text(emptyText).font(NeemaFont.manrope(12)).foregroundColor(c.muted).frame(maxWidth: .infinity).padding(.vertical, 32)
            } else if wide {
                HStack(spacing: 0) {
                    ForEach(Array(model.cols.enumerated()), id: \.offset) { _, col in
                        Text(col.uppercased()).font(NeemaFont.manrope(10, .bold)).tracking(0.6).foregroundColor(c.muted).lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(.horizontal, 12).padding(.vertical, 10)
                Hairline(color: c.bg3)
                LazyVStack(spacing: 0) {
                    ForEach(Array(model.rows.enumerated()), id: \.offset) { i, row in
                        HStack(alignment: .center, spacing: 0) {
                            ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                                ReportCellView(cell: cell).frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .padding(.horizontal, 12).padding(.vertical, 10)
                        .id(model.keys[i])
                        Hairline(color: c.bg)
                    }
                }
            } else {
                // Two label/value pairs a line where they fit; one when the font is
                // large, so a phone number or a date is never cut.
                let perLine = width / max(1, fontScale) >= 240 ? 2 : 1
                LazyVStack(spacing: 8) {
                    ForEach(Array(model.rows.enumerated()), id: \.offset) { i, row in
                        card(row, perLine: perLine).id(model.keys[i])
                    }
                }
                .padding(.horizontal, 10).padding(.vertical, 10)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(c.bg2))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(c.hairline))
    }

    private func card(_ row: [ReportCell], perLine: Int) -> some View {
        let rest = Array(row.dropFirst().enumerated())
        let lines = stride(from: 0, to: rest.count, by: perLine).map { Array(rest[$0..<min($0 + perLine, rest.count)]) }
        return VStack(alignment: .leading, spacing: 8) {
            if let first = row.first { ReportCellView(cell: first, lines: 2, bold: true) }
            // The other columns as a two-up grid of small label over value.
            ForEach(Array(lines.enumerated()), id: \.offset) { _, pair in
                HStack(alignment: .top, spacing: 12) {
                    ForEach(pair, id: \.offset) { j, cell in
                        VStack(alignment: .leading, spacing: 3) {
                            Text((j + 1 < model.cols.count ? model.cols[j + 1] : "").uppercased())
                                .font(NeemaFont.manrope(9, .bold)).tracking(0.5).foregroundColor(c.muted).lineLimit(1)
                            ReportCellView(cell: cell, lines: 2)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    if pair.count < perLine { Color.clear.frame(maxWidth: .infinity) }
                }
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        // White like the web's table rows, so the -50 badge tints still read.
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.isDark ? c.hairline : c.bg3))
    }
}

/// The system share sheet for a file (the Android chooser's twin): Mail, Drive, WhatsApp, Files…
struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]
    var subject: String? = nil
    /// Called once the sheet is done; `completed` is false when the agent cancelled.
    let onDone: (Bool) -> Void

    func makeUIViewController(context: Context) -> UIActivityViewController {
        let vc = UIActivityViewController(activityItems: items, applicationActivities: nil)
        if let s = subject { vc.setValue(s, forKey: "subject") }
        vc.completionWithItemsHandler = { _, completed, _, _ in onDone(completed) }
        return vc
    }

    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
