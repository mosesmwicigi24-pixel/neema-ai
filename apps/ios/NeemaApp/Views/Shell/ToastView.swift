import SwiftUI
import NeemaCore

/// The web's single toast (components/ui/Toast.tsx): a tinted pill with a
/// round ✓ / ! / ✕ badge. Success and info share the emerald look, as on the
/// web. Phones show it 96 pt up (above the bottom nav), full width less
/// 16 pt gutters; wider windows pin it top-right (288–384 pt). The shell
/// clears it after 3.5 s. VoiceOver reads it as it changes.
struct ToastView: View {
    let toast: Toast
    @Environment(\.neema) private var c

    var body: some View {
        let look = tone
        HStack(spacing: 8) {
            ZStack {
                Circle().fill(look.accent).frame(width: 20, height: 20)
                WebIcon(glyph: glyph, size: 12).foregroundColor(.white)
            }
            Text(toast.message).font(NeemaFont.manrope(14, .medium)).foregroundColor(look.text).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 16).padding(.vertical, 12)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(look.bg))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(look.border))
        .shadow(color: .black.opacity(0.15), radius: 8, y: 3)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(.updatesFrequently)
    }

    private var tone: Tone {
        switch toast.type {
        case .error: return Tone.error(c.isDark)
        case .warning: return Tone.warning(c.isDark)
        default: return Tone.success(c.isDark)
        }
    }

    private var glyph: WebGlyph {
        switch toast.type {
        case .error: return WebIcons.close
        case .warning: return WebIcons.exclamation
        default: return WebIcons.check
        }
    }
}

/// A slim bar across the top of the content while the device has no network
/// (app-only: the web leans on the browser's own): whatever is on screen stays
/// (it's what was last loaded), and the bar says so. When the network returns
/// it turns moss, says "Back online" and folds away after 2.5 s.
struct ConnectivityBanner: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @State private var backOnline = false
    @State private var wasOffline = false

    var body: some View {
        VStack(spacing: 0) {
            if !app.online {
                bar(tone: Tone.warning(c.isDark), offline: true)
            } else if backOnline {
                bar(tone: Tone.moss(c.isDark), offline: false)
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

    /// The bar itself: amber while offline, moss once back, a solid badge for the icon.
    private func bar(tone: Tone, offline: Bool) -> some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                ZStack {
                    Circle().fill(tone.accent).frame(width: 24, height: 24)
                    WebIcon(glyph: offline ? WebIcons.wifiOff : WebIcons.check, size: offline ? 14 : 12).foregroundColor(.white)
                }
                VStack(alignment: .leading, spacing: 1) {
                    Text(offline ? "You're offline" : "Back online").font(NeemaFont.manrope(13, .semibold)).foregroundColor(tone.text)
                    if offline {
                        Text("Showing what was last loaded. Check your connection.").font(NeemaFont.manrope(12)).foregroundColor(tone.text)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16).padding(.vertical, 8)
            Hairline(color: tone.border)
        }
        .background(tone.bg)
        .accessibilityElement(children: .combine)
    }
}
