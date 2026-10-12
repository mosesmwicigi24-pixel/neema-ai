import Foundation

/// Large-screen layout rules, decided from the space a view really has (the
/// window, or the content beside the navigation) — never from the screen
/// (Android `core/ui/Adaptive.kt`): an iPad Pro 13" is 1032 × 1376 pt, but
/// in Split View the app gets a third or a half, and a Slide Over window is
/// narrower still. Pure functions, unit-tested at each of those sizes.
public enum Adaptive {
    /// A thread never narrower than this beside other panes (~60 characters a line).
    public static let THREAD_MIN = 480
    /// Below this content width the inbox is one pane at a time (list, then thread): the 320 pt list plus a `THREAD_MIN` thread need 801.
    public static let TWO_PANE_MIN = 801
    /// The docked sidebar only from here: narrower windows get the icon rail.
    public static let DOCKED_NAV_MIN = 1200
}

/// How the shell shows navigation in a window `windowWidth` points wide.
public enum NavMode: Equatable, Sendable { case drawer, rail, docked }

public func navMode(for windowWidth: Int) -> NavMode {
    if windowWidth < 600 { return .drawer }
    if windowWidth < Adaptive.DOCKED_NAV_MIN { return .rail }
    return .docked
}

/// A side pane: beside the main one, or sliding over it on demand.
public enum SideMode: Equatable, Sendable { case docked, overlay }

/// The inbox's panes for a content area `contentWidth` points wide (the window minus the navigation).
public struct InboxPanes: Equatable, Sendable {
    public let twoPane: Bool
    public let listWidth: Int
    public let customer: SideMode
    public let customerWidth: Int
    /// The activity log's collapsed rail sits beside the thread.
    public let activityRail: Bool
    /// Opening the activity log docks it at `activityWidth` (else it slides over).
    public let activityDocks: Bool
    public let activityWidth: Int
    /// The thread's width with every docked pane closed but the customer panel.
    public let threadWidth: Int

    public init(twoPane: Bool, listWidth: Int, customer: SideMode, customerWidth: Int, activityRail: Bool, activityDocks: Bool, activityWidth: Int, threadWidth: Int) {
        self.twoPane = twoPane; self.listWidth = listWidth; self.customer = customer; self.customerWidth = customerWidth
        self.activityRail = activityRail; self.activityDocks = activityDocks; self.activityWidth = activityWidth; self.threadWidth = threadWidth
    }

    /// The thread is roomy enough for its actions on one line beside the badges.
    public var roomyThread: Bool { threadWidth >= 540 }
}

/// - One pane below `Adaptive.TWO_PANE_MIN` (a third of a split, a Slide Over window, a phone).
/// - The list takes ~30%, 300–400 pt.
/// - The customer panel docks beside the thread only when the thread keeps `THREAD_MIN` (plus the activity rail);
///   otherwise it slides over the thread from the end edge when asked for.
/// - The activity log opens beside the thread only when the thread would still keep `THREAD_MIN`; otherwise it slides over too.
public func inboxPanes(contentWidth: Int) -> InboxPanes {
    let w = max(0, contentWidth)
    let sheet = min(400, Int(Float(w) * 0.9))
    if w < Adaptive.TWO_PANE_MIN {
        return InboxPanes(twoPane: false, listWidth: w, customer: .overlay, customerWidth: sheet, activityRail: false, activityDocks: false, activityWidth: sheet, threadWidth: w)
    }
    let list = min(400, max(320, Int(Float(w) * 0.30)))
    let afterList = w - list - 1
    let customerW = min(360, max(300, Int(Float(w) * 0.26)))
    let rail = 32
    let docked = afterList - customerW - 1 - rail >= Adaptive.THREAD_MIN
    let thread = docked ? afterList - customerW - 1 - rail : afterList
    let activityW = min(292, max(196, Int(Float(w) * 0.16)))
    let activityDocks = docked && thread - activityW >= Adaptive.THREAD_MIN
    return InboxPanes(
        twoPane: true, listWidth: list,
        customer: docked ? .docked : .overlay,
        customerWidth: docked ? customerW : min(400, Int(Float(afterList) * 0.8)),
        activityRail: docked, activityDocks: activityDocks, activityWidth: activityW,
        threadWidth: thread
    )
}

/// Tabs that share a row: each gets at least its own label's width, and the
/// spare room is shared out so they fill `room` — equal widths when every
/// label fits an equal share, else content widths plus an equal share of the
/// slack. Only when the labels truly don't fit does the row run wider.
public func fitWidths(_ natural: [Int], room: Int) -> [Int] {
    if natural.isEmpty { return natural }
    let total = natural.reduce(0, +)
    if total >= room { return natural }
    let even = room / natural.count
    if natural.allSatisfy({ $0 <= even }) { return natural.map { _ in even } }
    let extra = (room - total) / natural.count
    return natural.map { $0 + extra }
}

/// Alt+↓ / Alt+↑ through a list: the next (or previous) id, clamped to the ends; none selected → the first (or last).
public func stepThrough(_ ids: [String], current: String?, forward: Bool) -> String? {
    if ids.isEmpty { return nil }
    guard let c = current, let i = ids.firstIndex(of: c) else { return forward ? ids.first : ids.last }
    let j = min(max(forward ? i + 1 : i - 1, 0), ids.count - 1)
    return ids[j]
}
