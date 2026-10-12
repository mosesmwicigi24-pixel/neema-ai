import Foundation

// Wire models for the CRM panel (routers/crm.py `_build_profile`, the merge
// endpoints and the production-enquiry routes) — Android `CustomerModels.kt`.

public struct CustomerChannel: Equatable, Hashable, Sendable, Decodable {
    public var channel: String
    /// The conversation's wa_id — nil for Messenger/IG/FB threads.
    public var identifier: String?
    public var firstSeen: String?
    public var lastSeen: String?
    public var conversationCount: Int
    public init(channel: String = "whatsapp", identifier: String? = nil, firstSeen: String? = nil, lastSeen: String? = nil, conversationCount: Int = 0) {
        self.channel = channel; self.identifier = identifier; self.firstSeen = firstSeen; self.lastSeen = lastSeen; self.conversationCount = conversationCount
    }
    enum K: String, CodingKey { case channel, identifier, first_seen, last_seen, conversation_count }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(channel: c.string(.channel, default: "whatsapp"), identifier: c.string(.identifier), firstSeen: c.string(.first_seen),
                  lastSeen: c.string(.last_seen), conversationCount: c.int(.conversation_count, default: 0))
    }
}

/// An order line: hub lines carry name / qty / quantity / unit_price / total; a local cart line has no `total`. Numbers may be strings.
public struct PanelOrderItem: Equatable, Hashable, Sendable, Decodable {
    public var name: String
    public var qty: Double?
    public var quantity: Double?
    public var total: Double?
    public init(name: String = "", qty: Double? = nil, quantity: Double? = nil, total: Double? = nil) {
        self.name = name; self.qty = qty; self.quantity = quantity; self.total = total
    }
    enum K: String, CodingKey { case name, qty, quantity, total }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(name: c.string(.name, default: ""), qty: Self.num(c.value(.qty)), quantity: Self.num(c.value(.quantity)), total: Self.num(c.value(.total)))
    }
    /// A hub number as the hub sent it: a JSON number or a numeric string; anything else reads as nil.
    static func num(_ v: JSONValue?) -> Double? {
        guard let v = v else { return nil }
        switch v {
        case .number(let d): return d
        case .string(let s): return Double(s.trimmingCharacters(in: .whitespaces))
        default: return nil
        }
    }
}

/// An order as the panel renders it: hub-sourced or a local WhatsApp order_event.
public struct PanelOrder: Equatable, Hashable, Sendable, Decodable, Identifiable {
    public var id: String
    public var orderNumber: String?
    public var status: String?
    public var paymentStatus: String?
    public var total: Double?
    public var subtotal: Double?
    public var currencyCode: String?
    public var createdAt: String?
    public var items: [PanelOrderItem]
    /// "hub" | "whatsapp"
    public var source: String?

    public init(id: String = "", orderNumber: String? = nil, status: String? = nil, paymentStatus: String? = nil, total: Double? = nil, subtotal: Double? = nil,
                currencyCode: String? = nil, createdAt: String? = nil, items: [PanelOrderItem] = [], source: String? = nil) {
        self.id = id; self.orderNumber = orderNumber; self.status = status; self.paymentStatus = paymentStatus; self.total = total
        self.subtotal = subtotal; self.currencyCode = currencyCode; self.createdAt = createdAt; self.items = items; self.source = source
    }

    enum K: String, CodingKey { case id, order_number, status, payment_status, total, subtotal, currency_code, created_at, items, source }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), orderNumber: c.string(.order_number), status: c.string(.status), paymentStatus: c.string(.payment_status),
                  total: c.double(.total), subtotal: c.double(.subtotal), currencyCode: c.string(.currency_code), createdAt: c.string(.created_at),
                  items: c.list(.items), source: c.string(.source))
    }

    /// `o.total || o.subtotal` — the web treats 0 as missing.
    public var amount: Double { (total ?? 0) != 0 ? total! : (subtotal ?? 0) }
    /// A hub order's `created_at` is the hub's own string — normalised for parsing.
    public var createdIso: String? { Crm.isoOf(createdAt) }
    /// The currency this order's amount is in: the hub's code for hub rows, else KES.
    public var displayCurrency: String {
        let code = (currencyCode ?? "").trimmingCharacters(in: .whitespaces).uppercased()
        return source == "hub" && code.count == 3 ? code : "KES"
    }
}

