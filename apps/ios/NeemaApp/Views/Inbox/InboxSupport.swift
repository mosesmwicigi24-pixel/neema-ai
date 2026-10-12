import SwiftUI
import NeemaCore

// The inbox's shared looks (Android `InboxTints.kt`, `ThreadView.kt`'s WebBtn / InterceptBadge,
// `Common.kt`'s channel styles) and the rest of the web's literal palette.

extension Palette {
    // Neema's own ramps (globals.css)
    static let moss50 = Color(hex: 0xF0F9EC); static let moss100 = Color(hex: 0xE2F3D8); static let moss200 = Color(hex: 0xC5E7B1)
    static let moss700 = Color(hex: 0x427425); static let moss800 = Color(hex: 0x2C4E18); static let moss900 = Color(hex: 0x16270C)
    static let willow50 = Color(hex: 0xF3F9EC); static let willow100 = Color(hex: 0xE6F3D8); static let willow200 = Color(hex: 0xCEE6B2)
    static let willow300 = Color(hex: 0xB5DA8B); static let willow500 = Color(hex: 0x84C13E); static let willow700 = Color(hex: 0x4F7425)
    static let prussian400 = Color(hex: 0x5D7BD5); static let prussian700 = Color(hex: 0x1F367A); static let prussian850 = Color(hex: 0x0F1A38)
    static let prussian950 = Color(hex: 0x070D1C); static let nightMuted = Color(hex: 0x7A8FA8)
    static let indigo500 = Color(hex: 0x4D66B3); static let indigo900 = Color(hex: 0x0F1424)
    // The dashboard shell's sage neutrals
    static let ink = Color(hex: 0x1C2917)
    static let sage500 = Color(hex: 0x6B7E64); static let sage400 = Color(hex: 0x8A9E80); static let sage300 = Color(hex: 0xB5C9A8); static let sage200 = Color(hex: 0xDDE4D6)
    static let parchment2 = Color(hex: 0xF7F8F5); static let mist = Color(hex: 0xF5F7F2); static let leaf = Color(hex: 0xF0F4EC)
    static let avatarDisc = Color(hex: 0xF5F6F3); static let avatarInk = Color(hex: 0x3A5C28); static let avatarRing = Color(hex: 0xDDE8D5)
    static let hairline2 = Color(hex: 0xEDF0EA); static let sproutTint = Color(hex: 0xFAFEF7)
    // Tailwind neutrals
    static let stone300 = Color(hex: 0xD6D3D1); static let stone400 = Color(hex: 0xA8A29E); static let stone600 = Color(hex: 0x57534E)
    static let gray100 = Color(hex: 0xF3F4F6); static let gray200 = Color(hex: 0xE5E7EB); static let gray300 = Color(hex: 0xD1D5DB); static let gray400 = Color(hex: 0x9CA3AF)
    static let gray600 = Color(hex: 0x4B5563); static let gray700 = Color(hex: 0x374151); static let gray800 = Color(hex: 0x1F2937); static let gray900 = Color(hex: 0x111827)
    static let slate50 = Color(hex: 0xF8FAFC); static let slate100 = Color(hex: 0xF1F5F9); static let slate500 = Color(hex: 0x64748B); static let slate600 = Color(hex: 0x475569); static let slate800 = Color(hex: 0x1E293B)
    static let pewter700 = Color(hex: 0x4A5568); static let pewter600 = Color(hex: 0x718096); static let pewter500 = Color(hex: 0xA0AEC0)
    // Tailwind hues
    static let amberTint = Color(hex: 0xFEF9EC); static let amber100 = Color(hex: 0xFEF3C7); static let amber300 = Color(hex: 0xFCD34D); static let amber400 = Color(hex: 0xFBBF24)
    static let amber600 = Color(hex: 0xD97706); static let amber800 = Color(hex: 0x92400E); static let amber900 = Color(hex: 0x78350F); static let amber950 = Color(hex: 0x451A03)
    static let red100 = Color(hex: 0xFEE2E2); static let red300 = Color(hex: 0xFCA5A5); static let red400 = Color(hex: 0xF87171); static let red800 = Color(hex: 0x991B1B); static let red950 = Color(hex: 0x450A0A)
    static let emerald100 = Color(hex: 0xD1FAE5); static let emerald300 = Color(hex: 0x6EE7B7); static let emerald400 = Color(hex: 0x34D399); static let emerald600 = Color(hex: 0x059669)
    static let emerald800 = Color(hex: 0x065F46); static let emerald900 = Color(hex: 0x064E3B)
    static let green50 = Color(hex: 0xF0FDF4); static let green100 = Color(hex: 0xDCFCE7); static let green200 = Color(hex: 0xBBF7D0); static let green300 = Color(hex: 0x86EFAC)
    static let green400 = Color(hex: 0x4ADE80); static let green600 = Color(hex: 0x16A34A); static let green700 = Color(hex: 0x15803D)
    static let blue100 = Color(hex: 0xDBEAFE); static let blue300 = Color(hex: 0x93C5FD); static let blue400 = Color(hex: 0x60A5FA); static let blue600 = Color(hex: 0x2563EB)
    static let blue800 = Color(hex: 0x1E40AF); static let blue950 = Color(hex: 0x172554)
    static let violet50 = Color(hex: 0xF5F3FF); static let violet100 = Color(hex: 0xEDE9FE); static let violet200 = Color(hex: 0xDDD6FE); static let violet500 = Color(hex: 0x8B5CF6)
    static let violet600 = Color(hex: 0x7C3AED); static let violet700 = Color(hex: 0x6D28D9)
    static let sky50 = Color(hex: 0xF0F9FF); static let sky100 = Color(hex: 0xE0F2FE); static let sky200 = Color(hex: 0xBAE6FD); static let sky300 = Color(hex: 0x7DD3FC); static let sky400 = Color(hex: 0x38BDF8); static let sky700 = Color(hex: 0x0369A1)
    static let purple50 = Color(hex: 0xFAF5FF); static let purple100 = Color(hex: 0xF3E8FF); static let purple200 = Color(hex: 0xE9D5FF); static let purple300 = Color(hex: 0xD8B4FE); static let purple500 = Color(hex: 0xA855F7); static let purple700 = Color(hex: 0x7E22CE)
    static let indigo50 = Color(hex: 0xEEF2FF); static let indigo100 = Color(hex: 0xE0E7FF); static let indigo200 = Color(hex: 0xC7D2FE); static let indigo300 = Color(hex: 0xA5B4FC); static let indigo700 = Color(hex: 0x4338CA)
    static let teal50 = Color(hex: 0xF0FDFA); static let teal100 = Color(hex: 0xCCFBF1); static let teal300 = Color(hex: 0x5EEAD4)
    static let lime50 = Color(hex: 0xF7FEE7); static let lime300 = Color(hex: 0xBEF264); static let lime800 = Color(hex: 0x3F6417)
    static let orange50 = Color(hex: 0xFFF7ED); static let orange100 = Color(hex: 0xFFEDD5); static let orange200 = Color(hex: 0xFED7AA); static let orange300 = Color(hex: 0xFDBA74)
    static let orange500 = Color(hex: 0xF97316); static let orange600 = Color(hex: 0xEA580C); static let orange700 = Color(hex: 0xC2410C)
    static let yellow50 = Color(hex: 0xFEFCE8); static let yellow200 = Color(hex: 0xFEF08A); static let yellow500 = Color(hex: 0xEAB308); static let yellow700 = Color(hex: 0xA16207)
    static let rose50 = Color(hex: 0xFFF1F2); static let pink50 = Color(hex: 0xFDF2F8); static let cyan50 = Color(hex: 0xECFEFF)
    // Inbox literals (ConversationsView, CustomerSidebar)
    static let bubbleGreen = Color(hex: 0x2AD113); static let bubbleInk = Color(hex: 0x0A2E05); static let livePill = Color(hex: 0xFFF3CD); static let livePillInk = Color(hex: 0x856404)
    static let activeRow = Color(hex: 0xFDF6E9); static let unreadEdge = Color(hex: 0xFCD98A); static let pickedRow = Color(hex: 0xEEF6E5)
    static let stoneGreen = Color(hex: 0xF5F6F3); static let forestInk = Color(hex: 0x3A5C28); static let sageRing = Color(hex: 0xDDE8D5)
    static let sagePale = Color(hex: 0xC5D5BC); static let sageDeep = Color(hex: 0x3D5A30); static let sageDetail = Color(hex: 0x8FA383)
    static let sageCaption = Color(hex: 0x5F6F57); static let sageRim = Color(hex: 0xCFDAC6); static let sageDash = Color(hex: 0xC7CEC0)
    static let sageField = Color(hex: 0xE5E8E2); static let sageFieldBg = Color(hex: 0xF6F7F5); static let sageRule = Color(hex: 0xF2F4EF)
    static let sageQuote = Color(hex: 0xF2F7EE); static let sageStrip = Color(hex: 0xFBFCFA); static let sageBanner = Color(hex: 0xFAFBF8)
    static let sageResult = Color(hex: 0xF8FAF6); static let sageResultRim = Color(hex: 0xE8EDE4); static let sageButton = Color(hex: 0xEEF2E8)
    static let mossNight = Color(hex: 0x7FC25A); static let mossBright = Color(hex: 0x86C95E); static let mossWash = Color(hex: 0xE9F6DF)
    static let mossRim = Color(hex: 0xD6E9C2); static let mossTint = Color(hex: 0xF0F9E8); static let forestText = Color(hex: 0x1A2E0F)
    static let coolGray = Color(hex: 0xF1F3F5); static let whatsAppDeep = Color(hex: 0x1DA851); static let messengerSky = Color(hex: 0x0099FF)
    static let pipeGold = Color(hex: 0xC89B3C); static let pipeGoldSolid = Color(hex: 0xA97C14); static let pipeGoldInk = Color(hex: 0x8A6D1F); static let pipeGoldWash = Color(hex: 0xFDF8EC)
    static let pipeGoldRim = Color(hex: 0xE3CF9B); static let pipeLost = Color(hex: 0xF4CCCC); static let pipeLostIcon = Color(hex: 0xEFA3A3); static let pipeLostText = Color(hex: 0xE08A8A)
    static let sproutWash = Color(hex: 0xEAF5DD); static let dangerWash = Color(hex: 0xFFF5F5)
    static let dealsPage = Color(hex: 0xF6F7F2); static let needsBg = Color(hex: 0xFDF6E9); static let needsBorder = Color(hex: 0xF0DDB0)
    static let queuedBg = Color(hex: 0xF8FAF6); static let queuedBorder = Color(hex: 0xE8EDE4); static let wonBg = Color(hex: 0xE9F6DF)
    static let hubLinkBorder = Color(hex: 0xCFE3BD); static let paneHighlight = Color(hex: 0xF7FBF2)
    static let mpesaGreen = Color(hex: 0x00A651); static let slackAubergine = Color(hex: 0x4A154B); static let sheetsGreen = Color(hex: 0x0F9D58)
    /// The thread's "Use as reply" button and summary accents (#128C4B, 4.9:1 with white).
    static let replyGreen = Color(hex: 0x128C4B)
    /// The suggested reply's box under a call summary.
    static let suggestedReplyBg = Color(hex: 0xF3F8F1)
    /// WhatsApp's deepest green: white text on it on light surfaces.
    static let waDeep = Color(hex: 0x008069)
}

