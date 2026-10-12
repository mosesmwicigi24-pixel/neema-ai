import Foundation

/// A pipeline column (LeadsView STAGES, plus the operator's own).
public struct LeadStage: Equatable, Sendable, Identifiable {
    public let id: String
    public let label: String
    /// An operator-added stage (drawn in the custom colour).
    public let custom: Bool
    public init(_ id: String, _ label: String, custom: Bool = false) { self.id = id; self.label = label; self.custom = custom }

    /// The server lower-cases stages on read (normalise_stage); match the same way.
    public func matches(_ stage: String?) -> Bool {
        id.caseInsensitiveCompare((stage ?? "").trimmingCharacters(in: .whitespacesAndNewlines)) == .orderedSame
    }
}

/// A detail-sheet save: only the fields that changed are set (nil = untouched).
public struct LeadEdit: Equatable, Sendable {
    public var stage: String?
    public var tags: [String]?
    public var notes: String?
    /// The notes text the edit started from — the server's three-way merge base.
    public var notesBase: String
    public init(stage: String? = nil, tags: [String]? = nil, notes: String? = nil, notesBase: String = "") {
        self.stage = stage; self.tags = tags; self.notes = notes; self.notesBase = notesBase
    }
    public var isEmpty: Bool { stage == nil && tags == nil && notes == nil }
}

/// The detail sheet's fields as typed, and the lead as the sheet opened (what
/// "changed" means, and the base of the server's notes merge). Held by the
/// model, so a trip to another view or the app being reclaimed never loses a
/// half-typed note; a swipe that closes the sheet keeps it too, while Cancel
/// and the close button throw it away as the web does.
public struct LeadSheetDraft: Equatable, Sendable {
    public var leadId: String
    public var stage: String
    public var tags: String
    public var notes: String
    public var baseStage: String?
    public var baseTags: [String]
    public var baseNotes: String
    public init(leadId: String, stage: String, tags: String, notes: String, baseStage: String?, baseTags: [String], baseNotes: String) {
        self.leadId = leadId; self.stage = stage; self.tags = tags; self.notes = notes
        self.baseStage = baseStage; self.baseTags = baseTags; self.baseNotes = baseNotes
    }

    public func edit() -> LeadEdit { LeadsRules.diff(baseStage: baseStage, baseTags: baseTags, baseNotes: baseNotes, stage: stage, tagsText: tags, notes: notes) }

    public static func of(_ lead: Lead, _ stages: [LeadStage]) -> LeadSheetDraft {
        LeadSheetDraft(leadId: lead.id, stage: stages.first { $0.matches(lead.leadStage) }?.id ?? lead.leadStage,
                       tags: lead.tags.joined(separator: ", "), notes: lead.notes ?? "",
                       baseStage: lead.leadStage, baseTags: lead.tags, baseNotes: lead.notes ?? "")
    }
}

/// The kanban as the screen draws it: every figure from one pass over the leads.
public struct LeadBoard: Equatable, Sendable {
    /// Leads per stage id, unfiltered (the stage pills' counts).
    public let counts: [String: Int]
    /// The filtered leads per stage id, in the server's (score) order.
    public let columns: [String: [Lead]]
    /// `total_spent` over each column's filtered leads (the column header's money).
    public let columnValue: [String: Double]
    /// The header's "Pipeline": everything neither won nor lost.
    public let pipelineValue: Double
    /// The header's "Won".
    public let wonValue: Double
    public init(counts: [String: Int], columns: [String: [Lead]], columnValue: [String: Double], pipelineValue: Double, wonValue: Double) {
        self.counts = counts; self.columns = columns; self.columnValue = columnValue; self.pipelineValue = pipelineValue; self.wonValue = wonValue
    }
}

/// The pure rules of components/views/LeadsView.tsx (Android `LeadsViewModel.kt`).
public enum LeadsRules {
    /// The canonical columns.
    public static let BASE_STAGES: [LeadStage] = [
        LeadStage("new", "New"), LeadStage("contacted", "Contacted"), LeadStage("qualified", "Qualified"),
        LeadStage("proposal", "Proposal"), LeadStage("negotiation", "Negotiating"), LeadStage("won", "Won"), LeadStage("lost", "Lost"),
    ]

    /// Canonical columns plus the operator-added stages, which sit between Negotiating and Won.
    public static func buildStages(_ customs: [String]) -> [LeadStage] {
        var seen = Set<String>()
        let defs = customs.filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
            .filter { seen.insert($0).inserted }
            .filter { c in !BASE_STAGES.contains { $0.id == c } }
            .map { LeadStage($0, $0, custom: true) }
        let won = BASE_STAGES.firstIndex { $0.id == "won" }!
        return Array(BASE_STAGES[..<won]) + defs + Array(BASE_STAGES[won...])
    }