public struct AdRef: Equatable, Hashable, Sendable, Decodable {
    public var headline: String?, adId: String?, sourceType: String?, sourceId: String?, sourceUrl: String?, source: String?
    public init(headline: String? = nil, adId: String? = nil, sourceType: String? = nil, sourceId: String? = nil, sourceUrl: String? = nil, source: String? = nil) {
        self.headline = headline; self.adId = adId; self.sourceType = sourceType; self.sourceId = sourceId; self.sourceUrl = sourceUrl; self.source = source
    }
    enum K: String, CodingKey { case headline, ad_id, source_type, source_id, source_url, source }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(headline: c.string(.headline), adId: c.string(.ad_id), sourceType: c.string(.source_type), sourceId: c.string(.source_id), sourceUrl: c.string(.source_url), source: c.string(.source))
    }
}

public struct ScorePart: Equatable, Hashable, Sendable, Decodable {
    public var label: String, pts: Double, max: Double
    public init(label: String = "", pts: Double = 0, max: Double = 0) { self.label = label; self.pts = pts; self.max = max }
    enum K: String, CodingKey { case label, pts, max }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(label: c.string(.label, default: ""), pts: c.double(.pts, default: 0), max: c.double(.max, default: 0))
    }
}

/// crm.py `_buying_rhythm` as the profile carries it (days_since_last is an int here).
public struct CustomerBuyingRhythm: Equatable, Hashable, Sendable, Decodable {
    public var daysSinceLast: Int?, avgIntervalDays: Double?, cadenceLabel: String?, overdue: Bool
    public init(daysSinceLast: Int? = nil, avgIntervalDays: Double? = nil, cadenceLabel: String? = nil, overdue: Bool = false) {
        self.daysSinceLast = daysSinceLast; self.avgIntervalDays = avgIntervalDays; self.cadenceLabel = cadenceLabel; self.overdue = overdue
    }
    enum K: String, CodingKey { case days_since_last, avg_interval_days, cadence_label, overdue }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(daysSinceLast: c.int(.days_since_last), avgIntervalDays: c.double(.avg_interval_days), cadenceLabel: c.string(.cadence_label), overdue: c.bool(.overdue, default: false))
    }
}

public struct Parish: Equatable, Hashable, Sendable, Decodable {
    public var id: String, name: String?, location: String?
    public init(id: String = "", name: String? = nil, location: String? = nil) { self.id = id; self.name = name; self.location = location }
    enum K: String, CodingKey { case id, name, location }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), name: c.string(.name), location: c.string(.location))
    }
}

public struct LinkedIdentity: Equatable, Hashable, Sendable, Decodable {
    public var channel: String, externalId: String, displayName: String?, source: String?, confidence: String?
    public init(channel: String = "", externalId: String = "", displayName: String? = nil, source: String? = nil, confidence: String? = nil) {
        self.channel = channel; self.externalId = externalId; self.displayName = displayName; self.source = source; self.confidence = confidence
    }
    enum K: String, CodingKey { case channel, external_id, display_name, source, confidence }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(channel: c.string(.channel, default: ""), externalId: c.string(.external_id, default: ""), displayName: c.string(.display_name), source: c.string(.source), confidence: c.string(.confidence))
    }
}