/// Brand channel colours (lib/channels.tsx).
enum ChannelColors {
    static let whatsApp = Color(hex: 0x25D366)
    static let messenger = Color(hex: 0x0084FF)
    static let facebook = Color(hex: 0x1877F2)
    static let instagram = Color(hex: 0xE1306C)
    static let tikTok = Color(hex: 0x010101)
    static let email = Color(hex: 0x6366F1)
    static let sms = Color(hex: 0x64748B)
    static let web = Color(hex: 0x589B31)
}

struct ChannelStyle {
    let label: String
    let color: Color
}

func channelStyle(_ channel: String?) -> ChannelStyle {
    switch channel?.lowercased() {
    case "messenger": return ChannelStyle(label: "Messenger", color: ChannelColors.messenger)
    case "facebook": return ChannelStyle(label: "Facebook", color: ChannelColors.facebook)
    case "instagram": return ChannelStyle(label: "Instagram", color: ChannelColors.instagram)
    case "tiktok": return ChannelStyle(label: "TikTok", color: ChannelColors.tikTok)
    case "email": return ChannelStyle(label: "Email", color: ChannelColors.email)
    case "sms": return ChannelStyle(label: "SMS", color: ChannelColors.sms)
    case "web": return ChannelStyle(label: "Web chat", color: ChannelColors.web)
    default: return ChannelStyle(label: "WhatsApp", color: ChannelColors.whatsApp)
    }
}

