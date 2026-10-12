import Foundation

/// A board column.
public struct DealStage: Equatable, Sendable {
    public let id: String
    public let label: String
    public init(_ id: String, _ label: String) { self.id = id; self.label = label }
}

/// One board column with its deals.
public struct DealColumn: Equatable, Sendable, Identifiable {
    public let stage: DealStage
    public let deals: [Deal]
    public var id: String { stage.id }
    public init(stage: DealStage, deals: [Deal]) { self.stage = stage; self.deals = deals }
}

/// The pure rules of components/views/DealsView.tsx (Android `DealsScreen.kt`).
public enum DealsRules {
    /// The board's columns. A deal in any other stage is shown under New.
    public static let STAGES = [DealStage("new", "New"), DealStage("qualified", "Qualified"), DealStage("proposal", "Proposal")]

    /// The open deals by board column ("new" / "qualified" / "proposal"), in their
    /// order, in one pass: a deal in any other stage lands under New. Every column
    /// is present, empty or not.
    public static func groupByStage(_ open: [Deal]) -> [String: [Deal]] {
        var out: [String: [Deal]] = [:]
        for s in STAGES { out[s.id] = [] }
        for d in open { out[out[d.stage] != nil ? d.stage : "new", default: []].append(d) }
        return out
    }

    /// The columns in board order, each with its deals.
    public static func columns(_ open: [Deal]) -> [DealColumn] {
        let g = groupByStage(open)
        return STAGES.map { DealColumn(stage: $0, deals: g[$0.id] ?? []) }
    }

    /// "due now" / "in 12m" / "in 5h" / "in 3d".
    public static func fmtDue(_ iso: String?, now: Int64 = AppClock.now()) -> String {
        guard let iso = iso, !iso.trimmingCharacters(in: .whitespaces).isEmpty, let t = Fmt.millis(iso) else { return "" }
        let d = t - now
        if d <= 0 { return "due now" }
        let h = d / 3_600_000
        if h < 1 { return "in \(max(1, d / 60_000))m" }
        if h < 48 { return "in \(h)h" }
        return "in \(h / 24)d"
    }

    /// The thread a deal opens: its wa_id, else its conversation id.
    public static func threadKey(_ d: Deal) -> String? {
        if let w = d.waId, !w.trimmingCharacters(in: .whitespaces).isEmpty { return w }
        return d.conversationId
    }

    /// The queue row's lead: who owes the next move, and when.
    public static func rowLead(_ a: PlannedAction, now: Int64 = AppClock.now()) -> String {
        a.status == "needs_approval" ? "⏳ Needs your approval" : "🕐 \(fmtDue(a.dueAt, now: now))"
    }
}
