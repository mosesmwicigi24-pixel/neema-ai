import SwiftUI
import NeemaCore

/// The bell's list as SwiftUI reads it (Android's NotificationCenter items).
@MainActor
final class BellModel: ObservableObject {
    let center: AgentNotifications
    @Published private(set) var items: [AppNotification]
    @Published private(set) var alerts: AlertSettings
    private var subs: [Subscription] = []

    var unread: Int { items.filter { !$0.read }.count }

    init(center: AgentNotifications, prefs: AppPrefs) {
        self.center = center
        items = center.items.value
        alerts = prefs.alerts.value
        subs.append(center.items.observe { [weak self] v in onMainActor { self?.items = v } })
        subs.append(prefs.alerts.observe { [weak self] v in onMainActor { self?.alerts = v } })
    }

    func close() { subs.forEach { $0.cancel() }; subs = [] }
}

/// The bell's panel (Notifications.tsx; Android `NotificationsPanel`): header
/// with the unread count and "Mark all read", the list (unread rows tinted,
/// time top-right, a ✕ per row), the empty state, and a footer with the count
/// and "Clear all". Rendered in a bottom sheet on phones and as the web's
/// 316 pt popup beside the sidebar on wider windows.
struct NotificationsPanel: View {
    let items: [AppNotification]
    let onOpen: (AppNotification) -> Void
    let onMarkAllRead: () -> Void
    let onDismissItem: (String) -> Void
    let onClear: () -> Void
    var listMaxHeight: CGFloat = 360
    var now: Int64 = AppClock.now()
    /// "Muted until 3:40 PM" while message sounds are muted, else nil.
    var muteStatus: String? = nil
    /// Mute for a duration (nil = until turned back on); nil hides the control.
    var onMute: ((Int64?) -> Void)? = nil
    var onUnmute: () -> Void = {}
    /// The popup is white in both themes (the web's); the phone sheet follows the theme.
    var forceLight = false
    @Environment(\.neema) private var neema