let CH_SHORT: [String: String] = ["whatsapp": "WA", "messenger": "MSG", "facebook": "FB", "instagram": "IG", "tiktok": "TT", "email": "Email", "sms": "SMS"]

/// A tinted surface — a chip, a pill, a strip — as the web draws it in light
/// mode (a Tailwind `*-50` fill, `*-200` border and `*-700` ink). In dark
/// mode the same hue becomes a translucent wash of its ink over the dark
/// surface, a stronger rim, and the ink lifted toward white.
struct Tint {
    let bg: Color
    let fg: Color
    let border: Color
}

extension Color {
    /// The colour's components in sRGB (0…1), for the dark-mode lifts.
    var rgba: (r: Double, g: Double, b: Double, a: Double) {
        #if canImport(UIKit)
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        UIColor(self).getRed(&r, green: &g, blue: &b, alpha: &a)
        return (Double(r), Double(g), Double(b), Double(a))
        #else
        return (0, 0, 0, 1)
        #endif
    }

    /// `lerp(self, white, t)`.
    func lifted(_ t: Double) -> Color {
        let c = rgba
        return Color(.sRGB, red: c.r + (1 - c.r) * t, green: c.g + (1 - c.g) * t, blue: c.b + (1 - c.b) * t, opacity: c.a)
    }

