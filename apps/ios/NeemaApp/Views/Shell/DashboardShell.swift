import SwiftUI
import NeemaCore

/// app/dashboard/page.tsx (Android `DashboardShell`). Windows under 600 pt (a
/// phone) get the web's mobile header, a bottom bar with the four most-used
/// views and the navy sidebar as a drawer from the start edge; under 1200 pt
/// (an iPad upright, Split View) the sidebar docks as its 60 pt icon rail so
/// the view keeps its width; wider windows dock the full 208 pt sidebar. The
/// toggle still switches it, and the choice holds until the window crosses
/// into the other mode (rotation, resizing a split) — then the new window's
/// own default applies.
struct DashboardShell: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    var body: some View {
        GeometryReader { g in
            let mode = navMode(for: Int(g.size.width))
            Group {
                if mode == .drawer {
                    MobileShell()
                } else {
                    WideShell(mode: mode)
                }
            }
            .frame(width: g.size.width, height: g.size.height)
        }
        .background(c.surface.ignoresSafeArea())
    }
}

/// Which view is on screen.
struct CurrentView: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        switch app.view {
        case .conversations: InboxScreen()
        case .calls: ViewPlaceholder(view: .calls, cycle: 5, note: "The call log, details, transcripts and the softphone.")
        case .orders: OrdersScreen()
        case .reports: ReportsScreen()
        case .deals: DealsScreen()
        case .leads: LeadsScreen()
        case .overview: OverviewScreen()
        case .catalog: CatalogScreen()
        case .agents: TeamScreen()
        case .settings: SettingsScreen()
        case .profile: ProfileScreen()
        }
    }
}

// ── Phone ─────────────────────────────────────────────────────────────────────

struct MobileShell: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    var body: some View {
        ZStack(alignment: .bottom) {
            VStack(spacing: 0) {
                if !app.immersive { MobileHeader() }
                ConnectivityBanner()
                CurrentView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                if !app.immersive { MobileBottomNav() }
            }
            // Clear of the bottom nav (or, in an immersive thread, of the composer).
            if let t = app.toast {
                ToastView(toast: t)
                    .padding(.horizontal, 16)
                    .padding(.bottom, app.immersive ? 24 : 96)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: app.toast?.id)
        // The navy sidebar as a drawer from the start edge: 272 pt, rounded end corners, over a scrim.
        .overlay {
            DrawerHost(open: $app.drawerOpen, width: 272) { SidebarView(docked: false) }
        }
    }
}

/// A modal navigation drawer (Android `ModalNavigationDrawer`): slides in
/// from the start edge over a scrim; a tap on the scrim, a swipe back, or
/// picking a view closes it.
struct DrawerHost<Content: View>: View {
    @Binding var open: Bool
    let width: CGFloat
    @ViewBuilder let content: () -> Content
    @State private var drag: CGFloat = 0

    var body: some View {
        ZStack(alignment: .leading) {
            if open {
                Color.black.opacity(0.32).ignoresSafeArea()
                    .onTapGesture { open = false }
                    .transition(.opacity)
                    .accessibilityLabel("Close navigation menu")
                    .accessibilityAddTraits(.isButton)
                content()
                    .frame(width: width)
                    .frame(maxHeight: .infinity)
                    .background(EndRoundedRect(radius: 18).fill(Brand.navy).ignoresSafeArea())
                    .compositingGroup()
                    .shadow(color: .black.opacity(0.25), radius: 16)
                    .offset(x: min(0, drag))
                    .gesture(
                        DragGesture(minimumDistance: 12)
                            .onChanged { v in drag = v.translation.width }
                            .onEnded { v in
                                if v.translation.width < -width * 0.3 || v.predictedEndTranslation.width < -width { open = false }
                                drag = 0
                            }
                    )
                    .transition(.move(edge: .leading))
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
        .animation(.easeInOut(duration: 0.22), value: open)
    }
}

/// A rectangle whose end (trailing) corners are rounded — the drawer's sheet shape.
struct EndRoundedRect: Shape {
    let radius: CGFloat
    func path(in rect: CGRect) -> Path {
        let r = min(radius, rect.height / 2, rect.width / 2)
        var p = Path()
        p.move(to: CGPoint(x: rect.minX, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX - r, y: rect.minY))
        p.addArc(center: CGPoint(x: rect.maxX - r, y: rect.minY + r), radius: r, startAngle: .degrees(270), endAngle: .degrees(0), clockwise: false)
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - r))
        p.addArc(center: CGPoint(x: rect.maxX - r, y: rect.maxY - r), radius: r, startAngle: .degrees(0), endAngle: .degrees(90), clockwise: false)
        p.addLine(to: CGPoint(x: rect.minX, y: rect.maxY))
        p.closeSubpath()
        return p
    }
}

