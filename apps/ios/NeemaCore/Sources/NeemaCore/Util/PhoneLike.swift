import Foundation

/// A display name that is really a phone number, a Messenger id or a website
/// visitor: the avatar draws a glyph for it, never "initials" like "+7"
/// (Android `core/ui/components/Common.kt` `isPhoneLike`).
public func isPhoneLike(_ name: String?) -> Bool {
    let n = (name ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    if n.isEmpty { return false }
    if n.lowercased().hasPrefix("messenger id") { return true }
    if n.caseInsensitiveCompare(WEBSITE_VISITOR) == .orderedSame || n.hasPrefix("web_") { return true }
    let digits = n.filter { !" +-().".contains($0) }
    return !digits.isEmpty && digits.allSatisfy { $0.isNumber }
}

/// What `Fmt.formatPhone` calls a website-chat visitor (ids "web_...").
private let WEBSITE_VISITOR = "Website visitor"
