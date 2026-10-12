import SwiftUI
import NeemaCore

/// The call screens' own colours (Android `Palette.Call`): CallsView.tsx and
/// CallStage.tsx style themselves inline with a WhatsApp-dark palette that is
/// neither Tailwind nor Neema's. Translucent variants are these at the web's
/// rgba() alpha; WhatsApp green itself is `ChannelColors.whatsApp`.
enum CallInk {
    // CallsView.tsx — the call-log console.
    static let green = Color(hex: 0x2AD17F)
    static let red = Color(hex: 0xF2555A)
    static let amber = Color(hex: 0xF5A623)
    static let muted = Color(hex: 0x7F9B8B)
    static let dim = Color(hex: 0x6B8577)
    static let text = Color(hex: 0xE9EDEF)
    static let soft = Color(hex: 0xCFE9D9)
    static let sage = Color(hex: 0x9FB3A8)
    /// The console card's night fill (and the ink on its green buttons).
    static let ink = Color(hex: 0x0B1410)
    /// The glow at the top of the console card's radial gradient.
    static let glow = Color(hex: 0x123626)
    /// "Transcribing…", the readiness bell.
    static let gold = Color(hex: 0xF5C451)
    /// The missed-count badge's text.
    static let missedText = Color(hex: 0xFF8A8D)
    /// `avatarColor`'s six discs.
    static let avatars: [Color] = [
        Color(hex: 0x3B6EA5), Color(hex: 0xA5417D), Color(hex: 0xB5892F), Color(hex: 0x3C8C5A), Color(hex: 0x8A4FC4), Color(hex: 0xB24A4A),
    ]
    /// WhatsApp green (ChannelColors.WhatsApp): the console card's outline, the row buttons.
    static let whatsApp = Color(hex: 0x25D366)

    // The call screen (docs/CALLING_UX.md §5): WhatsApp's own dark call surface.
    static let waTop = Color(hex: 0x0B141A)
    static let waBottom = Color(hex: 0x111B21)
    static let waText = Color(hex: 0xE9EDEF)
    static let waSub = Color(hex: 0x8696A0)
    /// WhatsApp's teal (accents, the minimised bar's live dot).
    static let waTeal = Color(hex: 0x00A884)
    /// WhatsApp's darker green: white TEXT on it reads at 4.9:1.
    static let waTealText = Color(hex: 0x008069)
    /// End / decline.
    static let waRed = Color(hex: 0xEA0038)
    /// A round control that is off.
    static let waControl = Color(hex: 0x2A3942)
    /// The rounded bar the controls sit in, and banners on the call surface.
    static let waBar = Color(hex: 0x1F2C33)
    /// "Reconnecting…" (always with its icon — never colour alone).
    static let waAmber = Color(hex: 0xFFB02E)
    /// The outcome words when the agent still owes the customer something (the web's #FFD1D9).
    static let owed = Color(hex: 0xFFD1D9)
    /// "● Rec" on the minimised bar (CallStage.tsx #FF6B81).
    static let rec = Color(hex: 0xFF6B81)
}

/// Messenger's accent on the call surfaces (CallStage.tsx MSGR): white glyph on
/// `blue` is 3.7:1 (≥ 3:1 for the Answer icon); text buttons sit on the darker
/// `ink` (5.4:1 for white text). Everything else about a call is shared.
enum Msgr {
    static let blue = Color(hex: 0x0084FF)
    static let ink = Color(hex: 0x0066D6)
    static let purple = Color(hex: 0xA033FF)
    static var ring: LinearGradient { LinearGradient(colors: [blue, purple], startPoint: .bottomLeading, endPoint: .topTrailing) }
    /// The badge on the dark call log (CallsView.tsx CH_BADGE): 7:1+ on its tint.
    static let badgeFg = Color(hex: 0x9CCBFF)
    static let badgeBg = Color(hex: 0x0084FF, alpha: 0.18)
}