    /// Relative luminance (WCAG).
    var luminance: Double {
        let c = rgba
        func lin(_ v: Double) -> Double { v <= 0.03928 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4) }
        return 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b)
    }
}

/// The ink of a tint lifted toward white for the dark surfaces.
func darkInk(_ fg: Color) -> Color { fg.lifted(0.45) }

/// The dark-mode form of a tint whose light-mode ink is `fg`.
func darkTint(_ fg: Color) -> Tint { Tint(bg: fg.opacity(0.16), fg: darkInk(fg), border: darkInk(fg).opacity(0.45)) }

func tintOf(_ bg: Color, _ fg: Color, _ border: Color? = nil, dark: Bool) -> Tint {
    dark ? darkTint(fg) : Tint(bg: bg, fg: fg, border: border ?? bg)
}

/// Just the ink of a tint — text sitting on the page, not on a tinted box.
func ink(_ fg: Color, dark: Bool) -> Color { dark ? darkInk(fg) : fg }

/// White or ink for text on `bg`, a colour chosen at run time (a role's, a tag's): ink only where white fails 4.5:1 and ink passes it.
func contentOn(_ bg: Color, ink: Color = Palette.ink) -> Color {
    let l = bg.luminance
    let onWhite = 1.05 / (l + 0.05)
    let onInk = (l + 0.05) / (ink.luminance + 0.05)
    return onWhite < 4.5 && onInk >= 4.5 ? ink : .white
}

/// The inbox's hairline: `#edf0ea` in light, the theme's border in dark.
func hairline(_ c: NeemaColors) -> Color { c.isDark ? c.border : Palette.hairline2 }

/// Stable hue per name, for initials avatars.
func avatarColor(_ seed: String?) -> Color {
    let palette: [UInt32] = [0x589B31, 0x2A48A2, 0x3D528F, 0xC0392B, 0x0E7490, 0x9333EA, 0xD97706, 0x0F766E, 0xBE185D, 0x4F7425]
    var h = 0
    for ch in (seed ?? "?").unicodeScalars { h = (h &* 31 &+ Int(ch.value)) & 0x7fffffff }
    return Color(hex: palette[h % palette.count])
}

// ── Buttons and badges ────────────────────────────────────────────────────────

