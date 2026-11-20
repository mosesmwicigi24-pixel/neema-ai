import SwiftUI

/// The app's own text size (owner, 2026-11-20: "a button where you can enlarge
/// or reduce the fonts; that setting affects the entire app"). One Dynamic Type
/// size applied at the root, so every font built with `NeemaFont.manrope`
/// (relative to `.body`) and every system text style follows it. Until the
/// agent picks a size, the device's own text size stands.
enum TextSize {
    static let key = "neema.textSize"
    static let steps: [DynamicTypeSize] = [.xSmall, .small, .medium, .large, .xLarge, .xxLarge, .xxxLarge, .accessibility1, .accessibility2]

    /// The chosen step, or nil to follow the device.
    static func size(_ index: Int) -> DynamicTypeSize? { steps.indices.contains(index) ? steps[index] : nil }

    static func index(of s: DynamicTypeSize) -> Int {
        if let i = steps.firstIndex(of: s) { return i }
        return s < steps[0] ? 0 : steps.count - 1
    }

    /// Roughly how large body text is against the standard size.
    static func label(_ s: DynamicTypeSize) -> String {
        let pct: [DynamicTypeSize: Int] = [.xSmall: 82, .small: 88, .medium: 94, .large: 100, .xLarge: 112,
                                           .xxLarge: 124, .xxxLarge: 135, .accessibility1: 160, .accessibility2: 190]
        return "\(pct[s] ?? 100)%"
    }
}

/// Applies the chosen size to everything under it. Always the same modifier
/// (the device's size when nothing is chosen), so changing it never resets
/// the screens underneath.
struct AppTextSize: ViewModifier {
    @AppStorage(TextSize.key) private var index = -1
    @Environment(\.dynamicTypeSize) private var device

    func body(content: Content) -> some View {
        content.dynamicTypeSize(TextSize.size(index) ?? device)
    }
}

/// "Text size   A−  100%  A+" — Profile → Appearance.
struct TextSizeRow: View {
    @AppStorage(TextSize.key) private var index = -1
    @Environment(\.dynamicTypeSize) private var current
    @Environment(\.neema) private var c

    var body: some View {
        let i = TextSize.index(of: current)
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Text size").font(NeemaFont.manrope(14, .medium)).foregroundColor(c.text)
                Text("Makes every screen's text larger or smaller").font(NeemaFont.manrope(12)).foregroundColor(c.muted)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            step("A−", size: 13, label: "Smaller text", enabled: i > 0) { index = i - 1 }
            Text(TextSize.label(current)).font(NeemaFont.fixed(13, .semibold)).foregroundColor(c.text)
                .frame(minWidth: 48).accessibilityLabel("Text size \(TextSize.label(current))")
            step("A+", size: 17, label: "Larger text", enabled: i < TextSize.steps.count - 1) { index = i + 1 }
        }
        .frame(minHeight: 48)
    }

    private func step(_ text: String, size: CGFloat, label: String, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(text).font(NeemaFont.fixed(size, .bold)).foregroundColor(enabled ? c.text : c.muted)
                .frame(width: 44, height: 44)
                .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.border))
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
        .accessibilityLabel(label)
    }
}
