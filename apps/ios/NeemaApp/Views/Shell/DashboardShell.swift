import SwiftUI
import NeemaCore

/// The signed-in chrome: on a phone a header, the view and a bottom nav with
/// the navy sidebar as a sheet; on a wide window the navy sidebar docked at
/// the start edge beside the view.
struct DashboardShell: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.horizontalSizeClass) private var hSize
    @Environment(\.neema) private var c

    var body: some View {
        Group {
            if hSize == .compact {
                MobileShell()
            } else {
                WideShell()
            }
        }
        .background(c.surface.ignoresSafeArea())
    }
}

/// Which view is on screen.
struct CurrentView: View {
    @EnvironmentObject private var app: AppModel

    var body: some View {
        switch app.view {
        case .conversations: ViewPlaceholder(view: .conversations, cycle: 2, note: "The inbox, threads, the composer and the customer panel.")
        case .calls: ViewPlaceholder(view: .calls, cycle: 5, note: "The call log, details, transcripts and the softphone.")
        case .orders: ViewPlaceholder(view: .orders, cycle: 2, note: "Orders with their hub state and status moves.")
        case .reports: ViewPlaceholder(view: .reports, cycle: 2, note: "Reports over every conversation, with CSV export.")
        case .deals: ViewPlaceholder(view: .deals, cycle: 2, note: "What Neema owns right now and her planned actions.")
        case .leads: ViewPlaceholder(view: .leads, cycle: 2, note: "The leads pipeline.")
        case .overview: ViewPlaceholder(view: .overview, cycle: 2, note: "Real-time metrics and platform performance.")
        case .catalog: ViewPlaceholder(view: .catalog, cycle: 2, note: "Live from the Bethany House hub.")
        case .agents: ViewPlaceholder(view: .agents, cycle: 2, note: "Agents and roles.")
        case .settings: ViewPlaceholder(view: .settings, cycle: 4, note: "Platform configuration and integrations.")
        case .profile: ViewPlaceholder(view: .profile, cycle: 2, note: "Your account and preferences.")
        }
    }
}

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
            if let t = app.toast {
                ToastView(toast: t)
                    .padding(.horizontal, 16)
                    .padding(.bottom, app.immersive ? 24 : 96)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: app.toast?.id)
        .sheet(isPresented: $app.drawerOpen) {
            SidebarView(docked: false)
                .presentationDetents([.large])
                .presentationDragIndicator(.visible)
        }
    }
}

struct WideShell: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @State private var collapsed = false

    var body: some View {
        ZStack(alignment: .topTrailing) {
            HStack(spacing: 0) {
                SidebarView(docked: true, collapsed: $collapsed)
                    .frame(width: collapsed ? 60 : 208)
                VStack(spacing: 0) {
                    ConnectivityBanner()
                    CurrentView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
                .background(c.surface)
            }
            .background(Brand.navy.ignoresSafeArea(edges: .top))
            if let t = app.toast {
                ToastView(toast: t)
                    .frame(minWidth: 288, maxWidth: 384)
                    .padding(20)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
            if !app.connected && app.online {
                OfflineDot().padding(.trailing, 20).padding(.top, app.toast == nil ? 20 : 80)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: app.toast?.id)
    }
}

/// White by day, Prussian by night: ☰, the amber logo, "Neema · {view}", the bell and the theme toggle.
struct MobileHeader: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c
    @Environment(\.sizeCategory) private var sizeCategory

    var body: some View {
        let chrome = ChromeColors.of(c)
        HStack(spacing: 4) {
            Button { app.drawerOpen = true } label: {
                Image(systemName: "line.3.horizontal").font(.system(size: 20, weight: .medium)).foregroundColor(chrome.subtitle)
                    .frame(width: 48, height: 48)
            }
            .accessibilityLabel("Open navigation menu")
            RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Brand.amber)
                .overlay(Image(systemName: "bubble.left.fill").foregroundColor(.white).font(.system(size: 13, weight: .bold)))
                .frame(width: 28, height: 28)
            HStack(spacing: 4) {
                if !sizeCategory.isAccessibilityCategory {
                    Text("Neema ·").font(NeemaFont.fixed(14, .semibold)).foregroundColor(chrome.subtitle)
                }
                Text(app.view.label).font(NeemaFont.fixed(14, .bold)).foregroundColor(chrome.title)
            }
            .lineLimit(1)
            .padding(.leading, 8)
            Spacer(minLength: 4)
            if !app.connected && app.online {
                OfflineDot(label: "Reconnecting…")
            }
            Button { } label: {
                Image(systemName: "bell").font(.system(size: 18, weight: .medium)).foregroundColor(chrome.subtitle)
                    .frame(width: 48, height: 48)
            }
            .accessibilityLabel("Notifications")
            Button { app.setDark(!app.dark) } label: {
                Image(systemName: app.dark ? "sun.max" : "moon").font(.system(size: 18, weight: .medium)).foregroundColor(chrome.subtitle)
                    .frame(width: 48, height: 48)
            }
            .accessibilityLabel(app.dark ? "Switch to light mode" : "Switch to dark mode")
        }
        .padding(.horizontal, 4)
        .frame(minHeight: 56)
        .background(chrome.bar)
        .overlay(Rectangle().fill(chrome.line).frame(height: 1), alignment: .bottom)
    }
}

