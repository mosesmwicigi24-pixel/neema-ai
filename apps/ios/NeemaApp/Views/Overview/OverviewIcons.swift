import SwiftUI

/// The exact shapes OverviewView.tsx draws: the stat cards' STAT_ICONS
/// (heroicons, stroked 1.8) and lib/channels.tsx's brand glyphs for the By
/// Channel panel. Generated from the web sources (Android `OverviewIcons`).
enum OverviewIcons {
    static let chat = expandArcFlags("M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z")
    static let team = expandArcFlags("M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z")
    static let money = expandArcFlags("M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z")
    static let box = expandArcFlags("M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4")
    static let robot = expandArcFlags("M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z")

    /// Filled brand marks (the web's CHANNEL_CONFIG icons).
    static let whatsApp = expandArcFlags("M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z")
    static let tikTok = expandArcFlags("M12.525.02c1.31-.02 2.61-.01 3.91-.02.08 1.53.63 3.09 1.75 4.17 1.12 1.11 2.7 1.62 4.24 1.79v4.03c-1.44-.05-2.89-.35-4.2-.97-.57-.26-1.1-.59-1.62-.93-.01 2.92.01 5.84-.02 8.75-.08 1.4-.54 2.79-1.35 3.94-1.31 1.92-3.58 3.17-5.91 3.21-1.43.08-2.86-.31-4.08-1.03-2.02-1.19-3.44-3.37-3.65-5.71-.02-.5-.03-1-.01-1.49.18-1.9 1.12-3.72 2.58-4.96 1.66-1.44 3.98-2.13 6.15-1.72.02 1.48-.04 2.96-.04 4.44-.99-.32-2.15-.23-3.02.37-.63.41-1.11 1.04-1.36 1.75-.21.51-.15 1.07-.14 1.61.24 1.64 1.82 3.02 3.5 2.87 1.12-.01 2.19-.66 2.77-1.61.19-.33.4-.67.41-1.06.1-1.79.06-3.57.07-5.36.01-4.03-.01-8.05.02-12.07z")
    /// Stroked (2) marks.
    static let emailBody = expandArcFlags("M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z")
    static let emailFlap = "M22 6L12 13L2 6"
    static let sms = expandArcFlags("M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z")

    /// Which brand marks are filled shapes (the rest are stroked).
    static func filled(_ ch: String) -> String? {
        switch ch {
        case "whatsapp": return whatsApp
        case "messenger": return expandArcFlags(ChannelIcons.messenger)
        case "facebook": return expandArcFlags(ChannelIcons.facebook)
        case "instagram": return expandArcFlags(ChannelIcons.instagram)
        case "tiktok": return tikTok
        default: return nil
        }
    }

    /// SVG lets an arc's two flags run into the next number ("0 01-4.255"):
    /// put a space around each flag so a plain tokenizer reads them as digits.
    static func expandArcFlags(_ d: String) -> String {
        let chars = Array(d)
        var out = ""
        var i = 0
        var cmd: Character = " "
        var argIndex = 0
        func readNumber() -> String {
            let start = i
            if i < chars.count && (chars[i] == "-" || chars[i] == "+") { i += 1 }
            var seenDot = false
            while i < chars.count {
                let ch = chars[i]
                if ch.isNumber { i += 1 }
                else if ch == "." && !seenDot { seenDot = true; i += 1 }
                else if (ch == "e" || ch == "E") && i + 1 < chars.count { i += 1; if chars[i] == "-" || chars[i] == "+" { i += 1 } }
                else { break }
            }
            return String(chars[start..<i])
        }
        while i < chars.count {
            let ch = chars[i]
            if ch.isLetter && ch != "e" && ch != "E" {
                cmd = ch; argIndex = 0
                out += " \(ch) "
                i += 1
                continue
            }
            if ch == " " || ch == "," { i += 1; continue }
            if (cmd == "a" || cmd == "A") && (argIndex % 7 == 3 || argIndex % 7 == 4) {
                // A flag is a single digit, even when glued to the number after it.
                out += " \(ch) "
                i += 1
            } else {
                let n = readNumber()
                if n.isEmpty { i += 1; continue }
                out += " \(n)"
            }
            argIndex += 1
        }
        return out
    }
}

/// The channel's white mark in a rounded square of its colour (the By Channel panel's rows).
struct ChannelTile: View {
    let channel: String
    var size: CGFloat = 28

    var body: some View {
        let cfg = channelStyle(channel)
        ZStack {
            RoundedRectangle(cornerRadius: 8, style: .continuous).fill(cfg.color)
            if let d = OverviewIcons.filled(channel) {
                SVGIcon(d: d, size: size * 0.5).foregroundColor(.white)
            } else if channel == "email" {
                ZStack {
                    SVGStrokeIcon(d: OverviewIcons.emailBody, size: size * 0.5, width: 2)
                    SVGStrokeIcon(d: OverviewIcons.emailFlap, size: size * 0.5, width: 2)
                }
                .foregroundColor(.white)
            } else {
                SVGStrokeIcon(d: OverviewIcons.sms, size: size * 0.5, width: 2).foregroundColor(.white)
            }
        }
        .frame(width: size, height: size)
        .accessibilityLabel(cfg.label)
    }
}
