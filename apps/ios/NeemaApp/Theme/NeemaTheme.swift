import SwiftUI

extension Color {
    /// `Color(hex: 0x589B31)`; `alpha` for the dim variants.
    init(hex: UInt32, alpha: Double = 1) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: alpha)
    }
}

/// The app's colour tokens — Android `NeemaColors` (light / dark), one for one.
struct NeemaColors {
    let bg, bg2, bg3, bg4, border, border2, gold, gold2, goldDim, text, textDim, textMid: Color
    let green, red, blue, amber, indigo, surface, hairline, muted: Color
    let isDark: Bool

    static let light = NeemaColors(
        bg: Color(hex: 0xF3F9EC), bg2: Color(hex: 0xFFFFFF), bg3: Color(hex: 0xE6F3D8), bg4: Color(hex: 0xCEE6B2),
        border: Color(hex: 0xB5DA8B), border2: Color(hex: 0x9CCD65), gold: Color(hex: 0x589B31), gold2: Color(hex: 0x427425),
        goldDim: Color(hex: 0x589B31, alpha: 0.10), text: Color(hex: 0x16270C), textDim: Color(hex: 0x699A32), textMid: Color(hex: 0x4F7425),
        green: Color(hex: 0x589B31), red: Color(hex: 0xC0392B), blue: Color(hex: 0x2A48A2), amber: Color(hex: 0xBCC13E),
        indigo: Color(hex: 0x3D528F), surface: Color(hex: 0xF7F8F5), hairline: Color(hex: 0xE8EBE3), muted: Color(hex: 0x8A9E80),
        isDark: false
    )

    static let dark = NeemaColors(
        bg: Color(hex: 0x070D1C), bg2: Color(hex: 0x0A1229), bg3: Color(hex: 0x0B0E19), bg4: Color(hex: 0x0F1424),
        border: Color(hex: 0x152451), border2: Color(hex: 0x1F367A), gold: Color(hex: 0x84C13E), gold2: Color(hex: 0x9CCD65),
        goldDim: Color(hex: 0x84C13E, alpha: 0.12), text: Color(hex: 0xF3F9EC), textDim: Color(hex: 0x699A32), textMid: Color(hex: 0xB5DA8B),
        green: Color(hex: 0x84C13E), red: Color(hex: 0xE05555), blue: Color(hex: 0x5D7BD5), amber: Color(hex: 0xD7DA8B),
        indigo: Color(hex: 0x7085C2), surface: Color(hex: 0x070D1C), hairline: Color(hex: 0x152451), muted: Color(hex: 0x8A9E80),
        isDark: true
    )
}

/// Same in both themes.
enum Brand {
    static let navy = Color(hex: 0x0E1729)
    static let navyBorder = Color(hex: 0x1E2A44)
    static let navyHover = Color(hex: 0x1B2740)
    static let amber = Color(hex: 0xF59E0B)
    static let textLight = Color(hex: 0xF8FAFC)
    static let textMuted = Color(hex: 0x94A3B8)
    static let online = Color(hex: 0x22C55E)
    static let moss = Color(hex: 0x589B31)
    static let amberInk = Color(hex: 0xB45309)
}

/// The phone header and bottom bar.
struct ChromeColors {
    let bar, line, title, subtitle, active, separator: Color
    static let light = ChromeColors(bar: Color(hex: 0xFFFFFF), line: Color(hex: 0xF3F4F6), title: Color(hex: 0x111827),
                                    subtitle: Color(hex: 0x6B7E64), active: Color(hex: 0xB45309), separator: Color(hex: 0xD1D5DB))
    static let dark = ChromeColors(bar: Color(hex: 0x0A1229), line: Color(hex: 0x152451), title: .white,
                                   subtitle: Color(hex: 0x9CA3AF), active: Color(hex: 0xF59E0B), separator: Color(hex: 0x4B5563))
    static func of(_ c: NeemaColors) -> ChromeColors { c.isDark ? .dark : .light }
}

/// The literal colours the web hard-codes (a subset; grows with the screens).
enum Palette {
    static let night = Color(hex: 0x070D1C)
    static let prussian900 = Color(hex: 0x0A1229)
    static let prussian800 = Color(hex: 0x152451)
    static let moss600 = Color(hex: 0x589B31)
    static let willow600 = Color(hex: 0x699A32)
    static let willow400 = Color(hex: 0x9CCD65)
    static let parchment = Color(hex: 0xF3F9EC)
    static let stone50 = Color(hex: 0xFAFAF9)
    static let stone100 = Color(hex: 0xF5F5F4)
    static let stone200 = Color(hex: 0xE7E5E4)
    static let stone500 = Color(hex: 0x78716C)
    static let stone900 = Color(hex: 0x1C1917)
    static let gray500 = Color(hex: 0x6B7280)
    static let slate400 = Color(hex: 0x94A3B8)
    static let amber50 = Color(hex: 0xFFFBEB)
    static let amber200 = Color(hex: 0xFDE68A)
    static let amber500 = Color(hex: 0xF59E0B)
    static let amber700 = Color(hex: 0xB45309)
    static let red50 = Color(hex: 0xFEF2F2)
    static let red200 = Color(hex: 0xFECACA)
    static let red500 = Color(hex: 0xEF4444)
    static let red600 = Color(hex: 0xDC2626)
    static let red700 = Color(hex: 0xB91C1C)
    static let emerald50 = Color(hex: 0xECFDF5)
    static let emerald200 = Color(hex: 0xA7F3D0)
    static let emerald500 = Color(hex: 0x10B981)
    static let emerald700 = Color(hex: 0x047857)
    static let green500 = Color(hex: 0x22C55E)
    static let blue50 = Color(hex: 0xEFF6FF)
    static let blue200 = Color(hex: 0xBFDBFE)
    static let blue500 = Color(hex: 0x3B82F6)
    static let blue700 = Color(hex: 0x1D4ED8)
    static let mossTint50 = Color(hex: 0xF1F8EB)
    static let mossTint200 = Color(hex: 0xCDE5BB)
    static let mossInk = Color(hex: 0x3F7A22)
    static let hairline = Color(hex: 0xE8EBE3)
}

