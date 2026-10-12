import SwiftUI
import NeemaCore

/// One of the dashboard's own outline icons: its 24-box path(s) and stroke width.
struct WebGlyph {
    let paths: [String]
    /// The stroke width in the 24-unit box.
    let width: CGFloat
    init(_ width: CGFloat = 1.8, _ paths: String...) {
        self.width = width
        self.paths = paths.map { OverviewIcons.expandArcFlags($0) }
    }
}

/// The dashboard's own outline icons (heroicons paths from
/// app/dashboard/page.tsx and the sidebar), so the app shows exactly the
/// shapes the web does (Android `WebIcons`). Stroked in the current colour.
enum WebIcons {
    private static let bubble = "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
    static let inbox = WebGlyph(1.8, bubble)
    static let logo = WebGlyph(2.5, bubble)
    static let calls = WebGlyph(1.8, "M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z")
    static let orders = WebGlyph(1.8, "M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4")
    static let reports = WebGlyph(1.8, "M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z")
    static let deals = WebGlyph(1.8, "M13 10V3L4 14h7v7l9-11h-7z")
    static let leads = WebGlyph(1.8, "M3 21v-4m0 0V5a2 2 0 012-2h6.5l1 1H21l-3 6 3 6h-8.5l-1-1H5a2 2 0 00-2 2zm9-13.5V9")
    static let analytics = WebGlyph(1.8, "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z")
    static let catalog = WebGlyph(1.8, "M4 6h16M4 10h16M4 14h16M4 18h16")
    static let team = WebGlyph(1.8, "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z")
    static let settings = WebGlyph(1.8, "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z", "M15 12a3 3 0 11-6 0 3 3 0 016 0z")
    static let profile = WebGlyph(1.8, "M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z")
    static let bell = WebGlyph(2, "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9")
    static let moon = WebGlyph(2, "M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z")
    static let sun = WebGlyph(2, "M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z")
    static let collapse = WebGlyph(2, "M11 19l-7-7 7-7m8 14l-7-7 7-7")
    static let expand = WebGlyph(2, "M13 5l7 7-7 7M5 5l7 7-7 7")
    static let chevronUp = WebGlyph(2, "M5 15l7-7 7 7")
    static let logout = WebGlyph(2, "M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1")
    static let more = WebGlyph(2, "M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z")
    static let menu = WebGlyph(2, "M4 6h16M4 12h16M4 18h16")
    /// The magnifier inside the web's search boxes (OrdersView, CatalogView, LeadsView).
    static let search = WebGlyph(2, "M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z")
    // login/page.tsx + SessionExpiredModal.tsx
    static let eye = WebGlyph(2, "M15 12a3 3 0 11-6 0 3 3 0 016 0z", "M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z")
    static let eyeOff = WebGlyph(2, "M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21")
    // The offline banner: lucide's wifi-off, and a plain check for "back online".
    static let wifiOff = WebGlyph(2, "M12 20h.01M8.5 16.429a5 5 0 0 1 7 0M5 12.859a10 10 0 0 1 5.17-2.69M19 12.859a10 10 0 0 0-2.007-1.523M2 8.82a15 15 0 0 1 4.177-2.643M22 8.82a15 15 0 0 0-11.288-3.764M2 2l20 20")
    static let check = WebGlyph(2.5, "M5 13l4 4L19 7")
    static let close = WebGlyph(2.5, "M6 18L18 6M6 6l12 12")
    static let exclamation = WebGlyph(3, "M12 6v7m0 5h.01")
    static let alertCircle = WebGlyph(2, "M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z")
    static let warning = WebGlyph(1.8, "M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z")

    /// The nav's icon for a view (Sidebar.tsx / page.tsx).
    static func icon(for v: ViewId) -> WebGlyph {
        switch v {
        case .conversations: return inbox
        case .calls: return calls
        case .orders: return orders
        case .reports: return reports
        case .deals: return deals
        case .leads: return leads
        case .overview: return analytics
        case .catalog: return catalog
        case .agents: return team
        case .settings: return settings
        case .profile: return profile
        }
    }
}

/// One of the web's icons at `size` points, stroked round-capped in the current foreground colour.
struct WebIcon: View {
    let glyph: WebGlyph
    var size: CGFloat = 20

    var body: some View {
        ZStack {
            ForEach(Array(glyph.paths.enumerated()), id: \.offset) { _, d in
                SVGShape(d: d).stroke(style: StrokeStyle(lineWidth: glyph.width * size / 24, lineCap: .round, lineJoin: .round))
            }
        }
        .frame(width: size, height: size)
        .accessibilityHidden(true)
    }
}

/// The amber chat-bubble mark (Sidebar.tsx / MobileNav.tsx). The sidebar's is
/// 32 pt with 10 pt corners and an amber glow; the mobile header's is 28 pt,
/// 8 pt corners, flat.
struct NeemaLogo: View {
    var size: CGFloat = 32
    var corner: CGFloat = 10
    var glow: Bool = true

    var body: some View {
        RoundedRectangle(cornerRadius: corner, style: .continuous).fill(Brand.amber)
            .frame(width: size, height: size)
            .overlay(WebIcon(glyph: WebIcons.logo, size: size * 0.5).foregroundColor(.white))
            .shadow(color: glow ? Brand.amber.opacity(0.45) : .clear, radius: glow ? 6 : 0)
            .accessibilityHidden(true)
    }
}
