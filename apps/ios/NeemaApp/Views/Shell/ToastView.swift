import SwiftUI
import NeemaCore

/// A 12 pt pill with a round badge: ✓ success and info (emerald), ! warning (amber), ✕ error (red).
struct ToastView: View {
    let toast: Toast
    @Environment(\.neema) private var c

    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                Circle().fill(badgeColor).frame(width: 20, height: 20)
                Image(systemName: badgeIcon).font(.system(size: 11, weight: .bold)).foregroundColor(.white)
            }
            Text(toast.message).font(NeemaFont.manrope(14, .medium)).foregroundColor(c.text).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(c.bg2))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(c.hairline))
        .shadow(color: .black.opacity(0.12), radius: 12, y: 4)
        .accessibilityAddTraits(.updatesFrequently)
    }

    private var badgeColor: Color {
        switch toast.type {
        case .success, .info: return Palette.emerald500
        case .warning: return Palette.amber500
        case .error: return Palette.red500
        }
    }

    private var badgeIcon: String {
        switch toast.type {
        case .success, .info: return "checkmark"
        case .warning: return "exclamationmark"
        case .error: return "xmark"
        }
    }
}

/// "You're offline" while the device has no network; "Back online" for 2.5 s after it returns.
struct ConnectivityBanner: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @State private var backOnline = false
    @State private var wasOffline = false

    var body: some View {
        VStack(spacing: 0) {
            if !app.online {
                banner(tone: Tone.warning(c.isDark), icon: "wifi.slash", title: "You're offline", body: "Showing what was last loaded. Check your connection.")
            } else if backOnline {
                banner(tone: Tone.moss(c.isDark), icon: "checkmark", title: "Back online", body: nil)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: app.online)
        .animation(.easeInOut(duration: 0.2), value: backOnline)
        .onChange(of: app.online) { up in
            if !up { wasOffline = true; backOnline = false; return }
            guard wasOffline else { return }
            wasOffline = false
            backOnline = true
            Task {
                try? await Task.sleep(nanoseconds: 2_500_000_000)
                backOnline = false
            }
        }
    }

    private func banner(tone: Tone, icon: String, title: String, body: String?) -> some View {
        HStack(spacing: 10) {
            Image(systemName: icon).foregroundColor(tone.accent)
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(NeemaFont.fixed(13, .semibold)).foregroundColor(tone.text)
                if let b = body { Text(b).font(NeemaFont.fixed(12)).foregroundColor(tone.text.opacity(0.85)) }
            }
            Spacer()
        }
        .padding(.horizontal, 16).padding(.vertical, 8)
        .background(tone.bg)
        .overlay(Rectangle().fill(tone.border).frame(height: 1), alignment: .bottom)
    }
}