/// components/ui/Btn.tsx variants — primary is AMBER there, not moss.
enum BtnVariant { case primary, secondary, danger, ghost, outline }

/// components/ui/Btn.tsx sizes: `sm` (h-8, px-3, text-xs) and the default `md` (h-9, px-4, text-sm).
enum BtnSize {
    case sm, md
    var height: CGFloat { self == .sm ? 32 : 36 }
    var padX: CGFloat { self == .sm ? 12 : 16 }
    var font: CGFloat { self == .sm ? 12 : 14 }
}

/// The web's `<Btn>`: rounded-lg, medium weight, gap-1.5, disabled at 40 % — in each variant's own light and dark colours.
struct WebBtn: View {
    var label: String?
    var variant: BtnVariant
    var lead: String? = nil
    var enabled: Bool = true
    var busy: Bool = false
    var size: BtnSize = .sm
    var action: () -> Void
    @Environment(\.neema) private var c

    private var colors: (bg: Color, fg: Color, bd: Color) {
        let dark = c.isDark
        switch variant {
        case .primary: return (Palette.amber500, .white, Palette.amber500)
        case .secondary: return dark ? (Palette.gray800, Palette.gray200, Palette.gray700) : (.white, Palette.gray700, Palette.gray200)
        case .danger: return dark ? (Palette.red950.opacity(0.3), Palette.red400, Palette.red800) : (Palette.red50, Palette.red600, Palette.red200)
        case .ghost: return (.clear, dark ? Palette.gray400 : Palette.gray500, .clear)
        case .outline: return (.clear, dark ? Palette.gray200 : Palette.gray700, dark ? Palette.gray600 : Palette.gray300)
        }
    }

    var body: some View {
        let col = colors
        Button(action: action) {
            HStack(spacing: 6) {
                if busy {
                    ProgressView().progressViewStyle(.circular).tint(col.fg).scaleEffect(0.6).frame(width: 12, height: 12)
                } else if let l = lead {
                    Text(l).font(NeemaFont.manrope(size.font)).foregroundColor(col.fg).lineLimit(1)
                }
                if let t = label { Text(t).font(NeemaFont.manrope(size.font, .medium)).foregroundColor(col.fg).lineLimit(1) }
            }
            .padding(.horizontal, size.padX).padding(.vertical, 4)
            .frame(minHeight: size.height)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(col.bg))
            .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(col.bd))
            .opacity(enabled ? 1 : 0.4)
        }
        .buttonStyle(.plain)
        .disabled(!enabled || busy)
    }
}

/// AI / Human / Paused (components/ui/Badges.tsx InterceptBadge), light and dark.
struct InterceptBadge: View {
    let mode: String
    @Environment(\.neema) private var c

    var body: some View {
        let dark = c.isDark
        let (bg, fg, bd, label): (Color, Color, Color, String) = {
            switch mode {
            case "human": return dark ? (Palette.amber950.opacity(0.4), Palette.amber400, Palette.amber800, "Human") : (Palette.amber50, Palette.amber700, Palette.amber200, "Human")
            case "paused": return dark ? (Palette.gray800, Palette.gray400, Palette.gray700, "Paused") : (Palette.gray100, Palette.gray500, Palette.gray200, "Paused")
            default: return dark ? (Palette.blue950.opacity(0.4), Palette.blue400, Palette.blue800, "AI") : (Palette.blue50, Palette.blue700, Palette.blue200, "AI")
            }
        }()
        Text(label).font(NeemaFont.manrope(11, .medium)).foregroundColor(fg).lineLimit(1)
            .padding(.horizontal, 8).padding(.vertical, 2)
            .background(RoundedRectangle(cornerRadius: 4).fill(bg))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(bd))
    }
}

/// A count in a capsule ("99+" past 99).
struct CountCapsule: View {
    let n: Int
    var color: Color = Palette.moss600
    var fg: Color = .white
    var size: CGFloat = 10
    var body: some View {
        Text(n > 99 ? "99+" : String(n))
            .font(NeemaFont.fixed(size, .bold)).foregroundColor(fg).lineLimit(1)
            .padding(.horizontal, 4).padding(.vertical, 3)
            .frame(minWidth: 18)
            .background(Capsule().fill(color))
    }
}

