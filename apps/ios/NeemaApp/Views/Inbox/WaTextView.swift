import SwiftUI
import NeemaCore

/// WhatsApp's own formatting (*bold*, _italic_, ~strike~, `code`) and tappable
/// links, as the web's `formatWa` draws them (Android `rememberWa`).
func waAttributed(_ text: String?, font: Font, link: Color) -> AttributedString {
    let f = WaText.format(text)
    var out = AttributedString(f.plain)
    out.font = font
    func range(_ s: Int, _ e: Int) -> Range<AttributedString.Index>? {
        let chars = f.plain
        guard s <= e, e <= chars.count else { return nil }
        let a = chars.index(chars.startIndex, offsetBy: s)
        let b = chars.index(chars.startIndex, offsetBy: e)
        guard let ra = AttributedString.Index(a, within: out), let rb = AttributedString.Index(b, within: out) else { return nil }
        return ra..<rb
    }
    for span in f.spans {
        guard let r = range(span.start, span.end) else { continue }
        switch span.style {
        case .bold: out[r].font = font.weight(.bold)
        case .italic: out[r].font = font.italic()
        case .strike: out[r].strikethroughStyle = .single
        case .code: out[r].font = NeemaFont.mono(12)
        }
    }
    for l in f.links {
        guard let r = range(l.start, l.end) else { continue }
        let target = l.url.lowercased().hasPrefix("www.") ? "https://\(l.url)" : l.url
        if let u = URL(string: target) {
            out[r].link = u
            out[r].foregroundColor = link
            out[r].underlineStyle = .single
        }
    }
    return out
}

/// A message body with WhatsApp formatting, in the bubble's ink.
struct WaTextView: View {
    let text: String
    var font: Font = NeemaFont.manrope(12)
    var color: Color
    var link: Color
    var lineSpacing: CGFloat = 4

    var body: some View {
        Text(waAttributed(text, font: font, link: link))
            .foregroundColor(color)
            .lineSpacing(lineSpacing)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
    }
}