/// GET /admin/customers/{id}?channel= — the full CRM profile.
public struct CustomerProfile: Equatable, Hashable, Sendable, Decodable {
    public var id: String
    public var waId: String?
    public var name: String?
    public var nameConfirmed: Bool
    public var email: String?
    public var phone: String?
    public var location: String?
    public var age: Int?
    public var tags: [String]
    public var leadStage: String
    /// "auto" | "manual"
    public var leadStageSource: String?
    public var suggestedLeadStage: String?
    public var leadSource: String?
    public var adRef: AdRef?
    public var role: String?
    public var organization: String?
    public var orders: [PanelOrder]?
    public var ordersSource: String?
    public var hubLinked: Bool
    public var hubCustomerId: JSONValue?
    public var hubCustomerName: String?
    public var leadScore: Double
    public var phoneVerified: Bool
    public var cartItems: Int
    public var leadScoreBreakdown: [ScorePart]
    public var parish: Parish?
    public var channels: [CustomerChannel]
    public var mergedIds: [String]
    public var personId: String?
    public var linkedIdentities: [LinkedIdentity]
    public var totalOrders: Int
    public var totalSpent: Double
    public var avgOrderValue: Double?
    /// prospect | new | regular | loyal | vip | at_risk
    public var tier: String?
    public var tierLabel: String?
    public var buyingRhythm: CustomerBuyingRhythm?
    public var lastOrderAt: String?
    public var lastSeenAt: String?
    public var firstSeenAt: String?
    public var notes: String?
    public var createdAt: String?
    public var countryIso: String?
    public var country: String?
    public var flagUrl: String?

    public init(id: String = "", waId: String? = nil, name: String? = nil, nameConfirmed: Bool = false, email: String? = nil, phone: String? = nil,
                location: String? = nil, age: Int? = nil, tags: [String] = [], leadStage: String = "new", leadStageSource: String? = nil,
                suggestedLeadStage: String? = nil, leadSource: String? = nil, adRef: AdRef? = nil, role: String? = nil, organization: String? = nil,
                orders: [PanelOrder]? = nil, ordersSource: String? = nil, hubLinked: Bool = false, hubCustomerId: JSONValue? = nil,
                hubCustomerName: String? = nil, leadScore: Double = 0, phoneVerified: Bool = false, cartItems: Int = 0,
                leadScoreBreakdown: [ScorePart] = [], parish: Parish? = nil, channels: [CustomerChannel] = [], mergedIds: [String] = [],
                personId: String? = nil, linkedIdentities: [LinkedIdentity] = [], totalOrders: Int = 0, totalSpent: Double = 0,
                avgOrderValue: Double? = nil, tier: String? = nil, tierLabel: String? = nil, buyingRhythm: CustomerBuyingRhythm? = nil,
                lastOrderAt: String? = nil, lastSeenAt: String? = nil, firstSeenAt: String? = nil, notes: String? = nil, createdAt: String? = nil,
                countryIso: String? = nil, country: String? = nil, flagUrl: String? = nil) {
        self.id = id; self.waId = waId; self.name = name; self.nameConfirmed = nameConfirmed; self.email = email; self.phone = phone
        self.location = location; self.age = age; self.tags = tags; self.leadStage = leadStage; self.leadStageSource = leadStageSource
        self.suggestedLeadStage = suggestedLeadStage; self.leadSource = leadSource; self.adRef = adRef; self.role = role; self.organization = organization
        self.orders = orders; self.ordersSource = ordersSource; self.hubLinked = hubLinked; self.hubCustomerId = hubCustomerId
        self.hubCustomerName = hubCustomerName; self.leadScore = leadScore; self.phoneVerified = phoneVerified; self.cartItems = cartItems
        self.leadScoreBreakdown = leadScoreBreakdown; self.parish = parish; self.channels = channels; self.mergedIds = mergedIds
        self.personId = personId; self.linkedIdentities = linkedIdentities; self.totalOrders = totalOrders; self.totalSpent = totalSpent
        self.avgOrderValue = avgOrderValue; self.tier = tier; self.tierLabel = tierLabel; self.buyingRhythm = buyingRhythm
        self.lastOrderAt = lastOrderAt; self.lastSeenAt = lastSeenAt; self.firstSeenAt = firstSeenAt; self.notes = notes; self.createdAt = createdAt
        self.countryIso = countryIso; self.country = country; self.flagUrl = flagUrl
    }