/// components/ui/MobileNav.tsx MobileHeader, plus ☰ for the sidebar drawer:
/// a flat 28 pt amber mark, "Neema · {view}", then the bell and the theme
/// switch as 48 pt touch targets around the web's glyphs. White by day; the
/// Prussian surface by night. At very large text sizes the "Neema ·" wordmark
/// gives its room to the view's name. The bell's list arrives in cycle 5.
struct MobileHeader: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    private var roomy: Bool { teamFontScale < 1.5 }

    var body: some View {
        let chrome = ChromeColors.of(c)
        VStack(spacing: 0) {
            HStack(spacing: 0) {
                Button { app.drawerOpen = true } label: {
                    WebIcon(glyph: WebIcons.menu, size: 20).foregroundColor(chrome.icon).frame(width: 48, height: 48).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Open navigation menu")
                NeemaLogo(size: 28, corner: 8, glow: false)
                Spacer().frame(width: 12)
                if roomy {
                    Text("Neema").font(NeemaFont.capped(14, .semibold, maxScale: 1.5)).foregroundColor(chrome.title).lineLimit(1)
                    Spacer().frame(width: 12)
                    Text("·").font(NeemaFont.capped(14, maxScale: 1.5)).foregroundColor(chrome.separator)
                    Spacer().frame(width: 12)
                }
                Text(app.view.label)
                    .font(NeemaFont.capped(14, roomy ? .medium : .semibold, maxScale: 1.5))
                    .foregroundColor(roomy ? chrome.subtitle : chrome.title)
                    .lineLimit(1)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .accessibilityAddTraits(.isHeader)
                if !app.connected && app.online { OfflineDot().padding(.trailing, 4) }
                HeaderBell(count: 0) {}
                Button { app.setDark(!app.dark) } label: {
                    WebIcon(glyph: app.dark ? WebIcons.sun : WebIcons.moon, size: 18).foregroundColor(chrome.icon)
                        .frame(width: 48, height: 48).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(app.dark ? "Switch to light mode" : "Switch to dark mode")
            }
            .padding(.horizontal, 4)
            .frame(minHeight: 56)
            Hairline(color: chrome.line)
        }
        .background(chrome.bar)
    }
}

/// The header's bell: the web's 18 pt glyph in a 48 pt target, a red count
/// ("9+" past nine) just off its top-right corner.
struct HeaderBell: View {
    let count: Int
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let chrome = ChromeColors.of(c)
        Button(action: action) {
            ZStack(alignment: .topTrailing) {
                WebIcon(glyph: WebIcons.bell, size: 18).foregroundColor(chrome.icon).frame(width: 48, height: 48)
                if count > 0 {
                    Text(count > 9 ? "9+" : String(count)).font(NeemaFont.capped(10, .semibold, maxScale: 1.2)).foregroundColor(.white)
                        .padding(.horizontal, 4).frame(minWidth: 16, minHeight: 16)
                        .background(Capsule().fill(Palette.red500))
                        .padding(.top, 6).padding(.trailing, 6)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(count > 0 ? "Notifications, \(count) unread" : "Notifications")
    }
}

/// components/ui/MobileNav.tsx MobileBottomNav: 56 pt, 20 pt icons over 10 pt
/// labels, amber when active with a 2 pt indicator across the middle half,
/// an amber count 8 pt right of centre. The web shows the first five views;
/// the app shows four and a "More" that opens the drawer, so every view is
/// reachable. Labels and counts grow with the text size up to 130% so they
/// stay inside the bar.
struct MobileBottomNav: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    var body: some View {
        let chrome = ChromeColors.of(c)
        let items = Array(app.navItems.prefix(4))
        let moreActive = app.navItems.dropFirst(4).contains { $0.view == app.view }
        VStack(spacing: 0) {
            Hairline(color: chrome.line)
            HStack(spacing: 0) {
                ForEach(items, id: \.view) { item in
                    BottomTab(glyph: WebIcons.icon(for: item.view), label: item.view.label, badge: item.badge, active: item.view == app.view) {
                        app.navigate(item.view)
                    }
                }
                BottomTab(glyph: WebIcons.more, label: "More", badge: 0, active: moreActive) { app.drawerOpen = true }
            }
            .frame(height: 56)
        }
        .background(chrome.bar)
    }
}

struct BottomTab: View {
    let glyph: WebGlyph
    let label: String
    let badge: Int
    let active: Bool
    let action: () -> Void
    @Environment(\.neema) private var c

    var body: some View {
        let chrome = ChromeColors.of(c)
        let tint = active ? chrome.active : chrome.subtitle
        Button(action: action) {
            ZStack(alignment: .top) {
                if active {
                    GeometryReader { g in
                        RoundedRectangle(cornerRadius: 1).fill(Brand.amber)
                            .frame(width: g.size.width / 2, height: 2)
                            .position(x: g.size.width / 2, y: 1)
                    }
                }
                VStack(spacing: 4) {
                    WebIcon(glyph: glyph, size: 20).foregroundColor(tint)
                    Text(label).font(NeemaFont.capped(10, active ? .semibold : .medium, maxScale: 1.3)).foregroundColor(tint).lineLimit(1)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                // top-2 left-1/2 ml-2: the count starts 8 pt right of the tab's centre, 6 pt down.
                if badge > 0 {
                    HStack(spacing: 0) {
                        Color.clear.frame(maxWidth: .infinity, maxHeight: 1)
                        AmberBadge(count: badge, style: .bottomNav).padding(.leading, 6)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(.top, 6)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(badge > 0 ? "\(label), \(badge) new" : label)
        .accessibilityAddTraits(active ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }
}

// ── Wide ──────────────────────────────────────────────────────────────────────

struct WideShell: View {
    let mode: NavMode
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @State private var collapsed = false
    @State private var collapsedFor: NavMode? = nil

    /// The docked sidebar widens with large text (up to 130%) so its labels keep their room.
    private var dockedWidth: CGFloat { 208 * min(1.3, max(1, teamFontScale)) }

    var body: some View {
        ZStack(alignment: .topTrailing) {
            HStack(spacing: 0) {
                // An immersive view (an open thread) takes the whole window.
                if !app.immersive {
                    SidebarView(docked: true, collapsed: $collapsed)
                        .frame(width: collapsed ? 60 : dockedWidth)
                }
                VStack(spacing: 0) {
                    ConnectivityBanner()
                    CurrentView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .background(c.surface)
            }
            // Navy runs under the status bar across the whole width, framing the view like the web's full-height sidebar does.
            .background(Brand.navy.ignoresSafeArea(edges: .top))
            if let t = app.toast {
                ToastView(toast: t)
                    .frame(minWidth: 288, maxWidth: 384)
                    .padding(20)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
            // Online but the live socket is down: it is on its way back.
            if !app.connected && app.online {
                OfflineDot().padding(10).padding(.top, app.toast == nil ? 0 : 64)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: app.toast?.id)
        .onAppear { applyDefault() }
        .onChange(of: mode) { _ in applyDefault() }
    }

    /// Windows under 1200 pt open on the icon rail so the view keeps its width; the choice holds until the mode changes.
    private func applyDefault() {
        if collapsedFor != mode {
            collapsed = mode == .rail
            collapsedFor = mode
        }
    }
}

// ── The sidebar ───────────────────────────────────────────────────────────────

/// components/ui/Sidebar.tsx: navy rail, "Neema AI · Admin Portal", the
/// bell, amber active pill with badges, and the account menu in the footer.
/// `collapsed` shows the 60 pt icon rail (docked only; the phone drawer is
/// always expanded). Sizes are the web's, in points.
struct SidebarView: View {
    @EnvironmentObject private var app: AppModel
    var docked: Bool
    var collapsed: Binding<Bool>? = nil

    private var isCollapsed: Bool { docked && (collapsed?.wrappedValue ?? false) }

    var body: some View {
        VStack(spacing: 0) {
            header
            Hairline(color: Brand.navyBorder)
            ScrollView {
                VStack(spacing: 2) {
                    if isCollapsed, let collapsed = collapsed {
                        // The web's full-width "Expand sidebar" button above the items.
                        Button { collapsed.wrappedValue = false } label: {
                            WebIcon(glyph: WebIcons.expand, size: 14).foregroundColor(Brand.textMuted)
                                .frame(maxWidth: .infinity).frame(height: 48).contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .padding(.bottom, 6)
                        .accessibilityLabel("Expand sidebar")
                    }
                    ForEach(app.navItems, id: \.view) { item in navRow(item) }
                }
                .padding(.horizontal, isCollapsed ? 6 : 8).padding(.vertical, 8)
            }
            Hairline(color: Brand.navyBorder)
            footer
        }
        .background { if docked { Brand.navy.ignoresSafeArea() } }
    }

    @ViewBuilder private var header: some View {
        if isCollapsed {
            VStack(spacing: 6) {
                NeemaLogo()
                BellButton(count: 0, compact: true) {}
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 12).padding(.bottom, 8)
        } else {
            HStack(spacing: 4) {
                NeemaLogo()
                VStack(alignment: .leading, spacing: 2) {
                    // The wordmark is a logo: it grows with the text size only to 130%.
                    Text("Neema AI").font(NeemaFont.capped(13, .semibold, maxScale: 1.3)).foregroundColor(Brand.textLight).lineLimit(1)
                    Text("ADMIN PORTAL").font(NeemaFont.capped(10, .medium, maxScale: 1.3)).tracking(0.8).foregroundColor(Brand.textMuted).lineLimit(1).fixedSize()
                }
                .padding(.leading, 6)
                .frame(maxWidth: .infinity, alignment: .leading)
                BellButton(count: 0) {}
                if docked, let collapsed = collapsed {
                    NavyIconButton(glyph: WebIcons.collapse, label: "Collapse sidebar") { collapsed.wrappedValue = true }
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 6)
            .frame(minHeight: 56)
        }
    }

    private func navRow(_ item: NavItem) -> some View {
        let active = item.view == app.view
        // Navy on the amber pill: the web's white is 2.1:1 there, navy 8.3:1.
        let fg = active ? Brand.navy : Brand.textMuted
        return Button {
            app.navigate(item.view)
        } label: {
            ZStack(alignment: .topTrailing) {
                HStack(spacing: 10) {
                    WebIcon(glyph: WebIcons.icon(for: item.view), size: 20).foregroundColor(fg)
                    if !isCollapsed {
                        Text(item.view.label).font(NeemaFont.manrope(13, active ? .semibold : .medium)).foregroundColor(fg).lineLimit(1)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        if item.badge > 0 { AmberBadge(count: item.badge, onPill: active) }
                    }
                }
                .padding(.horizontal, isCollapsed ? 0 : 12).padding(.vertical, 4)
                .frame(maxWidth: .infinity, alignment: isCollapsed ? .center : .leading)
                .frame(minHeight: 48)
                if isCollapsed && item.badge > 0 {
                    AmberBadge(count: item.badge, style: .rail, onPill: active).padding(4)
                }
            }
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(active ? Brand.amber : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(item.badge > 0 ? "\(item.view.label), \(item.badge) new" : item.view.label)
        .accessibilityAddTraits(active ? AccessibilityTraits.isSelected : AccessibilityTraits())
    }

    // ── Footer: the account ──────────────────────────────────────────────────

    private var footer: some View {
        VStack(spacing: 0) {
            // Expanded: the card opens above the footer row, as wide as it, 8 pt clear.
            if app.accountMenuOpen && !isCollapsed { AccountCard().padding(.bottom, 8) }
            accountRow
        }
        .padding(.horizontal, isCollapsed ? 6 : 8).padding(.vertical, 8)
    }

    /// The collapsed rail opens the card as a popover beside the avatar.
    private var railMenu: Binding<Bool> {
        Binding(get: { isCollapsed && app.accountMenuOpen }, set: { if !$0 { app.accountMenuOpen = false } })
    }

    private var accountRow: some View {
        let name = nonBlank(app.me?.name) ?? nonBlank(app.session?.name) ?? ""
        let email = nonBlank(app.me?.email) ?? nonBlank(app.session?.email) ?? ""
        let role = nonBlank(app.session?.role) ?? nonBlank(app.me?.role) ?? ""
        // text-transform: capitalize — each word's first letter.
        let roleLine = (nonBlank(role) ?? nonBlank(email) ?? "—").split(separator: " ").map { capitalizeFirst(String($0)) }.joined(separator: " ")
        return ZStack {
            Button { app.accountMenuOpen.toggle() } label: {
                HStack(spacing: 0) {
                    ZStack(alignment: .bottomTrailing) {
                        // The web's light avatar sits on the navy rail in both themes.
                        AvatarView(name: name.isEmpty ? "User" : name, url: app.me?.avatarUrl, size: 32).environment(\.neema, NeemaColors.light)
                        // 9 pt online dot with a 2 pt navy ring.
                        Circle().fill(Brand.online).frame(width: 5, height: 5).padding(2).background(Circle().fill(Brand.navy))
                    }
                    if !isCollapsed {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(name.isEmpty ? "—" : name).font(NeemaFont.manrope(12, .semibold)).foregroundColor(Brand.textLight).lineLimit(1)
                            Text(roleLine).font(NeemaFont.manrope(10)).foregroundColor(Brand.textMuted).lineLimit(1)
                        }
                        .padding(.leading, 10)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        WebIcon(glyph: WebIcons.chevronUp, size: 14).foregroundColor(Brand.textMuted)
                            .rotationEffect(.degrees(app.accountMenuOpen ? 180 : 0))
                            .padding(.leading, 10)
                    }
                }
                .padding(.horizontal, isCollapsed ? 0 : 8).padding(.vertical, isCollapsed ? 4 : 6)
                .frame(maxWidth: .infinity, alignment: isCollapsed ? .center : .leading)
                .frame(minHeight: 48)
                .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(app.accountMenuOpen ? Brand.navyHover : .clear))
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(app.signingOut)
            .accessibilityLabel("Account: \(name.isEmpty ? email : name), \(role.isEmpty ? "agent" : role)")
            .accessibilityHint(app.accountMenuOpen ? "Close account menu" : "Open account menu")
            .popover(isPresented: railMenu, arrowEdge: .leading) {
                AccountCard().frame(width: 252).padding(8).environmentObject(app)
            }
            // Sidebar.tsx while logging out: navy over the button, a 14 pt amber ring spinning.
            if app.signingOut {
                RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Brand.navy.opacity(0.85))
                    .overlay(RingSpinner())
                    .accessibilityLabel("Signing out…")
            }
        }
    }
}

private func nonBlank(_ s: String?) -> String? {
    guard let s = s?.trimmingCharacters(in: .whitespaces), !s.isEmpty else { return nil }
    return s
}

/// A 36 pt navy icon button (the sidebar's collapse control).
struct NavyIconButton: View {
    let glyph: WebGlyph
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            WebIcon(glyph: glyph, size: 14).foregroundColor(Brand.textMuted).frame(width: 36, height: 36).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }
}

/// Notifications.tsx's bell: 36 pt (40 pt on the collapsed rail), 12 pt
/// corners, a sage 16 pt glyph that turns moss on a pale tile while the popup
/// is open, and a red count with a navy ring sitting just off the top-right
/// corner. The list it opens arrives in cycle 5.
struct BellButton: View {
    let count: Int
    var open: Bool = false
    var compact: Bool = false
    let action: () -> Void

    var body: some View {
        let side: CGFloat = compact ? 40 : 36
        Button(action: action) {
            ZStack(alignment: .topTrailing) {
                RoundedRectangle(cornerRadius: 12, style: .continuous).fill(open ? Palette.leaf : .clear)
                    .frame(width: side, height: side)
                    .overlay(WebIcon(glyph: WebIcons.bell, size: 16).foregroundColor(open ? Palette.moss700 : Palette.sage400))
                if count > 0 {
                    Text(count > 9 ? "9+" : String(count)).font(NeemaFont.capped(9, .bold, maxScale: 1.2)).foregroundColor(.white)
                        .padding(.horizontal, 4).frame(minWidth: 16, minHeight: 16)
                        .background(Capsule().fill(Palette.red500))
                        .overlay(Capsule().stroke(Brand.navy, lineWidth: 2))
                        .offset(x: 2, y: -2)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(count > 0 ? "Notifications, \(count) unread" : "Notifications")
    }
}

/// The account popup (Sidebar.tsx AccountPopup) — white in both themes, as
/// on the web. Settings is always offered, as there: the page itself decides
/// what someone without manage_settings may do.
struct AccountCard: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        let name = nonBlank(app.me?.name) ?? nonBlank(app.session?.name) ?? "—"
        let email = nonBlank(app.me?.email) ?? nonBlank(app.session?.email) ?? "—"
        let role = nonBlank(app.session?.role) ?? nonBlank(app.me?.role) ?? "agent"
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 12) {
                AvatarView(name: name == "—" ? "User" : name, url: app.me?.avatarUrl, size: 40).environment(\.neema, NeemaColors.light)
                VStack(alignment: .leading, spacing: 2) {
                    Text(name).font(NeemaFont.manrope(13, .semibold)).foregroundColor(Palette.ink).lineLimit(1)
                    Text(email).font(NeemaFont.manrope(11)).foregroundColor(Palette.sage500).lineLimit(1)
                    Text(role.uppercased()).font(NeemaFont.manrope(9, .bold)).tracking(0.72).foregroundColor(Brand.moss)
                        .padding(.horizontal, 8).padding(.vertical, 2)
                        .background(Capsule().fill(Palette.moss50))
                        .overlay(Capsule().stroke(Palette.moss200))
                        .padding(.top, 4)
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 14)
            Hairline(color: Palette.hairline2)
            VStack(spacing: 0) {
                menuRow(WebIcons.profile, "View Profile") { app.navigate(.profile); close() }
                menuRow(WebIcons.settings, "Settings") { app.navigate(.settings); close() }
            }
            .padding(6)
            Hairline(color: Palette.hairline2)
            // One switch for VoiceOver: the row and its pill toggle together.
            Button { app.setDark(!app.dark) } label: {
                HStack(spacing: 8) {
                    WebIcon(glyph: app.dark ? WebIcons.sun : WebIcons.moon, size: 14).foregroundColor(Palette.pewter600)
                    Text(app.dark ? "Light mode" : "Dark mode").font(NeemaFont.manrope(12, .medium)).foregroundColor(Palette.pewter700)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    ThemePill(on: app.dark)
                }
                .padding(.horizontal, 14).padding(.vertical, 8)
                .frame(minHeight: 48)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dark mode")
            .accessibilityValue(app.dark ? "On" : "Off")
            Hairline(color: Palette.hairline2)
            VStack(spacing: 0) {
                menuRow(WebIcons.logout, "Sign out", danger: true) { app.logout() }
            }
            .padding(6)
        }
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Palette.hairline))
        .shadow(color: .black.opacity(0.2), radius: 12, y: 6)
    }

    private func close() {
        app.accountMenuOpen = false
        app.drawerOpen = false
    }

    private func menuRow(_ glyph: WebGlyph, _ title: String, danger: Bool = false, action: @escaping () -> Void) -> some View {
        // red-600 for the destructive row: the web's red-500 is 3.8:1 on white.
        let color = danger ? Palette.red600 : Palette.pewter700
        return Button(action: action) {
            HStack(spacing: 10) {
                WebIcon(glyph: glyph, size: 14).foregroundColor(danger ? color : Palette.pewter600).opacity(danger ? 1 : 0.65)
                Text(title).font(NeemaFont.manrope(12, .medium)).foregroundColor(color)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12).padding(.vertical, 7)
            .frame(minHeight: 48)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

/// The popup's 32×18 toggle: moss when dark, sage otherwise, a 14 pt white knob. Its row is the switch.
struct ThemePill: View {
    let on: Bool

    var body: some View {
        Capsule().fill(on ? Palette.moss600 : Palette.sage300)
            .frame(width: 32, height: 18)
            .overlay(alignment: on ? .trailing : .leading) {
                Circle().fill(Color.white).frame(width: 14, height: 14)
                    .shadow(color: .black.opacity(0.25), radius: 1, y: 1)
                    .padding(2)
            }
            .animation(.easeInOut(duration: 0.15), value: on)
            .accessibilityHidden(true)
    }
}

/// Sidebar.tsx's logging-out spinner: a 14 pt amber ring, 2 pt, a quarter of it open, turning once every 0.7 s.
struct RingSpinner: View {
    @State private var turning = false

    var body: some View {
        Circle().trim(from: 0, to: 0.75).stroke(Brand.amber, lineWidth: 2)
            .frame(width: 14, height: 14)
            .rotationEffect(.degrees(turning ? 360 : 0))
            .onAppear { withAnimation(.linear(duration: 0.7).repeatForever(autoreverses: false)) { turning = true } }
    }
}

/// The nav count (Sidebar.tsx / MobileNav.tsx): the full number, as the web
/// prints it. 18 pt / 10 pt beside a label; 14 pt / 8 pt on the collapsed
/// rail; 14 pt / 9 pt in the phone bar. Navy numerals on amber (the web's
/// white is 2.1:1); on the amber active pill the badge turns navy. The count
/// grows with the text size only to 130%, so it stays a badge.
struct AmberBadge: View {
    enum Style { case label, rail, bottomNav }
    let count: Int
    var style: Style = .label
    /// On the amber active pill an amber badge would vanish: navy there.
    var onPill: Bool = false

    var body: some View {
        let min: CGFloat = style == .label ? 18 : 14
        let size: CGFloat = style == .label ? 10 : (style == .rail ? 8 : 9)
        let pad: CGFloat = style == .label ? 5 : (style == .rail ? 2 : 3)
        Text(String(count))
            .font(NeemaFont.capped(size, .bold, maxScale: 1.3))
            .foregroundColor(onPill ? Brand.amber : Brand.navy)
            .padding(.horizontal, pad)
            .frame(minWidth: min, minHeight: min)
            .background(Capsule().fill(onPill ? Brand.navy : Brand.amber))
    }
}

/// Initials on a stone-green disc (Android `Avatar`).
struct AvatarView: View {
    var name: String
    var url: String? = nil
    var size: CGFloat
    @Environment(\.neema) private var c

    var body: some View {
        ZStack {
            disc
            // The photo when there is one, falling back to the disc while it loads or if it fails.
            if let u = url, !u.isEmpty, let link = URL(string: u) {
                AsyncImage(url: link) { phase in
                    if case .success(let img) = phase { img.resizable().scaledToFill() } else { Color.clear }
                }
                .frame(width: size, height: size)
                .clipShape(Circle())
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }

    /// components/ui/Avatar.tsx: one neutral stone-green disc with dark-green initials,
    /// and a person glyph for an unnamed contact whose "name" is only a phone number.
    private var disc: some View {
        let phoneLike = isPhoneLike(name)
        return Circle()
            .fill(c.isDark ? Color(hex: 0x0F1424) : Color(hex: 0xF5F6F3))
            .overlay(Circle().stroke(c.isDark ? Color(hex: 0x1F367A) : Color(hex: 0xDDE8D5)))
            .overlay(
                Group {
                    if phoneLike {
                        Image(systemName: "person.fill").font(.system(size: size * 0.45)).foregroundColor(c.isDark ? Color(hex: 0xB5DA8B) : Color(hex: 0x3A5C28))
                    } else {
                        Text(Fmt.initials(name)).font(NeemaFont.fixed(size * 0.38, .bold)).foregroundColor(c.isDark ? Color(hex: 0xB5DA8B) : Color(hex: 0x3A5C28))
                    }
                }
            )
            .frame(width: size, height: size)
    }
}

/// True when a "name" is really a phone number, a Meta id or a website-chat
/// visitor: its initials would read "+7", "MI" or "WV", so the avatar shows a person glyph.
func isPhoneLike(_ name: String?) -> Bool {
    let n = (name ?? "").trimmingCharacters(in: .whitespaces)
    if n.isEmpty { return true }
    if n.lowercased().hasPrefix("messenger id") { return true }
    if n.lowercased() == "website visitor" || n.hasPrefix("web_") { return true }
    let digits = n.filter { !" +-().".contains($0) }
    return !digits.isEmpty && digits.allSatisfy { $0.isNumber }
}

/// "Reconnecting…": the socket is down while the device is online (amber-100
/// pill, an amber-600 dot, amber-800 words that grow only to 130%).
struct OfflineDot: View {
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(Palette.amber600).frame(width: 6, height: 6)
            Text("Reconnecting…").font(NeemaFont.capped(10, .semibold, maxScale: 1.3)).foregroundColor(Palette.amber800).lineLimit(1)
        }
        .padding(.horizontal, 8).padding(.vertical, 3)
        .background(Capsule().fill(Palette.amber100))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Reconnecting to live updates")
    }
}