/// The first four permitted nav items plus "More", which opens the sidebar.
struct MobileBottomNav: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.neema) private var c

    var body: some View {
        let chrome = ChromeColors.of(c)
        let items = Array(app.navItems.prefix(4))
        let moreActive = !items.contains { $0.view == app.view }
        HStack(spacing: 0) {
            ForEach(items, id: \.view) { item in
                tab(label: item.view.label, icon: NavIcons.name(item.view), active: item.view == app.view, badge: item.badge) {
                    app.navigate(item.view)
                }
            }
            tab(label: "More", icon: "ellipsis", active: moreActive, badge: 0) { app.drawerOpen = true }
        }
        .frame(height: 56)
        .background(chrome.bar)
        .overlay(Rectangle().fill(chrome.line).frame(height: 1), alignment: .top)
    }

    private func tab(label: String, icon: String, active: Bool, badge: Int, action: @escaping () -> Void) -> some View {
        let chrome = ChromeColors.of(c)
        return Button(action: action) {
            VStack(spacing: 3) {
                Rectangle().fill(active ? chrome.active : .clear).frame(width: 28, height: 2)
                ZStack(alignment: .topTrailing) {
                    Image(systemName: icon).font(.system(size: 20, weight: .regular))
                        .foregroundColor(active ? chrome.active : chrome.subtitle)
                    if badge > 0 {
                        AmberBadge(count: badge, small: true).offset(x: 10, y: -6)
                    }
                }
                Text(label).font(NeemaFont.fixed(10, .semibold)).foregroundColor(active ? chrome.active : chrome.subtitle).lineLimit(1)
            }
            .frame(maxWidth: .infinity)
        }
        .accessibilityLabel(badge > 0 ? "\(label), \(badge) new" : label)
    }
}

/// The navy sidebar: brand header, the nav, and the account footer.
struct SidebarView: View {
    @EnvironmentObject private var app: AppModel
    var docked: Bool
    var collapsed: Binding<Bool>? = nil
    @Environment(\.dismiss) private var dismiss

    private var isCollapsed: Bool { docked && (collapsed?.wrappedValue ?? false) }

    var body: some View {
        VStack(spacing: 0) {
            header
            Rectangle().fill(Brand.navyBorder).frame(height: 1)
            ScrollView {
                VStack(spacing: 4) {
                    ForEach(app.navItems, id: \.view) { item in
                        navRow(item)
                    }
                }
                .padding(10)
            }
            Rectangle().fill(Brand.navyBorder).frame(height: 1)
            footer
        }
        .background(Brand.navy.ignoresSafeArea())
    }

