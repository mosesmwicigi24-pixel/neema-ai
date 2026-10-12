import SwiftUI
import NeemaCore

// The states every data screen shares (Android `core/ui/components/Common.kt`
// and `feature/orders/SalesErrorViews.kt`): loading, empty, error, a stale
// banner over data that failed to refresh, an inline error, the web Modal's
// title bar and drag handle, and the status badges' tones.

/// A centred spinner (Android `Loading`).
struct LoadingView: View {
    @Environment(\.neema) private var c
    var body: some View {
        ProgressView().progressViewStyle(.circular).tint(c.gold).scaleEffect(1.3)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityLabel("Loading")
    }
}

/// Icon, title, subtitle and an optional action, centred (Android `EmptyState`).
struct EmptyStateView<Action: View>: View {
    let title: String
    let subtitle: String?
    let icon: String
    let action: () -> Action
    @Environment(\.neema) private var c

    init(title: String, subtitle: String? = nil, icon: String = "tray", @ViewBuilder action: @escaping () -> Action) {
        self.title = title; self.subtitle = subtitle; self.icon = icon; self.action = action
    }

    var body: some View {
        VStack(spacing: 0) {
            Image(systemName: icon).font(.system(size: 36, weight: .regular)).foregroundColor(c.muted)
            Text(title).font(NeemaFont.titleSmall).foregroundColor(c.text).multilineTextAlignment(.center).padding(.top, 10)
            if let s = subtitle {
                Text(s).font(NeemaFont.bodySmall).foregroundColor(c.muted).multilineTextAlignment(.center).padding(.top, 4)
            }
            action().padding(.top, 12)
        }
        .frame(maxWidth: .infinity)
        .padding(32)
    }
}

extension EmptyStateView where Action == EmptyView {
    init(title: String, subtitle: String? = nil, icon: String = "tray") {
        self.init(title: title, subtitle: subtitle, icon: icon, action: { EmptyView() })
    }
}

/// Nothing was ever read: "Couldn't load", why, and Retry (Android `ErrorState`).
struct ErrorStateView: View {
    let message: String
    var onRetry: (() -> Void)? = nil

    var body: some View {
        EmptyStateView(title: "Couldn't load", subtitle: message, icon: "exclamationmark.circle") {
            if let r = onRetry { WebBtn(label: "Retry", variant: .outline, size: .md, action: r) }
        }
    }
}

/// A refresh failed while data is on screen: the data stays, and this thin
/// amber line over it says why, with a Retry (Android `StaleBanner`).
struct StaleBanner: View {
    let reason: String
    let onRetry: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let fg = c.isDark ? Palette.amber300 : Palette.amber800
        HStack(spacing: 8) {
            Image(systemName: "icloud.slash").font(.system(size: 14, weight: .medium)).foregroundColor(fg)
            VStack(alignment: .leading, spacing: 1) {
                Text("Couldn't refresh — showing what was loaded").font(NeemaFont.manrope(12, .semibold)).foregroundColor(fg)
                Text(reason).font(NeemaFont.manrope(12)).foregroundColor(fg.opacity(0.85))
            }
            .padding(.vertical, 6)
            Spacer(minLength: 4)
            Button(action: onRetry) {
                Text("Retry").font(NeemaFont.manrope(12, .semibold)).foregroundColor(fg).padding(.horizontal, 10).padding(.vertical, 8)
            }
            .accessibilityLabel("Retry refreshing")
        }
        .padding(.leading, 12).padding(.trailing, 4).padding(.vertical, 4)
        .background(RoundedRectangle(cornerRadius: 10, style: .continuous).fill(c.isDark ? Palette.amber950.opacity(0.45) : Palette.amber50))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).stroke(c.isDark ? c.amber.opacity(0.35) : Palette.amber200))
    }
}

/// An action's failure shown where the operator is typing (a sheet or dialog),
/// so it is never missed. `pending`: not a failure yet — the outcome is being
/// checked — so it reads amber, not red (Android `InlineError`).
struct InlineError: View {
    let message: String
    var pending: Bool = false
    @Environment(\.neema) private var c

    var body: some View {
        let fg = pending ? (c.isDark ? Palette.amber300 : Palette.amber800) : (c.isDark ? Palette.red300 : Palette.red700)
        let bg = pending ? (c.isDark ? Palette.amber950.opacity(0.45) : Palette.amber50) : (c.isDark ? Palette.red950.opacity(0.45) : Palette.red50)
        Text(message).font(NeemaFont.manrope(12)).foregroundColor(fg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 10).padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(bg))
    }
}