/// A tone (bg / border / text / accent) for success, warning, error, info and moss, light and dark.
struct Tone {
    let bg, border, text, accent: Color
    static func success(_ dark: Bool) -> Tone {
        dark ? Tone(bg: Color(hex: 0x022C22, alpha: 0.8), border: Color(hex: 0x065F46), text: Color(hex: 0x6EE7B7), accent: Color(hex: 0x10B981))
             : Tone(bg: Color(hex: 0xECFDF5), border: Color(hex: 0xA7F3D0), text: Color(hex: 0x047857), accent: Color(hex: 0x10B981))
    }
    static func warning(_ dark: Bool) -> Tone {
        dark ? Tone(bg: Color(hex: 0x451A03, alpha: 0.8), border: Color(hex: 0x92400E), text: Color(hex: 0xFCD34D), accent: Color(hex: 0xF59E0B))
             : Tone(bg: Color(hex: 0xFFFBEB), border: Color(hex: 0xFDE68A), text: Color(hex: 0xB45309), accent: Color(hex: 0xF59E0B))
    }
    static func error(_ dark: Bool) -> Tone {
        dark ? Tone(bg: Color(hex: 0x450A0A, alpha: 0.8), border: Color(hex: 0x991B1B), text: Color(hex: 0xFCA5A5), accent: Color(hex: 0xEF4444))
             : Tone(bg: Color(hex: 0xFEF2F2), border: Color(hex: 0xFECACA), text: Color(hex: 0xB91C1C), accent: Color(hex: 0xEF4444))
    }
    static func info(_ dark: Bool) -> Tone {
        dark ? Tone(bg: Color(hex: 0x172554, alpha: 0.8), border: Color(hex: 0x1D4ED8), text: Color(hex: 0xBFDBFE), accent: Color(hex: 0x3B82F6))
             : Tone(bg: Color(hex: 0xEFF6FF), border: Color(hex: 0xBFDBFE), text: Color(hex: 0x1D4ED8), accent: Color(hex: 0x3B82F6))
    }
    static func moss(_ dark: Bool) -> Tone {
        dark ? Tone(bg: Color(hex: 0x12230B), border: Color(hex: 0x2F5A1A), text: Color(hex: 0x9CCD65), accent: Color(hex: 0x589B31))
             : Tone(bg: Color(hex: 0xF1F8EB), border: Color(hex: 0xCDE5BB), text: Color(hex: 0x3F7A22), accent: Color(hex: 0x589B31))
    }
}

/// Manrope for everything, DM Mono for phones and ids — the Android type scale.
enum NeemaFont {
    enum Weight { case regular, medium, semibold, bold, extrabold }

    private static func name(_ w: Weight) -> String {
        switch w {
        case .regular: return "Manrope-Regular"
        case .medium: return "Manrope-Medium"
        case .semibold: return "Manrope-SemiBold"
        case .bold: return "Manrope-Bold"
        case .extrabold: return "Manrope-ExtraBold"
        }
    }

    /// Scales with Dynamic Type, relative to `.body`.
    static func manrope(_ size: CGFloat, _ weight: Weight = .regular) -> Font {
        Font.custom(name(weight), size: size, relativeTo: .body)
    }

    /// A fixed size (badges, emoji tiles, chrome capped at the design size).
    static func fixed(_ size: CGFloat, _ weight: Weight = .regular) -> Font {
        Font.custom(name(weight), fixedSize: size)
    }

    static func mono(_ size: CGFloat, medium: Bool = false) -> Font {
        Font.custom(medium ? "DMMono-Medium" : "DMMono-Regular", size: size, relativeTo: .body)
    }

    // The type scale.
    static var headlineSmall: Font { manrope(22, .extrabold) }
    static var titleLarge: Font { manrope(20, .bold) }
    static var titleMedium: Font { manrope(16, .bold) }
    static var titleSmall: Font { manrope(14, .semibold) }
    static var bodyLarge: Font { manrope(15) }
    static var bodyMedium: Font { manrope(14) }
    static var bodySmall: Font { manrope(12) }
    static var labelLarge: Font { manrope(14, .semibold) }
    static var labelMedium: Font { manrope(12, .semibold) }
    static var labelSmall: Font { manrope(11, .semibold) }
}

private struct NeemaColorsKey: EnvironmentKey {
    static let defaultValue = NeemaColors.light
}

extension EnvironmentValues {
    var neema: NeemaColors {
        get { self[NeemaColorsKey.self] }
        set { self[NeemaColorsKey.self] = newValue }
    }
}