/// The channel chip: the short brand code on the brand hue (a filled chip when it is the open thread).
struct ChannelCodeChip: View {
    let channel: String
    var open: Bool = false
    var dotted: Bool = false
    @Environment(\.neema) private var c
    var body: some View {
        let st = channelStyle(channel)
        Text(CH_SHORT[channel] ?? st.label)
            .font(NeemaFont.manrope(10, .bold))
            .foregroundColor(open ? .white : ink(st.color, dark: c.isDark))
            .lineLimit(1)
            .padding(.horizontal, 6).padding(.vertical, 1)
            .background(RoundedRectangle(cornerRadius: 4).fill(open ? st.color : st.color.opacity(c.isDark ? 0.16 : 0.08)))
            .overlay(RoundedRectangle(cornerRadius: 4).stroke(open ? st.color : st.color.opacity(c.isDark ? 0.45 : 0.2)))
            .overlay(alignment: .topTrailing) {
                if dotted { Circle().fill(Palette.moss600).frame(width: 6, height: 6).offset(x: 3, y: -3) }
            }
    }
}

// ── Layout helpers ───────────────────────────────────────────────────────────

/// Compose's FlowRow: items wrap onto the next line when the row is full.
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    var lineSpacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineH: CGFloat = 0, maxW: CGFloat = 0
        for s in subviews {
            let sz = s.sizeThatFits(.unspecified)
            if x > 0 && x + sz.width > width { x = 0; y += lineH + lineSpacing; lineH = 0 }
            x += sz.width + spacing
            lineH = max(lineH, sz.height)
            maxW = max(maxW, x - spacing)
        }
        return CGSize(width: width == .infinity ? maxW : min(width, maxW), height: y + lineH)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x: CGFloat = 0, y: CGFloat = 0, lineH: CGFloat = 0
        var line: [(LayoutSubview, CGSize, CGFloat)] = []
        func flush() {
            for (v, size, px) in line {
                v.place(at: CGPoint(x: bounds.minX + px, y: bounds.minY + y + (lineH - size.height) / 2), proposal: ProposedViewSize(size))
            }
            line = []
        }
        for s in subviews {
            let sz = s.sizeThatFits(.unspecified)
            if x > 0 && x + sz.width > bounds.width {
                flush()
                x = 0; y += lineH + lineSpacing; lineH = 0
            }
            line.append((s, sz, x))
            x += sz.width + spacing
            lineH = max(lineH, sz.height)
        }
        flush()
    }
}

/// CSS `border border-dashed`: a 1 pt dashed outline following the rounded shape.
struct DashedRoundedBorder: ViewModifier {
    let color: Color
    let radius: CGFloat
    func body(content: Content) -> some View {
        content.overlay(RoundedRectangle(cornerRadius: radius, style: .continuous).stroke(color, style: StrokeStyle(lineWidth: 1, dash: [3, 3])))
    }
}

extension View {
    func dashedBorder(_ color: Color, radius: CGFloat) -> some View { modifier(DashedRoundedBorder(color: color, radius: radius)) }
    func roundedBorder(_ color: Color, radius: CGFloat, width: CGFloat = 1) -> some View {
        overlay(RoundedRectangle(cornerRadius: radius, style: .continuous).stroke(color, lineWidth: width))
    }
}

/// CSS `border-t border-dashed`: a 1 pt dashed hairline across the full width.
struct DashedRule: View {
    let color: Color
    var body: some View {
        Rectangle().fill(.clear).frame(height: 1)
            .overlay(GeometryReader { g in
                Path { p in p.move(to: CGPoint(x: 0, y: 0.5)); p.addLine(to: CGPoint(x: g.size.width, y: 0.5)) }
                    .stroke(color, style: StrokeStyle(lineWidth: 1, dash: [3, 3]))
            })
    }
}

/// The web's thin rule between rows.
struct Hairline: View {
    var color: Color
    var body: some View { Rectangle().fill(color).frame(height: 0.5) }
}

/// `Fmt.timeAgo` for an optional ISO.
func timeAgo(_ iso: String?) -> String { iso.map { Fmt.timeAgo($0) } ?? "" }