/// The one accent a call's surface changes by channel (CallStage.tsx accent()):
/// Messenger's blue Answer, its darker blue behind white words, its blue pulse
/// and the blue → purple ring round the avatar. Everything else is shared.
struct CallAccent {
    let answer: Color
    let button: Color
    let pulse: Color
    let dot: Color
    let ring: Bool
    static let whatsApp = CallAccent(answer: CallInk.waTeal, button: CallInk.waTealText, pulse: CallInk.whatsApp, dot: CallInk.whatsApp, ring: false)
    static let messenger = CallAccent(answer: Msgr.blue, button: Msgr.ink, pulse: Msgr.blue, dot: Msgr.blue, ring: true)
    static func of(_ channel: String?) -> CallAccent { channelOf(channel) == CallWords.MESSENGER ? .messenger : .whatsApp }
}

/// The exact stroked icons CallStage.tsx (ICONS) and CallsView.tsx (DirIcon,
/// the transcript and chat buttons) draw, from the web's own SVG paths
/// (Android `CallIcons`). Tinted by the view that shows them.
enum CallIcons {
    static let handset = OverviewIcons.expandArcFlags("M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z")

    // CallStage.tsx ICONS (stroke 2).
    static let phone = WebGlyph(2, handset)
    static let callback = WebGlyph(2, "M9 14l-4-4 4-4M5 10h11a4 4 0 014 4v3")
    static let mic = WebGlyph(2, "M12 2a3 3 0 00-3 3v6a3 3 0 006 0V5a3 3 0 00-3-3z", "M5 10v1a7 7 0 0014 0v-1M12 18v3")
    static let micOff = WebGlyph(2, "M3 3l18 18", "M9 5a3 3 0 016 0v5m-1.3 2.7A3 3 0 019 11V9", "M5 10v1a7 7 0 0010.7 5.9M19 10v1a6.9 6.9 0 01-.3 2M12 18v3")
    static let speaker = WebGlyph(2, "M11 5L6 9H2v6h4l5 4V5z", "M15.54 8.46a5 5 0 010 7.07", "M19.07 4.93a10 10 0 010 14.14")
    static let minimise = WebGlyph(2, "M6 9l6 6 6-6")
    static let bluetooth = WebGlyph(2, "M7 7l10 10-5 5V2l5 5L7 17")
    static let headset = WebGlyph(2, "M3 18v-6a9 9 0 0118 0v6", "M21 19a2 2 0 01-2 2h-1a2 2 0 01-2-2v-3a2 2 0 012-2h3z", "M3 19a2 2 0 002 2h1a2 2 0 002-2v-3a2 2 0 00-2-2H3z")
    static let earpiece = WebGlyph(2, "M7 2h10a2 2 0 012 2v16a2 2 0 01-2 2H7a2 2 0 01-2-2V4a2 2 0 012-2z", "M12 18h.01")
    /// Reconnecting: never colour alone — this icon and the words.
    static let noSignal = WebGlyph(2, "M1 1l22 22", "M16.72 11.06A10.94 10.94 0 0119 12.55", "M5 12.55a10.94 10.94 0 015.17-2.39",
                                   "M10.71 5.05A16 16 0 0122.58 9", "M1.42 9a15.91 15.91 0 014.7-2.88", "M8.53 16.11a6 6 0 016.95 0", "M12 20h.01")
    static let check = WebGlyph(2.2, "M5 13l4 4L19 7")
    /// A wrap-up the agent must act on (CallStage.tsx "alert").
    static let alert = WebGlyph(2, "M12 9v4M12 17h.01", "M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z")
    static let close = WebGlyph(2, "M18 6L6 18M6 6l12 12")

    // CallsView.tsx DirIcon (stroke 2.2).
    static let dirIn = WebGlyph(2.2, "M17 7L7 17M7 17h7M7 17V10")
    static let dirBack = WebGlyph(2.2, "M9 14l-4-4 4-4M5 10h10a4 4 0 014 4v2")
    static let dirOut = WebGlyph(2.2, "M7 17L17 7M17 7h-7M17 7v7")
    /// A missed call: the arrow that turns back (as the phone's call log draws it).
    static let dirMissed = WebGlyph(2.2, "M3 7l6 6 4-4 8 8M21 11v6h-6")