    enum K: String, CodingKey {
        case id, wa_id, name, name_confirmed, email, phone, location, age, tags, lead_stage, lead_stage_source, suggested_lead_stage, lead_source
        case ad_ref, role, organization, orders, orders_source, hub_linked, hub_customer_id, hub_customer_name, lead_score, phone_verified, cart_items
        case lead_score_breakdown, parish, channels, merged_ids, person_id, linked_identities, total_orders, total_spent, avg_order_value
        case tier, tier_label, buying_rhythm, last_order_at, last_seen_at, first_seen_at, notes, created_at, country_iso, country, flag_url
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        let orders: [PanelOrder]? = c.value(.orders).map { _ in c.list(.orders) }
        self.init(
            id: c.string(.id, default: ""), waId: c.string(.wa_id), name: c.string(.name), nameConfirmed: c.bool(.name_confirmed, default: false),
            email: c.string(.email), phone: c.string(.phone), location: c.string(.location), age: c.int(.age), tags: c.stringList(.tags),
            leadStage: c.string(.lead_stage, default: "new"), leadStageSource: c.string(.lead_stage_source), suggestedLeadStage: c.string(.suggested_lead_stage),
            leadSource: c.string(.lead_source), adRef: c.object(.ad_ref), role: c.string(.role), organization: c.string(.organization),
            orders: orders, ordersSource: c.string(.orders_source), hubLinked: c.bool(.hub_linked, default: false), hubCustomerId: c.value(.hub_customer_id),
            hubCustomerName: c.string(.hub_customer_name), leadScore: c.double(.lead_score, default: 0), phoneVerified: c.bool(.phone_verified, default: false),
            cartItems: c.int(.cart_items, default: 0), leadScoreBreakdown: c.list(.lead_score_breakdown), parish: c.object(.parish), channels: c.list(.channels),
            mergedIds: c.stringList(.merged_ids), personId: c.string(.person_id), linkedIdentities: c.list(.linked_identities),
            totalOrders: c.int(.total_orders, default: 0), totalSpent: c.double(.total_spent, default: 0), avgOrderValue: c.double(.avg_order_value),
            tier: c.string(.tier), tierLabel: c.string(.tier_label), buyingRhythm: c.object(.buying_rhythm), lastOrderAt: c.string(.last_order_at),
            lastSeenAt: c.string(.last_seen_at), firstSeenAt: c.string(.first_seen_at), notes: c.string(.notes), createdAt: c.string(.created_at),
            countryIso: c.string(.country_iso), country: c.string(.country), flagUrl: c.string(.flag_url)
        )
    }
}

public struct MergeSuggestion: Equatable, Hashable, Sendable, Decodable {
    public var mergeWith: String, name: String?, phone: String?, country: String?, channelHint: String?, evidence: [String]
    /// "strong" | "possible"
    public var strength: String
    public init(mergeWith: String = "", name: String? = nil, phone: String? = nil, country: String? = nil, channelHint: String? = nil, evidence: [String] = [], strength: String = "possible") {
        self.mergeWith = mergeWith; self.name = name; self.phone = phone; self.country = country; self.channelHint = channelHint; self.evidence = evidence; self.strength = strength
    }
    enum K: String, CodingKey { case merge_with, name, phone, country, channel_hint, evidence, strength }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(mergeWith: c.string(.merge_with, default: ""), name: c.string(.name), phone: c.string(.phone), country: c.string(.country),
                  channelHint: c.string(.channel_hint), evidence: c.stringList(.evidence), strength: c.string(.strength, default: "possible"))
    }
}

public struct MergeSuggestionsResponse: Equatable, Sendable, Decodable {
    public var suggestions: [MergeSuggestion]
    public init(suggestions: [MergeSuggestion] = []) { self.suggestions = suggestions }
    enum K: String, CodingKey { case suggestions }
    public init(from decoder: Decoder) throws { self.init(suggestions: (try decoder.lenient(K.self)).list(.suggestions)) }
}

/// A made-to-order request (measurement form) waiting to go to hub production.
public struct ProductionEnquiry: Equatable, Hashable, Sendable, Decodable {
    public var id: String
    public var productName: String?
    /// Values are whatever the form captured — usually strings, sometimes numbers.
    public var measurements: [String: JSONValue]
    public var notes: String?
    public var location: String?
    /// "new" | "pushed" | "declined"
    public var status: String
    public var hubOrderNumber: String?
    public var pushable: Bool
    public init(id: String = "", productName: String? = nil, measurements: [String: JSONValue] = [:], notes: String? = nil, location: String? = nil,
                status: String = "new", hubOrderNumber: String? = nil, pushable: Bool = false) {
        self.id = id; self.productName = productName; self.measurements = measurements; self.notes = notes; self.location = location
        self.status = status; self.hubOrderNumber = hubOrderNumber; self.pushable = pushable
    }
    enum K: String, CodingKey { case id, product_name, measurements, notes, location, status, hub_order_number, pushable }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(id: c.string(.id, default: ""), productName: c.string(.product_name), measurements: c.value(.measurements)?.objectValue ?? [:],
                  notes: c.string(.notes), location: c.string(.location), status: c.string(.status, default: "new"),
                  hubOrderNumber: c.string(.hub_order_number), pushable: c.bool(.pushable, default: false))
    }
}