    var body: some View {
        let dark = neema.isDark && !forceLight
        let c = PanelColors.of(dark)
        let unread = items.filter { !$0.read }.count
        VStack(spacing: 0) {
            HStack(spacing: 8) {
                Text("Notifications").font(NeemaFont.manrope(14, .semibold)).foregroundColor(c.title).accessibilityAddTraits(.isHeader)
                if unread > 0 {
                    Text("\(unread)").font(NeemaFont.capped(10, .bold, maxScale: 1.3)).foregroundColor(.white)
                        .padding(.horizontal, 6).padding(.vertical, 2).background(Capsule().fill(Palette.red500))
                        .accessibilityLabel("\(unread) unread")
                }
                Spacer()
                if let onMute = onMute { MuteControl(status: muteStatus, onMute: onMute, onUnmute: onUnmute, active: c.action, idle: c.faint) }
                if unread > 0 {
                    Button(action: onMarkAllRead) {
                        Text("Mark all read").font(NeemaFont.manrope(11, .semibold)).foregroundColor(c.action).padding(.horizontal, 8).frame(minHeight: 48)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.leading, 16).padding(.trailing, 8).frame(minHeight: 48)
            Hairline(color: c.divider)
            if items.isEmpty {
                VStack(spacing: 0) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 16).fill(c.emptyTile)
                        Text("🔔").font(NeemaFont.fixed(24))
                    }
                    .frame(width: 48, height: 48)
                    Text("All caught up").font(NeemaFont.manrope(14, .medium)).foregroundColor(c.title).padding(.top, 12)
                    Text("No new notifications").font(NeemaFont.manrope(12)).foregroundColor(c.faint).padding(.top, 2)
                }
                .frame(maxWidth: .infinity).padding(.vertical, 48).padding(.horizontal, 16)
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(items) { n in
                            let look = NotifLook.of(n.type, dark: dark)
                            HStack(alignment: .top, spacing: 0) {
                                Button { onOpen(n) } label: {
                                    HStack(alignment: .top, spacing: 12) {
                                        ZStack {
                                            RoundedRectangle(cornerRadius: 12).fill(look.bg)
                                            Text(look.emoji).font(NeemaFont.fixed(14)).foregroundColor(c.title)
                                        }
                                        .frame(width: 32, height: 32).padding(.top, 2)
                                        VStack(alignment: .leading, spacing: 2) {
                                            HStack(alignment: .top, spacing: 8) {
                                                Text(n.title).font(NeemaFont.manrope(12, .semibold)).foregroundColor(n.read ? c.readTitle : c.title)
                                                    .frame(maxWidth: .infinity, alignment: .leading)
                                                Text(Fmt.timeAgo(isoOf(n.at), now: now)).font(NeemaFont.manrope(10)).foregroundColor(c.faint).lineLimit(1).padding(.top, 2)
                                            }
                                            if !n.body.trimmingCharacters(in: .whitespaces).isEmpty {
                                                Text(n.body).font(NeemaFont.manrope(11)).lineSpacing(3).foregroundColor(c.body).lineLimit(2)
                                            }
                                        }
                                    }
                                    .padding(.leading, 16).padding(.vertical, 12)
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)
                                Button { onDismissItem(n.id) } label: {
                                    WebIcon(glyph: WebIcons.close, size: 12).foregroundColor(c.dismiss).frame(width: 48, height: 48).contentShape(Circle())
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel("Dismiss notification")
                            }
                            .padding(.trailing, 4)
                            .background(n.read ? Color.clear : c.unreadBg)
                            Hairline(color: c.rowDivider)
                        }
                    }
                }
                .frame(maxHeight: listMaxHeight)
                Hairline(color: c.divider)
                HStack {
                    Text("\(items.count) notification\(items.count == 1 ? "" : "s")").font(NeemaFont.manrope(11)).foregroundColor(c.faint)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    Button(action: onClear) {
                        Text("Clear all").font(NeemaFont.manrope(11, .medium)).foregroundColor(c.faint).padding(.horizontal, 8).frame(minHeight: 48)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.leading, 16).padding(.trailing, 8)
            }
        }
        .background(c.bg)
    }
}

/// The notification's arrival as the formatter reads it.
private func isoOf(_ millis: Int64) -> String {
    ISO8601DateFormatter().string(from: Date(timeIntervalSince1970: Double(millis) / 1000))
}

/// The bell's speaker: one tap away from quiet. Muted, it shows crossed out
/// and offers Unmute; otherwise it offers 1 hour / 8 hours / until turned back
/// on. Mute silences message sounds and buzzes only — calls still ring.
private struct MuteControl: View {
    let status: String?
    let onMute: (Int64?) -> Void
    let onUnmute: () -> Void
    let active: Color
    let idle: Color
    var body: some View {
        Menu {
            if let s = status {
                Text(s)
                Button("Unmute", action: onUnmute)
                Text("Or mute for")
            } else {
                Text("Mute message sounds")
            }
            ForEach(Array(MUTE_CHOICES.enumerated()), id: \.offset) { _, choice in
                Button(choice.label) { onMute(choice.ms) }
            }
        } label: {
            Image(systemName: status != nil ? "speaker.slash" : "speaker.wave.2").font(.system(size: 17))
                .foregroundColor(status != nil ? active : idle).frame(width: 44, height: 44).contentShape(Rectangle())
        }
        .accessibilityLabel(status ?? "Mute message sounds")
    }
}

private struct NotifLook {
    let emoji: String
    let bg: Color
    static func of(_ type: String, dark: Bool) -> NotifLook {
        switch AgentNotifications.kindOf(type) {
        case "intercept": return NotifLook(emoji: "⚡", bg: dark ? Color(hex: 0xD97706, alpha: 0.2) : Palette.amberTint)
        case "new_message": return NotifLook(emoji: "💬", bg: dark ? Color(hex: 0x2563EB, alpha: 0.2) : Palette.blue50)
        case "order": return NotifLook(emoji: "📦", bg: dark ? Palette.green600.opacity(0.2) : Color(hex: 0xF0FDF4))
        // META's colours are never applied on the web: ⇄ is plain page text.
        case "transfer": return NotifLook(emoji: "⇄", bg: dark ? Palette.violet600.opacity(0.2) : Palette.violet50)
        default: return NotifLook(emoji: "ℹ️", bg: dark ? Palette.slate500.opacity(0.2) : Palette.slate50)
        }
    }
}

