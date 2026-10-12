import Foundation

/// Hardware-keyboard shortcuts (an iPad with a Magic Keyboard or any Bluetooth
/// keyboard; Android `core/ui/Shortcuts.kt` for the Tab S9 Ultra's Book Cover
/// Keyboard). The decisions are pure, so every combination is unit-tested;
/// the views only read the key event and act.
///
/// - Return sends a reply when a hardware keyboard is attached; Shift+Return
///   is a new line. Cmd/Ctrl+Return always sends (the on-screen keyboard too).
/// - Cmd+1...9 opens the nth view in the navigation; Cmd+B shows or hides the
///   sidebar's labels.
/// - In the inbox: Alt+Down / Alt+Up (or Cmd+] / Cmd+[) move to the next /
///   previous conversation; Cmd+F or Cmd+K jumps to the search box.
public enum Shortcut: Equatable, Sendable {
    case send
    case nextConversation
    case previousConversation
    case search
    case toggleNav
    case view(Int)
}

/// The keys the rules look at, platform-free (`Key` on Android, `KeyEquivalent` on iOS).
public enum KeyName: Equatable, Sendable {
    case enter, numPadEnter, escape, up, down, left, right, leftBracket, rightBracket
    case character(Character)

    public static func digit(_ n: Int) -> KeyName { .character(Character(String(n))) }
}

/// What a key press means for the reply box. Nil: type it as usual.
public func composerShortcut(key: KeyName, down: Bool, shift: Bool, ctrl: Bool, hardwareKeyboard: Bool) -> Shortcut? {
    if !down || (key != .enter && key != .numPadEnter) { return nil }
    if ctrl { return .send }
    if shift { return nil }
    return hardwareKeyboard ? .send : nil
}

/// What a key press means app-wide / in the inbox (never plain letters: those type).
public func appShortcut(key: KeyName, down: Bool, ctrl: Bool, alt: Bool, shift: Bool) -> Shortcut? {
    if !down || shift { return nil }
    if alt && !ctrl {
        switch key {
        case .down: return .nextConversation
        case .up: return .previousConversation
        default: return nil
        }
    }
    if !ctrl || alt { return nil }
    switch key {
    case .rightBracket: return .nextConversation
    case .leftBracket: return .previousConversation
    case .character("f"), .character("F"), .character("k"), .character("K"): return .search
    case .character("b"), .character("B"): return .toggleNav
    case .character(let c):
        if let n = Int(String(c)), (1...9).contains(n) { return .view(n - 1) }
        return nil
    default: return nil
    }
}

/// Esc on a hardware keyboard is back: close the topmost sheet, panel or
/// thread, but only while something can be closed (`somethingOpen`); at the
/// root it must never leave the app. Modified Esc (Cmd/Ctrl/Alt/Shift) is left alone.
public func escapeIsBack(key: KeyName, modified: Bool, somethingOpen: Bool) -> Bool {
    key == .escape && !modified && somethingOpen
}

/// A drag Neema can attach: images, video, audio, PDFs and office documents, not plain text or links.
public func acceptsDrop(_ mimeTypes: [String]) -> Bool {
    mimeTypes.contains { m in
        let t = m.lowercased()
        return t.hasPrefix("image/") || t.hasPrefix("video/") || t.hasPrefix("audio/")
            || t == "application/pdf" || t.hasPrefix("application/vnd.") || t == "application/msword"
            || t == "application/octet-stream"
    }
}