    private var header: some View {
        HStack(spacing: 10) {
            RoundedRectangle(cornerRadius: 10, style: .continuous).fill(Brand.amber)
                .overlay(Image(systemName: "bubble.left.fill").foregroundColor(.white).font(.system(size: 15, weight: .bold)))
                .frame(width: 32, height: 32)
                .shadow(color: Brand.amber.opacity(0.45), radius: 10)
            if !isCollapsed {
                VStack(alignment: .leading, spacing: 1) {
                    Text("Neema AI").font(NeemaFont.fixed(13, .bold)).foregroundColor(Brand.textLight)
                    Text("ADMIN PORTAL").font(NeemaFont.fixed(10, .semibold)).tracking(0.8).foregroundColor(Brand.textMuted)
                }
                Spacer()
                if docked, let collapsed = collapsed {
                    Button { collapsed.wrappedValue = true } label: {
                        Image(systemName: "chevron.left.2").foregroundColor(Brand.textMuted).frame(width: 36, height: 36)
                    }
                    .accessibilityLabel("Collapse sidebar")
                }
            } else if let collapsed = collapsed {
                Button { collapsed.wrappedValue = false } label: {
                    Image(systemName: "chevron.right.2").foregroundColor(Brand.textMuted).frame(width: 36, height: 36)
                }
                .accessibilityLabel("Expand sidebar")
            }
        }
        .padding(.horizontal, isCollapsed ? 0 : 16)
        .frame(maxWidth: .infinity, alignment: isCollapsed ? .center : .leading)
        .frame(height: 64)
    }

    private func navRow(_ item: NavItem) -> some View {
        let active = item.view == app.view
        return Button {
            app.navigate(item.view)
            if !docked { dismiss() }
        } label: {
            HStack(spacing: 12) {
                Image(systemName: NavIcons.name(item.view)).font(.system(size: 18, weight: .medium))
                    .foregroundColor(active ? Brand.navy : Brand.textMuted)
                    .frame(width: 24)
                if !isCollapsed {
                    Text(item.view.label).font(NeemaFont.fixed(13, .semibold)).foregroundColor(active ? Brand.navy : Brand.textLight)
                    Spacer()
                    if item.badge > 0 { AmberBadge(count: item.badge, inverted: active) }
                }
            }
            .padding(.horizontal, isCollapsed ? 0 : 12)
            .frame(maxWidth: .infinity, alignment: isCollapsed ? .center : .leading)
            .frame(minHeight: 48)
            .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(active ? Brand.amber : .clear))
        }
        .accessibilityLabel(item.badge > 0 ? "\(item.view.label), \(item.badge) new" : item.view.label)
    }

    private var footer: some View {
        VStack(spacing: 0) {
            if app.accountMenuOpen && !isCollapsed { AccountCard() .padding(10) }
            Button {
                app.accountMenuOpen.toggle()
            } label: {
                HStack(spacing: 10) {
                    ZStack(alignment: .bottomTrailing) {
                        AvatarView(name: app.me?.name ?? app.session?.name ?? "", size: 32)
                        Circle().fill(Brand.online).frame(width: 9, height: 9)
                            .overlay(Circle().stroke(Brand.navy, lineWidth: 2))
                    }
                    if !isCollapsed {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(app.me?.name ?? app.session?.name ?? "").font(NeemaFont.fixed(12, .semibold)).foregroundColor(Brand.textLight).lineLimit(1)
                            Text((app.me?.role ?? app.session?.role ?? "agent").capitalized).font(NeemaFont.fixed(11)).foregroundColor(Brand.textMuted)
                        }
                        Spacer()
                        Image(systemName: "chevron.up").foregroundColor(Brand.textMuted)
                            .rotationEffect(.degrees(app.accountMenuOpen ? 180 : 0))
                    }
                }
                .padding(.horizontal, isCollapsed ? 0 : 16)
                .frame(maxWidth: .infinity, alignment: isCollapsed ? .center : .leading)
                .frame(height: 60)
            }
            .accessibilityLabel("Account: \(app.me?.name ?? ""), \(app.me?.role ?? "")")
            .accessibilityHint(app.accountMenuOpen ? "Close account menu" : "Open account menu")
        }
    }
}

