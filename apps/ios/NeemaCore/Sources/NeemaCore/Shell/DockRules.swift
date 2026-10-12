import Foundation

/// The docked call panel's width beside the view (tablets).
public let CALL_PANEL_WIDTH: CGFloat = 420

/// Whether the call card docks beside the view (a view `contentWidth` wide
/// with room for it and a usable view: a big iPad on its side) rather than
/// covering it. A minimised call is the top bar, whatever the width.
public func callDocks(phase: CallPhase, minimised: Bool, contentWidth: CGFloat) -> Bool {
    phase != .idle && !minimised && contentWidth >= 1000
}
