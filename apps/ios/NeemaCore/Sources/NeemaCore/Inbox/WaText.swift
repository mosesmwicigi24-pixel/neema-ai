import Foundation

/// Port of lib/waText.tsx: WhatsApp-style inline formatting — *bold* (and
/// legacy Markdown **bold**), _italics_, ~strikethrough~, `monospace` and
/// ```monospace``` — plus tappable links, as data the views render.
/// Display-only; the stored text is untouched. Longer delimiters win over
/// shorter ones at the same position.
public enum WaStyle: String, Equatable, Hashable, Sendable { case bold, italic, strike, code }

public struct WaSpan: Equatable, Hashable, Sendable {
    /// Character offsets into `WaFormatted.plain`.
    public let start: Int
    public let end: Int
    public let style: WaStyle
    public init(start: Int, end: Int, style: WaStyle) { self.start = start; self.end = end; self.style = style }
}

public struct WaLink: Equatable, Hashable, Sendable {
    public let start: Int
    public let end: Int
    public let url: String
    public init(start: Int, end: Int, url: String) { self.start = start; self.end = end; self.url = url }
}

public struct WaFormatted: Equatable, Hashable, Sendable {
    public let plain: String
    public let spans: [WaSpan]
    public let links: [WaLink]
    public static let empty = WaFormatted(plain: "", spans: [], links: [])
    public init(plain: String, spans: [WaSpan], links: [WaLink]) { self.plain = plain; self.spans = spans; self.links = links }

    /// The styled text of one span (tests and accessibility).
    public func text(of span: WaSpan) -> String { slice(span.start, span.end) }
    public func text(of link: WaLink) -> String { slice(link.start, link.end) }
    private func slice(_ s: Int, _ e: Int) -> String {
        let a = plain.index(plain.startIndex, offsetBy: min(s, plain.count))
        let b = plain.index(plain.startIndex, offsetBy: min(e, plain.count))
        return String(plain[a..<b])
    }
}

public enum WaText {
    private static let token = try! NSRegularExpression(pattern: "(```[^`]+```|\\*\\*[^*\\n]+\\*\\*|\\*[^*\\n]+\\*|_[^_\\n]+_|~[^~\\n]+~|`[^`\\n]+`)")
    private static let url = try! NSRegularExpression(pattern: "(https?://[^\\s<>\"]+|www\\.[^\\s<>\"]+)", options: [.caseInsensitive])

    public static func format(_ text: String?) -> WaFormatted {
        guard let text = text, !text.isEmpty else { return .empty }
        var plain = ""
        var spans: [WaSpan] = []
        var last = text.startIndex
        func append(_ s: Substring) { plain += s }
        func styled(_ s: Substring, _ style: WaStyle) {
            let start = plain.count
            plain += s
            spans.append(WaSpan(start: start, end: plain.count, style: style))
        }
        for m in token.matches(in: text, range: NSRange(text.startIndex..., in: text)) {
            guard let r = Range(m.range, in: text) else { continue }
            if r.lowerBound > last { append(text[last..<r.lowerBound]) }
            let part = text[r]
            let n = part.count
            if part.hasPrefix("```") && n > 6 {
                styled(part.dropFirst(3).dropLast(3), .code)
            } else if part.hasPrefix("**") && part.hasSuffix("**") && n > 4 {
                styled(part.dropFirst(2).dropLast(2), .bold)
            } else if part.hasPrefix("*") && n > 2 {
                styled(part.dropFirst().dropLast(), .bold)
            } else if part.hasPrefix("_") && n > 2 {
                styled(part.dropFirst().dropLast(), .italic)
            } else if part.hasPrefix("~") && n > 2 {
                styled(part.dropFirst().dropLast(), .strike)
            } else if part.hasPrefix("`") && n > 2 {
                styled(part.dropFirst().dropLast(), .code)
            } else {
                append(part)
            }
            last = r.upperBound
        }
        if last < text.endIndex { append(text[last...]) }
        // Links are found on the rendered text so a link inside *bold* still works.
        var links: [WaLink] = []
        for m in url.matches(in: plain, range: NSRange(plain.startIndex..., in: plain)) {
            guard let r = Range(m.range, in: plain) else { continue }
            var end = r.upperBound
            // Trailing punctuation belongs to the sentence, not the URL.
            while end > r.lowerBound, ".,;:!?)".contains(plain[plain.index(before: end)]) { end = plain.index(before: end) }
            let raw = String(plain[r.lowerBound..<end])
            let link = raw.lowercased().hasPrefix("www.") ? "https://\(raw)" : raw
            links.append(WaLink(start: plain.distance(from: plain.startIndex, to: r.lowerBound), end: plain.distance(from: plain.startIndex, to: end), url: link))
        }
        return WaFormatted(plain: plain, spans: spans, links: links)
    }
}