/// Notifications.tsx's colours, with its faintest greys lifted to the sage that clears 4.3:1.
private struct PanelColors {
    let bg, divider, rowDivider, title, readTitle, body, faint, unreadBg, dismiss, emptyTile, action: Color
    static func of(_ dark: Bool) -> PanelColors {
        dark ? PanelColors(bg: Palette.prussian900, divider: Palette.prussian800, rowDivider: Palette.prussian850,
                           title: Palette.willow50, readTitle: Palette.sage400, body: Palette.sage400,
                           faint: Palette.nightMuted, unreadBg: Palette.willow500.opacity(0.08), dismiss: Palette.nightMuted,
                           emptyTile: Palette.indigo900, action: Palette.willow500)
             : PanelColors(bg: .white, divider: Palette.hairline2, rowDivider: Palette.mist,
                           title: Palette.ink, readTitle: Palette.sage500, body: Palette.sage500,
                           faint: Palette.sage500, unreadBg: Palette.sproutTint, dismiss: Palette.sage500, emptyTile: Palette.mist,
                           action: Palette.moss700)
    }
}

/// The bell's popup beside the sidebar (wide windows) or its sheet (phones), wired to the app.
struct BellHost: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    let wide: Bool
    /// Wide only: where the popup drops from (the rail or the full sidebar).
    var collapsed = false

    var body: some View {
        if let bell = app.bell {
            BellHostBody(bell: bell, wide: wide, collapsed: collapsed)
        }
    }
}

private struct BellHostBody: View {
    @ObservedObject var bell: BellModel
    let wide: Bool
    let collapsed: Bool
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    private func panel(maxList: CGFloat, forceLight: Bool) -> some View {
        NotificationsPanel(
            items: bell.items,
            onOpen: { app.openNotification($0) },
            onMarkAllRead: { bell.center.markAllRead() },
            onDismissItem: { bell.center.dismiss($0) },
            onClear: { bell.center.clear() },
            listMaxHeight: maxList,
            muteStatus: muteStatus(until: bell.alerts.mutedUntil, now: AppClock.now()),
            onMute: { app.container.prefs.muteFor($0) },
            onUnmute: { app.container.prefs.unmute() },
            forceLight: forceLight
        )
    }

    var body: some View {
        if wide {
            // The web's bell popup: 316 pt and white in both themes. Expanded, it
            // drops 6 pt below the bell; on the rail it opens right of the bell.
            ZStack(alignment: .topLeading) {
                if app.bellOpen {
                    Color.black.opacity(0.001).ignoresSafeArea().onTapGesture { app.bellOpen = false }
                    panel(maxList: 360, forceLight: true)
                        .frame(width: 316)
                        .background(RoundedRectangle(cornerRadius: 14).fill(Color.white))
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Palette.hairline, lineWidth: 1))
                        .shadow(color: .black.opacity(0.18), radius: 16, y: 8)
                        .padding(.leading, collapsed ? 58 : 130).padding(.top, collapsed ? 50 : 52)
                        .environment(\.neema, NeemaColors.light)
                        .transition(.opacity)
                }
            }
            .animation(.easeInOut(duration: 0.15), value: app.bellOpen)
        } else {
            Color.clear.frame(width: 0, height: 0)
                .sheet(isPresented: $app.bellOpen) {
                    panel(maxList: 520, forceLight: false)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                        .background(ChromeColors.of(c).bar)
                        .environment(\.neema, c)
                        .environmentObject(app)
                        .presentationDetents([.medium, .large])
                        .presentationDragIndicator(.visible)
                }
        }
    }
}