    // CallsView.tsx row buttons (stroke 2).
    static let transcript = WebGlyph(2, "M4 6h16M4 12h16M4 18h10")
    static let chat = WebGlyph(2, "M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z")

    static func of(_ d: CallDirIcon) -> WebGlyph {
        switch d {
        case .out: return dirOut
        case .in: return dirIn
        case .missed: return dirMissed
        case .back: return dirBack
        }
    }
}

/// Answer: the filled handset (CallStage.tsx "phone-fill"); Decline / End: the
/// same handset tipped down (rotate(135 12 12) scale(.95)) — the hang-up glyph
/// every phone and WhatsApp use.
struct HandsetIcon: View {
    var down: Bool = false
    var size: CGFloat = 24
    var body: some View {
        SVGShape(d: CallIcons.handset).fill()
            .frame(width: size, height: size)
            .scaleEffect(down ? 0.95 : 1)
            .rotationEffect(.degrees(down ? 135 : 0))
            .accessibilityHidden(true)
    }
}

/// The call glyphs of CallStage.tsx (WhatsAppGlyph / MessengerGlyph), 24×24 (Android `ChannelGlyphs`).
enum ChannelGlyphs {
    static let msgrBubble = OverviewIcons.expandArcFlags("M12 2C6.36 2 2 6.13 2 11.7c0 2.91 1.19 5.44 3.14 7.17.16.14.26.35.27.57l.05 1.78a.8.8 0 001.12.71l1.98-.87a.8.8 0 01.53-.04c.91.25 1.87.38 2.91.38 5.64 0 10-4.13 10-9.7S17.64 2 12 2z")
    static let msgrBolt = OverviewIcons.expandArcFlags("M6 14.54l2.94-4.66a1.5 1.5 0 012.17-.4l2.34 1.75a.6.6 0 00.72 0l3.16-2.4c.42-.32.97.18.69.63l-2.94 4.66a1.5 1.5 0 01-2.17.4l-2.34-1.75a.6.6 0 00-.72 0l-3.16 2.4c-.42.32-.97-.18-.69-.63z")
    static let waRing = OverviewIcons.expandArcFlags("M12 2a10 10 0 00-8.6 15.1L2 22l5-1.3A10 10 0 1012 2zm0 1.8a8.2 8.2 0 11-4.2 15.3l-.3-.2-3 .8.8-2.9-.2-.3A8.2 8.2 0 0112 3.8z")
    static let waHandset = OverviewIcons.expandArcFlags("M8.9 7.3c-.2-.4-.4-.4-.6-.4h-.5a1 1 0 00-.7.3 3 3 0 00-.9 2.2 5.2 5.2 0 001.1 2.7 11.8 11.8 0 004.6 4c2.3.9 2.7.7 3.2.7a2.7 2.7 0 001.8-1.3 2.2 2.2 0 00.2-1.3c-.1-.1-.3-.2-.6-.3l-1.9-.9c-.3-.1-.5-.2-.7.1l-.8 1a.5.5 0 01-.7.1 6.8 6.8 0 01-2-1.2 7.5 7.5 0 01-1.4-1.7.4.4 0 01.1-.6l.4-.5.3-.5a.5.5 0 000-.4l-.9-2z")
}

/// The call's app glyph: Messenger's own colours (its bubble in the blue →
/// purple gradient with the white bolt), or WhatsApp's bubble + handset in `waTint`.
struct ChannelGlyph: View {
    let channel: String?
    var size: CGFloat = 14
    var waTint: Color = CallInk.green

    var body: some View {
        if channelOf(channel) == CallWords.MESSENGER {
            ZStack {
                SVGShape(d: ChannelGlyphs.msgrBubble).fill(Msgr.ring)
                SVGShape(d: ChannelGlyphs.msgrBolt).fill(Color.white)
            }
            .frame(width: size, height: size)
            .accessibilityHidden(true)
        } else {
            ZStack {
                SVGShape(d: ChannelGlyphs.waRing).fill(waTint)
                SVGShape(d: ChannelGlyphs.waHandset).fill(waTint)
            }
            .frame(width: size, height: size)
            .accessibilityHidden(true)
        }
    }
}

