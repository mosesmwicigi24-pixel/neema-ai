import Foundation

/// crm.py `_buying_rhythm` — how often this customer buys and whether they're overdue (the leads row's shape).
public struct BuyingRhythm: Equatable, Hashable, Sendable, Decodable {
    public var daysSinceLast: Double?, avgIntervalDays: Double?, cadenceLabel: String?, overdue: Bool
    public init(daysSinceLast: Double? = nil, avgIntervalDays: Double? = nil, cadenceLabel: String? = nil, overdue: Bool = false) {
        self.daysSinceLast = daysSinceLast; self.avgIntervalDays = avgIntervalDays; self.cadenceLabel = cadenceLabel; self.overdue = overdue
    }
    enum K: String, CodingKey { case days_since_last, avg_interval_days, cadence_label, overdue }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(daysSinceLast: c.double(.days_since_last), avgIntervalDays: c.double(.avg_interval_days), cadenceLabel: c.string(.cadence_label), overdue: c.bool(.overdue, default: false))
    }
}

/// One row of GET /admin/leads (crm.py `list_leads`). `id` is the internal User id — the PATCH key.
public struct Lead: Identifiable, Equatable, Hashable, Sendable, Decodable {
    public let id: String
    public var waId: String?
    public var name: String?
    public var phone: String?
    public var email: String?
    public var location: String?
    public var leadStage: String
    /// 0–100: an int from the server; read as a Double so a float never fails the row.
    public var leadScoreRaw: Double
    public var tier: String?
    public var tierLabel: String?
    public var tags: [String]
    public var channels: [String]
    public var totalOrders: Int
    public var totalSpent: Double
    public var buyingRhythm: BuyingRhythm?
    public var lastSeenAt: String?
    public var notes: String?

    public init(id: String, waId: String? = nil, name: String? = nil, phone: String? = nil, email: String? = nil, location: String? = nil,
                leadStage: String = "new", leadScoreRaw: Double = 0, tier: String? = nil, tierLabel: String? = nil, tags: [String] = [],
                channels: [String] = [], totalOrders: Int = 0, totalSpent: Double = 0, buyingRhythm: BuyingRhythm? = nil, lastSeenAt: String? = nil, notes: String? = nil) {
        self.id = id; self.waId = waId; self.name = name; self.phone = phone; self.email = email; self.location = location
        self.leadStage = leadStage; self.leadScoreRaw = leadScoreRaw; self.tier = tier; self.tierLabel = tierLabel; self.tags = tags
        self.channels = channels; self.totalOrders = totalOrders; self.totalSpent = totalSpent; self.buyingRhythm = buyingRhythm; self.lastSeenAt = lastSeenAt; self.notes = notes
    }

    enum K: String, CodingKey {
        case id, wa_id, name, phone, email, location, lead_stage, lead_score, tier, tier_label, tags, channels, total_orders, total_spent, buying_rhythm, last_seen_at, notes
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), waId: c.string(.wa_id), name: c.string(.name), phone: c.string(.phone), email: c.string(.email),
                  location: c.string(.location), leadStage: c.string(.lead_stage, default: "new"), leadScoreRaw: c.double(.lead_score, default: 0),
                  tier: c.string(.tier), tierLabel: c.string(.tier_label), tags: Leads.lenientTags(c.value(.tags)), channels: c.stringList(.channels),
                  totalOrders: c.int(.total_orders, default: 0), totalSpent: c.double(.total_spent, default: 0), buyingRhythm: c.object(.buying_rhythm),
                  lastSeenAt: c.string(.last_seen_at), notes: c.string(.notes))
    }

    public var leadScore: Int { max(0, min(100, Int(leadScoreRaw))) }

    /// The handle shown and searched — wa_id, else the phone, else the id.
    public var handle: String {
        if let w = waId, !w.trimmingCharacters(in: .whitespaces).isEmpty { return w }
        if let p = phone, !p.trimmingCharacters(in: .whitespaces).isEmpty { return p }
        return id
    }
}

public enum Leads {
    /// A comma-separated tags field: split, trimmed, blanks dropped.
    public static func parseTags(_ text: String) -> [String] {
        text.split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }

    /// `tags` straight from `users.state["tags"]`: a list, a lone string (comma-separated), null, or a list with a stray number.
    public static func lenientTags(_ v: JSONValue?) -> [String] {
        guard let v = v else { return [] }
        switch v {
        case .array(let items):
            return items.compactMap { item -> String? in
                switch item {
                case .null, .array, .object: return nil
                default:
                    let t = (item.content ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    return t.isEmpty ? nil : t
                }
            }
        case .null: return []
        case .string(let s): return parseTags(s)
        case .number, .bool: return parseTags(v.content ?? "")
        case .object: return []
        }
    }

    /// lead_signals.py `normalise_stage`.
    public static func normaliseStage(_ s: String?) -> String {
        let raw = (s ?? "").isEmpty ? "new" : s!
        let t = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return t == "negotiating" ? "negotiation" : t
    }
}

/// The leads routes the web reaches with bare fetch() (outside api.ts).
public final class LeadsApi {
    public let http: NeemaHTTP
    public init(http: NeemaHTTP) { self.http = http }

    /// GET /admin/leads — a bare array, score-descending; `stage` is sent normalised.
    public func list(stage: String? = nil) async throws -> [Lead] {
        let qs = stage.map { "?stage=\(HTTPBody.formEncodeComponent(Leads.normaliseStage($0)))" } ?? ""
        return try await http.get("/admin/leads\(qs)")
    }

    /// PATCH /admin/leads/{id} — any of `lead_stage`, `tags`, `notes` (+ `notes_base`).
    public func update(id: String, body: JSONValue) async throws -> OkResponse {
        try await http.patch("/admin/leads/\(HTTPBody.formEncodeComponent(id))", body)
    }
}