/// The web's bottom-sheet grab bar.
struct WebDragHandle: View {
    @Environment(\.neema) private var c
    var body: some View {
        RoundedRectangle(cornerRadius: 2).fill(c.muted.opacity(0.4)).frame(width: 32, height: 4).padding(.vertical, 10)
    }
}

/// The web Modal's header: `text-base font-semibold` title, a ✕ button, a hairline beneath.
struct ModalTitleBar: View {
    let title: String
    let onClose: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                Text(title).font(NeemaFont.manrope(16, .semibold)).foregroundColor(c.text).lineLimit(2).padding(.vertical, 8)
                Spacer(minLength: 8)
                Button(action: onClose) {
                    Image(systemName: "xmark").font(.system(size: 14, weight: .medium)).foregroundColor(c.isDark ? c.muted : Palette.gray400)
                        .frame(width: 48, height: 48)
                }
                .accessibilityLabel("Close")
            }
            .padding(.leading, 20).padding(.trailing, 4).padding(.bottom, 4)
            Hairline(color: c.isDark ? c.hairline : Palette.gray100)
        }
    }
}

/// A small upper-case caption over a section (the sheets' "HUB", "ITEMS").
struct SectionLabel: View {
    let text: String
    @Environment(\.neema) private var c
    var body: some View {
        Text(text.uppercased()).font(NeemaFont.manrope(10, .bold)).tracking(1).foregroundColor(c.textDim)
            .frame(maxWidth: .infinity, alignment: .leading).padding(.bottom, 8)
    }
}

/// A label over a value in a soft bordered cell (the detail's meta grid).
struct MetaCell: View {
    let label: String
    let value: String
    @Environment(\.neema) private var c
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label.uppercased()).font(NeemaFont.manrope(9, .bold)).tracking(0.8).foregroundColor(c.textDim)
            Text(value).font(NeemaFont.manrope(12, .semibold)).foregroundColor(c.text).lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(c.bg))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(c.bg3))
    }
}

/// A status tone's colours: the web's `text-amber-700 bg-amber-50 border-amber-200`
/// badges; in dark mode the pale tint would glare, so it becomes a translucent
/// wash of the dot colour (Android `Tone` + `toneBg`/`toneBorder`/`toneText`).
struct ToneLook {
    let text: Color, bg: Color, border: Color, dot: Color

    static func of(_ tone: StatusTone) -> ToneLook {
        switch tone {
        case .amber: return ToneLook(text: Palette.amber700, bg: Palette.amber50, border: Palette.amber200, dot: Palette.amber400)
        case .blue: return ToneLook(text: Palette.blue700, bg: Palette.blue50, border: Palette.blue200, dot: Palette.blue400)
        case .emerald: return ToneLook(text: Palette.emerald700, bg: Palette.emerald50, border: Palette.emerald200, dot: Palette.emerald400)
        case .red: return ToneLook(text: Palette.red700, bg: Palette.red50, border: Palette.red200, dot: Palette.red400)
        case .sky: return ToneLook(text: Palette.sky700, bg: Palette.sky50, border: Palette.sky200, dot: Palette.sky400)
        case .green: return ToneLook(text: Palette.green700, bg: Palette.green50, border: Palette.green200, dot: Palette.green400)
        }
    }

    func bg(_ dark: Bool) -> Color { dark ? dot.opacity(0.14) : bg }
    func border(_ dark: Bool) -> Color { dark ? dot.opacity(0.35) : border }
    func text(_ dark: Bool) -> Color { dark ? dot : text }
}

/// A small bordered status badge (the list's `text-[10px] rounded border` chips; Android `Badge`).
struct StatusBadge: View {
    let text: String
    let tone: StatusTone
    var fontSize: CGFloat = 10
    var radius: CGFloat = 4
    var hPad: CGFloat = 6
    var vPad: CGFloat = 2
    @Environment(\.neema) private var c

    var body: some View {
        let look = ToneLook.of(tone)
        Text(text).font(NeemaFont.manrope(fontSize, .semibold)).foregroundColor(look.text(c.isDark)).lineLimit(1)
            .padding(.horizontal, hPad).padding(.vertical, vPad)
            .background(RoundedRectangle(cornerRadius: radius, style: .continuous).fill(look.bg(c.isDark)))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous).stroke(look.border(c.isDark)))
    }
}

/// A figure that must never break inside itself ("KES" on one line, the digits on the next).
extension String {
    var unbroken: String { replacingOccurrences(of: " ", with: "\u{00A0}") }
}