    /// LeadsView's `filteredLeads`: the stage filter, then name / handle / email / location.
    public static func filterLeads(_ leads: [Lead], filterStage: String, search: String) -> [Lead] {
        let q = search.lowercased()
        return leads.filter { l in
            if filterStage != "all" && filterStage.caseInsensitiveCompare(l.leadStage) != .orderedSame { return false }
            if q.isEmpty { return true }
            return (l.name ?? "").lowercased().contains(q) || l.handle.contains(q) ||
                (l.email ?? "").lowercased().contains(q) || (l.location ?? "").lowercased().contains(q)
        }
    }

    /// What changed between `base` (the lead as the sheet opened) and the sheet's
    /// fields. The web PATCHes all three every time, which re-locks an untouched
    /// AI-set stage as "manual" and clobbers notes appended meanwhile; only real
    /// changes are sent here, and notes carry their base for the server's merge.
    public static func diffLead(_ base: Lead, stage: String, tagsText: String, notes: String) -> LeadEdit {
        diff(baseStage: base.leadStage, baseTags: base.tags, baseNotes: base.notes ?? "", stage: stage, tagsText: tagsText, notes: notes)
    }

    static func diff(baseStage: String?, baseTags: [String], baseNotes: String, stage: String, tagsText: String, notes: String) -> LeadEdit {
        let tags = Leads.parseTags(tagsText)
        return LeadEdit(
            stage: stage.caseInsensitiveCompare(baseStage ?? "") == .orderedSame ? nil : stage,
            tags: tags == baseTags ? nil : tags,
            notes: notes == baseNotes ? nil : notes,
            notesBase: baseNotes
        )
    }

    /// Paragraphs as crm.py `merge_notes` splits them.
    static func paras(_ s: String?) -> [String] {
        (s ?? "").components(separatedBy: "\n\n").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }

    /// Whether `edit` is what the server now holds for `stored` — used when a
    /// save's answer was lost. Notes are merged server-side (the operator's
    /// paragraphs plus any appended meanwhile), so they landed when every typed
    /// paragraph is there.
    public static func editLanded(_ edit: LeadEdit, _ stored: Lead) -> Bool {
        if let s = edit.stage, s.caseInsensitiveCompare(stored.leadStage) != .orderedSame { return false }
        if let t = edit.tags, t != stored.tags { return false }
        if let n = edit.notes {
            let mine = paras(n)
            let now = paras(stored.notes)
            if !mine.allSatisfy({ now.contains($0) }) { return false }
            // Paragraphs deleted on purpose must be gone too.
            if paras(edit.notesBase).contains(where: { !mine.contains($0) && now.contains($0) }) { return false }
        }
        return true
    }

    /// A fresh read of the board, except the leads in `keepLocal` (changed here
    /// after the read began, or mid-save): they keep the row on screen — or stay
    /// gone, when this phone saw them deleted. One pass, whatever the board's size.
    public static func overlayLocal(_ server: [Lead], onScreen: [Lead], keepLocal: Set<String>) -> [Lead] {
        if keepLocal.isEmpty { return server }
        var local: [String: Lead] = [:]
        for l in onScreen where keepLocal.contains(l.id) { local[l.id] = l }
        return server.compactMap { l in keepLocal.contains(l.id) ? local[l.id] : l }
    }

    static func stageKey(_ s: String?) -> String { (s ?? "").trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }

    /// LeadsView's per-render work — `leads.filter(stage)` once per column and once
    /// per pill, the pipeline and won sums — done once per change of the board:
    /// O(leads + stages) instead of O(leads × stages). A lead matches a column
    /// as `LeadStage.matches` does (trimmed, any case).
    public static func buildBoard(_ leads: [Lead], filtered: [Lead], stages: [LeadStage]) -> LeadBoard {
        var count: [String: Int] = [:]
        var pipeline = 0.0
        var won = 0.0
        for l in leads {
            count[stageKey(l.leadStage), default: 0] += 1
            let raw = l.leadStage.lowercased()
            if raw != "lost" && raw != "won" { pipeline += l.totalSpent }
            if l.leadStage.caseInsensitiveCompare("won") == .orderedSame { won += l.totalSpent }
        }
        var byStage: [String: [Lead]] = [:]
        for l in filtered { byStage[stageKey(l.leadStage), default: []].append(l) }
        var columns: [String: [Lead]] = [:]
        var counts: [String: Int] = [:]
        var value: [String: Double] = [:]
        for s in stages {
            let col = byStage[stageKey(s.id)] ?? []
            columns[s.id] = col
            counts[s.id] = count[stageKey(s.id)] ?? 0
            value[s.id] = col.reduce(0) { $0 + $1.totalSpent }
        }
        return LeadBoard(counts: counts, columns: columns, columnValue: value, pipelineValue: pipeline, wonValue: won)
    }
}
