import SwiftUI

/// The web's Panel (Android `Panel`): a white card with a hairline and 14pt corners.
struct PanelCard<Content: View>: View {
    var padding: CGFloat = 16
    @ViewBuilder let content: () -> Content
    @Environment(\.neema) private var c

    var body: some View {
        VStack(alignment: .leading, spacing: 0) { content() }
            .padding(padding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(c.bg2))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(c.hairline))
    }
}

/// A panel's title with a figure on the right (the web's `flex justify-between`).
/// When both can't share a line — a narrow phone at a large font — the figure
/// drops under the title rather than squeezing it into a word per line.
struct PanelHeadline<Title: View, Trailing: View>: View {
    @ViewBuilder let title: () -> Title
    @ViewBuilder let trailing: () -> Trailing

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: 8) {
                title()
                Spacer(minLength: 8)
                trailing()
            }
            VStack(alignment: .leading, spacing: 2) {
                title()
                trailing()
            }
        }
    }
}

/// A panel's uppercase title.
struct PanelTitle: View {
    let text: String
    @Environment(\.neema) private var c
    var body: some View {
        Text(text.uppercased()).font(NeemaFont.manrope(11, .semibold)).tracking(0.6).foregroundColor(c.muted)
    }
}

/// A thin progress bar (the web's h-1.5 rounded track).
struct ThinBar: View {
    let fraction: Double
    let color: Color
    @Environment(\.neema) private var c

    var body: some View {
        GeometryReader { g in
            ZStack(alignment: .leading) {
                Capsule().fill(c.bg3)
                Capsule().fill(color).frame(width: g.size.width * CGFloat(min(1, max(0, fraction))))
            }
        }
        .frame(height: 6)
        .animation(.easeOut(duration: 0.7), value: fraction)
    }
}

/// A headline figure (the web's `text-2xl font-bold tabular-nums`) that is
/// never cut: on a narrow card or at a large font it steps down in size
/// until the whole amount fits on one line, instead of "KES 98,7…".
struct BigNumber: View {
    let text: String
    let color: Color
    var max: CGFloat = 22
    var min: CGFloat = 12

    var body: some View {
        Text(text).font(NeemaFont.manrope(max, .bold)).monospacedDigit().foregroundColor(color)
            .lineLimit(1).minimumScaleFactor(min / max)
    }
}

/// Columns for a grid of cards: `max` when each cell keeps at least `minCell`
/// (scaled with the user's font size), else two, else one. So a 360pt phone
/// at 130% keeps two KPI cards a row, and at 200% gets one card per row
/// instead of labels chopped to "Pendin…" (Android `gridColumns`).
func gridColumns(width: CGFloat, max: Int, gap: CGFloat = 12, minCell: CGFloat = 120, minWideCell: CGFloat = 160, fontScale: CGFloat) -> Int {
    let scale = Swift.max(1, fontScale)
    func cell(_ n: Int) -> CGFloat { (width - gap * CGFloat(n - 1)) / CGFloat(n) }
    if max > 2 && cell(max) >= minWideCell * scale { return max }
    if max >= 2 && cell(2) >= minCell * scale { return 2 }
    return 1
}

/// Day labels under a bar chart, one slot per bar. When a slot is too narrow
/// for a three-letter day (14 bars on a small phone, or a large font), only
/// every 2nd / 3rd label is drawn — always including the last (today) — so no
/// label is chopped to "Mo" or "We" and they never run together.
struct AxisLabels: View {
    let labels: [String]
    var fontSize: CGFloat = 10
    var weight: (Int) -> NeemaFont.Weight = { _ in .regular }
    let color: (Int) -> Color

    var body: some View {
        GeometryReader { g in
            let n = max(1, labels.count)
            let slot = g.size.width / CGFloat(n)
            // The widest label at this size, plus 4pt of air to its neighbours.
            let longest = CGFloat(labels.map { $0.count }.max() ?? 0) * fontSize * 0.66 + 4
            let every = max(1, Int(ceil(longest / max(slot, 1))))
            HStack(spacing: 0) {
                ForEach(Array(labels.enumerated()), id: \.offset) { i, label in
                    Group {
                        if (labels.count - 1 - i) % every == 0 {
                            Text(label).font(NeemaFont.manrope(fontSize, weight(i))).foregroundColor(color(i)).lineLimit(1).fixedSize()
                        } else {
                            Color.clear
                        }
                    }
                    .frame(width: slot, height: g.size.height)
                }
            }
        }
        .frame(height: fontSize * 1.4)
        .padding(.top, 4)
    }
}

/// The web's icon paths stroked, not filled (heroicons' 24-box strokes).
struct SVGStrokeIcon: View {
    let d: String
    var size: CGFloat = 20
    /// The stroke width in the 24-unit box.
    var width: CGFloat = 1.8

    var body: some View {
        SVGShape(d: d).stroke(style: StrokeStyle(lineWidth: width * size / 24, lineCap: .round, lineJoin: .round))
            .frame(width: size, height: size)
    }
}