/// The account popup: always white, in both themes.
struct AccountCard: View {
    @EnvironmentObject private var app: AppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                AvatarView(name: app.me?.name ?? "", size: 40)
                VStack(alignment: .leading, spacing: 2) {
                    Text(app.me?.name ?? app.session?.name ?? "").font(NeemaFont.fixed(13, .bold)).foregroundColor(Palette.stone900)
                    Text(app.me?.email ?? app.session?.email ?? "").font(NeemaFont.fixed(11)).foregroundColor(Palette.stone500).lineLimit(1)
                    Text((app.me?.role ?? app.session?.role ?? "agent").uppercased())
                        .font(NeemaFont.fixed(9, .bold)).tracking(0.6).foregroundColor(Palette.mossInk)
                        .padding(.horizontal, 6).padding(.vertical, 2)
                        .background(Capsule().fill(Palette.mossTint50))
                        .overlay(Capsule().stroke(Palette.mossTint200))
                }
            }
            .padding(12)
            Divider()
            row("View Profile", "person") { app.navigate(.profile); close() }
            row("Settings", "gearshape") { app.navigate(.settings); close() }
            Divider()
            HStack {
                Text(app.dark ? "Dark mode" : "Light mode").font(NeemaFont.fixed(13, .semibold)).foregroundColor(Palette.stone900)
                Spacer()
                Toggle("", isOn: Binding(get: { app.dark }, set: { app.setDark($0) })).labelsHidden().tint(Brand.moss)
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            Divider()
            row("Sign out", "rectangle.portrait.and.arrow.right", color: Palette.red600) { app.logout() }
        }
        .background(RoundedRectangle(cornerRadius: 14, style: .continuous).fill(Color.white))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(Palette.hairline))
        .shadow(color: .black.opacity(0.2), radius: 16, y: 8)
    }

    private func close() {
        app.accountMenuOpen = false
        dismiss()
    }

    private func row(_ title: String, _ icon: String, color: Color = Palette.stone900, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: icon).foregroundColor(color).frame(width: 20)
                Text(title).font(NeemaFont.fixed(13, .semibold)).foregroundColor(color)
                Spacer()
            }
            .padding(.horizontal, 12).frame(height: 44)
        }
    }
}

struct AmberBadge: View {
    var count: Int
    var small: Bool = false
    var inverted: Bool = false

    var body: some View {
        Text(small && count > 9 ? "9+" : String(count))
            .font(NeemaFont.fixed(small ? 9 : 10, .bold))
            .foregroundColor(inverted ? Brand.amber : Brand.navy)
            .padding(.horizontal, small ? 4 : 6)
            .frame(minWidth: small ? 14 : 18, minHeight: small ? 14 : 18)
            .background(Capsule().fill(inverted ? Brand.navy : Brand.amber))
    }
}

/// Initials on a stone-green disc (Android `Avatar`).
struct AvatarView: View {
    var name: String
    var size: CGFloat
    @Environment(\.neema) private var c

    var body: some View {
        let phoneLike = name.filter { $0.isNumber }.count >= 7 || name.hasPrefix("web_") || name.isEmpty
        Circle()
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

/// SF Symbols standing in for the web's heroicons until the custom paths land (Cycle 3).
enum NavIcons {
    static func name(_ v: ViewId) -> String {
        switch v {
        case .conversations: return "tray"
        case .calls: return "phone"
        case .orders: return "shippingbox"
        case .reports: return "doc.text"
        case .deals: return "briefcase"
        case .leads: return "person.2"
        case .overview: return "chart.bar"
        case .catalog: return "square.grid.2x2"
        case .agents: return "person.3"
        case .settings: return "gearshape"
        case .profile: return "person.crop.circle"
        }
    }
}

/// "Reconnecting…": the socket is down while the device is online.
struct OfflineDot: View {
    var label: String? = nil
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(Brand.amber).frame(width: 8, height: 8)
            if let l = label { Text(l).font(NeemaFont.fixed(11, .semibold)).foregroundColor(Brand.amberInk) }
        }
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background(Capsule().fill(Palette.amber50))
        .accessibilityLabel("Reconnecting to live updates")
    }
}