public struct EnquiryResponse: Equatable, Sendable, Decodable {
    public var enquiry: ProductionEnquiry?
    public init(enquiry: ProductionEnquiry? = nil) { self.enquiry = enquiry }
    enum K: String, CodingKey { case enquiry }
    public init(from decoder: Decoder) throws { self.init(enquiry: (try decoder.lenient(K.self)).object(.enquiry)) }
}

public struct PushResponse: Equatable, Sendable, Decodable {
    public var hubOrderNumber: String?
    /// push_production is idempotent: a second push answers `already: true` with the first order.
    public var already: Bool
    public init(hubOrderNumber: String? = nil, already: Bool = false) { self.hubOrderNumber = hubOrderNumber; self.already = already }
    enum K: String, CodingKey { case hub_order_number, already }
    public init(from decoder: Decoder) throws {
        let c = try decoder.lenient(K.self)
        self.init(hubOrderNumber: c.string(.hub_order_number), already: c.bool(.already, default: false))
    }
}

public enum Crm {
    static let sqlStyle = try! NSRegularExpression(pattern: #"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}"#)

    /// A SQL-style "2026-09-20 08:15:30" becomes ISO ("T"; a naive time is UTC); anything else is left as it came.
    public static func isoOf(_ raw: String?) -> String? {
        guard let s = raw?.trimmingCharacters(in: .whitespacesAndNewlines), !s.isEmpty else { return nil }
        guard sqlStyle.firstMatch(in: s, range: NSRange(s.startIndex..., in: s)) != nil else { return s }
        let date = String(s.prefix(10))
        let rest = String(s.dropFirst(11)).replacingOccurrences(of: " ", with: "")
        return date + "T" + rest
    }

    public static let CANONICAL_STAGES: Set<String> = ["new", "contacted", "qualified", "proposal", "negotiation", "won", "lost"]

    /// The profile's stage as the pipeline knows it: lower-cased canonicals; a custom label matched case-insensitively keeps the operator's spelling.
    public static func canonicalStage(_ stage: String?, customs: [String]) -> String {
        let s = (stage ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let v = s.isEmpty ? "new" : s
        let lower = v.lowercased()
        if lower == "negotiating" { return "negotiation" }
        if CANONICAL_STAGES.contains(lower) { return lower }
        return customs.first { $0.caseInsensitiveCompare(v) == .orderedSame } ?? v
    }

    /// Advance Stage: the next stop on the forward path (customs between Negotiating and Won); Lost re-opens at Won.
    public static func nextStage(_ current: String, customs: [String]) -> String {
        if current == "lost" { return "won" }
        let forward = ["new", "contacted", "qualified", "proposal", "negotiation"] + customs + ["won"]
        let idx = forward.firstIndex(of: current) ?? forward.firstIndex(of: "negotiation")!
        return forward[min(idx + 1, forward.count - 1)]
    }

    /// Dialable digits (7–15, E.164) of a phone — never a web-chat visitor's key.
    public static func realPhoneDigits(_ raw: String?) -> String? {
        let t = raw?.trimmingCharacters(in: .whitespaces)
        if Inbox.isWebVisitor(t) { return nil }
        let d = (raw ?? "").filter { $0.isASCII && $0.isNumber }
        return (7...15).contains(d.count) ? d : nil
    }

    /// A channel's display name (brand names everywhere; a web visitor's row says what it really is).
    public static func channelLabel(_ channel: String, identifier: String? = nil) -> String {
        if Inbox.isWebVisitor(identifier) { return "Web chat" }
        return ChannelMeta.label(channel)
    }

    /// The badge for a channel row: a web visitor gets the web badge, not WhatsApp's.
    public static func badgeKey(_ channel: String, identifier: String?) -> String { Inbox.isWebVisitor(identifier) ? "web" : channel }
}

/// The channel brand names (CH_META) and colours shared by every screen.
public enum ChannelMeta {
    public static func label(_ channel: String) -> String {
        switch channel.lowercased() {
        case "whatsapp": return "WhatsApp"
        case "messenger": return "Messenger"
        case "facebook": return "Facebook"
        case "instagram": return "Instagram"
        case "tiktok": return "TikTok"
        case "email": return "Email"
        case "sms": return "SMS"
        case "web", "web_chat", "webchat": return "Web chat"
        default: return channel.isEmpty ? "WhatsApp" : channel.prefix(1).uppercased() + channel.dropFirst()
        }
    }

    /// Hex colours: WhatsApp #25D366, Messenger #0084FF, Facebook #1877F2, Instagram #E1306C, TikTok #010101, Email #6366F1, SMS #64748B, Web #589B31.
    public static func colorHex(_ channel: String) -> UInt32 {
        switch channel.lowercased() {
        case "whatsapp": return 0x25D366
        case "messenger": return 0x0084FF
        case "facebook": return 0x1877F2
        case "instagram": return 0xE1306C
        case "tiktok": return 0x010101
        case "email": return 0x6366F1
        case "sms": return 0x64748B
        case "web", "web_chat", "webchat": return 0x589B31
        default: return 0x699A32
        }
    }

    /// The inbox's short chip names: WA · FB · MSG · IG · TT · Email · SMS.
    public static func short(_ channel: String) -> String {
        switch channel.lowercased() {
        case "whatsapp": return "WA"
        case "messenger": return "MSG"
        case "facebook": return "FB"
        case "instagram": return "IG"
        case "tiktok": return "TT"
        case "email": return "Email"
        case "sms": return "SMS"
        default: return channel.uppercased()
        }
    }
}

/// The CRM routes the web reaches through its own `crmReq` (not api.ts). Path segments are form-encoded (`+` for spaces), as Android's `CrmApi`.
public final class CrmApi {
    public let http: NeemaHTTP
    public init(http: NeemaHTTP) { self.http = http }

    private func enc(_ s: String) -> String { HTTPBody.formEncodeComponent(s) }
    private func ch(_ channel: String?) -> String { (channel ?? "").isEmpty ? "" : "?channel=\(enc(channel!))" }

    public func profile(key: String, channel: String?) async throws -> CustomerProfile {
        try await http.get("/admin/customers/\(enc(key))\(ch(channel))")
    }

    public func patch(key: String, channel: String?, body: JSONValue) async throws {
        _ = try await http.raw("PATCH", "/admin/customers/\(enc(key))\(ch(channel))", body: .json(body.text))
    }

    public func mergeSuggestions(key: String, channel: String?) async throws -> [MergeSuggestion] {
        (try await http.get("/admin/customers/\(enc(key))/merge_suggestions\(ch(channel))") as MergeSuggestionsResponse).suggestions
    }

    public func merge(key: String, channel: String?, target: String) async throws {
        _ = try await http.raw("POST", "/admin/customers/\(enc(key))/merge\(ch(channel))", body: .json(JSONValue.object(["merge_with": .string(target)]).text))
    }

    public func unmerge(key: String, channel: String?, target: String) async throws {
        _ = try await http.raw("POST", "/admin/customers/\(enc(key))/unmerge\(ch(channel))", body: .json(JSONValue.object(["merge_with": .string(target)]).text))
    }

    public func enquiry(conversationId: String) async throws -> ProductionEnquiry? {
        (try await http.get("/admin/production/conversation/\(enc(conversationId))") as EnquiryResponse).enquiry
    }

    public func pushProduction(enquiryId: String) async throws -> PushResponse {
        try await http.post("/admin/production/\(enc(enquiryId))/push", JSONValue.object([:]))
    }

    public func declineProduction(enquiryId: String) async throws {
        _ = try await http.raw("POST", "/admin/production/\(enc(enquiryId))/decline", body: .json("{}"))
    }
}