/// The web's `avatarColor`: `[...s].reduce((a, c) => a + c.charCodeAt(0))` —
/// one term per code point, taking its FIRST UTF-16 unit (so an emoji adds
/// its high surrogate once, not both halves).
func avatarIndex(_ s: String) -> Int {
    let src = s.isEmpty ? "?" : s
    var sum = 0
    for scalar in src.unicodeScalars {
        let utf16 = Array(String(scalar).utf16)
        sum += Int(utf16.first ?? 0)
    }
    return sum % CallInk.avatars.count
}

func avatarColor(_ s: String) -> Color { CallInk.avatars[avatarIndex(s)] }

/// The row's initials: who minus its first "+", first letter of the first two
/// words, upper-cased. A word starting with an emoji keeps the whole emoji.
func initialsOf(_ who: String) -> String {
    var s = who
    if let r = s.range(of: "+") { s.removeSubrange(r) }
    let words = s.split(whereSeparator: { $0.isWhitespace }).map(String.init).filter { !$0.isEmpty }
    return words.prefix(2).map { Fmt.firstGrapheme($0) }.joined().uppercased()
}

/// The outcome word's colour on the dark log (the word is always there too).
func callToneColor(_ t: CallTone) -> Color {
    switch t {
    case .live, .good: return CallInk.green
    case .bad: return CallInk.red
    case .warn: return CallInk.amber
    case .neutral: return CallInk.sage
    }
}

/// A recording_url is absolute when the server knows its public base, else a bare filename under /api/admin/media.
func recordingUrl(_ raw: String) -> String {
    if raw.hasPrefix("http://") || raw.hasPrefix("https://") { return raw }
    let base = NeemaConfig.baseUrl.hasSuffix("/") ? String(NeemaConfig.baseUrl.dropLast()) : NeemaConfig.baseUrl
    let name = raw.split(separator: "/").last.map(String.init) ?? raw
    return "\(base)/api/admin/media/\(name)"
}

/// The wrap-up's outcome glyph (CallStage.tsx OUTCOME_ICON); nil means the handset tipped down.
func outcomeGlyph(_ o: CallOutcome?) -> WebGlyph? {
    switch o {
    case .answeredElsewhere, .permissionRequested, .alreadyAllowed: return CallIcons.check
    case .missed: return CallIcons.dirIn
    case .callback: return CallIcons.callback
    case .connectionLost: return CallIcons.noSignal
    case .noAnswer, .rejected, .failed, .permissionNeeded, .micBlocked: return CallIcons.alert
    default: return nil
    }
}

func routeGlyph(_ k: AudioRouteKind) -> WebGlyph {
    switch k {
    case .earpiece: return CallIcons.earpiece
    case .speaker: return CallIcons.speaker
    case .wired: return CallIcons.headset
    case .bluetooth: return CallIcons.bluetooth
    }
}

/// "3 minutes 4 seconds" for the timer's accessibility label.
func spokenLength(_ s: Int) -> String {
    let m = s / 60, sec = s % 60
    return m > 0 ? "\(m) minute\(m == 1 ? "" : "s") \(sec) second\(sec == 1 ? "" : "s")" : "\(sec) second\(sec == 1 ? "" : "s")"
}

/// The Calls view's details pane on a tablet: the newest call shown opens in it
/// when none is open or the open one was filtered away; the agent's own pick
/// stays. Shrinking to a phone-sized window drops only a call the app picked,
/// so a ⅓ split shows the log rather than a call nobody asked for.
struct DetailsPick: Equatable {
    let select: String?
    let autoPicked: String?
}

func detailsPick(wide: Bool, shownIds: [String], selected: String?, autoPicked: String?) -> DetailsPick {
    if !wide { return DetailsPick(select: selected != nil && selected == autoPicked ? nil : selected, autoPicked: nil) }
    guard let first = shownIds.first else { return DetailsPick(select: selected, autoPicked: autoPicked) }
    if selected == nil || !shownIds.contains(selected!) { return DetailsPick(select: first, autoPicked: first) }
    return DetailsPick(select: selected, autoPicked: selected == autoPicked ? autoPicked : nil)
}
