import Foundation

/// The call log's avatar and details-pane rules (CallsView.tsx `avatarColor`,
/// the initials line, the tablet's details pane): pure functions the app's
/// `CallVisuals.swift` draws with, kept here so they are tested on Linux.
/// Android `feature/calls/CallVisuals.kt` (`avatarIndex`, `initialsOf`).

/// How many avatar discs `CallInk.avatars` holds (the web's six colours).
public let AVATAR_COLOURS = 6

/// The web's `avatarColor`: `[...s].reduce((a, c) => a + c.charCodeAt(0))` -
/// one term per code point, taking its FIRST UTF-16 unit (so an emoji adds
/// its high surrogate once, not both halves).
public func avatarIndex(_ s: String) -> Int {
    let src = s.isEmpty ? "?" : s
    var sum = 0
    for scalar in src.unicodeScalars {
        let utf16 = Array(String(scalar).utf16)
        sum += Int(utf16.first ?? 0)
    }
    return sum % AVATAR_COLOURS
}

/// The row's initials: who minus its first "+", first letter of the first two
/// words, upper-cased. A word starting with an emoji keeps the whole emoji.
public func initialsOf(_ who: String) -> String {
    var s = who
    if let r = s.range(of: "+") { s.removeSubrange(r) }
    let words = s.split(whereSeparator: { $0.isWhitespace }).map(String.init).filter { !$0.isEmpty }
    return words.prefix(2).map { Fmt.firstGrapheme($0) }.joined().uppercased()
}

/// The Calls view's details pane on a tablet: the newest call shown opens in it
/// when none is open or the open one was filtered away; the agent's own pick
/// stays. Shrinking to a phone-sized window drops only a call the app picked,
/// so a 1/3 split shows the log rather than a call nobody asked for.
public struct DetailsPick: Equatable {
    public let select: String?
    public let autoPicked: String?
    public init(select: String?, autoPicked: String?) { self.select = select; self.autoPicked = autoPicked }
}

public func detailsPick(wide: Bool, shownIds: [String], selected: String?, autoPicked: String?) -> DetailsPick {
    if !wide { return DetailsPick(select: selected != nil && selected == autoPicked ? nil : selected, autoPicked: nil) }
    guard let first = shownIds.first else { return DetailsPick(select: selected, autoPicked: autoPicked) }
    if selected == nil || !shownIds.contains(selected!) { return DetailsPick(select: first, autoPicked: first) }
    return DetailsPick(select: selected, autoPicked: selected == autoPicked ? autoPicked : nil)
}
